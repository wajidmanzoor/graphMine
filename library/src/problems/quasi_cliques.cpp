#include "graphmine/problems/quasi_cliques.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <set>
#include <stdexcept>
#include <utility>

#include "backends/quasi_clique_backend.hpp"

namespace graphmine {
namespace {

bool is_quasi_clique(const CsrGraph& graph,
                     const std::vector<VertexIndex>& vertices,
                     double ratio) {
  if (vertices.size() < 2) {
    return false;
  }
  const auto minimum_degree = static_cast<std::size_t>(
      std::ceil(ratio * static_cast<double>(vertices.size() - 1)));
  for (const auto vertex : vertices) {
    std::size_t degree = 0;
    const auto begin = graph.neighbors.begin() +
                       static_cast<std::ptrdiff_t>(graph.offsets[vertex]);
    const auto end = graph.neighbors.begin() +
                     static_cast<std::ptrdiff_t>(graph.offsets[vertex + 1]);
    for (const auto candidate : vertices) {
      if (candidate != vertex &&
          std::binary_search(begin, end, candidate)) {
        ++degree;
      }
    }
    if (degree < minimum_degree) {
      return false;
    }
  }
  return true;
}

Status validate_backend_output(
    const CsrGraph& graph,
    const std::vector<std::vector<VertexIndex>>& quasi_cliques,
    const QuasiCliqueOptions& options) {
  std::set<std::vector<VertexIndex>> unique;
  for (const auto& quasi_clique : quasi_cliques) {
    if (quasi_clique.size() < options.minimum_size) {
      return {StatusCode::correctness_mismatch,
              "cuQC returned a result below minimum_size"};
    }
    if (!std::is_sorted(quasi_clique.begin(), quasi_clique.end()) ||
        std::adjacent_find(quasi_clique.begin(), quasi_clique.end()) !=
            quasi_clique.end() ||
        (!quasi_clique.empty() &&
         quasi_clique.back() >= graph.vertex_count())) {
      return {StatusCode::correctness_mismatch,
              "cuQC returned an invalid vertex set"};
    }
    if (!is_quasi_clique(graph, quasi_clique,
                         options.minimum_degree_ratio)) {
      return {StatusCode::correctness_mismatch,
              "cuQC returned a set that does not satisfy gamma"};
    }
    if (!unique.emplace(quasi_clique).second) {
      return {StatusCode::correctness_mismatch,
              "cuQC returned a duplicate maximal quasi-clique"};
    }

    std::vector<bool> member(graph.vertex_count(), false);
    for (const auto vertex : quasi_clique) {
      member[vertex] = true;
    }
    for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
      if (member[vertex]) {
        continue;
      }
      auto extension = quasi_clique;
      extension.insert(
          std::lower_bound(extension.begin(), extension.end(), vertex),
          vertex);
      if (is_quasi_clique(graph, extension,
                          options.minimum_degree_ratio)) {
        std::string members;
        for (const auto member : quasi_clique) {
          members += (members.empty() ? "" : ",") + std::to_string(member);
        }
        return {StatusCode::correctness_mismatch,
                "cuQC returned a non-maximal quasi-clique; vertex " +
                    std::to_string(vertex) + " can extend a returned set of " +
                    std::to_string(quasi_clique.size()) + " vertices [" +
                    members + "]; backend returned " +
                    std::to_string(quasi_cliques.size()) +
                    " sets with maximum size " +
                    std::to_string(quasi_cliques.empty()
                                       ? 0
                                       : quasi_cliques.back().size())};
      }
    }
  }
  return Status::success();
}

Provenance cuqc_provenance() {
  return {"quasi_clique_mining",
          "cuqc",
          "cuQC artifact",
          "e3785db225f2730898c2b316a4fcc06516b16c06",
          "original cuQC CPU/GPU expansion and maximal-set filtering"};
}

}  // namespace

const char* to_string(QuasiCliqueBackend backend) noexcept {
  switch (backend) {
    case QuasiCliqueBackend::automatic:
      return "auto";
    case QuasiCliqueBackend::cuqc:
      return "cuqc";
  }
  return "unknown";
}

QuasiCliques::QuasiCliques(QuasiCliqueOptions options)
    : options_(std::move(options)) {}

