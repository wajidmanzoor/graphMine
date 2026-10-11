#include "pattern_match.hpp"

#include <queue>

namespace graphmine::runtime {
const json::value* record_field(const json::object& record, const std::string& path) {
  const json::object* current = &record;
  std::size_t start = 0;
  for (;;) {
    const auto end = path.find('.', start);
    const auto key =
        path.substr(start, end == std::string::npos ? path.size() - start : end - start);
    const auto* value = current->if_contains(key);
    if (!value || end == std::string::npos) return value;
    if (!value->is_object()) return nullptr;
    current = &value->as_object();
    start = end + 1;
  }
}
bool typed_equal(const json::value& a, const json::value& b, Work& work) {
  work.tick();
  const bool ai = a.is_int64() || a.is_uint64(), bi = b.is_int64() || b.is_uint64();
  if (ai || bi) return ai && bi && exact_number(a, "integer") == exact_number(b, "integer");
  if (a.kind() != b.kind()) return false;
  if (a.is_array()) {
    if (a.as_array().size() != b.as_array().size()) return false;
    for (std::size_t i = 0; i < a.as_array().size(); ++i)
      if (!typed_equal(a.as_array()[i], b.as_array()[i], work)) return false;
    return true;
  }
  if (a.is_object()) {
    if (a.as_object().size() != b.as_object().size()) return false;
    for (const auto& entry : a.as_object()) {
      const auto* value = b.as_object().if_contains(entry.key());
      if (!value || !typed_equal(entry.value(), *value, work)) return false;
    }
    return true;
  }
  return a == b;
}
json::object vertex_record_json(const VertexRecord& record, Work& work) {
  json::object row{{"id", id_json(record.id)}};
  if (record.label) row["label"] = *record.label;
  if (record.type) row["type"] = *record.type;
  if (record.attributes_present || !record.attributes.empty())
    row["attributes"] = property_json(PropertyValue(record.attributes), work);
  return row;
}
json::object edge_record_json(const EdgeRecord& record, Work& work) {
  json::object row{{"id", id_json(record.id)},
                   {"source", id_json(record.source)},
                   {"target", id_json(record.target)}};
  if (record.type) row["type"] = *record.type;
  if (record.original_weight)
    row["weight"] =
        std::visit([](const auto& value) { return json::value(value); }, *record.original_weight);
  else if (record.weight)
    row["weight"] = *record.weight;
  if (record.timestamp)
    row["timestamp"] =
        std::visit([](const auto& value) { return json::value(value); }, *record.timestamp);
  if (record.attributes_present || !record.attributes.empty())
    row["attributes"] = property_json(PropertyValue(record.attributes), work);
  return row;
}
AttributePredicates::AttributePredicates(const json::value& input, const Graph& query, bool edge)
    : edges(edge) {
  require(input.is_array(), "Predicates must be an array");
  specifications = input.as_array();
  const std::set<std::string> roots =
      edge ? std::set<std::string>{"type", "weight", "timestamp", "attributes"}
           : std::set<std::string>{"label", "type", "attributes"};
  const char* binding = edge ? "query_edge" : "query_vertex";
  std::set<ExternalId> ids;
  if (edge)
    for (const auto& record : query.canonical().edges) ids.insert(record.id);
  else
    for (const auto& record : query.canonical().vertices) ids.insert(record.id);
  for (const auto& raw : specifications) {
    const auto spec = object(raw, "predicate");
    if (edge)
      fields(spec, {"field", "operator", "value", "query_field", "query_edge"},
             {"field", "operator"});
    else
      fields(spec, {"field", "operator", "value", "query_field", "query_vertex"},
             {"field", "operator"});
    const auto op = family_util::choice(
        spec, "operator", "eq", {"eq", "ne", "lt", "le", "gt", "ge", "in", "exists", "eq_query"});
    for (const auto key : {"field", "query_field"})
      if (spec.contains(key)) {
        const auto path = string(spec.at(key), key);
        require(!path.empty() && path.front() != '.' && path.back() != '.' &&
                    path.find("..") == std::string::npos &&
                    roots.count(path.substr(0, path.find('.'))),
                "Invalid predicate field path");
      }
    if (spec.contains(binding))
      require(ids.count(external_id(spec.at(binding))), std::string("Unknown ") + binding);
    if (op == "eq_query")
      require(!spec.contains("value"), "eq_query does not accept value");
    else {
      require(!spec.contains("query_field"), "query_field applies only to eq_query");
      require(op == "exists" || spec.contains("value"), "Predicate is missing value");
      if (op == "in") require(spec.at("value").is_array(), "The in predicate requires an array");
      if (op == "exists" && spec.contains("value"))
        require(spec.at("value").is_bool(), "exists value must be boolean");
    }
  }
}
bool AttributePredicates::match(const json::object& data, const json::object& pattern,
                                Work& work) const {
  const char* binding = edges ? "query_edge" : "query_vertex";
  for (const auto& raw : specifications) {
    work.tick();
    const auto& spec = raw.as_object();
    if (spec.contains(binding) && !typed_equal(spec.at(binding), pattern.at("id"), work)) continue;
    const auto field = string(spec.at("field"), "field"),
               op = string(spec.at("operator"), "operator");
    const auto* value = record_field(data, field);
    if (op == "exists") {
      if ((value != nullptr) != boolean(spec, "value", true)) return false;
      continue;
    }
    const auto* expected =
        op == "eq_query" ? record_field(pattern, spec.contains("query_field")
                                                     ? string(spec.at("query_field"), "query_field")
                                                     : field)
                         : &spec.at("value");
    if (!value || !expected) return false;
    if (op == "eq" || op == "ne" || op == "eq_query") {
      if (typed_equal(*value, *expected, work) == (op == "ne")) return false;
    } else if (op == "in") {
      bool found = false;
      for (const auto& item : expected->as_array())
        if (typed_equal(*value, item, work)) {
          found = true;
          break;
        }
      if (!found) return false;
    } else {
      int comparison;
      if (value->is_number() && expected->is_number()) {
        const auto a = exact_number(*value, "comparison"),
                   b = exact_number(*expected, "comparison");
        comparison = a < b ? -1 : a > b ? 1 : 0;
      } else if (value->is_string() && expected->is_string())
        comparison = value->as_string().compare(expected->as_string());
      else
        return false;
      if ((op == "lt" && comparison >= 0) || (op == "le" && comparison > 0) ||
          (op == "gt" && comparison <= 0) || (op == "ge" && comparison < 0))
        return false;
    }
  }
  return true;
}

bool pattern_mappings(const Graph& graph, const Graph& query, bool induced,
                      const json::array& vertex_specs, const json::array& edge_specs,
                      const std::function<bool(const std::vector<VertexIndex>&)>& emit,
                      Work& work) {
  require(graph.directed() == query.directed(), "Query and data graph direction must match");
  const AttributePredicates vertex_match(vertex_specs, query, false),
      edge_match(edge_specs, query, true);
  using Pair = std::pair<VertexIndex, VertexIndex>;
  std::vector<json::object> data_vertices, query_vertices, data_edges, query_edges;
  std::map<Pair, std::vector<std::size_t>> data_bundles, query_bundles;
  auto collect = [&](const Graph& input, auto& vertices, auto& edges, auto& bundles) {
    for (const auto& v : input.canonical().vertices)
      vertices.push_back(vertex_record_json(v, work));
    for (const auto& edge : input.canonical().edges) {
      work.tick();
      auto u = input.dense_index(edge.source), v = input.dense_index(edge.target);
      if (!input.directed() && u > v) std::swap(u, v);
      bundles[{u, v}].push_back(edges.size());
      edges.push_back(edge_record_json(edge, work));
    }
  };
  collect(graph, data_vertices, data_edges, data_bundles);
  collect(query, query_vertices, query_edges, query_bundles);
  const std::vector<std::size_t> empty;
  auto bundle = [&](VertexIndex a, VertexIndex b, VertexIndex u, VertexIndex v) {
    if (!graph.directed()) {
      if (a > b) std::swap(a, b);
      if (u > v) std::swap(u, v);
    }
    const auto pi = query_bundles.find({a, b}), di = data_bundles.find({u, v});
    const auto& patterns = pi == query_bundles.end() ? empty : pi->second;
    const auto& data = di == data_bundles.end() ? empty : di->second;
    if (data.size() < patterns.size() || (induced && data.size() != patterns.size())) return false;
    if (patterns.empty() || edge_specs.empty()) return true;
    std::vector<std::vector<std::size_t>> allowed(patterns.size());
    for (std::size_t q = 0; q < patterns.size(); ++q)
      for (std::size_t d = 0; d < data.size(); ++d) {
        work.tick();
        if (edge_match.match(data_edges[data[d]], query_edges[patterns[q]], work))
          allowed[q].push_back(d);
      }
    std::vector<std::optional<std::size_t>> matched_data(data.size()),
        matched_query(patterns.size());
    for (std::size_t root = 0; root < patterns.size(); ++root) {
      work.tick(patterns.size() + data.size());
      std::queue<std::size_t> queue;
      queue.push(root);
      std::vector<bool> seen(patterns.size(), false);
      seen[root] = true;
      std::vector<std::optional<std::size_t>> parent(data.size());
      std::optional<std::size_t> found;
      while (!queue.empty() && !found) {
        const auto q = queue.front();
        queue.pop();
        for (const auto d : allowed[q]) {
          work.tick();
          if (parent[d]) continue;
          parent[d] = q;
          if (!matched_data[d]) {
            found = d;
            break;
          }
          const auto next = *matched_data[d];
          if (!seen[next]) {
            seen[next] = true;
            queue.push(next);
          }
        }
      }
      if (!found) return false;
      while (found) {
        work.tick();
        const auto d = *found, q = *parent[d];
        const auto previous = matched_query[q];
        matched_data[d] = q;
        matched_query[q] = d;
        found = previous;
      }
    }
    return true;
  };
  return family_util::injective_assignments(
      query.vertex_count(), graph.vertex_count(), work, emit,
      [&](const auto& chosen, VertexIndex candidate) {
        const VertexIndex q = chosen.size();
        if (!vertex_match.match(data_vertices[candidate], query_vertices[q], work) ||
            !bundle(q, q, candidate, candidate))
          return false;
        for (VertexIndex p = 0; p < q; ++p) {
          work.tick();
          if (!bundle(p, q, chosen[p], candidate) ||
              (graph.directed() && !bundle(q, p, candidate, chosen[p])))
            return false;
        }
        return true;
      });
}
bool simple_mappings(const MiningGraph& graph, const MiningGraph& query, bool directed,
                     bool induced, const std::function<bool(const std::vector<VertexIndex>&)>& emit,
                     Work& work) {
  return family_util::injective_assignments(
      query.size(), graph.size(), work, emit, [&](const auto& chosen, VertexIndex candidate) {
        const auto q = chosen.size();
        for (VertexIndex p = 0; p < q; ++p) {
          work.tick();
          const auto qp = family_util::adjacent(query, p, q),
                     gp = family_util::adjacent(graph, chosen[p], candidate);
          if ((qp && !gp) || (induced && qp != gp)) return false;
          if (directed) {
            const auto pq = family_util::adjacent(query, q, p),
                       pg = family_util::adjacent(graph, candidate, chosen[p]);
            if ((pq && !pg) || (induced && pq != pg)) return false;
          }
        }
        return true;
      });
}
json::array mapping_rows(const Graph& graph, const Graph& query,
                         const std::vector<VertexIndex>& mapping) {
  json::array rows;
  for (VertexIndex q = 0; q < mapping.size(); ++q)
    rows.push_back(json::object{{"query_vertex", id_json(query.external_id(q))},
                                {"data_vertex", id_json(graph.external_id(mapping[q]))}});
  return rows;
}
}  // namespace graphmine::runtime
