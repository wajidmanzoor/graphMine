#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/problems/graph_motifs.hpp"

namespace {

void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

graphmine::Graph motif(
    const std::string& id, std::size_t size,
    const std::vector<std::pair<graphmine::ExternalId,
                                graphmine::ExternalId>>& edges) {
  std::vector<graphmine::ExternalId> vertices;
  for (std::size_t vertex = 0; vertex < size; ++vertex) {
    vertices.emplace_back(static_cast<std::int64_t>(vertex));
  }
  return graphmine::Graph::from_edges(id, std::move(vertices), edges);
}

}  // namespace

int main() {
  std::vector<graphmine::ExternalId> vertices;
  for (std::int64_t vertex = 0; vertex < 12; ++vertex) {
    vertices.emplace_back(vertex);
  }
  const auto data = graphmine::Graph::from_edges(
      "motif-small", vertices,
      {{0, 1}, {0, 2}, {0, 3}, {0, 4}, {1, 2}, {1, 3},
       {1, 4}, {2, 3}, {2, 4}, {3, 4}, {4, 5}, {5, 6},
       {5, 7}, {6, 7}, {7, 8}, {8, 9}, {8, 10}, {8, 11},
       {9, 10}, {10, 11}});

  const std::vector<graphmine::Graph> patterns = {
      motif("triangle", 3, {{0, 1}, {0, 2}, {1, 2}}),
      motif("wedge", 3, {{0, 1}, {0, 2}}),
      motif("star3", 4, {{0, 1}, {0, 2}, {0, 3}}),
      motif("path4", 4, {{0, 1}, {1, 2}, {2, 3}}),
      motif("tailed-triangle", 4,
            {{0, 1}, {0, 2}, {1, 2}, {2, 3}}),
      motif("cycle4", 4, {{0, 1}, {1, 2}, {2, 3}, {3, 0}}),
      motif("diamond", 4,
            {{0, 1}, {0, 2}, {0, 3}, {1, 2}, {1, 3}}),
      motif("clique4", 4,
            {{0, 1}, {0, 2}, {0, 3}, {1, 2}, {1, 3}, {2, 3}})};

  graphmine::GraphMotifOptions options;
  options.backend = graphmine::GraphMotifBackend::graphminer;
  options.induced = true;
  const auto result = graphmine::GraphMotifs(options).run(data, patterns);
  require(result.ok(), result.status().message().c_str());
  const std::vector<std::uint64_t> expected = {13, 13, 1, 15, 10, 0, 1, 5};
  require(result.value().motifs.size() == expected.size(),
          "motif result size mismatch");
  for (std::size_t index = 0; index < expected.size(); ++index) {
    require(result.value().motifs[index].count == expected[index],
            "GraphMiner induced motif count mismatch");
    require(!result.value().motifs[index].instances.has_value(),
            "motif instances must be flag-controlled");
  }

  options.occurrence_identity =
      graphmine::MotifOccurrenceIdentity::all_embeddings;
  options.optional_outputs = graphmine::GraphMotifOptionalOutput::instances |
                             graphmine::GraphMotifOptionalOutput::
                                 per_vertex_participation;
  options.result_limit_per_motif = 10;
  const auto materialized =
      graphmine::GraphMotifs(options).run(data, {patterns.front()});
  require(materialized.ok(), materialized.status().message().c_str());
  const auto& triangle = materialized.value().motifs.front();
  require(triangle.count == 78 && triangle.instances->size() == 10 &&
              !triangle.instances_complete,
          "all-embedding triangle materialization mismatch");
  std::uint64_t participation = 0;
  for (const auto& entry : *triangle.per_vertex_participation) {
    participation += entry.count;
  }
  require(participation == triangle.count * 3,
          "motif participation invariant mismatch");

  options = {};
  options.backend = graphmine::GraphMotifBackend::graphset;
  options.induced = false;
  const auto graphset = graphmine::GraphMotifs(options).run(data, patterns);
  require(graphset.ok(), graphset.status().message().c_str());
  const std::vector<std::uint64_t> non_induced_expected = {
      13, 52, 33, 101, 74, 16, 31, 5};
  require(graphset.value().motifs.size() == non_induced_expected.size(),
          "GraphSet motif result size mismatch");
  for (std::size_t index = 0; index < non_induced_expected.size(); ++index) {
    require(graphset.value().motifs[index].count ==
                non_induced_expected[index],
            "GraphSet non-induced motif count mismatch");
  }

  options.occurrence_identity =
      graphmine::MotifOccurrenceIdentity::all_embeddings;
  options.optional_outputs = graphmine::GraphMotifOptionalOutput::instances |
                             graphmine::GraphMotifOptionalOutput::
                                 per_vertex_participation;
  options.result_limit_per_motif = 10;
  const auto graphset_materialized =
      graphmine::GraphMotifs(options).run(data, {patterns.front()});
  require(graphset_materialized.ok(),
          graphset_materialized.status().message().c_str());
  const auto& graphset_triangle =
      graphset_materialized.value().motifs.front();
  require(graphset_triangle.count == 78 &&
              graphset_triangle.instances->size() == 10 &&
              !graphset_triangle.instances_complete,
          "GraphSet all-embedding triangle materialization mismatch");
  participation = 0;
  for (const auto& entry : *graphset_triangle.per_vertex_participation) {
    participation += entry.count;
  }
  require(participation == graphset_triangle.count * 3,
          "GraphSet motif participation invariant mismatch");

  options = {};
  options.backend = graphmine::GraphMotifBackend::dumato;
  options.induced = true;
  const auto dumato = graphmine::GraphMotifs(options).run(data, patterns);
  require(dumato.ok(), dumato.status().message().c_str());
  for (std::size_t index = 0; index < expected.size(); ++index) {
    require(dumato.value().motifs[index].count == expected[index],
            "DuMato induced motif count mismatch");
  }

  options.occurrence_identity =
      graphmine::MotifOccurrenceIdentity::all_embeddings;
  options.optional_outputs = graphmine::GraphMotifOptionalOutput::instances;
  options.result_limit_per_motif = 10;
  const auto dumato_materialized =
      graphmine::GraphMotifs(options).run(data, {patterns.front()});
  require(dumato_materialized.ok(),
          dumato_materialized.status().message().c_str());
  const auto& dumato_triangle = dumato_materialized.value().motifs.front();
  require(dumato_triangle.count == 78 &&
              dumato_triangle.instances->size() == 10 &&
              !dumato_triangle.instances_complete,
          "DuMato all-embedding triangle materialization mismatch");
  return 0;
}
