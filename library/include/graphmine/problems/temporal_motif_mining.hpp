#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class TemporalMotifBackend {
  automatic,
  everest,
  mayura,
};

// The two validated generated kernels implement this exact ordered motif.
enum class TemporalMotifPattern {
  feed_forward_triangle,
};

enum class TemporalMotifOptionalOutput : std::uint32_t {
  none = 0,
  instances = 1U << 0U,
};

/// Combines two optional-output flags.
constexpr TemporalMotifOptionalOutput operator|(
    TemporalMotifOptionalOutput lhs, TemporalMotifOptionalOutput rhs) {
  return static_cast<TemporalMotifOptionalOutput>(
      static_cast<std::uint32_t>(lhs) | static_cast<std::uint32_t>(rhs));
}

/// Tests whether an optional-output flag is present.
constexpr bool has_output(TemporalMotifOptionalOutput outputs,
                          TemporalMotifOptionalOutput output) {
  return (static_cast<std::uint32_t>(outputs) &
          static_cast<std::uint32_t>(output)) != 0U;
}

struct TemporalMotifOptions {
  TemporalMotifBackend backend = TemporalMotifBackend::automatic;
  TemporalMotifPattern pattern =
      TemporalMotifPattern::feed_forward_triangle;
  // Inclusive window: last_timestamp <= first_timestamp + max_time_span.
  std::int64_t max_time_span = 0;
  TemporalMotifOptionalOutput optional_outputs =
      TemporalMotifOptionalOutput::none;
  std::optional<std::uint64_t> result_limit;
  ExecutionOptions execution;
};

struct TemporalMotifInstance {
  // Roles A, B, C in A->B, B->C, A->C.
  std::array<ExternalId, 3> vertices_by_role;
  // Original canonical edge IDs in motif-time order.
  std::array<ExternalId, 3> edges_in_temporal_order;
};

struct TemporalMotifOutput {
  std::uint64_t count = 0;
  std::optional<std::vector<TemporalMotifInstance>> instances;
  bool instances_complete = true;
};

/// Mines the validated ordered feed-forward temporal motif on event graphs.
class TemporalMotifMining {
 public:
  /// Stores backend, window, output, limit, and execution options.
  explicit TemporalMotifMining(TemporalMotifOptions options = {});

  /// Checks timestamps, directed events, and backend support without mining.
  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  /// Counts temporal motifs and optionally restores matching vertices/edges.
  [[nodiscard]] ExecutionResult<TemporalMotifOutput> run(
      const Graph& graph) const;
  /// Returns the immutable options captured at construction.
  [[nodiscard]] const TemporalMotifOptions& options() const noexcept {
    return options_;
  }

  /// Lists registered temporal-motif backends and their availability.
  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  TemporalMotifOptions options_;
};

/// Returns the stable manifest/CLI identifier for a backend value.
[[nodiscard]] const char* to_string(TemporalMotifBackend backend) noexcept;
/// Returns the stable JSON/CLI spelling for a temporal motif pattern.
[[nodiscard]] const char* to_string(TemporalMotifPattern pattern) noexcept;

}  // namespace graphmine
