#include "graphmine/runtime.hpp"

#include <openssl/sha.h>

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <sstream>

#include "catalog_data.hpp"
#include "internal.hpp"
#include "representation_cache.hpp"
#include "bipartite_input.hpp"

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
  for (const auto byte : digest)
    output << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(byte);
  return output.str();
}
void read_budget(const json::value& value, Work& work) {
  const auto budget = object(value, "budget");
  fields(budget, {"max_candidates", "max_output_items", "timeout_seconds"});
  if (budget.contains("max_candidates") && !budget.at("max_candidates").is_null())
    work.max_candidates = uint(budget.at("max_candidates"), "max_candidates");
  if (budget.contains("max_output_items") && !budget.at("max_output_items").is_null())
    work.max_output_items = uint(budget.at("max_output_items"), "max_output_items");
  if (budget.contains("timeout_seconds") && !budget.at("timeout_seconds").is_null())
    work.timeout_seconds = number(budget.at("timeout_seconds"), "timeout_seconds");
  require((!work.max_candidates || *work.max_candidates > 0) &&
              (!work.max_output_items || *work.max_output_items > 0) &&
              (!work.timeout_seconds || (std::isfinite(*work.timeout_seconds) && *work.timeout_seconds > 0)),
          "Budgets must be null for unlimited execution or finite and positive");
}
}  // namespace

std::string input_fingerprint(const json::value& input) { return hash(input); }

// Read-only preflight for telemetry and the agent's feasibility rules. All
// input restrictions remain owned by the same native support functions as run.
json::object backend_capabilities(const json::object& request) {
  fields(request,
         {"command", "problem", "graph", "parameters", "device", "backend", "gpu_device",
          "budget", "allowed_backends"},
         {"command", "problem", "graph"});
  const auto problem = string(request.at("problem"), "problem");
  const auto& card = problem_card(problem);
  const auto policy = request.contains("device") ? string(request.at("device"), "device") : "auto";
  require(policy == "cpu" || policy == "gpu" || policy == "auto", "Invalid device policy");
  const auto ordinal = request.contains("gpu_device") ? uint(request.at("gpu_device"), "gpu_device") : 0;
  require(ordinal <= INT32_MAX, "gpu_device is out of range");
  const auto requested = request.contains("backend") ? string(request.at("backend"), "backend") : "auto";
  std::vector<std::string> allowed;
  if (request.contains("allowed_backends")) {
    require(request.at("allowed_backends").is_array(), "allowed_backends must be an array");
    for (const auto& value : request.at("allowed_backends").as_array())
      allowed.push_back(string(value, "allowed backend"));
  }
  Work work;
  work.input_fingerprint = hash(request.at("graph"));
  if (request.contains("budget")) read_budget(request.at("budget"), work);
  auto parameters = request.contains("parameters") ? object(request.at("parameters"), "parameters") : json::object{};
  validate_parameters(card, parameters);
  std::shared_ptr<const Graph> graph;
  if (card.at("input_kind") == "graph") graph = cached_graph(request.at("graph"), work);
  else inspect_input(string(card.at("input_kind"), "input_kind"), request.at("graph"), work);
  work.input_graph = graph.get();
  if (problem == "maximal-bicliques")
    parameters = resolve_biclique_parameters(*graph, parameters);
  const auto gpu_reason = graph ? gpu_support_reason(problem, *graph, parameters)
                                : "This structured-input profile has a native CPU implementation";
  // CPU requests do not initialize CUDA, even when gathering telemetry.
  const bool available = policy != "cpu" && gpu_available(static_cast<int>(ordinal));
  json::array candidates;
  std::string selected;
  bool cpu_feasible = false;
  for (const auto& row : card.at("backends").as_array()) {
    const auto& backend = row.as_object();
    const auto id = string(backend.at("id"), "backend id");
    const bool cpu = backend.at("device") == "cpu";
    const bool compiled = backend.at("compiled").as_bool();
    const bool admitted = !request.contains("allowed_backends") ||
                          std::find(allowed.begin(), allowed.end(), id) != allowed.end();
    // Conservative preflight bounds in input units. GPU normalization can
    // symmetrize every edge, so reserve two signed-int32 arc indices per edge.
    // Individual adapters retain their more specific checks during execution.
    const std::uint64_t max_vertices = cpu ? UINT32_MAX - 1ULL :
        id == "ecl-maxflow" ? 1000000ULL : id == "hungarian-cuda" ? 128ULL : INT32_MAX - 1ULL;
    const std::uint64_t max_edges = cpu ? UINT64_MAX :
        id == "ecl-maxflow" ? 5000000ULL : (INT32_MAX - 1ULL) / 2;
    std::string reason;
    if (!compiled) reason = "not_compiled";
    else if (!admitted) reason = "not_admitted";
    else if ((policy == "cpu" && !cpu) || (policy == "gpu" && cpu)) reason = "device_policy";
    else if (graph && (graph->vertex_count() > max_vertices || graph->edge_count() > max_edges))
      reason = "size_or_index_limit";
    else if (!cpu && !gpu_reason.empty()) reason = gpu_reason;
    else if (!cpu && !available) reason = "gpu_unavailable";
    else if (graph) {
      try {
        // Comparing another candidate must not consume this one's work budget.
        auto candidate_work = work;
        candidate_work.started = std::chrono::steady_clock::now();
        reason = backend_support_reason(problem, id, *graph, parameters, candidate_work);
      } catch (const Failure& failure) {
        reason = failure.code;  // Avoid copying graph-specific error contents.
      }
    }
    const bool feasible = reason.empty();
    candidates.push_back(json::object{{"id", id}, {"device", cpu ? "cpu" : "gpu"},
                                      {"compiled", compiled}, {"admitted", admitted},
                                      {"feasible", feasible}, {"infeasible_reason", reason},
                                      {"limits", json::object{{"n", max_vertices}, {"m", max_edges}}}});
    if (id == "cpp") cpu_feasible = feasible;
    if (feasible && ((requested != "auto" && requested == id) ||
                     (requested == "auto" && !cpu && selected.empty()))) selected = id;
  }
  if (requested == "auto" && selected.empty() && cpu_feasible) selected = "cpp";
  return {{"problem", problem}, {"topic_id", card.at("topic_id")},
          {"family", card.at("family")}, {"input_kind", card.at("input_kind")},
          {"input_fingerprint", work.input_fingerprint}, {"candidates", candidates},
          {"legacy_backend", selected.empty() ? json::value(nullptr) : json::value(selected)},
          {"implementation_sha256", implementation_sha256}};
}

