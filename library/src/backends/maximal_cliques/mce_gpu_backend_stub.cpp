#include "backends/maximal_cliques/backend.hpp"

namespace graphmine::detail {

bool mce_gpu_backend_compiled() noexcept { return false; }

BackendCountResult run_mce_gpu_count(const CsrGraph&, int) {
  return {Status{StatusCode::backend_unavailable,
                 "mce-gpu was not compiled into this GraphMine build"},
          0, 0.0};
}

}  // namespace graphmine::detail
