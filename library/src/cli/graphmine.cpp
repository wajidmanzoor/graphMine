#include "graphmine/problems/validated_expansion.hpp"
#include <boost/json/src.hpp>

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

#include <fcntl.h>
#include <unistd.h>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"
#include "graphmine/problems/betweenness_centrality.hpp"
#include "graphmine/problems/community_detection.hpp"
#include "graphmine/problems/dynamic_triangle_counting.hpp"
#include "graphmine/problems/graph_motifs.hpp"
#include "graphmine/problems/k_cliques.hpp"
#include "graphmine/problems/k_core.hpp"
#include "graphmine/problems/maximal_bicliques.hpp"
#include "graphmine/problems/maximal_cliques.hpp"
#include "graphmine/problems/maximum_clique.hpp"
#include "graphmine/problems/quasi_cliques.hpp"
#include "graphmine/problems/subgraph_isomorphism.hpp"
#include "graphmine/problems/temporal_motif_mining.hpp"
#include "graphmine/problems/triangle_counting.hpp"

#ifndef GRAPHMINE_VERSION
#define GRAPHMINE_VERSION "unknown"
#endif

namespace json = boost::json;

namespace {

using graphmine::ExternalId;

class UsageError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

class ScopedBackendOutputSilence {
 public:
  ScopedBackendOutputSilence() {
    std::cout.flush();
    std::cerr.flush();
    std::fflush(stdout);
    std::fflush(stderr);
    saved_stdout_ = ::dup(STDOUT_FILENO);
    saved_stderr_ = ::dup(STDERR_FILENO);
    const int null_output = ::open("/dev/null", O_WRONLY);
    if (saved_stdout_ < 0 || saved_stderr_ < 0 || null_output < 0 ||
        ::dup2(null_output, STDOUT_FILENO) < 0 ||
        ::dup2(null_output, STDERR_FILENO) < 0) {
      if (null_output >= 0) ::close(null_output);
      restore();
      throw std::runtime_error("could not isolate backend process output");
    }
    ::close(null_output);
  }

  ScopedBackendOutputSilence(const ScopedBackendOutputSilence&) = delete;
  ScopedBackendOutputSilence& operator=(const ScopedBackendOutputSilence&) =
      delete;

  ~ScopedBackendOutputSilence() {
    std::cout.flush();
    std::cerr.flush();
    std::fflush(stdout);
    std::fflush(stderr);
    restore();
  }

 private:
  void restore() noexcept {
    if (saved_stdout_ >= 0) {
      ::dup2(saved_stdout_, STDOUT_FILENO);
      ::close(saved_stdout_);
      saved_stdout_ = -1;
    }
    if (saved_stderr_ >= 0) {
      ::dup2(saved_stderr_, STDERR_FILENO);
      ::close(saved_stderr_);
      saved_stderr_ = -1;
    }
  }

  int saved_stdout_ = -1;
  int saved_stderr_ = -1;
};

template <typename Callable>
auto invoke_backend(Callable&& callable) -> decltype(callable()) {
  ScopedBackendOutputSilence silence;
  return callable();
}

std::string read_text(const std::string& path) {
  std::ostringstream buffer;
  if (path == "-") {
    buffer << std::cin.rdbuf();
    if (std::cin.bad()) {
      throw UsageError("failed to read JSON from standard input");
    }
    return buffer.str();
  }

  std::ifstream input(path);
  if (!input) {
    throw UsageError("could not open JSON input: " + path);
  }
  buffer << input.rdbuf();
  if (input.bad()) {
    throw UsageError("failed while reading JSON input: " + path);
  }
  return buffer.str();
}

json::value read_json(const std::string& path) {
  const auto text = read_text(path);
  boost::system::error_code error;
  auto value = json::parse(text, error);
  if (error) {
    throw UsageError("invalid JSON in " + path + ": " + error.message());
  }
  return value;
}

const json::object& require_object(const json::value& value,
                                   std::string_view context) {
  if (!value.is_object()) {
    throw UsageError(std::string(context) + " must be a JSON object");
  }
  return value.as_object();
}

const json::array& require_array(const json::value& value,
                                 std::string_view context) {
  if (!value.is_array()) {
    throw UsageError(std::string(context) + " must be a JSON array");
  }
  return value.as_array();
}

const json::value& require_field(const json::object& object,
                                 std::string_view name,
                                 std::string_view context) {
  const auto* value = object.if_contains(name);
  if (value == nullptr) {
    throw UsageError(std::string(context) + " is missing required field '" +
                     std::string(name) + "'");
  }
  return *value;
}

std::string require_string(const json::value& value,
                           std::string_view context) {
  if (!value.is_string()) {
    throw UsageError(std::string(context) + " must be a string");
  }
  return std::string(value.as_string());
}

bool require_bool(const json::value& value, std::string_view context) {
  if (!value.is_bool()) {
    throw UsageError(std::string(context) + " must be a boolean");
  }
  return value.as_bool();
}

std::int64_t require_int64(const json::value& value,
                           std::string_view context) {
  if (value.is_int64()) return value.as_int64();
  if (value.is_uint64() &&
      value.as_uint64() <=
          static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())) {
    return static_cast<std::int64_t>(value.as_uint64());
  }
  throw UsageError(std::string(context) + " must be a signed 64-bit integer");
}

double require_number(const json::value& value, std::string_view context) {
  if (value.is_double()) return value.as_double();
  if (value.is_int64()) return static_cast<double>(value.as_int64());
  if (value.is_uint64()) return static_cast<double>(value.as_uint64());
  throw UsageError(std::string(context) + " must be a number");
}

void reject_unknown_fields(const json::object& object,
                           std::initializer_list<std::string_view> allowed,
                           std::string_view context) {
  for (const auto& member : object) {
    const auto known =
        std::find(allowed.begin(), allowed.end(), member.key()) != allowed.end();
    if (!known) {
      throw UsageError(std::string(context) + " contains unknown field '" +
                       std::string(member.key()) + "'");
    }
  }
}

ExternalId parse_external_id(const json::value& value,
                             std::string_view context) {
  if (value.is_string()) {
    if (value.as_string().empty()) {
      throw UsageError(std::string(context) + " must not be an empty string");
    }
    return ExternalId(std::string(value.as_string()));
  }
  return ExternalId(require_int64(value, context));
}

graphmine::PropertyValue parse_property(const json::value& value,
                                        std::string_view context) {
  if (value.is_null()) return graphmine::PropertyValue(nullptr);
  if (value.is_bool()) return graphmine::PropertyValue(value.as_bool());
  if (value.is_int64()) return graphmine::PropertyValue(value.as_int64());
  if (value.is_uint64()) {
    if (value.as_uint64() >
        static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())) {
      throw UsageError(std::string(context) +
                       " contains an integer larger than int64");
    }
    return graphmine::PropertyValue(
        static_cast<std::int64_t>(value.as_uint64()));
  }
  if (value.is_double()) return graphmine::PropertyValue(value.as_double());
  if (value.is_string()) {
    return graphmine::PropertyValue(std::string(value.as_string()));
  }
  if (value.is_array()) {
    graphmine::PropertyValue::Array result;
    result.reserve(value.as_array().size());
    for (const auto& element : value.as_array()) {
      result.push_back(parse_property(element, context));
    }
    return graphmine::PropertyValue(std::move(result));
  }
  graphmine::PropertyValue::Object result;
  for (const auto& member : value.as_object()) {
    result.emplace(std::string(member.key()),
                   parse_property(member.value(), context));
  }
  return graphmine::PropertyValue(std::move(result));
}

graphmine::Attributes parse_attributes(const json::object& object,
                                       std::string_view context) {
  const auto* value = object.if_contains("attributes");
  if (value == nullptr) return {};
  const auto& attributes = require_object(*value, context);
  graphmine::Attributes result;
  for (const auto& member : attributes) {
    result.emplace(std::string(member.key()),
                   parse_property(member.value(), context));
  }
  return result;
}

