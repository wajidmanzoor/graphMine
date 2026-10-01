#include "graphmine/problems/maximal_cliques.hpp"

#include <algorithm>
#include <chrono>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <utility>

#include "backends/maximal_cliques/backend.hpp"

namespace graphmine {
namespace {

using InternalClique = std::vector<VertexIndex>;

struct CollectionState {
  std::size_t minimum_size = 1;
  std::optional<std::uint64_t> result_limit;
  bool must_finish = false;
  bool stopped_early = false;
  std::uint64_t qualifying_count = 0;
  std::vector<InternalClique> cliques;
};

using NeighborIterator = std::vector<VertexIndex>::const_iterator;

std::pair<NeighborIterator, NeighborIterator> neighbors(
    const CsrGraph& graph, VertexIndex vertex) {
  const auto begin = graph.offsets[vertex];
  const auto end = graph.offsets[vertex + 1];
  return {graph.neighbors.begin() + static_cast<std::ptrdiff_t>(begin),
          graph.neighbors.begin() + static_cast<std::ptrdiff_t>(end)};
}

bool adjacent(const CsrGraph& graph, VertexIndex lhs, VertexIndex rhs) {
  const auto [begin, end] = neighbors(graph, lhs);
  return std::binary_search(begin, end, rhs);
}

std::vector<VertexIndex> intersect_neighbors(
    const CsrGraph& graph, const std::vector<VertexIndex>& vertices,
    VertexIndex pivot) {
  std::vector<VertexIndex> result;
  result.reserve(vertices.size());
  const auto [begin, end] = neighbors(graph, pivot);
  std::set_intersection(vertices.begin(), vertices.end(), begin, end,
                        std::back_inserter(result));
  return result;
}

VertexIndex choose_pivot(const CsrGraph& graph,
                         const std::vector<VertexIndex>& possible,
                         const std::vector<VertexIndex>& excluded) {
  VertexIndex best = possible.empty() ? excluded.front() : possible.front();
  std::size_t best_score = 0;
  const auto score = [&](VertexIndex candidate) {
    std::size_t count = 0;
    const auto [begin, end] = neighbors(graph, candidate);
    auto p = possible.begin();
    auto n = begin;
    while (p != possible.end() && n != end) {
      if (*p < *n) {
        ++p;
      } else if (*n < *p) {
        ++n;
      } else {
        ++count;
        ++p;
        ++n;
      }
    }
    return count;
  };

  for (const auto vertex : possible) {
    const auto candidate_score = score(vertex);
    if (candidate_score > best_score) {
      best = vertex;
      best_score = candidate_score;
    }
  }
  for (const auto vertex : excluded) {
    const auto candidate_score = score(vertex);
    if (candidate_score > best_score) {
      best = vertex;
      best_score = candidate_score;
    }
  }
  return best;
}

void collect_bron_kerbosch(const CsrGraph& graph, InternalClique& current,
                           std::vector<VertexIndex> possible,
                           std::vector<VertexIndex> excluded,
                           CollectionState& state) {
  if (state.stopped_early) {
    return;
  }
  if (possible.empty() && excluded.empty()) {
    if (current.size() < state.minimum_size) {
      return;
    }
    ++state.qualifying_count;
    if (!state.result_limit || state.cliques.size() < *state.result_limit) {
      auto clique = current;
      std::sort(clique.begin(), clique.end());
      state.cliques.push_back(std::move(clique));
    }
    if (state.result_limit && state.cliques.size() >= *state.result_limit &&
        !state.must_finish) {
      state.stopped_early = true;
    }
    return;
  }

  const auto pivot = choose_pivot(graph, possible, excluded);
  std::vector<VertexIndex> candidates;
  candidates.reserve(possible.size());
  for (const auto vertex : possible) {
    if (!adjacent(graph, pivot, vertex)) {
      candidates.push_back(vertex);
    }
  }

  for (const auto vertex : candidates) {
    if (state.stopped_early) {
      return;
    }
    const auto in_possible =
        std::lower_bound(possible.begin(), possible.end(), vertex);
    if (in_possible == possible.end() || *in_possible != vertex) {
      continue;
    }

    current.push_back(vertex);
    auto next_possible = intersect_neighbors(graph, possible, vertex);
    auto next_excluded = intersect_neighbors(graph, excluded, vertex);
    collect_bron_kerbosch(graph, current, std::move(next_possible),
                          std::move(next_excluded), state);
    current.pop_back();

    possible.erase(std::lower_bound(possible.begin(), possible.end(), vertex));
    excluded.insert(std::lower_bound(excluded.begin(), excluded.end(), vertex),
                    vertex);
  }
}

CollectionState collect_cliques(const CsrGraph& graph,
                                const MaximalCliqueOptions& options,
                                bool backend_total_is_qualifying) {
  CollectionState state;
  state.minimum_size = options.minimum_clique_size;
  state.result_limit = options.result_limit;
  state.must_finish =
      has_output(options.optional_outputs,
                 MaximalCliqueOptionalOutput::total_count) &&
      !backend_total_is_qualifying;

  std::vector<VertexIndex> possible(graph.vertex_count());
  std::iota(possible.begin(), possible.end(), VertexIndex{0});
  InternalClique current;
  collect_bron_kerbosch(graph, current, std::move(possible), {}, state);
  std::sort(state.cliques.begin(), state.cliques.end());
  return state;
}

CsrGraph without_isolated_vertices(const CsrGraph& graph,
                                   std::uint64_t& isolated_count) {
  isolated_count = 0;
  std::vector<VertexIndex> old_to_new(
      graph.vertex_count(), std::numeric_limits<VertexIndex>::max());
  VertexIndex next = 0;
  for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    if (graph.offsets[vertex] == graph.offsets[vertex + 1]) {
      ++isolated_count;
    } else {
      old_to_new[vertex] = next++;
    }
  }
  if (isolated_count == 0) {
    return graph;
  }

