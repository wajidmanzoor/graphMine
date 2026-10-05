#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/problems/maximum_clique.hpp"

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

}  // namespace

int main() {
  std::vector<graphmine::ExternalId> vertices;
  for (std::int64_t vertex = 0; vertex < 12; ++vertex) {
    vertices.emplace_back(vertex);
  }
  const std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>> edges = {
      {0, 1}, {0, 2}, {0, 3}, {0, 4}, {1, 2}, {1, 3}, {1, 4},
      {2, 3}, {2, 4}, {3, 4}, {4, 5}, {5, 6}, {5, 7}, {6, 7},
      {7, 8}, {8, 9}, {8, 10}, {8, 11}, {9, 10}, {10, 11}};
  auto graph = graphmine::Graph::from_edges("validation-small", vertices, edges);

  for (const auto backend :
       {graphmine::MaximumCliqueBackend::cuda_ms,
        graphmine::MaximumCliqueBackend::gpu_maximum_clique,
        graphmine::MaximumCliqueBackend::maximum_clique_on_gpu}) {
    graphmine::MaximumCliqueOptions options;
    options.backend = backend;
    options.optional_outputs =
        graphmine::MaximumCliqueOptionalOutput::upper_bound;
    graphmine::MaximumClique algorithm(options);

    const auto result = algorithm.run(graph);
    require(result.ok(), result.status().message().c_str());
    require(result.value().maximum_size == 5,
            "maximum-clique size mismatch");
    require(result.value().cliques.size() == 1, "clique output mismatch");
    require(result.value().cliques.front().size() == 5,
            "returned clique size mismatch");
    require(result.value().upper_bound.has_value(), "upper bound is missing");
    require(*result.value().upper_bound >= result.value().maximum_size,
            "upper bound is invalid");
    require(result.value().optimal,
            "small fixture should be proven optimal");
  }

  const std::vector<graphmine::ExternalId> cycle_vertices = {0, 1, 2, 3, 4};
  const std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>>
      cycle_edges = {{0, 1}, {1, 2}, {2, 3}, {3, 4}, {4, 0}};
  const auto cycle = graphmine::Graph::from_edges(
      "maximum-clique-search-path", cycle_vertices, cycle_edges);
  graphmine::MaximumCliqueOptions search_options;
  search_options.backend =
      graphmine::MaximumCliqueBackend::maximum_clique_on_gpu;
  graphmine::MaximumClique search_algorithm(search_options);
  const auto search_result = search_algorithm.run(cycle);
  require(search_result.ok(), search_result.status().message().c_str());
  require(search_result.value().maximum_size == 2,
          "Maximum-Clique-on-GPU search-path size mismatch");
  require(search_result.value().cliques.front().size() == 2,
          "Maximum-Clique-on-GPU search-path clique mismatch");
  require(search_result.value().optimal,
          "Maximum-Clique-on-GPU search should be exact");

  // The application audit's eight-cycle with chord 0--2 improves the
  // preprocessing bound from two to three. Exercise witness ownership,
  // external string IDs, isolates, and repeated use in the same process.
  std::vector<graphmine::ExternalId> chord_vertices;
  for (int v = 0; v < 10; ++v)
    chord_vertices.emplace_back(std::string("device-") + std::to_string(v));
  std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>> chord_edges;
  for (int v = 0; v < 8; ++v)
    chord_edges.emplace_back(chord_vertices[v], chord_vertices[(v + 1) % 8]);
  chord_edges.emplace_back(chord_vertices[0], chord_vertices[2]);
  const auto chord = graphmine::Graph::from_edges(
      "cycle-chord-native-regression", chord_vertices, chord_edges);
  for (int repetition = 0; repetition < 4; ++repetition) {
    const auto result = search_algorithm.run(chord);
    require(result.ok(), result.status().message().c_str());
    require(result.value().maximum_size == 3 && result.value().optimal,
            "cycle-with-chord maximum size mismatch");
    require(result.value().cliques.size() == 1 && result.value().cliques[0].size() == 3,
            "cycle-with-chord witness size mismatch");
    for (const auto& vertex : result.value().cliques[0])
      require(vertex == chord_vertices[0] || vertex == chord_vertices[1] || vertex == chord_vertices[2],
              "cycle-with-chord external witness mapping mismatch");
  }
  auto invalid_bound_options = search_options;
  invalid_bound_options.known_lower_bound = 4;
  require(!graphmine::MaximumClique(invalid_bound_options).run(chord).ok(),
          "unverified lower bound must not fabricate a larger clique");

  // A lower-core triangle precedes a higher-core bipartite component. The
  // reduction must apply one permutation to vertex names and row lengths.
  std::vector<graphmine::ExternalId> mixed_vertices;
  for (int v = 0; v < 14; ++v) mixed_vertices.emplace_back(v);
  std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>> mixed_edges;
  for (int v = 0; v < 8; ++v) mixed_edges.emplace_back(v, (v + 1) % 8);
  mixed_edges.emplace_back(0, 2);
  for (int u = 8; u < 11; ++u)
    for (int v = 11; v < 14; ++v) mixed_edges.emplace_back(u, v);
  const auto mixed = graphmine::Graph::from_edges(
      "maximum-clique-mixed-core-regression", mixed_vertices, mixed_edges);
  const auto mixed_result = search_algorithm.run(mixed);
  require(mixed_result.ok(), mixed_result.status().message().c_str());
  require(mixed_result.value().maximum_size == 3 && mixed_result.value().optimal,
          "core-sorted reduction lost the lower-core maximum clique");

  graphmine::MaximumCliqueOptions ties_options;
  ties_options.backend =
      graphmine::MaximumCliqueBackend::gpu_maximum_clique;
  ties_options.return_all_ties = true;
  graphmine::MaximumClique ties_algorithm(ties_options);
  const auto ties_result = ties_algorithm.run(cycle);
  require(ties_result.ok(), ties_result.status().message().c_str());
  require(ties_result.value().maximum_size == 2,
          "GPUMaximumClique tied size mismatch");
  require(ties_result.value().cliques.size() == 5,
          "GPUMaximumClique did not return every tied cycle edge");

  // The old CUDA-MS relaxation returned three. Completed GPU search must
  // recover the four-clique {2, 4, 6, 7} and certify it.
  const std::vector<graphmine::ExternalId> audit_vertices = {0, 1, 2, 3, 4, 5, 6, 7, 8};
  const std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>> audit_edges = {
      {0, 1}, {0, 2}, {0, 3}, {0, 8}, {1, 2}, {1, 4}, {1, 8}, {2, 4},
      {2, 6}, {2, 7}, {3, 5}, {4, 6}, {4, 7}, {5, 7}, {5, 8}, {6, 7}};
  const auto audit_graph = graphmine::Graph::from_edges(
      "synthetic-random-01-false-optimality", audit_vertices, audit_edges);
  for (const auto backend :
       {graphmine::MaximumCliqueBackend::cuda_ms,
        graphmine::MaximumCliqueBackend::gpu_maximum_clique,
        graphmine::MaximumCliqueBackend::maximum_clique_on_gpu}) {
    graphmine::MaximumCliqueOptions options;
    options.backend = backend;
    options.optional_outputs = graphmine::MaximumCliqueOptionalOutput::upper_bound;
    const auto result = graphmine::MaximumClique(options).run(audit_graph);
    require(result.ok(), result.status().message().c_str());
    require(result.value().upper_bound.has_value() && *result.value().upper_bound >= 4,
            "relaxation mask incorrectly reduced the certified upper bound");
    require(!result.value().optimal || result.value().maximum_size == 4,
            "a non-maximum clique was certified as optimal");
    require(result.value().maximum_size == 4 && result.value().optimal,
            "exact backend failed the seeded four-clique regression");
  }
  return 0;
}
