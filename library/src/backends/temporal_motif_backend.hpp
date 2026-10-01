#pragma once

#include <cstdint>
#include <vector>

#include "graphmine/status.hpp"

namespace graphmine::detail {

// The generated Everest and Mayura kernels use signed 32-bit vertex, event,
// and timestamp values.  The public facade validates and normalizes the
// canonical Graph before constructing this lossless backend representation.
struct TemporalMotifBackendEvent {
  int source = 0;
  int target = 0;
  int timestamp = 0;
};

struct TemporalMotifBackendInput {
  int vertex_count = 0;
  int max_time_span = 0;
  std::vector<TemporalMotifBackendEvent> events;
};

struct TemporalMotifBackendResult {
  Status status;
  std::uint64_t count = 0;
  double elapsed_ms = 0.0;
};

[[nodiscard]] bool everest_backend_compiled() noexcept;
[[nodiscard]] TemporalMotifBackendResult run_everest(
    const TemporalMotifBackendInput& input, int device_id);

[[nodiscard]] bool mayura_backend_compiled() noexcept;
[[nodiscard]] TemporalMotifBackendResult run_mayura(
    const TemporalMotifBackendInput& input, int device_id);

}  // namespace graphmine::detail
