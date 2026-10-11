#include "exact_flow.hpp"
#include "family_util.hpp"

namespace graphmine::runtime {
namespace {
using namespace family_util;
struct Term {
  Vertices vertices;
  Exact weight;
};
std::vector<Term> terms(const Graph& graph, const std::vector<Edge>& edges, std::uint64_t order,
                        Work& work) {
  std::vector<Term> result;
  if (order == 2) {
    for (const auto& edge : edges) result.push_back({{edge.u, edge.v}, edge.weight});
    return result;
  }
  const auto adj = adjacency(graph, work);
  if (order <= graph.vertex_count())
    each_clique(adj, order, order, work, [&](const Vertices& selected) {
      work.tick(selected.size());
      result.push_back({selected, 1});
      return true;
    });
  return result;
}
Exact induced_value(const std::vector<Term>& terms, const std::vector<bool>& selected, Work& work) {
  Exact result = 0;
  for (const auto& term : terms) {
    work.tick(term.vertices.size());
    bool inside = true;
    for (const auto v : term.vertices)
      if (!selected[v]) {
        inside = false;
        break;
      }
    if (inside) result += term.weight;
  }
  return result;
}
// Maximum-weight closure gives an exact Dinkelbach ratio iteration. Unlike
// cardinality enumeration, this path scales to graphs with thousands of nodes.
Vertices closure_density(std::size_t n, const std::vector<Term>& terms, Work& work) {
  Vertices best(n);
  std::iota(best.begin(), best.end(), 0);
  Exact total = 0;
  for (const auto& term : terms) total += term.weight;
  Exact ratio = total / n;
  for (;;) {
    work.tick(n + terms.size());
    const auto source = n + terms.size(), sink = source + 1;
    ExactFlow flow(sink + 1);
    const Exact infinity = total + n * ratio + 1;
    for (std::size_t i = 0; i < terms.size(); ++i) {
      work.tick(terms[i].vertices.size());
      flow.add(source, n + i, terms[i].weight);
      for (const auto v : terms[i].vertices) flow.add(n + i, v, infinity);
    }
    for (std::size_t v = 0; v < n; ++v) flow.add(v, sink, ratio);
    flow.solve(source, sink, work);
    const auto reached = flow.reachable(source, work);
    Vertices selected;
    for (VertexIndex v = 0; v < n; ++v)
      if (reached[v]) selected.push_back(v);
    const auto value = induced_value(terms, reached, work);
    if (value <= ratio * selected.size()) return best;
    best = std::move(selected);
    ratio = value / best.size();
  }
}
json::object density(const Graph& graph, const json::object& args, Work& work, bool fixed) {
  require(!graph.directed(), "Density requires an undirected graph");
  if (fixed)
    fields(args, {"k", "weight_mode", "solution_quality"}, {"k"});
  else
    fields(args, {"clique_order", "minimum_vertices", "weight_mode", "solution_quality"});
  const auto order = fixed ? 2 : natural(args, "clique_order", 2, 2);
  const auto minimum = natural(args, fixed ? "k" : "minimum_vertices", 1, 1);
  const auto weight = choice(args, "weight_mode", "unweighted", {"unweighted", "edge_weight"});
  const auto quality = choice(args, "solution_quality", "exact", {"exact", "approximate"});
  require(order == 2 || weight == "unweighted",
          "Weighted density is defined only for clique_order=2");
  require(minimum <= graph.vertex_count(), "No feasible nonempty vertex set at the requested size");
  const auto normalized = edges(graph, weight == "edge_weight", work);
  const auto objective = terms(graph, normalized, order, work);
  Vertices best;
  Exact best_ratio = -1;
  if (!fixed && minimum == 1)
    best = closure_density(graph.vertex_count(), objective, work);
  else
    for (std::size_t size = minimum; size <= (fixed ? minimum : graph.vertex_count()); ++size) {
      combinations(graph.vertex_count(), size, work, [&](const Vertices& selected) {
        work.tick(graph.vertex_count());
        std::vector<bool> mask(graph.vertex_count(), false);
        for (const auto v : selected) mask[v] = true;
        const Exact ratio = induced_value(objective, mask, work) / size;
        if (ratio > best_ratio) {
          best_ratio = ratio;
          best = selected;
        }
        return true;
      });
    }
  std::vector<bool> mask(graph.vertex_count(), false);
  for (const auto v : best) mask[v] = true;
  const Exact numerator = induced_value(objective, mask, work);
  std::uint64_t count = 0;
  Exact edge_value = 0;
  for (const auto& term : objective) {
    work.tick(term.vertices.size());
    if (std::all_of(term.vertices.begin(), term.vertices.end(), [&](auto v) { return mask[v]; }))
      ++count;
  }
  for (const auto& edge : normalized) {
    work.tick();
    if (mask[edge.u] && mask[edge.v]) edge_value += edge.weight;
  }
  work.output(best.size());
  const auto selected = ids(graph, best);
  json::object data{
      {"vertices", selected}, {"optimal", true}, {"clique_order", order}, {"clique_count", count}};
  exact_field(data, "density", numerator / best.size());
  exact_field(data, "induced_edge_value", edge_value);
  json::object resolved{{"weight_mode", weight}, {"solution_quality", quality}};
  if (fixed)
    resolved["k"] = minimum;
  else {
    resolved["minimum_vertices"] = minimum;
    resolved["clique_order"] = order;
  }
  auto result = output(resolved, data, {{"vertices", result_port("vertex_set", selected)}});
  result["diagnostics"] =
      json::object{{"solver", !fixed && minimum == 1 ? "native_exact_maximum_weight_closure"
                                                     : "native_exact_cardinality_search"},
                   {"arithmetic", "exact rational"}};
  return result;
}
}  // namespace
json::object densest_subgraph(const Graph& graph, const json::object& args, const std::string&, int,
                              Work& work) {
  return density(graph, args, work, false);
}
json::object densest_k_subgraph(const Graph& graph, const json::object& args, const std::string&,
                                int, Work& work) {
  return density(graph, args, work, true);
}
json::object quasi_cliques(const Graph& graph, const json::object& args, const std::string&, int,
                           Work& work) {
  using namespace family_util;
  fields(args, {"gamma", "minimum_size", "maximum_size", "maximal_only"},
         {"gamma", "minimum_size"});
  require(!graph.directed(), "Quasi-cliques require undirected input");
  const auto gamma = decimal_number(args.at("gamma"), "gamma");
  require(gamma > 0 && gamma <= 1, "gamma must be in (0,1]");
  const auto minimum = natural(args, "minimum_size", 2, 2),
             upper = limit(args, "maximum_size", 2).value_or(graph.vertex_count());
  require(!args.contains("maximum_size") || args.at("maximum_size").is_null() || upper >= minimum,
          "maximum_size is below minimum_size");
  const bool maximal_only = boolean(args, "maximal_only", true);
  const auto adj = adjacency(graph, work);
  std::vector<Vertices> accepted;
  json::array rows;
  std::uint64_t output_items = 0;
  for (std::size_t size = std::min<std::uint64_t>(upper, graph.vertex_count()); size >= minimum;
       --size) {
    const Exact threshold = gamma * (size - 1);
    combinations(graph.vertex_count(), size, work, [&](const Vertices& selected) {
      std::uint64_t degree_sum = 0, minimum_degree = size;
      for (const auto v : selected) {
        std::uint64_t degree = 0;
        for (const auto u : selected) {
          work.tick();
          degree += adjacent(adj, u, v);
        }
        if (Exact(degree) < threshold) return true;
        degree_sum += degree;
        minimum_degree = std::min(minimum_degree, degree);
      }
      if (maximal_only)
        for (const auto& bigger : accepted) {
          work.tick(bigger.size() + selected.size());
          if (std::includes(bigger.begin(), bigger.end(), selected.begin(), selected.end()))
            return true;
        }
      output_items += 1 + selected.size();
      work.output(output_items);
      accepted.push_back(selected);
      rows.push_back(
          json::object{{"vertices", ids(graph, selected)},
                       {"size", size},
                       {"induced_edge_count", degree_sum / 2},
                       {"density", static_cast<double>(degree_sum) / (size * (size - 1))},
                       {"minimum_internal_degree", minimum_degree}});
      return true;
    });
  }
  auto result = output({{"gamma", args.at("gamma")},
                        {"minimum_size", minimum},
                        {"maximum_size", args.contains("maximum_size") ? args.at("maximum_size")
                                                                       : json::value(nullptr)},
                        {"maximal_only", maximal_only}},
                       {{"quasi_cliques", rows}, {"count", rows.size()}, {"complete", true}},
                       {{"groups", result_port("vertex_groups", rows)}});
  result["diagnostics"] = json::object{{"threshold_arithmetic", "decimal_rational"},
                                       {"maximality_scope", "qualifying_sets_within_size_bounds"}};
  return result;
}
}  // namespace graphmine::runtime
