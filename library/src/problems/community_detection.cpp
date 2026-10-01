#include "graphmine/problems/community_detection.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "backends/community_detection_backend.hpp"

namespace graphmine {
namespace {

CommunityDetectionBackend selected_backend(
    const CommunityDetectionOptions& options) {
  if (options.backend != CommunityDetectionBackend::automatic) {
    return options.backend;
  }
  if (detail::gleiden_backend_compiled()) {
    return CommunityDetectionBackend::gleiden;
  }
  return CommunityDetectionBackend::parallel_leiden_plus;
}

bool compiled(CommunityDetectionBackend backend) {
  switch (backend) {
    case CommunityDetectionBackend::gleiden:
      return detail::gleiden_backend_compiled();
    case CommunityDetectionBackend::parallel_louvain:
    case CommunityDetectionBackend::parallel_leiden:
    case CommunityDetectionBackend::parallel_leiden_plus:
      return detail::pggc_backend_compiled();
    case CommunityDetectionBackend::automatic:
      break;
  }
  return false;
}

Provenance provenance_for(CommunityDetectionBackend backend) {
  if (backend == CommunityDetectionBackend::gleiden) {
    return {"community_detection",
            "gleiden",
            "gLeiden artifact",
            "6aacd7f8e91d",
            "original recursive GPU Leiden kernels + in-memory CSR and "
            "original-vertex projection adapter"};
  }
  return {"community_detection",
          to_string(backend),
          "Parallel Multilevel Graph Clustering artifact",
          "29c69d27ba38",
          std::string("original Kokkos ") + to_string(backend) +
              " clustering path + in-memory CSR adapter"};
}

detail::PggcAlgorithm pggc_algorithm(CommunityDetectionBackend backend) {
  switch (backend) {
    case CommunityDetectionBackend::parallel_louvain:
      return detail::PggcAlgorithm::parallel_louvain;
    case CommunityDetectionBackend::parallel_leiden:
      return detail::PggcAlgorithm::parallel_leiden;
    case CommunityDetectionBackend::parallel_leiden_plus:
      return detail::PggcAlgorithm::parallel_leiden_plus;
    case CommunityDetectionBackend::automatic:
    case CommunityDetectionBackend::gleiden:
      break;
  }
  return detail::PggcAlgorithm::parallel_leiden_plus;
}

struct PartitionMetrics {
  double modularity = 0.0;
  std::uint64_t edge_cut = 0;
};

PartitionMetrics partition_metrics(const CsrGraph& graph,
                                   const std::vector<std::uint32_t>& labels,
                                   std::uint32_t community_count) {
  PartitionMetrics result;
  if (graph.neighbors.empty()) return result;
  std::vector<std::uint64_t> degree_sum(community_count, 0);
  std::uint64_t internal_arcs = 0;
  for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    degree_sum[labels[vertex]] +=
        graph.offsets[vertex + 1U] - graph.offsets[vertex];
    for (auto edge = graph.offsets[vertex];
         edge < graph.offsets[vertex + 1U]; ++edge) {
      const auto neighbor = graph.neighbors[edge];
      if (labels[vertex] == labels[neighbor]) {
        ++internal_arcs;
      } else if (vertex < neighbor) {
        ++result.edge_cut;
      }
    }
  }
  const auto arc_count = static_cast<long double>(graph.neighbors.size());
  long double quality =
      static_cast<long double>(internal_arcs) / arc_count;
  for (const auto degree : degree_sum) {
    const auto fraction = static_cast<long double>(degree) / arc_count;
    quality -= fraction * fraction;
  }
  result.modularity = static_cast<double>(quality);
  return result;
}

}  // namespace

const char* to_string(CommunityDetectionBackend backend) noexcept {
  switch (backend) {
    case CommunityDetectionBackend::automatic:
      return "auto";
    case CommunityDetectionBackend::gleiden:
      return "gleiden";
    case CommunityDetectionBackend::parallel_louvain:
      return "parallel-louvain";
    case CommunityDetectionBackend::parallel_leiden:
      return "parallel-leiden";
    case CommunityDetectionBackend::parallel_leiden_plus:
      return "parallel-leiden-plus";
  }
  return "unknown";
}

CommunityDetection::CommunityDetection(CommunityDetectionOptions options)
    : options_(std::move(options)) {}

SupportReport CommunityDetection::supports(const Graph& graph) const {
  const auto backend = selected_backend(options_);
  if (graph.directed() && !options_.allow_directed_projection) {
    return {false,
            "directed input requires allow_directed_projection=true"};
  }
  if (options_.execution.device_ids.empty()) {
    return {false, "at least one CUDA device id must be provided"};
  }
  for (const auto& edge : graph.canonical().edges) {
    if (edge.weight &&
        (!std::isfinite(*edge.weight) || *edge.weight != 1.0)) {
      return {false,
              "the validated community paths accept unweighted graphs only"};
    }
  }
  if (!compiled(backend) && graph.edge_count() != 0) {
    return {false, std::string("the ") + to_string(backend) +
                       " backend is not compiled in this build"};
  }
  return {true, {}};
}

