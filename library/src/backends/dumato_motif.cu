#include "backends/graph_motif_backend.hpp"

#include <chrono>
#include <climits>
#include <cstdint>
#include <limits>
#include <mutex>
#include <new>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#define DataCPU GraphMineDumatoMotifDataCpu
#define DataGPU GraphMineDumatoMotifDataGpu
#define DuMatoCPU GraphMineDumatoMotifCpu
#define EnumerationHelper GraphMineDumatoMotifEnumerationHelper
#define GPULocalVariables GraphMineDumatoMotifGpuLocalVariables
#define Graph GraphMineDumatoMotifGraph
#define QuickMapping GraphMineDumatoMotifQuickMapping
#include "DuMatoCPU.h"
#undef QuickMapping
#undef Graph
#undef GPULocalVariables
#undef EnumerationHelper
#undef DuMatoCPU
#undef DataGPU
#undef DataCPU

__global__ void graphmine_dumato_motif_kernel(
    GraphMineDumatoMotifDataGpu* data);

namespace graphmine::detail {
namespace {

std::mutex dumato_motif_mutex;

std::vector<std::uint64_t> common_order(
    std::uint32_t motif_size,
    const std::vector<std::uint64_t>& canonical_graph_counts) {
  if (motif_size == 3 && canonical_graph_counts.size() >= 3) {
    // DuMato canonical graph ids: 1=wedge, 2=triangle.
    return {canonical_graph_counts[2], canonical_graph_counts[1]};
  }
  if (motif_size == 4 && canonical_graph_counts.size() >= 10) {
    // DuMato canonical graph ids: 3=path, 4=cycle, 6=star,
    // 7=tailed triangle, 8=diamond, 9=clique.
    return {canonical_graph_counts[6], canonical_graph_counts[3],
            canonical_graph_counts[7], canonical_graph_counts[4],
            canonical_graph_counts[8], canonical_graph_counts[9]};
  }
  return {};
}

}  // namespace

bool dumato_motif_backend_compiled() noexcept { return true; }

GraphMotifBackendResult run_dumato_motifs(const CsrGraph& graph,
                                          std::uint32_t motif_size,
                                          int device_id) {
  const auto result_size = motif_size == 3 ? 2U : 6U;
  if (motif_size < 3 || motif_size > 4) {
    return {{StatusCode::unsupported,
             "the validated DuMato motif path supports sizes 3 and 4"},
            {}, 0.0};
  }
  if (graph.vertex_count() < motif_size || graph.neighbors.empty()) {
    return {Status::success(), std::vector<std::uint64_t>(result_size, 0),
            0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(INT_MAX) ||
      graph.neighbors.size() > static_cast<std::size_t>(INT_MAX)) {
    return {{StatusCode::unsupported,
             "DuMato uses signed 32-bit graph indices"},
            {}, 0.0};
  }

  int device_count = 0;
  cudaDeviceProp properties{};
  if (device_id < 0 || cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count || cudaSetDevice(device_id) != cudaSuccess ||
      cudaGetDeviceProperties(&properties, device_id) != cudaSuccess) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for DuMato"},
            {}, 0.0};
  }

  try {
    std::vector<std::int64_t> offsets(graph.offsets.begin(),
                                      graph.offsets.end());
    std::vector<std::int32_t> neighbours(graph.neighbors.begin(),
                                         graph.neighbors.end());

    const std::lock_guard<std::mutex> lock(dumato_motif_mutex);
    const auto started = std::chrono::steady_clock::now();
    auto* original =
        new GraphMineDumatoMotifGraph(offsets, neighbours);
    GraphMineDumatoMotifCpu engine(
        original, static_cast<int>(motif_size), 102400, 256,
        properties.multiProcessorCount, 16, graphmine_dumato_motif_kernel,
        100, true, false);
    engine.runKernel();
    engine.waitKernel();

    const auto number_of_canonical_graphs =
        static_cast<std::size_t>(engine.quickMapping->numberOfCgs);
    const auto number_of_warps =
        static_cast<std::size_t>(engine.dataCPU->h_numberOfWarps);
    const auto copied = cudaMemcpy(
        engine.dataCPU->h_hashPerWarp, engine.dataGPU->d_hashPerWarp,
        number_of_warps * number_of_canonical_graphs *
            sizeof(unsigned long long),
        cudaMemcpyDeviceToHost);
    if (copied != cudaSuccess) {
      return {{StatusCode::execution_failed,
               std::string("DuMato motif result transfer failed: ") +
                   cudaGetErrorString(copied)},
              {}, 0.0};
    }

    std::vector<std::uint64_t> canonical_counts(
        number_of_canonical_graphs, 0);
    for (std::size_t warp = 0; warp < number_of_warps; ++warp) {
      for (std::size_t canonical = 0;
           canonical < number_of_canonical_graphs; ++canonical) {
        canonical_counts[canonical] +=
            engine.dataCPU
                ->h_hashPerWarp[warp * number_of_canonical_graphs + canonical];
      }
    }
    auto counts = common_order(motif_size, canonical_counts);
    const auto finished = std::chrono::steady_clock::now();
    if (counts.size() != result_size) {
      return {{StatusCode::internal_error,
               "DuMato returned an unexpected canonical-graph vector"},
              {}, 0.0};
    }
    return {Status::success(), std::move(counts),
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::bad_alloc&) {
    return {{StatusCode::resource_exhausted,
             "DuMato motif host allocation failed"},
            {}, 0.0};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("DuMato motif execution failed: ") + error.what()},
            {}, 0.0};
  }
}

}  // namespace graphmine::detail
