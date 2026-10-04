#include "graphmine/problems/validated_expansion.hpp"

#include <iostream>
#include <stdexcept>

namespace gm = graphmine;

static void check(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

int main() {
  try {
    auto graph = gm::Graph::from_edges("components", {0, 1, 2, 3},
                                     {{0, 1}, {1, 0}, {1, 2}}, true);
    if (!gm::ConnectedComponents::backends().front().compiled) {
      check(!gm::ConnectedComponents().supports(graph).supported,
            "CUDA-disabled supports must be false");
      auto result = gm::ConnectedComponents().run(graph);
      check(!result.ok() && result.status().code() == gm::StatusCode::backend_unavailable,
            "CUDA-disabled call must report backend_unavailable");
      return 0;
    }
    auto components = gm::ConnectedComponents().run(graph);
    check(components.ok() && components.value().component_sizes ==
          std::vector<std::uint64_t>({2, 1, 1}), "strong partition is incorrect");
    gm::ConnectedComponentsOptions weak;
    weak.connectivity_mode = gm::ConnectivityMode::weakly_connected;
    components = gm::ConnectedComponents(weak).run(graph);
    check(components.ok() && components.value().component_sizes ==
          std::vector<std::uint64_t>({3, 1}), "weak partition is incorrect");
    auto closure = gm::TransitiveClosure().run(graph);
    check(closure.ok() && closure.value().reachable_pair_count == 8,
          "reflexive closure is incomplete");

    gm::CanonicalGraphInput network;
    network.graph.id = "flow";
    network.graph.directed = true;
    network.vertices = {{0}, {1}, {2}};
    network.edges = {{"a", 0, 1, 7}, {"b", 1, 2, 5}, {"c", 0, 2, 2}};
    gm::MaxFlowOptions flow_options;
    flow_options.source = 0;
    flow_options.sink = 2;
    auto flow = gm::MaxFlowMinCut(flow_options).run(gm::Graph(network));
    check(flow.ok() && flow.value().max_flow_value == 7 &&
          flow.value().min_cut_value == 7 && flow.value().optimal,
          "flow/cut certificate is incorrect");
    network.edges.clear();
    flow = gm::MaxFlowMinCut(flow_options).run(gm::Graph(network));
    check(flow.ok() && flow.value().max_flow_value == 0,
          "edgeless flow must avoid a zero-grid launch");

    gm::CanonicalGraphInput assignment;
    assignment.graph.id = "assignment";
    assignment.vertices = {{"left-a"}, {"left-b"}, {"right-a"}, {"right-b"}};
    for (int i = 0; i < 4; ++i)
      assignment.vertices[i].attributes["side"] = i < 2 ? "left" : "right";
    assignment.edges = {{0, "left-a", "right-a", 4},
                        {1, "left-a", "right-b", 1},
                        {2, "left-b", "right-a", 0},
                        {3, "left-b", "right-b", 3}};
    auto matching = gm::LinearAssignment().run(gm::Graph(assignment));
    check(matching.ok() && matching.value().matching_edges ==
          std::vector<gm::ExternalId>({1, 2}) && matching.value().objective_value == 1,
          "minimum-cost perfect assignment is incorrect");
    if (gm::ButterflyCounting::backends().front().compiled) {
      auto count = gm::ButterflyCounting().run(gm::Graph(assignment));
      check(count.ok() && count.value().butterfly_count == 1,
            "single K2,2 must have exactly one butterfly");
    }
    assignment.edges.pop_back();
    check(!gm::LinearAssignment().supports(gm::Graph(assignment)).supported,
          "incomplete assignment matrices must be rejected");
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
