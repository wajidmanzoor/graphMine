#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class MaximalBicliqueBackend {
  automatic,
  cumbe,
};

enum class MaximalBicliqueOptionalOutput : std::uint32_t {
  none = 0,
  total_count = 1U << 0U,
};

/// Combines two optional-output flags.
constexpr MaximalBicliqueOptionalOutput operator|(
    MaximalBicliqueOptionalOutput lhs, MaximalBicliqueOptionalOutput rhs) {
  return static_cast<MaximalBicliqueOptionalOutput>(
      static_cast<std::uint32_t>(lhs) | static_cast<std::uint32_t>(rhs));
}

/// Tests whether an optional-output flag is present.
constexpr bool has_output(MaximalBicliqueOptionalOutput outputs,
                          MaximalBicliqueOptionalOutput output) {
  return (static_cast<std::uint32_t>(outputs) &
          static_cast<std::uint32_t>(output)) != 0U;
}

struct MaximalBicliqueOptions {
  // Every graph vertex not listed here belongs to the right partition.
  std::vector<ExternalId> left_partition;
  MaximalBicliqueBackend backend = MaximalBicliqueBackend::automatic;
  std::size_t minimum_left_size = 1;
  std::size_t minimum_right_size = 1;
  std::optional<std::uint64_t> result_limit;
  MaximalBicliqueOptionalOutput optional_outputs =
      MaximalBicliqueOptionalOutput::none;
  bool allow_directed_projection = false;
  ExecutionOptions execution;
};

struct MaximalBiclique {
  std::vector<ExternalId> left;
  std::vector<ExternalId> right;
};

struct MaximalBicliqueOutput {
  std::vector<MaximalBiclique> bicliques;
  std::uint64_t returned_count = 0;
  bool complete = false;
  std::optional<std::uint64_t> total_count;
};

/// Enumerates maximal bicliques for a caller-supplied bipartition with cuMBE.
class MaximalBicliques {
 public:
  /// Stores the required left partition and all execution options.
  explicit MaximalBicliques(MaximalBicliqueOptions options);

  /// Checks the bipartition, graph, thresholds, and backend without execution.
  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  /// Executes maximal-biclique enumeration and optional total counting.
  [[nodiscard]] ExecutionResult<MaximalBicliqueOutput> run(
      const Graph& graph) const;
  /// Returns the immutable options captured at construction.
  [[nodiscard]] const MaximalBicliqueOptions& options() const noexcept {
    return options_;
  }

  /// Lists registered maximal-biclique backends and their availability.
  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  MaximalBicliqueOptions options_;
};

/// Returns the stable manifest/CLI identifier for a backend value.
[[nodiscard]] const char* to_string(MaximalBicliqueBackend backend) noexcept;

}  // namespace graphmine
