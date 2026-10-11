#include "pattern_match.hpp"
#include "structured_input.hpp"

namespace graphmine::runtime {
json::object graph_coarsening(const Graph& graph, const json::object& args, const std::string&, int,
                              Work& work) {
  using namespace family_util;
  fields(args, {"cluster_assignment", "method", "self_loop_policy", "feature_reduction"});
  require(!graph.directed(), "Graph coarsening requires undirected input");
  const auto method = choice(args, "method", "greedy_matching", {"greedy_matching"}),
             loop_policy = choice(args, "self_loop_policy", "keep", {"keep", "drop"}),
             reduction = choice(args, "feature_reduction", "sum", {"sum", "mean"});
  const auto n = graph.vertex_count();
  std::vector<std::int64_t> assignment(n, -1);
  const bool supplied =
      args.contains("cluster_assignment") && !args.at("cluster_assignment").is_null();
  for (const auto& edge : graph.canonical().edges) {
    require(edge.source != edge.target, "Graph coarsening rejects self-loops");
    require(edge.weight.value_or(1) >= 0, "Weights must be nonnegative");
  }
  if (supplied) {
    const auto values = vertex_values(graph, args.at("cluster_assignment"), "cluster_assignment");
    for (std::size_t v = 0; v < n; ++v) {
      const auto id = external_id(values[v]);
      require(std::holds_alternative<std::int64_t>(id.value()), "Cluster IDs must be integers");
      assignment[v] = std::get<std::int64_t>(id.value());
    }
  } else {
    std::vector<bool> used(n, false);
    std::vector<Vertices> groups;
    for (const auto& edge : edges(graph, true, work))
      if (!used[edge.u] && !used[edge.v]) {
        groups.push_back({edge.u, edge.v});
        used[edge.u] = used[edge.v] = true;
      }
    for (VertexIndex v = 0; v < n; ++v)
      if (!used[v]) groups.push_back({v});
    std::sort(groups.begin(), groups.end());
    for (std::size_t c = 0; c < groups.size(); ++c)
      for (auto v : groups[c]) assignment[v] = c;
  }
  std::map<std::int64_t, Vertices> groups;
  for (VertexIndex v = 0; v < n; ++v) groups[assignment[v]].push_back(v);
  std::map<std::pair<std::int64_t, std::int64_t>, Exact> weights;
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    auto a = assignment[graph.dense_index(edge.source)],
         b = assignment[graph.dense_index(edge.target)];
    if (a == b && loop_policy == "drop") continue;
    if (a > b) std::swap(a, b);
    weights[{a, b}] += Exact(edge.weight.value_or(1));
  }
  std::vector<json::value> features(n);
  bool any = false;
  std::optional<std::size_t> width;
  for (std::size_t v = 0; v < n; ++v) {
    const auto record = vertex_record_json(graph.canonical().vertices[v], work);
    const auto* value = record_field(record, "attributes.features");
    if (value && !value->is_null()) {
      features[v] = *value;
      any = true;
    }
  }
  if (any)
    for (const auto& value : features) {
      require(value.is_array() && !value.as_array().empty(),
              "All vertices need nonempty equal-width feature arrays");
      if (!width) width = value.as_array().size();
      require(value.as_array().size() == *width, "Features must have equal width");
      for (const auto& item : value.as_array()) exact_number(item, "feature");
    }
  json::array vertices, output_edges, mapping, sizes, exact_weights, exact_features;
  bool rounded = false;
  auto numeric_value = [&](const Exact& value) {
    const double result = numeric::finite(value.convert_to<long double>());
    rounded = rounded || Exact(result) != value;
    return result;
  };
  for (const auto& [cluster, members] : groups) {
    json::object attrs{{"cluster_size", members.size()}};
    if (any) {
      json::array merged, exact;
      for (std::size_t c = 0; c < *width; ++c) {
        Exact value = 0;
        for (const auto v : members) {
          work.tick();
          value += exact_number(features[v].as_array()[c], "feature");
        }
        if (reduction == "mean") value /= members.size();
        merged.push_back(numeric_value(value));
        exact.push_back(fraction_json(value));
      }
      attrs["features"] = merged;
      exact_features.push_back(json::object{{"cluster", cluster}, {"values", exact}});
    }
    vertices.push_back(json::object{{"id", cluster}, {"attributes", attrs}});
    sizes.push_back(json::object{{"cluster", cluster}, {"size", members.size()}});
  }
  for (const auto& [pair, value] : weights) {
    const auto id = output_edges.size();
    output_edges.push_back(json::object{{"id", id},
                                        {"source", pair.first},
                                        {"target", pair.second},
                                        {"weight", numeric_value(value)}});
    exact_weights.push_back(json::object{{"edge", id}, {"value", fraction_json(value)}});
  }
  for (VertexIndex v = 0; v < n; ++v)
    mapping.push_back(
        json::object{{"vertex", id_json(graph.external_id(v))}, {"cluster", assignment[v]}});
  json::object quotient{{"graph",
                         {{"id", graph.canonical().graph.id + ":quotient"},
                          {"directed", false},
                          {"allows_self_loops", loop_policy == "keep"},
                          {"allows_parallel_edges", false}}},
                        {"vertices", vertices},
                        {"edges", output_edges}};
  work.output(mapping.size() + 2 * vertices.size() + 2 * output_edges.size() +
              (width ? vertices.size() * 2 * (*width) : 0));
  auto result = output(
      {{"cluster_assignment", supplied ? args.at("cluster_assignment") : json::value(nullptr)},
       {"method", method},
       {"self_loop_policy", loop_policy},
       {"feature_reduction", reduction}},
      {{"fine_to_coarse", mapping}, {"coarse_graph", quotient}, {"cluster_sizes", sizes}},
      {{"graph", result_port("graph", quotient)},
       {"mapping", result_port("vertex_coarsening", mapping)}},
      true,
      rounded    ? "numerical"
      : supplied ? "exact"
                 : "feasible");
  result["diagnostics"] =
      json::object{{"method", supplied ? "supplied_partition" : "native greedy maximal matching"},
                   {"edge_aggregation", "sum_once_per_original_undirected_edge"},
                   {"binary64_output_rounded", rounded},
                   {"exact_edge_weights", exact_weights},
                   {"exact_feature_aggregates", exact_features}};
  return result;
}

