#include "graphmine/runtime.hpp"
#include "internal.hpp"
#include "catalog_data.hpp"

#include <openssl/sha.h>
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <sstream>

namespace graphmine::runtime {
namespace {
json::value sorted_json(const json::value& value) {
  if (value.is_array()) {
    json::array result;
    for (const auto& item : value.as_array()) result.push_back(sorted_json(item));
    return result;
  }
  if (!value.is_object()) return value;
  std::vector<std::string> keys;
  for (const auto& item : value.as_object()) keys.emplace_back(item.key());
  std::sort(keys.begin(), keys.end());
  json::object result;
  for (const auto& key : keys) result[key] = sorted_json(value.as_object().at(key));
  return result;
}
std::string hash(const json::value& value) {
  const auto raw = json::serialize(sorted_json(value));
  unsigned char digest[SHA256_DIGEST_LENGTH];
  SHA256(reinterpret_cast<const unsigned char*>(raw.data()), raw.size(), digest);
  std::ostringstream output;
  for (const auto byte : digest) output << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(byte);
  return output.str();
}
}

json::object execute(const json::object& request) {
  fields(request, {"command", "operation", "graph", "parameters", "device", "backend", "gpu_device", "budget"},
         {"command", "operation", "graph"});
  const auto operation = string(request.at("operation"), "operation");
  json::object card;
  for (const auto& value : operation_cards())
    if (value.as_object().at("id").as_string() == operation) card = value.as_object();
  if (card.empty()) throw Failure("unsupported_operation", "No native runtime integration for " + operation);
  const auto policy = request.contains("device") ? string(request.at("device"), "device") : "auto";
  require(policy == "cpu" || policy == "gpu" || policy == "auto", "device must be cpu, gpu or auto");
  const auto ordinal = request.contains("gpu_device") ? uint(request.at("gpu_device"), "gpu_device") : 0;
  require(ordinal <= INT32_MAX, "gpu_device is out of range");
  const auto device = static_cast<int>(ordinal);
  std::string backend = request.contains("backend") ? string(request.at("backend"), "backend") : "auto";
  bool compiled = false;
  if (backend == "auto") {
    backend = "cpp";
    if (policy != "cpu") {
      for (const auto& row : card.at("backends").as_array()) {
        const auto& candidate = row.as_object();
        if (candidate.at("device") == "gpu" && candidate.at("compiled").as_bool() && gpu_available(device)) {
          backend = string(candidate.at("id"), "backend id"); break;
        }
      }
      if (policy == "gpu" && backend == "cpp") throw Failure("backend_unavailable", "No compiled GPU backend and usable device for " + operation);
    }
  }
  bool known = false;
  for (const auto& row : card.at("backends").as_array()) {
    const auto& candidate = row.as_object();
    if (candidate.at("id").as_string() == backend) {
      known = true; compiled = candidate.at("compiled").as_bool(); break;
    }
  }
  require(known, "Backend is not declared for this native operation");
  require(!((policy == "cpu" && backend != "cpp") || (policy == "gpu" && backend == "cpp")), "Backend conflicts with requested device policy");
  if (!compiled) throw Failure("backend_unavailable", "Selected native backend was not compiled");
  if (backend != "cpp" && !gpu_available(device)) throw Failure("backend_unavailable", "Selected CUDA device is unavailable");
  std::optional<DeviceScope> device_scope;
  if (backend != "cpp") device_scope.emplace(device);
  Work work;
  if (request.contains("budget")) {
    const auto budget = object(request.at("budget"), "budget");
    fields(budget, {"max_candidates", "max_output_items", "timeout_seconds"});
    if (budget.contains("max_candidates")) work.max_candidates = uint(budget.at("max_candidates"), "max_candidates");
    if (budget.contains("max_output_items")) work.max_output_items = uint(budget.at("max_output_items"), "max_output_items");
    if (budget.contains("timeout_seconds")) {
      require(budget.at("timeout_seconds").is_number(), "timeout_seconds must be numeric");
      work.timeout_seconds = budget.at("timeout_seconds").to_number<double>();
    }
    require(work.max_candidates && work.max_output_items && std::isfinite(work.timeout_seconds) && work.timeout_seconds > 0, "Budgets must be finite and positive");
  }
  const auto graph = parse_graph(request.at("graph"));
  const auto parameters = request.contains("parameters") ? object(request.at("parameters"), "parameters") : json::object{};
  auto result = operation == "breadth-first-search" ? bfs(graph, parameters, backend, device, work) : triangles(graph, parameters, backend, device, work);
  work.tick(0);
  const auto fingerprint = hash(request.at("graph"));
  for (auto& port : result.at("ports").as_object()) {
    port.value().as_object()["input_fingerprint"] = fingerprint;
    port.value().as_object()["graph_fingerprint"] = fingerprint;
  }
  result["schema_version"] = "2.0.0";
  result["operation"] = operation;
  result["problem_id"] = card.at("problem_id");
  result["family"] = card.at("family");
  result["input_kind"] = "graph";
  result["input_fingerprint"] = fingerprint;
  result["graph_fingerprint"] = fingerprint;
  result["implementation_sha256"] = implementation_sha256;
  result["requested_device"] = policy;
  json::object provenance{{"id", backend}, {"device", backend == "cpp" ? "cpu" : "gpu"},
                          {"implementation_language", "c++/cuda"}, {"python_runtime_required", false}};
  if (backend == "libcugraph") provenance["version"] = cugraph_version();
  if (backend != "cpp") provenance["hardware"] = gpu_description(device);
  if (policy == "auto" && backend == "cpp") provenance["selection_reason"] = "Selected the compiled native CPU implementation";
  result["backend"] = provenance;
  result["budget"] = json::object{{"max_candidates", work.max_candidates}, {"max_output_items", work.max_output_items}, {"timeout_seconds", work.timeout_seconds}};
  result["elapsed_seconds"] = std::chrono::duration<double>(std::chrono::steady_clock::now() - work.started).count();
  return result;
}

int abi_version() noexcept { return 1; }
std::string request(std::string_view raw) {
  try {
    if (raw.size() > 64 * 1024 * 1024) throw Failure("resource_limit", "Native request exceeds 64 MiB");
    const auto value = object(json::parse(raw), "request");
    require(value.contains("command"), "Missing command");
    const auto command = string(value.at("command"), "command");
    if (command == "catalog") {
      fields(value, {"command"});
      return json::serialize(catalog());
    }
    if (command == "run") return json::serialize(execute(value));
    if (command == "read_csv") return json::serialize(read_csv(value));
    throw Failure("invalid_input", "Unknown native command");
  } catch (const Failure& failure) {
    return json::serialize(json::object{{"error", {{"code", failure.code}, {"message", failure.what()}}}});
  } catch (const std::bad_alloc&) {
    return "{\"error\":{\"code\":\"resource_limit\",\"message\":\"Native memory allocation failed\"}}";
  } catch (const std::exception& failure) {
    return json::serialize(json::object{{"error", {{"code", "invalid_input"}, {"message", failure.what()}}}});
  }
}
}  // namespace graphmine::runtime
