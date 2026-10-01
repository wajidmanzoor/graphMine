#include "backends/triangle_backend.hpp"

#include <chrono>
#include <climits>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

#include <cuda_runtime.h>
#include <cub/device/device_radix_sort.cuh>
#include <cub/device/device_segmented_sort.cuh>

namespace {

class WetricUpstreamError : public std::runtime_error {
 public:
  explicit WetricUpstreamError(int code)
      : std::runtime_error("WeTriC upstream routine aborted with code " +
                           std::to_string(code)) {}
};

[[noreturn]] void graphmine_wetric_exit(int code) {
  throw WetricUpstreamError(code);
}

}  // namespace

// Compile the pinned artifact unchanged inside this non-RDC adapter
// translation unit.
// Only externally visible identifiers are prefixed so independently sourced
// GPU backends can coexist in one process.
#define exit graphmine_wetric_exit
#define main graphmine_wetric_disabled_main
#define GRAPH_TYPE GraphMineWetricGraph
#define GPU_time GraphMineWetricGpuTime
#define preprocess_t GraphMineWetricPreprocess
#define preprocess graphmine_wetric_preprocess
#define free_graph graphmine_wetric_free_graph
#define tc_GPU graphmine_wetric_count
#include <tc.cu>
#undef tc_GPU
#undef free_graph
#undef preprocess
#undef preprocess_t
#undef GPU_time
#undef GRAPH_TYPE
#undef main
#undef exit

namespace graphmine::detail {

bool wetric_backend_compiled() noexcept { return true; }

TriangleBackendResult run_wetric(const CsrGraph& graph, int device_id,
                                 std::uint32_t spread,
                                 std::uint32_t adjacency_matrix_length) {
  if (graph.vertex_count() < 3 || graph.undirected_edge_count() < 3) {
    return {Status::success(), 0, 0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(UINT_MAX) ||
      graph.neighbors.size() > static_cast<std::size_t>(UINT_MAX)) {
    return {{StatusCode::unsupported, "WeTriC uses unsigned 32-bit indices"},
            0, 0.0};
  }
  if (spread == 0) {
    return {{StatusCode::invalid_argument,
             "wetric_spread must be at least one"},
            0, 0.0};
  }
  if (adjacency_matrix_length == 0 ||
      adjacency_matrix_length % 64 != 0) {
    return {{StatusCode::invalid_argument,
             "wetric_adjacency_matrix_length must be a positive multiple of 64"},
            0, 0.0};
  }

  int device_count = 0;
  cudaDeviceProp properties{};
  if (device_id < 0 || cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count || cudaSetDevice(device_id) != cudaSuccess ||
      cudaGetDeviceProperties(&properties, device_id) != cudaSuccess) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for WeTriC"},
            0, 0.0};
  }
  const auto shared_bytes =
      (2ULL * 128ULL * spread + 1ULL) * sizeof(std::uint32_t);
  if (shared_bytes >
      static_cast<std::uint64_t>(properties.sharedMemPerBlock)) {
    return {{StatusCode::unsupported,
             "wetric_spread exceeds the device shared-memory limit"},
            0, 0.0};
  }

  try {
    std::vector<std::uint32_t> offsets(graph.offsets.begin(),
                                       graph.offsets.end());
    std::vector<std::uint32_t> neighbors(graph.neighbors.begin(),
                                         graph.neighbors.end());
    GraphMineWetricGraph original{
        static_cast<std::uint32_t>(graph.vertex_count()),
        static_cast<std::uint32_t>(neighbors.size()), offsets.data(),
        neighbors.data()};

    // PREPROCESS_CPU is the artifact's original degree ordering and forward
    // orientation without an extra device-side sort or file parser.
    auto* oriented = graphmine_wetric_preprocess(&original, PREPROCESS_CPU);
    GraphMineWetricGpuTime timing{0.0, 0.0};
    const auto started = std::chrono::steady_clock::now();
    const auto count = graphmine_wetric_count(
        oriented, spread, adjacency_matrix_length, &timing);
    const auto finished = std::chrono::steady_clock::now();
    graphmine_wetric_free_graph(oriented);

    const auto cuda_result = cudaGetLastError();
    if (cuda_result != cudaSuccess) {
      return {{StatusCode::execution_failed,
               std::string("WeTriC failed: ") +
                   cudaGetErrorString(cuda_result)},
              0, 0.0};
    }
    return {Status::success(), static_cast<std::uint64_t>(count),
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("WeTriC execution failed: ") + error.what()},
            0, 0.0};
  }
}

}  // namespace graphmine::detail
