#include "graphmine/views.hpp"
#include <stdexcept>
// This executable links only the core, never the native runtime.
int main() {
  auto input = graphmine::Graph::from_edges("standalone", {"b", "a", "isolate"},
                                           {{"b", "a"}}, true).canonical();
  input.graph.allows_parallel_edges = input.graph.allows_self_loops = true;
  auto edge = input.edges[0]; edge.id = 1; edge.source = "a"; edge.target = "b";
  input.edges.push_back(edge);
  edge.id = 2; edge.target = "a"; input.edges.push_back(edge);
  const graphmine::Graph graph(input);
  const auto spec = graphmine::ViewSpec::from_json(
      R"({"direction":"symmetrize","self_loops":"drop","parallel_edges":"collapse:first","weights":"none"})");
  const auto result = graphmine::make_view(graph, spec);
  const auto& csr = std::get<graphmine::CsrView>(result->view);
  const auto simple = graph.simple_undirected({true});
  if (csr.offsets != simple.csr.offsets || csr.indices != simple.csr.neighbors ||
      result->normalization.self_loops_removed != 1 || result->normalization.parallel_edges_collapsed != 1)
    throw std::runtime_error("standalone core view mismatch");
  bool rejected = false;
  try { (void)graph.simple_undirected(); } catch (const std::invalid_argument&) { rejected = true; }
  if (!rejected) throw std::runtime_error("implicit directed projection accepted");
}
