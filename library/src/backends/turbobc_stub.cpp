#include "backends/betweenness_centrality_backend.hpp"

namespace graphmine::detail {

bool turbobc_backend_compiled() noexcept { return false; }

BetweennessCentralityBackendResult run_turbobc(const CsrGraph&, int) {
  return {{StatusCode::backend_unavailable,
           "TurboBC was not compiled into this GraphMine build"},
          {}, 0.0};
}

}  // namespace graphmine::detail
