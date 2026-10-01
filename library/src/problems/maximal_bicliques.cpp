#include "graphmine/problems/maximal_bicliques.hpp"

#include <algorithm>
#include <chrono>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "backends/maximal_biclique_backend.hpp"

namespace graphmine {
namespace {

struct PartitionView {
  std::vector<bool> is_left;
  std::vector<VertexIndex> left;
  std::vector<VertexIndex> right;
};

PartitionView make_partitions(const Graph& graph,
                              const std::vector<ExternalId>& left_ids) {
  PartitionView partition;
  partition.is_left.assign(graph.vertex_count(), false);
  partition.left.reserve(left_ids.size());
  for (const auto& id : left_ids) {
    const auto vertex = graph.dense_index(id);
    if (partition.is_left[vertex]) {
      throw std::invalid_argument(
          "left_partition contains a duplicate vertex: " + id.to_string());
    }
    partition.is_left[vertex] = true;
    partition.left.push_back(vertex);
  }
  std::sort(partition.left.begin(), partition.left.end());
  for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    if (!partition.is_left[vertex]) {
      partition.right.push_back(vertex);
    }
  }
  if (partition.left.empty() || partition.right.empty()) {
    throw std::invalid_argument(
        "left_partition and its right-partition complement must both be "
        "non-empty");
  }
  return partition;
}

void validate_bipartite_edges(const Graph& graph,
                              const PartitionView& partition) {
  for (const auto& edge : graph.canonical().edges) {
    const auto source = graph.dense_index(edge.source);
    const auto target = graph.dense_index(edge.target);
    if (source == target ||
        partition.is_left[source] == partition.is_left[target]) {
      throw std::invalid_argument(
          "every edge must connect the declared left partition to its "
          "right-partition complement");
    }
  }
}

detail::BipartiteCsrGraph make_backend_graph(
    const CsrGraph& graph, const PartitionView& partition) {
  detail::BipartiteCsrGraph output;
  output.left_vertex_count =
      static_cast<std::uint32_t>(partition.left.size());
  output.right_vertex_count =
      static_cast<std::uint32_t>(partition.right.size());
  output.left_offsets.reserve(partition.left.size() + 1);
  output.left_offsets.push_back(0);

  std::vector<std::uint32_t> right_local(
      graph.vertex_count(), std::numeric_limits<std::uint32_t>::max());
  for (std::uint32_t local = 0; local < partition.right.size(); ++local) {
    right_local[partition.right[local]] = local;
  }
  for (const auto left : partition.left) {
    for (auto offset = graph.offsets[left]; offset < graph.offsets[left + 1];
         ++offset) {
      output.right_neighbors.push_back(right_local[graph.neighbors[offset]]);
    }
    output.left_offsets.push_back(output.right_neighbors.size());
  }
  return output;
}

CsrGraph make_completed_graph(const CsrGraph& graph,
                              const PartitionView& partition) {
  CsrGraph completed;
  completed.offsets.reserve(graph.vertex_count() + 1);
  completed.offsets.push_back(0);
  for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    const auto& same_side = partition.is_left[vertex] ? partition.left
                                                      : partition.right;
    for (const auto neighbor : same_side) {
      if (neighbor != vertex) {
        completed.neighbors.push_back(neighbor);
      }
    }
    completed.neighbors.insert(
        completed.neighbors.end(),
        graph.neighbors.begin() +
            static_cast<std::ptrdiff_t>(graph.offsets[vertex]),
        graph.neighbors.begin() +
            static_cast<std::ptrdiff_t>(graph.offsets[vertex + 1]));
    std::sort(completed.neighbors.begin() +
                  static_cast<std::ptrdiff_t>(completed.offsets.back()),
              completed.neighbors.end());
    completed.offsets.push_back(completed.neighbors.size());
  }
  return completed;
}

using InternalBiclique =
    std::pair<std::vector<VertexIndex>, std::vector<VertexIndex>>;

