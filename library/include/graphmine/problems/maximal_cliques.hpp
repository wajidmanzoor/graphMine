#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class MaximalCliqueBackend {
  automatic,
  mce_gpu,
  g2_aimd,
  rdmce,
};

enum class MaximalCliqueOptionalOutput : std::uint32_t {
  none = 0,
  total_count = 1U << 0U,
};

/// Combines two optional-output flags.
constexpr MaximalCliqueOptionalOutput operator|(
    MaximalCliqueOptionalOutput lhs, MaximalCliqueOptionalOutput rhs) {
  return static_cast<MaximalCliqueOptionalOutput>(
      static_cast<std::uint32_t>(lhs) | static_cast<std::uint32_t>(rhs));
}

/// Tests whether an optional-output flag is present.
constexpr bool has_output(MaximalCliqueOptionalOutput outputs,
                          MaximalCliqueOptionalOutput output) {
  return (static_cast<std::uint32_t>(outputs) &
          static_cast<std::uint32_t>(output)) != 0U;
}

struct MaximalCliqueOptions {
  MaximalCliqueBackend backend = MaximalCliqueBackend::automatic;
  std::size_t minimum_clique_size = 1;
  std::optional<std::uint64_t> result_limit;
  MaximalCliqueOptionalOutput optional_outputs =
      MaximalCliqueOptionalOutput::none;
  bool allow_directed_projection = false;
  ExecutionOptions execution;
};

struct MaximalCliqueOutput {
  std::vector<std::vector<ExternalId>> cliques;
  std::uint64_t returned_count = 0;
  bool complete = false;
  std::optional<std::uint64_t> total_count;
};

/// Enumerates inclusion-maximal cliques through a selected validated backend.
class MaximalCliques {
 public:
  /// Stores the backend, filtering, materialization, and execution options.
  explicit MaximalCliques(MaximalCliqueOptions options = {});

  /// Checks the graph and selected backend without running enumeration.
  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  /// Executes enumeration and returns cliques with optional total count.
  [[nodiscard]] ExecutionResult<MaximalCliqueOutput> run(
      const Graph& graph) const;
  /// Returns the immutable options captured at construction.
  [[nodiscard]] const MaximalCliqueOptions& options() const noexcept {
    return options_;
  }

  /// Lists all registered maximal-clique backends and their availability.
  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  MaximalCliqueOptions options_;
};

/// Returns the stable manifest/CLI identifier for a backend value.
[[nodiscard]] const char* to_string(MaximalCliqueBackend backend) noexcept;

}  // namespace graphmine
