#include "backends/maximum_clique_backend.hpp"

namespace graphmine::detail {

bool cuda_ms_backend_compiled() noexcept { return false; }

MaximumCliqueBackendResult run_cuda_ms(const CsrGraph&, int) {
  return {{StatusCode::backend_unavailable,
           "CUDA-MS was not compiled into this GraphMine build"},
          {}, 0, 0.0};
}

}  // namespace graphmine::detail
