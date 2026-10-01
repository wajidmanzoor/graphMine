#include "backends/community_detection_backend.hpp"

#include <chrono>
#include <limits>
#include <mutex>
#include <numeric>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "leiden.h"
#include "struct.h"

// Declared by the small GRAPHMINE_LIBRARY hook in the original artifact.
std::vector<int> graphmine_gleiden_original_to_current;

namespace graphmine::detail {
namespace {

std::mutex gleiden_mutex;

Status cuda_status(cudaError_t code, const char* operation) {
  if (code == cudaSuccess) return Status::success();
  return {StatusCode::execution_failed,
          std::string(operation) + ": " + cudaGetErrorString(code)};
}

}  // namespace

bool gleiden_backend_compiled() noexcept { return true; }

CommunityDetectionBackendResult run_gleiden(const CsrGraph& input,
                                             int device_id) {
  if (input.vertex_count() == 0) {
    return {Status::success(), {}, 0.0, 0.0};
  }
  if (input.vertex_count() >
          static_cast<std::size_t>(std::numeric_limits<int>::max()) ||
      input.neighbors.size() >
          static_cast<std::size_t>(std::numeric_limits<int>::max())) {
    return {{StatusCode::unsupported,
             "gLeiden uses signed 32-bit graph indices"},
            {}, std::nullopt, 0.0};
  }

  int device_count = 0;
  if (cudaGetDeviceCount(&device_count) != cudaSuccess || device_id < 0 ||
      device_id >= device_count) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for gLeiden"},
            {}, std::nullopt, 0.0};
  }

  std::lock_guard<std::mutex> lock(gleiden_mutex);
  auto status = cuda_status(cudaSetDevice(device_id),
                            "selecting the gLeiden CUDA device");
  if (!status.ok()) return {status, {}, std::nullopt, 0.0};

  graph upstream{};
  Leiden_Partition partition{};
  try {
    const auto vertices = static_cast<int>(input.vertex_count());
    const auto arcs = static_cast<int>(input.neighbors.size());
    upstream.nodes = vertices;
    upstream.ed = arcs;
    upstream.out_col = new int[static_cast<std::size_t>(vertices) + 1U];
    upstream.in_col = new int[static_cast<std::size_t>(vertices) + 1U];
    upstream.child_out = new int[static_cast<std::size_t>(arcs)];
    upstream.child_in = new int[static_cast<std::size_t>(arcs)];
    upstream.wts_out = new double[static_cast<std::size_t>(arcs)];
    upstream.wts_in = new double[static_cast<std::size_t>(arcs)];

    for (int vertex = 0; vertex <= vertices; ++vertex) {
      upstream.out_col[vertex] = static_cast<int>(input.offsets[vertex]);
      upstream.in_col[vertex] = static_cast<int>(input.offsets[vertex]);
    }
    for (int edge = 0; edge < arcs; ++edge) {
      upstream.child_out[edge] = static_cast<int>(input.neighbors[edge]);
      upstream.child_in[edge] = static_cast<int>(input.neighbors[edge]);
      upstream.wts_out[edge] = 1.0;
      upstream.wts_in[edge] = 1.0;
    }

    create_c_partition(upstream, partition);
    graphmine_gleiden_original_to_current.resize(input.vertex_count());
    std::iota(graphmine_gleiden_original_to_current.begin(),
              graphmine_gleiden_original_to_current.end(), 0);

    const auto started = std::chrono::steady_clock::now();
    Leiden_GPU(partition, upstream, arcs);
    status = cuda_status(cudaGetLastError(), "executing gLeiden");
    const auto finished = std::chrono::steady_clock::now();
    if (!status.ok()) {
      ::free(upstream);
      free_part(partition);
      return {status, {}, std::nullopt, 0.0};
    }

    std::vector<std::uint32_t> labels;
    labels.reserve(graphmine_gleiden_original_to_current.size());
    for (const auto label : graphmine_gleiden_original_to_current) {
      if (label < 0) {
        ::free(upstream);
        free_part(partition);
        return {{StatusCode::correctness_mismatch,
                 "gLeiden produced a negative community label"},
                {}, std::nullopt, 0.0};
      }
      labels.push_back(static_cast<std::uint32_t>(label));
    }

    ::free(upstream);
    free_part(partition);
    return {Status::success(), std::move(labels), std::nullopt,
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("gLeiden execution failed: ") + error.what()},
            {}, std::nullopt, 0.0};
  }
}

}  // namespace graphmine::detail