graphmine::Graph parse_graph(const json::value& value,
                             std::string_view source_name) {
  const auto& root = require_object(value, source_name);
  reject_unknown_fields(root, {"graph", "vertices", "edges"}, source_name);

  graphmine::CanonicalGraphInput input;
  const auto& descriptor = require_object(
      require_field(root, "graph", source_name), "graph");
  reject_unknown_fields(descriptor,
                        {"id", "directed", "allows_self_loops",
                         "allows_parallel_edges", "attributes"},
                        "graph");
  input.graph.id = require_string(require_field(descriptor, "id", "graph"),
                                  "graph.id");
  input.graph.directed = require_bool(
      require_field(descriptor, "directed", "graph"), "graph.directed");
  input.graph.allows_self_loops = require_bool(
      require_field(descriptor, "allows_self_loops", "graph"),
      "graph.allows_self_loops");
  input.graph.allows_parallel_edges = require_bool(
      require_field(descriptor, "allows_parallel_edges", "graph"),
      "graph.allows_parallel_edges");
  input.graph.attributes = parse_attributes(descriptor, "graph.attributes");

  const auto& vertices = require_array(
      require_field(root, "vertices", source_name), "vertices");
  input.vertices.reserve(vertices.size());
  for (std::size_t index = 0; index < vertices.size(); ++index) {
    const auto context = "vertices[" + std::to_string(index) + "]";
    const auto& vertex = require_object(vertices[index], context);
    reject_unknown_fields(vertex, {"id", "label", "type", "attributes"},
                          context);
    graphmine::VertexRecord record;
    record.id =
        parse_external_id(require_field(vertex, "id", context), context + ".id");
    if (const auto* label = vertex.if_contains("label")) {
      record.label = require_string(*label, context + ".label");
    }
    if (const auto* type = vertex.if_contains("type")) {
      record.type = require_string(*type, context + ".type");
    }
    record.attributes = parse_attributes(vertex, context + ".attributes");
    input.vertices.push_back(std::move(record));
  }

  const auto& edges =
      require_array(require_field(root, "edges", source_name), "edges");
  input.edges.reserve(edges.size());
  for (std::size_t index = 0; index < edges.size(); ++index) {
    const auto context = "edges[" + std::to_string(index) + "]";
    const auto& edge = require_object(edges[index], context);
    reject_unknown_fields(edge,
                          {"id", "source", "target", "weight", "timestamp",
                           "type", "attributes"},
                          context);
    graphmine::EdgeRecord record;
    record.id =
        parse_external_id(require_field(edge, "id", context), context + ".id");
    record.source = parse_external_id(
        require_field(edge, "source", context), context + ".source");
    record.target = parse_external_id(
        require_field(edge, "target", context), context + ".target");
    if (const auto* weight = edge.if_contains("weight")) {
      record.weight = require_number(*weight, context + ".weight");
      if (!std::isfinite(*record.weight)) {
        throw UsageError(context + ".weight must be finite");
      }
    }
    if (const auto* timestamp = edge.if_contains("timestamp")) {
      if (timestamp->is_string()) {
        record.timestamp = std::string(timestamp->as_string());
      } else {
        record.timestamp = require_int64(*timestamp, context + ".timestamp");
      }
    }
    if (const auto* type = edge.if_contains("type")) {
      record.type = require_string(*type, context + ".type");
    }
    record.attributes = parse_attributes(edge, context + ".attributes");
    input.edges.push_back(std::move(record));
  }

  try {
    return graphmine::Graph(std::move(input));
  } catch (const std::exception& error) {
    throw UsageError(std::string(source_name) + ": " + error.what());
  }
}

graphmine::Graph read_graph(const std::string& path) {
  return parse_graph(read_json(path), path);
}

json::value id_json(const ExternalId& id) {
  if (std::holds_alternative<std::int64_t>(id.value())) {
    return std::get<std::int64_t>(id.value());
  }
  return json::value(std::get<std::string>(id.value()));
}

json::array ids_json(const std::vector<ExternalId>& ids) {
  json::array result;
  result.reserve(ids.size());
  for (const auto& id : ids) result.push_back(id_json(id));
  return result;
}

json::array sets_json(const std::vector<std::vector<ExternalId>>& sets) {
  json::array result;
  result.reserve(sets.size());
  for (const auto& set : sets) result.push_back(ids_json(set));
  return result;
}

std::string status_code_name(graphmine::StatusCode code) {
  switch (code) {
    case graphmine::StatusCode::ok:
      return "ok";
    case graphmine::StatusCode::invalid_argument:
      return "invalid_argument";
    case graphmine::StatusCode::unsupported:
      return "unsupported";
    case graphmine::StatusCode::backend_unavailable:
      return "backend_unavailable";
    case graphmine::StatusCode::execution_failed:
      return "execution_failed";
    case graphmine::StatusCode::correctness_mismatch:
      return "correctness_mismatch";
    case graphmine::StatusCode::resource_exhausted:
      return "resource_exhausted";
    case graphmine::StatusCode::internal_error:
      return "internal_error";
  }
  return "unknown";
}

json::object provenance_json(const graphmine::Provenance& provenance) {
  return {{"problem", provenance.problem},
          {"backend", provenance.backend},
          {"backend_version", provenance.backend_version},
          {"source_commit", provenance.source_commit},
          {"execution_path", provenance.execution_path}};
}

json::object statistics_json(const graphmine::ExecutionStatistics& statistics) {
  json::object result{{"end_to_end_ms", statistics.end_to_end_ms},
                      {"backend_ms", statistics.backend_ms},
                      {"output_materialization_ms",
                       statistics.output_materialization_ms}};
  if (statistics.peak_gpu_bytes) {
    result["peak_gpu_bytes"] = *statistics.peak_gpu_bytes;
  }
  return result;
}

template <typename Output, typename Serialize>
json::object result_json(const graphmine::ExecutionResult<Output>& result,
                         bool include_statistics, Serialize serialize) {
  json::object root;
  root["ok"] = result.ok();
  root["provenance"] = provenance_json(result.provenance());
  json::array warnings;
  for (const auto& warning : result.warnings()) {
    warnings.push_back(json::value(warning));
  }
  root["warnings"] = std::move(warnings);
  if (!result.ok()) {
    root["error"] = json::object{
        {"code", status_code_name(result.status().code())},
        {"message", result.status().message()}};
    return root;
  }
  if (include_statistics) {
    root["statistics"] = statistics_json(result.statistics());
  }
  root["output"] = serialize(result.value());
  return root;
}

void write_indent(std::ostream& output, unsigned count) {
  for (unsigned i = 0; i < count; ++i) output.put(' ');
}

void write_pretty(std::ostream& output, const json::value& value,
                  unsigned indent = 0) {
  if (value.is_array()) {
    const auto& array = value.as_array();
    if (array.empty()) {
      output << "[]";
      return;
    }
    output << "[\n";
    for (std::size_t i = 0; i < array.size(); ++i) {
      write_indent(output, indent + 2);
      write_pretty(output, array[i], indent + 2);
      output << (i + 1 == array.size() ? "\n" : ",\n");
    }
    write_indent(output, indent);
    output << ']';
    return;
  }
  if (value.is_object()) {
    const auto& object = value.as_object();
    if (object.empty()) {
      output << "{}";
      return;
    }
    output << "{\n";
    std::size_t index = 0;
    for (const auto& member : object) {
      write_indent(output, indent + 2);
      output << json::serialize(member.key()) << ": ";
      write_pretty(output, member.value(), indent + 2);
      output << (++index == object.size() ? "\n" : ",\n");
    }
    write_indent(output, indent);
    output << '}';
    return;
  }
  output << json::serialize(value);
}

void emit_json(const json::value& value, const std::optional<std::string>& path,
               bool pretty) {
  std::ofstream file;
  std::ostream* output = &std::cout;
  if (path && *path != "-") {
    file.open(*path);
    if (!file) throw UsageError("could not open output file: " + *path);
    output = &file;
  }
  if (pretty) {
    write_pretty(*output, value);
  } else {
    *output << json::serialize(value);
  }
  *output << '\n';
  if (!*output) throw UsageError("failed while writing JSON output");
}

class Arguments {
 public:
  Arguments(int argc, char** argv, int first) {
    for (int i = first; i < argc; ++i) {
      std::string token(argv[i]);
      if (token.rfind("--", 0) != 0 || token.size() == 2) {
        throw UsageError("unexpected positional argument: " + token);
      }
      token.erase(0, 2);
      std::optional<std::string> value;
      const auto equals = token.find('=');
      if (equals != std::string::npos) {
        value = token.substr(equals + 1);
        token.resize(equals);
      } else if (i + 1 < argc &&
                 std::string_view(argv[i + 1]).rfind("--", 0) != 0) {
        value = std::string(argv[++i]);
      }
      entries_.push_back({std::move(token), std::move(value), false});
    }
  }

  bool flag(std::string_view name) {
    auto matches = find(name);
    if (matches.size() > 1) {
      throw UsageError("--" + std::string(name) + " may be specified once");
    }
    if (matches.empty()) return false;
    auto& entry = entries_[matches.front()];
    entry.consumed = true;
    if (entry.value) {
      throw UsageError("--" + std::string(name) + " is a flag and takes no value");
    }
    return true;
  }

