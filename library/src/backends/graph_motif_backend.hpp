#pragma once

#include <cstdint>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/status.hpp"

namespace graphmine::detail {

struct GraphMotifBackendResult {
  Status status;
  std::vector<std::uint64_t> counts;
  double elapsed_ms = 0.0;
};

[[nodiscard]] bool graphminer_motif_backend_compiled() noexcept;
[[nodiscard]] GraphMotifBackendResult run_graphminer_motifs(
    const CsrGraph& graph, std::uint32_t motif_size, int device_id);

[[nodiscard]] bool graphset_motif_backend_compiled() noexcept;
[[nodiscard]] GraphMotifBackendResult run_graphset_motifs(
    const CsrGraph& graph, std::uint32_t motif_size, int device_id);

[[nodiscard]] bool dumato_motif_backend_compiled() noexcept;
[[nodiscard]] GraphMotifBackendResult run_dumato_motifs(
    const CsrGraph& graph, std::uint32_t motif_size, int device_id);

}  // namespace graphmine::detail
