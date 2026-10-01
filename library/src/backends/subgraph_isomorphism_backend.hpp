#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/status.hpp"

namespace graphmine::detail {

struct SubgraphIsomorphismBackendResult {
  Status status;
  std::uint64_t count = 0;
  double elapsed_ms = 0.0;
};

[[nodiscard]] bool gmatch_backend_compiled() noexcept;
[[nodiscard]] SubgraphIsomorphismBackendResult run_gmatch(
    const CsrGraph& data_graph, const std::vector<int>& data_labels,
    const CsrGraph& query_graph, const std::vector<int>& query_labels,
    std::size_t initial_match_capacity, int device_id);

}  // namespace graphmine::detail
