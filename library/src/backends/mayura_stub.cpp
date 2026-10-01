#include "backends/temporal_motif_backend.hpp"

namespace graphmine::detail {

bool mayura_backend_compiled() noexcept { return false; }

TemporalMotifBackendResult run_mayura(const TemporalMotifBackendInput&, int) {
  return {{StatusCode::backend_unavailable,
           "the Mayura backend is not compiled in this build"},
          0, 0.0};
}

}  // namespace graphmine::detail
