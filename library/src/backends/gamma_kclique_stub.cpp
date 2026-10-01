#include "backends/k_clique_backend.hpp"

namespace graphmine::detail {

bool gamma_kclique_backend_compiled() noexcept { return false; }

KCliqueBackendResult run_gamma_kclique(const CsrGraph&, std::uint32_t, int) {
  return {{StatusCode::backend_unavailable,
           "GAMMA was not compiled into this GraphMine build"},
          0, 0.0};
}

}  // namespace graphmine::detail
