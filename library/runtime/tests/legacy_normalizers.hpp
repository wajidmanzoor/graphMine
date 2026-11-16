#pragma once
// Frozen from a38d1dcb for equivalence tests only. Never linked into production.
#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include "../internal.hpp"
namespace graphmine::legacy_test {
using namespace graphmine::runtime;
inline UndirectedGraphView simple(const Graph& graph, UndirectedProjectionOptions options = {}) {
  if (graph.canonical().graph.directed && !options.allow_directed_projection) {
    throw std::invalid_argument(
        "undirected algorithm received directed input without an explicit projection");
  }

  UndirectedGraphView view;
  view.normalization.directed_projection_applied = graph.canonical().graph.directed;

  std::set<std::pair<VertexIndex, VertexIndex>> unique_edges;
  for (const auto& edge : graph.canonical().edges) {
    auto source = graph.dense_index(edge.source);
    auto target = graph.dense_index(edge.target);
    if (source == target) {
      ++view.normalization.self_loops_removed;
      continue;
    }
    if (target < source) {
      std::swap(source, target);
    }
    if (!unique_edges.emplace(source, target).second) {
      ++view.normalization.parallel_edges_collapsed;
    }
  }

  std::vector<std::vector<VertexIndex>> adjacency(graph.vertex_count());
  for (const auto& [source, target] : unique_edges) {
    adjacency[source].push_back(target);
    adjacency[target].push_back(source);
  }

  view.csr.offsets.resize(graph.vertex_count() + 1, 0);
  for (std::size_t vertex = 0; vertex < adjacency.size(); ++vertex) {
    std::sort(adjacency[vertex].begin(), adjacency[vertex].end());
    view.csr.offsets[vertex + 1] =
        view.csr.offsets[vertex] + adjacency[vertex].size();
    view.csr.neighbors.insert(view.csr.neighbors.end(),
                              adjacency[vertex].begin(),
                              adjacency[vertex].end());
  }
  return view;
}

inline WeightedGraph weighted(const Graph& graph, bool weighted, bool nonnegative,
                                          const std::string& aggregation,
                                          const std::string& direction, Work& work) {
  work.tick(graph.vertex_count());
  std::vector<std::map<VertexIndex, double>> rows(graph.vertex_count());
  const bool directed = graph.directed() && direction != "undirected_projection";
  auto add = [&](VertexIndex u, VertexIndex v, double weight) {
    work.tick();
    const auto found = rows[u].emplace(v, weight);
    if (found.second) return;
    auto& previous = found.first->second;
    if (aggregation == "min")
      previous = std::min(previous, weight);
    else if (aggregation == "max")
      previous = std::max(previous, weight);
    else if (aggregation == "sum")
      previous += weight;
    require(std::isfinite(previous), "Aggregated edge weight overflowed");
  };
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    const double weight = weighted ? edge.weight.value_or(1) : 1;
    require(!nonnegative || weight >= 0, "This operation requires nonnegative edge weights");
    auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    if (direction == "incoming" && directed) std::swap(u, v);
    add(u, v, weight);
    if (!directed) add(v, u, weight);
  }
  WeightedGraph result{std::vector<std::vector<Arc>>(rows.size()), directed};
  for (VertexIndex u = 0; u < rows.size(); ++u)
    for (const auto& [v, weight] : rows[u]) result.rows[u].push_back({v, weight});
  return result;
}

inline std::vector<std::vector<VertexIndex>> adjacency(const Graph& graph, Work& work) {
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
}  // namespace graphmine::legacy_test
