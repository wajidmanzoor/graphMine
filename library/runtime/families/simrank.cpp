#include "family_util.hpp"
#include "numeric.hpp"

namespace graphmine::runtime {
json::object simrank(const Graph& graph, const json::object& args, const std::string&, int,
                     Work& work) {
  using namespace family_util;
  fields(args,
         {"query_mode", "source_vertex", "target_vertex", "decay_factor", "direction_mode", "top_k",
          "solution_quality", "convergence_tolerance", "max_iterations"},
         {"query_mode"});
  const auto mode = choice(args, "query_mode", "single_pair",
                           {"single_pair", "single_source_all", "top_k_pairs"});
  const auto direction =
      choice(args, "direction_mode", "incoming", {"incoming", "undirected_projection"});
  const auto quality = choice(args, "solution_quality", "exact", {"exact", "approximate"});
  const auto cap = limit(args, "top_k");
  const auto iterations = natural(args, "max_iterations", 1000, 1);
  const auto tol = numeric::tolerance(args, "convergence_tolerance");
  const double decay =
      args.contains("decay_factor") ? number(args.at("decay_factor"), "decay_factor") : 0.8;
  require(decay > 0 && decay < 1, "SimRank requires 0 < decay_factor < 1");
  std::optional<VertexIndex> source, target;
  if (args.contains("source_vertex") && !args.at("source_vertex").is_null())
    source = graph.dense_index(external_id(args.at("source_vertex")));
  if (args.contains("target_vertex") && !args.at("target_vertex").is_null())
    target = graph.dense_index(external_id(args.at("target_vertex")));
  require((mode != "top_k_pairs") == source.has_value(),
          "source_vertex is required only for single-pair or single-source queries");
  require((mode == "single_pair") == target.has_value(),
          "target_vertex is required only for single_pair");
  require(mode != "single_pair" || !cap, "top_k does not apply to single_pair");
  const auto n = graph.vertex_count();
  MiningGraph neighbors(n);
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    neighbors[v].push_back(u);
    if (!graph.directed() || direction == "undirected_projection") neighbors[u].push_back(v);
  }
  for (auto& row : neighbors) {
    std::sort(row.begin(), row.end());
    row.erase(std::unique(row.begin(), row.end()), row.end());
  }
  auto values = numeric::identity(n, work);
  numeric::Matrix temporary(n, n, work), updated(n, n, work);
  double residual = 0;
  std::uint64_t used = 0;
  bool converged = n == 0;
  for (std::uint64_t iteration = 0; iteration <= iterations && n; ++iteration) {
    for (std::size_t u = 0; u < n; ++u)
      for (std::size_t v = 0; v < n; ++v) {
        work.tick(neighbors[u].size() + 1);
        long double total = 0;
        for (const auto a : neighbors[u]) total += values(a, v);
        temporary(u, v) = neighbors[u].empty() ? 0 : numeric::finite(total / neighbors[u].size());
      }
    residual = 0;
    for (std::size_t u = 0; u < n; ++u)
      for (std::size_t v = u; v < n; ++v) {
        work.tick(neighbors[v].size() + 1);
        long double total = 0;
        for (const auto b : neighbors[v]) total += temporary(u, b);
        const double value =
            u == v ? 1
            : neighbors[v].empty()
                ? 0
                : std::clamp(numeric::finite(decay * total / neighbors[v].size()), 0.0, 1.0);
        updated(u, v) = updated(v, u) = value;
        residual = std::max(residual, std::abs(value - values(u, v)));
      }
    if (residual / (1 - decay) <= tol) {
      converged = true;
      used = iteration;
      break;
    }
    if (iteration < iterations) values = updated;
  }
  if (!converged)
    throw Failure("numerical_failure",
                  "SimRank fixed-point error exceeds tolerance within max_iterations");
  std::vector<std::pair<VertexIndex, VertexIndex>> pairs;
  if (mode == "single_pair")
    pairs.emplace_back(*source, *target);
  else if (mode == "single_source_all") {
    for (VertexIndex v = 0; v < n; ++v)
      if (v != *source) pairs.emplace_back(*source, v);
  } else {
    auto ordered = all_vertices(graph);
    std::sort(ordered.begin(), ordered.end(),
              [&](auto u, auto v) { return graph.external_id(u) < graph.external_id(v); });
    work.tick(n * (n ? n - 1 : 0) / 2);
    for (std::size_t i = 0; i < n; ++i)
      for (std::size_t j = i + 1; j < n; ++j) pairs.emplace_back(ordered[i], ordered[j]);
  }
  std::sort(pairs.begin(), pairs.end(), [&](const auto& a, const auto& b) {
    work.tick();
    if (values(a.first, a.second) != values(b.first, b.second))
      return values(a.first, a.second) > values(b.first, b.second);
    if (graph.external_id(a.first) != graph.external_id(b.first))
      return graph.external_id(a.first) < graph.external_id(b.first);
    return graph.external_id(a.second) < graph.external_id(b.second);
  });
  const auto total = pairs.size();
  if (cap && *cap < pairs.size()) pairs.resize(*cap);
  work.output(pairs.size());
  json::array rows;
  for (const auto& [u, v] : pairs)
    rows.push_back(json::object{{"source", id_json(graph.external_id(u))},
                                {"target", id_json(graph.external_id(v))},
                                {"similarity", values(u, v)}});
  auto result = output(
      {{"query_mode", mode},
       {"source_vertex", source ? id_json(graph.external_id(*source)) : json::value(nullptr)},
       {"target_vertex", target ? id_json(graph.external_id(*target)) : json::value(nullptr)},
       {"decay_factor", decay},
       {"direction_mode", direction},
       {"top_k", cap ? json::value(*cap) : json::value(nullptr)},
       {"solution_quality", quality},
       {"convergence_tolerance", tol},
       {"max_iterations", iterations}},
      {{"similarity_scores", rows},
       {"scored_pair_count", total},
       {"complete", true},
       {"error_bound", residual / (1 - decay)}},
      {{"pairs", result_port("pair_scores", rows, rows.size() == total)}}, true, "numerical");
  result["diagnostics"] = json::object{{"solver", "native_simrank_fixed_point"},
                                       {"residual_max", residual},
                                       {"absolute_error_bound", residual / (1 - decay)},
                                       {"iterations", used},
                                       {"single_source_includes_self", false}};
  return result;
}
}  // namespace graphmine::runtime