struct CollectionState {
  const PartitionView* partition = nullptr;
  std::size_t minimum_left_size = 1;
  std::size_t minimum_right_size = 1;
  std::optional<std::uint64_t> result_limit;
  bool must_finish = false;
  bool stopped_early = false;
  std::uint64_t qualifying_count = 0;
  std::vector<InternalBiclique> bicliques;
};

bool adjacent(const CsrGraph& graph, VertexIndex lhs, VertexIndex rhs) {
  const auto begin = graph.neighbors.begin() +
                     static_cast<std::ptrdiff_t>(graph.offsets[lhs]);
  const auto end = graph.neighbors.begin() +
                   static_cast<std::ptrdiff_t>(graph.offsets[lhs + 1]);
  return std::binary_search(begin, end, rhs);
}

std::vector<VertexIndex> intersect_neighbors(
    const CsrGraph& graph, const std::vector<VertexIndex>& vertices,
    VertexIndex pivot) {
  std::vector<VertexIndex> output;
  const auto begin = graph.neighbors.begin() +
                     static_cast<std::ptrdiff_t>(graph.offsets[pivot]);
  const auto end = graph.neighbors.begin() +
                   static_cast<std::ptrdiff_t>(graph.offsets[pivot + 1]);
  std::set_intersection(vertices.begin(), vertices.end(), begin, end,
                        std::back_inserter(output));
  return output;
}

VertexIndex choose_pivot(const CsrGraph& graph,
                         const std::vector<VertexIndex>& possible,
                         const std::vector<VertexIndex>& excluded) {
  VertexIndex best = possible.empty() ? excluded.front() : possible.front();
  std::size_t best_score = 0;
  const auto consider = [&](VertexIndex candidate) {
    const auto begin = graph.neighbors.begin() +
                       static_cast<std::ptrdiff_t>(graph.offsets[candidate]);
    const auto end = graph.neighbors.begin() +
                     static_cast<std::ptrdiff_t>(graph.offsets[candidate + 1]);
    std::size_t score = 0;
    auto possible_it = possible.begin();
    auto neighbor_it = begin;
    while (possible_it != possible.end() && neighbor_it != end) {
      if (*possible_it < *neighbor_it) {
        ++possible_it;
      } else if (*neighbor_it < *possible_it) {
        ++neighbor_it;
      } else {
        ++score;
        ++possible_it;
        ++neighbor_it;
      }
    }
    return score;
  };
  for (const auto candidate : possible) {
    const auto score = consider(candidate);
    if (score > best_score) {
      best = candidate;
      best_score = score;
    }
  }
  for (const auto candidate : excluded) {
    const auto score = consider(candidate);
    if (score > best_score) {
      best = candidate;
      best_score = score;
    }
  }
  return best;
}

void collect_bicliques(const CsrGraph& graph,
                       std::vector<VertexIndex>& current,
                       std::vector<VertexIndex> possible,
                       std::vector<VertexIndex> excluded,
                       CollectionState& state) {
  if (state.stopped_early) {
    return;
  }
  if (possible.empty() && excluded.empty()) {
    InternalBiclique biclique;
    for (const auto vertex : current) {
      (state.partition->is_left[vertex] ? biclique.first : biclique.second)
          .push_back(vertex);
    }
    std::sort(biclique.first.begin(), biclique.first.end());
    std::sort(biclique.second.begin(), biclique.second.end());
    if (biclique.first.size() < state.minimum_left_size ||
        biclique.second.size() < state.minimum_right_size) {
      return;
    }
    if (state.qualifying_count == std::numeric_limits<std::uint64_t>::max()) {
      throw std::overflow_error("maximal-biclique count exceeds uint64_t");
    }
    ++state.qualifying_count;
    if (!state.result_limit ||
        state.bicliques.size() < *state.result_limit) {
      state.bicliques.push_back(std::move(biclique));
    }
    if (state.result_limit &&
        state.bicliques.size() >= *state.result_limit &&
        !state.must_finish) {
      state.stopped_early = true;
    }
    return;
  }

  const auto pivot = choose_pivot(graph, possible, excluded);
  std::vector<VertexIndex> candidates;
  for (const auto vertex : possible) {
    if (!adjacent(graph, pivot, vertex)) {
      candidates.push_back(vertex);
    }
  }
  for (const auto vertex : candidates) {
    if (state.stopped_early) {
      return;
    }
    const auto present =
        std::lower_bound(possible.begin(), possible.end(), vertex);
    if (present == possible.end() || *present != vertex) {
      continue;
    }
    current.push_back(vertex);
    auto next_possible = intersect_neighbors(graph, possible, vertex);
    auto next_excluded = intersect_neighbors(graph, excluded, vertex);
    collect_bicliques(graph, current, std::move(next_possible),
                      std::move(next_excluded), state);
    current.pop_back();
    possible.erase(std::lower_bound(possible.begin(), possible.end(), vertex));
    excluded.insert(std::lower_bound(excluded.begin(), excluded.end(), vertex),
                    vertex);
  }
}

