#include <cstdint>
#include <numeric>
#include <stdexcept>
#include <utility>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/problems/k_cliques.hpp"

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
  const auto graph =
      graphmine::Graph::from_edges("validation-small", vertices, edges);

  for (const auto backend : {graphmine::KCliqueBackend::kcgpu,
                             graphmine::KCliqueBackend::graphset,
                             graphmine::KCliqueBackend::gamma}) {
    for (const auto [k, expected] :
         std::vector<std::pair<std::uint32_t, std::uint64_t>>{
             {3, 13}, {4, 5}, {5, 1}}) {
      graphmine::KCliqueOptions options;
      options.k = k;
      options.backend = backend;
      options.enumerate = true;
      options.include_per_vertex_counts = true;
      graphmine::KCliques algorithm(options);

      const auto result = algorithm.run(graph);
      require(result.ok(), result.status().message().c_str());
      require(result.value().count == expected, "k-clique count mismatch");
      require(result.value().complete, "full enumeration should be complete");
      require(result.value().cliques->size() == expected,
              "enumeration size mismatch");
      std::uint64_t participation = 0;
      for (const auto& entry : *result.value().per_vertex_count) {
        participation += entry.count;
      }
      require(participation == expected * k,
              "per-vertex k-clique counts are inconsistent");
    }
  }

  graphmine::KCliqueOptions limited_options;
  limited_options.backend = graphmine::KCliqueBackend::graphset;
  limited_options.enumerate = true;
  limited_options.result_limit = 4;
  const auto limited = graphmine::KCliques(limited_options).run(graph);
  require(limited.ok(), limited.status().message().c_str());
  require(limited.value().count == 13, "limited total count mismatch");
  require(!limited.value().complete, "limited enumeration must be incomplete");
  require(limited.value().cliques->size() == 4,
          "limited enumeration size mismatch");
  return 0;
}