  std::optional<std::string> optional(std::string_view name) {
    auto matches = find(name);
    if (matches.size() > 1) {
      throw UsageError("--" + std::string(name) + " may be specified once");
    }
    if (matches.empty()) return std::nullopt;
    auto& entry = entries_[matches.front()];
    entry.consumed = true;
    if (!entry.value) {
      throw UsageError("--" + std::string(name) + " requires a value");
    }
    return entry.value;
  }

  std::string required(std::string_view name) {
    auto value = optional(name);
    if (!value) {
      throw UsageError("missing required option --" + std::string(name));
    }
    return *value;
  }

  std::vector<std::string> multiple(std::string_view name) {
    std::vector<std::string> result;
    for (auto index : find(name)) {
      auto& entry = entries_[index];
      entry.consumed = true;
      if (!entry.value) {
        throw UsageError("--" + std::string(name) + " requires a value");
      }
      result.push_back(*entry.value);
    }
    return result;
  }

  void finish() const {
    for (const auto& entry : entries_) {
      if (!entry.consumed) {
        throw UsageError("unknown option --" + entry.name);
      }
    }
  }

 private:
  struct Entry {
    std::string name;
    std::optional<std::string> value;
    bool consumed;
  };

  std::vector<std::size_t> find(std::string_view name) const {
    std::vector<std::size_t> result;
    for (std::size_t i = 0; i < entries_.size(); ++i) {
      if (entries_[i].name == name) result.push_back(i);
    }
    return result;
  }

  std::vector<Entry> entries_;
};

template <typename Integer>
Integer parse_integer(const std::string& text, std::string_view option,
                      Integer minimum = std::numeric_limits<Integer>::min()) {
  Integer result{};
  const auto parsed =
      std::from_chars(text.data(), text.data() + text.size(), result);
  if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size() ||
      result < minimum) {
    throw UsageError("invalid value for --" + std::string(option) + ": " +
                     text);
  }
  return result;
}

double parse_double(const std::string& text, std::string_view option) {
  char* end = nullptr;
  const auto value = std::strtod(text.c_str(), &end);
  if (end != text.c_str() + text.size() || !std::isfinite(value)) {
    throw UsageError("invalid value for --" + std::string(option) + ": " +
                     text);
  }
  return value;
}

std::string normalized_name(std::string name) {
  std::replace(name.begin(), name.end(), '_', '-');
  return name;
}

struct CommonOptions {
  std::string graph_path;
  std::string backend = "auto";
  bool allow_directed_projection = false;
  graphmine::ExecutionOptions execution;
  std::optional<std::string> output_path;
  bool pretty = false;
};

std::vector<int> parse_devices(const std::string& text) {
  std::vector<int> result;
  std::size_t start = 0;
  while (start <= text.size()) {
    const auto comma = text.find(',', start);
    const auto part = text.substr(start, comma - start);
    if (part.empty()) throw UsageError("--device contains an empty device id");
    result.push_back(parse_integer<int>(part, "device", 0));
    if (comma == std::string::npos) break;
    start = comma + 1;
  }
  if (result.empty()) throw UsageError("--device requires at least one id");
  return result;
}

CommonOptions parse_common(Arguments& arguments) {
  CommonOptions result;
  result.graph_path = arguments.required("graph");
  if (auto backend = arguments.optional("backend")) {
    result.backend = normalized_name(*backend);
  }
  result.allow_directed_projection =
      arguments.flag("allow-directed-projection");
  if (auto devices = arguments.optional("device")) {
    result.execution.device_ids = parse_devices(*devices);
  }
  result.execution.collect_statistics = !arguments.flag("no-statistics");
  result.output_path = arguments.optional("output");
  result.pretty = arguments.flag("pretty");
  return result;
}

std::optional<std::uint64_t> parse_limit(Arguments& arguments,
                                         std::string_view option =
                                             "result-limit") {
  auto value = arguments.optional(option);
  if (!value) return std::nullopt;
  return parse_integer<std::uint64_t>(*value, option, 1);
}

template <typename Enum>
Enum parse_backend(const std::string& value,
                   std::initializer_list<std::pair<std::string_view, Enum>>
                       choices) {
  for (const auto& [name, backend] : choices) {
    if (value == name) return backend;
  }
  std::string expected;
  for (const auto& [name, unused] : choices) {
    (void)unused;
    if (!expected.empty()) expected += ", ";
    expected += name;
  }
  throw UsageError("unknown backend '" + value + "'; expected one of: " +
                   expected);
}

std::vector<ExternalId> read_id_array(const std::string& path,
                                      std::string_view field) {
  const auto value = read_json(path);
  const json::array* source = nullptr;
  if (value.is_array()) {
    source = &value.as_array();
  } else {
    const auto& object = require_object(value, path);
    source = &require_array(require_field(object, field, path), field);
  }
  std::vector<ExternalId> result;
  result.reserve(source->size());
  for (std::size_t i = 0; i < source->size(); ++i) {
    result.push_back(parse_external_id(
        (*source)[i], std::string(field) + "[" + std::to_string(i) + "]"));
  }
  return result;
}

std::vector<graphmine::TriangleUpdate> read_updates(const std::string& path) {
  const auto value = read_json(path);
  const json::array* source = nullptr;
  if (value.is_array()) {
    source = &value.as_array();
  } else {
    const auto& object = require_object(value, path);
    source = &require_array(require_field(object, "updates", path), "updates");
  }
  std::vector<graphmine::TriangleUpdate> result;
  result.reserve(source->size());
  for (std::size_t i = 0; i < source->size(); ++i) {
    const auto context = "updates[" + std::to_string(i) + "]";
    const auto& update = require_object((*source)[i], context);
    reject_unknown_fields(update, {"kind", "source", "target"}, context);
    const auto kind = normalized_name(require_string(
        require_field(update, "kind", context), context + ".kind"));
    graphmine::TriangleUpdate record;
    if (kind == "insert-edge" || kind == "insert") {
      record.kind = graphmine::TriangleUpdateKind::insert_edge;
    } else if (kind == "delete-edge" || kind == "delete") {
      record.kind = graphmine::TriangleUpdateKind::delete_edge;
    } else {
      throw UsageError(context +
                       ".kind must be insert_edge or delete_edge");
    }
    record.source = parse_external_id(
        require_field(update, "source", context), context + ".source");
    record.target = parse_external_id(
        require_field(update, "target", context), context + ".target");
    result.push_back(std::move(record));
  }
  return result;
}

json::object maximal_clique_output(
    const graphmine::MaximalCliqueOutput& output) {
  json::object result{{"cliques", sets_json(output.cliques)},
                      {"returned_count", output.returned_count},
                      {"complete", output.complete}};
  if (output.total_count) result["total_count"] = *output.total_count;
  return result;
}

json::object maximum_clique_output(
    const graphmine::MaximumCliqueOutput& output) {
  json::object result{{"maximum_size", output.maximum_size},
                      {"cliques", sets_json(output.cliques)},
                      {"optimal", output.optimal}};
  if (output.upper_bound) result["upper_bound"] = *output.upper_bound;
  return result;
}

json::object k_core_output(const graphmine::KCoreOutput& output) {
  json::array core_numbers;
  for (const auto& entry : output.core_number_by_vertex) {
    core_numbers.push_back(json::object{{"vertex", id_json(entry.vertex)},
                                        {"core_number", entry.core_number}});
  }
  json::object result{{"core_number_by_vertex", std::move(core_numbers)},
                      {"degeneracy", output.degeneracy}};
  if (output.requested_core_vertices) {
    result["requested_core_vertices"] =
        ids_json(*output.requested_core_vertices);
  }
  if (output.requested_core_edges) {
    result["requested_core_edges"] = ids_json(*output.requested_core_edges);
  }
  if (output.peeling_order) {
    result["peeling_order"] = ids_json(*output.peeling_order);
  }
  return result;
}

json::object triangle_output(const graphmine::TriangleOutput& output) {
  json::object result{{"global_triangle_count", output.global_triangle_count},
                      {"instances_complete", output.instances_complete}};
  if (output.triangles) result["triangles"] = sets_json(*output.triangles);
  if (output.per_vertex_count) {
    json::array values;
    for (const auto& entry : *output.per_vertex_count) {
      values.push_back(json::object{{"vertex", id_json(entry.vertex)},
                                    {"count", entry.count}});
    }
    result["per_vertex_count"] = std::move(values);
  }
  if (output.per_edge_count) {
    json::array values;
    for (const auto& entry : *output.per_edge_count) {
      values.push_back(json::object{{"edge", id_json(entry.edge)},
                                    {"count", entry.count}});
    }
    result["per_edge_count"] = std::move(values);
  }
  return result;
}

