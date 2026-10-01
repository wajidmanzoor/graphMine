#include <algorithm>
#include <cassert>
#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/problems/maximal_cliques.hpp"

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

}  // namespace

void check_backend(const graphmine::Graph& graph,
                   graphmine::MaximalCliqueBackend backend) {
  graphmine::MaximalCliqueOptions options;
  options.backend = backend;
  options.minimum_clique_size = 1;
  options.optional_outputs =
      graphmine::MaximalCliqueOptionalOutput::total_count;
  graphmine::MaximalCliques algorithm(options);

  const auto support = algorithm.supports(graph);
  require(support.supported, "backend should support the validation graph");
  const auto result = algorithm.run(graph);
  require(result.ok(), result.status().message().c_str());
  require(result.value().complete, "result should be complete");
  require(result.value().returned_count == 6, "returned count mismatch");
  require(result.value().total_count == 6, "total count mismatch");
  require(result.value().cliques.size() == 6, "clique list mismatch");

  for (const auto& clique : result.value().cliques) {
    require(!clique.empty(), "empty clique was returned");
  }
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

  check_backend(graph, graphmine::MaximalCliqueBackend::rdmce);
  check_backend(graph, graphmine::MaximalCliqueBackend::mce_gpu);
  check_backend(graph, graphmine::MaximalCliqueBackend::g2_aimd);
  return 0;
}
