#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class GraphMotifBackend {
  automatic,
  graphminer,
  graphset,
  dumato,
};

enum class MotifOccurrenceIdentity {
  unique_vertex_set_and_mapping_class,
  all_embeddings,
};

enum class GraphMotifOptionalOutput : std::uint32_t {
  none = 0,
  instances = 1U << 0U,
  per_vertex_participation = 1U << 1U,
};

constexpr GraphMotifOptionalOutput operator|(GraphMotifOptionalOutput lhs,
                                              GraphMotifOptionalOutput rhs) {
  return static_cast<GraphMotifOptionalOutput>(
      static_cast<std::uint32_t>(lhs) | static_cast<std::uint32_t>(rhs));
}

constexpr bool has_output(GraphMotifOptionalOutput outputs,
                          GraphMotifOptionalOutput output) {
  return (static_cast<std::uint32_t>(outputs) &
          static_cast<std::uint32_t>(output)) != 0U;
}

struct GraphMotifOptions {
  GraphMotifBackend backend = GraphMotifBackend::automatic;
  bool induced = false;
  MotifOccurrenceIdentity occurrence_identity =
      MotifOccurrenceIdentity::unique_vertex_set_and_mapping_class;
  GraphMotifOptionalOutput optional_outputs = GraphMotifOptionalOutput::none;
  std::optional<std::uint64_t> result_limit_per_motif;
  bool allow_directed_projection = false;
  ExecutionOptions execution;
};

struct MotifVertexMapping {
  ExternalId motif_vertex;
  ExternalId data_vertex;
};

using MotifInstance = std::vector<MotifVertexMapping>;

struct MotifVertexParticipation {
  ExternalId vertex;
  std::uint64_t count = 0;
};

struct GraphMotifResult {
  std::string motif_id;
  std::uint64_t count = 0;
  bool instances_complete = true;
  std::optional<std::vector<MotifInstance>> instances;
  std::optional<std::vector<MotifVertexParticipation>>
      per_vertex_participation;
};

struct GraphMotifOutput {
  std::vector<GraphMotifResult> motifs;
};

class GraphMotifs {
 public:
  explicit GraphMotifs(GraphMotifOptions options = {});

  [[nodiscard]] SupportReport supports(
      const Graph& data_graph, const std::vector<Graph>& motifs) const;
  [[nodiscard]] ExecutionResult<GraphMotifOutput> run(
      const Graph& data_graph, const std::vector<Graph>& motifs) const;
  [[nodiscard]] const GraphMotifOptions& options() const noexcept {
    return options_;
  }

  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  GraphMotifOptions options_;
};

[[nodiscard]] const char* to_string(GraphMotifBackend backend) noexcept;
[[nodiscard]] const char* to_string(
    MotifOccurrenceIdentity identity) noexcept;

}  // namespace graphmine
