#include "graphmine/problems/k_cliques.hpp"

#include <algorithm>
#include <chrono>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "backends/k_clique_backend.hpp"

namespace graphmine {
namespace {

struct KCliqueMaterialization {
  std::uint64_t count = 0;
  std::vector<std::vector<VertexIndex>> instances;
  std::vector<std::uint64_t> per_vertex;
};

void enumerate_k_cliques(const CsrGraph& graph, std::uint32_t k,
                         const KCliqueOptions& options,
                         std::vector<VertexIndex>& current,
                         const std::vector<VertexIndex>& candidates,
                         KCliqueMaterialization& output) {
  const auto needed = static_cast<std::size_t>(k) - current.size();
  if (needed == 0) {
    if (output.count == std::numeric_limits<std::uint64_t>::max()) {
      throw std::overflow_error("k-clique count exceeds uint64_t");
    }
    ++output.count;
    if (options.enumerate &&
        (!options.result_limit ||
         output.instances.size() < *options.result_limit)) {
      output.instances.push_back(current);
    }
    if (options.include_per_vertex_counts) {
      for (const auto vertex : current) {
        ++output.per_vertex[vertex];
      }
    }
    return;
  }
  if (candidates.size() < needed) {
    return;
  }

  for (std::size_t index = 0;
       index + needed <= candidates.size(); ++index) {
    const auto vertex = candidates[index];
    current.push_back(vertex);
    std::vector<VertexIndex> next;
    if (needed > 1) {
      const auto neighbor_begin =
          graph.neighbors.begin() +
          static_cast<std::ptrdiff_t>(graph.offsets[vertex]);
      const auto neighbor_end =
          graph.neighbors.begin() +
          static_cast<std::ptrdiff_t>(graph.offsets[vertex + 1]);
      std::set_intersection(candidates.begin() +
                                static_cast<std::ptrdiff_t>(index + 1),
                            candidates.end(), neighbor_begin, neighbor_end,
                            std::back_inserter(next));
    }
    enumerate_k_cliques(graph, k, options, current, next, output);
    current.pop_back();
  }
}

KCliqueMaterialization materialize_k_cliques(const CsrGraph& graph,
                                             const KCliqueOptions& options) {
  KCliqueMaterialization output;
  if (options.include_per_vertex_counts) {
    output.per_vertex.resize(graph.vertex_count(), 0);
  }
  std::vector<VertexIndex> candidates(graph.vertex_count());
  for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    candidates[vertex] = vertex;
  }
  std::vector<VertexIndex> current;
  current.reserve(options.k);
  enumerate_k_cliques(graph, options.k, options, current, candidates, output);
  return output;
}

Provenance kclique_provenance(KCliqueBackend backend) {
  Provenance provenance;
  provenance.problem = "k_clique_counting_enumeration";
  provenance.backend = to_string(backend);
  switch (backend) {
    case KCliqueBackend::kcgpu:
      provenance.backend_version = "KCGPU artifact";
      provenance.source_commit =
          "314ac6d41fbe6582c2a258c2094c67ec1aa47116";
      provenance.execution_path =
          "original KCGPU GPU count + optional common exact materializer";
      break;
    case KCliqueBackend::graphset:
      provenance.backend_version = "GraphSet artifact";
      provenance.source_commit =
          "3bc6e6b9e2e0f61ba799a9c25cab96a9da6b4dc8";
      provenance.execution_path =
          "original GraphSet GPU count + optional common exact materializer";
      break;
    case KCliqueBackend::gamma:
      provenance.backend_version = "GAMMA artifact";
      provenance.source_commit =
          "3e01be68ededb8dcc4fa44bdb069a945a822232c";
      provenance.execution_path =
          "original GAMMA GPU count + optional common exact materializer";
      break;
    case KCliqueBackend::automatic:
      break;
  }
  return provenance;
}

}  // namespace

const char* to_string(KCliqueBackend backend) noexcept {
  switch (backend) {
    case KCliqueBackend::automatic:
      return "auto";
    case KCliqueBackend::kcgpu:
      return "kcgpu";
    case KCliqueBackend::graphset:
      return "graphset";
    case KCliqueBackend::gamma:
      return "gamma";
  }
  return "unknown";
}

KCliques::KCliques(KCliqueOptions options) : options_(std::move(options)) {}

SupportReport KCliques::supports(const Graph& graph) const {
  if (options_.k < 2) {
    return {false, "k must be at least two"};
  }
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
  if (options_.result_limit && !options_.enumerate) {
    return {false, "result_limit is meaningful only when enumerate=true"};
  }
  const auto selected = options_.backend == KCliqueBackend::automatic
                            ? KCliqueBackend::graphset
                            : options_.backend;
  if (selected == KCliqueBackend::gamma && options_.k > 5 &&
      graph.vertex_count() >= options_.k) {
    return {false, "the validated GAMMA path supports k up to five"};
  }
  if (selected == KCliqueBackend::kcgpu && options_.k > 5 &&
      graph.vertex_count() >= options_.k) {
    return {false, "the validated KCGPU path supports k up to five"};
  }
  if (selected == KCliqueBackend::graphset && options_.k > 6 &&
      graph.vertex_count() >= options_.k) {
    return {false, "the validated GraphSet path supports k up to six"};
  }
  if (selected == KCliqueBackend::kcgpu &&
      !detail::kcgpu_backend_compiled() && options_.k > 2 &&
      graph.vertex_count() >= options_.k) {
    return {false, "the KCGPU backend is not compiled"};
  }
  if (selected == KCliqueBackend::graphset &&
      !detail::graphset_kclique_backend_compiled() && options_.k > 2 &&
      graph.vertex_count() >= options_.k) {
    return {false, "the GraphSet k-clique backend is not compiled"};
  }
  if (selected == KCliqueBackend::gamma &&
      !detail::gamma_kclique_backend_compiled() && options_.k > 2 &&
      graph.vertex_count() >= options_.k) {
    return {false, "the GAMMA backend is not compiled"};
  }
  return {true, {}};
}

