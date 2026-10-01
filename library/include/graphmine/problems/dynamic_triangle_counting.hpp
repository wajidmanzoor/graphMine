#pragma once

#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class DynamicTriangleBackend {
  automatic,
  edtc,
};

enum class TriangleUpdateKind {
  insert_edge,
  delete_edge,
};

struct TriangleUpdate {
  TriangleUpdateKind kind = TriangleUpdateKind::insert_edge;
  ExternalId source;
  ExternalId target;
};

struct DynamicTriangleOptions {
  DynamicTriangleBackend backend = DynamicTriangleBackend::automatic;

  // Optional output controls. result_limit applies independently to the
  // deleted- and inserted-triangle lists.
  bool list_changed_instances = false;
  bool include_global_counts = false;
  std::optional<std::uint64_t> result_limit;

  bool allow_directed_projection = false;
  ExecutionOptions execution;
};

struct DynamicTriangleOutput {
  std::uint64_t deleted_triangle_count = 0;
  std::uint64_t inserted_triangle_count = 0;
  std::int64_t net_triangle_change = 0;

  std::optional<std::uint64_t> initial_global_triangle_count;
  std::optional<std::uint64_t> final_global_triangle_count;

  bool changed_instances_complete = true;
  std::optional<std::vector<std::vector<ExternalId>>> deleted_triangles;
  std::optional<std::vector<std::vector<ExternalId>>> inserted_triangles;
};

// EDTC applies every deletion in the supplied vector before every insertion,
// matching the validated artifact's single-batch semantics.
class DynamicTriangleCounting {
 public:
  /// Stores output, limit, normalization, backend, and execution options.
  explicit DynamicTriangleCounting(DynamicTriangleOptions options = {});

  /// Checks the graph and update batch against EDTC's validated contract.
  [[nodiscard]] SupportReport supports(
      const Graph& graph, const std::vector<TriangleUpdate>& updates) const;
  /// Applies deletions then insertions and reports the triangle-count delta.
  [[nodiscard]] ExecutionResult<DynamicTriangleOutput> run(
      const Graph& graph, const std::vector<TriangleUpdate>& updates) const;
  /// Returns the immutable options captured at construction.
  [[nodiscard]] const DynamicTriangleOptions& options() const noexcept {
    return options_;
  }

  /// Lists registered dynamic triangle backends and their availability.
  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  DynamicTriangleOptions options_;
};

/// Returns the stable manifest/CLI identifier for a backend value.
[[nodiscard]] const char* to_string(DynamicTriangleBackend backend) noexcept;
/// Returns the stable JSON/CLI spelling for an update kind.
[[nodiscard]] const char* to_string(TriangleUpdateKind kind) noexcept;

}  // namespace graphmine
