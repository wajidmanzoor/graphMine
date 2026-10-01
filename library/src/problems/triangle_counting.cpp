#include "graphmine/problems/triangle_counting.hpp"

#include <algorithm>
#include <chrono>
#include <map>
#include <stdexcept>
#include <utility>

#include "backends/triangle_backend.hpp"

namespace graphmine {
namespace {

struct TriangleMaterialization {
  std::uint64_t count = 0;
  std::vector<std::vector<VertexIndex>> instances;
  std::vector<std::uint64_t> vertex_counts;
  std::vector<EdgeTriangleCount> edge_counts;
};

TriangleMaterialization materialize_triangles(
    const Graph& original, const CsrGraph& graph,
    const TriangleOptions& options) {
  TriangleMaterialization result;
  if (options.include_per_vertex_counts) {
    result.vertex_counts.resize(graph.vertex_count(), 0);
  }

  std::map<std::pair<VertexIndex, VertexIndex>, std::size_t> edge_positions;
  if (options.include_per_edge_counts) {
    for (const auto& edge : original.canonical().edges) {
      auto source = original.dense_index(edge.source);
      auto target = original.dense_index(edge.target);
      if (source == target) {
        continue;
      }
      if (target < source) {
        std::swap(source, target);
      }
      const auto [it, inserted] = edge_positions.emplace(
          std::make_pair(source, target), result.edge_counts.size());
      if (inserted) {
        result.edge_counts.push_back({edge.id, 0});
      }
    }
  }

  for (VertexIndex u = 0; u < graph.vertex_count(); ++u) {
    const auto u_begin = graph.neighbors.begin() +
                         static_cast<std::ptrdiff_t>(graph.offsets[u]);
    const auto u_end = graph.neighbors.begin() +
                       static_cast<std::ptrdiff_t>(graph.offsets[u + 1]);
    for (auto v_it = std::upper_bound(u_begin, u_end, u); v_it != u_end;
         ++v_it) {
      const auto v = *v_it;
      const auto v_begin = graph.neighbors.begin() +
                           static_cast<std::ptrdiff_t>(graph.offsets[v]);
      const auto v_end = graph.neighbors.begin() +
                         static_cast<std::ptrdiff_t>(graph.offsets[v + 1]);
      auto left = std::upper_bound(v_it + 1, u_end, v);
      auto right = std::upper_bound(v_begin, v_end, v);
      while (left != u_end && right != v_end) {
        if (*left < *right) {
          ++left;
        } else if (*right < *left) {
          ++right;
        } else {
          const auto w = *left;
          ++result.count;
          if (options.list_instances &&
              (!options.result_limit ||
               result.instances.size() < *options.result_limit)) {
            result.instances.push_back({u, v, w});
          }
          if (options.include_per_vertex_counts) {
            ++result.vertex_counts[u];
            ++result.vertex_counts[v];
            ++result.vertex_counts[w];
          }
          if (options.include_per_edge_counts) {
            ++result.edge_counts[edge_positions.at({u, v})].count;
            ++result.edge_counts[edge_positions.at({u, w})].count;
            ++result.edge_counts[edge_positions.at({v, w})].count;
          }
          ++left;
          ++right;
        }
      }
    }
  }
  return result;
}

Provenance triangle_provenance(TriangleBackend backend) {
  Provenance provenance;
  provenance.problem = "triangle_counting_listing";
  provenance.backend = to_string(backend);
  switch (backend) {
    case TriangleBackend::tot:
      provenance.backend_version = "ToT tensor-core artifact";
      provenance.source_commit = "5f9cde83a528";
      provenance.execution_path =
          "original ToT bitmap/tensor count + optional common materializer";
      break;
    case TriangleBackend::wetric:
      provenance.backend_version = "WeTriC artifact";
      provenance.source_commit =
          "f0c80447dc428ead5f8a41f2f1d9c4c4cbc41c2e";
      provenance.execution_path =
          "original WeTriC wedge-parallel count + optional common materializer";
      break;
    case TriangleBackend::automatic:
      break;
  }
  return provenance;
}

}  // namespace

const char* to_string(TriangleBackend backend) noexcept {
  switch (backend) {
    case TriangleBackend::automatic:
      return "auto";
    case TriangleBackend::tot:
      return "tot";
    case TriangleBackend::wetric:
      return "wetric";
  }
  return "unknown";
}

TriangleCounting::TriangleCounting(TriangleOptions options)
    : options_(std::move(options)) {}

SupportReport TriangleCounting::supports(const Graph& graph) const {
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
  if (options_.result_limit && !options_.list_instances) {
    return {false, "result_limit is meaningful only when list_instances=true"};
  }
  if (options_.wetric_spread == 0) {
    return {false, "wetric_spread must be at least one"};
  }
  if (options_.wetric_adjacency_matrix_length == 0 ||
      options_.wetric_adjacency_matrix_length % 64 != 0) {
    return {false,
            "wetric_adjacency_matrix_length must be a positive multiple of 64"};
  }
  const auto selected = options_.backend == TriangleBackend::automatic
                            ? TriangleBackend::tot
                            : options_.backend;
  if (selected == TriangleBackend::tot &&
      !detail::tot_backend_compiled()) {
    return {false, "the ToT backend is not compiled in this build"};
  }
  if (selected == TriangleBackend::wetric &&
      !detail::wetric_backend_compiled()) {
    return {false, "the WeTriC backend is not compiled in this build"};
  }
  return {true, {}};
}

ExecutionResult<TriangleOutput> TriangleCounting::run(
    const Graph& graph) const {
  const auto started = std::chrono::steady_clock::now();
  const auto support = supports(graph);
  const auto selected = options_.backend == TriangleBackend::automatic
                            ? TriangleBackend::tot
                            : options_.backend;
  auto provenance = triangle_provenance(selected);
  if (!support.supported) {
    return ExecutionResult<TriangleOutput>::failure(
        {StatusCode::unsupported, support.reason}, provenance);
  }

  UndirectedGraphView normalized;
  try {
    normalized = graph.simple_undirected(
        {options_.allow_directed_projection});
  } catch (const std::exception& error) {
    return ExecutionResult<TriangleOutput>::failure(
        {StatusCode::invalid_argument, error.what()}, provenance);
  }

  std::vector<std::string> warnings;
  if (normalized.normalization.directed_projection_applied) {
    warnings.emplace_back("directed input was projected to an undirected graph");
  }
  if (normalized.normalization.self_loops_removed > 0) {
    warnings.emplace_back("self-loops were removed during normalization");
  }
  if (normalized.normalization.parallel_edges_collapsed > 0) {
    warnings.emplace_back("parallel edges were collapsed during normalization");
  }

  detail::TriangleBackendResult backend;
  switch (selected) {
    case TriangleBackend::tot:
      backend = detail::run_tot(normalized.csr,
                                options_.execution.device_ids.front());
      break;
    case TriangleBackend::wetric:
      backend = detail::run_wetric(
          normalized.csr, options_.execution.device_ids.front(),
          options_.wetric_spread,
          options_.wetric_adjacency_matrix_length);
      break;
    case TriangleBackend::automatic:
      return ExecutionResult<TriangleOutput>::failure(
          {StatusCode::internal_error,
           "automatic triangle backend was not resolved"},
          provenance, std::move(warnings));
  }
  if (!backend.status.ok()) {
    return ExecutionResult<TriangleOutput>::failure(
        backend.status, provenance, std::move(warnings));
  }

  TriangleOutput output;
  output.global_triangle_count = backend.count;
  const bool needs_materialization = options_.list_instances ||
                                     options_.include_per_vertex_counts ||
                                     options_.include_per_edge_counts;
  const auto materialization_started = std::chrono::steady_clock::now();
  if (needs_materialization) {
    auto materialized =
        materialize_triangles(graph, normalized.csr, options_);
    if (materialized.count != backend.count) {
      return ExecutionResult<TriangleOutput>::failure(
          {StatusCode::correctness_mismatch,
           std::string(to_string(selected)) +
               " count " + std::to_string(backend.count) +
               " disagreed with exact materializer count " +
               std::to_string(materialized.count)},
          provenance, std::move(warnings));
    }
    if (options_.list_instances) {
      output.triangles.emplace();
      output.triangles->reserve(materialized.instances.size());
      for (const auto& triangle : materialized.instances) {
        output.triangles->push_back({graph.external_id(triangle[0]),
                                     graph.external_id(triangle[1]),
                                     graph.external_id(triangle[2])});
      }
      output.instances_complete =
          output.triangles->size() == output.global_triangle_count;
    }
    if (options_.include_per_vertex_counts) {
      output.per_vertex_count.emplace();
      output.per_vertex_count->reserve(graph.vertex_count());
      for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
        output.per_vertex_count->push_back(
            {graph.external_id(vertex), materialized.vertex_counts[vertex]});
      }
    }
    if (options_.include_per_edge_counts) {
      output.per_edge_count = std::move(materialized.edge_counts);
      if (normalized.normalization.parallel_edges_collapsed > 0) {
        warnings.emplace_back(
            "per-edge counts use the first input edge ID as the representative "
            "of each collapsed parallel-edge group");
      }
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
  return ExecutionResult<TriangleOutput>::success(
      std::move(output), std::move(provenance), statistics,
      std::move(warnings));
}

std::vector<BackendInfo> TriangleCounting::backends() {
  return {
      {"tot",
       "ToT",
       "triangle_counting_listing",
       "5f9cde83a528",
       detail::tot_backend_compiled(),
       true,
       {"exact_global_count", "single_gpu", "tensor_cores"}},
      {"wetric",
       "WeTriC",
       "triangle_counting_listing",
       "f0c80447dc42",
       detail::wetric_backend_compiled(),
       true,
       {"exact_global_count", "single_gpu"}},
  };
}

}  // namespace graphmine