  CsrGraph compact;
  compact.offsets.resize(static_cast<std::size_t>(next) + 1, 0);
  for (VertexIndex old_vertex = 0; old_vertex < graph.vertex_count();
       ++old_vertex) {
    const auto new_vertex = old_to_new[old_vertex];
    if (new_vertex == std::numeric_limits<VertexIndex>::max()) {
      continue;
    }
    const auto [begin, end] = neighbors(graph, old_vertex);
    for (auto it = begin; it != end; ++it) {
      compact.neighbors.push_back(old_to_new[*it]);
    }
    compact.offsets[new_vertex + 1] = compact.neighbors.size();
  }
  return compact;
}

Provenance provenance_for(MaximalCliqueBackend backend) {
  Provenance provenance;
  provenance.problem = "maximal_clique_enumeration";
  provenance.backend = to_string(backend);
  provenance.execution_path =
      "original GPU count kernel + GraphMine exact output materializer";
  switch (backend) {
    case MaximalCliqueBackend::rdmce:
      provenance.backend_version = "PPoPP 2026 artifact";
      provenance.source_commit =
          "59452dcfbcdc8dabf41abef277ef3e240248ee0c";
      break;
    case MaximalCliqueBackend::mce_gpu:
      provenance.backend_version = "PACT 2023 artifact";
      provenance.source_commit =
          "44ef6e034e39660c77c31eee475455a16af470e1";
      break;
    case MaximalCliqueBackend::g2_aimd:
      provenance.backend_version = "G2-AIMD artifact";
      provenance.source_commit =
          "751595c0511acadd662d4f999ebf04ff6cc3483a";
      break;
    case MaximalCliqueBackend::automatic:
      break;
  }
  return provenance;
}

}  // namespace

const char* to_string(MaximalCliqueBackend backend) noexcept {
  switch (backend) {
    case MaximalCliqueBackend::automatic:
      return "auto";
    case MaximalCliqueBackend::mce_gpu:
      return "mce-gpu";
    case MaximalCliqueBackend::g2_aimd:
      return "g2-aimd";
    case MaximalCliqueBackend::rdmce:
      return "rdmce";
  }
  return "unknown";
}

MaximalCliques::MaximalCliques(MaximalCliqueOptions options)
    : options_(std::move(options)) {}

SupportReport MaximalCliques::supports(const Graph& graph) const {
  if (options_.minimum_clique_size == 0) {
    return {false, "minimum_clique_size must be at least one"};
  }
  if (options_.result_limit && *options_.result_limit == 0) {
    return {false, "result_limit must be null or at least one"};
  }
  if (graph.directed() && !options_.allow_directed_projection) {
    return {false,
            "directed input requires allow_directed_projection=true"};
  }
  if (options_.execution.device_ids.empty()) {
    return {false, "at least one CUDA device id must be provided"};
  }
  const auto selected = options_.backend == MaximalCliqueBackend::automatic
                            ? MaximalCliqueBackend::rdmce
                            : options_.backend;
  if (selected == MaximalCliqueBackend::mce_gpu &&
      !detail::mce_gpu_backend_compiled()) {
    return {false, "the mce-gpu backend is not compiled in this build"};
  }
  if (selected == MaximalCliqueBackend::g2_aimd &&
      !detail::g2_aimd_backend_compiled()) {
    return {false, "the G2-AIMD backend is not compiled in this build"};
  }
  if (selected == MaximalCliqueBackend::rdmce &&
      !detail::rdmce_backend_compiled()) {
    return {false, "the RDMCE backend is not compiled in this build"};
  }
  return {true, {}};
}

