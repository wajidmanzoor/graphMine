#include "backends/dynamic_triangle_backend.hpp"

namespace graphmine::detail {

bool edtc_backend_compiled() noexcept { return false; }

DynamicTriangleBackendResult run_edtc(
    const CsrGraph&, const std::vector<DenseTriangleUpdate>&, int) {
  return {{StatusCode::backend_unavailable,
           "EDTC was not compiled into this GraphMine build"},
          0, 0, 0.0};
}

}  // namespace graphmine::detail
