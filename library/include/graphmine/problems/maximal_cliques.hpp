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

constexpr MaximalCliqueOptionalOutput operator|(
    MaximalCliqueOptionalOutput lhs, MaximalCliqueOptionalOutput rhs) {
  return static_cast<MaximalCliqueOptionalOutput>(
      static_cast<std::uint32_t>(lhs) | static_cast<std::uint32_t>(rhs));
}

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

class MaximalCliques {
 public:
  explicit MaximalCliques(MaximalCliqueOptions options = {});

  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  [[nodiscard]] ExecutionResult<MaximalCliqueOutput> run(
      const Graph& graph) const;
  [[nodiscard]] const MaximalCliqueOptions& options() const noexcept {
    return options_;
  }

  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  MaximalCliqueOptions options_;
};

[[nodiscard]] const char* to_string(MaximalCliqueBackend backend) noexcept;

}  // namespace graphmine
