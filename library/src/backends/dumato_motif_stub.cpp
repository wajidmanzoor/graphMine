#include "backends/graph_motif_backend.hpp"

namespace graphmine::detail {

bool dumato_motif_backend_compiled() noexcept { return false; }

GraphMotifBackendResult run_dumato_motifs(const CsrGraph&, std::uint32_t,
                                          int) {
  return {{StatusCode::backend_unavailable,
           "DuMato motifs were not compiled into this GraphMine build"},
          {}, 0.0};
}

}  // namespace graphmine::detail
