#include "backends/k_core_backend.hpp"

namespace graphmine::detail {

bool kcore_gpu_backend_compiled() noexcept { return false; }

KCoreBackendResult run_kcore_gpu(const CsrGraph&, int) {
  return {Status{StatusCode::backend_unavailable,
                 "KCoreGPU was not compiled into this GraphMine build"},
          {}, 0.0};
}

}  // namespace graphmine::detail
