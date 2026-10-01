#include "backends/community_detection_backend.hpp"

namespace graphmine::detail {

bool gleiden_backend_compiled() noexcept { return false; }

CommunityDetectionBackendResult run_gleiden(const CsrGraph&, int) {
  return {{StatusCode::backend_unavailable,
           "the gLeiden backend is not compiled in this build"},
          {}, std::nullopt, 0.0};
}

}  // namespace graphmine::detail
