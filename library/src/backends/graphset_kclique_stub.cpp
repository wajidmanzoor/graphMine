#include "backends/k_clique_backend.hpp"

namespace graphmine::detail {

bool graphset_kclique_backend_compiled() noexcept { return false; }

KCliqueBackendResult run_graphset_kclique(const CsrGraph&, std::uint32_t,
                                          int) {
  return {{StatusCode::backend_unavailable,
           "GraphSet k-clique was not compiled into this GraphMine build"},
          0, 0.0};
}

}  // namespace graphmine::detail
