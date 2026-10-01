#include "backends/community_detection_backend.hpp"

namespace graphmine::detail {

bool pggc_backend_compiled() noexcept { return false; }

CommunityDetectionBackendResult run_pggc(const CsrGraph&, int,
                                          PggcAlgorithm) {
  return {{StatusCode::backend_unavailable,
           "the parallel multilevel clustering backend is not compiled in "
           "this build"},
          {}, std::nullopt, 0.0};
}

}  // namespace graphmine::detail
