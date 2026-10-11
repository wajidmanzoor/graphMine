#include "family_util.hpp"
#include "numeric.hpp"

namespace graphmine::runtime {
json::object seeded_local_community(const Graph& graph, const json::object& args,
                                    const std::string&, int, Work& work) {
  using namespace family_util;
  fields(args, {"seeds", "maximum_volume", "method_parameters", "solution_quality"}, {"seeds"});
  require(!graph.directed(), "Local community requires undirected input");
  const auto quality = choice(args, "solution_quality", "heuristic", {"heuristic"});
  const auto seeds = vertices(graph, args.at("seeds"), "seeds");
  require(!seeds.empty(), "seeds must be nonempty");
  const auto methods = args.contains("method_parameters")
                           ? object(args.at("method_parameters"), "method_parameters")
                           : json::object{};
  fields(methods, {"alpha", "tolerance", "max_iterations"});
  const double alpha = methods.contains("alpha") ? number(methods.at("alpha"), "alpha") : 0.85;
  require(alpha >= 0 && alpha < 1, "alpha must be in [0,1)");
  const auto tol = numeric::tolerance(methods, "tolerance", 1e-10);
  const auto iterations = natural(methods, "max_iterations", 1000, 1);
  for (const auto& edge : graph.canonical().edges)
    require(edge.source != edge.target, "Local community rejects self-loops");
  const auto normalized = edges(graph, true, work);
  const auto n = graph.vertex_count();
  std::vector<Exact> degree(n, 0);
  Exact total = 0;
  for (const auto& edge : normalized) {
    degree[edge.u] += edge.weight;
    degree[edge.v] += edge.weight;
    total += 2 * edge.weight;
  }
  Exact bound = total;
  if (args.contains("maximum_volume") && !args.at("maximum_volume").is_null()) {
    bound = exact_number(args.at("maximum_volume"), "maximum_volume");
    require(bound >= 0, "maximum_volume must be nonnegative");
  }
  std::vector<bool> selected(n, false);
  Exact volume = 0;
  for (const auto v : seeds) {
    selected[v] = true;
    volume += degree[v];
  }
  require(volume <= bound, "Required seeds exceed maximum_volume");
  const auto scores = personalized_pagerank(graph,
                                            {{"seed_vertices", args.at("seeds")},
                                             {"restart_probability", 1 - alpha},
                                             {"weight_mode", "edge_weight"},
                                             {"convergence_tolerance", tol},
                                             {"max_iterations", iterations}},
                                            "cpp", 0, work);
  std::vector<Exact> ranking(n, 0);
  for (const auto& row :
       scores.at("ports").as_object().at("scores").as_object().at("value").as_array()) {
    const auto v = graph.dense_index(external_id(row.as_object().at("vertex")));
    if (degree[v] > 0)
      ranking[v] = exact_number(row.as_object().at("score"), "PageRank score") / degree[v];
  }
  Vertices order;
  for (VertexIndex v = 0; v < n; ++v)
    if (!selected[v]) order.push_back(v);
  std::sort(order.begin(), order.end(), [&](auto u, auto v) {
    work.tick();
    return ranking[u] != ranking[v] ? ranking[u] > ranking[v] : u < v;
  });
  Exact cut = 0;
  for (const auto& edge : normalized)
    if (selected[edge.u] != selected[edge.v]) cut += edge.weight;
  const auto seed_selection = selected;
  const auto seed_volume = volume, seed_cut = cut;
  std::optional<Exact> best;
  std::vector<bool> chosen = selected;
  Exact best_volume = volume, best_cut = cut;
  json::array sweep;
  for (std::size_t step = 0; step <= order.size(); ++step) {
    work.tick();
    const Exact denominator = std::min(volume, Exact(total - volume));
    json::object row{{"size", std::count(selected.begin(), selected.end(), true)},
                     {"conductance", nullptr}};
    exact_field(row, "volume", volume);
    exact_field(row, "cut_weight", cut);
    if (denominator > 0) {
      const Exact value = cut / denominator;
      exact_field(row, "conductance", value);
      if (!best || value < *best) {
        best = value;
        chosen = selected;
        best_volume = volume;
        best_cut = cut;
      }
    }
    sweep.push_back(row);
    work.output(sweep.size());
    if (step == order.size() || volume + degree[order[step]] > bound) break;
    const auto v = order[step];
    for (const auto& edge : normalized) {
      work.tick();
      if (edge.u == v)
        cut += selected[edge.v] ? -edge.weight : edge.weight;
      else if (edge.v == v)
        cut += selected[edge.u] ? -edge.weight : edge.weight;
    }
    selected[v] = true;
    volume += degree[v];
  }
  if (!best) {
    chosen = seed_selection;
    best_volume = seed_volume;
    best_cut = seed_cut;
  }
  Vertices members;
  for (VertexIndex v = 0; v < n; ++v)
    if (chosen[v]) members.push_back(v);
  work.output(members.size() + sweep.size() + order.size());
  const auto external = ids(graph, members);
  json::object data{{"vertices", external},
                    {"conductance", nullptr},
                    {"optimal", false},
                    {"sweep_candidates", sweep}};
  exact_field(data, "volume", best_volume);
  exact_field(data, "cut_weight", best_cut);
  if (best) exact_field(data, "conductance", *best);
  auto result =
      output({{"seeds", args.at("seeds")},
              {"maximum_volume",
               args.contains("maximum_volume") ? args.at("maximum_volume") : json::value(nullptr)},
              {"method_parameters",
               {{"alpha", alpha}, {"tolerance", tol}, {"max_iterations", iterations}}},
              {"solution_quality", quality}},
             data, {{"vertices", result_port("vertex_set", external)}}, true, "heuristic");
  auto diagnostics = scores.at("diagnostics").as_object();
  diagnostics["method"] = "personalized_pagerank_degree_normalized_seed_first_sweep";
  diagnostics["sweep_order"] = ids(graph, order);
  diagnostics["undefined_conductance_policy"] =
      "return_seeds_if_no_feasible_prefix_has_positive_denominator";
  result["diagnostics"] = diagnostics;
  return result;
}
}  // namespace graphmine::runtime
