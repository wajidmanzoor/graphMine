#include "backends/triangle_backend.hpp"

namespace graphmine::detail {

bool tot_backend_compiled() noexcept { return false; }

TriangleBackendResult run_tot(const CsrGraph&, int) {
  return {{StatusCode::backend_unavailable,
           "ToT was not compiled into this GraphMine build"},
          0, 0.0};
}

}  // namespace graphmine::detail
