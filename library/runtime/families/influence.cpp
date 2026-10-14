#include <queue>

#include "family_util.hpp"

namespace graphmine::runtime {
json::object influence_maximization(const Graph& graph, const json::object& args,
                                    const std::string&, int, Work& work) {
  using namespace family_util;
  fields(args, {"diffusion_model", "seed_set_size", "vertex_thresholds", "solution_quality", "sample_count", "random_seed"},
         {"diffusion_model", "seed_set_size"});
  require(graph.directed(), "Influence maximization requires directed input");
  const auto model = choice(args, "diffusion_model", "independent_cascade",
                            {"independent_cascade", "linear_threshold"});
  const auto k = natural(args, "seed_set_size", 1, 1), n = graph.vertex_count();
  require(k <= n, "seed_set_size exceeds vertex count");
  const bool fixed = args.contains("vertex_thresholds") && !args.at("vertex_thresholds").is_null();
  require(!fixed || model == "linear_threshold", "Fixed thresholds apply only to linear_threshold");
  std::map<std::pair<VertexIndex, VertexIndex>, Exact> weights;
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    require(edge.weight && *edge.weight >= 0 && *edge.weight <= 1,
            "Every diffusion edge needs an explicit weight in [0,1]");
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    auto& weight = weights[{u, v}];
    const Exact probability(*edge.weight);
    if (model == "independent_cascade")
      weight = 1 - (1 - weight) * (1 - probability);
    else
      weight += probability;
  }
  std::vector<std::vector<std::pair<VertexIndex, Exact>>> incoming(n);
  for (const auto& [ends, weight] : weights)
    if (weight > 0) incoming[ends.second].emplace_back(ends.first, weight);
  if (model == "linear_threshold")
    for (const auto& row : incoming) {
      Exact sum = 0;
      for (const auto& entry : row) sum += entry.second;
      require(sum <= 1, "Linear-threshold incoming weights exceed one");
    }
  std::vector<Vertices> candidates;
  combinations(n, k, work, [&](const Vertices& set) {
    work.tick(set.size());
    candidates.push_back(set);
    return true;
  });
  std::vector<Exact> spreads(candidates.size(), 0);
  std::uint64_t states = 0;
  Exact probability_mass = 0;
  if (fixed) {
    const auto values = vertex_values(graph, args.at("vertex_thresholds"), "vertex_thresholds");
    std::vector<Exact> thresholds;
    for (const auto& value : values) {
      const auto threshold = exact_number(value, "threshold");
      require(threshold >= 0 && threshold <= 1, "Thresholds must lie in [0,1]");
      thresholds.push_back(threshold);
    }
    for (std::size_t i = 0; i < candidates.size(); ++i) {
      work.tick(n);
      std::vector<bool> active(n, false);
      for (const auto v : candidates[i]) active[v] = true;
      for (;;) {
        bool changed = false;
        for (VertexIndex v = 0; v < n; ++v)
          if (!active[v]) {
            work.tick(incoming[v].size() + 1);
            Exact sum = 0;
            for (const auto& [u, weight] : incoming[v])
              if (active[u]) sum += weight;
            if (sum >= thresholds[v]) {
              active[v] = true;
              changed = true;
            }
          }
        if (!changed) break;
      }
      spreads[i] = std::count(active.begin(), active.end(), true);
    }
    states = 1;
    probability_mass = 1;
  } else {
    struct Option {
      std::optional<std::pair<VertexIndex, VertexIndex>> arc;
      Exact probability;
    };
    std::vector<std::vector<Option>> choices;
    if (model == "independent_cascade") {
      for (const auto& [ends, weight] : weights) {
        std::vector<Option> options;
        if (weight < 1) options.push_back({{}, 1 - weight});
        if (weight > 0) options.push_back({ends, weight});
        choices.push_back(std::move(options));
      }
    } else
      for (VertexIndex v = 0; v < n; ++v) {
        std::vector<Option> options;
        Exact residual = 1;
        for (const auto& [u, weight] : incoming[v]) {
          options.push_back({std::make_pair(u, v), weight});
          residual -= weight;
        }
        if (residual > 0) options.push_back({{}, residual});
        choices.push_back(std::move(options));
      }
    std::vector<std::size_t> state(choices.size(), 0);
    for (;;) {
      work.tick(n + choices.size());
      MiningGraph live(n);
      Exact probability = 1;
      for (std::size_t i = 0; i < choices.size(); ++i) {
        const auto& option = choices[i][state[i]];
        probability *= option.probability;
        if (option.arc) live[option.arc->first].push_back(option.arc->second);
      }
      work.tick(n * n);
      std::vector<std::vector<bool>> reach(n, std::vector<bool>(n, false));
      for (VertexIndex v = 0; v < n; ++v) {
        const auto search = cpu_bfs(live, v, {}, work);
        for (VertexIndex u = 0; u < n; ++u) reach[v][u] = search.distances[u] >= 0;
      }
      for (std::size_t i = 0; i < candidates.size(); ++i) {
        std::size_t count = 0;
        for (VertexIndex v = 0; v < n; ++v) {
          work.tick(k);
          if (std::any_of(candidates[i].begin(), candidates[i].end(),
                          [&](auto seed) { return reach[seed][v]; }))
            ++count;
        }
        spreads[i] += probability * count;
      }
      probability_mass += probability;
      if (states == UINT64_MAX)
        throw Failure("resource_limit", "Diffusion state count exceeds uint64");
      ++states;
      std::size_t at = 0;
      while (at < state.size() && ++state[at] == choices[at].size()) {
        state[at] = 0;
        ++at;
      }
      if (at == state.size()) break;
    }
  }
  if (probability_mass != 1)
    throw Failure("correctness_mismatch", "Diffusion probability mass does not equal one");
  const auto chosen = std::max_element(spreads.begin(), spreads.end()) - spreads.begin();
  const auto& expectation = spreads[chosen];
  require(expectation >= k && expectation <= n, "Expected spread violates graph bounds");
  const auto selected = ids(graph, candidates[chosen]);
  work.output(k);
  json::object data{{"seed_set", selected},
                    {"expected_spread_rational", fraction_json(expectation)},
                    {"optimal", true},
                    {"guarantee_met", true},
                    {"approximation_ratio", 1},
                    {"failure_probability", 0},
                    {"seed_sets_evaluated", candidates.size()},
                    {"diffusion_states_evaluated", states}};
  exact_field(data, "expected_spread", expectation);
  auto result =
      output({{"diffusion_model", model},
              {"seed_set_size", k},
              {"vertex_thresholds", fixed ? args.at("vertex_thresholds") : json::value(nullptr)}},
             data,
             {{"vertices", result_port("vertex_set", selected)},
              {"spread", result_port("scalar", display_number(expectation))}});
  result["diagnostics"] = json::object{
      {"expectation_method", fixed ? "fixed_threshold_propagation" : "exact_live_edge_enumeration"},
      {"probability_arithmetic", "exact rational values of admitted binary64 weights"},
      {"seed_selection", "exhaustive subsets; input-vertex order resolves ties"},
      {"sampling_used", false},
      {"self_loops", "removed"}};
  return result;
}
}  // namespace graphmine::runtime
