#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <map>
#include <string>
#include <utility>
#include <vector>

#include "graphmine/problems/community_detection.hpp"

namespace {

graphmine::Graph validation_graph(bool isolates = false) {
  std::vector<graphmine::ExternalId> vertices;
  if (isolates) vertices.emplace_back(-10);
  for (int vertex = 0; vertex < 18; ++vertex) {
    vertices.emplace_back(vertex);
    if (isolates && vertex == 8) vertices.emplace_back(100);
  }
  if (isolates) vertices.emplace_back(200);
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
                   bool optional_outputs, bool isolates = false) {
  graphmine::CommunityDetectionOptions options;
  options.backend = backend;
  if (optional_outputs) {
    options.optional_outputs =
        graphmine::CommunityDetectionOptionalOutput::communities |
        graphmine::CommunityDetectionOptionalOutput::edge_cut;
  }
  graphmine::CommunityDetection detection(options);
  const auto result = detection.run(validation_graph(isolates));
  if (!result.ok()) {
    std::cerr << graphmine::to_string(backend) << ": "
              << result.status().message() << '\n';
  }
  assert(result.ok());
  assert(result.value().assignment_by_vertex.size() == (isolates ? 21 : 18));
  assert(result.value().community_count == (isolates ? 6 : 3));
  assert(std::abs(result.value().modularity - 0.6041666666666667) < 1e-7);
  if (optional_outputs) {
    assert(result.value().communities.has_value());
    assert(result.value().communities->size() == (isolates ? 6 : 3));
    assert(result.value().edge_cut == 3);
  }
}

void check_refinement_stagnation(graphmine::CommunityDetectionBackend backend) {
  // Exhaustive six-vertex sweep fixture: refinement sometimes keeps every
  // coarse vertex, making the upstream level-building loop repeat forever.
  const std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>> edges{
      {0, 2}, {0, 4}, {0, 5}, {1, 4}, {1, 5},
      {2, 4}, {2, 5}, {3, 4}, {3, 5}};
  const auto graph = graphmine::Graph::from_edges(
      "leiden-no-contraction", {0, 1, 2, 3, 4, 5}, edges);
  graphmine::CommunityDetectionOptions options;
  options.backend = backend;
  options.optional_outputs =
      graphmine::CommunityDetectionOptionalOutput::edge_cut;
  for (int repeat = 0; repeat < 20; ++repeat) {
    const auto result = graphmine::CommunityDetection(options).run(graph);
    assert(result.ok());
    const auto& output = result.value();
    assert(output.assignment_by_vertex.size() == 6);
    std::map<graphmine::ExternalId, std::uint32_t> assignment;
    for (const auto& row : output.assignment_by_vertex) {
      assert(assignment.emplace(row.vertex, row.community).second);
    }
    for (int vertex = 0; vertex < 6; ++vertex) assert(assignment.count(vertex));
    std::map<std::uint32_t, int> internal_edges, degree_sum;
    std::uint64_t cut = 0;
    for (const auto& edge : edges) {
      const auto u = assignment.at(edge.first), v = assignment.at(edge.second);
      ++degree_sum[u];
      ++degree_sum[v];
      if (u == v) ++internal_edges[u];
      else ++cut;
    }
    assert(degree_sum.size() == output.community_count);
    double modularity = 0;
    for (const auto& row : degree_sum) {
      const double fraction = row.second / 18.0;
      modularity += internal_edges[row.first] / 9.0 - fraction * fraction;
    }
    assert(std::abs(modularity - output.modularity) < 1e-10);
    assert(output.edge_cut == cut);
  }
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "usage: graphmine_community_detection_test BACKEND\n";
    return 2;
  }
  const std::string backend = argv[1];
  if (backend == "gleiden") {
    check_backend(graphmine::CommunityDetectionBackend::gleiden, true);
    check_backend(graphmine::CommunityDetectionBackend::gleiden, true, true);
    graphmine::CommunityDetectionOptions options;
    options.backend = graphmine::CommunityDetectionBackend::gleiden;
    const auto empty = graphmine::CommunityDetection(options).run(
        graphmine::Graph::from_edges("isolated-records", {11, 22, 33}, {}));
    assert(empty.ok());
    assert(empty.value().community_count == 3);
    assert(empty.value().modularity == 0.0);
  } else if (backend == "parallel-louvain") {
    check_backend(graphmine::CommunityDetectionBackend::parallel_louvain,
                  false);
  } else if (backend == "parallel-leiden") {
    check_backend(graphmine::CommunityDetectionBackend::parallel_leiden,
                  false);
    check_refinement_stagnation(graphmine::CommunityDetectionBackend::parallel_leiden);
  } else if (backend == "parallel-leiden-plus") {
    check_backend(graphmine::CommunityDetectionBackend::parallel_leiden_plus,
                  false);
    check_refinement_stagnation(graphmine::CommunityDetectionBackend::parallel_leiden_plus);
  } else {
    std::cerr << "unknown backend: " << backend << '\n';
    return 2;
  }
  return 0;
}