json::object dynamic_triangle_output(
    const graphmine::DynamicTriangleOutput& output) {
  json::object result{{"deleted_triangle_count", output.deleted_triangle_count},
                      {"inserted_triangle_count",
                       output.inserted_triangle_count},
                      {"net_triangle_change", output.net_triangle_change},
                      {"changed_instances_complete",
                       output.changed_instances_complete}};
  if (output.initial_global_triangle_count) {
    result["initial_global_triangle_count"] =
        *output.initial_global_triangle_count;
  }
  if (output.final_global_triangle_count) {
    result["final_global_triangle_count"] =
        *output.final_global_triangle_count;
  }
  if (output.deleted_triangles) {
    result["deleted_triangles"] = sets_json(*output.deleted_triangles);
  }
  if (output.inserted_triangles) {
    result["inserted_triangles"] = sets_json(*output.inserted_triangles);
  }
  return result;
}

json::object k_clique_output(const graphmine::KCliqueOutput& output) {
  json::object result{{"count", output.count}, {"complete", output.complete}};
  if (output.cliques) result["cliques"] = sets_json(*output.cliques);
  if (output.per_vertex_count) {
    json::array values;
    for (const auto& entry : *output.per_vertex_count) {
      values.push_back(json::object{{"vertex", id_json(entry.vertex)},
                                    {"count", entry.count}});
    }
    result["per_vertex_count"] = std::move(values);
  }
  return result;
}

json::array centrality_scores_json(
    const std::vector<graphmine::VertexCentralityScore>& scores) {
  json::array result;
  for (const auto& entry : scores) {
    result.push_back(json::object{{"vertex", id_json(entry.vertex)},
                                  {"score", entry.score}});
  }
  return result;
}

json::object centrality_output(
    const graphmine::BetweennessCentralityOutput& output) {
  json::object result{
      {"score_by_vertex", centrality_scores_json(output.score_by_vertex)}};
  if (output.normalized_score_by_vertex) {
    result["normalized_score_by_vertex"] =
        centrality_scores_json(*output.normalized_score_by_vertex);
  }
  if (output.ranking) {
    result["ranking"] = centrality_scores_json(*output.ranking);
  }
  if (output.maximum) {
    result["maximum"] =
        json::object{{"vertex", id_json(output.maximum->vertex)},
                     {"score", output.maximum->score}};
  }
  return result;
}

json::object maximal_biclique_output(
    const graphmine::MaximalBicliqueOutput& output) {
  json::array bicliques;
  for (const auto& biclique : output.bicliques) {
    bicliques.push_back(json::object{{"left", ids_json(biclique.left)},
                                     {"right", ids_json(biclique.right)}});
  }
  json::object result{{"bicliques", std::move(bicliques)},
                      {"returned_count", output.returned_count},
                      {"complete", output.complete}};
  if (output.total_count) result["total_count"] = *output.total_count;
  return result;
}

json::object quasi_clique_output(const graphmine::QuasiCliqueOutput& output) {
  json::object result{{"quasi_cliques", sets_json(output.quasi_cliques)},
                      {"returned_count", output.returned_count},
                      {"complete", output.complete}};
  if (output.total_count) result["total_count"] = *output.total_count;
  return result;
}

json::object subgraph_output(
    const graphmine::SubgraphIsomorphismOutput& output) {
  json::object result{{"count", output.count},
                      {"embeddings_complete", output.embeddings_complete}};
  if (output.embeddings) {
    json::array embeddings;
    for (const auto& embedding : *output.embeddings) {
      json::array mappings;
      for (const auto& mapping : embedding) {
        mappings.push_back(
            json::object{{"query_vertex", id_json(mapping.query_vertex)},
                         {"data_vertex", id_json(mapping.data_vertex)}});
      }
      embeddings.push_back(std::move(mappings));
    }
    result["embeddings"] = std::move(embeddings);
  }
  return result;
}

json::object motif_output(const graphmine::GraphMotifOutput& output) {
  json::array motifs;
  for (const auto& motif : output.motifs) {
    json::object item{{"motif_id", motif.motif_id},
                      {"count", motif.count},
                      {"instances_complete", motif.instances_complete}};
    if (motif.instances) {
      json::array instances;
      for (const auto& instance : *motif.instances) {
        json::array mappings;
        for (const auto& mapping : instance) {
          mappings.push_back(
              json::object{{"motif_vertex", id_json(mapping.motif_vertex)},
                           {"data_vertex", id_json(mapping.data_vertex)}});
        }
        instances.push_back(std::move(mappings));
      }
      item["instances"] = std::move(instances);
    }
    if (motif.per_vertex_participation) {
      json::array participation;
      for (const auto& entry : *motif.per_vertex_participation) {
        participation.push_back(
            json::object{{"vertex", id_json(entry.vertex)},
                         {"count", entry.count}});
      }
      item["per_vertex_participation"] = std::move(participation);
    }
    motifs.push_back(std::move(item));
  }
  return {{"motifs", std::move(motifs)}};
}

json::object temporal_output(const graphmine::TemporalMotifOutput& output) {
  json::object result{{"count", output.count},
                      {"instances_complete", output.instances_complete}};
  if (output.instances) {
    json::array instances;
    for (const auto& instance : *output.instances) {
      json::array vertices;
      for (const auto& vertex : instance.vertices_by_role) {
        vertices.push_back(id_json(vertex));
      }
      json::array edges;
      for (const auto& edge : instance.edges_in_temporal_order) {
        edges.push_back(id_json(edge));
      }
      instances.push_back(
          json::object{{"vertices_by_role", std::move(vertices)},
                       {"edges_in_temporal_order", std::move(edges)}});
    }
    result["instances"] = std::move(instances);
  }
  return result;
}

json::object community_output(
    const graphmine::CommunityDetectionOutput& output) {
  json::array assignments;
  for (const auto& assignment : output.assignment_by_vertex) {
    assignments.push_back(
        json::object{{"vertex", id_json(assignment.vertex)},
                     {"community", assignment.community}});
  }
  json::object result{{"assignment_by_vertex", std::move(assignments)},
                      {"community_count", output.community_count},
                      {"modularity", output.modularity}};
  if (output.communities) {
    json::array communities;
    for (const auto& community : *output.communities) {
      communities.push_back(json::object{{"id", community.id},
                                          {"vertices",
                                           ids_json(community.vertices)}});
    }
    result["communities"] = std::move(communities);
  }
  if (output.edge_cut) result["edge_cut"] = *output.edge_cut;
  return result;
}

json::object run_maximal_cliques(Arguments& arguments,
                                 const CommonOptions& common) {
  graphmine::MaximalCliqueOptions options;
  options.backend = parse_backend<graphmine::MaximalCliqueBackend>(
      common.backend,
      {{"auto", graphmine::MaximalCliqueBackend::automatic},
       {"mce-gpu", graphmine::MaximalCliqueBackend::mce_gpu},
       {"g2-aimd", graphmine::MaximalCliqueBackend::g2_aimd},
       {"rdmce", graphmine::MaximalCliqueBackend::rdmce}});
  if (auto value = arguments.optional("minimum-clique-size")) {
    options.minimum_clique_size =
        parse_integer<std::size_t>(*value, "minimum-clique-size", 1);
  }
  options.result_limit = parse_limit(arguments);
  if (arguments.flag("include-total-count")) {
    options.optional_outputs =
        graphmine::MaximalCliqueOptionalOutput::total_count;
  }
  options.allow_directed_projection = common.allow_directed_projection;
  options.execution = common.execution;
  arguments.finish();
  auto graph = read_graph(common.graph_path);
  const auto result = invoke_backend(
      [&] { return graphmine::MaximalCliques(options).run(graph); });
  return result_json(result, common.execution.collect_statistics,
                     maximal_clique_output);
}

