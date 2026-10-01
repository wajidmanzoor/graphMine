#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/problems/quasi_cliques.hpp"

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

std::vector<graphmine::ExternalId> sequence(int begin, int end) {
  std::vector<graphmine::ExternalId> output;
  for (int vertex = begin; vertex < end; ++vertex) {
    output.emplace_back(vertex);
  }
  return output;
}

}  // namespace

int main() {
  std::vector<graphmine::ExternalId> small_vertices;
  for (int vertex = 0; vertex < 12; ++vertex) {
    small_vertices.emplace_back(vertex);
  }
  const std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>>
      small_edges = {{0, 1}, {0, 2}, {0, 3}, {0, 4}, {1, 2}, {1, 3},
                     {1, 4}, {2, 3}, {2, 4}, {3, 4}, {4, 5}, {5, 6},
                     {5, 7}, {6, 7}, {7, 8}, {8, 9}, {8, 10}, {8, 11},
                     {9, 10}, {10, 11}};
  const auto small = graphmine::Graph::from_edges(
      "quasi-small", small_vertices, small_edges);

  graphmine::QuasiCliqueOptions options;
  options.backend = graphmine::QuasiCliqueBackend::cuqc;
  options.minimum_degree_ratio = 0.8;
  options.minimum_size = 4;
  options.optional_outputs = graphmine::QuasiCliqueOptionalOutput::total_count;
  graphmine::QuasiCliques algorithm(options);
  const auto small_result = algorithm.run(small);
  require(small_result.ok(), small_result.status().message().c_str());
  require(small_result.value().complete &&
              small_result.value().total_count == 1 &&
              small_result.value().quasi_cliques.size() == 1 &&
              small_result.value().quasi_cliques.front() == sequence(0, 5),
          "small cuQC result mismatch");

  std::vector<graphmine::ExternalId> medium_vertices;
  for (int vertex = 0; vertex < 28; ++vertex) {
    medium_vertices.emplace_back(vertex);
  }
  std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>>
      medium_edges;
  for (int group = 0; group < 4; ++group) {
    const int first = group * 7;
    for (int lhs = first; lhs < first + 7; ++lhs) {
      for (int rhs = lhs + 1; rhs < first + 7; ++rhs) {
        if (!(lhs == first + 5 && rhs == first + 6)) {
          medium_edges.emplace_back(lhs, rhs);
        }
      }
    }
    if (group > 0) {
      medium_edges.emplace_back(first, first - 1);
    }
  }
  const auto medium = graphmine::Graph::from_edges(
      "quasi-medium", medium_vertices, medium_edges);
  const auto medium_result = algorithm.run(medium);
  require(medium_result.ok(), medium_result.status().message().c_str());
  require(medium_result.value().complete &&
              medium_result.value().total_count == 4 &&
              medium_result.value().quasi_cliques.size() == 4,
          "medium cuQC result count mismatch");
  for (int group = 0; group < 4; ++group) {
    require(medium_result.value().quasi_cliques[group] ==
                sequence(group * 7, group * 7 + 7),
            "medium cuQC vertex set mismatch");
  }
  return 0;
}
