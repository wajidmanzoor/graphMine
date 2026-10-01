#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/problems/k_core.hpp"

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

  graphmine::KCoreOptions options;
  options.backend = graphmine::KCoreBackend::kcore_gpu;
  options.requested_k = 3;
  options.optional_outputs =
      graphmine::KCoreOptionalOutput::requested_core_vertices |
      graphmine::KCoreOptionalOutput::requested_core_edges |
      graphmine::KCoreOptionalOutput::peeling_order;
  graphmine::KCore algorithm(options);

  const auto result = algorithm.run(graph);
  require(result.ok(), result.status().message().c_str());
  require(result.value().degeneracy == 4, "degeneracy mismatch");
  const std::vector<std::uint32_t> expected = {4, 4, 4, 4, 4, 2,
                                               2, 2, 2, 2, 2, 2};
  require(result.value().core_number_by_vertex.size() == expected.size(),
          "core vector size mismatch");
  for (std::size_t vertex = 0; vertex < expected.size(); ++vertex) {
    require(result.value().core_number_by_vertex[vertex].core_number ==
                expected[vertex],
            "core number mismatch");
  }
  require(result.value().requested_core_vertices->size() == 5,
          "requested core vertex count mismatch");
  require(result.value().requested_core_edges->size() == 10,
          "requested core edge count mismatch");
  require(result.value().peeling_order->size() == 12,
          "peeling order size mismatch");
  return 0;
}
