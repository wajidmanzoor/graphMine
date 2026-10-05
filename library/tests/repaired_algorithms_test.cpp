#include "graphmine/problems/repaired_algorithms.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>

namespace gm = graphmine;
static void check(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

int main() {
  try {
    auto triangle = gm::Graph::from_edges("triangle", {0, "0", -1, "isolate"},
                                         {{0, "0"}, {"0", -1}, {-1, 0}});
    if (!gm::KTruss::backends().front().compiled) {
      auto result = gm::KTruss().run(triangle);
      check(!gm::KTruss().supports(triangle).supported && !result.ok() &&
            result.status().code() == gm::StatusCode::backend_unavailable,
            "missing workers must fail closed");
      return 0;
    }
    auto truss = gm::KTruss().run(triangle);
    check(truss.ok() && truss.value().maximum_truss_number == 3 &&
          truss.value().truss_number_by_edge.size() == 3, "triangle truss numbers");
    auto density = gm::DensestSubgraph().run(triangle);
    check(density.ok() && density.value().optimal && density.value().density == 1 &&
          density.value().vertices.size() == 3, "densest triangle excludes isolate");

    gm::CanonicalGraphInput bipartite;
    bipartite.graph.id = "bipartite";
    bipartite.vertices = {{0}, {"0"}, {-1}, {"right"}};
    for (int i = 0; i < 4; ++i)
      bipartite.vertices[i].attributes["side"] = i < 2 ? "left" : "right";
    bipartite.edges = {{0, 0, -1}, {1, 0, "right"},
                       {2, "0", -1}, {3, "0", "right"}};
    auto bicliques = gm::MaximalBicliqueCounting().run(gm::Graph(bipartite));
    check(bicliques.ok() && bicliques.value().total_count == 1 &&
          bicliques.value().complete, "K2,2 has one maximal biclique");
    gm::ButterflyOptions butterfly_options;
    butterfly_options.backend = "gamma-butterfly";
    auto butterflies = gm::ButterflyCounting(butterfly_options).run(gm::Graph(bipartite));
    check(butterflies.ok() && butterflies.value().butterfly_count == 1,
          "GAMMA public dispatch counts one butterfly");

    auto cycle = gm::Graph::from_edges("cycle", {0, "0"}, {{0, "0"}, {"0", 0}}, true);
    gm::PersonalizedPageRankOptions ppr_options;
    ppr_options.seed_vertex = "0";
    ppr_options.top_k = 2;
    auto ppr = gm::PersonalizedPageRank(ppr_options).run(cycle);
    check(ppr.ok() && ppr.value().ranked_vertices.size() == 2 &&
          ppr.value().ranked_vertices[0].vertex == gm::ExternalId("0") &&
          std::abs(ppr.value().ranked_vertices[0].score - 5.0/9.0) < 0.04 &&
          ppr.value().approximate && !ppr.value().error_bound_certified,
          "PPR must preserve seed type and report approximation");

    gm::CanonicalGraphInput weighted;
    weighted.graph.id = "tree";
    weighted.vertices = {{0}, {"0"}, {-1}};
    weighted.edges = {{"expensive", 0, -1, 20}, {"a", 0, "0", 2}, {"b", "0", -1, 3}};
    gm::GroupSteinerTreeOptions tree_options;
    tree_options.groups = {{0}, {-1}};
    auto tree = gm::GroupSteinerTree(tree_options).run(gm::Graph(weighted));
    check(tree.ok() && tree.value().feasible && tree.value().optimal &&
          tree.value().tree_weight == 5 && tree.value().tree_edges.size() == 2,
          "Steiner tree must return the two cheaper edges");
    weighted.graph.directed = true;
    check(!gm::GroupSteinerTree(tree_options).supports(gm::Graph(weighted)).supported,
          "directed Steiner input must be rejected");

    weighted.edges = {{"a", 0, "0", 1}, {"b", "0", -1, 1}};
    gm::InfluenceMaximizationOptions influence_options;
    influence_options.seed_set_size = 1;
    influence_options.sample_count = 32;
    auto influence = gm::InfluenceMaximization(influence_options).run(gm::Graph(weighted));
    check(influence.ok() && influence.value().seed_set == std::vector<gm::ExternalId>{0} &&
          influence.value().expected_spread == 3 && !influence.value().guarantee_met,
          "deterministic cascade chain must reach every vertex");
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
