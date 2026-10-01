#include "backends/maximum_clique_backend.hpp"

namespace graphmine::detail {

bool maximum_clique_on_gpu_backend_compiled() noexcept { return false; }

MaximumCliqueBackendResult run_maximum_clique_on_gpu(
    const CsrGraph&, int, std::uint32_t) {
  return {{StatusCode::backend_unavailable,
           "the Maximum-Clique-on-GPU backend is not compiled in this build"},
          {}, 0, 0.0};
}

}  // namespace graphmine::detail
