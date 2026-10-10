#include "internal.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <set>

namespace graphmine::runtime {
namespace {
struct RankResult { std::vector<double> values; double residual = 0; };
RankResult rank(WeightedGraph input, const std::vector<double>& teleport,
                const std::vector<double>& dangling, double alpha, double tolerance,
                std::uint64_t iterations, const std::string& backend, int device, Work& work) {
  const auto n = input.rows.size();
  if (!n) return {};
  // Scale each row first. Long-double sums avoid overflow when several finite
  // outgoing weights are close to DBL_MAX. Both solvers see these same values.
  for (auto& row : input.rows) {
    long double total = 0;
    for (const auto& arc : row) { work.tick(); total += arc.weight; }
    if (total > 0) for (auto& arc : row) arc.weight = static_cast<double>(arc.weight / total);
    row.erase(std::remove_if(row.begin(), row.end(), [](const Arc& arc) { return arc.weight == 0; }), row.end());
  }
  // Row normalization generally gives reciprocal arcs different transition
  // probabilities, even when the original graph was undirected.
  input.directed = true;
  auto step = [&](const std::vector<double>& values) {
    work.tick(n);
    std::vector<long double> accumulated(n, 0);
    long double lost = 0;
    for (VertexIndex u = 0; u < n; ++u) {
      if (input.rows[u].empty()) lost += values[u];
      for (const auto& arc : input.rows[u]) { work.tick(); accumulated[arc.target] += static_cast<long double>(values[u]) * arc.weight; }
    }
    std::vector<double> next(n);
    for (VertexIndex v = 0; v < n; ++v)
      next[v] = static_cast<double>(alpha * (accumulated[v] + lost * dangling[v]) + (1 - alpha) * teleport[v]);
    return next;
  };
  const double accepted = std::max(tolerance, 1e-12);
  std::vector<double> values(n, 1.0 / n);
  if (alpha == 0) values = teleport;
  else if (backend != "cpp") values = cugraph_pagerank(input, teleport, alpha, tolerance, iterations, device, work);
  else {
    bool converged = false;
    for (std::uint64_t iteration = 0; iteration < iterations; ++iteration) {
      auto next = step(values);
      long double difference = 0;
      for (VertexIndex v = 0; v < n; ++v) difference += std::abs(static_cast<long double>(next[v]) - values[v]);
      values = std::move(next);
      if (difference <= accepted) { converged = true; break; }
    }
    if (!converged) throw Failure("convergence_failure", "Native PageRank did not converge within max_iterations");
  }
  require(values.size() == n, "PageRank returned an incomplete score vector");
  long double mass = 0;
  for (const auto value : values) {
    require(std::isfinite(value) && value >= 0, "PageRank returned an invalid score"); mass += value;
  }
  if (std::abs(mass - 1) > std::max(accepted, 1e-10)) throw Failure("convergence_failure", "PageRank probability mass is not one");
  const auto next = step(values);
  long double residual = 0;
  for (VertexIndex v = 0; v < n; ++v) residual += std::abs(static_cast<long double>(next[v]) - values[v]);
  if (residual > accepted) throw Failure("convergence_failure", "PageRank fixed-point residual exceeds the requested tolerance");
  return {std::move(values), static_cast<double>(residual)};
}
json::object score_output(const Graph& graph, const RankResult& computed, json::object parameters,
                          double alpha, double tolerance) {
  json::array rows;
  for (VertexIndex v = 0; v < graph.vertex_count(); ++v)
    rows.push_back(json::object{{"vertex", id_json(graph.external_id(v))}, {"score", computed.values[v]}});
  auto port = result_port("vertex_scores", rows); port["score_field"] = "score";
  return {{"parameters", parameters}, {"result", {{"vertices", rows}}}, {"ports", {{"scores", port}}},
          {"complete", true}, {"quality", "numerical"},
          {"diagnostics", {{"fixed_point_residual_l1", computed.residual},
                            {"l1_error_bound", computed.residual / (1 - alpha)},
                            {"tolerance", tolerance}, {"accepted_residual", std::max(tolerance, 1e-12)}}}};
}
void validate(double alpha, double tolerance, std::uint64_t iterations) {
  require(alpha >= 0 && alpha < 1, "PageRank alpha must be in [0, 1)");
  require(tolerance > 0 && iterations > 0, "Tolerance and max_iterations must be positive");
}
}

json::object pagerank(const Graph& graph, const json::object& args, const std::string& backend, int device, Work& work) {
  fields(args, {"alpha", "tolerance", "max_iterations", "weight_mode"});
  const auto alpha = args.contains("alpha") ? number(args.at("alpha"), "alpha") : 0.85;
  const auto tolerance = args.contains("tolerance") ? number(args.at("tolerance"), "tolerance") : 1e-9;
  const auto iterations = args.contains("max_iterations") ? uint(args.at("max_iterations"), "max_iterations") : 1000;
  const auto mode = args.contains("weight_mode") ? string(args.at("weight_mode"), "weight_mode") : "unweighted";
  require(mode == "unweighted" || mode == "edge_weight", "Unknown weight_mode");
  validate(alpha, tolerance, iterations); work.output(graph.vertex_count());
  const auto input = weighted_graph(graph, mode == "edge_weight", true, "sum", "outgoing", work);
  const std::vector<double> uniform(graph.vertex_count(), graph.vertex_count() ? 1.0 / graph.vertex_count() : 0);
  const auto computed = rank(input, uniform, uniform, alpha, tolerance, iterations, backend, device, work);
  auto output = score_output(graph, computed, {{"alpha", alpha}, {"tolerance", tolerance}, {"max_iterations", iterations}, {"weight_mode", mode}}, alpha, tolerance);
  std::vector<VertexIndex> order(graph.vertex_count()); std::iota(order.begin(), order.end(), 0);
  std::sort(order.begin(), order.end(), [&](auto a, auto b) {
    return computed.values[a] != computed.values[b] ? computed.values[a] > computed.values[b] : graph.external_id(a) < graph.external_id(b);
  });
  json::array ranking;
  for (const auto v : order) ranking.push_back(json::object{{"vertex", id_json(graph.external_id(v))}, {"score", computed.values[v]}, {"rank", ranking.size() + 1}});
  auto& result = output.at("result").as_object(); result["ranked_vertices"] = ranking; result["complete"] = true;
  result["score_definition"] = json::object{{"centrality_measure", "pagerank"}, {"direction_mode", graph.directed() ? "outgoing" : "undirected"},
      {"weight_semantics", mode == "edge_weight" ? "strength" : "unweighted"}, {"parameters", output.at("parameters")},
      {"normalized", true}, {"dangling_distribution", "uniform"}, {"restart_distribution", "uniform"}, {"parallel_edges", "sum"}, {"self_loops", "discard"},
      {"tie_break", "numeric IDs before strings, then ascending stored value"}};
  return output;
}

json::object personalized_pagerank(const Graph& graph, const json::object& args, const std::string& backend, int device, Work& work) {
  fields(args, {"seed_vertices", "restart_probability", "direction_mode", "weight_mode", "dangling_policy", "convergence_tolerance", "max_iterations", "exclude_seeds_from_output", "top_k"}, {"seed_vertices"});
  require(args.at("seed_vertices").is_array() && !args.at("seed_vertices").as_array().empty(), "seed_vertices must be a nonempty array");
  std::set<VertexIndex> seeds;
  for (const auto& id : args.at("seed_vertices").as_array()) seeds.insert(graph.dense_index(external_id(id)));
  const auto restart = args.contains("restart_probability") ? number(args.at("restart_probability"), "restart_probability") : 0.15;
  require(restart > 0 && restart <= 1, "restart_probability must be in (0, 1]");
  const auto alpha = 1 - restart;
  const auto tolerance = args.contains("convergence_tolerance") ? number(args.at("convergence_tolerance"), "convergence_tolerance") : 1e-9;
  const auto iterations = args.contains("max_iterations") ? uint(args.at("max_iterations"), "max_iterations") : 1000;
  const auto direction = args.contains("direction_mode") ? string(args.at("direction_mode"), "direction_mode") : "outgoing";
  const auto mode = args.contains("weight_mode") ? string(args.at("weight_mode"), "weight_mode") : "unweighted";
  const auto policy = args.contains("dangling_policy") ? string(args.at("dangling_policy"), "dangling_policy") : "redistribute_to_seeds";
  const auto exclude = boolean(args, "exclude_seeds_from_output", false);
  std::optional<std::uint64_t> top;
  if (args.contains("top_k") && !args.at("top_k").is_null()) { top = uint(args.at("top_k"), "top_k"); require(*top > 0, "top_k must be positive"); }
  require(direction == "outgoing" || direction == "incoming" || direction == "undirected_projection", "Unknown direction_mode");
  require(mode == "unweighted" || mode == "edge_weight", "Unknown weight_mode");
  require(policy == "redistribute_to_seeds" || policy == "redistribute_uniformly" || policy == "self_loop", "Unknown dangling_policy");
  validate(alpha, tolerance, iterations); work.output(graph.vertex_count());
  auto input = weighted_graph(graph, mode == "edge_weight", true, "sum", direction, work);
  if (policy == "self_loop") for (VertexIndex v = 0; v < input.rows.size(); ++v)
    if (std::none_of(input.rows[v].begin(), input.rows[v].end(), [](const Arc& arc) { return arc.weight > 0; })) input.rows[v] = {{v, 1}};
  std::vector<double> teleport(graph.vertex_count(), 0), dangling(graph.vertex_count(), 1.0 / graph.vertex_count());
  json::array seed_ids;
  for (const auto v : seeds) { teleport[v] = 1.0 / seeds.size(); seed_ids.push_back(id_json(graph.external_id(v))); }
  if (policy != "redistribute_uniformly") dangling = teleport;
  const auto computed = rank(input, teleport, dangling, alpha, tolerance, iterations, backend, device, work);
  auto output = score_output(graph, computed,
      {{"seed_vertices", seed_ids}, {"restart_probability", restart}, {"direction_mode", direction}, {"weight_mode", mode},
       {"dangling_policy", policy}, {"convergence_tolerance", tolerance}, {"max_iterations", iterations},
       {"exclude_seeds_from_output", exclude}, {"top_k", top ? json::value(*top) : json::value(nullptr)}}, alpha, tolerance);
  std::vector<VertexIndex> order;
  for (VertexIndex v = 0; v < graph.vertex_count(); ++v) if (!exclude || !seeds.count(v)) order.push_back(v);
  std::sort(order.begin(), order.end(), [&](auto a, auto b) { return computed.values[a] != computed.values[b] ? computed.values[a] > computed.values[b] : a < b; });
  if (top && order.size() > *top) order.resize(*top);
  json::array ranking;
  for (const auto v : order) ranking.push_back(json::object{{"vertex", id_json(graph.external_id(v))}, {"score", computed.values[v]}});
  output.at("result").as_object()["ranking"] = ranking;
  return output;
}
}  // namespace graphmine::runtime
