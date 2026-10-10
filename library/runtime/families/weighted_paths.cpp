#include "internal.hpp"
#include "exact_number.hpp"

#include <algorithm>
#include <limits>
#include <numeric>
#include <queue>
#include <set>
#include <tuple>

namespace graphmine::runtime {
namespace {
struct ExactSearch {
  std::vector<std::optional<Exact>> distances;
  std::vector<std::int64_t> predecessors;
};
ExactSearch dijkstra(const WeightedGraph& graph, VertexIndex source, Work& work) {
  work.tick(graph.rows.size());
  ExactSearch result{std::vector<std::optional<Exact>>(graph.rows.size()), std::vector<std::int64_t>(graph.rows.size(), -1)};
  using Item = std::pair<Exact, VertexIndex>;
  std::priority_queue<Item, std::vector<Item>, std::greater<Item>> queue;
  result.distances[source] = 0;
  queue.emplace(0, source);
  while (!queue.empty()) {
    work.tick();
    const auto [cost, u] = queue.top(); queue.pop();
    if (cost != *result.distances[u]) continue;
    for (const auto& edge : graph.rows[u]) {
      work.tick();
      Exact next = cost + Exact(edge.weight);
      if (!result.distances[edge.target] || next < *result.distances[edge.target]) {
        result.distances[edge.target] = next;
        result.predecessors[edge.target] = u;
        queue.emplace(std::move(next), edge.target);
      }
    }
  }
  return result;
}
std::vector<VertexIndex> vertices(const Graph& graph, const json::value& value) {
  std::vector<VertexIndex> result;
  if (value.is_null()) {
    result.resize(graph.vertex_count()); std::iota(result.begin(), result.end(), 0); return result;
  }
  require(value.is_array(), "Vertex selection must be an array or null");
  std::set<VertexIndex> seen;
  for (const auto& id : value.as_array()) {
    const auto v = graph.dense_index(external_id(id));
    if (seen.insert(v).second) result.push_back(v);
  }
  return result;
}
json::array external_vertices(const Graph& graph, const std::vector<VertexIndex>& values) {
  json::array result;
  for (const auto v : values) result.push_back(id_json(graph.external_id(v)));
  return result;
}
std::vector<ExactSearch> searches(const WeightedGraph& graph, const std::vector<VertexIndex>& sources,
                                 const std::string& backend, int device, Work& work) {
  std::vector<ExactSearch> result;
  work.tick(static_cast<std::uint64_t>(graph.rows.size()) * sources.size());
  if (backend == "cpp") {
    for (const auto source : sources) result.push_back(dijkstra(graph, source, work));
  } else {
    for (const auto& computed : cugraph_shortest_paths(graph, sources, device, work)) {
      ExactSearch row{std::vector<std::optional<Exact>>(graph.rows.size()), computed.predecessors};
      for (std::size_t i = 0; i < graph.rows.size(); ++i)
        if (computed.distances[i] < std::numeric_limits<double>::max()) row.distances[i] = Exact(computed.distances[i]);
      result.push_back(std::move(row));
    }
  }
  return result;
}
void distance_field(json::object& row, const std::optional<Exact>& distance, bool exact) {
  if (!distance) { row["distance"] = nullptr; return; }
  if (exact) exact_field(row, "distance", *distance);
  else row["distance"] = display_number(*distance);
}
json::object numeric_diagnostics(bool exact) {
  return {{"arithmetic", exact ? "exact_rational_over_native_binary64_edge_values" : "libcugraph_float64"},
          {"display_policy", exact ? "distance_exact is authoritative; rounded displays are marked; out-of-range numbers use a rational object" : "floating_point_result"}};
}
}

json::object shortest_paths(const Graph& graph, const json::object& args, const std::string& backend, int device, Work& work) {
  fields(args, {"source", "cutoff", "return_predecessors"}, {"source"});
  const auto source = graph.dense_index(external_id(args.at("source")));
  std::optional<Exact> cutoff;
  if (args.contains("cutoff") && !args.at("cutoff").is_null()) {
    cutoff = exact_number(args.at("cutoff"), "cutoff");
    require(*cutoff >= 0, "cutoff must be nonnegative");
  }
  const bool predecessors = boolean(args, "return_predecessors", true), exact = backend == "cpp";
  work.output(graph.vertex_count());
  const auto input = weighted_graph(graph, true, true, "min", "outgoing", work);
  const auto computed = searches(input, {source}, backend, device, work).front();
  json::array rows;
  for (VertexIndex v = 0; v < graph.vertex_count(); ++v) {
    auto distance = computed.distances[v];
    if (distance && cutoff && *distance > *cutoff) distance.reset();
    json::object row{{"vertex", id_json(graph.external_id(v))}};
    distance_field(row, distance, exact);
    if (predecessors) row["predecessor"] = !distance || v == source || computed.predecessors[v] < 0 ? json::value(nullptr) : id_json(graph.external_id(static_cast<VertexIndex>(computed.predecessors[v])));
    rows.push_back(std::move(row));
  }
  auto port = result_port("vertex_scores", rows); port["score_field"] = "distance";
  return {{"parameters", {{"source", args.at("source")}, {"cutoff", args.contains("cutoff") ? args.at("cutoff") : json::value(nullptr)}, {"return_predecessors", predecessors}}},
          {"result", {{"distances", rows}}}, {"ports", {{"distances", port}}}, {"complete", true},
          {"quality", exact ? "exact" : "numerical"}, {"diagnostics", numeric_diagnostics(exact)}};
}

json::object many_shortest_paths(const Graph& graph, const json::object& args, const std::string& backend, int device, Work& work) {
  fields(args, {"origins", "destinations", "weight_mode"});
  const auto mode = args.contains("weight_mode") ? string(args.at("weight_mode"), "weight_mode") : "edge_weight";
  require(mode == "edge_weight" || mode == "unweighted", "Unknown weight_mode");
  const auto sources = vertices(graph, args.contains("origins") ? args.at("origins") : json::value(nullptr));
  const auto targets = vertices(graph, args.contains("destinations") ? args.at("destinations") : json::value(nullptr));
  work.output(static_cast<std::uint64_t>(sources.size()) * targets.size());
  // The reference contract rejects negative stored lengths even when asking
  // for hop counts; retain that validation instead of changing request meaning.
  auto input = weighted_graph(graph, true, true, "min", "outgoing", work);
  if (mode == "unweighted") for (auto& row : input.rows) for (auto& arc : row) arc.weight = 1;
  const bool exact = backend == "cpp";
  const auto computed = targets.empty() ? std::vector<ExactSearch>{} : searches(input, sources, backend, device, work);
  json::array rows;
  for (std::size_t i = 0; !targets.empty() && i < sources.size(); ++i) for (const auto target : targets) {
    work.tick();
    json::object row{{"source", id_json(graph.external_id(sources[i]))}, {"target", id_json(graph.external_id(target))}};
    distance_field(row, computed[i].distances[target], exact); rows.push_back(std::move(row));
  }
  return {{"parameters", {{"origins", args.contains("origins") && !args.at("origins").is_null() ? json::value(external_vertices(graph, sources)) : json::value(nullptr)},
                           {"destinations", args.contains("destinations") && !args.at("destinations").is_null() ? json::value(external_vertices(graph, targets)) : json::value(nullptr)}, {"weight_mode", mode}}},
          {"result", {{"distances", rows}}}, {"ports", {{"distances", result_port("table", rows)}}}, {"complete", true},
          {"quality", exact ? "exact" : "numerical"}, {"diagnostics", numeric_diagnostics(exact)}};
}

json::object spanning_forest(const Graph& graph, const json::object& args, const std::string& backend, int device, Work& work) {
  fields(args, {"objective", "require_connected"});
  require(!graph.directed(), "Spanning forests require an undirected graph");
  const auto objective = args.contains("objective") ? string(args.at("objective"), "objective") : "minimum";
  require(objective == "minimum" || objective == "maximum", "Unknown spanning forest objective");
  const bool connected = boolean(args, "require_connected", false), maximum = objective == "maximum";
  const auto input = weighted_graph(graph, true, false, maximum ? "max" : "min", "outgoing", work);
  struct Edge { VertexIndex u, v; double weight; };
  std::vector<Edge> candidates;
  for (VertexIndex u = 0; u < input.rows.size(); ++u) for (const auto& arc : input.rows[u]) if (u < arc.target) candidates.push_back({u, arc.target, arc.weight});
  std::vector<VertexIndex> parents(graph.vertex_count()), sizes(graph.vertex_count(), 1);
  std::iota(parents.begin(), parents.end(), 0);
  auto root = [&](VertexIndex v) { while (parents[v] != v) { parents[v] = parents[parents[v]]; v = parents[v]; } return v; };
  auto join = [&](VertexIndex u, VertexIndex v) {
    u = root(u); v = root(v); if (u == v) return false;
    if (sizes[u] < sizes[v]) std::swap(u, v);
    parents[v] = u; sizes[u] += sizes[v]; return true;
  };
  std::vector<Edge> chosen;
  if (backend == "cpp") {
    std::sort(candidates.begin(), candidates.end(), [&](const Edge& a, const Edge& b) {
      if (a.weight != b.weight) return maximum ? a.weight > b.weight : a.weight < b.weight;
      return std::tie(a.u, a.v) < std::tie(b.u, b.v);
    });
    for (const auto& edge : candidates) { work.tick(); if (join(edge.u, edge.v)) chosen.push_back(edge); }
  } else {
    std::set<std::pair<VertexIndex, VertexIndex>> seen;
    for (auto [u, v] : cugraph_spanning_forest(input, maximum, device, work)) {
      work.tick(); if (v < u) std::swap(u, v);
      require(u < input.rows.size() && v < input.rows.size() && u != v, "libcugraph forest contains an invalid endpoint");
      if (!seen.emplace(u, v).second) continue;
      const auto found = std::find_if(input.rows[u].begin(), input.rows[u].end(), [v](const Arc& a) { return a.target == v; });
      require(found != input.rows[u].end() && join(u, v), "libcugraph forest contains an unknown edge or cycle");
      chosen.push_back({u, v, found->weight});
    }
    for (const auto& edge : candidates) require(root(edge.u) == root(edge.v), "libcugraph forest does not span an input component");
  }
  require(!connected || (graph.vertex_count() > 0 && chosen.size() + 1 == graph.vertex_count()), "A connected graph is required");
  work.output(graph.vertex_count() + chosen.size());
  std::sort(chosen.begin(), chosen.end(), [](const Edge& a, const Edge& b) { return std::tie(a.u, a.v) < std::tie(b.u, b.v); });
  json::array edges, nodes;
  Exact total = 0;
  for (const auto& edge : chosen) {
    edges.push_back(json::object{{"source", id_json(graph.external_id(edge.u))}, {"target", id_json(graph.external_id(edge.v))}, {"weight", edge.weight}});
    total += Exact(edge.weight);
  }
  for (VertexIndex v = 0; v < graph.vertex_count(); ++v) nodes.push_back(id_json(graph.external_id(v)));
  json::object data{{"vertices", nodes}, {"edges", edges}};
  exact_field(data, "total_weight", total);
  return {{"parameters", {{"objective", objective}, {"require_connected", connected}}}, {"result", data},
          {"ports", {{"edges", result_port("edge_set", edges)}, {"vertices", result_port("vertex_set", nodes)}}},
          {"complete", true}, {"quality", "exact"}};
}
}  // namespace graphmine::runtime
