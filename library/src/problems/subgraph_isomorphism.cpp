#include "graphmine/problems/subgraph_isomorphism.hpp"

#include <algorithm>
#include <chrono>
#include <climits>
#include <limits>
#include <map>
#include <queue>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "backends/subgraph_isomorphism_backend.hpp"

namespace graphmine {
namespace {

struct EncodedLabels {
  std::vector<int> data;
  std::vector<int> query;
};

EncodedLabels encode_labels(const Graph& data, const Graph& query,
                            bool respect_labels) {
  EncodedLabels output;
  output.data.resize(data.vertex_count(), 0);
  output.query.resize(query.vertex_count(), 0);
  if (!respect_labels) {
    return output;
  }

  std::map<std::string, int> dictionary;
  const auto key = [](const VertexRecord& vertex) {
    return vertex.label ? std::string("label:") + *vertex.label
                        : std::string("missing:");
  };
  const auto encode = [&](const Graph& graph, std::vector<int>& labels) {
    for (std::size_t vertex = 0; vertex < graph.vertex_count(); ++vertex) {
      const auto label_key = key(graph.canonical().vertices[vertex]);
      auto [it, inserted] =
          dictionary.emplace(label_key, static_cast<int>(dictionary.size()));
      labels[vertex] = it->second;
    }
  };
  encode(data, output.data);
  encode(query, output.query);
  return output;
}

bool adjacent(const CsrGraph& graph, VertexIndex lhs, VertexIndex rhs) {
  const auto begin = graph.neighbors.begin() +
                     static_cast<std::ptrdiff_t>(graph.offsets[lhs]);
  const auto end = graph.neighbors.begin() +
                   static_cast<std::ptrdiff_t>(graph.offsets[lhs + 1]);
  return std::binary_search(begin, end, rhs);
}

bool connected(const CsrGraph& graph) {
  if (graph.vertex_count() <= 1) {
    return true;
  }
  std::vector<bool> visited(graph.vertex_count(), false);
  std::queue<VertexIndex> queue;
  queue.push(0);
  visited[0] = true;
  std::size_t count = 1;
  while (!queue.empty()) {
    const auto vertex = queue.front();
    queue.pop();
    for (auto edge = graph.offsets[vertex]; edge < graph.offsets[vertex + 1];
         ++edge) {
      const auto neighbor = graph.neighbors[edge];
      if (!visited[neighbor]) {
        visited[neighbor] = true;
        ++count;
        queue.push(neighbor);
      }
    }
  }
  return count == graph.vertex_count();
}

struct EmbeddingCollector {
  const CsrGraph* data = nullptr;
  const CsrGraph* query = nullptr;
  const std::vector<int>* data_labels = nullptr;
  const std::vector<int>* query_labels = nullptr;
  std::optional<std::uint64_t> limit;
  std::vector<VertexIndex> order;
  std::vector<VertexIndex> mapping;
  std::vector<bool> used;
  std::vector<std::vector<VertexIndex>> embeddings;
  bool stopped = false;
};

void collect_embeddings(std::size_t depth, EmbeddingCollector& state) {
  if (state.stopped) {
    return;
  }
  if (depth == state.order.size()) {
    state.embeddings.push_back(state.mapping);
    if (state.limit && state.embeddings.size() >= *state.limit) {
      state.stopped = true;
    }
    return;
  }

  const auto query_vertex = state.order[depth];
  const auto query_degree = state.query->offsets[query_vertex + 1] -
                            state.query->offsets[query_vertex];
  for (VertexIndex data_vertex = 0;
       data_vertex < state.data->vertex_count(); ++data_vertex) {
    if (state.used[data_vertex] ||
        (*state.data_labels)[data_vertex] !=
            (*state.query_labels)[query_vertex] ||
        state.data->offsets[data_vertex + 1] -
                state.data->offsets[data_vertex] <
            query_degree) {
      continue;
    }
    bool compatible = true;
    for (VertexIndex other = 0; other < state.query->vertex_count(); ++other) {
      if (state.mapping[other] != std::numeric_limits<VertexIndex>::max() &&
          adjacent(*state.query, query_vertex, other) &&
          !adjacent(*state.data, data_vertex, state.mapping[other])) {
        compatible = false;
        break;
      }
    }
    if (!compatible) {
      continue;
    }
    state.mapping[query_vertex] = data_vertex;
    state.used[data_vertex] = true;
    collect_embeddings(depth + 1, state);
    state.used[data_vertex] = false;
    state.mapping[query_vertex] = std::numeric_limits<VertexIndex>::max();
    if (state.stopped) {
      return;
    }
  }
}

EmbeddingCollector materialize_embeddings(
    const CsrGraph& data, const CsrGraph& query,
    const std::vector<int>& data_labels,
    const std::vector<int>& query_labels,
    std::optional<std::uint64_t> limit) {
  EmbeddingCollector state;
  state.data = &data;
  state.query = &query;
  state.data_labels = &data_labels;
  state.query_labels = &query_labels;
  state.limit = limit;
  state.order.resize(query.vertex_count());
  for (VertexIndex vertex = 0; vertex < query.vertex_count(); ++vertex) {
    state.order[vertex] = vertex;
  }
  std::stable_sort(state.order.begin(), state.order.end(),
                   [&](VertexIndex lhs, VertexIndex rhs) {
                     const auto lhs_degree =
                         query.offsets[lhs + 1] - query.offsets[lhs];
                     const auto rhs_degree =
                         query.offsets[rhs + 1] - query.offsets[rhs];
                     if (lhs_degree != rhs_degree) {
                       return lhs_degree > rhs_degree;
                     }
                     return lhs < rhs;
                   });
  state.mapping.assign(query.vertex_count(),
                       std::numeric_limits<VertexIndex>::max());
  state.used.assign(data.vertex_count(), false);
  collect_embeddings(0, state);
  return state;
}

Provenance gmatch_provenance() {
  return {"subgraph_isomorphism",
          "gmatch",
          "gMatch artifact",
          "4628e73dbcb564dba367b3f042595e71f98c9046",
          "original gMatch GPU count + optional exact embedding materializer"};
}

}  // namespace

const char* to_string(SubgraphIsomorphismBackend backend) noexcept {
  switch (backend) {
    case SubgraphIsomorphismBackend::automatic:
      return "auto";
    case SubgraphIsomorphismBackend::gmatch:
      return "gmatch";
  }
  return "unknown";
}

SubgraphIsomorphism::SubgraphIsomorphism(
    SubgraphIsomorphismOptions options)
    : options_(std::move(options)) {}

SupportReport SubgraphIsomorphism::supports(
    const Graph& data_graph, const Graph& query_graph) const {
  if ((data_graph.directed() || query_graph.directed()) &&
      !options_.allow_directed_projection) {
    return {false,
            "directed input requires allow_directed_projection=true"};
  }
  if (query_graph.vertex_count() > 16) {
    return {false, "the validated gMatch bitmap path supports at most 16 query vertices"};
  }
  if (data_graph.vertex_count() > SHRT_MAX) {
    return {false,
            "the validated gMatch short-candidate path supports at most "
            "32767 data vertices"};
  }
  if (data_graph.edge_count() > static_cast<std::size_t>(INT_MAX) ||
      query_graph.edge_count() > static_cast<std::size_t>(INT_MAX)) {
    return {false, "gMatch uses signed 32-bit graph sizes"};
  }
  if (options_.initial_match_capacity == 0 ||
      options_.initial_match_capacity > static_cast<std::size_t>(INT_MAX)) {
    return {false, "initial_match_capacity must fit a positive int"};
  }
  if (options_.result_limit && *options_.result_limit == 0) {
    return {false, "result_limit must be null or at least one"};
  }
  if (options_.result_limit &&
      !has_output(options_.optional_outputs,
                  SubgraphIsomorphismOptionalOutput::embeddings)) {
    return {false, "result_limit requires the embeddings output flag"};
  }
  if (options_.execution.device_ids.empty()) {
    return {false, "at least one CUDA device id must be provided"};
  }
  try {
    const auto query = query_graph.simple_undirected(
        {options_.allow_directed_projection});
    if (!connected(query.csr)) {
      return {false, "the validated gMatch path requires a connected query"};
    }
  } catch (const std::exception& error) {
    return {false, error.what()};
  }
  if (!detail::gmatch_backend_compiled() &&
      query_graph.vertex_count() > 1 &&
      query_graph.vertex_count() <= data_graph.vertex_count()) {
    return {false, "the gMatch backend is not compiled in this build"};
  }
  return {true, {}};
}

ExecutionResult<SubgraphIsomorphismOutput> SubgraphIsomorphism::run(
    const Graph& data_graph, const Graph& query_graph) const {
  const auto started = std::chrono::steady_clock::now();
  auto provenance = gmatch_provenance();
  const auto support = supports(data_graph, query_graph);
  if (!support.supported) {
    return ExecutionResult<SubgraphIsomorphismOutput>::failure(
        {StatusCode::unsupported, support.reason}, provenance);
  }

  UndirectedGraphView data;
  UndirectedGraphView query;
  try {
    data = data_graph.simple_undirected(
        {options_.allow_directed_projection});
    query = query_graph.simple_undirected(
        {options_.allow_directed_projection});
  } catch (const std::exception& error) {
    return ExecutionResult<SubgraphIsomorphismOutput>::failure(
        {StatusCode::invalid_argument, error.what()}, provenance);
  }
  const auto labels = encode_labels(data_graph, query_graph,
                                    options_.respect_vertex_labels);

  std::vector<std::string> warnings;
  if (data.normalization.directed_projection_applied ||
      query.normalization.directed_projection_applied) {
    warnings.emplace_back("directed input was projected to undirected graphs");
  }
  if (data.normalization.self_loops_removed > 0 ||
      query.normalization.self_loops_removed > 0) {
    warnings.emplace_back("self-loops were removed during normalization");
  }
  if (data.normalization.parallel_edges_collapsed > 0 ||
      query.normalization.parallel_edges_collapsed > 0) {
    warnings.emplace_back("parallel edges were collapsed during normalization");
  }

  const auto backend = detail::run_gmatch(
      data.csr, labels.data, query.csr, labels.query,
      options_.initial_match_capacity, options_.execution.device_ids.front());
  if (!backend.status.ok()) {
    return ExecutionResult<SubgraphIsomorphismOutput>::failure(
        backend.status, provenance, std::move(warnings));
  }

  SubgraphIsomorphismOutput output;
  output.count = backend.count;
  const auto materialization_started = std::chrono::steady_clock::now();
  if (has_output(options_.optional_outputs,
                 SubgraphIsomorphismOptionalOutput::embeddings)) {
    const auto collected = materialize_embeddings(
        data.csr, query.csr, labels.data, labels.query, options_.result_limit);
    const bool complete = !collected.stopped;
    if (complete && collected.embeddings.size() != backend.count) {
      return ExecutionResult<SubgraphIsomorphismOutput>::failure(
          {StatusCode::correctness_mismatch,
           "gMatch count disagreed with the exact embedding materializer"},
          provenance, std::move(warnings));
    }
    output.embeddings.emplace();
    output.embeddings->reserve(collected.embeddings.size());
    for (const auto& internal : collected.embeddings) {
      SubgraphEmbedding embedding;
      embedding.reserve(internal.size());
      for (VertexIndex query_vertex = 0;
           query_vertex < internal.size(); ++query_vertex) {
        embedding.push_back({query_graph.external_id(query_vertex),
                             data_graph.external_id(internal[query_vertex])});
      }
      output.embeddings->push_back(std::move(embedding));
    }
    output.embeddings_complete =
        output.embeddings->size() == output.count;
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
  return ExecutionResult<SubgraphIsomorphismOutput>::success(
      std::move(output), std::move(provenance), statistics,
      std::move(warnings));
}

std::vector<BackendInfo> SubgraphIsomorphism::backends() {
  return {{"gmatch",
           "gMatch",
           "subgraph_isomorphism",
           "4628e73dbcb564dba367b3f042595e71f98c9046",
           detail::gmatch_backend_compiled(),
           true,
           {"labeled", "non_induced", "exact_count", "single_gpu"}}};
}

}  // namespace graphmine
