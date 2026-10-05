#include <cuda_runtime.h>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include "graphmine/graph.hpp"
#include "graphmine/problems/maximum_clique.hpp"

// Run the public API repeatedly in one process, preserving external vertex IDs.
// Input: case_id n m lower_bound, followed by m pairs of zero-based endpoints.
int main(int argc, char** argv) {
  if (argc != 3) return 2;
  std::ifstream input(argv[1]);
  std::ofstream output(argv[2]);
  if (!input || !output) return 2;
  std::string id;
  int n, m, lower_bound;
  while (input >> id >> n >> m >> lower_bound) {
    std::vector<graphmine::ExternalId> vertices;
    for (int v = 0; v < n; ++v) vertices.emplace_back(std::string("vertex:") + std::to_string(v));
    std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>> edges;
    for (int e = 0, u, v; e < m; ++e) {
      if (!(input >> u >> v)) return 2;
      edges.emplace_back(vertices[u], vertices[v]);
    }
    const auto graph = graphmine::Graph::from_edges(id, vertices, edges);
    graphmine::MaximumCliqueOptions options;
    options.backend = graphmine::MaximumCliqueBackend::cuda_ms;
    options.optional_outputs = graphmine::MaximumCliqueOptionalOutput::upper_bound;
    if (lower_bound >= 0) options.known_lower_bound = lower_bound;
    const auto result = graphmine::MaximumClique(options).run(graph);
    output << id;
    if (!result.ok()) {
      output << " ERROR " << result.status().message() << std::endl;
      continue;
    }
    const auto& value = result.value();
    output << " OK " << value.maximum_size << ' ' << value.optimal << ' '
           << value.upper_bound.value_or(0);
    for (const auto& v : value.cliques.front()) output << ' ' << v.to_string();
    output << std::endl;
  }
  return input.eof() ? 0 : 2;
}
