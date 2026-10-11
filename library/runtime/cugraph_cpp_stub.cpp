#include "internal.hpp"
namespace graphmine::runtime {
bool cugraph_cpp_compiled() noexcept { return false; }
std::vector<VertexIndex> cugraph_maximal_independent(const MiningGraph&, std::uint64_t, int,
                                                     Work&) {
  throw Failure("backend_unavailable", "The libcugraph C++ interface is not linked in this build");
}
std::vector<std::uint32_t> cugraph_vertex_coloring(const MiningGraph&, std::uint64_t, int, Work&) {
  throw Failure("backend_unavailable", "The libcugraph C++ interface is not linked in this build");
}
}  // namespace graphmine::runtime
