#pragma once

#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class CommunityDetectionBackend {
  automatic,
  gleiden,
  parallel_louvain,
  parallel_leiden,
  parallel_leiden_plus,
};

enum class CommunityDetectionOptionalOutput : std::uint32_t {
  none = 0,
  communities = 1U << 0U,
  edge_cut = 1U << 1U,
};

/// Combines two optional-output flags.
constexpr CommunityDetectionOptionalOutput operator|(
    CommunityDetectionOptionalOutput lhs,
    CommunityDetectionOptionalOutput rhs) {
  return static_cast<CommunityDetectionOptionalOutput>(
      static_cast<std::uint32_t>(lhs) | static_cast<std::uint32_t>(rhs));
}

/// Tests whether an optional-output flag is present.
constexpr bool has_output(CommunityDetectionOptionalOutput outputs,
                          CommunityDetectionOptionalOutput output) {
  return (static_cast<std::uint32_t>(outputs) &
          static_cast<std::uint32_t>(output)) != 0U;
}

struct CommunityDetectionOptions {
  CommunityDetectionBackend backend = CommunityDetectionBackend::automatic;
  CommunityDetectionOptionalOutput optional_outputs =
      CommunityDetectionOptionalOutput::none;
  bool allow_directed_projection = false;
  ExecutionOptions execution;
};

struct VertexCommunityAssignment {
  ExternalId vertex;
  std::uint32_t community = 0;
};

struct Community {
  std::uint32_t id = 0;
  std::vector<ExternalId> vertices;
};

struct CommunityDetectionOutput {
  std::vector<VertexCommunityAssignment> assignment_by_vertex;
  std::uint32_t community_count = 0;
  double modularity = 0.0;
  std::optional<std::vector<Community>> communities;
  std::optional<std::uint64_t> edge_cut;
};

/// Partitions vertices into disjoint communities with a validated backend.
class CommunityDetection {
 public:
  /// Stores backend, output, projection, and execution options.
  explicit CommunityDetection(CommunityDetectionOptions options = {});

  /// Checks the graph and selected backend without clustering it.
  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  /// Runs clustering and returns assignments, modularity, and requested detail.
  [[nodiscard]] ExecutionResult<CommunityDetectionOutput> run(
      const Graph& graph) const;
  /// Returns the immutable options captured at construction.
  [[nodiscard]] const CommunityDetectionOptions& options() const noexcept {
    return options_;
  }

  /// Lists registered community-detection backends and their availability.
  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  CommunityDetectionOptions options_;
};

/// Returns the stable manifest/CLI identifier for a backend value.
[[nodiscard]] const char* to_string(
    CommunityDetectionBackend backend) noexcept;

}  // namespace graphmine
