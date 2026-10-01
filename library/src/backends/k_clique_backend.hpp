#pragma once

#include <cstdint>

#include "graphmine/graph.hpp"
#include "graphmine/status.hpp"

namespace graphmine::detail {

struct KCliqueBackendResult {
  Status status;
  std::uint64_t count = 0;
  double elapsed_ms = 0.0;
};

[[nodiscard]] bool kcgpu_backend_compiled() noexcept;
[[nodiscard]] KCliqueBackendResult run_kcgpu(const CsrGraph& graph,
                                             std::uint32_t k,
                                             int device_id);
[[nodiscard]] bool graphset_kclique_backend_compiled() noexcept;
[[nodiscard]] KCliqueBackendResult run_graphset_kclique(
    const CsrGraph& graph, std::uint32_t k, int device_id);
[[nodiscard]] bool gamma_kclique_backend_compiled() noexcept;
[[nodiscard]] KCliqueBackendResult run_gamma_kclique(
    const CsrGraph& graph, std::uint32_t k, int device_id);

}  // namespace graphmine::detail