json::object run_maximum_clique(Arguments& arguments,
                                const CommonOptions& common) {
  graphmine::MaximumCliqueOptions options;
  options.backend = parse_backend<graphmine::MaximumCliqueBackend>(
      common.backend,
      {{"auto", graphmine::MaximumCliqueBackend::automatic},
       {"cuda-ms", graphmine::MaximumCliqueBackend::cuda_ms},
       {"gpu-maximum-clique",
        graphmine::MaximumCliqueBackend::gpu_maximum_clique},
       {"maximum-clique-on-gpu",
        graphmine::MaximumCliqueBackend::maximum_clique_on_gpu}});
  options.return_all_ties = arguments.flag("return-all-ties");
  if (auto value = arguments.optional("known-lower-bound")) {
    options.known_lower_bound =
        parse_integer<std::uint32_t>(*value, "known-lower-bound", 0);
  }
  if (arguments.flag("include-upper-bound")) {
    options.optional_outputs =
        graphmine::MaximumCliqueOptionalOutput::upper_bound;
  }
  options.allow_directed_projection = common.allow_directed_projection;
  options.execution = common.execution;
  arguments.finish();
  auto graph = read_graph(common.graph_path);
  const auto result = invoke_backend(
      [&] { return graphmine::MaximumClique(options).run(graph); });
  return result_json(result, common.execution.collect_statistics,
                     maximum_clique_output);
}

json::object run_k_core(Arguments& arguments, const CommonOptions& common) {
  graphmine::KCoreOptions options;
  options.backend = parse_backend<graphmine::KCoreBackend>(
      common.backend,
      {{"auto", graphmine::KCoreBackend::automatic},
       {"kcore-gpu", graphmine::KCoreBackend::kcore_gpu}});
  if (auto value = arguments.optional("requested-k")) {
    options.requested_k =
        parse_integer<std::uint32_t>(*value, "requested-k", 0);
  }
  if (arguments.flag("include-requested-core-vertices")) {
    options.optional_outputs = options.optional_outputs |
                               graphmine::KCoreOptionalOutput::requested_core_vertices;
  }
  if (arguments.flag("include-requested-core-edges")) {
    options.optional_outputs = options.optional_outputs |
                               graphmine::KCoreOptionalOutput::requested_core_edges;
  }
  if (arguments.flag("include-peeling-order")) {
    options.optional_outputs = options.optional_outputs |
                               graphmine::KCoreOptionalOutput::peeling_order;
  }
  options.allow_directed_projection = common.allow_directed_projection;
  options.execution = common.execution;
  arguments.finish();
  auto graph = read_graph(common.graph_path);
  const auto result =
      invoke_backend([&] { return graphmine::KCore(options).run(graph); });
  return result_json(result, common.execution.collect_statistics, k_core_output);
}

json::object run_triangle_counting(Arguments& arguments,
                                   const CommonOptions& common) {
  graphmine::TriangleOptions options;
  options.backend = parse_backend<graphmine::TriangleBackend>(
      common.backend,
      {{"auto", graphmine::TriangleBackend::automatic},
       {"tot", graphmine::TriangleBackend::tot},
       {"wetric", graphmine::TriangleBackend::wetric}});
  options.list_instances = arguments.flag("list-instances");
  options.include_per_vertex_counts =
      arguments.flag("include-per-vertex-counts");
  options.include_per_edge_counts =
      arguments.flag("include-per-edge-counts");
  options.result_limit = parse_limit(arguments);
  if (auto value = arguments.optional("wetric-spread")) {
    options.wetric_spread =
        parse_integer<std::uint32_t>(*value, "wetric-spread", 1);
  }
  if (auto value = arguments.optional("wetric-adjacency-matrix-length")) {
    options.wetric_adjacency_matrix_length = parse_integer<std::uint32_t>(
        *value, "wetric-adjacency-matrix-length", 1);
  }
  options.allow_directed_projection = common.allow_directed_projection;
  options.execution = common.execution;
  arguments.finish();
  auto graph = read_graph(common.graph_path);
  const auto result = invoke_backend(
      [&] { return graphmine::TriangleCounting(options).run(graph); });
  return result_json(result, common.execution.collect_statistics,
                     triangle_output);
}

json::object run_dynamic_triangle_counting(Arguments& arguments,
                                           const CommonOptions& common) {
  graphmine::DynamicTriangleOptions options;
  options.backend = parse_backend<graphmine::DynamicTriangleBackend>(
      common.backend,
      {{"auto", graphmine::DynamicTriangleBackend::automatic},
       {"edtc", graphmine::DynamicTriangleBackend::edtc}});
  const auto updates_path = arguments.required("updates");
  options.list_changed_instances =
      arguments.flag("list-changed-instances");
  options.include_global_counts = arguments.flag("include-global-counts");
  options.result_limit = parse_limit(arguments);
  options.allow_directed_projection = common.allow_directed_projection;
  options.execution = common.execution;
  arguments.finish();
  auto graph = read_graph(common.graph_path);
  auto updates = read_updates(updates_path);
  const auto result = invoke_backend([&] {
    return graphmine::DynamicTriangleCounting(options).run(graph, updates);
  });
  return result_json(result, common.execution.collect_statistics,
                     dynamic_triangle_output);
}

json::object run_k_cliques(Arguments& arguments,
                           const CommonOptions& common) {
  graphmine::KCliqueOptions options;
  options.backend = parse_backend<graphmine::KCliqueBackend>(
      common.backend,
      {{"auto", graphmine::KCliqueBackend::automatic},
       {"kcgpu", graphmine::KCliqueBackend::kcgpu},
       {"graphset", graphmine::KCliqueBackend::graphset},
       {"gamma", graphmine::KCliqueBackend::gamma}});
  if (auto value = arguments.optional("k")) {
    options.k = parse_integer<std::uint32_t>(*value, "k", 1);
  }
  options.enumerate = arguments.flag("enumerate");
  options.include_per_vertex_counts =
      arguments.flag("include-per-vertex-counts");
  options.result_limit = parse_limit(arguments);
  options.allow_directed_projection = common.allow_directed_projection;
  options.execution = common.execution;
  arguments.finish();
  auto graph = read_graph(common.graph_path);
  const auto result =
      invoke_backend([&] { return graphmine::KCliques(options).run(graph); });
  return result_json(result, common.execution.collect_statistics,
                     k_clique_output);
}

json::object run_centrality(Arguments& arguments,
                            const CommonOptions& common) {
  graphmine::BetweennessCentralityOptions options;
  options.backend = parse_backend<graphmine::BetweennessCentralityBackend>(
      common.backend,
      {{"auto", graphmine::BetweennessCentralityBackend::automatic},
       {"turbo-bc", graphmine::BetweennessCentralityBackend::turbo_bc}});
  if (arguments.flag("include-normalized-scores")) {
    options.optional_outputs =
        options.optional_outputs |
        graphmine::BetweennessCentralityOptionalOutput::normalized_scores;
  }
  if (arguments.flag("include-ranking")) {
    options.optional_outputs =
        options.optional_outputs |
        graphmine::BetweennessCentralityOptionalOutput::ranking;
  }
  if (arguments.flag("include-maximum")) {
    options.optional_outputs =
        options.optional_outputs |
        graphmine::BetweennessCentralityOptionalOutput::maximum;
  }
  options.allow_directed_projection = common.allow_directed_projection;
  options.execution = common.execution;
  arguments.finish();
  auto graph = read_graph(common.graph_path);
  const auto result = invoke_backend(
      [&] { return graphmine::BetweennessCentrality(options).run(graph); });
  return result_json(result, common.execution.collect_statistics,
                     centrality_output);
}

json::object run_maximal_bicliques(Arguments& arguments,
                                   const CommonOptions& common) {
  graphmine::MaximalBicliqueOptions options;
  options.backend = parse_backend<graphmine::MaximalBicliqueBackend>(
      common.backend,
      {{"auto", graphmine::MaximalBicliqueBackend::automatic},
       {"cumbe", graphmine::MaximalBicliqueBackend::cumbe}});
  options.left_partition =
      read_id_array(arguments.required("left-partition"), "left_partition");
  if (auto value = arguments.optional("minimum-left-size")) {
    options.minimum_left_size =
        parse_integer<std::size_t>(*value, "minimum-left-size", 1);
  }
  if (auto value = arguments.optional("minimum-right-size")) {
    options.minimum_right_size =
        parse_integer<std::size_t>(*value, "minimum-right-size", 1);
  }
  options.result_limit = parse_limit(arguments);
  if (arguments.flag("include-total-count")) {
    options.optional_outputs =
        graphmine::MaximalBicliqueOptionalOutput::total_count;
  }
  options.allow_directed_projection = common.allow_directed_projection;
  options.execution = common.execution;
  arguments.finish();
  auto graph = read_graph(common.graph_path);
  const auto result = invoke_backend(
      [&] { return graphmine::MaximalBicliques(options).run(graph); });
  return result_json(result, common.execution.collect_statistics,
                     maximal_biclique_output);
}