json::object execute(const json::object& request) {
  fields(request,
         {"command", "problem", "graph", "parameters", "device", "backend", "gpu_device",
          "budget", "allowed_backends"},
         {"command", "problem", "graph"});
  const auto problem = string(request.at("problem"), "problem");
  const auto& card = problem_card(problem);
  const auto policy = request.contains("device") ? string(request.at("device"), "device") : "auto";
  require(policy == "cpu" || policy == "gpu" || policy == "auto",
          "device must be cpu, gpu or auto");
  const auto ordinal =
      request.contains("gpu_device") ? uint(request.at("gpu_device"), "gpu_device") : 0;
  require(ordinal <= INT32_MAX, "gpu_device is out of range");
  const auto device = static_cast<int>(ordinal);
  std::string backend =
      request.contains("backend") ? string(request.at("backend"), "backend") : "auto";
  std::vector<std::string> allowed;
  if (request.contains("allowed_backends")) {
    require(request.at("allowed_backends").is_array(), "allowed_backends must be an array");
    for (const auto& value : request.at("allowed_backends").as_array())
      allowed.push_back(string(value, "allowed backend"));
    require(!allowed.empty(), "No verified backend was admitted for this problem");
  }
  const auto admitted = [&](const std::string& id) {
    return !request.contains("allowed_backends") ||
           std::find(allowed.begin(), allowed.end(), id) != allowed.end();
  };
  Work work;
  work.input_fingerprint = hash(request.at("graph"));
  if (request.contains("budget")) read_budget(request.at("budget"), work);
  const auto input_kind = string(card.at("input_kind"), "input_kind");
  std::shared_ptr<const Graph> graph;
  if (input_kind == "graph") graph = cached_graph(request.at("graph"), work);
  work.input_graph = graph.get();
  auto parameters = request.contains("parameters")
                              ? object(request.at("parameters"), "parameters")
                              : json::object{};
  validate_parameters(card, parameters);
  if (problem == "maximal-bicliques")
    parameters = resolve_biclique_parameters(*graph, parameters);
  const auto gpu_reason = graph ? gpu_support_reason(problem, *graph, parameters)
                                : "This structured-input profile has a native CPU implementation";
  std::string selection_reason = gpu_reason;
  bool compiled = false;
  if (backend == "auto") {
    backend = "cpp";
    if (policy != "cpu" && gpu_reason.empty()) {
      for (const auto& row : card.at("backends").as_array()) {
        const auto& candidate = row.as_object();
        if (candidate.at("device") == "gpu" && candidate.at("compiled").as_bool() &&
            gpu_available(device)) {
          const auto id = string(candidate.at("id"), "backend id");
          if (!admitted(id)) continue;
          const auto reason = backend_support_reason(problem, id, *graph, parameters, work);
          if (!reason.empty()) {
            selection_reason = reason;
            continue;
          }
          backend = id;
          break;
        }
      }
      if (policy == "gpu" && backend == "cpp")
        throw Failure(selection_reason.empty() ? "backend_unavailable" : "unsupported_input",
                      selection_reason.empty()
                          ? "No compiled GPU backend and usable device for " + problem
                          : selection_reason);
    }
  }
  if (policy == "gpu" && !gpu_reason.empty()) throw Failure("unsupported_input", gpu_reason);
  bool known = false;
  for (const auto& row : card.at("backends").as_array()) {
    const auto& candidate = row.as_object();
    if (candidate.at("id").as_string() == backend) {
      known = true;
      compiled = candidate.at("compiled").as_bool();
      break;
    }
  }
  require(known, "Backend is not declared for this native problem");
  require(admitted(backend), "Selected backend has no admitted correctness evidence");
  require(!((policy == "cpu" && backend != "cpp") || (policy == "gpu" && backend == "cpp")),
          "Backend conflicts with requested device policy");
  if (!compiled) throw Failure("backend_unavailable", "Selected native backend was not compiled");
  if (backend != "cpp" && !gpu_reason.empty()) throw Failure("unsupported_input", gpu_reason);
  const auto backend_reason =
      graph ? backend_support_reason(problem, backend, *graph, parameters, work) : std::string{};
  if (!backend_reason.empty()) throw Failure("unsupported_input", backend_reason);
  if (backend != "cpp" && !gpu_available(device))
    throw Failure("backend_unavailable", "Selected CUDA device is unavailable");
  std::optional<DeviceScope> device_scope;
  if (backend != "cpp") device_scope.emplace(device);
  auto result = graph ? (original_extension_backend(problem, backend)
                            ? original_extension_run(problem, *graph, parameters, backend, device, work)
                            : problem_handler(problem)(*graph, parameters, backend, device, work))
                      : input_problem_handler(problem)(request.at("graph"), parameters, work);
  work.tick(0);
  const auto& fingerprint = work.input_fingerprint;
  for (auto& port : result.at("ports").as_object()) {
    port.value().as_object()["input_fingerprint"] = fingerprint;
    auto& record = port.value().as_object();
    record["graph_fingerprint"] =
        record.at("type") == "graph" ? hash(record.at("value")) : fingerprint;
  }
  result["schema_version"] = "2.0.0";
  result["problem"] = problem;
  result["topic_id"] = card.at("topic_id");
  result["family"] = card.at("family");
  result["input_kind"] = input_kind;
  result["input_fingerprint"] = fingerprint;
  result["graph_fingerprint"] = fingerprint;
  result["implementation_sha256"] = implementation_sha256;
  result["requested_device"] = policy;
  json::object provenance{{"id", backend},
                          {"device", backend == "cpp" ? "cpu" : "gpu"},
                          {"implementation_language", "c++/cuda"},
                          {"python_runtime_required", false}};
  if (backend == "libcugraph") provenance["version"] = cugraph_version();
  if (backend != "cpp") provenance["hardware"] = gpu_description(device);
  if (policy == "auto" && backend == "cpp")
    provenance["selection_reason"] = selection_reason.empty()
                                         ? "Selected the compiled native CPU implementation"
                                         : selection_reason;
  result["backend"] = provenance;
  result["representations"] = work.representations;
  result["budget"] = json::object{{"max_candidates", work.max_candidates ? json::value(*work.max_candidates) : json::value(nullptr)},
                                  {"max_output_items", work.max_output_items ? json::value(*work.max_output_items) : json::value(nullptr)},
                                  {"timeout_seconds", work.timeout_seconds ? json::value(*work.timeout_seconds) : json::value(nullptr)}};
  result["elapsed_seconds"] =
      std::chrono::duration<double>(std::chrono::steady_clock::now() - work.started).count();
  return result;
}

