#pragma once

#include <cstddef>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/status.hpp"

namespace graphmine::detail {

struct QuasiCliqueBackendResult {
  Status status;
  std::vector<std::vector<VertexIndex>> quasi_cliques;
  double elapsed_ms = 0.0;
};

[[nodiscard]] bool cuqc_backend_compiled() noexcept;
[[nodiscard]] QuasiCliqueBackendResult run_cuqc(
    const CsrGraph& graph, double minimum_degree_ratio,
    std::size_t minimum_size, bool static_scheduling, int device_id);

}  // namespace graphmine::detail
