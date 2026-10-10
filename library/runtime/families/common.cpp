#include "internal.hpp"

#include <algorithm>
#include <cmath>
#include <map>
#include <limits>

namespace graphmine::runtime {
double number(const json::value& value, const std::string& context) {
  require(value.is_number(), context + " must be numeric");
  const auto result = value.to_number<double>();
  require(std::isfinite(result), context + " must be finite");
  return result;
}
bool boolean(const json::object& values, const char* key, bool initial) {
  if (!values.contains(key)) return initial;
  require(values.at(key).is_bool(), std::string(key) + " must be boolean");
  return values.at(key).as_bool();
}
json::object result_port(const char* type, json::value value, bool complete) {
  return {{"type", type}, {"value", std::move(value)}, {"complete", complete}};
}
WeightedGraph weighted_graph(const Graph& graph, bool weighted, bool nonnegative,
                             const std::string& aggregation, const std::string& direction,
                             Work& work) {
  work.tick(graph.vertex_count());
  std::vector<std::map<VertexIndex, double>> rows(graph.vertex_count());
  const bool directed = graph.directed() && direction != "undirected_projection";
  auto add = [&](VertexIndex u, VertexIndex v, double weight) {
    work.tick();
    const auto found = rows[u].emplace(v, weight);
    if (found.second) return;
    auto& previous = found.first->second;
    if (aggregation == "min") previous = std::min(previous, weight);
    else if (aggregation == "max") previous = std::max(previous, weight);
    else if (aggregation == "sum") previous += weight;
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

std::string gpu_support_reason(const std::string& operation, const Graph& graph, const json::object& args) {
  if (operation == "link-prediction" && args.contains("scoring_measure") && args.at("scoring_measure") != "jaccard")
    return "The native libcugraph link-prediction profile supports Jaccard; the other measures use C++ CPU code";
  if (operation == "personalized-pagerank" && args.contains("dangling_policy") && args.at("dangling_policy") == "redistribute_uniformly")
    return "The native libcugraph personalized PageRank profile does not expose custom dangling weights";
  if (operation == "single-source-shortest-paths" || operation == "many-source-shortest-paths") {
    const bool weighted = operation == "single-source-shortest-paths" || !args.contains("weight_mode") || args.at("weight_mode") == "edge_weight";
    if (!weighted) return {};
    bool integral = true;
    double maximum = 0;
    for (const auto& edge : graph.canonical().edges) {
      const auto weight = edge.weight.value_or(1);
      integral = integral && std::trunc(weight) == weight;
      maximum = std::max(maximum, std::abs(weight));
    }
    const auto bound = static_cast<long double>(maximum) * std::max<std::size_t>(1, graph.vertex_count() ? graph.vertex_count() - 1 : 0);
    if (bound >= std::numeric_limits<double>::max())
      return "Path costs may reach the float64 unreachable sentinel or overflow; use the native CPU implementation";
    if (integral && bound > 9007199254740992.0L)
      return "Integer path costs may exceed exact float64 range; use the native CPU implementation";
  }
  return {};
}
}  // namespace graphmine::runtime