ExecutionResult<MaximalCliqueOutput> MaximalCliques::run(
    const Graph& graph) const {
  const auto started = std::chrono::steady_clock::now();
  const auto support = supports(graph);
  if (!support.supported) {
    return ExecutionResult<MaximalCliqueOutput>::failure(
        Status{StatusCode::unsupported, support.reason});
  }

  const auto selected = options_.backend == MaximalCliqueBackend::automatic
                            ? MaximalCliqueBackend::rdmce
                            : options_.backend;
  auto provenance = provenance_for(selected);

  UndirectedGraphView normalized;
  try {
    normalized = graph.simple_undirected(
        {options_.allow_directed_projection});
  } catch (const std::exception& error) {
    return ExecutionResult<MaximalCliqueOutput>::failure(
        Status{StatusCode::invalid_argument, error.what()}, provenance);
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

  std::uint64_t backend_count = 0;
  double backend_ms = 0.0;
  std::uint64_t isolated_count = 0;
  auto backend_graph =
      without_isolated_vertices(normalized.csr, isolated_count);
  if (backend_graph.vertex_count() > 0) {
    detail::BackendCountResult backend_result;
    switch (selected) {
      case MaximalCliqueBackend::mce_gpu:
        backend_result = detail::run_mce_gpu_count(
            backend_graph, options_.execution.device_ids.front());
        break;
      case MaximalCliqueBackend::g2_aimd:
        backend_result = detail::run_g2_aimd_count(
            backend_graph, options_.execution.device_ids.front());
        break;
      case MaximalCliqueBackend::rdmce:
        backend_result = detail::run_rdmce_count(
            backend_graph, options_.execution.device_ids.front());
        break;
      case MaximalCliqueBackend::automatic:
        return ExecutionResult<MaximalCliqueOutput>::failure(
            {StatusCode::internal_error,
             "automatic maximal-clique backend was not resolved"},
            provenance, std::move(warnings));
    }
    if (!backend_result.status.ok()) {
      return ExecutionResult<MaximalCliqueOutput>::failure(
          backend_result.status, provenance, std::move(warnings));
    }
    backend_count = backend_result.count + isolated_count;
    backend_ms = backend_result.elapsed_ms;
  } else {
    backend_count = isolated_count;
  }

  const bool backend_total_is_qualifying = options_.minimum_clique_size == 1;
  const auto materialization_started = std::chrono::steady_clock::now();
  auto collected = collect_cliques(normalized.csr, options_,
                                   backend_total_is_qualifying);
  const auto materialization_finished = std::chrono::steady_clock::now();

  const bool collector_finished = !collected.stopped_early;
  if (collector_finished && options_.minimum_clique_size == 1 &&
      collected.qualifying_count != backend_count) {
    return ExecutionResult<MaximalCliqueOutput>::failure(
        Status{StatusCode::correctness_mismatch,
               std::string(to_string(selected)) +
                   " count disagreed with the exact output materializer"},
        provenance, std::move(warnings));
  }

  MaximalCliqueOutput output;
  output.cliques.reserve(collected.cliques.size());
  for (const auto& internal_clique : collected.cliques) {
    std::vector<ExternalId> clique;
    clique.reserve(internal_clique.size());
    for (const auto vertex : internal_clique) {
      clique.push_back(graph.external_id(vertex));
    }
    output.cliques.push_back(std::move(clique));
  }
  output.returned_count = output.cliques.size();

  std::uint64_t known_total = collected.qualifying_count;
  bool total_known = collector_finished;
  if (backend_total_is_qualifying) {
    known_total = backend_count;
    total_known = true;
  }
  output.complete = total_known && output.returned_count == known_total;
  if (has_output(options_.optional_outputs,
                 MaximalCliqueOptionalOutput::total_count)) {
    output.total_count = known_total;
  }

  warnings.emplace_back(
      std::string(to_string(selected)) +
      " supplies the validated GPU total; clique sets are materialized by "
      "GraphMine's exact Bron-Kerbosch collector");

  const auto finished = std::chrono::steady_clock::now();
  ExecutionStatistics statistics;
  statistics.backend_ms = backend_ms;
  statistics.output_materialization_ms =
      std::chrono::duration<double, std::milli>(materialization_finished -
                                                materialization_started)
          .count();
  statistics.end_to_end_ms =
      std::chrono::duration<double, std::milli>(finished - started).count();

  return ExecutionResult<MaximalCliqueOutput>::success(
      std::move(output), std::move(provenance), statistics,
      std::move(warnings));
}

std::vector<BackendInfo> MaximalCliques::backends() {
  return {
      {"mce-gpu",
       "mce-gpu",
       "maximal_clique_enumeration",
       "44ef6e034e39660c77c31eee475455a16af470e1",
       detail::mce_gpu_backend_compiled(),
       true,
       {"exact_count", "multi_gpu"}},
      {"g2-aimd",
       "G2-AIMD",
       "maximal_clique_enumeration",
       "751595c0511acadd662d4f999ebf04ff6cc3483a",
       detail::g2_aimd_backend_compiled(),
       true,
       {"exact_count"}},
      {"rdmce",
       "RDMCE",
       "maximal_clique_enumeration",
       "59452dcfbcdc8dabf41abef277ef3e240248ee0c",
       detail::rdmce_backend_compiled(),
       true,
       {"exact_count", "single_gpu", "multi_gpu_upstream"}},
  };
}

}  // namespace graphmine