ExecutionResult<KCliqueOutput> KCliques::run(const Graph& graph) const {
  const auto started = std::chrono::steady_clock::now();
  const auto selected = options_.backend == KCliqueBackend::automatic
                            ? KCliqueBackend::graphset
                            : options_.backend;
  auto provenance = kclique_provenance(selected);
  const auto support = supports(graph);
  if (!support.supported) {
    return ExecutionResult<KCliqueOutput>::failure(
        {StatusCode::unsupported, support.reason}, provenance);
  }

  UndirectedGraphView normalized;
  try {
    normalized = graph.simple_undirected(
        {options_.allow_directed_projection});
  } catch (const std::exception& error) {
    return ExecutionResult<KCliqueOutput>::failure(
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

  detail::KCliqueBackendResult backend;
  if (options_.k > normalized.csr.vertex_count()) {
    backend.status = Status::success();
    provenance.execution_path += " (trivial k-greater-than-n result)";
  } else if (options_.k == 2) {
    backend.status = Status::success();
    backend.count = normalized.csr.undirected_edge_count();
    provenance.execution_path += " (common exact k=2 path)";
  } else if (normalized.csr.undirected_edge_count() <
             (static_cast<std::uint64_t>(options_.k) *
              (options_.k - 1U)) /
                 2U) {
    backend.status = Status::success();
    provenance.execution_path += " (trivial insufficient-edge result)";
  } else {
    switch (selected) {
      case KCliqueBackend::kcgpu:
        backend = detail::run_kcgpu(normalized.csr, options_.k,
                                    options_.execution.device_ids.front());
        break;
      case KCliqueBackend::graphset:
        backend = detail::run_graphset_kclique(
            normalized.csr, options_.k,
            options_.execution.device_ids.front());
        break;
      case KCliqueBackend::gamma:
        backend = detail::run_gamma_kclique(
            normalized.csr, options_.k,
            options_.execution.device_ids.front());
        break;
      case KCliqueBackend::automatic:
        return ExecutionResult<KCliqueOutput>::failure(
            {StatusCode::internal_error,
             "k-clique backend was not resolved"},
            provenance, std::move(warnings));
    }
  }
  if (!backend.status.ok()) {
    return ExecutionResult<KCliqueOutput>::failure(
        backend.status, provenance, std::move(warnings));
  }

  KCliqueOutput output;
  output.count = backend.count;
  const auto materialization_started = std::chrono::steady_clock::now();
  if (options_.enumerate || options_.include_per_vertex_counts) {
    KCliqueMaterialization materialized;
    try {
      materialized = materialize_k_cliques(normalized.csr, options_);
    } catch (const std::exception& error) {
      return ExecutionResult<KCliqueOutput>::failure(
          {StatusCode::resource_exhausted, error.what()}, provenance,
          std::move(warnings));
    }
    if (materialized.count != backend.count) {
      return ExecutionResult<KCliqueOutput>::failure(
          {StatusCode::correctness_mismatch,
           std::string(to_string(selected)) + " count " +
               std::to_string(backend.count) +
               " disagreed with exact materializer count " +
               std::to_string(materialized.count)},
          provenance, std::move(warnings));
    }
    if (options_.enumerate) {
      output.cliques.emplace();
      output.cliques->reserve(materialized.instances.size());
      for (const auto& clique : materialized.instances) {
        output.cliques->emplace_back();
        output.cliques->back().reserve(clique.size());
        for (const auto vertex : clique) {
          output.cliques->back().push_back(graph.external_id(vertex));
        }
      }
      output.complete = output.cliques->size() == output.count;
    }
    if (options_.include_per_vertex_counts) {
      output.per_vertex_count.emplace();
      output.per_vertex_count->reserve(graph.vertex_count());
      for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
        output.per_vertex_count->push_back(
            {graph.external_id(vertex), materialized.per_vertex[vertex]});
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
  return ExecutionResult<KCliqueOutput>::success(
      std::move(output), std::move(provenance), statistics,
      std::move(warnings));
}

std::vector<BackendInfo> KCliques::backends() {
  return {
      {"kcgpu", "KCGPU", "k_clique_counting_enumeration",
       "314ac6d41fbe6582c2a258c2094c67ec1aa47116",
       detail::kcgpu_backend_compiled(), true,
       {"exact_count", "single_gpu", "k_3_to_5_validated"}},
      {"graphset", "GraphSet", "k_clique_counting_enumeration",
       "3bc6e6b9e2e0f61ba799a9c25cab96a9da6b4dc8",
       detail::graphset_kclique_backend_compiled(), true,
       {"exact_count", "single_gpu", "k_3_to_5_validated"}},
      {"gamma", "GAMMA", "k_clique_counting_enumeration",
       "3e01be68ededb8dcc4fa44bdb069a945a822232c",
       detail::gamma_kclique_backend_compiled(), true,
       {"exact_count", "single_gpu", "k_3_to_5_validated"}},
  };
}

}  // namespace graphmine
