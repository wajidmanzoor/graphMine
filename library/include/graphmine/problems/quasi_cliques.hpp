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

constexpr QuasiCliqueOptionalOutput operator|(QuasiCliqueOptionalOutput lhs,
                                               QuasiCliqueOptionalOutput rhs) {
  return static_cast<QuasiCliqueOptionalOutput>(
      static_cast<std::uint32_t>(lhs) | static_cast<std::uint32_t>(rhs));
}

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

class QuasiCliques {
 public:
  explicit QuasiCliques(QuasiCliqueOptions options = {});

  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  [[nodiscard]] ExecutionResult<QuasiCliqueOutput> run(
      const Graph& graph) const;
  [[nodiscard]] const QuasiCliqueOptions& options() const noexcept {
    return options_;
  }

  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  QuasiCliqueOptions options_;
};

[[nodiscard]] const char* to_string(QuasiCliqueBackend backend) noexcept;

}  // namespace graphmine
