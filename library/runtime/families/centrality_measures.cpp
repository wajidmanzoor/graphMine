#include <algorithm>
#include <cmath>
#include <numeric>
#include <queue>
#include <type_traits>

#include "exact_number.hpp"
#include "internal.hpp"

namespace graphmine::runtime {
namespace {
// Brandes accumulation with unbounded integer path counts and exact rational
// distances/dependencies. Positive weights ensure the predecessor DAG is acyclic.
std::vector<Exact> cpu_betweenness(const WeightedGraph& graph, bool weighted, Work& work) {
  const auto n = graph.rows.size();
  std::vector<Exact> scores(n, 0);
  if (n < 3) return scores;
  for (VertexIndex source = 0; source < n; ++source) {
    work.tick(n);
    std::vector<Integer> paths(n, 0);
    paths[source] = 1;
    std::vector<std::vector<VertexIndex>> predecessors(n);
    std::vector<VertexIndex> order;
    if (!weighted) {
      std::vector<std::int64_t> distance(n, -1);
      distance[source] = 0;
      std::queue<VertexIndex> queue;
      queue.push(source);
      while (!queue.empty()) {
        work.tick();
        const auto u = queue.front();
        queue.pop();
        order.push_back(u);
        for (const auto& arc : graph.rows[u]) {
          work.tick();
          const auto v = arc.target;
          if (distance[v] < 0) {
            distance[v] = distance[u] + 1;
            queue.push(v);
          }
          if (distance[v] == distance[u] + 1) {
            paths[v] += paths[u];
            predecessors[v].push_back(u);
          }
        }
      }
    } else {
      std::vector<std::optional<Exact>> distance(n);
      distance[source] = 0;
      using Item = std::pair<Exact, VertexIndex>;
      std::priority_queue<Item, std::vector<Item>, std::greater<Item>> queue;
      queue.emplace(0, source);
      while (!queue.empty()) {
        work.tick();
        const auto [cost, u] = queue.top();
        queue.pop();
        if (cost != *distance[u]) continue;
        order.push_back(u);
        for (const auto& arc : graph.rows[u]) {
          work.tick();
          const auto v = arc.target;
          const Exact candidate = cost + Exact(arc.weight);
          if (!distance[v] || candidate < *distance[v]) {
            distance[v] = candidate;
            paths[v] = 0;
            predecessors[v].clear();
            queue.emplace(candidate, v);
          }
          if (candidate == *distance[v]) {
            paths[v] += paths[u];
            predecessors[v].push_back(u);
          }
        }
      }
    }
    std::vector<Exact> dependency(n, 0);
    for (auto it = order.rbegin(); it != order.rend(); ++it) {
      work.tick();
      const auto v = *it;
      const Exact factor = (1 + dependency[v]) / Exact(paths[v]);
      for (const auto u : predecessors[v]) {
        work.tick();
        dependency[u] += Exact(paths[u]) * factor;
      }
      if (v != source) scores[v] += dependency[v];
    }
  }
  return scores;
}

template <class Number>
json::object output(const Graph& graph, const std::vector<Number>& scores, json::object parameters,
                    json::object definition, Work& work) {
  work.output(scores.size());
  work.tick(scores.size());
  json::array rows;
  for (VertexIndex v = 0; v < graph.vertex_count(); ++v) {
    json::object row{{"vertex", id_json(graph.external_id(v))}};
    if constexpr (std::is_same_v<Number, Exact>)
      exact_field(row, "score", scores[v]);
    else
      row["score"] = scores[v];
    rows.push_back(row);
  }
  std::vector<VertexIndex> order(scores.size());
  std::iota(order.begin(), order.end(), 0);
  std::sort(order.begin(), order.end(), [&](auto a, auto b) {
    return scores[a] != scores[b] ? scores[a] > scores[b]
                                  : graph.external_id(a) < graph.external_id(b);
  });
  json::array ranking;
  for (const auto v : order) {
    auto row = rows[v].as_object();
    row["rank"] = ranking.size() + 1;
    ranking.push_back(row);
  }
  definition["tie_break"] = "numeric IDs before strings, then ascending stored value";
  auto port = result_port("vertex_scores", rows);
  port["score_field"] = "score";
  if constexpr (std::is_same_v<Number, Exact>) port["exact_score_field"] = "score_exact";
  return {{"parameters", parameters},
          {"result",
           {{"vertices", rows},
            {"ranked_vertices", ranking},
            {"score_definition", definition},
            {"complete", true}}},
          {"ports", {{"scores", port}}},
          {"complete", true},
          {"quality", std::is_same_v<Number, Exact> ? "exact" : "numerical"}};
}
}  // namespace

json::object betweenness(const Graph& graph, const json::object& args, const std::string& backend,
                         int device, Work& work) {
  fields(args, {"normalized", "weight_mode"});
  const bool normalized = boolean(args, "normalized", true);
  const auto mode =
      args.contains("weight_mode") ? string(args.at("weight_mode"), "weight_mode") : "unweighted";
  require(mode == "unweighted" || mode == "edge_weight", "Unknown weight_mode");
  if (mode == "edge_weight")
    for (const auto& edge : graph.canonical().edges) {
      work.tick();
      require(edge.weight.value_or(1) > 0,
              "Weighted betweenness requires strictly positive edge lengths");
    }
  work.output(graph.vertex_count());
  const auto input = weighted_graph(graph, mode == "edge_weight", true, "min", "outgoing", work);
  const auto n = graph.vertex_count();
  // Both CPU and adapters supply ordered-pair accumulation. Undirected raw
  // scores divide by two; normalized scores divide by (n-1)(n-2) in both cases.
  Exact scale = graph.directed() ? Exact(1) : Exact(1) / 2;
  if (normalized) scale = n < 3 ? Exact(0) : Exact(1) / (Integer(n - 1) * (n - 2));
  const json::object parameters{{"normalized", normalized}, {"weight_mode", mode}};
  const json::object definition{
      {"centrality_measure", "betweenness"},
      {"direction_mode", graph.directed() ? "preserve" : "undirected"},
      {"weight_semantics", mode == "edge_weight" ? "positive_distance" : "unweighted"},
      {"normalized", normalized},
      {"include_endpoints", false},
      {"source_set", "all_vertices"},
      {"parallel_edges", "minimum_length"},
      {"self_loops", "discard"}};
  if (backend == "cpp") {
    auto scores = cpu_betweenness(input, mode == "edge_weight", work);
    for (auto& value : scores) {
      work.tick();
      value *= scale;
    }
    auto result = output(graph, scores, parameters, definition, work);
    result["diagnostics"] = json::object{
        {"arithmetic",
         "exact rational over admitted binary64 lengths; unbounded integer path counts"}};
    return result;
  }
  std::vector<double> scores;
  if (backend == "turbo-bc") {
    MiningGraph adjacency(input.rows.size());
    for (VertexIndex u = 0; u < input.rows.size(); ++u)
      for (const auto& arc : input.rows[u]) {
        work.tick();
        adjacency[u].push_back(arc.target);
      }
    scores = original_betweenness(adjacency, device, work);
  } else
    scores = cugraph_betweenness(input, device, work);
  require(scores.size() == n, "GPU betweenness returned an incomplete score vector");
  for (auto& value : scores) {
    work.tick();
    value *= scale.convert_to<double>();
    if (!std::isfinite(value) || value < 0)
      throw Failure("correctness_mismatch",
                    "GPU betweenness returned a non-finite or negative score");
  }
  auto result = output(graph, scores, parameters, definition, work);
  result["diagnostics"] = json::object{
      {"arithmetic",
       backend == "turbo-bc" ? "float32 upstream accumulation; float64 normalization" : "float64"},
      {"sampled", false}};
  return result;
}

json::object degree_centrality(const Graph& graph, const json::object& args, const std::string&,
                               int, Work& work) {
  fields(args, {"normalized", "direction_mode"});
  const bool normalized = boolean(args, "normalized", true);
  const auto direction = args.contains("direction_mode")
                             ? string(args.at("direction_mode"), "direction_mode")
                             : "outgoing";
  require(direction == "outgoing" || direction == "incoming" || direction == "both" ||
              direction == "undirected_projection",
          "Unknown direction_mode");
  work.output(graph.vertex_count());
  const auto input = weighted_graph(graph, false, false, "collapse",
                                    direction == "both" ? "outgoing" : direction, work);
  std::vector<Exact> scores(graph.vertex_count(), 0);
  for (VertexIndex u = 0; u < input.rows.size(); ++u) {
    work.tick(input.rows[u].size() + 1);
    scores[u] += input.rows[u].size();
    if (direction == "both" && graph.directed())
      for (const auto& arc : input.rows[u]) ++scores[arc.target];
  }
  if (normalized && graph.vertex_count() > 1)
    for (auto& score : scores) score /= graph.vertex_count() - 1;
  return output(graph, scores, {{"normalized", normalized}, {"direction_mode", direction}},
                {{"centrality_measure", "degree"},
                 {"direction_mode", direction},
                 {"weight_semantics", "unweighted"},
                 {"normalized", normalized},
                 {"normalization_denominator",
                  std::max<std::size_t>(1, graph.vertex_count() ? graph.vertex_count() - 1 : 0)},
                 {"parallel_edges", "collapse"},
                 {"self_loops", "discard"}},
                work);
}
}  // namespace graphmine::runtime
