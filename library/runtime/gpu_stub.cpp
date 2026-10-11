#include "internal.hpp"
namespace graphmine::runtime {
std::vector<std::vector<VertexIndex>> cugraph_walks(const WeightedGraph&, const std::vector<VertexIndex>&, std::uint64_t, const std::string&, double, double, std::uint64_t, int, Work&) {
  throw Failure("backend_unavailable", "libcugraph is not linked in this native build");
}
bool cugraph_compiled() noexcept { return false; }
std::string cugraph_version() { return "not-linked"; }
std::vector<Search> cugraph_bfs(const Graph&, const std::vector<VertexIndex>&,
                              std::optional<std::uint64_t>, int, Work&) {
  throw Failure("backend_unavailable", "libcugraph is not linked in this native build");
}
std::vector<WeightedSearch> cugraph_shortest_paths(const WeightedGraph&, const std::vector<VertexIndex>&, int, Work&) {
  throw Failure("backend_unavailable", "libcugraph is not linked in this native build");
}
std::vector<std::pair<VertexIndex, VertexIndex>> cugraph_spanning_forest(const WeightedGraph&, bool, int, Work&) {
  throw Failure("backend_unavailable", "libcugraph is not linked in this native build");
}
std::vector<std::vector<VertexIndex>> cugraph_components(const WeightedGraph&, bool, int, Work&) {
  throw Failure("backend_unavailable", "libcugraph is not linked in this native build");
}
std::vector<double> cugraph_pagerank(const WeightedGraph&, const std::vector<double>&, double, double, std::uint64_t, int, Work&) {
  throw Failure("backend_unavailable", "libcugraph is not linked in this native build");
}
std::vector<double> cugraph_jaccard(const WeightedGraph&, const std::vector<std::pair<VertexIndex, VertexIndex>>&, int, Work&) {
  throw Failure("backend_unavailable", "libcugraph is not linked in this native build");
}
std::vector<std::uint32_t> cugraph_truss_numbers(const WeightedGraph&, const std::vector<std::pair<VertexIndex, VertexIndex>>&, int, Work&) {
  throw Failure("backend_unavailable", "libcugraph was not linked in this build");
}
std::vector<std::uint32_t> cugraph_core_numbers(const WeightedGraph&, int, Work&) {
  throw Failure("backend_unavailable", "libcugraph is not linked in this native build");
}
std::vector<double> cugraph_betweenness(const WeightedGraph&, int, Work&) {
  throw Failure("backend_unavailable", "libcugraph is not linked in this native build");
}
}
