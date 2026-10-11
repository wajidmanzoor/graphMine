#include "record_query.hpp"

namespace graphmine::runtime {
void validate_query_parameters(const std::string& operation, const Graph& graph,
                               const json::object& args, Work& work) {
  if (operation_card(operation).at("problem_id") != "graph_record_queries") return;
  using namespace family_util;
  const record_query::Index index(graph, work);
  index.selected(args, "vertices", false);
  index.selected(args, "edge_ids", true);
  for (const auto* key : {"vertex_filters", "source_filters", "target_filters"})
    index.filters(args, key, false);
  index.filters(args, "edge_filters", true);
  for (const auto* key : {"entity", "source", "target"})
    if (args.contains(key) && !args.at(key).is_null())
      (void)graph.dense_index(external_id(args.at(key)));
  const auto direction = choice(args, "direction", "out", {"out", "in", "both"});
  const auto hops = natural(args, "hops", 1);
  if (args.contains("max_hops")) natural(args, "max_hops", 3);
  if (operation == "query-subgraph") {
    const auto mode = choice(args, "mode", "vertices", {"vertices", "edges", "neighborhood"});
    const bool vertices = args.contains("vertices") && !args.at("vertices").is_null();
    const bool entity = args.contains("entity") && !args.at("entity").is_null();
    require(mode != "vertices" || vertices, "Vertex extraction needs an explicit vertices array");
    require(mode == "neighborhood" || (!entity && hops == 1 && direction == "out"),
            "entity, hops and direction apply only to neighborhood mode");
    require(mode != "neighborhood" || (entity && !vertices),
            "Neighborhood mode needs entity and cannot accept vertices");
  }
  if (operation == "graph-aggregate") {
    const bool edges = choice(args, "scope", "edges", {"vertices", "edges"}) == "edges";
    const auto metric = choice(args, "metric", "count", {"count", "sum", "avg", "min", "max"});
    const auto& records = edges ? index.edges : index.vertices;
    index.filters(args, "filters", edges);
    const bool field = args.contains("field") && !args.at("field").is_null();
    const auto group = args.contains("group_by") && !args.at("group_by").is_null()
                           ? string(args.at("group_by"), "group_by")
                           : "";
    require(metric == "count" ? !field : field,
            "Numeric aggregation needs an explicit field; count must omit field");
    require(direction == "out" || (edges && group == "vertex"),
            "direction applies only to per-vertex edge aggregation");
    if (field) record_query::check_field(records, string(args.at("field"), "field"), edges);
    if (!group.empty() && group != "vertex") record_query::check_field(records, group, edges);
  }
}
}  // namespace graphmine::runtime
#include <queue>