json::object knn_graph(const json::value& input, const json::object& args, Work& work) {
  using namespace family_util;
  using namespace numeric;
  fields(args, {"k", "distance", "search_mode", "symmetrization"}, {"k"});
  const FeatureInput data(input, work);
  const auto n = data.ids.size(), k = natural(args, "k", 0);
  require(k < n, "k must be smaller than the number of vectors");
  const auto distance =
      choice(args, "distance", "squared_euclidean", {"squared_euclidean", "euclidean", "cosine"});
  const auto mode = choice(args, "search_mode", "exact", {"exact", "approximate"}),
             symmetry = choice(args, "symmetrization", "directed", {"directed", "union", "mutual"});
  Matrix distances(n, n, work);
  std::vector<long double> norms(n, 0);
  if (distance == "cosine")
    for (std::size_t i = 0; i < n; ++i) {
      for (std::size_t c = 0; c < data.vectors.cols; ++c) {
        work.tick();
        const long double x = data.vectors(i, c);
        norms[i] += x * x;
      }
      require(norms[i] > 0, "Cosine distance is undefined for a zero vector");
      norms[i] = std::sqrt(norms[i]);
    }
  for (std::size_t i = 0; i < n; ++i)
    for (std::size_t j = i + 1; j < n; ++j) {
      long double sum = 0;
      for (std::size_t c = 0; c < data.vectors.cols; ++c) {
        work.tick();
        const long double a = data.vectors(i, c), b = data.vectors(j, c);
        sum += distance == "cosine" ? (a / norms[i]) * (b / norms[j]) : (a - b) * (a - b);
      }
      const auto value = distance == "cosine"
                             ? finite(std::max(0.0L, std::min(2.0L, 1 - sum)))
                             : finite(distance == "euclidean" ? std::sqrt(sum) : sum);
      distances(i, j) = distances(j, i) = value;
    }
  json::array rows;
  std::set<std::pair<std::size_t, std::size_t>> arcs, pairs;
  for (std::size_t i = 0; i < n; ++i) {
    std::vector<std::size_t> candidates;
    for (std::size_t j = 0; j < n; ++j)
      if (i != j) candidates.push_back(j);
    std::sort(candidates.begin(), candidates.end(), [&](auto a, auto b) {
      work.tick();
      return distances(i, a) == distances(i, b) ? a < b : distances(i, a) < distances(i, b);
    });
    json::array neighbors, values;
    for (std::size_t p = 0; p < k; ++p) {
      const auto j = candidates[p];
      arcs.emplace(i, j);
      neighbors.push_back(id_json(data.ids[j]));
      values.push_back(distances(i, j));
    }
    work.output((i + 1) * (1 + 2 * k));
    rows.push_back(json::object{
        {"vertex", id_json(data.ids[i])}, {"neighbors", neighbors}, {"distances", values}});
  }
  for (auto [a, b] : arcs) {
    if (symmetry == "mutual" && !arcs.count({b, a})) continue;
    if (symmetry != "directed" && a > b) std::swap(a, b);
    pairs.emplace(a, b);
  }
  json::array vertices, edges;
  for (const auto& id : data.ids) vertices.push_back(json::object{{"id", id_json(id)}});
  for (auto [a, b] : pairs)
    edges.push_back(json::object{{"id", edges.size()},
                                 {"source", id_json(data.ids[a])},
                                 {"target", id_json(data.ids[b])},
                                 {"weight", distances(a, b)}});
  json::object graph{{"graph",
                      {{"id", data.dataset_id + ":knn"},
                       {"directed", symmetry == "directed"},
                       {"allows_self_loops", false},
                       {"allows_parallel_edges", false}}},
                     {"vertices", vertices},
                     {"edges", edges}};
  work.output(n * (2 + 2 * k) + edges.size());
  return output(
      {{"k", k}, {"distance", distance}, {"search_mode", mode}, {"symmetrization", symmetry}},
      {{"graph", graph},
       {"neighbor_lists", rows},
       {"search_metadata",
        {{"algorithm", "native exhaustive pairwise search"},
         {"actual_search_mode", "exact"},
         {"requested_search_mode", mode},
         {"distance", distance},
         {"tie_break", "input_vector_order"},
         {"arithmetic", "float64 with extended accumulation"}}}},
      {{"graph", result_port("graph", graph)}, {"neighbors", result_port("neighbor_lists", rows)}},
      true, "numerical");
}

