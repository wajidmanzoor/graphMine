#include "pattern_match.hpp"

namespace graphmine::runtime {
namespace {
using namespace family_util;
using Pair = std::pair<VertexIndex, VertexIndex>;
struct ComparisonGraph {
  bool directed;
  json::object graph;
  std::vector<std::string> labels;
  struct Edge {
    VertexIndex u, v;
    json::object record;
    std::string label;
  };
  std::vector<Edge> edges;
  std::map<Pair, std::size_t> indices;
  Pair key(VertexIndex u, VertexIndex v) const {
    if (!directed && u > v) std::swap(u, v);
    return {u, v};
  }
  std::optional<std::size_t> edge(VertexIndex u, VertexIndex v) const {
    const auto it = indices.find(key(u, v));
    if (it == indices.end()) return {};
    return it->second;
  }
};
std::vector<std::string> label_fields(const json::object& args, const char* name,
                                      json::array defaults, bool vertices) {
  const auto input = args.contains(name) ? args.at(name) : json::value(defaults);
  require(input.is_array(), std::string(name) + " must be an array");
  std::set<std::string> fields;
  for (const auto& value : input.as_array()) {
    const auto field = string(value, name);
    require(field == "type" || (vertices && field == "label"),
            "Unsupported comparison label field");
    require(fields.insert(field).second, "Repeated comparison label field");
  }
  return {fields.begin(), fields.end()};
}
std::string label_key(const json::object& record, const std::vector<std::string>& fields,
                      bool ignore) {
  json::array key;
  if (!ignore)
    for (const auto& field : fields)
      key.push_back(json::array{record.contains(field),
                                record.contains(field) ? record.at(field) : json::value(nullptr)});
  return json::serialize(key);
}
ComparisonGraph comparison_graph(const Graph& input, const std::vector<std::string>& vf,
                                 const std::vector<std::string>& ef, bool ignore,
                                 const std::string& loops, const std::string& parallel,
                                 Work& work) {
  ComparisonGraph result{input.directed(), {}, {}, {}, {}};
  json::array vertices, edges;
  for (const auto& vertex : input.canonical().vertices) {
    const auto record = vertex_record_json(vertex, work);
    json::object selected{{"id", record.at("id")}};
    for (const auto& field : vf)
      if (record.contains(field)) selected[field] = record.at(field);
    result.labels.push_back(label_key(record, vf, ignore));
    vertices.push_back(selected);
  }
  for (const auto& edge : input.canonical().edges) {
    work.tick();
    const auto u = input.dense_index(edge.source), v = input.dense_index(edge.target);
    if (u == v) {
      require(loops == "drop", "Selected comparison rejects self-loops");
      continue;
    }
    const auto record = edge_record_json(edge, work);
    const auto label = label_key(record, ef, ignore);
    const auto old = result.edge(u, v);
    if (old) {
      require(parallel == "collapse", "Parallel edges require explicit collapse");
      require(result.edges[*old].label == label, "Cannot collapse different selected edge types");
      continue;
    }
    json::object selected{
        {"id", record.at("id")}, {"source", record.at("source")}, {"target", record.at("target")}};
    for (const auto& field : ef)
      if (record.contains(field)) selected[field] = record.at(field);
    result.indices[result.key(u, v)] = result.edges.size();
    result.edges.push_back({u, v, selected, label});
    edges.push_back(selected);
  }
  result.graph = {{"graph",
                   {{"id", input.canonical().graph.id},
                    {"directed", input.directed()},
                    {"allows_self_loops", false},
                    {"allows_parallel_edges", false}}},
                  {"vertices", vertices},
                  {"edges", edges}};
  return result;
}
json::object compare_graphs(const Graph& graph, const json::object& args, bool edit, Work& work) {
  fields(args,
         edit
             ? std::initializer_list<std::string_view>{"other_graph", "label_match_policy",
                                                       "vertex_label_fields", "edge_label_fields",
                                                       "self_loops", "parallel_edges", "edit_costs"}
             : std::initializer_list<std::string_view>{"other_graph", "label_match_policy",
                                                       "vertex_label_fields", "edge_label_fields",
                                                       "self_loops", "parallel_edges", "induced"},
         {"other_graph"});
  const auto other = parse_graph(args.at("other_graph"));
  require(graph.directed() == other.directed(), "Comparison graphs must have the same direction");
  const auto policy = choice(args, "label_match_policy", "exact", {"exact", "ignore_labels"}),
             loops = choice(args, "self_loops", "drop", {"drop", "reject"}),
             parallel = choice(args, "parallel_edges", "reject", {"reject", "collapse"});
  const auto vf = label_fields(args, "vertex_label_fields", {"label", "type"}, true),
             ef = label_fields(args, "edge_label_fields", {"type"}, false);
  const auto a = comparison_graph(graph, vf, ef, policy == "ignore_labels", loops, parallel, work),
             b = comparison_graph(other, vf, ef, policy == "ignore_labels", loops, parallel, work);
  const auto n = a.labels.size(), m = b.labels.size();
  std::map<VertexIndex, VertexIndex> best_mapping;
  std::set<VertexIndex> matched;
  for (VertexIndex u = 0; u < n; ++u)
    for (VertexIndex v = 0; v < m; ++v) {
      work.tick();
      if (!matched.count(v) && a.labels[u] == b.labels[v]) {
        best_mapping[u] = v;
        matched.insert(v);
        break;
      }
    }
  json::array vfields, efields;
  for (const auto& field : vf) vfields.push_back(json::value(field));
  for (const auto& field : ef) efields.push_back(json::value(field));
  json::object parameters{{"other_graph", args.at("other_graph")},
                          {"label_match_policy", policy},
                          {"vertex_label_fields", vfields},
                          {"edge_label_fields", efields},
                          {"self_loops", loops},
                          {"parallel_edges", parallel}};
  json::object ports, data;
  if (!edit) {
    const bool induced = boolean(args, "induced", true);
    parameters["induced"] = induced;
    if (induced) {
      const auto upper = best_mapping.size();
      best_mapping.clear();
      for (std::size_t size = upper; size > 0 && best_mapping.empty(); --size)
        combinations(n, size, work, [&](const Vertices& subset) {
          return injective_assignments(
              size, m, work,
              [&](const Vertices& images) {
                for (std::size_t i = 0; i < size; ++i) best_mapping[subset[i]] = images[i];
                return false;
              },
              [&](const Vertices& images, VertexIndex candidate) {
                const auto q = images.size();
                const auto u = subset[q];
                if (a.labels[u] != b.labels[candidate]) return false;
                auto equal_edge = [&](VertexIndex x, VertexIndex y, VertexIndex p, VertexIndex r) {
                  const auto ae = a.edge(x, y), be = b.edge(p, r);
                  return ae.has_value() == be.has_value() &&
                         (!ae || a.edges[*ae].label == b.edges[*be].label);
                };
                for (std::size_t p = 0; p < q; ++p) {
                  work.tick();
                  if (!equal_edge(subset[p], u, images[p], candidate) ||
                      (a.directed && !equal_edge(u, subset[p], candidate, images[p])))
                    return false;
                }
                return true;
              });
        });
    }
    json::array vertices, edges, rows;
    for (auto [u, v] : best_mapping) {
      vertices.push_back(a.graph.at("vertices").as_array()[u]);
      rows.push_back(json::object{{"graph_a_vertex", id_json(graph.external_id(u))},
                                  {"graph_b_vertex", id_json(other.external_id(v))}});
    }
    for (const auto& edge : a.edges)
      if (best_mapping.count(edge.u) && best_mapping.count(edge.v)) {
        const auto opposite = b.edge(best_mapping.at(edge.u), best_mapping.at(edge.v));
        if (opposite && edge.label == b.edges[*opposite].label) edges.push_back(edge.record);
      }
    auto common = a.graph;
    common.at("graph").as_object()["id"] = "common-subgraph:" + input_fingerprint(a.graph) + ":" +
                                           input_fingerprint(args.at("other_graph"));
    common["vertices"] = vertices;
    common["edges"] = edges;
    work.output(2 * vertices.size() + edges.size());
    auto mapping_port = result_port("cross_graph_mapping", rows);
    mapping_port["other_graph_fingerprint"] = input_fingerprint(args.at("other_graph"));
    data = {
        {"task", "maximum_common_subgraph"},
        {"task_result",
         {{"subgraph", common}, {"vertex_count", vertices.size()}, {"edge_count", edges.size()}}},
        {"vertex_correspondence", rows},
        {"optimal", true}};
    ports = {{"graph", result_port("graph", common)},
             {"mapping", mapping_port},
             {"size", result_port("scalar", vertices.size())}};
  } else {
    const auto raw_costs =
        args.contains("edit_costs") ? object(args.at("edit_costs"), "edit_costs") : json::object{};
    fields(raw_costs, {"vertex_insertion", "vertex_deletion", "edge_insertion", "edge_deletion",
                       "edge_substitution"});
    std::map<std::string, Exact> costs;
    json::object declared;
    for (const auto* name : {"vertex_insertion", "vertex_deletion", "edge_insertion",
                             "edge_deletion", "edge_substitution"}) {
      const auto raw = raw_costs.contains(name) ? raw_costs.at(name) : json::value(1);
      costs[name] = decimal_number(raw, name);
      require(costs[name] >= 0, "Edit costs must be nonnegative");
      declared[name] = raw;
    }
    parameters["edit_costs"] = declared;
    auto vertex_cost = [&](VertexIndex u, VertexIndex v) -> Exact {
      return a.labels[u] == b.labels[v]
                 ? Exact(0)
                 : Exact(costs["vertex_insertion"] + costs["vertex_deletion"]);
    };
    auto edge_cost = [&](std::size_t first, std::size_t second) -> Exact {
      return a.edges[first].label == b.edges[second].label
                 ? Exact(0)
                 : std::min(costs["edge_substitution"],
                            Exact(costs["edge_deletion"] + costs["edge_insertion"]));
    };
    auto mapping_cost = [&](const std::map<VertexIndex, VertexIndex>& mapping) {
      Exact value = (n - mapping.size()) * costs["vertex_deletion"] +
                    (m - mapping.size()) * costs["vertex_insertion"];
      std::set<std::size_t> covered;
      for (auto [u, v] : mapping) {
        work.tick();
        value += vertex_cost(u, v);
      }
      for (std::size_t i = 0; i < a.edges.size(); ++i) {
        work.tick();
        const auto& e = a.edges[i];
        const auto counterpart = mapping.count(e.u) && mapping.count(e.v)
                                     ? b.edge(mapping.at(e.u), mapping.at(e.v))
                                     : std::nullopt;
        if (counterpart) {
          value += edge_cost(i, *counterpart);
          covered.insert(*counterpart);
        } else
          value += costs["edge_deletion"];
      }
      value += (b.edges.size() - covered.size()) * costs["edge_insertion"];
      return value;
    };
    Exact optimum = mapping_cost(best_mapping);
    if (optimum > 0 && (!a.edges.empty() || !b.edges.empty()))
      for (std::size_t size = 0; size <= std::min(n, m) && optimum > 0; ++size)
        combinations(n, size, work, [&](const Vertices& subset) {
          return injective_assignments(
              size, m, work,
              [&](const Vertices& images) {
                std::map<VertexIndex, VertexIndex> mapping;
                for (std::size_t i = 0; i < size; ++i) mapping[subset[i]] = images[i];
                const auto value = mapping_cost(mapping);
                if (value < optimum) {
                  optimum = value;
                  best_mapping = std::move(mapping);
                }
                return optimum > 0;
              },
              [](const Vertices&, VertexIndex) { return true; });
        });
    json::array edits, rows;
    Exact script_cost = 0;
    auto emit = [&](const char* kind, const Exact& cost, json::object row) {
      row["operation"] = kind;
      row["cost"] = display_number(cost);
      row["cost_numerator"] = numerator(cost).convert_to<std::string>();
      row["cost_denominator"] = denominator(cost).convert_to<std::string>();
      script_cost += cost;
      work.output(edits.size() + 1);
      edits.push_back(row);
    };
    std::vector<std::pair<std::size_t, std::size_t>> retained;
    std::set<std::size_t> covered;
    for (std::size_t i = 0; i < a.edges.size(); ++i) {
      const auto& e = a.edges[i];
      const auto counterpart = best_mapping.count(e.u) && best_mapping.count(e.v)
                                   ? b.edge(best_mapping.at(e.u), best_mapping.at(e.v))
                                   : std::nullopt;
      const bool split =
          counterpart && e.label != b.edges[*counterpart].label &&
          costs["edge_substitution"] > costs["edge_deletion"] + costs["edge_insertion"];
      if (!counterpart || split)
        emit("edge_deletion", costs["edge_deletion"], {{"edge_handle", i}});
      else {
        retained.emplace_back(i, *counterpart);
        covered.insert(*counterpart);
      }
    }
    std::map<VertexIndex, std::size_t> handles;
    for (VertexIndex u = 0; u < n; ++u)
      if (!best_mapping.count(u)) {
        emit("vertex_deletion", costs["vertex_deletion"], {{"vertex_handle", u}});
      }
    for (auto [u, v] : best_mapping) {
      handles[v] = u;
      emit("vertex_substitution", vertex_cost(u, v),
           {{"vertex_handle", u}, {"vertex_record", b.graph.at("vertices").as_array()[v]}});
      rows.push_back(json::object{{"graph_a_vertex", id_json(graph.external_id(u))},
                                  {"graph_b_vertex", id_json(other.external_id(v))}});
    }
    for (VertexIndex u = 0; u < n; ++u)
      if (!best_mapping.count(u))
        rows.push_back(json::object{{"graph_a_vertex", id_json(graph.external_id(u))},
                                    {"graph_b_vertex", nullptr}});
    for (VertexIndex v = 0; v < m; ++v)
      if (!handles.count(v)) {
        handles[v] = n + v;
        emit("vertex_insertion", costs["vertex_insertion"],
             {{"vertex_handle", n + v}, {"vertex_record", b.graph.at("vertices").as_array()[v]}});
        rows.push_back(json::object{{"graph_a_vertex", nullptr},
                                    {"graph_b_vertex", id_json(other.external_id(v))}});
      }
    auto target_record = [&](std::size_t i) {
      auto row = b.edges[i].record;
      row["source"] = handles.at(b.edges[i].u);
      row["target"] = handles.at(b.edges[i].v);
      return row;
    };
    for (auto [i, j] : retained)
      emit("edge_substitution", edge_cost(i, j),
           {{"edge_handle", i}, {"edge_record", target_record(j)}});
    for (std::size_t j = 0; j < b.edges.size(); ++j)
      if (!covered.count(j))
        emit("edge_insertion", costs["edge_insertion"],
             {{"edge_handle", a.edges.size() + j}, {"edge_record", target_record(j)}});
    require(script_cost == optimum, "Edit script does not realize the optimum");
    json::array vertex_handles, edge_handles;
    for (VertexIndex u = 0; u < n; ++u)
      vertex_handles.push_back(
          json::object{{"vertex_handle", u}, {"vertex", id_json(graph.external_id(u))}});
    for (std::size_t e = 0; e < a.edges.size(); ++e)
      edge_handles.push_back(
          json::object{{"edge_handle", e}, {"edge", a.edges[e].record.at("id")}});
    auto value = fraction_json(optimum);
    value["display"] = display_number(optimum);
    value["display_is_exact"] = !value.at("display").is_double() ||
                                decimal_number(value.at("display"), "distance") == optimum;
    auto mapping_port = result_port("cross_graph_mapping", rows);
    mapping_port["other_graph_fingerprint"] = input_fingerprint(args.at("other_graph"));
    json::object task_result{{"distance", display_number(optimum)},
                             {"distance_numerator", value.at("numerator")},
                             {"distance_denominator", value.at("denominator")}};
    exact_field(task_result, "distance", optimum);
    data = {{"task", "graph_edit_distance"},
            {"task_result", task_result},
            {"optimal", true},
            {"vertex_correspondence", rows},
            {"edit_path", edits},
            {"normalized_source", a.graph},
            {"normalized_target", b.graph},
            {"source_vertex_handles", vertex_handles},
            {"source_edge_handles", edge_handles}};
    ports = {{"distance", result_port("rational_scalar", value)},
             {"mapping", mapping_port},
             {"edits", result_port("table", edits)}};
    work.output(edits.size() + rows.size() + n + m + a.edges.size() + b.edges.size());
  }
  auto result = output(parameters, data, ports);
  result["diagnostics"] =
      json::object{{"method", "native bounded partial correspondence enumeration"},
                   {"arithmetic", "exact decimal rational"},
                   {"objective", edit ? "minimum declared edit cost"
                                      : "maximum vertex count; no edge-count tie objective"},
                   {"other_graph_fingerprint", input_fingerprint(args.at("other_graph"))}};
  return result;
}
}  // namespace
json::object graph_edit_distance(const Graph& graph, const json::object& args, const std::string&,
                                 int, Work& work) {
  return compare_graphs(graph, args, true, work);
}
json::object maximum_common_subgraph(const Graph& graph, const json::object& args,
                                     const std::string&, int, Work& work) {
  return compare_graphs(graph, args, false, work);
}
}  // namespace graphmine::runtime
