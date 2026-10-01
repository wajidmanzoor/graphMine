#include "backends/maximal_cliques/backend.hpp"

namespace graphmine::detail {

bool rdmce_backend_compiled() noexcept { return false; }

BackendCountResult run_rdmce_count(const CsrGraph&, int) {
  return {Status{StatusCode::backend_unavailable,
                 "RDMCE was not compiled into this GraphMine build"},
          0, 0.0};
}

}  // namespace graphmine::detail