namespace graphmine::runtime::record_query {
bool scalar(const json::value& value) {
  return value.is_null() || value.is_bool() || value.is_number() || value.is_string();
}
std::string scalar_key(const json::value& value) {
  require(scalar(value), "Filter/group values must be finite JSON scalars");
  if (value.is_number())
    return "number:" + json::serialize(fraction_json(family_util::decimal_number(value, "scalar")));
  return std::to_string(static_cast<int>(value.kind())) + ":" + json::serialize(value);
}
int compare(const json::value& a, const json::value& b) {
  if (a.is_number() && b.is_number()) {
    const auto x = family_util::decimal_number(a, "comparison"),
               y = family_util::decimal_number(b, "comparison");
    return x < y ? -1 : x > y ? 1 : 0;
  }
  if (a.is_string() && b.is_string()) {
    const auto result = a.as_string().compare(b.as_string());
    return result < 0 ? -1 : result > 0 ? 1 : 0;
  }
  return 2;
}
void check_field(const std::vector<json::object>& records, const std::string& field, bool edges,
                 bool allow_absent) {
  require(!field.empty() && field.front() != '.' && field.back() != '.' &&
              field.find("..") == std::string::npos,
          "Field must be a nonempty dotted record path");
  const std::set<std::string> fields =
      edges ? std::set<std::string>{"id",        "source", "target",    "weight",
                                    "timestamp", "type",   "attributes"}
            : std::set<std::string>{"id", "label", "type", "attributes"};
  if (fields.count(field)) return;
  require(field.rfind("attributes.", 0) == 0, "Unknown record field: " + field);
  require(allow_absent || records.empty() ||
              std::any_of(records.begin(), records.end(),
                          [&](const auto& row) { return record_field(row, field) != nullptr; }),
          "Unknown attribute field: " + field);
}
Filters::Filters(const json::value& input, const std::vector<json::object>& records, bool edges) {
  require(input.is_array(), "Filters must be an array");
  rules = input.as_array();
  for (const auto& raw : rules) {
    const auto row = object(raw, "filter");
    fields(row, {"field", "op", "value"}, {"field", "op", "value"});
    const auto field = string(row.at("field"), "field"),
               op = family_util::choice(
                   row, "op", "eq",
                   {"eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in", "contains", "exists"});
    const auto& value = row.at("value");
    check_field(records, field, edges, op == "exists");
    if (op == "in" || op == "not_in") {
      require(value.is_array(), "Membership filters need an array");
      for (const auto& item : value.as_array())
        require(scalar(item), "Filter values must be scalars");
    } else
      require(scalar(value), "Filter values must be scalars");
    if (op == "exists") require(value.is_bool(), "exists needs a boolean value");
    if (op == "lt" || op == "lte" || op == "gt" || op == "gte")
      require(value.is_string() || value.is_number(), "Ordered filters need a string or number");
    if ((field == "id" || field == "source" || field == "target") && op != "exists") {
      require(op != "contains", "IDs support exact comparisons, not contains");
      if (value.is_array())
        for (const auto& item : value.as_array()) external_id(item);
      else
        external_id(value);
    }
  }
}
bool Filters::match(const json::object& record, Work& work) const {
  for (const auto& raw : rules) {
    work.tick();
    const auto& row = raw.as_object();
    const auto field = string(row.at("field"), "field"), op = string(row.at("op"), "op");
    const auto* value = record_field(record, field);
    const auto& wanted = row.at("value");
    bool matched = false;
    if (op == "exists")
      matched = (value != nullptr) == wanted.as_bool();
    else if (value) {
      if (op == "contains") {
        if (value->is_string() && wanted.is_string()) {
          work.tick(value->as_string().size() + wanted.as_string().size());
          matched = value->as_string().find(wanted.as_string()) != json::string::npos;
        } else if (value->is_array())
          for (const auto& item : value->as_array()) {
            work.tick();
            if (scalar(item) && scalar_key(item) == scalar_key(wanted)) {
              matched = true;
              break;
            }
          }
      } else if (scalar(*value)) {
        if (op == "eq" || op == "ne" || op == "in" || op == "not_in") {
          if (op == "in" || op == "not_in")
            for (const auto& item : wanted.as_array()) {
              work.tick();
              if (scalar_key(*value) == scalar_key(item)) {
                matched = true;
                break;
              }
            }
          else
            matched = scalar_key(*value) == scalar_key(wanted);
          if (op == "ne" || op == "not_in") matched = !matched;
        } else {
          const auto comparison = compare(*value, wanted);
          matched = comparison != 2 &&
                    ((op == "lt" && comparison < 0) || (op == "lte" && comparison <= 0) ||
                     (op == "gt" && comparison > 0) || (op == "gte" && comparison >= 0));
        }
      }
    }
    if (!matched) return false;
  }
  return true;
}
Index::Index(const Graph& input, Work& work)
    : graph(input), outgoing(input.vertex_count()), incoming(input.vertex_count()) {
  for (const auto& row : graph.canonical().vertices)
    vertices.push_back(vertex_record_json(row, work));
  for (const auto& row : graph.canonical().edges) {
    work.tick();
    const auto i = edges.size();
    const auto u = graph.dense_index(row.source), v = graph.dense_index(row.target);
    edges.push_back(edge_record_json(row, work));
    outgoing[u].push_back(i);
    incoming[v].push_back(i);
    endpoints.emplace_back(u, v);
    edge_indices[row.id] = i;
  }
}
std::optional<std::set<std::size_t>> Index::selected(const json::object& args, const char* key,
                                                     bool is_edge) const {
  if (!args.contains(key) || args.at(key).is_null()) return {};
  const auto& raw = args.at(key);
  require(raw.is_array(), std::string(key) + " must be an array");
  std::set<std::size_t> result;
  for (const auto& value : raw.as_array()) {
    const auto id = external_id(value);
    if (is_edge) {
      const auto it = edge_indices.find(id);
      require(it != edge_indices.end(), "Unknown edge ID in selection");
      result.insert(it->second);
    } else
      result.insert(graph.dense_index(id));
  }
  return result;
}
Filters Index::filters(const json::object& args, const char* key, bool edge) const {
  return Filters(args.contains(key) ? args.at(key) : json::value(json::array{}),
                 edge ? edges : vertices, edge);
}
Adjacency adjacency(const Index& index, const json::object& args, Work& work) {
  const auto direction = family_util::choice(args, "direction", "out", {"out", "in", "both"});
  const auto edges = index.selected(args, "edge_ids", true);
  const auto filters = index.filters(args, "edge_filters", true);
  Adjacency result(index.vertices.size());
  for (VertexIndex v = 0; v < index.vertices.size(); ++v) {
    std::set<std::size_t> seen;
    auto append = [&](const auto& entries) {
      for (const auto e : entries) {
        work.tick();
        if (seen.count(e) || (edges && !edges->count(e)) || !filters.match(index.edges[e], work))
          continue;
        seen.insert(e);
        const auto [source, target] = index.endpoints[e];
        result[v].emplace_back(source == v ? target : source, e);
      }
    };
    if (!index.graph.directed() || direction == "out" || direction == "both")
      append(index.outgoing[v]);
    if (!index.graph.directed() || direction == "in" || direction == "both")
      append(index.incoming[v]);
  }
  return result;
}
std::vector<std::int64_t> distances(const Adjacency& adjacency, VertexIndex source,
                                    std::uint64_t hops, Work& work) {
  std::vector<std::int64_t> result(adjacency.size(), -1);
  result[source] = 0;
  std::queue<VertexIndex> queue;
  queue.push(source);
  while (!queue.empty()) {
    const auto u = queue.front();
    queue.pop();
    if (static_cast<std::uint64_t>(result[u]) >= hops) continue;
    for (const auto& [v, edge] : adjacency[u]) {
      work.tick();
      if (result[v] < 0) {
        result[v] = result[u] + 1;
        queue.push(v);
      }
    }
  }
  return result;
}
json::object result(const json::object& args, const json::array& rows, std::uint64_t count,
                    json::object ports) {
  const bool complete = rows.size() == count;
  if (!ports.contains("rows")) ports["rows"] = result_port("table", rows, complete);
  ports["count"] = result_port("scalar", count);
  auto output = family_util::output(
      args, {{"rows", rows}, {"matched_count", count}, {"returned_count", rows.size()}}, ports,
      complete);
  if (!complete)
    output["diagnostics"] =
        json::object{{"narrowing_hint",
                      "Add filters or reduce the neighborhood, or increase result_limit. "
                      "Incomplete collections cannot supply later steps."}};
  return output;
}
}  // namespace graphmine::runtime::record_query
