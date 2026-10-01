#pragma once

#include <cstdint>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/status.hpp"

namespace graphmine::detail {

struct DenseTriangleUpdate {
  bool insertion = false;
  VertexIndex source = 0;
  VertexIndex target = 0;
};

struct DynamicTriangleBackendResult {
  Status status;
  std::uint64_t deleted_count = 0;
  std::uint64_t inserted_count = 0;
  double elapsed_ms = 0.0;
};

[[nodiscard]] bool edtc_backend_compiled() noexcept;
[[nodiscard]] DynamicTriangleBackendResult run_edtc(
    const CsrGraph& graph, const std::vector<DenseTriangleUpdate>& updates,
    int device_id);

}  // namespace graphmine::detail
