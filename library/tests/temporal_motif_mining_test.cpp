#include <cassert>
#include <cstdint>
#include <iostream>
#include <optional>
#include <vector>

#include "graphmine/problems/temporal_motif_mining.hpp"

namespace {

graphmine::Graph validation_graph() {
  graphmine::CanonicalGraphInput input;
  input.graph.id = "temporal-validation-small";
  input.graph.directed = true;
  input.graph.allows_parallel_edges = true;
  for (int vertex = 0; vertex < 6; ++vertex) {
    input.vertices.push_back({vertex, std::nullopt, std::nullopt, {}});
  }

  const std::vector<std::array<int, 3>> events{
      {0, 1, 1},  {1, 2, 3},  {0, 2, 5},  {0, 1, 20},
      {1, 2, 22}, {0, 2, 40}, {3, 4, 7},  {4, 5, 8},
      {3, 5, 9},  {2, 3, 10}, {3, 1, 11}, {2, 1, 12},
  };
  for (std::size_t index = 0; index < events.size(); ++index) {
    input.edges.push_back(
        {static_cast<std::int64_t>(index), events[index][0], events[index][1],
         std::nullopt,
         graphmine::Timestamp{static_cast<std::int64_t>(events[index][2])},
         std::nullopt, {}});
  }
  return graphmine::Graph(std::move(input));
}

void check_backend(graphmine::TemporalMotifBackend backend,
                   bool materialize) {
  graphmine::TemporalMotifOptions options;
  options.backend = backend;
  options.max_time_span = 10;
  if (materialize) {
    options.optional_outputs =
        graphmine::TemporalMotifOptionalOutput::instances;
  }
  graphmine::TemporalMotifMining mining(options);
  const auto result = mining.run(validation_graph());
  if (!result.ok()) {
    std::cerr << graphmine::to_string(backend) << ": "
              << result.status().message() << '\n';
  }
  assert(result.ok());
  assert(result.value().count == 3);
  if (materialize) {
    assert(result.value().instances.has_value());
    assert(result.value().instances->size() == 3);
    assert(result.value().instances_complete);
    const auto& first = result.value().instances->front();
    assert(first.edges_in_temporal_order[0] == graphmine::ExternalId{0});
    assert(first.edges_in_temporal_order[1] == graphmine::ExternalId{1});
    assert(first.edges_in_temporal_order[2] == graphmine::ExternalId{2});
  }
}

void check_timestamp_ties(graphmine::TemporalMotifBackend backend) {
  graphmine::CanonicalGraphInput input;
  input.graph.id = "timestamp-ties";
  input.graph.directed = true;
  input.graph.allows_parallel_edges = true;
  for (int vertex = 0; vertex < 3; ++vertex)
    input.vertices.push_back({vertex, std::nullopt, std::nullopt, {}});
  const std::vector<std::array<int, 3>> events{
      {0, 1, 1}, {1, 2, 1}, {0, 1, 2},
      {1, 2, 2}, {0, 2, 2}, {0, 2, 3}};
  for (std::size_t i = 0; i < events.size(); ++i)
    input.edges.push_back({static_cast<std::int64_t>(i), events[i][0],
        events[i][1], std::nullopt,
        graphmine::Timestamp{static_cast<std::int64_t>(events[i][2])},
        std::nullopt, {}});
  const graphmine::Graph graph(std::move(input));
  graphmine::TemporalMotifOptions options;
  options.backend = backend;
  options.max_time_span = 2;
  const auto counted = graphmine::TemporalMotifMining(options).run(graph);
  assert(counted.ok() && counted.value().count == 1);
  options.optional_outputs = graphmine::TemporalMotifOptionalOutput::instances;
  const auto listed = graphmine::TemporalMotifMining(options).run(graph);
  assert(listed.ok() && listed.value().count == 1);
  assert(listed.value().instances_complete && listed.value().instances->size() == 1);
  const auto& ids = listed.value().instances->front().edges_in_temporal_order;
  assert((ids == std::array<graphmine::ExternalId, 3>{0, 3, 5}));
  options.max_time_span = 0;
  const auto zero_window = graphmine::TemporalMotifMining(options).run(graph);
  assert(zero_window.ok() && zero_window.value().count == 0);
}

}  // namespace

int main() {
  check_backend(graphmine::TemporalMotifBackend::everest, true);
  check_backend(graphmine::TemporalMotifBackend::mayura, false);
  check_timestamp_ties(graphmine::TemporalMotifBackend::everest);
  check_timestamp_ties(graphmine::TemporalMotifBackend::mayura);
  return 0;
}
