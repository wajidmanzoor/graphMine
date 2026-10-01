#pragma once

#include <vector>

#include "graphmine/graph.hpp"
#include "graphmine/status.hpp"

namespace graphmine::detail {

struct BetweennessCentralityBackendResult {
  Status status;
  std::vector<double> scores;
  double elapsed_ms = 0.0;
};

[[nodiscard]] bool turbobc_backend_compiled() noexcept;
[[nodiscard]] BetweennessCentralityBackendResult run_turbobc(
    const CsrGraph& graph, int device_id);

}  // namespace graphmine::detail
