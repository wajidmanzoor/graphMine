#include "backends/graph_motif_backend.hpp"

#include <chrono>
#include <climits>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#define Graph GraphMineG2MotifGraph
#define GraphGPU GraphMineG2MotifGraphGpu
#define VertexSet GraphMineG2MotifVertexSet
#include "graph.h"
#undef VertexSet
#undef GraphGPU
#undef Graph

void graphmine_g2_motif_solver(GraphMineG2MotifGraph& graph, int k,
                               std::vector<std::uint64_t>& counts, int,
                               int);

namespace graphmine::detail {
namespace {

std::mutex graphminer_mutex;

}  // namespace

bool graphminer_motif_backend_compiled() noexcept { return true; }

GraphMotifBackendResult run_graphminer_motifs(const CsrGraph& graph,
                                              std::uint32_t motif_size,
                                              int device_id) {
  if (motif_size < 3 || motif_size > 4) {
    return {{StatusCode::unsupported,
             "the validated GraphMiner motif path supports sizes 3 and 4"},
            {}, 0.0};
  }
  if (graph.vertex_count() < motif_size) {
    return {Status::success(),
            std::vector<std::uint64_t>(motif_size == 3 ? 2 : 6, 0), 0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(INT_MAX) ||
      graph.neighbors.size() > static_cast<std::size_t>(LLONG_MAX)) {
    return {{StatusCode::unsupported,
             "GraphMiner uses signed 32-bit vertices and 64-bit offsets"},
            {}, 0.0};
  }

  int device_count = 0;
  if (device_id < 0 || cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count || cudaSetDevice(device_id) != cudaSuccess) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for GraphMiner"},
            {}, 0.0};
  }

  try {
    std::vector<std::int64_t> offsets(graph.offsets.begin(),
                                      graph.offsets.end());
    std::vector<std::int32_t> neighbors(graph.neighbors.begin(),
                                        graph.neighbors.end());
    GraphMineG2MotifGraph original(offsets, neighbors);
    std::vector<std::uint64_t> counts(motif_size == 3 ? 2 : 6, 0);
    const std::lock_guard<std::mutex> lock(graphminer_mutex);
    const auto started = std::chrono::steady_clock::now();
    graphmine_g2_motif_solver(original, static_cast<int>(motif_size), counts,
                              1, 1024);
    const auto cuda_status = cudaDeviceSynchronize();
    const auto finished = std::chrono::steady_clock::now();
    if (cuda_status != cudaSuccess) {
      return {{StatusCode::execution_failed,
               std::string("GraphMiner motif execution failed: ") +
                   cudaGetErrorString(cuda_status)},
              {}, 0.0};
    }
    return {Status::success(), std::move(counts),
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("GraphMiner motif execution failed: ") +
                 error.what()},
            {}, 0.0};
  }
}

}  // namespace graphmine::detail
