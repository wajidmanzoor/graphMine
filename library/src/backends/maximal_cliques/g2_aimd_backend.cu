#include "backends/maximal_cliques/backend.hpp"

#include <algorithm>
#include <chrono>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <limits>
#include <mutex>
#include <numeric>
#include <string>
#include <vector>

#include <cuda_runtime.h>

// Load Bliss before defining the upstream Graph-name prefix.  Otherwise the
// preprocessor also renames bliss::Graph and the adapter can no longer link
// against the unmodified bundled Bliss archive.
#include "bliss/graph.hh"
using GraphMineG2AimdBliss = bliss::Graph;

// G2-AIMD is header implemented and uses broad global names.  Prefix its host
// types and kernel entry points so it can coexist with the other artifacts.
#define Graph GraphMineG2AimdGraph
#define Timer GraphMineG2AimdTimer
#define WorkContext GraphMineG2AimdWorkContext
#define CudaContext GraphMineG2AimdCudaContext
#define DeviceMemoryInfo GraphMineG2AimdDeviceMemoryInfo
#define BufferBase GraphMineG2AimdBufferBase
#define SubgraphContainer GraphMineG2AimdSubgraphContainer
#define AppBase GraphMineG2AimdAppBase
#define BKBuffer GraphMineG2AimdBKBuffer
#define BKBase GraphMineG2AimdBKBase
#define BKExpandSequential GraphMineG2AimdBKExpandSequential
#define PipelineExecutor GraphMineG2AimdPipelineExecutor
#define HandleError graphmine_g2_aimd_handle_error
#define chkerr graphmine_g2_aimd_check_error
#define generateSubgraphs graphmine_g2_aimd_generate_subgraphs
#define process graphmine_g2_aimd_process
#define expand graphmine_g2_aimd_expand
#define loadFromHost graphmine_g2_aimd_load_from_host
#include "app_BK/BK.h"
#include "view/view_bin_holder.h"
#include "system/pipeline_executor.h"
#undef loadFromHost
#undef expand
#undef process
#undef generateSubgraphs
#undef chkerr
#undef PipelineExecutor
#undef BKExpandSequential
#undef BKBase
#undef BKBuffer
#undef AppBase
#undef SubgraphContainer
#undef BufferBase
#undef DeviceMemoryInfo
#undef CudaContext
#undef WorkContext
#undef Timer
#undef Graph

namespace graphmine::detail {
namespace {

std::mutex g2_aimd_mutex;

}  // namespace

bool g2_aimd_backend_compiled() noexcept { return true; }

BackendCountResult run_g2_aimd_count(const CsrGraph& graph, int device_id) {
  if (graph.vertex_count() == 0) {
    return {Status::success(), 0, 0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(UINT_MAX) ||
      graph.neighbors.size() >
          static_cast<std::size_t>(std::numeric_limits<uintE>::max())) {
    return {{StatusCode::unsupported,
             "G2-AIMD uses unsigned 32-bit vertex indices"},
            0, 0.0};
  }
  std::uint64_t maximum_degree = 0;
  for (std::size_t vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    maximum_degree =
        std::max(maximum_degree,
                 graph.offsets[vertex + 1U] - graph.offsets[vertex]);
  }
  if (maximum_degree >= TEMPSIZE) {
    return {{StatusCode::unsupported,
             "G2-AIMD requires maximum degree below its 100000-entry "
             "per-warp temporary capacity"},
            0, 0.0};
  }

  int device_count = 0;
  if (device_id < 0 || device_id >= 8 ||
      cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count || cudaSetDevice(device_id) != cudaSuccess) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for G2-AIMD"},
            0, 0.0};
  }

  try {
    std::lock_guard<std::mutex> lock(g2_aimd_mutex);
    std::vector<uintE> offsets(graph.offsets.begin(), graph.offsets.end());
    std::vector<uintV> neighbors(graph.neighbors.begin(),
                                 graph.neighbors.end());
    std::vector<uintV> sources(graph.vertex_count());
    std::iota(sources.begin(), sources.end(), uintV{0});

    GraphMineG2AimdGraph original;
    original.SetVertexCount(graph.vertex_count());
    original.SetEdgeCount(graph.neighbors.size());
    original.SetRowPtrs(offsets.data());
    original.SetCols(neighbors.data());

    GraphMineG2AimdBKExpandSequential application;
    std::vector<StoreStrategy> strategy;
    constexpr std::size_t maximum_buffer_entries = 16'000'000ULL;
    const auto adjacency_bytes =
        std::max<std::size_t>(sizeof(uintV),
                              neighbors.size() * sizeof(uintV));
    GraphMineG2AimdPipelineExecutor<GraphMineG2AimdBKExpandSequential>
        executor(static_cast<std::size_t>(device_id), &original,
                 graph.vertex_count(), application, adjacency_bytes, strategy,
                 maximum_buffer_entries);

    executor.app.ctx->sources_num[0] = sources.size();
    HToD(executor.app.ctx->sources, sources.data(), sources.size());
    HToD(executor.app.ctx->d_row_ptrs, offsets.data(), offsets.size());
    HToD(executor.app.ctx->d_cols, neighbors.data(), neighbors.size());

    const auto started = std::chrono::steady_clock::now();
    executor.Run();
    CUDA_ERROR(cudaDeviceSynchronize());
    const auto finished = std::chrono::steady_clock::now();
    const auto count = executor.app.totalCliques[0];
    return {Status::success(), static_cast<std::uint64_t>(count),
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("G2-AIMD execution failed: ") + error.what()},
            0, 0.0};
  }
}

}  // namespace graphmine::detail

#undef HandleError
