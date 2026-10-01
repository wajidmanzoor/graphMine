#pragma once

#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class KCliqueBackend {
  automatic,
  kcgpu,
  graphset,
  gamma,
};

struct KCliqueOptions {
  std::uint32_t k = 3;
  KCliqueBackend backend = KCliqueBackend::automatic;
  bool enumerate = false;
  bool include_per_vertex_counts = false;
  std::optional<std::uint64_t> result_limit;
  bool allow_directed_projection = false;
  ExecutionOptions execution;
};

struct VertexKCliqueCount {
  ExternalId vertex;
  std::uint64_t count = 0;
};

struct KCliqueOutput {
  std::uint64_t count = 0;
  bool complete = true;
  std::optional<std::vector<std::vector<ExternalId>>> cliques;
  std::optional<std::vector<VertexKCliqueCount>> per_vertex_count;
};

/// Counts or enumerates fixed-size cliques through a validated GPU backend.
class KCliques {
 public:
  /// Stores k, backend, optional materialization, and execution options.
  explicit KCliques(KCliqueOptions options = {});

  /// Checks k, the graph, and selected backend without running the algorithm.
  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  /// Counts k-cliques and materializes requested optional results.
  [[nodiscard]] ExecutionResult<KCliqueOutput> run(const Graph& graph) const;
  /// Returns the immutable options captured at construction.
  [[nodiscard]] const KCliqueOptions& options() const noexcept {
    return options_;
  }

  /// Lists all registered k-clique backends and their availability.
  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  KCliqueOptions options_;
};

/// Returns the stable manifest/CLI identifier for a backend value.
[[nodiscard]] const char* to_string(KCliqueBackend backend) noexcept;

}  // namespace graphmine
