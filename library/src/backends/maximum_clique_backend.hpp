#pragma once

#include <cstdint>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/status.hpp"

namespace graphmine::detail {

struct MaximumCliqueBackendResult {
  Status status;
  std::vector<VertexIndex> clique;
  std::uint32_t relaxation_upper_size = 0;
  double elapsed_ms = 0.0;
  std::vector<std::vector<VertexIndex>> tied_cliques;
};

[[nodiscard]] bool cuda_ms_backend_compiled() noexcept;
[[nodiscard]] MaximumCliqueBackendResult run_cuda_ms(
    const CsrGraph& graph, int device_id);

[[nodiscard]] bool gpu_maximum_clique_backend_compiled() noexcept;
[[nodiscard]] MaximumCliqueBackendResult run_gpu_maximum_clique(
    const CsrGraph& graph, int device_id,
    std::uint32_t known_lower_bound = 0,
    bool return_all_ties = false);

[[nodiscard]] bool maximum_clique_on_gpu_backend_compiled() noexcept;
[[nodiscard]] MaximumCliqueBackendResult run_maximum_clique_on_gpu(
    const CsrGraph& graph, int device_id,
    std::uint32_t known_lower_bound = 0);

}  // namespace graphmine::detail
