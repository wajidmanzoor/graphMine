#include "backends/subgraph_isomorphism_backend.hpp"

namespace graphmine::detail {

bool gmatch_backend_compiled() noexcept { return false; }

SubgraphIsomorphismBackendResult run_gmatch(
    const CsrGraph&, const std::vector<int>&, const CsrGraph&,
    const std::vector<int>&, std::size_t, int) {
  return {{StatusCode::backend_unavailable,
           "gMatch was not compiled into this GraphMine build"},
          0, 0.0};
}

}  // namespace graphmine::detail
