#pragma once
// Frozen from a38d1dcb for equivalence tests only. Never linked into production.
#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include "../internal.hpp"
#include "../exact_number.hpp"
#include "../pattern_match.hpp"
#include "../numeric.hpp"
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
// Frozen exact edge-list normalizer from 0d4986de. Keep independent of the new
// factory and layout decoder so a policy/rounding change cannot bless itself.
struct ExactEdge { VertexIndex u, v; Exact weight; std::size_t original; };
inline std::vector<ExactEdge> exact_edges(const Graph& graph, bool weighted, Work& work,
                                         bool nonnegative = true, bool loops = false) {
  std::map<std::pair<VertexIndex, VertexIndex>, ExactEdge> normalized;
  for (std::size_t i = 0; i < graph.edge_count(); ++i) {
    work.tick();
    const auto& raw = graph.canonical().edges[i];
    auto u = graph.dense_index(raw.source), v = graph.dense_index(raw.target);
    Exact weight = weighted ? Exact(raw.weight.value_or(1)) : Exact(1);
    require(!nonnegative || weight >= 0, "Weights must be nonnegative");
    if (u == v && !loops) continue;
    if (!graph.directed() && u > v) std::swap(u, v);
    auto [it, inserted] = normalized.emplace(std::make_pair(u, v), ExactEdge{u, v, weight, i});
    if (!inserted && weighted) it->second.weight += weight;
  }
  std::vector<ExactEdge> output;
  for (auto& entry : normalized) output.push_back(std::move(entry.second));
  return output;
}
// Frozen SimRank incoming-neighbor builder from 0d4986de.
inline MiningGraph simrank(const Graph& graph, bool project, Work& work) {
  MiningGraph neighbors(graph.vertex_count());
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    neighbors[v].push_back(u);
    if (!graph.directed() || project) neighbors[u].push_back(v);
  }
  for (auto& row : neighbors) {
    std::sort(row.begin(), row.end());
    row.erase(std::unique(row.begin(), row.end()), row.end());
  }
  return neighbors;
}
// Frozen record-query Index constructor from b80b1071. Record JSON conversion
// is part of the unchanged common front, not view normalization.
struct RecordIndex {
  const Graph& graph;
  std::vector<json::object> vertices, edges;
  std::vector<std::vector<std::size_t>> outgoing, incoming;
  std::vector<std::pair<VertexIndex, VertexIndex>> endpoints;
  std::map<ExternalId, std::size_t> edge_indices;
  RecordIndex(const Graph& input, Work& work)
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
};
// Frozen force-layout input preparation from 06dc4cf3. In particular, every
// addition uses a long-double intermediate and rounds back to double at once.
struct ForceLayoutInput { numeric::Matrix weights, positions; };
inline ForceLayoutInput force_layout_input(const Graph& graph, bool weighted,
                                           std::size_t dimensions, Work& work) {
  const auto n = graph.vertex_count();
  ForceLayoutInput input{numeric::Matrix(n,n,work),numeric::Matrix(n,dimensions,work)};
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    require(!weighted || edge.weight.has_value(), "Weighted layout requires every edge weight");
    const double value = weighted ? *edge.weight : 1;
    require(value >= 0, "Layout weights must be nonnegative");
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    input.weights(u,v) = input.weights(v,u) = weighted
      ? numeric::finite(static_cast<long double>(input.weights(u,v)) + value) : 1;
  }
  return input;
}
}  // namespace graphmine::legacy_test
