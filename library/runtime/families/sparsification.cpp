#include "native_random.hpp"
#include "numeric.hpp"
#include "pattern_match.hpp"

namespace graphmine::runtime {
json::object spectral_sparsification(const Graph& graph, const json::object& args,
                                     const std::string&, int, Work& work) {
  using namespace family_util;
  using namespace numeric;
  fields(args, {"mode", "edge_budget", "epsilon", "random_seed"}, {"edge_budget"});
  choice(args, "mode", "static", {"static"});
  require(!graph.directed(), "Sparsification requires undirected input");
  const auto budget = natural(args, "edge_budget", 0), seed = natural(args, "random_seed", 0);
  std::optional<double> epsilon;
  if (args.contains("epsilon") && !args.at("epsilon").is_null()) {
    epsilon = number(args.at("epsilon"), "epsilon");
    require(*epsilon > 0 && *epsilon < 1, "epsilon must lie strictly between zero and one");
  }
  struct Edge {
    VertexIndex u, v;
    double weight;
    std::size_t original;
  };
  std::vector<Edge> input;
  std::set<std::pair<VertexIndex, VertexIndex>> seen;
  const auto n = graph.vertex_count();
  MiningGraph adj(n);
  for (std::size_t i = 0; i < graph.edge_count(); ++i) {
    work.tick();
    const auto& edge = graph.canonical().edges[i];
    require(edge.weight.has_value() && *edge.weight >= 0,
            "Sparsification requires explicit nonnegative weights");
    auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    require(u != v, "Sparsification rejects loops");
    if (u > v) std::swap(u, v);
    require(seen.emplace(u, v).second, "Sparsification rejects parallel edges");
    if (*edge.weight > 0) {
      input.push_back({u, v, *edge.weight, i});
      adj[u].push_back(v);
      adj[v].push_back(u);
    }
  }
  std::vector<Vertices> components;
  std::vector<bool> visited(n, false);
  for (VertexIndex root = 0; root < n; ++root)
    if (!visited[root]) {
      Vertices members{root};
      visited[root] = true;
      for (std::size_t at = 0; at < members.size(); ++at)
        for (const auto v : adj[members[at]]) {
          work.tick();
          if (!visited[v]) {
            visited[v] = true;
            members.push_back(v);
          }
        }
      std::sort(members.begin(), members.end());
      components.push_back(std::move(members));
    }
  const auto m = input.size(), rank = n - components.size();
  const bool identity = budget >= m, zero = budget == 0;
  std::vector<double> retained(m, 0), probabilities(m, 0);
  std::vector<std::uint64_t> counts(m, 0);
  double lower = identity ? 1 : 0, upper = lower;
  std::uint64_t draws = 0;
  if (identity)
    for (std::size_t e = 0; e < m; ++e) retained[e] = input[e].weight;
  else if (!zero) {
    double scale = 0;
    for (const auto& e : input) scale = std::max(scale, e.weight);
    struct Component {
      Vertices edges;
      Matrix incidence, matrix;
    };
    std::vector<Component> systems;
    std::vector<double> leverage(m, 0);
    for (const auto& members : components) {
      if (members.size() < 2) continue;
      const auto r = members.size() - 1;
      std::map<VertexIndex, std::size_t> local;
      for (std::size_t i = 0; i < members.size(); ++i) local[members[i]] = i;
      Vertices selected;
      for (std::size_t e = 0; e < m; ++e)
        if (local.count(input[e].u)) selected.push_back(e);
      Matrix incidence(r, selected.size(), work), matrix(r, r, work);
      for (std::size_t col = 0; col < selected.size(); ++col) {
        const auto& e = input[selected[col]];
        const auto u = local.at(e.u), v = local.at(e.v);
        const auto w = e.weight / scale;
        require(w > 0, "Weight range underflowed Laplacian scaling");
        if (u < r) {
          incidence(u, col) = 1;
          matrix(u, u) += w;
        }
        if (v < r) {
          incidence(v, col) = -1;
          matrix(v, v) += w;
        }
        if (u < r && v < r) {
          matrix(u, v) -= w;
          matrix(v, u) -= w;
        }
      }
      const auto solution = positive_solve(matrix, incidence, work);
      for (std::size_t col = 0; col < selected.size(); ++col) {
        long double resistance = 0;
        for (std::size_t i = 0; i < r; ++i) {
          work.tick();
          resistance += static_cast<long double>(incidence(i, col)) * solution(i, col);
        }
        leverage[selected[col]] = finite(input[selected[col]].weight / scale * resistance);
      }
      systems.push_back({selected, std::move(incidence), std::move(matrix)});
    }
    long double total = 0;
    for (const auto l : leverage) {
      require(l > 0 && l <= 1 + 1e-7, "Effective resistance failed positivity check");
      total += l;
    }
    require(std::abs(total - rank) <= 1e-7 * std::max<std::size_t>(1, rank),
            "Effective resistance failed rank check");
    std::vector<Exact> masses;
    for (std::size_t i = 0; i < m; ++i) {
      probabilities[i] = finite(leverage[i] / total);
      require(probabilities[i] > 0, "Sampling probability underflowed");
      masses.emplace_back(probabilities[i]);
    }
    // NativeRandom normalizes rational binary64 masses exactly. Reweight using
    // that same normalized probability, including any rounding in their sum.
    Exact mass_total = 0;
    for (const auto& mass : masses) mass_total += mass;
    NativeRandom random(json::object{{"random_seed", seed}});
    work.tick(budget);
    for (std::uint64_t i = 0; i < budget; ++i) ++counts[*random.weighted(masses, work)];
    for (std::size_t e = 0; e < m; ++e)
      if (counts[e]) {
        const Exact value = Exact(input[e].weight) * counts[e] * mass_total / (budget * masses[e]);
        retained[e] = finite(value.convert_to<long double>());
        require(retained[e] > 0, "Sparsifier weight underflowed");
      }
    lower = std::numeric_limits<double>::infinity();
    upper = -lower;
    for (const auto& system : systems) {
      const auto r = system.matrix.rows;
      Matrix candidate(r, r, work);
      for (std::size_t col = 0; col < system.edges.size(); ++col) {
        const auto weight = retained[system.edges[col]] / scale;
        require(retained[system.edges[col]] == 0 || weight > 0, "Verification weight underflowed");
        for (std::size_t i = 0; i < r; ++i)
          for (std::size_t j = 0; j < r; ++j) {
            work.tick();
            candidate(i, j) += system.incidence(i, col) * weight * system.incidence(j, col);
          }
      }
      const auto basis = symmetric_eigen(system.matrix, work);
      Matrix inverse_root(r, r, work);
      for (std::size_t k = 0; k < r; ++k) {
        require(basis.values[k] > 0, "Grounded Laplacian eigenvalue is unresolved");
        const auto factor = 1 / std::sqrt(basis.values[k]);
        for (std::size_t i = 0; i < r; ++i)
          for (std::size_t j = 0; j < r; ++j) {
            work.tick();
            inverse_root(i, j) += basis.vectors(i, k) * factor * basis.vectors(j, k);
          }
      }
      auto whitened = multiply(multiply(inverse_root, candidate, work), inverse_root, work);
      for (std::size_t i = 0; i < r; ++i)
        for (std::size_t j = 0; j < i; ++j)
          whitened(i, j) = whitened(j, i) = (whitened(i, j) + whitened(j, i)) / 2;
      const auto eigen = symmetric_eigen(std::move(whitened), work);
      lower = std::min(lower, eigen.values.front());
      upper = std::max(upper, eigen.values.back());
    }
    draws = budget;
  }
  MiningGraph output_adj(n);
  json::array output_edges;
  for (std::size_t e = 0; e < m; ++e)
    if (retained[e] > 0) {
      auto record = edge_record_json(graph.canonical().edges[input[e].original], work);
      if (!identity) record["weight"] = retained[e];
      output_edges.push_back(record);
      output_adj[input[e].u].push_back(input[e].v);
      output_adj[input[e].v].push_back(input[e].u);
    }
  bool preserved = true;
  for (const auto& component : components)
    if (component.size() > 1) {
      const auto reached = cpu_bfs(output_adj, component[0], {}, work);
      for (auto v : component)
        if (reached.distances[v] < 0) preserved = false;
    }
  if (!preserved)
    lower = 0;
  else if (rank)
    require(lower > 0, "Positive spectral lower ratio is unresolved");
  const auto error = rank ? std::max(std::abs(1 - lower), std::abs(upper - 1)) : 0;
  if (epsilon)
    require(error <= *epsilon,
            "Requested epsilon was not met; increase edge_budget or choose another random_seed");
  auto output_graph = selected_graph(graph, std::vector<bool>(n, true), work);
  output_graph["edges"] = output_edges;
  auto& meta = output_graph.at("graph").as_object();
  meta["id"] = graph.canonical().graph.id + "-spectral-sparsifier";
  meta["allows_self_loops"] = false;
  meta["allows_parallel_edges"] = false;
  json::array sampling;
  if (!identity && !zero)
    for (std::size_t e = 0; e < m; ++e)
      sampling.push_back(
          json::object{{"edge", id_json(graph.canonical().edges[input[e].original].id)},
                       {"draws", counts[e]},
                       {"probability_mass", probabilities[e]}});
  json::object summary{
      {"input_positive_edge_count", m},
      {"output_edge_count", output_edges.size()},
      {"edge_budget", budget},
      {"sample_count", draws},
      {"positive_weight_components_preserved", preserved},
      {"laplacian_rank", rank},
      {"lower_quadratic_form_ratio", rank ? json::value(lower) : json::value(nullptr)},
      {"upper_quadratic_form_ratio", rank ? json::value(upper) : json::value(nullptr)},
      {"maximum_relative_spectral_error", error},
      {"epsilon", epsilon ? json::value(*epsilon) : json::value(nullptr)},
      {"epsilon_met_numerically", epsilon ? json::value(error <= *epsilon) : json::value(nullptr)},
      {"exact_bound", identity || zero},
      {"probabilistic_guarantee_claimed", false},
      {"bound_kind", identity ? "exact_identity_after_zero_weight_removal"
                     : zero   ? "exact_zero_laplacian"
                              : "numerical_generalized_eigenvalue_diagnostics"},
      {"verification", identity || zero
                           ? "identity_or_zero_algebra"
                           : "all generalized eigenvalues on grounded positive-weight components"}};
  work.output(n + output_edges.size() + sampling.size());
  auto result = output({{"mode", "static"},
                        {"edge_budget", budget},
                        {"epsilon", epsilon ? json::value(*epsilon) : json::value(nullptr)},
                        {"random_seed", seed}},
                       {{"sparsifier", output_graph}, {"quality_summary", summary}},
                       {{"graph", result_port("graph", output_graph)}}, true, "heuristic");
  result["diagnostics"] = json::object{
      {"sampling", "effective-resistance probability, with replacement"},
      {"draws", sampling},
      {"arithmetic",
       "float64 numerical eigenvalue diagnostics; no exact-arithmetic approximation guarantee"}};
  return result;
}
}  // namespace graphmine::runtime
