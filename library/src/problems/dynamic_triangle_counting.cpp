#include "graphmine/problems/dynamic_triangle_counting.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "backends/dynamic_triangle_backend.hpp"

namespace graphmine {
namespace {

using EdgeKey = std::uint64_t;
using Triangle = std::array<VertexIndex, 3>;

EdgeKey edge_key(VertexIndex source, VertexIndex target) {
  if (target < source) std::swap(source, target);
  return (static_cast<EdgeKey>(source) << 32U) |
         static_cast<EdgeKey>(target);
}

std::set<EdgeKey> edge_set(const CsrGraph& graph) {
  std::set<EdgeKey> edges;
  for (VertexIndex source = 0; source < graph.vertex_count(); ++source) {
    for (auto offset = graph.offsets[source];
         offset < graph.offsets[source + 1]; ++offset) {
      const auto target = graph.neighbors[offset];
      if (source < target) edges.insert(edge_key(source, target));
    }
  }
  return edges;
}

CsrGraph make_csr(std::size_t vertex_count, const std::set<EdgeKey>& edges) {
  CsrGraph graph;
  graph.offsets.assign(vertex_count + 1U, 0);
  for (const auto key : edges) {
    const auto source = static_cast<VertexIndex>(key >> 32U);
    const auto target = static_cast<VertexIndex>(key & 0xffffffffULL);
    ++graph.offsets[source + 1U];
    ++graph.offsets[target + 1U];
  }
  for (std::size_t vertex = 1; vertex < graph.offsets.size(); ++vertex) {
    graph.offsets[vertex] += graph.offsets[vertex - 1U];
  }
  graph.neighbors.resize(edges.size() * 2U);
  auto cursor = graph.offsets;
  for (const auto key : edges) {
    const auto source = static_cast<VertexIndex>(key >> 32U);
    const auto target = static_cast<VertexIndex>(key & 0xffffffffULL);
    graph.neighbors[cursor[source]++] = target;
    graph.neighbors[cursor[target]++] = source;
  }
  for (VertexIndex vertex = 0; vertex < vertex_count; ++vertex) {
    std::sort(graph.neighbors.begin() +
                  static_cast<std::ptrdiff_t>(graph.offsets[vertex]),
              graph.neighbors.begin() +
                  static_cast<std::ptrdiff_t>(graph.offsets[vertex + 1U]));
  }
  return graph;
}

template <typename Visitor>
std::uint64_t visit_triangles(const CsrGraph& graph, Visitor&& visitor) {
  std::uint64_t count = 0;
  for (VertexIndex u = 0; u < graph.vertex_count(); ++u) {
    const auto u_begin = graph.neighbors.begin() +
                         static_cast<std::ptrdiff_t>(graph.offsets[u]);
    const auto u_end = graph.neighbors.begin() +
                       static_cast<std::ptrdiff_t>(graph.offsets[u + 1U]);
    for (auto v_it = std::upper_bound(u_begin, u_end, u); v_it != u_end;
         ++v_it) {
      const auto v = *v_it;
      const auto v_begin = graph.neighbors.begin() +
                           static_cast<std::ptrdiff_t>(graph.offsets[v]);
      const auto v_end = graph.neighbors.begin() +
                         static_cast<std::ptrdiff_t>(graph.offsets[v + 1U]);
      auto left = std::upper_bound(v_it + 1, u_end, v);
      auto right = std::upper_bound(v_begin, v_end, v);
      while (left != u_end && right != v_end) {
        if (*left < *right) {
          ++left;
        } else if (*right < *left) {
          ++right;
        } else {
          ++count;
          visitor(Triangle{u, v, *left});
          ++left;
          ++right;
        }
      }
    }
  }
  return count;
}

std::uint64_t count_triangles(const CsrGraph& graph) {
  return visit_triangles(graph, [](const Triangle&) {});
}

bool triangle_exists(const std::set<EdgeKey>& edges,
                     const Triangle& triangle) {
  return edges.count(edge_key(triangle[0], triangle[1])) != 0U &&
         edges.count(edge_key(triangle[0], triangle[2])) != 0U &&
         edges.count(edge_key(triangle[1], triangle[2])) != 0U;
}

struct PreparedUpdateBatch {
  UndirectedGraphView initial;
  CsrGraph after_deletions;
  CsrGraph final;
  std::set<EdgeKey> initial_edges;
  std::set<EdgeKey> after_deletion_edges;
  std::set<EdgeKey> final_edges;
  std::vector<detail::DenseTriangleUpdate> updates;
  std::vector<std::string> warnings;
};

Status prepare_batch(const Graph& graph,
                     const std::vector<TriangleUpdate>& updates,
                     bool allow_directed_projection,
                     PreparedUpdateBatch& prepared) {
  try {
    prepared.initial =
        graph.simple_undirected({allow_directed_projection});
  } catch (const std::exception& error) {
    return {StatusCode::invalid_argument, error.what()};
  }

  if (prepared.initial.normalization.directed_projection_applied) {
    prepared.warnings.emplace_back(
        "directed input and updates were projected to an undirected graph");
  }
  if (prepared.initial.normalization.self_loops_removed > 0) {
    prepared.warnings.emplace_back(
        "self-loops were removed from the initial graph during normalization");
  }
  if (prepared.initial.normalization.parallel_edges_collapsed > 0) {
    prepared.warnings.emplace_back(
        "parallel edges were collapsed in the initial graph during "
        "normalization");
  }

  prepared.initial_edges = edge_set(prepared.initial.csr);
  prepared.after_deletion_edges = prepared.initial_edges;
  prepared.updates.reserve(updates.size());
  std::set<EdgeKey> deletions;
  std::set<EdgeKey> insertions;

  struct ResolvedUpdate {
    TriangleUpdateKind kind;
    VertexIndex source;
    VertexIndex target;
    EdgeKey key;
  };
  std::vector<ResolvedUpdate> resolved;
  resolved.reserve(updates.size());
  try {
    for (const auto& update : updates) {
      auto source = graph.dense_index(update.source);
      auto target = graph.dense_index(update.target);
      if (source == target) {
        return {StatusCode::invalid_argument,
                "dynamic triangle updates cannot contain self-loops"};
      }
      if (target < source) std::swap(source, target);
      const auto key = edge_key(source, target);
      auto& same_kind = update.kind == TriangleUpdateKind::delete_edge
                            ? deletions
                            : insertions;
      if (!same_kind.insert(key).second) {
        return {StatusCode::invalid_argument,
                "a dynamic triangle batch contains a duplicate " +
                    std::string(to_string(update.kind)) + " update"};
      }
      resolved.push_back({update.kind, source, target, key});
      prepared.updates.push_back(
          {update.kind == TriangleUpdateKind::insert_edge, source, target});
    }
  } catch (const std::exception& error) {
    return {StatusCode::invalid_argument,
            std::string("dynamic triangle update references an unknown "
                        "vertex: ") +
                error.what()};
  }

  for (const auto& update : resolved) {
    if (update.kind != TriangleUpdateKind::delete_edge) continue;
    if (prepared.initial_edges.count(update.key) == 0U) {
      return {StatusCode::invalid_argument,
              "a dynamic triangle deletion references a missing edge"};
    }
    prepared.after_deletion_edges.erase(update.key);
  }
  prepared.final_edges = prepared.after_deletion_edges;
  for (const auto& update : resolved) {
    if (update.kind != TriangleUpdateKind::insert_edge) continue;
    if (prepared.final_edges.count(update.key) != 0U) {
      return {StatusCode::invalid_argument,
              "a dynamic triangle insertion references an existing edge"};
    }
    prepared.final_edges.insert(update.key);
  }

  prepared.after_deletions =
      make_csr(graph.vertex_count(), prepared.after_deletion_edges);
  prepared.final = make_csr(graph.vertex_count(), prepared.final_edges);
  return Status::success();
}

Provenance edtc_provenance() {
  return {"triangle_counting_listing",
          "edtc",
          "EDTC artifact",
          "7da15bf9aded217c8bff9fdc4c7b52a6b1e25947",
          "original EDTC delete/add kernels over an in-memory update batch"};
}

}  // namespace

const char* to_string(DynamicTriangleBackend backend) noexcept {
  switch (backend) {
    case DynamicTriangleBackend::automatic:
      return "auto";
    case DynamicTriangleBackend::edtc:
      return "edtc";
  }
  return "unknown";
}

const char* to_string(TriangleUpdateKind kind) noexcept {
  switch (kind) {
    case TriangleUpdateKind::insert_edge:
      return "insert_edge";
    case TriangleUpdateKind::delete_edge:
      return "delete_edge";
  }
  return "unknown";
}

DynamicTriangleCounting::DynamicTriangleCounting(
    DynamicTriangleOptions options)
    : options_(std::move(options)) {}

SupportReport DynamicTriangleCounting::supports(
    const Graph& graph, const std::vector<TriangleUpdate>& updates) const {
  if (graph.directed() && !options_.allow_directed_projection) {
    return {false,
            "directed input requires allow_directed_projection=true"};
  }
  if (options_.execution.device_ids.empty()) {
    return {false, "at least one CUDA device id must be provided"};
  }
  if (options_.result_limit && *options_.result_limit == 0) {
    return {false, "result_limit must be null or at least one"};
  }
  if (options_.result_limit && !options_.list_changed_instances) {
    return {false,
            "result_limit is meaningful only when "
            "list_changed_instances=true"};
  }
  if (!detail::edtc_backend_compiled()) {
    return {false, "the EDTC backend is not compiled in this build"};
  }
  PreparedUpdateBatch prepared;
  const auto status = prepare_batch(
      graph, updates, options_.allow_directed_projection, prepared);
  if (!status.ok()) return {false, status.message()};
  return {true, {}};
}

ExecutionResult<DynamicTriangleOutput> DynamicTriangleCounting::run(
    const Graph& graph, const std::vector<TriangleUpdate>& updates) const {
  const auto started = std::chrono::steady_clock::now();
  auto provenance = edtc_provenance();
  if (options_.execution.device_ids.empty()) {
    return ExecutionResult<DynamicTriangleOutput>::failure(
        {StatusCode::invalid_argument,
         "at least one CUDA device id must be provided"},
        provenance);
  }
  if (options_.result_limit && *options_.result_limit == 0) {
    return ExecutionResult<DynamicTriangleOutput>::failure(
        {StatusCode::invalid_argument,
         "result_limit must be null or at least one"},
        provenance);
  }
  if (options_.result_limit && !options_.list_changed_instances) {
    return ExecutionResult<DynamicTriangleOutput>::failure(
        {StatusCode::invalid_argument,
         "result_limit is meaningful only when "
         "list_changed_instances=true"},
        provenance);
  }
  if (!detail::edtc_backend_compiled()) {
    return ExecutionResult<DynamicTriangleOutput>::failure(
        {StatusCode::backend_unavailable,
         "EDTC was not compiled into this GraphMine build"},
        provenance);
  }

  PreparedUpdateBatch prepared;
  const auto prepare_status = prepare_batch(
      graph, updates, options_.allow_directed_projection, prepared);
  if (!prepare_status.ok()) {
    return ExecutionResult<DynamicTriangleOutput>::failure(
        prepare_status, provenance, std::move(prepared.warnings));
  }

  const auto backend = detail::run_edtc(
      prepared.initial.csr, prepared.updates,
      options_.execution.device_ids.front());
  if (!backend.status.ok()) {
    return ExecutionResult<DynamicTriangleOutput>::failure(
        backend.status, provenance, std::move(prepared.warnings));
  }

  DynamicTriangleOutput output;
  output.deleted_triangle_count = backend.deleted_count;
  output.inserted_triangle_count = backend.inserted_count;
  if (backend.inserted_count >= backend.deleted_count) {
    const auto difference = backend.inserted_count - backend.deleted_count;
    if (difference > static_cast<std::uint64_t>(INT64_MAX)) {
      return ExecutionResult<DynamicTriangleOutput>::failure(
          {StatusCode::unsupported,
           "EDTC net triangle change exceeds signed 64-bit range"},
          provenance, std::move(prepared.warnings));
    }
    output.net_triangle_change = static_cast<std::int64_t>(difference);
  } else {
    const auto difference = backend.deleted_count - backend.inserted_count;
    if (difference > static_cast<std::uint64_t>(INT64_MAX)) {
      return ExecutionResult<DynamicTriangleOutput>::failure(
          {StatusCode::unsupported,
           "EDTC net triangle change exceeds signed 64-bit range"},
          provenance, std::move(prepared.warnings));
    }
    output.net_triangle_change = -static_cast<std::int64_t>(difference);
  }

  const auto materialization_started = std::chrono::steady_clock::now();
  if (options_.include_global_counts || options_.list_changed_instances) {
    const auto initial_count = count_triangles(prepared.initial.csr);
    const auto after_delete_count = count_triangles(prepared.after_deletions);
    const auto final_count = count_triangles(prepared.final);
    const auto expected_deleted = initial_count - after_delete_count;
    const auto expected_inserted = final_count - after_delete_count;
    if (expected_deleted != backend.deleted_count ||
        expected_inserted != backend.inserted_count) {
      return ExecutionResult<DynamicTriangleOutput>::failure(
          {StatusCode::correctness_mismatch,
           "EDTC change counts disagreed with the exact optional "
           "materializer"},
          provenance, std::move(prepared.warnings));
    }
    if (options_.include_global_counts) {
      output.initial_global_triangle_count = initial_count;
      output.final_global_triangle_count = final_count;
    }

    if (options_.list_changed_instances) {
      output.deleted_triangles.emplace();
      output.inserted_triangles.emplace();
      const auto limit = options_.result_limit.value_or(
          std::numeric_limits<std::uint64_t>::max());
      visit_triangles(prepared.initial.csr, [&](const Triangle& triangle) {
        if (!triangle_exists(prepared.after_deletion_edges, triangle) &&
            output.deleted_triangles->size() < limit) {
          output.deleted_triangles->push_back(
              {graph.external_id(triangle[0]), graph.external_id(triangle[1]),
               graph.external_id(triangle[2])});
        }
      });
      visit_triangles(prepared.final, [&](const Triangle& triangle) {
        if (!triangle_exists(prepared.after_deletion_edges, triangle) &&
            output.inserted_triangles->size() < limit) {
          output.inserted_triangles->push_back(
              {graph.external_id(triangle[0]), graph.external_id(triangle[1]),
               graph.external_id(triangle[2])});
        }
      });
      output.changed_instances_complete =
          output.deleted_triangles->size() == backend.deleted_count &&
          output.inserted_triangles->size() == backend.inserted_count;
    }
  }
  const auto materialization_finished = std::chrono::steady_clock::now();
  const auto finished = std::chrono::steady_clock::now();

  ExecutionStatistics statistics;
  statistics.backend_ms = backend.elapsed_ms;
  statistics.output_materialization_ms =
      std::chrono::duration<double, std::milli>(materialization_finished -
                                                materialization_started)
          .count();
  statistics.end_to_end_ms =
      std::chrono::duration<double, std::milli>(finished - started).count();
  return ExecutionResult<DynamicTriangleOutput>::success(
      std::move(output), std::move(provenance), statistics,
      std::move(prepared.warnings));
}

std::vector<BackendInfo> DynamicTriangleCounting::backends() {
  return {{"edtc",
           "EDTC",
           "triangle_counting_listing",
           "7da15bf9aded",
           detail::edtc_backend_compiled(),
           true,
           {"exact_batch_changes", "single_gpu", "dynamic_graph"}}};
}

}  // namespace graphmine
