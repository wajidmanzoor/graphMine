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

}  // namespace

int main() {
  check_backend(graphmine::TemporalMotifBackend::everest, true);
  check_backend(graphmine::TemporalMotifBackend::mayura, false);
  return 0;
}
