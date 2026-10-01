#include "backends/maximal_cliques/backend.hpp"

namespace graphmine::detail {

bool g2_aimd_backend_compiled() noexcept { return false; }

BackendCountResult run_g2_aimd_count(const CsrGraph&, int) {
  return {Status{StatusCode::backend_unavailable,
                 "G2-AIMD was not compiled into this GraphMine build"},
          0, 0.0};
}

}  // namespace graphmine::detail
