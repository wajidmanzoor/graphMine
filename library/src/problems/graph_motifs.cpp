#include "graphmine/problems/graph_motifs.hpp"

#include <algorithm>
#include <chrono>
#include <limits>
#include <map>
#include <numeric>
#include <queue>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "backends/graph_motif_backend.hpp"

namespace graphmine {
namespace {

using OccurrenceKey =
    std::vector<std::pair<VertexIndex, VertexIndex>>;

bool adjacent(const CsrGraph& graph, VertexIndex lhs, VertexIndex rhs) {
  const auto begin = graph.neighbors.begin() +
                     static_cast<std::ptrdiff_t>(graph.offsets[lhs]);
  const auto end = graph.neighbors.begin() +
                   static_cast<std::ptrdiff_t>(graph.offsets[lhs + 1]);
  return std::binary_search(begin, end, rhs);
}

bool connected(const CsrGraph& graph) {
  if (graph.vertex_count() == 0) {
    return false;
  }
  std::vector<bool> visited(graph.vertex_count(), false);
  std::queue<VertexIndex> pending;
  pending.push(0);
  visited[0] = true;
  std::size_t reached = 1;
  while (!pending.empty()) {
    const auto vertex = pending.front();
    pending.pop();
    for (auto edge = graph.offsets[vertex]; edge < graph.offsets[vertex + 1];
         ++edge) {
      const auto neighbor = graph.neighbors[edge];
      if (!visited[neighbor]) {
        visited[neighbor] = true;
        ++reached;
        pending.push(neighbor);
      }
    }
  }
  return reached == graph.vertex_count();
}

int graphminer_pattern_index(const CsrGraph& motif) {
  const auto size = motif.vertex_count();
  const auto edges = motif.undirected_edge_count();
  std::vector<std::uint64_t> degrees(size);
  for (VertexIndex vertex = 0; vertex < size; ++vertex) {
    degrees[vertex] = motif.offsets[vertex + 1] - motif.offsets[vertex];
  }
  std::sort(degrees.begin(), degrees.end());
  if (size == 3) {
    if (edges == 3) return 0;  // triangle
    if (edges == 2) return 1;  // wedge
  } else if (size == 4) {
    if (edges == 3 && degrees == std::vector<std::uint64_t>{1, 1, 1, 3})
      return 0;  // 3-star
    if (edges == 3 && degrees == std::vector<std::uint64_t>{1, 1, 2, 2})
      return 1;  // 4-path
    if (edges == 4 && degrees == std::vector<std::uint64_t>{1, 2, 2, 3})
      return 2;  // tailed triangle
    if (edges == 4 && degrees == std::vector<std::uint64_t>{2, 2, 2, 2})
      return 3;  // 4-cycle
    if (edges == 5) return 4;  // diamond
    if (edges == 6) return 5;  // 4-clique
  }
  return -1;
}

std::uint64_t automorphism_count(const CsrGraph& motif) {
  std::vector<VertexIndex> permutation(motif.vertex_count());
  std::iota(permutation.begin(), permutation.end(), VertexIndex{0});
  std::uint64_t count = 0;
  do {
    bool valid = true;
    for (VertexIndex lhs = 0; lhs < motif.vertex_count() && valid; ++lhs) {
      for (VertexIndex rhs = lhs + 1; rhs < motif.vertex_count(); ++rhs) {
        if (adjacent(motif, lhs, rhs) !=
            adjacent(motif, permutation[lhs], permutation[rhs])) {
          valid = false;
          break;
        }
      }
    }
    if (valid) ++count;
  } while (std::next_permutation(permutation.begin(), permutation.end()));
  return count;
}

struct MaterializedMotif {
  std::uint64_t count = 0;
  std::vector<std::vector<VertexIndex>> mappings;
  std::vector<std::uint64_t> participation;
};

struct MatchState {
  const CsrGraph* data = nullptr;
  const CsrGraph* motif = nullptr;
  const GraphMotifOptions* options = nullptr;
  std::vector<VertexIndex> order;
  std::vector<VertexIndex> mapping;
  std::vector<bool> used;
  std::set<OccurrenceKey> unique_occurrences;
  MaterializedMotif output;
};

OccurrenceKey occurrence_key(const MatchState& state) {
  OccurrenceKey key;
  for (VertexIndex source = 0; source < state.motif->vertex_count(); ++source) {
    for (auto edge = state.motif->offsets[source];
         edge < state.motif->offsets[source + 1]; ++edge) {
      const auto target = state.motif->neighbors[edge];
      if (source >= target) continue;
      auto mapped_source = state.mapping[source];
      auto mapped_target = state.mapping[target];
      if (mapped_target < mapped_source) {
        std::swap(mapped_source, mapped_target);
      }
      key.emplace_back(mapped_source, mapped_target);
    }
  }
  std::sort(key.begin(), key.end());
  return key;
}

void record_match(MatchState& state) {
  if (state.options->occurrence_identity ==
      MotifOccurrenceIdentity::unique_vertex_set_and_mapping_class) {
    if (!state.unique_occurrences.insert(occurrence_key(state)).second) {
      return;
    }
  }
  ++state.output.count;
  if (has_output(state.options->optional_outputs,
                 GraphMotifOptionalOutput::instances) &&
      (!state.options->result_limit_per_motif ||
       state.output.mappings.size() <
           *state.options->result_limit_per_motif)) {
    state.output.mappings.push_back(state.mapping);
  }
  if (has_output(state.options->optional_outputs,
                 GraphMotifOptionalOutput::per_vertex_participation)) {
    for (const auto vertex : state.mapping) {
      ++state.output.participation[vertex];
    }
  }
}

void enumerate_matches(std::size_t depth, MatchState& state) {
  if (depth == state.order.size()) {
    record_match(state);
    return;
  }
  const auto query_vertex = state.order[depth];
  const auto query_degree = state.motif->offsets[query_vertex + 1] -
                            state.motif->offsets[query_vertex];
  for (VertexIndex data_vertex = 0;
       data_vertex < state.data->vertex_count(); ++data_vertex) {
    if (state.used[data_vertex] ||
        state.data->offsets[data_vertex + 1] -
                state.data->offsets[data_vertex] <
            query_degree) {
      continue;
    }
    bool compatible = true;
    for (VertexIndex other = 0; other < state.motif->vertex_count(); ++other) {
      if (state.mapping[other] == std::numeric_limits<VertexIndex>::max()) {
        continue;
      }
      const bool query_edge = adjacent(*state.motif, query_vertex, other);
      const bool data_edge =
          adjacent(*state.data, data_vertex, state.mapping[other]);
      if ((query_edge && !data_edge) ||
          (state.options->induced && query_edge != data_edge)) {
        compatible = false;
        break;
      }
    }
    if (!compatible) continue;
    state.mapping[query_vertex] = data_vertex;
    state.used[data_vertex] = true;
    enumerate_matches(depth + 1, state);
    state.used[data_vertex] = false;
    state.mapping[query_vertex] = std::numeric_limits<VertexIndex>::max();
  }
}

MaterializedMotif materialize(const CsrGraph& data, const CsrGraph& motif,
                              const GraphMotifOptions& options) {
  MatchState state;
  state.data = &data;
  state.motif = &motif;
  state.options = &options;
  state.order.resize(motif.vertex_count());
  std::iota(state.order.begin(), state.order.end(), VertexIndex{0});
  std::stable_sort(state.order.begin(), state.order.end(),
                   [&](VertexIndex lhs, VertexIndex rhs) {
                     const auto lhs_degree =
                         motif.offsets[lhs + 1] - motif.offsets[lhs];
                     const auto rhs_degree =
                         motif.offsets[rhs + 1] - motif.offsets[rhs];
                     return lhs_degree == rhs_degree ? lhs < rhs
                                                     : lhs_degree > rhs_degree;
                   });
  state.mapping.assign(motif.vertex_count(),
                       std::numeric_limits<VertexIndex>::max());
  state.used.assign(data.vertex_count(), false);
  if (has_output(options.optional_outputs,
                 GraphMotifOptionalOutput::per_vertex_participation)) {
    state.output.participation.assign(data.vertex_count(), 0);
  }
  enumerate_matches(0, state);
  return std::move(state.output);
}

GraphMotifBackend resolve_backend(const GraphMotifOptions& options) {
  if (options.backend != GraphMotifBackend::automatic) {
    return options.backend;
  }
  return options.induced ? GraphMotifBackend::graphminer
                         : GraphMotifBackend::graphset;
}

bool backend_compiled(GraphMotifBackend backend) {
  switch (backend) {
    case GraphMotifBackend::graphminer:
      return detail::graphminer_motif_backend_compiled();
    case GraphMotifBackend::graphset:
      return detail::graphset_motif_backend_compiled();
    case GraphMotifBackend::dumato:
      return detail::dumato_motif_backend_compiled();
    case GraphMotifBackend::automatic:
      return false;
  }
  return false;
}

Provenance motif_provenance(GraphMotifBackend backend) {
  Provenance provenance;
  provenance.problem = "graph_motif_counting";
  provenance.backend = to_string(backend);
  provenance.execution_path =
      "original GPU motif vector + canonical motif classifier";
  switch (backend) {
    case GraphMotifBackend::graphminer:
      provenance.backend_version = "GraphMiner/G2Miner artifact";
      provenance.source_commit =
          "2a76e3f612e40e46a821d603ca11d10fcbc63ddd";
      break;
    case GraphMotifBackend::graphset:
      provenance.backend_version = "GraphSet artifact";
      provenance.source_commit =
          "3bc6e6b9e2e0f61ba799a9c25cab96a9da6b4dc8";
      break;
    case GraphMotifBackend::dumato:
      provenance.backend_version = "DuMato artifact";
      provenance.source_commit =
          "79c255ee2467e436d49e3ee974b4d7149551c641";
      break;
    case GraphMotifBackend::automatic:
      break;
  }
  return provenance;
}

}  // namespace

const char* to_string(GraphMotifBackend backend) noexcept {
  switch (backend) {
    case GraphMotifBackend::automatic:
      return "auto";
    case GraphMotifBackend::graphminer:
      return "graphminer";
    case GraphMotifBackend::graphset:
      return "graphset";
    case GraphMotifBackend::dumato:
      return "dumato";
  }
  return "unknown";
}

const char* to_string(MotifOccurrenceIdentity identity) noexcept {
  switch (identity) {
    case MotifOccurrenceIdentity::unique_vertex_set_and_mapping_class:
      return "unique_vertex_set_and_mapping_class";
    case MotifOccurrenceIdentity::all_embeddings:
      return "all_embeddings";
  }
  return "unknown";
}

GraphMotifs::GraphMotifs(GraphMotifOptions options)
    : options_(std::move(options)) {}

SupportReport GraphMotifs::supports(
    const Graph& data_graph, const std::vector<Graph>& motifs) const {
  if (motifs.empty()) return {false, "at least one motif is required"};
  if (options_.execution.device_ids.empty()) {
    return {false, "at least one CUDA device id must be provided"};
  }
  if (options_.result_limit_per_motif &&
      *options_.result_limit_per_motif == 0) {
    return {false, "result_limit_per_motif must be null or at least one"};
  }
  if (options_.result_limit_per_motif &&
      !has_output(options_.optional_outputs,
                  GraphMotifOptionalOutput::instances)) {
    return {false, "result_limit_per_motif requires the instances flag"};
  }
  if (data_graph.directed() && !options_.allow_directed_projection) {
    return {false,
            "the validated motif backends require undirected data; set "
            "allow_directed_projection=true to project explicitly"};
  }

  const auto selected = resolve_backend(options_);
  if ((selected == GraphMotifBackend::graphminer ||
       selected == GraphMotifBackend::dumato) &&
      !options_.induced) {
    return {false, std::string(to_string(selected)) +
                       " was validated for induced motifs only"};
  }
  if (selected == GraphMotifBackend::graphset && options_.induced) {
    return {false, "GraphSet was validated for non-induced motifs only"};
  }
  if (!backend_compiled(selected)) {
    return {false, std::string(to_string(selected)) +
                       " motif backend is not compiled in this build"};
  }

  std::set<std::string> ids;
  try {
    for (const auto& motif_graph : motifs) {
      if (motif_graph.directed() && !options_.allow_directed_projection) {
        return {false,
                "the validated motif backends require undirected motifs"};
      }
      if (motif_graph.canonical().graph.id.empty() ||
          !ids.insert(motif_graph.canonical().graph.id).second) {
        return {false, "motif graph IDs must be nonempty and unique"};
      }
      const auto motif = motif_graph.simple_undirected(
          {options_.allow_directed_projection});
      if ((motif.csr.vertex_count() != 3 &&
           motif.csr.vertex_count() != 4) ||
          !connected(motif.csr) || graphminer_pattern_index(motif.csr) < 0) {
        return {false,
                "validated motif backends support connected undirected "
                "3- and 4-vertex simple motifs"};
      }
    }
  } catch (const std::exception& error) {
    return {false, error.what()};
  }
  return {true, {}};
}

ExecutionResult<GraphMotifOutput> GraphMotifs::run(
    const Graph& data_graph, const std::vector<Graph>& motifs) const {
  const auto started = std::chrono::steady_clock::now();
  const auto selected = resolve_backend(options_);
  auto provenance = motif_provenance(selected);
  const auto support = supports(data_graph, motifs);
  if (!support.supported) {
    return ExecutionResult<GraphMotifOutput>::failure(
        {StatusCode::unsupported, support.reason}, provenance);
  }

  UndirectedGraphView data;
  std::vector<UndirectedGraphView> normalized_motifs;
  try {
    data = data_graph.simple_undirected(
        {options_.allow_directed_projection});
    normalized_motifs.reserve(motifs.size());
    for (const auto& motif : motifs) {
      normalized_motifs.push_back(motif.simple_undirected(
          {options_.allow_directed_projection}));
    }
  } catch (const std::exception& error) {
    return ExecutionResult<GraphMotifOutput>::failure(
        {StatusCode::invalid_argument, error.what()}, provenance);
  }

  std::vector<std::string> warnings;
  if (data.normalization.directed_projection_applied) {
    warnings.emplace_back("directed data was projected to an undirected graph");
  }
  if (data.normalization.self_loops_removed > 0) {
    warnings.emplace_back("data self-loops were removed during normalization");
  }
  if (data.normalization.parallel_edges_collapsed > 0) {
    warnings.emplace_back(
        "parallel data edges were collapsed during normalization");
  }

  std::map<std::uint32_t, detail::GraphMotifBackendResult> backend_results;
  double backend_ms = 0.0;
  for (const auto& motif : normalized_motifs) {
    const auto size = static_cast<std::uint32_t>(motif.csr.vertex_count());
    if (backend_results.count(size) != 0) continue;
    detail::GraphMotifBackendResult backend;
    switch (selected) {
      case GraphMotifBackend::graphminer:
        backend = detail::run_graphminer_motifs(
            data.csr, size, options_.execution.device_ids.front());
        break;
      case GraphMotifBackend::graphset:
        backend = detail::run_graphset_motifs(
            data.csr, size, options_.execution.device_ids.front());
        break;
      case GraphMotifBackend::dumato:
        backend = detail::run_dumato_motifs(
            data.csr, size, options_.execution.device_ids.front());
        break;
      case GraphMotifBackend::automatic:
        return ExecutionResult<GraphMotifOutput>::failure(
            {StatusCode::internal_error,
             "automatic motif backend was not resolved"},
            provenance, std::move(warnings));
    }
    if (!backend.status.ok()) {
      return ExecutionResult<GraphMotifOutput>::failure(
          backend.status, provenance, std::move(warnings));
    }
    backend_ms += backend.elapsed_ms;
    backend_results.emplace(size, std::move(backend));
  }

  GraphMotifOutput output;
  output.motifs.reserve(motifs.size());
  const auto materialization_started = std::chrono::steady_clock::now();
  for (std::size_t index = 0; index < motifs.size(); ++index) {
    const auto& motif = normalized_motifs[index].csr;
    const auto pattern_index = graphminer_pattern_index(motif);
    const auto& counts =
        backend_results.at(static_cast<std::uint32_t>(motif.vertex_count()))
            .counts;
    if (pattern_index < 0 ||
        static_cast<std::size_t>(pattern_index) >= counts.size()) {
      return ExecutionResult<GraphMotifOutput>::failure(
          {StatusCode::internal_error,
           "motif classifier did not match the backend count vector"},
          provenance, std::move(warnings));
    }

    GraphMotifResult result;
    result.motif_id = motifs[index].canonical().graph.id;
    result.count = counts[pattern_index];
    if (options_.occurrence_identity ==
        MotifOccurrenceIdentity::all_embeddings) {
      result.count *= automorphism_count(motif);
    }

    const bool needs_materialization =
        options_.optional_outputs != GraphMotifOptionalOutput::none;
    if (needs_materialization) {
      auto exact = materialize(data.csr, motif, options_);
      if (exact.count != result.count) {
        return ExecutionResult<GraphMotifOutput>::failure(
            {StatusCode::correctness_mismatch,
             std::string(to_string(selected)) + " count for motif " +
                 result.motif_id +
                 " disagreed with the exact optional-output materializer"},
            provenance, std::move(warnings));
      }
      if (has_output(options_.optional_outputs,
                     GraphMotifOptionalOutput::instances)) {
        result.instances.emplace();
        result.instances->reserve(exact.mappings.size());
        for (const auto& mapping : exact.mappings) {
          MotifInstance instance;
          instance.reserve(mapping.size());
          for (VertexIndex query_vertex = 0;
               query_vertex < mapping.size(); ++query_vertex) {
            instance.push_back(
                {motifs[index].external_id(query_vertex),
                 data_graph.external_id(mapping[query_vertex])});
          }
          result.instances->push_back(std::move(instance));
        }
        result.instances_complete = result.instances->size() == result.count;
      }
      if (has_output(options_.optional_outputs,
                     GraphMotifOptionalOutput::per_vertex_participation)) {
        result.per_vertex_participation.emplace();
        result.per_vertex_participation->reserve(data_graph.vertex_count());
        for (VertexIndex vertex = 0; vertex < data_graph.vertex_count();
             ++vertex) {
          result.per_vertex_participation->push_back(
              {data_graph.external_id(vertex), exact.participation[vertex]});
        }
      }
    }
    output.motifs.push_back(std::move(result));
  }
  const auto materialization_finished = std::chrono::steady_clock::now();
  const auto finished = std::chrono::steady_clock::now();

  ExecutionStatistics statistics;
  statistics.backend_ms = backend_ms;
  statistics.output_materialization_ms =
      std::chrono::duration<double, std::milli>(materialization_finished -
                                                materialization_started)
          .count();
  statistics.end_to_end_ms =
      std::chrono::duration<double, std::milli>(finished - started).count();
  return ExecutionResult<GraphMotifOutput>::success(
      std::move(output), std::move(provenance), statistics,
      std::move(warnings));
}

std::vector<BackendInfo> GraphMotifs::backends() {
  return {
      {"graphminer",
       "GraphMiner/G2Miner",
       "graph_motif_counting",
       "2a76e3f612e40e46a821d603ca11d10fcbc63ddd",
       detail::graphminer_motif_backend_compiled(),
       true,
       {"induced", "undirected", "sizes_3_4", "single_gpu"}},
      {"graphset",
       "GraphSet",
       "graph_motif_counting",
       "3bc6e6b9e2e0f61ba799a9c25cab96a9da6b4dc8",
       detail::graphset_motif_backend_compiled(),
       true,
       {"non_induced", "undirected", "sizes_3_4", "single_gpu"}},
      {"dumato",
       "DuMato",
       "graph_motif_counting",
       "79c255ee2467e436d49e3ee974b4d7149551c641",
       detail::dumato_motif_backend_compiled(),
       true,
       {"induced", "undirected", "sizes_3_4", "single_gpu"}},
  };
}

}  // namespace graphmine
