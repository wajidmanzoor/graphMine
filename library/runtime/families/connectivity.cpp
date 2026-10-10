#include "internal.hpp"

#include <algorithm>
#include <numeric>
#include <queue>

namespace graphmine::runtime {
namespace {
std::vector<std::vector<VertexIndex>> cpu_components(const WeightedGraph& graph, bool strong, Work& work) {
  const auto n = graph.rows.size();
  std::vector<bool> seen(n, false);
  std::vector<VertexIndex> order;
  for (VertexIndex root = 0; root < n; ++root) {
    if (seen[root]) continue;
    std::vector<std::pair<VertexIndex, std::size_t>> stack{{root, 0}};
    seen[root] = true;
    while (!stack.empty()) {
      work.tick();
      auto& [u, position] = stack.back();
      if (position == graph.rows[u].size()) { order.push_back(u); stack.pop_back(); continue; }
      const auto v = graph.rows[u][position++].target;
      if (!seen[v]) { seen[v] = true; stack.emplace_back(v, 0); }
    }
  }
  std::vector<std::vector<VertexIndex>> reverse(n);
  for (VertexIndex u = 0; u < n; ++u) for (const auto& arc : graph.rows[u]) {
    work.tick(); reverse[arc.target].push_back(u);
  }
  std::fill(seen.begin(), seen.end(), false);
  if (strong) std::reverse(order.begin(), order.end());
  else { std::iota(order.begin(), order.end(), 0); }
  std::vector<std::vector<VertexIndex>> result;
  for (const auto root : order) {
    if (seen[root]) continue;
    std::vector<VertexIndex> members, stack{root}; seen[root] = true;
    while (!stack.empty()) {
      work.tick(); const auto u = stack.back(); stack.pop_back(); members.push_back(u);
      for (const auto v : reverse[u]) { work.tick(); if (!seen[v]) { seen[v] = true; stack.push_back(v); } }
    }
    result.push_back(std::move(members));
  }
  return result;
}
}

json::object components(const Graph& graph, const json::object& args, const std::string& backend, int device, Work& work) {
  fields(args, {"connectivity_mode"});
  const auto mode = args.contains("connectivity_mode") ? string(args.at("connectivity_mode"), "connectivity_mode") : "weakly_connected";
  require(mode == "weakly_connected" || mode == "strongly_connected", "Unknown connectivity_mode");
  const bool strong = mode == "strongly_connected" && graph.directed();
  work.output(graph.vertex_count());
  const auto input = weighted_graph(graph, false, false, "collapse", strong ? "outgoing" : "undirected_projection", work);
  auto groups = backend == "cpp" ? cpu_components(input, strong, work) : cugraph_components(input, strong, device, work);
  for (auto& members : groups) std::sort(members.begin(), members.end());
  std::sort(groups.begin(), groups.end(), [](const auto& a, const auto& b) { return a.size() != b.size() ? a.size() > b.size() : a < b; });
  json::array rows;
  for (const auto& group : groups) {
    json::array members;
    for (const auto v : group) members.push_back(id_json(graph.external_id(v)));
    rows.push_back(json::object{{"group", rows.size()}, {"vertices", members}, {"size", members.size()}});
  }
  return {{"parameters", {{"connectivity_mode", mode}}}, {"result", {{"groups", rows}, {"count", rows.size()}}},
          {"ports", {{"groups", result_port("vertex_groups", rows)}}}, {"complete", true}, {"quality", "exact"}};
}

json::object topological(const Graph& graph, const json::object& args, const std::string&, int, Work& work) {
  fields(args, {});
  require(graph.directed(), "Topological sorting requires a directed graph");
  work.output(graph.vertex_count());
  for (const auto& edge : graph.canonical().edges) require(edge.source != edge.target, "A self-loop is a directed cycle; no topological ordering exists");
  const auto adj = adjacency(graph, work);
  std::vector<std::size_t> degree(graph.vertex_count(), 0);
  for (const auto& row : adj) for (const auto v : row) { work.tick(); ++degree[v]; }
  std::priority_queue<VertexIndex, std::vector<VertexIndex>, std::greater<VertexIndex>> ready;
  for (VertexIndex v = 0; v < degree.size(); ++v) if (!degree[v]) ready.push(v);
  json::array order;
  while (!ready.empty()) {
    work.tick(); const auto u = ready.top(); ready.pop(); order.push_back(id_json(graph.external_id(u)));
    for (const auto v : adj[u]) { work.tick(); if (--degree[v] == 0) ready.push(v); }
  }
  require(order.size() == graph.vertex_count(), "The graph has a directed cycle; no topological ordering exists");
  return {{"parameters", json::object{}}, {"result", {{"order", order}}},
          {"ports", {{"vertices", result_port("vertex_set", order)}}}, {"complete", true}, {"quality", "exact"}};
}
}  // namespace graphmine::runtime
