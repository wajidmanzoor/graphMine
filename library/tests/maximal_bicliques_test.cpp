#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/problems/maximal_bicliques.hpp"

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

std::vector<graphmine::ExternalId> ids(std::initializer_list<int> values) {
  std::vector<graphmine::ExternalId> output;
  for (const auto value : values) {
    output.emplace_back(value);
  }
  return output;
}

}  // namespace

int main() {
  std::vector<graphmine::ExternalId> vertices;
  for (std::int64_t vertex = 0; vertex < 11; ++vertex) {
    vertices.emplace_back(vertex);
  }
  const std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>>
      edges = {{0, 5}, {0, 6}, {0, 7}, {1, 5}, {1, 6},  {1, 7},
               {2, 5}, {2, 6}, {2, 7}, {2, 8}, {2, 9},  {3, 7},
               {3, 8}, {3, 9}, {3, 10}, {4, 9}, {4, 10}};
  const auto graph =
      graphmine::Graph::from_edges("bipartite-small", vertices, edges);

  graphmine::MaximalBicliqueOptions options;
  options.left_partition = ids({0, 1, 2, 3, 4});
  options.backend = graphmine::MaximalBicliqueBackend::cumbe;
  options.optional_outputs =
      graphmine::MaximalBicliqueOptionalOutput::total_count;
  graphmine::MaximalBicliques algorithm(options);
  const auto result = algorithm.run(graph);
  require(result.ok(), result.status().message().c_str());
  require(result.value().complete, "maximal-biclique output is incomplete");
  require(result.value().total_count == 7,
          "maximal-biclique total mismatch");

  const std::vector<std::pair<std::vector<graphmine::ExternalId>,
                              std::vector<graphmine::ExternalId>>>
      expected = {{ids({2}), ids({5, 6, 7, 8, 9})},
                  {ids({3}), ids({7, 8, 9, 10})},
                  {ids({2, 3}), ids({7, 8, 9})},
                  {ids({3, 4}), ids({9, 10})},
                  {ids({0, 1, 2}), ids({5, 6, 7})},
                  {ids({2, 3, 4}), ids({9})},
                  {ids({0, 1, 2, 3}), ids({7})}};
  require(result.value().bicliques.size() == expected.size(),
          "maximal-biclique set count mismatch");
  for (std::size_t index = 0; index < expected.size(); ++index) {
    require(result.value().bicliques[index].left == expected[index].first,
            "maximal-biclique left side mismatch");
    require(result.value().bicliques[index].right == expected[index].second,
            "maximal-biclique right side mismatch");
  }

  options.result_limit = 2;
  graphmine::MaximalBicliques limited(options);
  const auto limited_result = limited.run(graph);
  require(limited_result.ok(), limited_result.status().message().c_str());
  require(limited_result.value().returned_count == 2 &&
              !limited_result.value().complete &&
              limited_result.value().total_count == 7,
          "limited maximal-biclique output mismatch");

  std::vector<graphmine::ExternalId> medium_vertices;
  for (std::int64_t vertex = 0; vertex < 80; ++vertex) {
    medium_vertices.emplace_back(vertex);
  }
  std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>>
      medium_edges;
  for (int block = 0; block < 4; ++block) {
    for (int left = block * 8; left < block * 8 + 8; ++left) {
      for (int right = 32 + block * 12;
           right < 32 + block * 12 + 10; ++right) {
        medium_edges.emplace_back(left, right);
      }
    }
    medium_edges.emplace_back(block * 8 + 7,
                              32 + ((block + 1) % 4) * 12);
  }
  medium_edges.emplace_back(0, 42);
  medium_edges.emplace_back(8, 54);
  medium_edges.emplace_back(16, 66);
  medium_edges.emplace_back(24, 32);
  auto medium_graph = graphmine::Graph::from_edges(
      "bipartite-medium", medium_vertices, medium_edges);
  graphmine::MaximalBicliqueOptions medium_options;
  for (int vertex = 0; vertex < 32; ++vertex) {
    medium_options.left_partition.emplace_back(vertex);
  }
  medium_options.backend = graphmine::MaximalBicliqueBackend::cumbe;
  medium_options.optional_outputs =
      graphmine::MaximalBicliqueOptionalOutput::total_count;
  const auto medium_result =
      graphmine::MaximalBicliques(medium_options).run(medium_graph);
  require(medium_result.ok(), medium_result.status().message().c_str());
  require(medium_result.value().complete &&
              medium_result.value().returned_count == 15 &&
              medium_result.value().total_count == 15,
          "medium maximal-biclique validation mismatch");
  return 0;
}
