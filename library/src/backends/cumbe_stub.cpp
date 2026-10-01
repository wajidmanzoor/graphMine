#include "backends/maximal_biclique_backend.hpp"

namespace graphmine::detail {

bool cumbe_backend_compiled() noexcept { return false; }

MaximalBicliqueBackendResult run_cumbe(const BipartiteCsrGraph&, int) {
  return {{StatusCode::backend_unavailable,
           "cuMBE was not compiled into this GraphMine build"},
          0, 0.0};
}

}  // namespace graphmine::detail
