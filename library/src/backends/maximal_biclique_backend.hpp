#pragma once

#include <cstdint>
#include <vector>

#include "graphmine/status.hpp"

namespace graphmine::detail {

struct BipartiteCsrGraph {
  std::uint32_t left_vertex_count = 0;
  std::uint32_t right_vertex_count = 0;
  std::vector<std::uint64_t> left_offsets;
  std::vector<std::uint32_t> right_neighbors;
};

struct MaximalBicliqueBackendResult {
  Status status;
  std::uint64_t count = 0;
  double elapsed_ms = 0.0;
};

[[nodiscard]] bool cumbe_backend_compiled() noexcept;
[[nodiscard]] MaximalBicliqueBackendResult run_cumbe(
    const BipartiteCsrGraph& graph, int device_id);

}  // namespace graphmine::detail
