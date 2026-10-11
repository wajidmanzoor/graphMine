#include "family_util.hpp"

namespace graphmine::runtime {
json::object network_alignment(const Graph& graph, const json::object& args, const std::string&,
                               int, Work& work) {
  using namespace family_util;
  fields(args,
         {"other_graph", "alignment_mode", "node_similarity_prior", "topology_weight",
          "weight_mode", "solution_quality"},
         {"other_graph"});
  const auto other = parse_graph(args.at("other_graph"));
  require(graph.directed() == other.directed(),
          "Alignment graphs must have matching direction semantics");
  const auto mode = choice(args, "alignment_mode", "global_one_to_one", {"global_one_to_one"});
  const auto quality = choice(args, "solution_quality", "exact", {"exact", "approximate"});
  const auto weights = choice(args, "weight_mode", "unweighted", {"unweighted", "edge_weight"});
  const Exact alpha = args.contains("topology_weight")
                          ? exact_number(args.at("topology_weight"), "topology_weight")
                          : Exact(1);
  require(alpha >= 0, "topology_weight must be nonnegative");
  if (weights == "edge_weight")
    for (const auto* input : {&graph, &other})
      for (const auto& edge : input->canonical().edges)
        require(edge.weight.has_value(),
                "Weighted alignment requires explicit edge weights on both graphs");
  const auto a = edges(graph, weights == "edge_weight", work),
             b = edges(other, weights == "edge_weight", work);
  using Pair = std::pair<VertexIndex, VertexIndex>;
  std::map<Pair, Exact> b_weights, prior;
  for (const auto& edge : b) b_weights[{edge.u, edge.v}] = edge.weight;
  if (args.contains("node_similarity_prior") && !args.at("node_similarity_prior").is_null()) {
    require(args.at("node_similarity_prior").is_array(), "node_similarity_prior must be an array");
    for (const auto& raw : args.at("node_similarity_prior").as_array()) {
      work.tick();
      const auto row = object(raw, "similarity prior");
      fields(row, {"graph_a_vertex", "graph_b_vertex", "value"},
             {"graph_a_vertex", "graph_b_vertex", "value"});
      const Pair pair{graph.dense_index(external_id(row.at("graph_a_vertex"))),
                      other.dense_index(external_id(row.at("graph_b_vertex")))};
      require(prior.emplace(pair, exact_number(row.at("value"), "prior value")).second,
              "Duplicate pair in node_similarity_prior");
    }
  }
  const auto na = graph.vertex_count(), nb = other.vertex_count();
  std::optional<Exact> best;
  std::vector<std::optional<VertexIndex>> selected(na);
  auto conserved = [&](const Edge& edge, const auto& mapping) -> Exact {
    if (!mapping[edge.u] || !mapping[edge.v]) return 0;
    auto u = *mapping[edge.u], v = *mapping[edge.v];
    if (!graph.directed() && u > v) std::swap(u, v);
    const auto found = b_weights.find({u, v});
    return found == b_weights.end() ? Exact(0) : std::min(edge.weight, found->second);
  };
  injective_assignments(
      std::min(na, nb), std::max(na, nb), work,
      [&](const Vertices& assignment) {
        work.tick(na);
        std::vector<std::optional<VertexIndex>> mapping(na);
        for (VertexIndex v = 0; v < assignment.size(); ++v) {
          if (na <= nb)
            mapping[v] = assignment[v];
          else
            mapping[assignment[v]] = v;
        }
        Exact value = 0;
        for (VertexIndex v = 0; v < na; ++v)
          if (mapping[v]) {
            const auto it = prior.find({v, *mapping[v]});
            if (it != prior.end()) value += it->second;
          }
        for (const auto& edge : a) {
          work.tick();
          value += alpha * conserved(edge, mapping);
        }
        if (!best || value > *best) {
          best = value;
          selected = std::move(mapping);
        }
        return true;
      },
      [](const Vertices&, VertexIndex) { return true; });
  require(best.has_value(), "Global alignment unexpectedly infeasible");
  Exact topology = 0, prior_total = 0;
  std::vector<Exact> scores(na, 0);
  json::array conserved_edges;
  for (VertexIndex v = 0; v < na; ++v)
    if (selected[v]) {
      const auto it = prior.find({v, *selected[v]});
      if (it != prior.end()) scores[v] = it->second;
      prior_total += scores[v];
    }
  for (const auto& edge : a) {
    work.tick();
    if (!selected[edge.u] || !selected[edge.v]) continue;
    auto u = *selected[edge.u], v = *selected[edge.v];
    if (!graph.directed() && u > v) std::swap(u, v);
    if (!b_weights.count({u, v})) continue;
    const Exact value = conserved(edge, selected);
    topology += value;
    scores[edge.u] += alpha * value / 2;
    scores[edge.v] += alpha * value / 2;
    json::object row{
        {"graph_a_endpoints",
         json::array{id_json(graph.external_id(edge.u)), id_json(graph.external_id(edge.v))}},
        {"graph_b_endpoints", json::array{id_json(other.external_id(*selected[edge.u])),
                                          id_json(other.external_id(*selected[edge.v]))}}};
    exact_field(row, "value", value);
    conserved_edges.push_back(row);
  }
  if (prior_total + alpha * topology != *best)
    throw Failure("correctness_mismatch", "Alignment objective failed recomputation");
  Vertices order;
  for (VertexIndex v = 0; v < na; ++v)
    if (selected[v]) order.push_back(v);
  std::sort(order.begin(), order.end(), [&](auto u, auto v) {
    return scores[u] != scores[v] ? scores[u] > scores[v]
                                  : graph.external_id(u) < graph.external_id(v);
  });
  json::array rows;
  for (const auto v : order) {
    json::object row{{"graph_a_vertex", id_json(graph.external_id(v))},
                     {"graph_b_vertex", id_json(other.external_id(*selected[v]))}};
    exact_field(row, "score", scores[v]);
    rows.push_back(row);
  }
  work.output(rows.size() + conserved_edges.size());
  const auto other_fingerprint = input_fingerprint(args.at("other_graph"));
  json::object data{
      {"vertex_mapping", rows},
      {"conserved_edges", conserved_edges},
      {"edge_correctness",
       a.empty() ? json::value(nullptr)
                 : json::value(static_cast<double>(conserved_edges.size()) / a.size())},
      {"objective_fraction", best->str()},
      {"optimal", true},
      {"complete", true}};
  exact_field(data, "objective_value", *best);
  exact_field(data, "conserved_edge_value", topology);
  exact_field(data, "similarity_prior_value", prior_total);
  auto port = result_port("cross_graph_mapping", rows);
  port["other_graph_fingerprint"] = other_fingerprint;
  auto result = output({{"other_graph", args.at("other_graph")},
                        {"alignment_mode", mode},
                        {"node_similarity_prior", args.contains("node_similarity_prior")
                                                      ? args.at("node_similarity_prior")
                                                      : json::value(nullptr)},
                        {"topology_weight", display_number(alpha)},
                        {"weight_mode", weights},
                        {"solution_quality", quality}},
                       data, {{"mapping", port}});
  result["diagnostics"] =
      json::object{{"solver", "native_exact_injective_alignment"},
                   {"other_graph_fingerprint", other_fingerprint},
                   {"weighted_conservation", "minimum_normalized_edge_weight"},
                   {"pair_score", "prior_plus_half_incident_conserved_topology"}};
  return result;
}
}  // namespace graphmine::runtime
