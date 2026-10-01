#include <cstdint>
#include <numeric>
#include <stdexcept>
#include <utility>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/problems/triangle_counting.hpp"

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

}  // namespace

void check_backend(const graphmine::Graph& graph,
                   graphmine::TriangleBackend backend) {
  graphmine::TriangleOptions options;
  options.backend = backend;
  options.list_instances = true;
  options.include_per_vertex_counts = true;
  options.include_per_edge_counts = true;
  options.result_limit = 5;
  graphmine::TriangleCounting algorithm(options);

  const auto result = algorithm.run(graph);
  require(result.ok(), result.status().message().c_str());
  require(result.value().global_triangle_count == 13,
          "triangle count mismatch");
  require(!result.value().instances_complete,
          "limited triangle list should be incomplete");
  require(result.value().triangles->size() == 5,
          "triangle list limit mismatch");

  std::uint64_t vertex_sum = 0;
  for (const auto& entry : *result.value().per_vertex_count) {
    vertex_sum += entry.count;
  }
  require(vertex_sum == 39, "per-vertex triangle counts are inconsistent");
  std::uint64_t edge_sum = 0;
  for (const auto& entry : *result.value().per_edge_count) {
    edge_sum += entry.count;
  }
  require(edge_sum == 39, "per-edge triangle counts are inconsistent");
}

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

  check_backend(graph, graphmine::TriangleBackend::tot);
  check_backend(graph, graphmine::TriangleBackend::wetric);
  return 0;
}
