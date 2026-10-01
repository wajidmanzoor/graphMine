#pragma once

#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/status.hpp"

namespace graphmine::detail {

enum class PggcAlgorithm {
  parallel_louvain,
  parallel_leiden,
  parallel_leiden_plus,
};

struct CommunityDetectionBackendResult {
  Status status;
  std::vector<std::uint32_t> labels;
  std::optional<double> native_modularity;
  double elapsed_ms = 0.0;
};

[[nodiscard]] bool gleiden_backend_compiled() noexcept;
[[nodiscard]] CommunityDetectionBackendResult run_gleiden(
    const CsrGraph& graph, int device_id);

[[nodiscard]] bool pggc_backend_compiled() noexcept;
[[nodiscard]] CommunityDetectionBackendResult run_pggc(
    const CsrGraph& graph, int device_id, PggcAlgorithm algorithm);

}  // namespace graphmine::detail