json::object run_quasi_cliques(Arguments& arguments,
                               const CommonOptions& common) {
  graphmine::QuasiCliqueOptions options;
  options.backend = parse_backend<graphmine::QuasiCliqueBackend>(
      common.backend,
      {{"auto", graphmine::QuasiCliqueBackend::automatic},
       {"cuqc", graphmine::QuasiCliqueBackend::cuqc}});
  if (auto value = arguments.optional("minimum-degree-ratio")) {
    options.minimum_degree_ratio =
        parse_double(*value, "minimum-degree-ratio");
  }
  if (auto value = arguments.optional("minimum-size")) {
    options.minimum_size =
        parse_integer<std::size_t>(*value, "minimum-size", 1);
  }
  if (auto value = arguments.optional("scheduling")) {
    const auto scheduling = normalized_name(*value);
    if (scheduling == "dynamic") {
      options.scheduling = graphmine::CuQCScheduling::dynamic;
    } else if (scheduling == "static") {
      options.scheduling = graphmine::CuQCScheduling::static_schedule;
    } else {
      throw UsageError("--scheduling must be dynamic or static");
    }
  }
  options.result_limit = parse_limit(arguments);
  if (arguments.flag("include-total-count")) {
    options.optional_outputs =
        graphmine::QuasiCliqueOptionalOutput::total_count;
  }
  options.allow_directed_projection = common.allow_directed_projection;
  options.execution = common.execution;
  arguments.finish();
  auto graph = read_graph(common.graph_path);
  const auto result = invoke_backend(
      [&] { return graphmine::QuasiCliques(options).run(graph); });
  return result_json(result, common.execution.collect_statistics,
                     quasi_clique_output);
}

json::object run_subgraph_isomorphism(Arguments& arguments,
                                      const CommonOptions& common) {
  graphmine::SubgraphIsomorphismOptions options;
  options.backend = parse_backend<graphmine::SubgraphIsomorphismBackend>(
      common.backend,
      {{"auto", graphmine::SubgraphIsomorphismBackend::automatic},
       {"gmatch", graphmine::SubgraphIsomorphismBackend::gmatch}});
  const auto query_path = arguments.required("query-graph");
  options.respect_vertex_labels = !arguments.flag("ignore-vertex-labels");
  if (auto value = arguments.optional("initial-match-capacity")) {
    options.initial_match_capacity = parse_integer<std::size_t>(
        *value, "initial-match-capacity", 1);
  }
  if (arguments.flag("include-embeddings")) {
    options.optional_outputs =
        graphmine::SubgraphIsomorphismOptionalOutput::embeddings;
  }
  options.result_limit = parse_limit(arguments);
  options.allow_directed_projection = common.allow_directed_projection;
  options.execution = common.execution;
  arguments.finish();
  auto graph = read_graph(common.graph_path);
  auto query = read_graph(query_path);
  const auto result = invoke_backend(
      [&] { return graphmine::SubgraphIsomorphism(options).run(graph, query); });
  return result_json(result, common.execution.collect_statistics,
                     subgraph_output);
}

json::object run_graph_motifs(Arguments& arguments,
                              const CommonOptions& common) {
  graphmine::GraphMotifOptions options;
  options.backend = parse_backend<graphmine::GraphMotifBackend>(
      common.backend,
      {{"auto", graphmine::GraphMotifBackend::automatic},
       {"graphminer", graphmine::GraphMotifBackend::graphminer},
       {"graphset", graphmine::GraphMotifBackend::graphset},
       {"dumato", graphmine::GraphMotifBackend::dumato}});
  const auto motif_paths = arguments.multiple("motif");
  if (motif_paths.empty()) {
    throw UsageError("graph-motifs requires at least one --motif graph.json");
  }
  options.induced = arguments.flag("induced");
  if (auto value = arguments.optional("occurrence-identity")) {
    const auto identity = normalized_name(*value);
    if (identity == "unique-vertex-set-and-mapping-class") {
      options.occurrence_identity =
          graphmine::MotifOccurrenceIdentity::unique_vertex_set_and_mapping_class;
    } else if (identity == "all-embeddings") {
      options.occurrence_identity =
          graphmine::MotifOccurrenceIdentity::all_embeddings;
    } else {
      throw UsageError(
          "--occurrence-identity must be "
          "unique-vertex-set-and-mapping-class or all-embeddings");
    }
  }
  if (arguments.flag("include-instances")) {
    options.optional_outputs =
        options.optional_outputs | graphmine::GraphMotifOptionalOutput::instances;
  }
  if (arguments.flag("include-per-vertex-participation")) {
    options.optional_outputs =
        options.optional_outputs |
        graphmine::GraphMotifOptionalOutput::per_vertex_participation;
  }
  options.result_limit_per_motif =
      parse_limit(arguments, "result-limit-per-motif");
  options.allow_directed_projection = common.allow_directed_projection;
  options.execution = common.execution;
  arguments.finish();
  auto graph = read_graph(common.graph_path);
  std::vector<graphmine::Graph> motifs;
  motifs.reserve(motif_paths.size());
  for (const auto& path : motif_paths) motifs.push_back(read_graph(path));
  const auto result = invoke_backend(
      [&] { return graphmine::GraphMotifs(options).run(graph, motifs); });
  return result_json(result, common.execution.collect_statistics, motif_output);
}

json::object run_temporal_motifs(Arguments& arguments,
                                 const CommonOptions& common) {
  graphmine::TemporalMotifOptions options;
  options.backend = parse_backend<graphmine::TemporalMotifBackend>(
      common.backend,
      {{"auto", graphmine::TemporalMotifBackend::automatic},
       {"everest", graphmine::TemporalMotifBackend::everest},
       {"mayura", graphmine::TemporalMotifBackend::mayura}});
  options.max_time_span = parse_integer<std::int64_t>(
      arguments.required("max-time-span"), "max-time-span", 0);
  if (arguments.flag("include-instances")) {
    options.optional_outputs =
        graphmine::TemporalMotifOptionalOutput::instances;
  }
  options.result_limit = parse_limit(arguments);
  options.execution = common.execution;
  arguments.finish();
  auto graph = read_graph(common.graph_path);
  const auto result = invoke_backend(
      [&] { return graphmine::TemporalMotifMining(options).run(graph); });
  return result_json(result, common.execution.collect_statistics,
                     temporal_output);
}

json::object run_community_detection(Arguments& arguments,
                                     const CommonOptions& common) {
  graphmine::CommunityDetectionOptions options;
  options.backend = parse_backend<graphmine::CommunityDetectionBackend>(
      common.backend,
      {{"auto", graphmine::CommunityDetectionBackend::automatic},
       {"gleiden", graphmine::CommunityDetectionBackend::gleiden},
       {"parallel-louvain",
        graphmine::CommunityDetectionBackend::parallel_louvain},
       {"parallel-leiden",
        graphmine::CommunityDetectionBackend::parallel_leiden},
       {"parallel-leiden-plus",
        graphmine::CommunityDetectionBackend::parallel_leiden_plus}});
  if (arguments.flag("include-communities")) {
    options.optional_outputs =
        options.optional_outputs |
        graphmine::CommunityDetectionOptionalOutput::communities;
  }
  if (arguments.flag("include-edge-cut")) {
    options.optional_outputs =
        options.optional_outputs |
        graphmine::CommunityDetectionOptionalOutput::edge_cut;
  }
  options.allow_directed_projection = common.allow_directed_projection;
  options.execution = common.execution;
  arguments.finish();
  auto graph = read_graph(common.graph_path);
  const auto result = invoke_backend(
      [&] { return graphmine::CommunityDetection(options).run(graph); });
  return result_json(result, common.execution.collect_statistics,
                     community_output);
}

void expansion_backend(const CommonOptions& common, const std::string& expected) {
  if (common.backend != "auto" && common.backend != expected)
    throw UsageError("this operation supports only backend " + expected);
  if (common.allow_directed_projection)
    throw UsageError("this operation does not accept --allow-directed-projection");
}

template<class Options>
void isolated_options(Options& options, Arguments& arguments, const CommonOptions& common) {
  options.execution=common.execution;
  if(auto value=arguments.optional("timeout-seconds")) options.timeout_seconds=parse_integer<std::uint32_t>(*value,"timeout-seconds",1);
  if(auto value=arguments.optional("worker-directory")) options.worker_directory=*value;
}

ExternalId argument_id(const std::string& text) {
  boost::system::error_code error;
  auto value=json::parse(text,error);
  if(error) return ExternalId(text);
  return parse_external_id(value,"vertex id argument");
}

