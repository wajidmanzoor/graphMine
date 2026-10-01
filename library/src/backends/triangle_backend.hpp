#pragma once

#include <cstdint>

#include "graphmine/graph.hpp"
#include "graphmine/status.hpp"

namespace graphmine::detail {

struct TriangleBackendResult {
  Status status;
  std::uint64_t count = 0;
  double elapsed_ms = 0.0;
};

[[nodiscard]] bool tot_backend_compiled() noexcept;
[[nodiscard]] TriangleBackendResult run_tot(const CsrGraph& graph,
                                            int device_id);
[[nodiscard]] bool wetric_backend_compiled() noexcept;
[[nodiscard]] TriangleBackendResult run_wetric(
    const CsrGraph& graph, int device_id, std::uint32_t spread,
    std::uint32_t adjacency_matrix_length);

}  // namespace graphmine::detail
