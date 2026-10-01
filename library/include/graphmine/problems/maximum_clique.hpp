#pragma once

#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class MaximumCliqueBackend {
  automatic,
  cuda_ms,
  gpu_maximum_clique,
  maximum_clique_on_gpu,
};

enum class MaximumCliqueOptionalOutput : std::uint32_t {
  none = 0,
  upper_bound = 1U << 0U,
};

/// Combines two optional-output flags.
constexpr MaximumCliqueOptionalOutput operator|(
    MaximumCliqueOptionalOutput lhs, MaximumCliqueOptionalOutput rhs) {
  return static_cast<MaximumCliqueOptionalOutput>(
      static_cast<std::uint32_t>(lhs) | static_cast<std::uint32_t>(rhs));
}

/// Tests whether an optional-output flag is present.
constexpr bool has_output(MaximumCliqueOptionalOutput outputs,
                          MaximumCliqueOptionalOutput output) {
  return (static_cast<std::uint32_t>(outputs) &
          static_cast<std::uint32_t>(output)) != 0U;
}

struct MaximumCliqueOptions {
  MaximumCliqueBackend backend = MaximumCliqueBackend::automatic;
  bool return_all_ties = false;
  std::optional<std::uint32_t> known_lower_bound;
  MaximumCliqueOptionalOutput optional_outputs =
      MaximumCliqueOptionalOutput::none;
  bool allow_directed_projection = false;
  ExecutionOptions execution;
};

struct MaximumCliqueOutput {
  std::uint32_t maximum_size = 0;
  std::vector<std::vector<ExternalId>> cliques;
  bool optimal = false;
  std::optional<std::uint32_t> upper_bound;
};

/// Finds a maximum-cardinality clique through a selected validated backend.
class MaximumClique {
 public:
  /// Stores backend, tie-handling, bound, output, and execution options.
  explicit MaximumClique(MaximumCliqueOptions options = {});

  /// Checks the graph and selected backend without solving the instance.
  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  /// Executes the maximum-clique search and returns an optimality-bearing result.
  [[nodiscard]] ExecutionResult<MaximumCliqueOutput> run(
      const Graph& graph) const;
  /// Returns the immutable options captured at construction.
  [[nodiscard]] const MaximumCliqueOptions& options() const noexcept {
    return options_;
  }

  /// Lists all registered maximum-clique backends and their availability.
  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  MaximumCliqueOptions options_;
};

/// Returns the stable manifest/CLI identifier for a backend value.
[[nodiscard]] const char* to_string(MaximumCliqueBackend backend) noexcept;

}  // namespace graphmine
