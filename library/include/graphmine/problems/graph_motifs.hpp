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

/// Combines two optional-output flags.
constexpr GraphMotifOptionalOutput operator|(GraphMotifOptionalOutput lhs,
                                              GraphMotifOptionalOutput rhs) {
  return static_cast<GraphMotifOptionalOutput>(
      static_cast<std::uint32_t>(lhs) | static_cast<std::uint32_t>(rhs));
}

/// Tests whether an optional-output flag is present.
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

/// Counts caller-supplied motif graphs through a validated mining backend.
class GraphMotifs {
 public:
  /// Stores backend, occurrence identity, output, and execution options.
  explicit GraphMotifs(GraphMotifOptions options = {});

  /// Checks the data graph, motif queries, and backend without mining.
  [[nodiscard]] SupportReport supports(
      const Graph& data_graph, const std::vector<Graph>& motifs) const;
  /// Counts each motif and materializes requested instances or participation.
  [[nodiscard]] ExecutionResult<GraphMotifOutput> run(
      const Graph& data_graph, const std::vector<Graph>& motifs) const;
  /// Returns the immutable options captured at construction.
  [[nodiscard]] const GraphMotifOptions& options() const noexcept {
    return options_;
  }

  /// Lists registered graph-motif backends and their availability.
  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  GraphMotifOptions options_;
};

/// Returns the stable manifest/CLI identifier for a backend value.
[[nodiscard]] const char* to_string(GraphMotifBackend backend) noexcept;
/// Returns the stable JSON/CLI spelling for occurrence identity.
[[nodiscard]] const char* to_string(
    MotifOccurrenceIdentity identity) noexcept;

}  // namespace graphmine
