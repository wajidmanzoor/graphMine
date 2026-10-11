#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <queue>
#include <set>

#include "exact_number.hpp"
#include "internal.hpp"
#include "representation_cache.hpp"

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
static WeightedGraph build_weighted_graph(const Graph& graph, bool weighted, bool nonnegative,
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

WeightedGraph weighted_graph(const Graph& graph, bool weighted, bool nonnegative,
                             const std::string& aggregation, const std::string& direction,
                             Work& work) {
  const auto build = [&] {
    return build_weighted_graph(graph, weighted, nonnegative, aggregation, direction, work);
  };
  if (work.input_graph != &graph) return build();
  const auto semantics = std::string(weighted ? "weighted:" : "unit:") +
                         (nonnegative ? "nonnegative:" : "signed:") + aggregation + ":" + direction;
  return cached_weighted_graph(semantics, work, build);
}

std::string gpu_support_reason(const std::string& operation, const Graph& graph,
                               const json::object& args) {
  if (operation == "induced-subgraph" && args.contains("mode") && args.at("mode") == "induced")
    return "Explicit induced selection uses native CPU; GPU supports ego discovery";
  if (operation == "betweenness-centrality" && args.contains("weight_mode") &&
      args.at("weight_mode") == "edge_weight")
    return "Native GPU betweenness profiles support unweighted paths; positive weighted paths use "
           "exact C++ CPU code";
  if (operation == "link-prediction" && args.contains("scoring_measure") &&
      args.at("scoring_measure") != "jaccard")
    return "The native libcugraph link-prediction profile supports Jaccard; the other measures use "
           "C++ CPU code";
  if (operation == "personalized-pagerank" && args.contains("dangling_policy") &&
      args.at("dangling_policy") == "redistribute_uniformly")
    return "The native libcugraph personalized PageRank profile does not expose custom dangling "
           "weights";
  if (operation == "single-source-shortest-paths" || operation == "many-source-shortest-paths") {
    const bool weighted = operation == "single-source-shortest-paths" ||
                          !args.contains("weight_mode") || args.at("weight_mode") == "edge_weight";
    if (!weighted) return {};
    bool integral = true;
    double maximum = 0;
    for (const auto& edge : graph.canonical().edges) {
      const auto weight = edge.weight.value_or(1);
      integral = integral && std::trunc(weight) == weight;
      maximum = std::max(maximum, std::abs(weight));
    }
    const auto bound =
        static_cast<long double>(maximum) *
        std::max<std::size_t>(1, graph.vertex_count() ? graph.vertex_count() - 1 : 0);
    if (bound >= std::numeric_limits<double>::max())
      return "Path costs may reach the float64 unreachable sentinel or overflow; use the native "
             "CPU implementation";
    if (integral && bound > 9007199254740992.0L)
      return "Integer path costs may exceed exact float64 range; use the native CPU implementation";
  }
  return {};
}
std::string backend_support_reason(const std::string& operation, const std::string& backend,
                                   const Graph& graph, const json::object& args, Work& work) {
  if (backend == "cpp") return {};
  if (operation == "random-walks") {
    const auto model = args.contains("walk_model") ? args.at("walk_model") : json::value("uniform");
    if (model == "node2vec")
      return "Node2vec uses exact native CPU: the linked cuGraph bias operator does not implement "
             "weighted node2vec probabilities";
    if (model == "weighted") {
      std::vector<std::map<VertexIndex, Exact>> rows(graph.vertex_count());
      work.tick(graph.vertex_count());
      for (const auto& edge : graph.canonical().edges) {
        work.tick();
        const auto weight = edge.weight.value_or(1);
        if (weight < 0) return {};
        const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
        rows[u][v] += Exact(weight);
        if (!graph.directed() && u != v) rows[v][u] += Exact(weight);
      }
      for (const auto& row : rows) {
        Exact maximum = 0;
        for (const auto& [v, w] : row) {
          work.tick();
          maximum = std::max(maximum, w);
        }
        for (const auto& [v, w] : row) {
          work.tick();
          if (w > 0 && (w / maximum).convert_to<double>() == 0)
            return "A positive GPU walk probability underflows float64; exact rational sampling "
                   "uses native CPU";
        }
      }
    }
  }
  if (operation == "max-flow-min-cut") {
    if (graph.vertex_count() > 1000000 || graph.edge_count() > 10000000)
      return "ECL flow supports at most 1M vertices and 10M input edges";
    if (args.contains("vertex_capacities") && !args.at("vertex_capacities").is_null() &&
        (!args.at("vertex_capacities").is_array() ||
         !args.at("vertex_capacities").as_array().empty()))
      return "The ECL GPU flow profile does not support vertex capacities; use native CPU";
    const bool unit = args.contains("capacity_mode") && args.at("capacity_mode") == "unit_capacity";
    Exact total = 0;
    for (const auto& edge : graph.canonical().edges) {
      work.tick();
      if (!unit && !edge.weight) return {};  // Shared parameter validation reports missing weights.
      const double value = unit ? 1 : *edge.weight;
      if (value < 0) return {};
      if (std::trunc(value) != value)
        return "ECL GPU flow supports integral capacities; fractional capacities use exact native "
               "CPU";
      if (edge.source != edge.target) total += Exact(value) * (graph.directed() ? 1 : 2);
      if (total > 1000000000)
        return "ECL GPU flow requires total normalized capacity <=1e9 to prevent int32 overflow; "
               "use native CPU";
    }
  }
  if (operation == "bipartite-matching") {
    if ((args.contains("objective") && !args.at("objective").is_string()) ||
        (args.contains("perfect_matching_required") &&
         !args.at("perfect_matching_required").is_bool()))
      return {};
    if (!args.contains("objective") || args.at("objective") != "minimum_cost" ||
        !args.contains("perfect_matching_required") || args.at("perfect_matching_required") != true)
      return "Hungarian CUDA supports minimum-cost matching with required perfect coverage; other "
             "objectives use native CPU";
    std::vector<bool> left;
    std::size_t count = 0;
    for (const auto& vertex : graph.canonical().vertices) {
      work.tick();
      const auto found = vertex.attributes.find("side");
      if (found == vertex.attributes.end() ||
          !std::holds_alternative<std::string>(found->second.value()))
        return {};
      const auto& side = std::get<std::string>(found->second.value());
      if (side != "left" && side != "right") return {};
      left.push_back(side == "left");
      count += left.back();
    }
    if (count * 2 != graph.vertex_count() || count > 64)
      return "Hungarian CUDA requires equal sides with at most 64 vertices each";
    std::set<std::pair<VertexIndex, VertexIndex>> pairs;
    for (const auto& edge : graph.canonical().edges) {
      work.tick();
      if (!edge.weight) return {};
      if (*edge.weight < 0 || *edge.weight > 999 || std::trunc(*edge.weight) != *edge.weight)
        return "Hungarian CUDA requires every input cost to be an integer in [0,999]; use native "
               "CPU";
      auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
      if (left[u] == left[v]) return {};
      if (!left[u]) std::swap(u, v);
      pairs.emplace(u, v);
    }
    if (pairs.size() != count * count)
      return "Hungarian CUDA requires a complete bipartite graph; sparse matching uses native CPU";
  }
  if (operation == "betweenness-centrality" && backend == "turbo-bc" && graph.directed())
    return "The original TurboBC profile supports undirected graphs; use libcugraph or C++ for "
           "directed betweenness";
  if (operation == "betweenness-centrality" && graph.vertex_count() > 32) {
    // Both linked GPU profiles use signed int32 shortest-path counters, even
    // though their returned scores are floating point. A simple shortest path
    // is determined by its interior vertex subset, so n<=32 is safe outright.
    // For larger graphs, bounded BFS admission detects overflow before CUDA.
    const auto input = weighted_graph(graph, false, false, "collapse", "outgoing", work);
    for (VertexIndex source = 0; source < input.rows.size(); ++source) {
      work.tick(input.rows.size());
      std::vector<std::int64_t> distance(input.rows.size(), -1);
      std::vector<std::uint64_t> paths(input.rows.size(), 0);
      std::queue<VertexIndex> queue;
      queue.push(source);
      paths[source] = 1;
      distance[source] = 0;
      while (!queue.empty()) {
        work.tick();
        const auto u = queue.front();
        queue.pop();
        for (const auto& arc : input.rows[u]) {
          work.tick();
          const auto v = arc.target;
          if (distance[v] < 0) {
            distance[v] = distance[u] + 1;
            queue.push(v);
          }
          if (distance[v] == distance[u] + 1) {
            paths[v] += paths[u];
            if (paths[v] > INT32_MAX)
              return "The GPU shortest-path counter would exceed signed int32; use exact native "
                     "C++ betweenness";
          }
        }
      }
    }
  }
  std::uint64_t k = 0;
  if (operation == "k-cliques") {
    if (!args.contains("k") ||
        !(args.at("k").is_uint64() || (args.at("k").is_int64() && args.at("k").as_int64() >= 0)))
      return {};
    k = uint(args.at("k"), "k");
    if (k > graph.vertex_count()) return {};  // Exact empty boundary; no kernel launch.
    const unsigned maximum = backend == "graphset" ? 6 : backend == "gamma" ? 7 : 10;
    if (k < 3 || k > maximum)
      return "The " + backend + " count kernel supports 3 <= k <= " + std::to_string(maximum) +
             "; native CPU has no upper k bound";
  }
  if (graph.directed() || (operation != "maximal-cliques" && operation != "k-cliques")) return {};
  // Every nonempty clique has one first vertex in this ordering. Counting
  // all possible forward subsets bounds both fixed-size and maximal counts.
  work.tick(graph.vertex_count() + graph.canonical().edges.size());
  const auto simple = graph.simple_undirected({});
  Integer bound = 0;
  for (VertexIndex v = 0; v < simple.csr.vertex_count(); ++v) {
    work.tick(simple.csr.offsets[v + 1] - simple.csr.offsets[v] + 1);
    std::size_t degree = 0;
    for (auto i = simple.csr.offsets[v]; i < simple.csr.offsets[v + 1]; ++i)
      degree += simple.csr.neighbors[i] > v;
    Integer choices = 1;
    if (operation == "maximal-cliques") {
      if (degree >= 64)
        return "Cannot certify that the original maximal-clique count fits uint64; use native CPU";
      choices <<= degree;
    } else {
      if (degree < k - 1) continue;
      for (std::uint64_t j = 1; j < k; ++j) choices = choices * (degree - j + 1) / j;
    }
    bound += choices;
    if (bound > UINT64_MAX)
      return "Cannot certify that the original clique count fits uint64; use native CPU";
  }
  return {};
}
}  // namespace graphmine::runtime
