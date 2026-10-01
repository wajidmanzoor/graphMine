#include "graphmine/problems/betweenness_centrality.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <stdexcept>
#include <utility>

#include "backends/betweenness_centrality_backend.hpp"

namespace graphmine {
namespace {

Provenance turbobc_provenance() {
  return {"centrality_influential_node_mining",
          "turbo-bc",
          "TurboBC artifact",
          "6e885a207902",
          "original TurboBC scalar CSC GPU implementation + typed adapter"};
}

}  // namespace

const char* to_string(BetweennessCentralityBackend backend) noexcept {
  switch (backend) {
    case BetweennessCentralityBackend::automatic:
      return "auto";
    case BetweennessCentralityBackend::turbo_bc:
      return "turbo-bc";
  }
  return "unknown";
}

BetweennessCentrality::BetweennessCentrality(
    BetweennessCentralityOptions options)
    : options_(std::move(options)) {}

SupportReport BetweennessCentrality::supports(const Graph& graph) const {
  if (graph.directed() && !options_.allow_directed_projection) {
    return {false,
            "directed input requires allow_directed_projection=true"};
  }
  if (options_.execution.device_ids.empty()) {
    return {false, "at least one CUDA device id must be provided"};
  }
  if (!detail::turbobc_backend_compiled() && graph.vertex_count() > 0) {
    return {false, "the TurboBC backend is not compiled in this build"};
  }
  return {true, {}};
}

ExecutionResult<BetweennessCentralityOutput> BetweennessCentrality::run(
    const Graph& graph) const {
  const auto started = std::chrono::steady_clock::now();
  auto provenance = turbobc_provenance();
  const auto support = supports(graph);
  if (!support.supported) {
    return ExecutionResult<BetweennessCentralityOutput>::failure(
        {StatusCode::unsupported, support.reason}, provenance);
  }

  UndirectedGraphView normalized;
  try {
    normalized = graph.simple_undirected(
        {options_.allow_directed_projection});
  } catch (const std::exception& error) {
    return ExecutionResult<BetweennessCentralityOutput>::failure(
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

  const auto backend = normalized.csr.vertex_count() == 0
                           ? detail::BetweennessCentralityBackendResult{
                                 Status::success(), {}, 0.0}
                           : detail::run_turbobc(
                                 normalized.csr,
                                 options_.execution.device_ids.front());
  if (!backend.status.ok()) {
    return ExecutionResult<BetweennessCentralityOutput>::failure(
        backend.status, provenance, std::move(warnings));
  }
  if (backend.scores.size() != graph.vertex_count()) {
    return ExecutionResult<BetweennessCentralityOutput>::failure(
        {StatusCode::correctness_mismatch,
         "TurboBC did not return one score per input vertex"},
        provenance, std::move(warnings));
  }
  if (std::any_of(backend.scores.begin(), backend.scores.end(),
                  [](double score) { return !std::isfinite(score); })) {
    return ExecutionResult<BetweennessCentralityOutput>::failure(
        {StatusCode::correctness_mismatch,
         "TurboBC returned a non-finite centrality score"},
        provenance, std::move(warnings));
  }

  const auto materialization_started = std::chrono::steady_clock::now();
  BetweennessCentralityOutput output;
  output.score_by_vertex.reserve(graph.vertex_count());
  for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    output.score_by_vertex.push_back(
        {graph.external_id(vertex), backend.scores[vertex]});
  }

  if (has_output(options_.optional_outputs,
                 BetweennessCentralityOptionalOutput::normalized_scores)) {
    output.normalized_score_by_vertex.emplace();
    output.normalized_score_by_vertex->reserve(graph.vertex_count());
    const auto n = graph.vertex_count();
    const double scale = n > 2
                             ? 1.0 / (static_cast<double>(n - 1) *
                                      static_cast<double>(n - 2))
                             : 0.0;
    for (const auto& entry : output.score_by_vertex) {
      output.normalized_score_by_vertex->push_back(
          {entry.vertex, entry.score * scale});
    }
  }

  if (has_output(options_.optional_outputs,
                 BetweennessCentralityOptionalOutput::ranking)) {
    output.ranking = output.score_by_vertex;
    std::stable_sort(output.ranking->begin(), output.ranking->end(),
                     [](const auto& lhs, const auto& rhs) {
                       if (lhs.score != rhs.score) {
                         return lhs.score > rhs.score;
                       }
                       return lhs.vertex < rhs.vertex;
                     });
  }

  if (has_output(options_.optional_outputs,
                 BetweennessCentralityOptionalOutput::maximum) &&
      !output.score_by_vertex.empty()) {
    output.maximum = *std::max_element(
        output.score_by_vertex.begin(), output.score_by_vertex.end(),
        [](const auto& lhs, const auto& rhs) {
          if (lhs.score != rhs.score) {
            return lhs.score < rhs.score;
          }
          return rhs.vertex < lhs.vertex;
        });
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
  return ExecutionResult<BetweennessCentralityOutput>::success(
      std::move(output), std::move(provenance), statistics,
      std::move(warnings));
}

std::vector<BackendInfo> BetweennessCentrality::backends() {
  return {{"turbo-bc",
           "TurboBC",
           "centrality_influential_node_mining",
           "6e885a207902",
           detail::turbobc_backend_compiled(),
           true,
           {"unweighted", "undirected", "full_score_vector", "single_gpu"}}};
}

}  // namespace graphmine