CollectionState materialize_bicliques(const CsrGraph& bipartite_graph,
                                      const PartitionView& partition,
                                      const MaximalBicliqueOptions& options) {
  CollectionState state;
  state.partition = &partition;
  state.minimum_left_size = options.minimum_left_size;
  state.minimum_right_size = options.minimum_right_size;
  state.result_limit = options.result_limit;
  state.must_finish =
      has_output(options.optional_outputs,
                 MaximalBicliqueOptionalOutput::total_count) &&
      (options.minimum_left_size != 1 || options.minimum_right_size != 1);

  auto completed = make_completed_graph(bipartite_graph, partition);
  std::vector<VertexIndex> possible(completed.vertex_count());
  std::iota(possible.begin(), possible.end(), VertexIndex{0});
  std::vector<VertexIndex> current;
  collect_bicliques(completed, current, std::move(possible), {}, state);
  std::sort(state.bicliques.begin(), state.bicliques.end(),
            [](const auto& lhs, const auto& rhs) {
              if (lhs.first.size() != rhs.first.size()) {
                return lhs.first.size() < rhs.first.size();
              }
              if (lhs.first != rhs.first) {
                return lhs.first < rhs.first;
              }
              if (lhs.second.size() != rhs.second.size()) {
                return lhs.second.size() < rhs.second.size();
              }
              return lhs.second < rhs.second;
            });
  return state;
}

Provenance cumbe_provenance() {
  return {"maximal_biclique_enumeration",
          "cumbe",
          "cuMBE artifact",
          "2fff8005b2f74e5683d915f9cd817409f6499bcf",
          "original cuMBE GPU count kernel + exact common set materializer"};
}

}  // namespace

const char* to_string(MaximalBicliqueBackend backend) noexcept {
  switch (backend) {
    case MaximalBicliqueBackend::automatic:
      return "auto";
    case MaximalBicliqueBackend::cumbe:
      return "cumbe";
  }
  return "unknown";
}

MaximalBicliques::MaximalBicliques(MaximalBicliqueOptions options)
    : options_(std::move(options)) {}

SupportReport MaximalBicliques::supports(const Graph& graph) const {
  if (options_.minimum_left_size == 0 || options_.minimum_right_size == 0) {
    return {false, "minimum partition sizes must both be at least one"};
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
  if (graph.vertex_count() >
      static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max())) {
    return {false, "cuMBE uses 32-bit vertex indices"};
  }
  try {
    const auto partition = make_partitions(graph, options_.left_partition);
    validate_bipartite_edges(graph, partition);
  } catch (const std::exception& error) {
    return {false, error.what()};
  }
  if (!detail::cumbe_backend_compiled() && graph.edge_count() > 0) {
    return {false, "the cuMBE backend is not compiled in this build"};
  }
  return {true, {}};
}

