#include "graphmine/problems/maximum_clique.hpp"

#include <algorithm>
#include <chrono>
#include <functional>
#include <numeric>
#include <stdexcept>
#include <string>
#include <utility>

#include "backends/maximum_clique_backend.hpp"

namespace graphmine {
namespace {

bool is_clique(const CsrGraph& graph,
               const std::vector<VertexIndex>& vertices) {
  for (std::size_t i = 0; i < vertices.size(); ++i) {
    const auto begin = graph.neighbors.begin() +
                       static_cast<std::ptrdiff_t>(graph.offsets[vertices[i]]);
    const auto end = graph.neighbors.begin() + static_cast<std::ptrdiff_t>(
                                                   graph.offsets[vertices[i] + 1]);
    for (std::size_t j = i + 1; j < vertices.size(); ++j) {
      if (!std::binary_search(begin, end, vertices[j])) {
        return false;
      }
    }
  }
  return true;
}

std::uint32_t greedy_coloring_upper_bound(const CsrGraph& graph) {
  if (graph.vertex_count() == 0) {
    return 0;
  }
  std::vector<VertexIndex> order(graph.vertex_count());
  std::iota(order.begin(), order.end(), VertexIndex{0});
  std::sort(order.begin(), order.end(), [&](VertexIndex lhs, VertexIndex rhs) {
    const auto lhs_degree = graph.offsets[lhs + 1] - graph.offsets[lhs];
    const auto rhs_degree = graph.offsets[rhs + 1] - graph.offsets[rhs];
    return lhs_degree == rhs_degree ? lhs < rhs : lhs_degree > rhs_degree;
  });

  std::vector<int> color(graph.vertex_count(), -1);
  std::uint32_t color_count = 0;
  for (const auto vertex : order) {
    std::vector<bool> used(color_count, false);
    for (auto offset = graph.offsets[vertex];
         offset < graph.offsets[vertex + 1]; ++offset) {
      const auto neighbor_color = color[graph.neighbors[offset]];
      if (neighbor_color >= 0) {
        used[static_cast<std::size_t>(neighbor_color)] = true;
      }
    }
    std::uint32_t selected = 0;
    while (selected < used.size() && used[selected]) {
      ++selected;
    }
    if (selected == color_count) {
      ++color_count;
    }
    color[vertex] = static_cast<int>(selected);
  }
  return color_count;
}

Provenance maximum_clique_provenance(MaximumCliqueBackend backend) {
  Provenance provenance;
  provenance.problem = "maximum_clique";
  provenance.backend = to_string(backend);
  switch (backend) {
    case MaximumCliqueBackend::cuda_ms:
      provenance.backend_version = "CUDA-MS artifact";
      provenance.source_commit =
          "a0b6b00a1f67";
      provenance.execution_path =
          "original CUDA-MS solver + GraphMine feasibility and coloring bound";
      break;
    case MaximumCliqueBackend::gpu_maximum_clique:
      provenance.backend_version = "GPUMaximumClique artifact";
      provenance.source_commit = "2365400c7b4a";
      provenance.execution_path =
          "original parallel greedy preprocessing + clique-merging search";
      break;
    case MaximumCliqueBackend::maximum_clique_on_gpu:
      provenance.backend_version = "Maximum-Clique-on-GPU artifact";
      provenance.source_commit = "62708c588219";
      provenance.execution_path =
          "original k-core heuristic, reduction, and GPU branch-and-bound";
      break;
    case MaximumCliqueBackend::automatic:
      break;
  }
  return provenance;
}

}  // namespace

const char* to_string(MaximumCliqueBackend backend) noexcept {
  switch (backend) {
    case MaximumCliqueBackend::automatic:
      return "auto";
    case MaximumCliqueBackend::cuda_ms:
      return "cuda-ms";
    case MaximumCliqueBackend::gpu_maximum_clique:
      return "gpu-maximum-clique";
    case MaximumCliqueBackend::maximum_clique_on_gpu:
      return "maximum-clique-on-gpu";
  }
  return "unknown";
}

MaximumClique::MaximumClique(MaximumCliqueOptions options)
    : options_(std::move(options)) {}

SupportReport MaximumClique::supports(const Graph& graph) const {
  const auto selected = options_.backend == MaximumCliqueBackend::automatic
                            ? MaximumCliqueBackend::cuda_ms
                            : options_.backend;
  if (graph.directed() && !options_.allow_directed_projection) {
    return {false,
            "directed input requires allow_directed_projection=true"};
  }
  if (options_.execution.device_ids.empty()) {
    return {false, "at least one CUDA device id must be provided"};
  }
  if (options_.known_lower_bound &&
      *options_.known_lower_bound > graph.vertex_count()) {
    return {false, "known_lower_bound exceeds the graph vertex count"};
  }
  if (options_.return_all_ties &&
      selected != MaximumCliqueBackend::gpu_maximum_clique) {
    return {false,
            "return_all_ties is only available with GPUMaximumClique"};
  }
  bool compiled = false;
  switch (selected) {
    case MaximumCliqueBackend::cuda_ms:
      compiled = detail::cuda_ms_backend_compiled();
      break;
    case MaximumCliqueBackend::gpu_maximum_clique:
      compiled = detail::gpu_maximum_clique_backend_compiled();
      break;
    case MaximumCliqueBackend::maximum_clique_on_gpu:
      compiled = detail::maximum_clique_on_gpu_backend_compiled();
      break;
    case MaximumCliqueBackend::automatic:
      break;
  }
  if (!compiled) {
    return {false, std::string("the ") + to_string(selected) +
                       " backend is not compiled in this build"};
  }
  return {true, {}};
}

ExecutionResult<MaximumCliqueOutput> MaximumClique::run(
    const Graph& graph) const {
  const auto started = std::chrono::steady_clock::now();
  const auto support = supports(graph);
  const auto selected = options_.backend == MaximumCliqueBackend::automatic
                            ? MaximumCliqueBackend::cuda_ms
                            : options_.backend;
  auto provenance = maximum_clique_provenance(selected);
  if (!support.supported) {
    return ExecutionResult<MaximumCliqueOutput>::failure(
        {StatusCode::unsupported, support.reason}, provenance);
  }

  UndirectedGraphView normalized;
  try {
    normalized = graph.simple_undirected(
        {options_.allow_directed_projection});
  } catch (const std::exception& error) {
    return ExecutionResult<MaximumCliqueOutput>::failure(
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

  detail::MaximumCliqueBackendResult backend;
  if (normalized.csr.vertex_count() == 0) {
    backend.status = Status::success();
  } else if (normalized.csr.undirected_edge_count() == 0) {
    backend.status = Status::success();
    backend.clique = {0};
    provenance.execution_path += " (trivial edgeless-graph result)";
  } else {
    const auto lower_bound = options_.known_lower_bound.value_or(0U);
    switch (selected) {
      case MaximumCliqueBackend::cuda_ms:
        backend = detail::run_cuda_ms(
            normalized.csr, options_.execution.device_ids.front());
        break;
      case MaximumCliqueBackend::gpu_maximum_clique:
        backend = detail::run_gpu_maximum_clique(
            normalized.csr, options_.execution.device_ids.front(),
            lower_bound, options_.return_all_ties);
        break;
      case MaximumCliqueBackend::maximum_clique_on_gpu:
        backend = detail::run_maximum_clique_on_gpu(
            normalized.csr, options_.execution.device_ids.front(),
            lower_bound);
        break;
      case MaximumCliqueBackend::automatic:
        break;
    }
  }
  if (!backend.status.ok()) {
    return ExecutionResult<MaximumCliqueOutput>::failure(
        backend.status, provenance, std::move(warnings));
  }
  if (!is_clique(normalized.csr, backend.clique)) {
    return ExecutionResult<MaximumCliqueOutput>::failure(
        {StatusCode::correctness_mismatch,
         std::string(to_string(selected)) +
             " returned vertices that do not form a clique"},
        provenance, std::move(warnings));
  }
  for (const auto& tied_clique : backend.tied_cliques) {
    if (tied_clique.size() != backend.clique.size() ||
        !is_clique(normalized.csr, tied_clique)) {
      return ExecutionResult<MaximumCliqueOutput>::failure(
          {StatusCode::correctness_mismatch,
           std::string(to_string(selected)) +
               " returned an invalid tied maximum clique"},
          provenance, std::move(warnings));
    }
  }
  if (options_.known_lower_bound &&
      backend.clique.size() < *options_.known_lower_bound) {
    return ExecutionResult<MaximumCliqueOutput>::failure(
        {StatusCode::correctness_mismatch,
         std::string(to_string(selected)) +
             " result is smaller than the caller's valid lower bound"},
        provenance, std::move(warnings));
  }

  // CUDA-MS's returned relaxation mask is not a certified global upper
  // bound. On the seeded nine-vertex regression it has size three although
  // vertices 2, 4, 6, 7 form a four-clique. Only a proper coloring provides
  // the common upper bound; a local relaxation must never certify optimality.
  const auto certified_upper = greedy_coloring_upper_bound(normalized.csr);
  if (backend.clique.size() > certified_upper) {
    return ExecutionResult<MaximumCliqueOutput>::failure(
        {StatusCode::internal_error,
         "computed coloring bound is below the feasible clique size"},
        provenance, std::move(warnings));
  }

  MaximumCliqueOutput output;
  output.maximum_size = static_cast<std::uint32_t>(backend.clique.size());
  const auto append_clique = [&](const std::vector<VertexIndex>& clique) {
    output.cliques.emplace_back();
    output.cliques.back().reserve(clique.size());
    for (const auto vertex : clique) {
      output.cliques.back().push_back(graph.external_id(vertex));
    }
  };
  if (backend.tied_cliques.empty()) {
    append_clique(backend.clique);
  } else {
    for (const auto& clique : backend.tied_cliques) append_clique(clique);
  }
  output.optimal = selected != MaximumCliqueBackend::cuda_ms ||
                   output.maximum_size == certified_upper;
  if (has_output(options_.optional_outputs,
                 MaximumCliqueOptionalOutput::upper_bound)) {
    output.upper_bound = certified_upper;
  }
  if (!output.optimal) {
    warnings.emplace_back(
        std::string(to_string(selected)) +
        " returned a feasible clique, but the common coloring bound "
        "did not prove global optimality");
  }

  const auto finished = std::chrono::steady_clock::now();
  ExecutionStatistics statistics;
  statistics.backend_ms = backend.elapsed_ms;
  statistics.end_to_end_ms =
      std::chrono::duration<double, std::milli>(finished - started).count();
  return ExecutionResult<MaximumCliqueOutput>::success(
      std::move(output), std::move(provenance), statistics,
      std::move(warnings));
}

std::vector<BackendInfo> MaximumClique::backends() {
  return {
      {"cuda-ms",
       "CUDA-MS",
       "maximum_clique",
       "a0b6b00a1f67",
       detail::cuda_ms_backend_compiled(),
       true,
       {"single_clique", "single_gpu", "dense_adjacency"}},
      {"gpu-maximum-clique",
       "GPUMaximumClique",
       "maximum_clique",
       "2365400c7b4a",
       detail::gpu_maximum_clique_backend_compiled(),
       true,
       {"single_clique", "single_gpu"}},
      {"maximum-clique-on-gpu",
       "Maximum-Clique-on-GPU",
       "maximum_clique",
       "62708c588219",
       detail::maximum_clique_on_gpu_backend_compiled(),
       true,
       {"single_clique", "multi_gpu_upstream"}},
  };
}

}  // namespace graphmine
