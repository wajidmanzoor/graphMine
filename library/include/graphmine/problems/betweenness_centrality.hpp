#pragma once

#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class BetweennessCentralityBackend {
  automatic,
  turbo_bc,
};

enum class BetweennessCentralityOptionalOutput : std::uint32_t {
  none = 0,
  normalized_scores = 1U << 0U,
  ranking = 1U << 1U,
  maximum = 1U << 2U,
};

constexpr BetweennessCentralityOptionalOutput operator|(
    BetweennessCentralityOptionalOutput lhs,
    BetweennessCentralityOptionalOutput rhs) {
  return static_cast<BetweennessCentralityOptionalOutput>(
      static_cast<std::uint32_t>(lhs) | static_cast<std::uint32_t>(rhs));
}

constexpr bool has_output(BetweennessCentralityOptionalOutput outputs,
                          BetweennessCentralityOptionalOutput output) {
  return (static_cast<std::uint32_t>(outputs) &
          static_cast<std::uint32_t>(output)) != 0U;
}

struct BetweennessCentralityOptions {
  BetweennessCentralityBackend backend =
      BetweennessCentralityBackend::automatic;
  BetweennessCentralityOptionalOutput optional_outputs =
      BetweennessCentralityOptionalOutput::none;
  bool allow_directed_projection = false;
  ExecutionOptions execution;
};

struct VertexCentralityScore {
  ExternalId vertex;
  double score = 0.0;
};

struct BetweennessCentralityOutput {
  // TurboBC's validated native quantity: ordered-pair, endpoint-excluding,
  // unweighted betweenness without normalization.
  std::vector<VertexCentralityScore> score_by_vertex;
  std::optional<std::vector<VertexCentralityScore>> normalized_score_by_vertex;
  std::optional<std::vector<VertexCentralityScore>> ranking;
  std::optional<VertexCentralityScore> maximum;
};

class BetweennessCentrality {
 public:
  explicit BetweennessCentrality(BetweennessCentralityOptions options = {});

  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  [[nodiscard]] ExecutionResult<BetweennessCentralityOutput> run(
      const Graph& graph) const;
  [[nodiscard]] const BetweennessCentralityOptions& options() const noexcept {
    return options_;
  }

  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  BetweennessCentralityOptions options_;
};

[[nodiscard]] const char* to_string(
    BetweennessCentralityBackend backend) noexcept;

}  // namespace graphmine