json::object run_expansion(const std::string& operation, Arguments& arguments, const CommonOptions& common) {
  auto graph=read_graph(common.graph_path);
  if(operation=="connected-components") {
    expansion_backend(common,"ecl-scc");graphmine::ConnectedComponentsOptions options;isolated_options(options,arguments,common);
    auto mode=arguments.required("connectivity-mode");
    if(mode=="weakly_connected") options.connectivity_mode=graphmine::ConnectivityMode::weakly_connected;
    else if(mode!="strongly_connected") throw UsageError("connectivity-mode must be weakly_connected or strongly_connected");
    arguments.finish();auto result=graphmine::ConnectedComponents(options).run(graph);
    return result_json(result,common.execution.collect_statistics,[](const graphmine::ConnectedComponentsOutput& out){
      json::array assignments,sizes;for(const auto& entry:out.component_assignment) assignments.push_back(json::object{{"vertex",id_json(entry.vertex)},{"component",entry.component}});
      for(auto size:out.component_sizes)sizes.push_back(size);
      return json::object{{"component_assignment",std::move(assignments)},{"component_count",out.component_count},{"component_sizes",std::move(sizes)}};
    });
  }
  if(operation=="max-flow-min-cut") {
    expansion_backend(common,"ecl-maxflow");graphmine::MaxFlowOptions options;isolated_options(options,arguments,common);
    options.source=argument_id(arguments.required("source"));options.sink=argument_id(arguments.required("sink"));options.unit_capacity=arguments.flag("unit-capacity");arguments.finish();
    auto result=graphmine::MaxFlowMinCut(options).run(graph);
    return result_json(result,common.execution.collect_statistics,[](const graphmine::MaxFlowOutput& out){
      json::array flows;for(const auto& entry:out.flow_assignment)flows.push_back(json::object{{"edge",id_json(entry.edge)},{"flow",entry.flow}});
      return json::object{{"max_flow_value",out.max_flow_value},{"min_cut_value",out.min_cut_value},{"min_cut_edges",ids_json(out.min_cut_edges)},{"flow_assignment",std::move(flows)},{"source_side_vertices",ids_json(out.source_side_vertices)},{"optimal",out.optimal}};
    });
  }
  if(operation=="linear-assignment") {
    expansion_backend(common,"hungarian-cuda");graphmine::LinearAssignmentOptions options;isolated_options(options,arguments,common);arguments.finish();
    auto result=graphmine::LinearAssignment(options).run(graph);
    return result_json(result,common.execution.collect_statistics,[](const graphmine::LinearAssignmentOutput& out){return json::object{{"matching_edges",ids_json(out.matching_edges)},{"matching_size",out.matching_size},{"objective_value",out.objective_value},{"feasible",out.feasible},{"optimal",out.optimal}};});
  }
  if(operation=="transitive-closure") {
    expansion_backend(common,"gdlog");graphmine::ReachabilityOptions options;isolated_options(options,arguments,common);arguments.finish();auto result=graphmine::TransitiveClosure(options).run(graph);
    return result_json(result,common.execution.collect_statistics,[](const graphmine::ReachabilityOutput& out){json::array pairs;for(const auto& pair:out.reachable_pairs)pairs.push_back(json::object{{"source",id_json(pair.source)},{"target",id_json(pair.target)}});return json::object{{"transitive_closure_edges",std::move(pairs)},{"reachable_pair_count",out.reachable_pair_count},{"reachability_results",json::array{}},{"complete",out.complete}};});
  }
  expansion_backend(common,"graphminer");graphmine::ButterflyOptions options;options.execution=common.execution;arguments.finish();
  auto result=invoke_backend([&]{return graphmine::ButterflyCounting(options).run(graph);});
  return result_json(result,common.execution.collect_statistics,[](const graphmine::ButterflyOutput& out){return json::object{{"butterfly_count",out.butterfly_count},{"complete",out.complete}};});
}

using BackendProvider = std::function<std::vector<graphmine::BackendInfo>()>;

struct OperationDescriptor {
  std::string id;
  std::string research_problem;
  std::string usage;
  BackendProvider backends;
};

const std::vector<OperationDescriptor>& operations() {
  static const std::vector<OperationDescriptor> values = {
      {"connected-components","connected_components","graphmine run connected-components --graph GRAPH.json --connectivity-mode weakly_connected|strongly_connected [--backend ecl-scc] [--timeout-seconds N]",graphmine::ConnectedComponents::backends},
      {"max-flow-min-cut","max_flow_min_cut","graphmine run max-flow-min-cut --graph GRAPH.json --source ID --sink ID [--unit-capacity] [--backend ecl-maxflow] [--timeout-seconds N]",graphmine::MaxFlowMinCut::backends},
      {"linear-assignment","bipartite_matching_assignment","graphmine run linear-assignment --graph GRAPH.json [--backend hungarian-cuda] [--timeout-seconds N] (complete square minimum-cost perfect assignment, <=64 per side, integer costs 0..999)",graphmine::LinearAssignment::backends},
      {"transitive-closure","transitive_closure_reachability","graphmine run transitive-closure --graph GRAPH.json [--backend gdlog] [--timeout-seconds N] (reflexive closure; <=1024 vertices)",graphmine::TransitiveClosure::backends},
      {"butterfly-counting","butterfly_counting_bipartite","graphmine run butterfly-counting --graph GRAPH.json [--backend graphminer] (global count only; undirected bipartite graph)",graphmine::ButterflyCounting::backends},
      {"maximal-cliques", "maximal_clique_enumeration",
       "graphmine run maximal-cliques --graph GRAPH.json [--backend "
       "auto|mce-gpu|g2-aimd|rdmce] [--minimum-clique-size N] "
       "[--result-limit N] [--include-total-count]",
       graphmine::MaximalCliques::backends},
      {"maximum-clique", "maximum_clique",
       "graphmine run maximum-clique --graph GRAPH.json [--backend "
       "auto|cuda-ms|gpu-maximum-clique|maximum-clique-on-gpu] "
       "[--return-all-ties] [--known-lower-bound N] [--include-upper-bound]",
       graphmine::MaximumClique::backends},
      {"k-cliques", "k_clique_counting_enumeration",
       "graphmine run k-cliques --graph GRAPH.json --k N [--backend "
       "auto|kcgpu|graphset|gamma] [--enumerate] "
       "[--include-per-vertex-counts] [--result-limit N]",
       graphmine::KCliques::backends},
      {"quasi-cliques", "quasi_clique_mining",
       "graphmine run quasi-cliques --graph GRAPH.json "
       "[--minimum-degree-ratio R] [--minimum-size N] "
       "[--scheduling dynamic|static] [--result-limit N] "
       "[--include-total-count]",
       graphmine::QuasiCliques::backends},
      {"k-core", "k_core_decomposition",
       "graphmine run k-core --graph GRAPH.json [--requested-k N] "
       "[--include-requested-core-vertices] "
       "[--include-requested-core-edges] [--include-peeling-order]",
       graphmine::KCore::backends},
      {"maximal-bicliques", "maximal_biclique_enumeration",
       "graphmine run maximal-bicliques --graph GRAPH.json "
       "--left-partition LEFT.json [--minimum-left-size N] "
       "[--minimum-right-size N] [--result-limit N] "
       "[--include-total-count]",
       graphmine::MaximalBicliques::backends},
      {"triangle-counting", "triangle_counting_listing",
       "graphmine run triangle-counting --graph GRAPH.json [--backend "
       "auto|tot|wetric] [--list-instances] "
       "[--include-per-vertex-counts] [--include-per-edge-counts] "
       "[--result-limit N]",
       graphmine::TriangleCounting::backends},
      {"dynamic-triangle-counting", "triangle_counting_listing",
       "graphmine run dynamic-triangle-counting --graph GRAPH.json "
       "--updates UPDATES.json [--list-changed-instances] "
       "[--include-global-counts] [--result-limit N]",
       graphmine::DynamicTriangleCounting::backends},
      {"graph-motifs", "graph_motif_counting",
       "graphmine run graph-motifs --graph GRAPH.json --motif MOTIF.json "
       "[--motif OTHER.json ...] [--backend auto|graphminer|graphset|dumato] "
       "[--induced] [--include-instances] "
       "[--include-per-vertex-participation] "
       "[--result-limit-per-motif N]",
       graphmine::GraphMotifs::backends},
      {"subgraph-isomorphism", "subgraph_isomorphism",
       "graphmine run subgraph-isomorphism --graph DATA.json "
       "--query-graph QUERY.json [--ignore-vertex-labels] "
       "[--include-embeddings] [--result-limit N]",
       graphmine::SubgraphIsomorphism::backends},
      {"temporal-motif-mining", "temporal_motif_mining",
       "graphmine run temporal-motif-mining --graph GRAPH.json "
       "--max-time-span N [--backend auto|everest|mayura] "
       "[--include-instances] [--result-limit N]",
       graphmine::TemporalMotifMining::backends},
      {"community-detection", "community_detection",
       "graphmine run community-detection --graph GRAPH.json [--backend "
       "auto|gleiden|parallel-louvain|parallel-leiden|parallel-leiden-plus] "
       "[--include-communities] [--include-edge-cut]",
       graphmine::CommunityDetection::backends},
      {"betweenness-centrality", "centrality_influential_node_mining",
       "graphmine run betweenness-centrality --graph GRAPH.json "
       "[--include-normalized-scores] [--include-ranking] "
       "[--include-maximum]",
       graphmine::BetweennessCentrality::backends},
  };
  return values;
}

