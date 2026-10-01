#include <cassert>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "graphmine/graph.hpp"

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

}  // namespace

int main() {
  using graphmine::ExternalId;

  auto graph = graphmine::Graph::from_edges(
      "mixed-ids", {ExternalId{"alice"}, ExternalId{42}, ExternalId{"isolated"}},
      {{ExternalId{"alice"}, ExternalId{42}}});
  require(graph.vertex_count() == 3, "vertex count mismatch");
  require(graph.edge_count() == 1, "edge count mismatch");
  require(graph.dense_index(ExternalId{"alice"}) == 0,
          "dense ID mapping mismatch");
  require(graph.external_id(1) == ExternalId{42},
          "external ID mapping mismatch");

  const auto view = graph.simple_undirected();
  require(view.csr.vertex_count() == 3, "CSR vertex count mismatch");
  require(view.csr.undirected_edge_count() == 1,
          "CSR edge count mismatch");
  require(view.csr.offsets == std::vector<std::uint64_t>({0, 1, 2, 2}),
          "CSR offsets mismatch");

  auto directed = graphmine::Graph::from_edges(
      "directed", {0, 1}, {{0, 1}}, true);
  bool rejected = false;
  try {
    static_cast<void>(directed.simple_undirected());
  } catch (const std::invalid_argument&) {
    rejected = true;
  }
  require(rejected, "directed input was not rejected");
  const auto projected = directed.simple_undirected({true});
  require(projected.normalization.directed_projection_applied,
          "directed projection was not recorded");

  return 0;
}
