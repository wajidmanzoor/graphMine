#include "internal.hpp"
namespace graphmine::runtime {
bool cugraph_compiled() noexcept { return false; }
std::string cugraph_version() { return "not-linked"; }
std::vector<Search> cugraph_bfs(const Graph&, const std::vector<VertexIndex>&,
                              std::optional<std::uint64_t>, int, Work&) {
  throw Failure("backend_unavailable", "libcugraph is not linked in this native build");
}
}