json::object backend_json(const graphmine::BackendInfo& backend) {
  json::array capabilities;
  for (const auto& capability : backend.capabilities) {
    capabilities.push_back(json::value(capability));
  }
  return {{"id", backend.id},
          {"display_name", backend.display_name},
          {"problem", backend.problem},
          {"source_commit", backend.source_commit},
          {"compiled", backend.compiled},
          {"validated", backend.validated},
          {"capabilities", std::move(capabilities)}};
}

json::object operation_json(const OperationDescriptor& operation) {
  json::array backends;
  for (const auto& backend : operation.backends()) {
    backends.push_back(backend_json(backend));
  }
  return {{"id", operation.id},
          {"research_problem", operation.research_problem},
          {"usage", operation.usage},
          {"backends", std::move(backends)}};
}

const OperationDescriptor& find_operation(std::string name) {
  name = normalized_name(std::move(name));
  const auto& values = operations();
  const auto found = std::find_if(
      values.begin(), values.end(),
      [&](const auto& operation) { return operation.id == name; });
  if (found == values.end()) {
    throw UsageError("unknown operation '" + name +
                     "'; run 'graphmine list' to see valid operations");
  }
  return *found;
}

json::object list_json() {
  json::array values;
  std::uint64_t backend_count = 0;
  std::uint64_t compiled_count = 0;
  for (const auto& operation : operations()) {
    auto item = operation_json(operation);
    const auto& backends = item.at("backends").as_array();
    backend_count += backends.size();
    for (const auto& backend : backends) {
      if (backend.as_object().at("compiled").as_bool()) ++compiled_count;
    }
    values.push_back(std::move(item));
  }
  return {{"schema_version", "1.0.0"},
          {"library_version", GRAPHMINE_VERSION},
          {"operation_count", values.size()},
          {"validated_backend_count", backend_count},
          {"compiled_backend_count", compiled_count},
          {"operations", std::move(values)}};
}

json::object validate_graph_json(const graphmine::Graph& graph) {
  const auto& descriptor = graph.canonical().graph;
  return {{"ok", true},
          {"graph",
           json::object{{"id", descriptor.id},
                        {"directed", descriptor.directed},
                        {"allows_self_loops", descriptor.allows_self_loops},
                        {"allows_parallel_edges",
                         descriptor.allows_parallel_edges},
                        {"vertex_count", graph.vertex_count()},
                        {"edge_count", graph.edge_count()}}}};
}

json::object run_operation(const std::string& operation, Arguments& arguments,
                           const CommonOptions& common) {
  if(operation=="connected-components" || operation=="max-flow-min-cut" || operation=="linear-assignment" || operation=="transitive-closure" || operation=="butterfly-counting")
    return run_expansion(operation,arguments,common);
  if (operation == "maximal-cliques") {
    return run_maximal_cliques(arguments, common);
  }
  if (operation == "maximum-clique") {
    return run_maximum_clique(arguments, common);
  }
  if (operation == "k-core") return run_k_core(arguments, common);
  if (operation == "triangle-counting") {
    return run_triangle_counting(arguments, common);
  }
  if (operation == "dynamic-triangle-counting") {
    return run_dynamic_triangle_counting(arguments, common);
  }
  if (operation == "k-cliques") return run_k_cliques(arguments, common);
  if (operation == "betweenness-centrality") {
    return run_centrality(arguments, common);
  }
  if (operation == "maximal-bicliques") {
    return run_maximal_bicliques(arguments, common);
  }
  if (operation == "quasi-cliques") {
    return run_quasi_cliques(arguments, common);
  }
  if (operation == "subgraph-isomorphism") {
    return run_subgraph_isomorphism(arguments, common);
  }
  if (operation == "graph-motifs") {
    return run_graph_motifs(arguments, common);
  }
  if (operation == "temporal-motif-mining") {
    return run_temporal_motifs(arguments, common);
  }
  if (operation == "community-detection") {
    return run_community_detection(arguments, common);
  }
  throw UsageError("internal dispatcher error for operation: " + operation);
}

void print_help() {
  std::cout
      << "GraphMine build-once/run-many command line interface\n\n"
      << "Usage:\n"
      << "  graphmine --version\n"
      << "  graphmine list [--output FILE] [--pretty]\n"
      << "  graphmine describe OPERATION [--output FILE] [--pretty]\n"
      << "  graphmine validate --graph GRAPH.json [--output FILE] [--pretty]\n"
      << "  graphmine run OPERATION --graph GRAPH.json [OPTIONS]\n\n"
      << "Common run options:\n"
      << "  --backend NAME                 Validated implementation (default: auto)\n"
      << "  --device ID[,ID...]           CUDA device ids (default: 0)\n"
      << "  --allow-directed-projection   Explicitly project directed input\n"
      << "  --no-statistics               Omit execution statistics from JSON\n"
      << "  --output FILE                 Write JSON to FILE instead of stdout\n"
      << "  --pretty                      Pretty-print JSON\n\n"
      << "Run 'graphmine list --pretty' for operations/backends and\n"
      << "'graphmine describe OPERATION --pretty' for exact operation usage.\n";
}

bool json_succeeded(const json::object& result) {
  const auto* ok = result.if_contains("ok");
  return ok == nullptr || (ok->is_bool() && ok->as_bool());
}

}  // namespace

int main(int argc, char** argv) {
  try {
    if (argc == 2 && (std::string_view(argv[1]) == "--version" ||
                      std::string_view(argv[1]) == "-V")) {
      std::cout << "GraphMine " << GRAPHMINE_VERSION << '\n';
      return 0;
    }
    if (argc < 2 || std::string_view(argv[1]) == "--help" ||
        std::string_view(argv[1]) == "-h" ||
        std::string_view(argv[1]) == "help") {
      print_help();
      return 0;
    }

    const std::string command = normalized_name(argv[1]);
    if (command == "list") {
      Arguments arguments(argc, argv, 2);
      const auto output = arguments.optional("output");
      const auto pretty = arguments.flag("pretty");
      arguments.finish();
      emit_json(list_json(), output, pretty);
      return 0;
    }
    if (command == "describe") {
      if (argc < 3 || std::string_view(argv[2]).rfind("--", 0) == 0) {
        throw UsageError("describe requires an operation name");
      }
      const auto& operation = find_operation(argv[2]);
      Arguments arguments(argc, argv, 3);
      const auto output = arguments.optional("output");
      const auto pretty = arguments.flag("pretty");
      arguments.finish();
      emit_json(operation_json(operation), output, pretty);
      return 0;
    }
    if (command == "validate") {
      Arguments arguments(argc, argv, 2);
      const auto graph_path = arguments.required("graph");
      const auto output = arguments.optional("output");
      const auto pretty = arguments.flag("pretty");
      arguments.finish();
      emit_json(validate_graph_json(read_graph(graph_path)), output, pretty);
      return 0;
    }
    if (command == "run") {
      if (argc < 3 || std::string_view(argv[2]).rfind("--", 0) == 0) {
        throw UsageError("run requires an operation name");
      }
      const auto operation = find_operation(argv[2]).id;
      Arguments arguments(argc, argv, 3);
      const auto common = parse_common(arguments);
      auto result = run_operation(operation, arguments, common);
      const auto succeeded = json_succeeded(result);
      emit_json(result, common.output_path, common.pretty);
      return succeeded ? 0 : 3;
    }
    throw UsageError("unknown command '" + command + "'");
  } catch (const UsageError& error) {
    json::object result{{"ok", false},
                        {"error",
                         json::object{{"code", "invalid_argument"},
                                      {"message", error.what()}}}};
    std::cerr << json::serialize(result) << '\n';
    return 2;
  } catch (const std::exception& error) {
    json::object result{{"ok", false},
                        {"error",
                         json::object{{"code", "internal_error"},
                                      {"message", error.what()}}}};
    std::cerr << json::serialize(result) << '\n';
    return 4;
  }
}
