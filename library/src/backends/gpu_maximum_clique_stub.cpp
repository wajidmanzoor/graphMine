#include "backends/maximum_clique_backend.hpp"

namespace graphmine::detail {

bool gpu_maximum_clique_backend_compiled() noexcept { return false; }

MaximumCliqueBackendResult run_gpu_maximum_clique(
    const CsrGraph&, int, std::uint32_t, bool) {
  return {{StatusCode::backend_unavailable,
           "the GPUMaximumClique backend is not compiled in this build"},
          {}, 0, 0.0};
}

}  // namespace graphmine::detail
