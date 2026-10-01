#pragma once

#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class TriangleBackend {
  automatic,
  tot,
  wetric,
};

struct TriangleOptions {
  TriangleBackend backend = TriangleBackend::automatic;
  bool list_instances = false;
  bool include_per_vertex_counts = false;
  bool include_per_edge_counts = false;
  std::optional<std::uint64_t> result_limit;
  bool allow_directed_projection = false;
  std::uint32_t wetric_spread = 5;
  std::uint32_t wetric_adjacency_matrix_length = 64;
  ExecutionOptions execution;
};

struct VertexTriangleCount {
  ExternalId vertex;
  std::uint64_t count = 0;
};

struct EdgeTriangleCount {
  ExternalId edge;
  std::uint64_t count = 0;
};

struct TriangleOutput {
  std::uint64_t global_triangle_count = 0;
  bool instances_complete = true;
  std::optional<std::vector<std::vector<ExternalId>>> triangles;
  std::optional<std::vector<VertexTriangleCount>> per_vertex_count;
  std::optional<std::vector<EdgeTriangleCount>> per_edge_count;
};

class TriangleCounting {
 public:
  explicit TriangleCounting(TriangleOptions options = {});

  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  [[nodiscard]] ExecutionResult<TriangleOutput> run(const Graph& graph) const;
  [[nodiscard]] const TriangleOptions& options() const noexcept {
    return options_;
  }

  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  TriangleOptions options_;
};

[[nodiscard]] const char* to_string(TriangleBackend backend) noexcept;

}  // namespace graphmine