SupportReport QuasiCliques::supports(const Graph& graph) const {
  if (!std::isfinite(options_.minimum_degree_ratio) ||
      options_.minimum_degree_ratio < 0.5 ||
      options_.minimum_degree_ratio > 1.0) {
    return {false, "minimum_degree_ratio must be in [0.5, 1.0]"};
  }
  if (options_.minimum_size <= 1) {
    return {false, "minimum_size must be greater than one"};
  }
  if (options_.minimum_size >
      static_cast<std::size_t>(std::numeric_limits<int>::max())) {
    return {false, "cuQC uses a signed 32-bit minimum size"};
  }
  if (options_.result_limit && *options_.result_limit == 0) {
    return {false, "result_limit must be null or at least one"};
  }
  if (graph.vertex_count() >
          static_cast<std::size_t>(std::numeric_limits<int>::max()) ||
      graph.edge_count() >
          static_cast<std::size_t>(std::numeric_limits<int>::max() / 2)) {
    return {false, "cuQC uses signed 32-bit graph sizes"};
  }
  if (graph.directed() && !options_.allow_directed_projection) {
    return {false,
            "directed input requires allow_directed_projection=true"};
  }
  if (options_.execution.device_ids.empty()) {
    return {false, "at least one CUDA device id must be provided"};
  }
  if (!detail::cuqc_backend_compiled() &&
      graph.vertex_count() >= options_.minimum_size) {
    return {false, "the cuQC backend is not compiled in this build"};
  }
  return {true, {}};
}

ExecutionResult<QuasiCliqueOutput> QuasiCliques::run(
    const Graph& graph) const {
  const auto started = std::chrono::steady_clock::now();
  auto provenance = cuqc_provenance();
  const auto support = supports(graph);
  if (!support.supported) {
    return ExecutionResult<QuasiCliqueOutput>::failure(
        {StatusCode::unsupported, support.reason}, provenance);
  }

  UndirectedGraphView normalized;
  try {
    normalized = graph.simple_undirected(
        {options_.allow_directed_projection});
  } catch (const std::exception& error) {
    return ExecutionResult<QuasiCliqueOutput>::failure(
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

  const auto backend =
      graph.vertex_count() < options_.minimum_size
          ? detail::QuasiCliqueBackendResult{Status::success(), {}, 0.0}
          : detail::run_cuqc(
                normalized.csr, options_.minimum_degree_ratio,
                options_.minimum_size,
                options_.scheduling == CuQCScheduling::static_schedule,
                options_.execution.device_ids.front());
  if (!backend.status.ok()) {
    return ExecutionResult<QuasiCliqueOutput>::failure(
        backend.status, provenance, std::move(warnings));
  }
  const auto validation =
      validate_backend_output(normalized.csr, backend.quasi_cliques, options_);
  if (!validation.ok()) {
    return ExecutionResult<QuasiCliqueOutput>::failure(
        validation, provenance, std::move(warnings));
  }

  const auto materialization_started = std::chrono::steady_clock::now();
  QuasiCliqueOutput output;
  const std::uint64_t total = backend.quasi_cliques.size();
  const std::size_t returned = options_.result_limit
                                   ? std::min<std::uint64_t>(
                                         total, *options_.result_limit)
                                   : static_cast<std::size_t>(total);
  output.quasi_cliques.reserve(returned);
  for (std::size_t index = 0; index < returned; ++index) {
    std::vector<ExternalId> external;
    external.reserve(backend.quasi_cliques[index].size());
    for (const auto vertex : backend.quasi_cliques[index]) {
      external.push_back(graph.external_id(vertex));
    }
    output.quasi_cliques.push_back(std::move(external));
  }
  output.returned_count = output.quasi_cliques.size();
  output.complete = output.returned_count == total;
  if (has_output(options_.optional_outputs,
                 QuasiCliqueOptionalOutput::total_count)) {
    output.total_count = total;
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
  return ExecutionResult<QuasiCliqueOutput>::success(
      std::move(output), std::move(provenance), statistics,
      std::move(warnings));
}

std::vector<BackendInfo> QuasiCliques::backends() {
  return {{"cuqc",
           "cuQC",
           "quasi_clique_mining",
           "e3785db225f2730898c2b316a4fcc06516b16c06",
           detail::cuqc_backend_compiled(),
           true,
           {"maximal_sets", "gamma_at_least_one_half", "single_gpu"}}};
}

}  // namespace graphmine
