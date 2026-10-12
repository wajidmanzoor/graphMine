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

  // GAMMA's prefix pre-merge must compare query positions with positions,
  // rather than with mapped vertex IDs. This triangle-containing graph has
  // no 4-clique; the upstream comparison incorrectly counted one.
  const auto gamma_regression = graphmine::Graph::from_edges(
      "gamma-prefix-position", {0, 1, 2, 3, 4, 5},
      {{0, 1}, {0, 3}, {0, 4}, {0, 5}, {1, 2}, {1, 5},
       {2, 3}, {2, 5}, {3, 4}});
  graphmine::KCliqueOptions regression_options;
  regression_options.backend = graphmine::KCliqueBackend::gamma;
  regression_options.k = 4;
  const auto regression = graphmine::KCliques(regression_options).run(gamma_regression);
  require(regression.ok(), regression.status().message().c_str());
  require(regression.value().count == 0, "GAMMA skipped a prefix adjacency check");

  graphmine::KCliqueOptions limited_options;
  // Complete graphs have a closed-form count, independent of all GPU paths.
  std::vector<graphmine::ExternalId> complete_vertices;
  std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>> complete_edges;
  for (int i=0;i<12;++i) {
    complete_vertices.emplace_back(i);
    for (int j=0;j<i;++j) complete_edges.emplace_back(j,i);
  }
  const auto complete = graphmine::Graph::from_edges("K12", complete_vertices, complete_edges);
  for (const auto backend : {graphmine::KCliqueBackend::kcgpu, graphmine::KCliqueBackend::graphset,
                             graphmine::KCliqueBackend::gamma, graphmine::KCliqueBackend::automatic}) {
    const unsigned maximum = backend == graphmine::KCliqueBackend::graphset ? 6 :
                             backend == graphmine::KCliqueBackend::gamma ? 7 : 10;
    std::uint64_t choose=1;
    for (unsigned k=1;k<=maximum;++k) {
      choose=choose*(13-k)/k;
      if (k<6) continue;
      graphmine::KCliqueOptions options;options.backend=backend;options.k=k;
      options.enumerate=true;options.include_per_vertex_counts=true;
      const auto result=graphmine::KCliques(options).run(complete);
      require(result.ok(),result.status().message().c_str());
      require(result.value().count==choose,"higher-order complete-graph count mismatch");
      require(result.value().cliques->size()==choose,"higher-order listing mismatch");
    }
  }
  limited_options.backend = graphmine::KCliqueBackend::graphset;
  // Pivot depth is independent of k. This crosses both the old 401-column
  // Pascal table and the old 512-slot pivot array while only counting triangles.
  complete_vertices.clear();complete_edges.clear();
  for (int i=0;i<514;++i) {
    complete_vertices.emplace_back(i);
    for (int j=0;j<i;++j) complete_edges.emplace_back(j,i);
  }
  const auto deep_pivot_graph=graphmine::Graph::from_edges("K514",complete_vertices,complete_edges);
  graphmine::KCliqueOptions deep_options;
  deep_options.backend=graphmine::KCliqueBackend::kcgpu;deep_options.k=3;
  const auto deep_result=graphmine::KCliques(deep_options).run(deep_pivot_graph);
  require(deep_result.ok(),deep_result.status().message().c_str());
  require(deep_result.value().count==514ULL*513*512/6,"deep pivot Pascal/scratch regression");
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
