#include "backends/betweenness_centrality_backend.hpp"

#include <chrono>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

#include <cuda_runtime.h>

extern "C" int graphmine_turbobc_compute(
    int* row_indices, int* column_offsets, int* levels, float* path_counts,
    float* scores, int source_count, int first_source, int nonzeros,
    int vertex_count, int repetition_count);

namespace graphmine::detail {
namespace {

std::mutex turbobc_mutex;

Status cuda_status(cudaError_t code, const char* operation) {
  if (code == cudaSuccess) {
    return Status::success();
  }
  return {StatusCode::execution_failed,
          std::string(operation) + ": " + cudaGetErrorString(code)};
}

}  // namespace

bool turbobc_backend_compiled() noexcept { return true; }

BetweennessCentralityBackendResult run_turbobc(const CsrGraph& graph,
                                                int device_id) {
  if (graph.vertex_count() == 0) {
    return {Status::success(), {}, 0.0};
  }
  if (graph.vertex_count() >
          static_cast<std::size_t>(std::numeric_limits<int>::max()) ||
      graph.neighbors.size() >
          static_cast<std::size_t>(std::numeric_limits<int>::max())) {
    return {{StatusCode::unsupported,
             "TurboBC uses signed 32-bit CSR indices"},
            {}, 0.0};
  }

  try {
    std::vector<int> offsets;
    offsets.reserve(graph.offsets.size());
    for (const auto offset : graph.offsets) {
      if (offset > static_cast<std::uint64_t>(
                       std::numeric_limits<int>::max())) {
        return {{StatusCode::unsupported,
                 "TurboBC uses signed 32-bit CSR offsets"},
                {}, 0.0};
      }
      offsets.push_back(static_cast<int>(offset));
    }
    std::vector<int> neighbors;
    neighbors.reserve(graph.neighbors.size());
    for (const auto neighbor : graph.neighbors) {
      neighbors.push_back(static_cast<int>(neighbor));
    }

    const auto vertex_count = static_cast<int>(graph.vertex_count());
    std::vector<int> levels(graph.vertex_count(), 0);
    std::vector<float> path_counts(graph.vertex_count(), 0.0F);
    std::vector<float> raw_scores(graph.vertex_count(), 0.0F);

    std::lock_guard<std::mutex> lock(turbobc_mutex);
    auto status = cuda_status(cudaSetDevice(device_id),
                              "selecting the TurboBC CUDA device");
    if (!status.ok()) {
      return {status, {}, 0.0};
    }

    const auto started = std::chrono::steady_clock::now();
    const int return_code = graphmine_turbobc_compute(
        neighbors.data(), offsets.data(), levels.data(), path_counts.data(),
        raw_scores.data(), vertex_count, 0,
        static_cast<int>(neighbors.size()), vertex_count, 1);
    status = cuda_status(cudaGetLastError(), "executing TurboBC");
    const auto finished = std::chrono::steady_clock::now();
    if (return_code != 0) {
      return {{StatusCode::execution_failed,
               "TurboBC returned error code " +
                   std::to_string(return_code)},
              {}, 0.0};
    }
    if (!status.ok()) {
      return {status, {}, 0.0};
    }

    std::vector<double> scores;
    scores.reserve(raw_scores.size());
    for (const auto score : raw_scores) {
      scores.push_back(static_cast<double>(score));
    }
    return {Status::success(), std::move(scores),
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("TurboBC execution failed: ") + error.what()},
            {}, 0.0};
  }
}

}  // namespace graphmine::detail
