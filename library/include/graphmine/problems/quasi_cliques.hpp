#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class QuasiCliqueBackend {
  automatic,
  cuqc,
};

enum class CuQCScheduling {
  dynamic,
  static_schedule,
};

enum class QuasiCliqueOptionalOutput : std::uint32_t {
  none = 0,
  total_count = 1U << 0U,
};

/// Combines two optional-output flags.
constexpr QuasiCliqueOptionalOutput operator|(QuasiCliqueOptionalOutput lhs,
                                               QuasiCliqueOptionalOutput rhs) {
  return static_cast<QuasiCliqueOptionalOutput>(
      static_cast<std::uint32_t>(lhs) | static_cast<std::uint32_t>(rhs));
}

/// Tests whether an optional-output flag is present.
constexpr bool has_output(QuasiCliqueOptionalOutput outputs,
                          QuasiCliqueOptionalOutput output) {
  return (static_cast<std::uint32_t>(outputs) &
          static_cast<std::uint32_t>(output)) != 0U;
}

struct QuasiCliqueOptions {
  double minimum_degree_ratio = 0.8;
  std::size_t minimum_size = 4;
  QuasiCliqueBackend backend = QuasiCliqueBackend::automatic;
  CuQCScheduling scheduling = CuQCScheduling::dynamic;
  std::optional<std::uint64_t> result_limit;
  QuasiCliqueOptionalOutput optional_outputs =
      QuasiCliqueOptionalOutput::none;
  bool allow_directed_projection = false;
  ExecutionOptions execution;
};

struct QuasiCliqueOutput {
  std::vector<std::vector<ExternalId>> quasi_cliques;
  std::uint64_t returned_count = 0;
  bool complete = false;
  std::optional<std::uint64_t> total_count;
};

/// Mines maximal quasi-cliques through the validated cuQC path.
class QuasiCliques {
 public:
  /// Stores density, size, scheduling, output, and execution options.
  explicit QuasiCliques(QuasiCliqueOptions options = {});

  /// Checks thresholds, graph shape, and backend support without mining.
  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  /// Executes quasi-clique mining and returns requested result materialization.
  [[nodiscard]] ExecutionResult<QuasiCliqueOutput> run(
      const Graph& graph) const;
  /// Returns the immutable options captured at construction.
  [[nodiscard]] const QuasiCliqueOptions& options() const noexcept {
    return options_;
  }

  /// Lists registered quasi-clique backends and their availability.
  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  QuasiCliqueOptions options_;
};

/// Returns the stable manifest/CLI identifier for a backend value.
[[nodiscard]] const char* to_string(QuasiCliqueBackend backend) noexcept;

}  // namespace graphmine
