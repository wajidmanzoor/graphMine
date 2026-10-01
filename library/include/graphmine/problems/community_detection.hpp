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

constexpr CommunityDetectionOptionalOutput operator|(
    CommunityDetectionOptionalOutput lhs,
    CommunityDetectionOptionalOutput rhs) {
  return static_cast<CommunityDetectionOptionalOutput>(
      static_cast<std::uint32_t>(lhs) | static_cast<std::uint32_t>(rhs));
}

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

class CommunityDetection {
 public:
  explicit CommunityDetection(CommunityDetectionOptions options = {});

  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  [[nodiscard]] ExecutionResult<CommunityDetectionOutput> run(
      const Graph& graph) const;
  [[nodiscard]] const CommunityDetectionOptions& options() const noexcept {
    return options_;
  }

  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  CommunityDetectionOptions options_;
};

[[nodiscard]] const char* to_string(
    CommunityDetectionBackend backend) noexcept;

}  // namespace graphmine
