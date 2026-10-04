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

  // Seeded application audit: CUDA-MS finds a three-clique here, while
  // {2, 4, 6, 7} is a four-clique. Its relaxation mask must not certify three.
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
    if (backend != graphmine::MaximumCliqueBackend::cuda_ms) {
      require(result.value().maximum_size == 4 && result.value().optimal,
              "exact backend failed the seeded four-clique regression");
    }
  }
  return 0;
}
