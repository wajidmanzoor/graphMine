#pragma once

#include <cstdint>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/status.hpp"

namespace graphmine::detail {

struct KCoreBackendResult {
  Status status;
  std::vector<std::uint32_t> core_numbers;
  double elapsed_ms = 0.0;
};

[[nodiscard]] bool kcore_gpu_backend_compiled() noexcept;
[[nodiscard]] KCoreBackendResult run_kcore_gpu(const CsrGraph& graph,
                                               int device_id);

}  // namespace graphmine::detail
