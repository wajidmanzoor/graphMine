#pragma once

#include <cstdint>

#include "graphmine/graph.hpp"
#include "graphmine/status.hpp"

namespace graphmine::detail {

struct BackendCountResult {
  Status status;
  std::uint64_t count = 0;
  double elapsed_ms = 0.0;
};

[[nodiscard]] bool rdmce_backend_compiled() noexcept;
[[nodiscard]] BackendCountResult run_rdmce_count(const CsrGraph& graph,
                                                 int device_id);
[[nodiscard]] bool mce_gpu_backend_compiled() noexcept;
[[nodiscard]] BackendCountResult run_mce_gpu_count(const CsrGraph& graph,
                                                   int device_id);
[[nodiscard]] bool g2_aimd_backend_compiled() noexcept;
[[nodiscard]] BackendCountResult run_g2_aimd_count(const CsrGraph& graph,
                                                   int device_id);

}  // namespace graphmine::detail
