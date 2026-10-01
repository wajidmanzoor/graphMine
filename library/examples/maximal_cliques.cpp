#include <iostream>
#include <utility>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/problems/maximal_cliques.hpp"

int main() {
  using graphmine::ExternalId;

  auto graph = graphmine::Graph::from_edges(
      "example", {0, 1, 2, 3, 4},
      {{0, 1}, {0, 2}, {0, 3}, {1, 2}, {1, 3}, {2, 3}, {3, 4}});

  graphmine::MaximalCliques algorithm({
      graphmine::MaximalCliqueBackend::rdmce,
      2,
      std::nullopt,
      graphmine::MaximalCliqueOptionalOutput::total_count,
  });

  const auto result = algorithm.run(graph);
  if (!result.ok()) {
    std::cerr << result.status().message() << '\n';
    return 1;
  }

  std::cout << "backend: " << result.provenance().backend << '\n';
  std::cout << "maximal cliques: " << result.value().returned_count << '\n';
  for (const auto& clique : result.value().cliques) {
    for (const auto& vertex : clique) {
      std::cout << vertex.to_string() << ' ';
    }
    std::cout << '\n';
  }
  return 0;
}
