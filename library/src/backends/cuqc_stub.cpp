#include "backends/quasi_clique_backend.hpp"

namespace graphmine::detail {

bool cuqc_backend_compiled() noexcept { return false; }

QuasiCliqueBackendResult run_cuqc(const CsrGraph&, double, std::size_t, bool,
                                  int) {
  return {{StatusCode::backend_unavailable,
           "cuQC was not compiled into this GraphMine build"},
          {}, 0.0};
}

}  // namespace graphmine::detail
