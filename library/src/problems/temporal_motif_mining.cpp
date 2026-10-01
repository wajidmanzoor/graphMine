#include "graphmine/problems/temporal_motif_mining.hpp"

#include <algorithm>
#include <chrono>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "backends/temporal_motif_backend.hpp"

namespace graphmine {
namespace {

struct PreparedEvent {
  VertexIndex source = 0;
  VertexIndex target = 0;
  std::int64_t timestamp = 0;
  std::size_t original_index = 0;
};

struct PreparedTemporalGraph {
  detail::TemporalMotifBackendInput backend;
  std::vector<PreparedEvent> events;
};

TemporalMotifBackend selected_backend(const TemporalMotifOptions& options) {
  if (options.backend != TemporalMotifBackend::automatic) {
    return options.backend;
  }
  if (detail::everest_backend_compiled()) {
    return TemporalMotifBackend::everest;
  }
  if (detail::mayura_backend_compiled()) {
    return TemporalMotifBackend::mayura;
  }
  return TemporalMotifBackend::everest;
}

bool backend_compiled(TemporalMotifBackend backend) {
  switch (backend) {
    case TemporalMotifBackend::everest:
      return detail::everest_backend_compiled();
    case TemporalMotifBackend::mayura:
      return detail::mayura_backend_compiled();
    case TemporalMotifBackend::automatic:
      break;
  }
  return false;
}

Provenance provenance_for(TemporalMotifBackend backend) {
  switch (backend) {
    case TemporalMotifBackend::everest:
      return {"temporal_motif_mining",
              "everest",
              "Everest artifact",
              "ef530d",
              "validated query-generated DYN CUDA search kernel + canonical "
              "temporal graph adapter"};
    case TemporalMotifBackend::mayura:
      return {"temporal_motif_mining",
              "mayura",
              "Mayura artifact",
              "8e4276",
              "validated query-generated DYN CUDA co-mining kernel + "
              "canonical temporal graph adapter"};
    case TemporalMotifBackend::automatic:
      break;
  }
  return {};
}

Status validate(const Graph& graph, const TemporalMotifOptions& options,
                TemporalMotifBackend backend) {
  if (!graph.directed()) {
    return {StatusCode::unsupported,
            "temporal motif mining requires a directed canonical graph"};
  }
  if (options.pattern != TemporalMotifPattern::feed_forward_triangle) {
    return {StatusCode::unsupported,
            "the validated kernels only support feed_forward_triangle"};
  }
  if (options.max_time_span < 0 ||
      options.max_time_span > std::numeric_limits<int>::max()) {
    return {StatusCode::invalid_argument,
            "max_time_span must fit a non-negative signed 32-bit integer"};
  }
  if (options.execution.device_ids.empty()) {
    return {StatusCode::invalid_argument,
            "at least one CUDA device id must be provided"};
  }
  if (graph.vertex_count() >
          static_cast<std::size_t>(std::numeric_limits<int>::max()) ||
      graph.edge_count() >
          static_cast<std::size_t>(std::numeric_limits<int>::max())) {
    return {StatusCode::unsupported,
            "Everest and Mayura use signed 32-bit graph indices"};
  }
  for (const auto& edge : graph.canonical().edges) {
    if (!edge.timestamp.has_value()) {
      return {StatusCode::invalid_argument,
              "every temporal edge must have a timestamp"};
    }
    if (!std::holds_alternative<std::int64_t>(*edge.timestamp)) {
      return {StatusCode::unsupported,
              "Everest and Mayura require integer edge timestamps"};
    }
  }
  if (!backend_compiled(backend) && graph.edge_count() != 0) {
    return {StatusCode::backend_unavailable,
            std::string("the ") + to_string(backend) +
                " backend is not compiled in this build"};
  }
  return Status::success();
}

Status prepare(const Graph& graph, const TemporalMotifOptions& options,
               PreparedTemporalGraph& prepared) {
  prepared.events.reserve(graph.edge_count());
  const auto& canonical = graph.canonical();
  for (std::size_t index = 0; index < canonical.edges.size(); ++index) {
    const auto& edge = canonical.edges[index];
    prepared.events.push_back(
        {graph.dense_index(edge.source), graph.dense_index(edge.target),
         std::get<std::int64_t>(*edge.timestamp), index});
  }
  std::stable_sort(prepared.events.begin(), prepared.events.end(),
                   [](const auto& lhs, const auto& rhs) {
                     return lhs.timestamp < rhs.timestamp;
                   });

  prepared.backend.vertex_count = static_cast<int>(graph.vertex_count());
  prepared.backend.max_time_span =
      static_cast<int>(options.max_time_span);
  prepared.backend.events.reserve(prepared.events.size());
  if (prepared.events.empty()) return Status::success();

  const auto first_timestamp = prepared.events.front().timestamp;
  for (const auto& event : prepared.events) {
    const auto relative = static_cast<__int128>(event.timestamp) -
                          static_cast<__int128>(first_timestamp);
    if (relative < 0 ||
        relative + static_cast<__int128>(options.max_time_span) >
            std::numeric_limits<int>::max()) {
      return {StatusCode::unsupported,
              "timestamp span plus max_time_span exceeds the kernels' "
              "signed 32-bit time representation"};
    }
    prepared.backend.events.push_back(
        {static_cast<int>(event.source), static_cast<int>(event.target),
         static_cast<int>(relative)});
  }
  return Status::success();
}

struct MaterializedInstances {
  std::uint64_t count = 0;
  std::vector<TemporalMotifInstance> values;
};

MaterializedInstances materialize_instances(
    const Graph& graph, const PreparedTemporalGraph& prepared,
    std::optional<std::uint64_t> limit) {
  MaterializedInstances result;
  std::vector<std::vector<std::size_t>> outgoing(graph.vertex_count());
  for (std::size_t index = 0; index < prepared.events.size(); ++index) {
    outgoing[prepared.events[index].source].push_back(index);
  }

  const auto should_store = [&]() {
    return !limit || result.values.size() < *limit;
  };
  const auto& canonical_edges = graph.canonical().edges;
  for (std::size_t first = 0; first < prepared.events.size(); ++first) {
    const auto& first_event = prepared.events[first];
    if (first_event.source == first_event.target) continue;
    const auto deadline = static_cast<__int128>(first_event.timestamp) +
                          static_cast<__int128>(
                              prepared.backend.max_time_span);

    for (const auto second : outgoing[first_event.target]) {
      if (second <= first) continue;
      const auto& second_event = prepared.events[second];
      if (static_cast<__int128>(second_event.timestamp) > deadline) break;
      const auto third_vertex = second_event.target;
      if (third_vertex == first_event.source ||
          third_vertex == first_event.target) {
        continue;
      }

      for (const auto third : outgoing[first_event.source]) {
        if (third <= second) continue;
        const auto& third_event = prepared.events[third];
        if (static_cast<__int128>(third_event.timestamp) > deadline) break;
        if (third_event.target != third_vertex) continue;

        if (result.count == std::numeric_limits<std::uint64_t>::max()) {
          throw std::overflow_error("temporal motif instance count overflow");
        }
        ++result.count;
        if (should_store()) {
          result.values.push_back(
              {{{graph.external_id(first_event.source),
                 graph.external_id(first_event.target),
                 graph.external_id(third_vertex)}},
               {{canonical_edges[first_event.original_index].id,
                 canonical_edges[second_event.original_index].id,
                 canonical_edges[third_event.original_index].id}}});
        }
      }
    }
  }
  return result;
}

}  // namespace

const char* to_string(TemporalMotifBackend backend) noexcept {
  switch (backend) {
    case TemporalMotifBackend::automatic:
      return "auto";
    case TemporalMotifBackend::everest:
      return "everest";
    case TemporalMotifBackend::mayura:
      return "mayura";
  }
  return "unknown";
}

const char* to_string(TemporalMotifPattern pattern) noexcept {
  switch (pattern) {
    case TemporalMotifPattern::feed_forward_triangle:
      return "feed-forward-triangle";
  }
  return "unknown";
}

TemporalMotifMining::TemporalMotifMining(TemporalMotifOptions options)
    : options_(std::move(options)) {}

SupportReport TemporalMotifMining::supports(const Graph& graph) const {
  const auto status = validate(graph, options_, selected_backend(options_));
  return {status.ok(), status.message()};
}

ExecutionResult<TemporalMotifOutput> TemporalMotifMining::run(
    const Graph& graph) const {
  const auto started = std::chrono::steady_clock::now();
  const auto backend = selected_backend(options_);
  auto provenance = provenance_for(backend);
  const auto validation = validate(graph, options_, backend);
  if (!validation.ok()) {
    return ExecutionResult<TemporalMotifOutput>::failure(validation,
                                                          provenance);
  }

  PreparedTemporalGraph prepared;
  const auto prepared_status = prepare(graph, options_, prepared);
  if (!prepared_status.ok()) {
    return ExecutionResult<TemporalMotifOutput>::failure(prepared_status,
                                                          provenance);
  }

  detail::TemporalMotifBackendResult backend_result;
  if (prepared.backend.events.empty()) {
    backend_result.status = Status::success();
    provenance.execution_path += " (trivial empty-event result)";
  } else if (backend == TemporalMotifBackend::everest) {
    backend_result = detail::run_everest(
        prepared.backend, options_.execution.device_ids.front());
  } else {
    backend_result = detail::run_mayura(
        prepared.backend, options_.execution.device_ids.front());
  }
  if (!backend_result.status.ok()) {
    return ExecutionResult<TemporalMotifOutput>::failure(
        backend_result.status, provenance);
  }

  const auto materialization_started = std::chrono::steady_clock::now();
  TemporalMotifOutput output;
  output.count = backend_result.count;
  if (has_output(options_.optional_outputs,
                 TemporalMotifOptionalOutput::instances)) {
    try {
      auto instances =
          materialize_instances(graph, prepared, options_.result_limit);
      if (instances.count != output.count) {
        return ExecutionResult<TemporalMotifOutput>::failure(
            {StatusCode::correctness_mismatch,
             std::string(to_string(backend)) + " returned " +
                 std::to_string(output.count) +
                 " matches, but facade materialization found " +
                 std::to_string(instances.count)},
            provenance);
      }
      output.instances_complete = instances.values.size() == output.count;
      output.instances = std::move(instances.values);
    } catch (const std::exception& error) {
      return ExecutionResult<TemporalMotifOutput>::failure(
          {StatusCode::execution_failed,
           std::string("temporal instance materialization failed: ") +
               error.what()},
          provenance);
    }
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
  return ExecutionResult<TemporalMotifOutput>::success(
      std::move(output), std::move(provenance), statistics);
}

std::vector<BackendInfo> TemporalMotifMining::backends() {
  return {
      {"everest",
       "Everest",
       "temporal_motif_mining",
       "ef530d",
       detail::everest_backend_compiled(),
       true,
       {"directed", "parallel_events", "integer_timestamps",
        "feed_forward_triangle", "single_gpu"}},
      {"mayura",
       "Mayura",
       "temporal_motif_mining",
       "8e4276",
       detail::mayura_backend_compiled(),
       true,
       {"directed", "parallel_events", "integer_timestamps",
        "feed_forward_triangle", "single_gpu"}},
  };
}

}  // namespace graphmine