json::object hypergraph_partitioning(const json::value& input, const json::object& args,
                                     Work& work) {
  using namespace family_util;
  fields(args, {"num_parts", "imbalance_tolerance", "objective"}, {"num_parts"});
  const HypergraphInput data(input, work);
  const auto n = data.ids.size(), k = natural(args, "num_parts", 1, 1);
  require(k <= n, "num_parts exceeds the number of vertices");
  const auto objective =
      choice(args, "objective", "cut_net", {"cut_net", "connectivity_minus_one"});
  const auto tolerance = args.contains("imbalance_tolerance")
                             ? decimal_number(args.at("imbalance_tolerance"), "imbalance_tolerance")
                             : Exact(3) / 100;
  require(tolerance >= 0, "Imbalance tolerance must be nonnegative");
  Exact total = 0;
  for (const auto& w : data.weights) total += w;
  const Exact upper = total * (1 + tolerance) / k;
  std::optional<Exact> best;
  std::vector<std::size_t> assignment;
  std::vector<Exact> best_weights;
  partitions(n, k, k, work, [&](const std::vector<std::size_t>& values) {
    std::vector<Exact> weights(k, 0);
    for (std::size_t v = 0; v < n; ++v) {
      work.tick();
      weights[values[v]] += data.weights[v];
    }
    if (std::any_of(weights.begin(), weights.end(), [&](const auto& w) { return w > upper; }))
      return;
    Exact cost = 0;
    for (const auto& edge : data.edges) {
      std::set<std::size_t> parts;
      for (const auto v : edge.vertices) {
        work.tick();
        parts.insert(values[v]);
      }
      cost +=
          edge.weight * (objective == "cut_net" ? (parts.size() > 1 ? 1 : 0) : parts.size() - 1);
    }
    if (!best || cost < *best) {
      best = cost;
      assignment = values;
      best_weights = weights;
    }
  });
  json::array rows, weights, exact_weights;
  for (std::size_t v = 0; v < assignment.size(); ++v)
    rows.push_back(json::object{{"vertex", id_json(data.ids[v])}, {"part", assignment[v]}});
  for (const auto& weight : best_weights) {
    weights.push_back(display_number(weight));
    exact_weights.push_back(fraction_json(weight));
  }
  json::object result{{"partition", rows},
                      {"part_weights", weights},
                      {"part_weights_exact", exact_weights},
                      {"feasible", best.has_value()},
                      {"optimal", best.has_value()},
                      {"infeasibility_certified", !best.has_value()},
                      {"objective_value", nullptr}};
  if (best) exact_field(result, "objective_value", *best);
  work.output(rows.size() + weights.size());
  json::object ports;
  if (best) ports["partition"] = result_port("vertex_partition", rows);
  return output(
      {{"num_parts", k},
       {"objective", objective},
       {"imbalance_tolerance",
        args.contains("imbalance_tolerance") ? args.at("imbalance_tolerance") : json::value(0.03)}},
      result, ports);
}
}  // namespace graphmine::runtime
