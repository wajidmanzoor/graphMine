#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/problems/betweenness_centrality.hpp"

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
  const std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>>
      edges = {{0, 1}, {0, 2},  {0, 3},  {0, 4},  {1, 2},  {1, 3},
               {1, 4}, {2, 3},  {2, 4},  {3, 4},  {4, 5},  {5, 6},
               {5, 7}, {6, 7},  {7, 8},  {8, 9},  {8, 10}, {8, 11},
               {9, 10}, {10, 11}};
  const auto graph =
      graphmine::Graph::from_edges("validation-small", vertices, edges);

  graphmine::BetweennessCentralityOptions options;
  options.backend = graphmine::BetweennessCentralityBackend::turbo_bc;
  options.optional_outputs =
      graphmine::BetweennessCentralityOptionalOutput::normalized_scores |
      graphmine::BetweennessCentralityOptionalOutput::ranking |
      graphmine::BetweennessCentralityOptionalOutput::maximum;
  graphmine::BetweennessCentrality algorithm(options);
  const auto result = algorithm.run(graph);
  require(result.ok(), result.status().message().c_str());

  const std::vector<double> expected = {0, 0, 0, 0, 56, 60,
                                        0, 56, 49, 0, 1,  0};
  require(result.value().score_by_vertex.size() == expected.size(),
          "centrality vector size mismatch");
  for (std::size_t vertex = 0; vertex < expected.size(); ++vertex) {
    require(std::abs(result.value().score_by_vertex[vertex].score -
                     expected[vertex]) < 1.0e-4,
            "unnormalized centrality score mismatch");
  }
  require(result.value().normalized_score_by_vertex.has_value(),
          "normalized score output missing");
  require(std::abs((*result.value().normalized_score_by_vertex)[5].score -
                   60.0 / 110.0) < 1.0e-6,
          "normalized centrality score mismatch");
  require(result.value().ranking->front().vertex == graphmine::ExternalId(5),
          "centrality ranking mismatch");
  require(result.value().maximum->vertex == graphmine::ExternalId(5) &&
              std::abs(result.value().maximum->score - 60.0) < 1.0e-4,
          "maximum centrality output mismatch");

  const auto repeated = algorithm.run(graph);
  require(repeated.ok(), repeated.status().message().c_str());
  require(std::abs(repeated.value().score_by_vertex[5].score - 60.0) < 1.0e-4,
          "repeated TurboBC invocation mismatch");
  return 0;
}
