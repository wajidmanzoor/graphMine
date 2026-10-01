#include "graphmine/problems/k_core.hpp"

#include <algorithm>
#include <chrono>
#include <functional>
#include <queue>
#include <set>
#include <stdexcept>
#include <utility>

#include "backends/k_core_backend.hpp"

namespace graphmine {
namespace {

std::vector<VertexIndex> make_peeling_order(const CsrGraph& graph) {
  using QueueEntry = std::pair<std::uint32_t, VertexIndex>;
  std::priority_queue<QueueEntry, std::vector<QueueEntry>,
                      std::greater<QueueEntry>>
      queue;
  std::vector<std::uint32_t> degree(graph.vertex_count());
  std::vector<bool> removed(graph.vertex_count(), false);

  for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    degree[vertex] = static_cast<std::uint32_t>(
        graph.offsets[vertex + 1] - graph.offsets[vertex]);
    queue.emplace(degree[vertex], vertex);
  }

  std::vector<VertexIndex> order;
  order.reserve(graph.vertex_count());
  while (!queue.empty()) {
    const auto [queued_degree, vertex] = queue.top();
    queue.pop();
    if (removed[vertex] || queued_degree != degree[vertex]) {
      continue;
    }
    removed[vertex] = true;
    order.push_back(vertex);
    for (auto offset = graph.offsets[vertex];
         offset < graph.offsets[vertex + 1]; ++offset) {
      const auto neighbor = graph.neighbors[offset];
      if (!removed[neighbor] && degree[neighbor] > 0) {
        --degree[neighbor];
        queue.emplace(degree[neighbor], neighbor);
      }
    }
  }
  return order;
}

Provenance kcore_provenance() {
  return {"k_core_decomposition",
          "kcore-gpu",
          "KCoreGPU artifact",
          "0a2d37634024",
          "original KCoreGPU peeling kernels + GraphMine typed adapter"};
}

}  // namespace

const char* to_string(KCoreBackend backend) noexcept {
  switch (backend) {
    case KCoreBackend::automatic:
      return "auto";
    case KCoreBackend::kcore_gpu:
      return "kcore-gpu";
  }
  return "unknown";
}

KCore::KCore(KCoreOptions options) : options_(std::move(options)) {}

SupportReport KCore::supports(const Graph& graph) const {
  if (graph.directed() && !options_.allow_directed_projection) {
    return {false,
            "directed input requires allow_directed_projection=true"};
  }
  if (options_.execution.device_ids.empty()) {
    return {false, "at least one CUDA device id must be provided"};
  }
  const bool requests_core_subgraph =
      has_output(options_.optional_outputs,
                 KCoreOptionalOutput::requested_core_vertices) ||
      has_output(options_.optional_outputs,
                 KCoreOptionalOutput::requested_core_edges);
  if (requests_core_subgraph && !options_.requested_k) {
    return {false,
            "requested_k is required when a requested-core output is enabled"};
  }
  if (!detail::kcore_gpu_backend_compiled()) {
    return {false, "the KCoreGPU backend is not compiled in this build"};
  }
  return {true, {}};
}

ExecutionResult<KCoreOutput> KCore::run(const Graph& graph) const {
  const auto started = std::chrono::steady_clock::now();
  const auto support = supports(graph);
  auto provenance = kcore_provenance();
  if (!support.supported) {
    return ExecutionResult<KCoreOutput>::failure(
        {StatusCode::unsupported, support.reason}, provenance);
  }

  UndirectedGraphView normalized;
  try {
    normalized = graph.simple_undirected(
        {options_.allow_directed_projection});
  } catch (const std::exception& error) {
    return ExecutionResult<KCoreOutput>::failure(
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

  const auto backend = detail::run_kcore_gpu(
      normalized.csr, options_.execution.device_ids.front());
  if (!backend.status.ok()) {
    return ExecutionResult<KCoreOutput>::failure(
        backend.status, provenance, std::move(warnings));
  }
  if (backend.core_numbers.size() != graph.vertex_count()) {
    return ExecutionResult<KCoreOutput>::failure(
        {StatusCode::correctness_mismatch,
         "KCoreGPU did not return one core number per input vertex"},
        provenance, std::move(warnings));
  }

  KCoreOutput output;
  output.core_number_by_vertex.reserve(graph.vertex_count());
  for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    output.core_number_by_vertex.push_back(
        {graph.external_id(vertex), backend.core_numbers[vertex]});
    output.degeneracy =
        std::max(output.degeneracy, backend.core_numbers[vertex]);
  }

  if (has_output(options_.optional_outputs,
                 KCoreOptionalOutput::requested_core_vertices)) {
    output.requested_core_vertices.emplace();
    for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
      if (backend.core_numbers[vertex] >= *options_.requested_k) {
        output.requested_core_vertices->push_back(graph.external_id(vertex));
      }
    }
  }

  if (has_output(options_.optional_outputs,
                 KCoreOptionalOutput::requested_core_edges)) {
    output.requested_core_edges.emplace();
    std::set<std::pair<VertexIndex, VertexIndex>> emitted;
    for (const auto& edge : graph.canonical().edges) {
      auto source = graph.dense_index(edge.source);
      auto target = graph.dense_index(edge.target);
      if (source == target) {
        continue;
      }
      if (target < source) {
        std::swap(source, target);
      }
      if (backend.core_numbers[source] >= *options_.requested_k &&
          backend.core_numbers[target] >= *options_.requested_k &&
          emitted.emplace(source, target).second) {
        output.requested_core_edges->push_back(edge.id);
      }
    }
  }

  const auto materialization_started = std::chrono::steady_clock::now();
  if (has_output(options_.optional_outputs,
                 KCoreOptionalOutput::peeling_order)) {
    output.peeling_order.emplace();
    for (const auto vertex : make_peeling_order(normalized.csr)) {
      output.peeling_order->push_back(graph.external_id(vertex));
    }
    warnings.emplace_back(
        "peeling_order is a deterministic valid common-layer order; "
        "KCoreGPU does not export its internal concurrent order");
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
  return ExecutionResult<KCoreOutput>::success(
      std::move(output), std::move(provenance), statistics,
      std::move(warnings));
}

std::vector<BackendInfo> KCore::backends() {
  return {{"kcore-gpu",
           "KCoreGPU",
           "k_core_decomposition",
           "0a2d37634024",
           detail::kcore_gpu_backend_compiled(),
           true,
           {"full_core_vector", "single_gpu"}}};
}

}  // namespace graphmine
