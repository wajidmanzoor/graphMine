#include "backends/triangle_backend.hpp"

namespace graphmine::detail {

bool wetric_backend_compiled() noexcept { return false; }

TriangleBackendResult run_wetric(const CsrGraph&, int, std::uint32_t,
                                 std::uint32_t) {
  return {{StatusCode::backend_unavailable,
           "WeTriC was not compiled into this GraphMine build"},
          0, 0.0};
}

}  // namespace graphmine::detail
