#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/problems/dynamic_triangle_counting.hpp"

namespace {

void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

graphmine::Graph validation_graph() {
  std::vector<graphmine::ExternalId> vertices;
  for (std::int64_t vertex = 0; vertex < 12; ++vertex) {
    vertices.emplace_back(vertex);
  }
  return graphmine::Graph::from_edges(
      "validation-small", vertices,
      {{0, 1}, {0, 2}, {0, 3}, {0, 4}, {1, 2}, {1, 3}, {1, 4},
       {2, 3}, {2, 4}, {3, 4}, {4, 5}, {5, 6}, {5, 7}, {6, 7},
       {7, 8}, {8, 9}, {8, 10}, {8, 11}, {9, 10}, {10, 11}});
}

}  // namespace

int main() {
  const auto graph = validation_graph();
  const std::vector<graphmine::TriangleUpdate> updates = {
      {graphmine::TriangleUpdateKind::delete_edge, 0, 1},
      {graphmine::TriangleUpdateKind::insert_edge, 0, 5}};

  graphmine::DynamicTriangleOptions options;
  options.backend = graphmine::DynamicTriangleBackend::edtc;
  options.include_global_counts = true;
  options.list_changed_instances = true;
  options.result_limit = 2;
  const auto result =
      graphmine::DynamicTriangleCounting(options).run(graph, updates);
  require(result.ok(), result.status().message().c_str());
  require(result.value().deleted_triangle_count == 3,
          "EDTC deleted triangle count mismatch");
  require(result.value().inserted_triangle_count == 1,
          "EDTC inserted triangle count mismatch");
  require(result.value().net_triangle_change == -2,
          "EDTC net triangle change mismatch");
  require(result.value().initial_global_triangle_count == 13,
          "EDTC initial global count mismatch");
  require(result.value().final_global_triangle_count == 11,
          "EDTC final global count mismatch");
  require(result.value().deleted_triangles->size() == 2,
          "EDTC deleted instance limit mismatch");
  require(result.value().inserted_triangles->size() == 1,
          "EDTC inserted instance list mismatch");
  require(!result.value().changed_instances_complete,
          "EDTC limited instance output should be incomplete");

  // A pure insertion still follows EDTC's validated mixed batch path via an
  // isolated sentinel edge in the adapter.
  graphmine::DynamicTriangleOptions pure_options;
  pure_options.backend = graphmine::DynamicTriangleBackend::edtc;
  pure_options.include_global_counts = true;
  const auto pure = graphmine::DynamicTriangleCounting(pure_options).run(
      graph, {{graphmine::TriangleUpdateKind::insert_edge, 0, 5}});
  require(pure.ok(), pure.status().message().c_str());
  require(pure.value().deleted_triangle_count == 0 &&
              pure.value().inserted_triangle_count == 1,
          "EDTC pure insertion mismatch");
  return 0;
}