ExecutionResult<MaximalBicliqueOutput> MaximalBicliques::run(
    const Graph& graph) const {
  const auto started = std::chrono::steady_clock::now();
  auto provenance = cumbe_provenance();
  const auto support = supports(graph);
  if (!support.supported) {
    return ExecutionResult<MaximalBicliqueOutput>::failure(
        {StatusCode::unsupported, support.reason}, provenance);
  }

  UndirectedGraphView normalized;
  PartitionView partition;
  try {
    normalized = graph.simple_undirected(
        {options_.allow_directed_projection});
    partition = make_partitions(graph, options_.left_partition);
  } catch (const std::exception& error) {
    return ExecutionResult<MaximalBicliqueOutput>::failure(
        {StatusCode::invalid_argument, error.what()}, provenance);
  }

  std::vector<std::string> warnings;
  if (normalized.normalization.directed_projection_applied) {
    warnings.emplace_back("directed input was projected to an undirected graph");
  }
  if (normalized.normalization.parallel_edges_collapsed > 0) {
    warnings.emplace_back("parallel edges were collapsed during normalization");
  }

  const auto backend_graph = make_backend_graph(normalized.csr, partition);
  const auto backend = backend_graph.right_neighbors.empty()
                           ? detail::MaximalBicliqueBackendResult{
                                 Status::success(), 0, 0.0}
                           : detail::run_cumbe(
                                 backend_graph,
                                 options_.execution.device_ids.front());
  if (!backend.status.ok()) {
    return ExecutionResult<MaximalBicliqueOutput>::failure(
        backend.status, provenance, std::move(warnings));
  }

  const auto materialization_started = std::chrono::steady_clock::now();
  CollectionState collected;
  try {
    collected = materialize_bicliques(normalized.csr, partition, options_);
  } catch (const std::exception& error) {
    return ExecutionResult<MaximalBicliqueOutput>::failure(
        {StatusCode::execution_failed, error.what()}, provenance,
        std::move(warnings));
  }
  const auto materialization_finished = std::chrono::steady_clock::now();

  const bool unfiltered = options_.minimum_left_size == 1 &&
                          options_.minimum_right_size == 1;
  const bool collector_finished = !collected.stopped_early;
  if (unfiltered && collector_finished &&
      collected.qualifying_count != backend.count) {
    return ExecutionResult<MaximalBicliqueOutput>::failure(
        {StatusCode::correctness_mismatch,
         "cuMBE count disagreed with the exact output materializer"},
        provenance, std::move(warnings));
  }

  MaximalBicliqueOutput output;
  output.bicliques.reserve(collected.bicliques.size());
  for (const auto& internal : collected.bicliques) {
    MaximalBiclique biclique;
    for (const auto vertex : internal.first) {
      biclique.left.push_back(graph.external_id(vertex));
    }
    for (const auto vertex : internal.second) {
      biclique.right.push_back(graph.external_id(vertex));
    }
    output.bicliques.push_back(std::move(biclique));
  }
  output.returned_count = output.bicliques.size();

  std::uint64_t known_total = collected.qualifying_count;
  bool total_known = collector_finished;
  if (unfiltered) {
    known_total = backend.count;
    total_known = true;
  }
  output.complete = total_known && output.returned_count == known_total;
  if (has_output(options_.optional_outputs,
                 MaximalBicliqueOptionalOutput::total_count)) {
    output.total_count = known_total;
  }
  warnings.emplace_back(
      "cuMBE supplies the validated GPU total; biclique sets are materialized "
      "by GraphMine's exact completed-graph collector");

  const auto finished = std::chrono::steady_clock::now();
  ExecutionStatistics statistics;
  statistics.backend_ms = backend.elapsed_ms;
  statistics.output_materialization_ms =
      std::chrono::duration<double, std::milli>(materialization_finished -
                                                materialization_started)
          .count();
  statistics.end_to_end_ms =
      std::chrono::duration<double, std::milli>(finished - started).count();
  return ExecutionResult<MaximalBicliqueOutput>::success(
      std::move(output), std::move(provenance), statistics,
      std::move(warnings));
}

std::vector<BackendInfo> MaximalBicliques::backends() {
  return {{"cumbe",
           "cuMBE",
           "maximal_biclique_enumeration",
           "2fff8005b2f74e5683d915f9cd817409f6499bcf",
           detail::cumbe_backend_compiled(),
           true,
           {"exact_count", "bipartite", "single_gpu"}}};
}

}  // namespace graphmine
