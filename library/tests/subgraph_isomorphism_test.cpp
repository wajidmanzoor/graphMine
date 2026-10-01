#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/problems/subgraph_isomorphism.hpp"

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

graphmine::Graph make_query(
    const std::string& name, std::size_t vertex_count,
    const std::vector<std::pair<graphmine::ExternalId,
                                graphmine::ExternalId>>& edges) {
  std::vector<graphmine::ExternalId> vertices;
  for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
    vertices.emplace_back(static_cast<std::int64_t>(vertex));
  }
  return graphmine::Graph::from_edges(name, std::move(vertices), edges);
}

}  // namespace

int main() {
  std::vector<graphmine::ExternalId> vertices;
  for (std::int64_t vertex = 0; vertex < 12; ++vertex) {
    vertices.emplace_back(vertex);
  }
  const std::vector<std::pair<graphmine::ExternalId, graphmine::ExternalId>>
      edges = {{0, 1}, {0, 2}, {0, 3}, {0, 4}, {1, 2}, {1, 3},
               {1, 4}, {2, 3}, {2, 4}, {3, 4}, {4, 5}, {5, 6},
               {5, 7}, {6, 7}, {7, 8}, {8, 9}, {8, 10}, {8, 11},
               {9, 10}, {10, 11}};
  const auto data =
      graphmine::Graph::from_edges("validation-small", vertices, edges);

  const auto triangle =
      make_query("triangle", 3, {{0, 1}, {0, 2}, {1, 2}});
  const auto clique4 = make_query(
      "clique4", 4,
      {{0, 1}, {0, 2}, {0, 3}, {1, 2}, {1, 3}, {2, 3}});
  const auto cycle4 =
      make_query("cycle4", 4, {{0, 1}, {0, 3}, {1, 2}, {2, 3}});
  const auto diamond = make_query(
      "diamond", 4, {{0, 1}, {0, 2}, {0, 3}, {1, 2}, {1, 3}});

  graphmine::SubgraphIsomorphismOptions options;
  options.backend = graphmine::SubgraphIsomorphismBackend::gmatch;
  options.respect_vertex_labels = false;
  graphmine::SubgraphIsomorphism algorithm(options);
  for (const auto& expected :
       std::vector<std::pair<const graphmine::Graph*, std::uint64_t>>{
           {&triangle, 78}, {&clique4, 120}, {&cycle4, 128},
           {&diamond, 124}}) {
    const auto result = algorithm.run(data, *expected.first);
    require(result.ok(), result.status().message().c_str());
    require(result.value().count == expected.second,
            "gMatch count differed from the validated reference");
    require(!result.value().embeddings.has_value(),
            "embeddings must only be populated when requested");
  }

  options.optional_outputs =
      graphmine::SubgraphIsomorphismOptionalOutput::embeddings;
  const auto materialized =
      graphmine::SubgraphIsomorphism(options).run(data, triangle);
  require(materialized.ok(), materialized.status().message().c_str());
  require(materialized.value().count == 78 &&
              materialized.value().embeddings.has_value() &&
              materialized.value().embeddings->size() == 78 &&
              materialized.value().embeddings_complete,
          "optional exact embedding materialization mismatch");

  options.result_limit = 5;
  const auto limited =
      graphmine::SubgraphIsomorphism(options).run(data, triangle);
  require(limited.ok(), limited.status().message().c_str());
  require(limited.value().count == 78 &&
              limited.value().embeddings->size() == 5 &&
              !limited.value().embeddings_complete,
          "limited embedding materialization mismatch");
  return 0;
}
