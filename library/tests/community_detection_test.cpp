#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <utility>
#include <vector>

#include "graphmine/problems/community_detection.hpp"

namespace {

graphmine::Graph validation_graph() {
  std::vector<graphmine::ExternalId> vertices;
  for (int vertex = 0; vertex < 18; ++vertex) vertices.emplace_back(vertex);
  const std::vector<std::pair<int, int>> raw_edges{
      {0, 1},   {0, 2},   {0, 3},   {0, 4},   {0, 5},   {1, 2},
      {1, 3},   {1, 4},   {1, 5},   {2, 3},   {2, 4},   {2, 5},
      {3, 4},   {3, 5},   {4, 5},   {5, 6},   {5, 12},  {6, 7},
      {6, 8},   {6, 9},   {6, 10},  {6, 11},  {7, 8},   {7, 9},
      {7, 10},  {7, 11},  {8, 9},   {8, 10},  {8, 11},  {9, 10},
      {9, 11},  {10, 11}, {11, 12}, {12, 13}, {12, 14}, {12, 15},
      {12, 16}, {12, 17}, {13, 14}, {13, 15}, {13, 16}, {13, 17},
      {14, 15}, {14, 16}, {14, 17}, {15, 16}, {15, 17}, {16, 17},
  };
  std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>> edges;
  for (const auto& edge : raw_edges) edges.emplace_back(edge.first, edge.second);
  return graphmine::Graph::from_edges("community-validation-small",
                                      std::move(vertices), edges);
}

void check_backend(graphmine::CommunityDetectionBackend backend,
                   bool optional_outputs) {
  graphmine::CommunityDetectionOptions options;
  options.backend = backend;
  if (optional_outputs) {
    options.optional_outputs =
        graphmine::CommunityDetectionOptionalOutput::communities |
        graphmine::CommunityDetectionOptionalOutput::edge_cut;
  }
  graphmine::CommunityDetection detection(options);
  const auto result = detection.run(validation_graph());
  if (!result.ok()) {
    std::cerr << graphmine::to_string(backend) << ": "
              << result.status().message() << '\n';
  }
  assert(result.ok());
  assert(result.value().assignment_by_vertex.size() == 18);
  assert(result.value().community_count == 3);
  assert(std::abs(result.value().modularity - 0.6041666666666667) < 1e-7);
  if (optional_outputs) {
    assert(result.value().communities.has_value());
    assert(result.value().communities->size() == 3);
    assert(result.value().edge_cut == 3);
  }
}

}  // namespace

int main() {
  check_backend(graphmine::CommunityDetectionBackend::gleiden, true);
  check_backend(graphmine::CommunityDetectionBackend::parallel_louvain,
                false);
  check_backend(graphmine::CommunityDetectionBackend::parallel_leiden,
                false);
  check_backend(graphmine::CommunityDetectionBackend::parallel_leiden_plus,
                false);
  return 0;
}
