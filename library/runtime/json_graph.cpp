#include <algorithm>
#include <cmath>
#include <limits>
#include <set>

#include "internal.hpp"

namespace graphmine::runtime {
json::object object(const json::value& value, const std::string& context) {
  require(value.is_object(), context + " must be an object");
  return value.as_object();
}

void fields(const json::object& value, std::initializer_list<std::string_view> allowed,
            std::initializer_list<std::string_view> required) {
  for (const auto& field : value) {
    require(std::find(allowed.begin(), allowed.end(),
                      std::string_view(field.key().data(), field.key().size())) != allowed.end(),
            "Unknown field: " + std::string(field.key()));
  }
  for (const auto& field : required)
    require(value.contains(field), "Missing required field: " + std::string(field));
}

std::string string(const json::value& value, const std::string& context) {
  require(value.is_string(), context + " must be a string");
  return std::string(value.as_string());
}

std::uint64_t uint(const json::value& value, const std::string& context) {
  require(value.is_uint64() || (value.is_int64() && value.as_int64() >= 0),
          context + " must be a nonnegative integer");
  return value.is_uint64() ? value.as_uint64() : static_cast<std::uint64_t>(value.as_int64());
}

ExternalId external_id(const json::value& value) {
  if (value.is_string()) {
    require(!value.as_string().empty(), "IDs must not be empty");
    return ExternalId(std::string(value.as_string()));
  }
  require(value.is_int64() || (value.is_uint64() && value.as_uint64() <= INT64_MAX),
          "IDs must be strings or signed 64-bit integers; no floating-point conversion is allowed");
  return ExternalId(value.is_int64() ? value.as_int64()
                                     : static_cast<std::int64_t>(value.as_uint64()));
}

json::value id_json(const ExternalId& value) {
  if (std::holds_alternative<std::int64_t>(value.value()))
    return std::get<std::int64_t>(value.value());
  return json::value(std::get<std::string>(value.value()));
}

namespace {
PropertyValue property(const json::value& value) {
  if (value.is_null()) return nullptr;
  if (value.is_bool()) return value.as_bool();
  if (value.is_int64()) return value.as_int64();
  if (value.is_uint64()) {
    require(value.as_uint64() <= INT64_MAX, "Native attribute integers must fit signed 64-bit");
    return static_cast<std::int64_t>(value.as_uint64());
  }
  if (value.is_double()) {
    require(std::isfinite(value.as_double()), "Attribute values must be finite");
    return value.as_double();
  }
  if (value.is_string()) return std::string(value.as_string());
  if (value.is_array()) {
    PropertyValue::Array output;
    for (const auto& item : value.as_array()) output.push_back(property(item));
    return output;
  }
  PropertyValue::Object output;
  for (const auto& item : value.as_object())
    output.emplace(std::string(item.key()), property(item.value()));
  return output;
}
Attributes attributes(const json::object& value) {
  if (!value.contains("attributes")) return {};
  require(value.at("attributes").is_object(), "attributes must be an object");
  return std::get<Attributes>(property(value.at("attributes")).value());
}
bool boolean(const json::object& value, const char* field) {
  require(value.at(field).is_bool(), std::string(field) + " must be a boolean");
  return value.at(field).as_bool();
}
}  // namespace

Graph parse_graph(const json::value& value) {
  const auto data = object(value, "graph input");
  fields(data, {"graph", "vertices", "edges"}, {"graph", "vertices", "edges"});
  const auto meta = object(data.at("graph"), "graph metadata");
  fields(meta, {"id", "directed", "allows_self_loops", "allows_parallel_edges", "attributes"},
         {"id", "directed", "allows_self_loops", "allows_parallel_edges"});
  CanonicalGraphInput input;
  input.graph = {string(meta.at("id"), "graph.id"), boolean(meta, "directed"),
                 boolean(meta, "allows_self_loops"), boolean(meta, "allows_parallel_edges"),
                 attributes(meta)};
  input.graph.attributes_present = meta.contains("attributes");
  require(data.at("vertices").is_array() && data.at("edges").is_array(),
          "vertices and edges must be arrays");
  for (const auto& raw : data.at("vertices").as_array()) {
    const auto row = object(raw, "vertex");
    fields(row, {"id", "label", "type", "attributes"}, {"id"});
    VertexRecord vertex;
    vertex.id = external_id(row.at("id"));
    if (row.contains("label")) vertex.label = string(row.at("label"), "label");
    if (row.contains("type")) vertex.type = string(row.at("type"), "type");
    vertex.attributes = attributes(row);
    vertex.attributes_present = row.contains("attributes");
    input.vertices.push_back(std::move(vertex));
  }
  std::set<std::pair<ExternalId, ExternalId>> pairs;
  for (const auto& raw : data.at("edges").as_array()) {
    const auto row = object(raw, "edge");
    fields(row, {"id", "source", "target", "weight", "timestamp", "type", "attributes"},
           {"id", "source", "target"});
    EdgeRecord edge;
    edge.id = external_id(row.at("id"));
    edge.source = external_id(row.at("source"));
    edge.target = external_id(row.at("target"));
    require(edge.source != edge.target || input.graph.allows_self_loops,
            "Self-loop contradicts graph metadata");
    auto pair = std::make_pair(edge.source, edge.target);
    if (!input.graph.directed && pair.second < pair.first) std::swap(pair.first, pair.second);
    require(pairs.insert(pair).second || input.graph.allows_parallel_edges,
            "Parallel edge contradicts graph metadata");
    if (row.contains("weight")) {
      const auto& weight = row.at("weight");
      require(weight.is_number(), "Edge weight must be numeric");
      edge.weight = weight.to_number<double>();
      if (weight.is_int64())
        edge.original_weight = weight.as_int64();
      else if (weight.is_uint64())
        edge.original_weight = weight.as_uint64();
      else
        edge.original_weight = weight.as_double();
      require(std::isfinite(*edge.weight), "Edge weight must be finite");
      // The existing native Graph stores weights as doubles. Do not silently
      // change an integer weight before a future weighted native operation.
      if (weight.is_int64())
        require(
            static_cast<long double>(*edge.weight) == static_cast<long double>(weight.as_int64()),
            "Integer edge weight loses precision in native Graph");
      if (weight.is_uint64())
        require(
            static_cast<long double>(*edge.weight) == static_cast<long double>(weight.as_uint64()),
            "Integer edge weight loses precision in native Graph");
    }
    if (row.contains("timestamp")) {
      const auto& time = row.at("timestamp");
      require(time.is_int64() || time.is_string(), "Timestamp must be an integer epoch or string");
      edge.timestamp =
          time.is_string() ? Timestamp(std::string(time.as_string())) : Timestamp(time.as_int64());
    }
    if (row.contains("type")) edge.type = string(row.at("type"), "type");
    edge.attributes = attributes(row);
    edge.attributes_present = row.contains("attributes");
    input.edges.push_back(std::move(edge));
  }
  return Graph(std::move(input));
}

void Work::tick(std::uint64_t amount) {
  if (amount > max_candidates - candidates)
    throw Failure("resource_limit", "Native candidate budget exceeded");
  candidates += amount;
  if (std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count() >
      timeout_seconds)
    throw Failure("resource_limit", "Native computation deadline exceeded");
}
void Work::output(std::uint64_t count) {
  tick(0);
  if (count > max_output_items) throw Failure("resource_limit", "Native output budget exceeded");
}

std::vector<std::vector<VertexIndex>> adjacency(const Graph& graph, Work& work) {
  std::vector<std::vector<VertexIndex>> result(graph.vertex_count());
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u != v) {
      result[u].push_back(v);
      if (!graph.directed()) result[v].push_back(u);
    }
  }
  for (auto& row : result) {
    std::sort(row.begin(), row.end());
    row.erase(std::unique(row.begin(), row.end()), row.end());
  }
  return result;
}
}  // namespace graphmine::runtime
