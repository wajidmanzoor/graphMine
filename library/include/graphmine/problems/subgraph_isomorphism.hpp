#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class SubgraphIsomorphismBackend {
  automatic,
  gmatch,
};

enum class SubgraphIsomorphismOptionalOutput : std::uint32_t {
  none = 0,
  embeddings = 1U << 0U,
};

constexpr SubgraphIsomorphismOptionalOutput operator|(
    SubgraphIsomorphismOptionalOutput lhs,
    SubgraphIsomorphismOptionalOutput rhs) {
  return static_cast<SubgraphIsomorphismOptionalOutput>(
      static_cast<std::uint32_t>(lhs) | static_cast<std::uint32_t>(rhs));
}

constexpr bool has_output(SubgraphIsomorphismOptionalOutput outputs,
                          SubgraphIsomorphismOptionalOutput output) {
  return (static_cast<std::uint32_t>(outputs) &
          static_cast<std::uint32_t>(output)) != 0U;
}

struct SubgraphIsomorphismOptions {
  SubgraphIsomorphismBackend backend =
      SubgraphIsomorphismBackend::automatic;
  bool respect_vertex_labels = true;
  std::size_t initial_match_capacity = 1'000'000;
  SubgraphIsomorphismOptionalOutput optional_outputs =
      SubgraphIsomorphismOptionalOutput::none;
  std::optional<std::uint64_t> result_limit;
  bool allow_directed_projection = false;
  ExecutionOptions execution;
};

struct VertexMapping {
  ExternalId query_vertex;
  ExternalId data_vertex;
};

using SubgraphEmbedding = std::vector<VertexMapping>;

struct SubgraphIsomorphismOutput {
  std::uint64_t count = 0;
  std::optional<std::vector<SubgraphEmbedding>> embeddings;
  bool embeddings_complete = false;
};

class SubgraphIsomorphism {
 public:
  explicit SubgraphIsomorphism(SubgraphIsomorphismOptions options = {});

  [[nodiscard]] SupportReport supports(const Graph& data_graph,
                                       const Graph& query_graph) const;
  [[nodiscard]] ExecutionResult<SubgraphIsomorphismOutput> run(
      const Graph& data_graph, const Graph& query_graph) const;
  [[nodiscard]] const SubgraphIsomorphismOptions& options() const noexcept {
    return options_;
  }

  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  SubgraphIsomorphismOptions options_;
};

[[nodiscard]] const char* to_string(
    SubgraphIsomorphismBackend backend) noexcept;

}  // namespace graphmine