ExecutionResult<CommunityDetectionOutput> CommunityDetection::run(
    const Graph& graph) const {
  const auto started = std::chrono::steady_clock::now();
  const auto backend = selected_backend(options_);
  auto provenance = provenance_for(backend);
  const auto support = supports(graph);
  if (!support.supported) {
    return ExecutionResult<CommunityDetectionOutput>::failure(
        {StatusCode::unsupported, support.reason}, provenance);
  }

  UndirectedGraphView normalized;
  try {
    normalized = graph.simple_undirected(
        {options_.allow_directed_projection});
  } catch (const std::exception& error) {
    return ExecutionResult<CommunityDetectionOutput>::failure(
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

  detail::CommunityDetectionBackendResult backend_result;
  if (normalized.csr.vertex_count() == 0) {
    backend_result.status = Status::success();
    provenance.execution_path += " (trivial empty-graph result)";
  } else if (normalized.csr.neighbors.empty()) {
    backend_result.status = Status::success();
    backend_result.labels.resize(normalized.csr.vertex_count());
    for (std::size_t vertex = 0; vertex < backend_result.labels.size();
         ++vertex) {
      backend_result.labels[vertex] = static_cast<std::uint32_t>(vertex);
    }
    backend_result.native_modularity = 0.0;
    provenance.execution_path += " (trivial edgeless-graph result)";
  } else if (backend == CommunityDetectionBackend::gleiden) {
    backend_result = detail::run_gleiden(
        normalized.csr, options_.execution.device_ids.front());
  } else {
    backend_result = detail::run_pggc(
        normalized.csr, options_.execution.device_ids.front(),
        pggc_algorithm(backend));
  }
  if (!backend_result.status.ok()) {
    return ExecutionResult<CommunityDetectionOutput>::failure(
        backend_result.status, provenance, std::move(warnings));
  }
  if (backend_result.labels.size() != normalized.csr.vertex_count()) {
    return ExecutionResult<CommunityDetectionOutput>::failure(
        {StatusCode::correctness_mismatch,
         std::string(to_string(backend)) +
             " did not return one label per input vertex"},
        provenance, std::move(warnings));
  }

  // Community IDs are semantically arbitrary.  Densify by first appearance
  // to give callers stable, compact IDs without changing the partition.
  std::unordered_map<std::uint32_t, std::uint32_t> dense_labels;
  std::vector<std::uint32_t> labels;
  labels.reserve(backend_result.labels.size());
  for (const auto raw : backend_result.labels) {
    const auto inserted = dense_labels.emplace(
        raw, static_cast<std::uint32_t>(dense_labels.size()));
    labels.push_back(inserted.first->second);
  }
  if (dense_labels.size() >
      static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max())) {
    return ExecutionResult<CommunityDetectionOutput>::failure(
        {StatusCode::resource_exhausted,
         "community count exceeds the public label type"},
        provenance, std::move(warnings));
  }
  const auto community_count =
      static_cast<std::uint32_t>(dense_labels.size());
  const auto metrics =
      partition_metrics(normalized.csr, labels, community_count);
  if (backend_result.native_modularity &&
      std::abs(*backend_result.native_modularity - metrics.modularity) >
          1e-7) {
    return ExecutionResult<CommunityDetectionOutput>::failure(
        {StatusCode::correctness_mismatch,
         std::string(to_string(backend)) + " reported modularity " +
             std::to_string(*backend_result.native_modularity) +
             ", but the returned partition has modularity " +
             std::to_string(metrics.modularity)},
        provenance, std::move(warnings));
  }

  const auto materialization_started = std::chrono::steady_clock::now();
  CommunityDetectionOutput output;
  output.community_count = community_count;
  output.modularity = metrics.modularity;
  output.assignment_by_vertex.reserve(graph.vertex_count());
  for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    output.assignment_by_vertex.push_back(
        {graph.external_id(vertex), labels[vertex]});
  }
  if (has_output(options_.optional_outputs,
                 CommunityDetectionOptionalOutput::communities)) {
    output.communities.emplace(community_count);
    for (std::uint32_t community = 0; community < community_count;
         ++community) {
      (*output.communities)[community].id = community;
    }
    for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
      (*output.communities)[labels[vertex]].vertices.push_back(
          graph.external_id(vertex));
    }
  }
  if (has_output(options_.optional_outputs,
                 CommunityDetectionOptionalOutput::edge_cut)) {
    output.edge_cut = metrics.edge_cut;
  }
  const auto materialization_finished = std::chrono::steady_clock::now();
  const auto finished = std::chrono::steady_clock::now();

  ExecutionStatistics statistics;
  statistics.backend_ms = backend_result.elapsed_ms;
  statistics.output_materialization_ms =
      std::chrono::duration<double, std::milli>(materialization_finished -
                                                materialization_started)
          .count();
  statistics.end_to_end_ms =
      std::chrono::duration<double, std::milli>(finished - started).count();
  return ExecutionResult<CommunityDetectionOutput>::success(
      std::move(output), std::move(provenance), statistics,
      std::move(warnings));
}

std::vector<BackendInfo> CommunityDetection::backends() {
  return {
      {"gleiden",
       "gLeiden",
       "community_detection",
       "6aacd7f8e91d",
       detail::gleiden_backend_compiled(),
       true,
       {"unweighted", "undirected", "modularity", "single_gpu"}},
      {"parallel-louvain",
       "Parallel Louvain",
       "community_detection",
       "29c69d27ba38",
       detail::pggc_backend_compiled(),
       true,
       {"unweighted", "undirected", "modularity", "kokkos_cuda"}},
      {"parallel-leiden",
       "Parallel Leiden",
       "community_detection",
       "29c69d27ba38",
       detail::pggc_backend_compiled(),
       true,
       {"unweighted", "undirected", "modularity", "kokkos_cuda"}},
      {"parallel-leiden-plus",
       "Parallel Leiden+",
       "community_detection",
       "29c69d27ba38",
       detail::pggc_backend_compiled(),
       true,
       {"unweighted", "undirected", "modularity", "kokkos_cuda"}},
  };
}

}  // namespace graphmine
