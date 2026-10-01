#include "backends/graph_motif_backend.hpp"

namespace graphmine::detail {

bool graphset_motif_backend_compiled() noexcept { return false; }

GraphMotifBackendResult run_graphset_motifs(const CsrGraph&, std::uint32_t,
                                            int) {
  return {{StatusCode::backend_unavailable,
           "GraphSet motifs were not compiled into this GraphMine build"},
          {}, 0.0};
}

}  // namespace graphmine::detail
