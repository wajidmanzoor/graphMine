#include "backends/temporal_motif_backend.hpp"

namespace graphmine::detail {

bool everest_backend_compiled() noexcept { return false; }

TemporalMotifBackendResult run_everest(const TemporalMotifBackendInput&, int) {
  return {{StatusCode::backend_unavailable,
           "the Everest backend is not compiled in this build"},
          0, 0.0};
}

}  // namespace graphmine::detail
