#include "backends/k_clique_backend.hpp"

namespace graphmine::detail {

bool kcgpu_backend_compiled() noexcept { return false; }

KCliqueBackendResult run_kcgpu(const CsrGraph&, std::uint32_t, int) {
  return {{StatusCode::backend_unavailable,
           "KCGPU was not compiled into this GraphMine build"},
          0, 0.0};
}

}  // namespace graphmine::detail