int abi_version() noexcept { return 2; }
std::string request(std::string_view raw) {
  try {
    if (raw.size() > 64 * 1024 * 1024)
      throw Failure("resource_limit", "Native request exceeds 64 MiB");
    auto value = object(strict_json(raw), "request");
    // Read the former wire key only at the boundary; all responses use problem.
    if (value.contains("operation")) {
      require(!value.contains("problem") || value.at("problem") == value.at("operation"),
              "Conflicting problem and operation identifiers");
      value["problem"] = value.at("operation");
      value.erase("operation");
    }
    require(value.contains("command"), "Missing command");
    const auto command = string(value.at("command"), "command");
    if (command == "catalog") {
      fields(value, {"command"});
      return json::serialize(catalog());
    }
    if (command == "run") return json::serialize(execute(value));
    if (command == "backend_capabilities") return json::serialize(backend_capabilities(value));
    if (command == "validate") return json::serialize(validate_request(value));
    if (command == "representation_cache")
      return json::serialize(representation_cache_request(value));
    if (command == "inspect_input") {
      fields(value, {"command", "input_kind", "input"}, {"command", "input_kind", "input"});
      Work work;
      return json::serialize(
          inspect_input(string(value.at("input_kind"), "input_kind"), value.at("input"), work));
    }
    if (command == "read_csv") return json::serialize(read_csv(value));
    if (command == "read_graph") return json::serialize(read_graph_file(value));
    if (command == "project_graph") return json::serialize(project_tables(value));
    throw Failure("invalid_input", "Unknown native command");
  } catch (const Failure& failure) {
    return json::serialize(
        json::object{{"error", {{"code", failure.code}, {"message", failure.what()}}}});
  } catch (const std::bad_alloc&) {
    return "{\"error\":{\"code\":\"resource_limit\",\"message\":\"Native memory allocation "
           "failed\"}}";
  } catch (const std::exception& failure) {
    return json::serialize(
        json::object{{"error", {{"code", "invalid_input"}, {"message", failure.what()}}}});
  }
}
}  // namespace graphmine::runtime
