#include "backends/maximal_cliques/backend.hpp"

#include <algorithm>
#include <chrono>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <string>
#include <vector>

#include <cuda_runtime.h>

// Isolate the artifact's generic global and namespace identifiers.  The
// kernels and data structures themselves remain the pinned implementation.
#define graph graphmine_mce_gpu_upstream
#define Config GraphMineMceGpuConfig
#define gpuAssert graphmine_mce_gpu_assert
#define setelements graphmine_mce_gpu_setelements
#define init_asc graphmine_mce_gpu_init_asc
#define filter_window graphmine_mce_gpu_filter_window
#define filter_with_random_append graphmine_mce_gpu_filter_append
#define update_priority graphmine_mce_gpu_update_priority
#define getNodeDegree_kernel graphmine_mce_gpu_degree_kernel
#define kernel_partition_level_next graphmine_mce_gpu_partition_next
#define set_priority graphmine_mce_gpu_set_priority
#define split_pointer graphmine_mce_gpu_split_pointer
#define split_data graphmine_mce_gpu_split_data
#define PARTSIZE GRAPHMINE_MCE_GPU_PARTSIZE
#define NUMPART GRAPHMINE_MCE_GPU_NUMPART
#define MAXLEVEL GRAPHMINE_MCE_GPU_MAXLEVEL
#define NUMDIVS GRAPHMINE_MCE_GPU_NUMDIVS
#define MAXDEG GRAPHMINE_MCE_GPU_MAXDEG
#define MAXUNDEG GRAPHMINE_MCE_GPU_MAXUNDEG
#define CBPSM GRAPHMINE_MCE_GPU_CBPSM
#define MSGCNT GRAPHMINE_MCE_GPU_MSGCNT
#define CB GRAPHMINE_MCE_GPU_CB
#include "config.h"
#include "csrcoo.cuh"
#include "kcore.cuh"
#include "main_support.cuh"
#include "mce.cuh"
#undef CB
#undef MSGCNT
#undef CBPSM
#undef MAXUNDEG
#undef MAXDEG
#undef NUMDIVS
#undef MAXLEVEL
#undef NUMPART
#undef PARTSIZE
#undef split_data
#undef split_pointer
#undef set_priority
#undef kernel_partition_level_next
#undef getNodeDegree_kernel
#undef update_priority
#undef filter_with_random_append
#undef filter_window
#undef init_asc
#undef setelements
#undef Config
#undef graph

namespace graphmine::detail {

bool mce_gpu_backend_compiled() noexcept { return true; }

BackendCountResult run_mce_gpu_count(const CsrGraph& graph, int device_id) {
  if (graph.vertex_count() == 0) {
    return {Status::success(), 0, 0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(UINT_MAX - 1U) ||
      graph.neighbors.size() > static_cast<std::size_t>(UINT_MAX)) {
    return {{StatusCode::unsupported,
             "mce-gpu uses unsigned 32-bit graph indices"},
            0, 0.0};
  }

  int device_count = 0;
  if (device_id < 0 || cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count || cudaSetDevice(device_id) != cudaSuccess) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for mce-gpu"},
            0, 0.0};
  }

  try {
    using UpstreamGraph =
        graphmine_mce_gpu_upstream::COOCSRGraph_d<DataType>;
    // The artifact's converter and validated inputs reserve vertex zero and
    // store graph vertices from one.  Preserve that convention in memory; its
    // kernels ignore the isolated sentinel in the maximal-clique total.
    const auto vertex_count =
        static_cast<DataType>(graph.vertex_count() + 1U);
    const auto directed_edges = static_cast<DataType>(graph.neighbors.size());

    std::vector<DataType> offsets(vertex_count + 1U, 0);
    for (std::size_t vertex = 0; vertex <= graph.vertex_count(); ++vertex) {
      offsets[vertex + 1U] = static_cast<DataType>(graph.offsets[vertex]);
    }
    std::vector<DataType> neighbors;
    neighbors.reserve(graph.neighbors.size());
    for (const auto neighbor : graph.neighbors) {
      neighbors.push_back(neighbor + 1U);
    }
    std::vector<DataType> row_indices(neighbors.size());
    for (DataType vertex = 0; vertex < vertex_count; ++vertex) {
      std::fill(row_indices.begin() + offsets[vertex],
                row_indices.begin() + offsets[vertex + 1U], vertex);
    }

    UpstreamGraph original{};
    original.numNodes = vertex_count;
    original.numEdges = directed_edges;
    original.capacity = directed_edges;
    CUDA_RUNTIME(cudaMallocManaged(&original.rowPtr,
                                   sizeof(DataType) * (vertex_count + 1ULL)));
    CUDA_RUNTIME(cudaMallocManaged(&original.rowInd,
                                   sizeof(DataType) * directed_edges));
    CUDA_RUNTIME(cudaMallocManaged(&original.colInd,
                                   sizeof(DataType) * directed_edges));
    CUDA_RUNTIME(cudaMemcpy(original.rowPtr, offsets.data(),
                            sizeof(DataType) * (vertex_count + 1ULL),
                            cudaMemcpyHostToDevice));
    CUDA_RUNTIME(cudaMemcpy(original.rowInd, row_indices.data(),
                            sizeof(DataType) * directed_edges,
                            cudaMemcpyHostToDevice));
    CUDA_RUNTIME(cudaMemcpy(original.colInd, neighbors.data(),
                            sizeof(DataType) * directed_edges,
                            cudaMemcpyHostToDevice));

    graphmine_mce_gpu_upstream::SingleGPU_Kcore<DataType, PeelType> kcore(
        device_id);
    kcore.findKcoreIncremental_async(original);

    UpstreamGraph oriented{};
    oriented.numNodes = vertex_count;
    oriented.numEdges = directed_edges;
    oriented.capacity = directed_edges;
    CUDA_RUNTIME(cudaMallocManaged(&oriented.colInd,
                                   sizeof(DataType) * directed_edges));
    CUDA_RUNTIME(cudaMallocManaged(&oriented.splitPtr,
                                   sizeof(DataType) * (vertex_count + 1ULL)));
    CUDA_RUNTIME(cudaMallocManaged(&oriented.rowPtr,
                                   sizeof(DataType) * (vertex_count + 1ULL)));
    CUDA_RUNTIME(cudaMemcpy(oriented.rowPtr, original.rowPtr,
                            sizeof(DataType) * (vertex_count + 1ULL),
                            cudaMemcpyDefault));
    CUDA_RUNTIME(cudaMallocManaged(&oriented.rowInd,
                                   sizeof(DataType) * directed_edges));
    CUDA_RUNTIME(cudaMemcpy(oriented.rowInd, original.rowInd,
                            sizeof(DataType) * directed_edges,
                            cudaMemcpyDefault));

    constexpr std::size_t block_size = 1024;
    graphmine_mce_gpu_upstream::GPUArray<DataType> tmp_block(
        "Temp Block", AllocationTypeEnum::unified,
        (directed_edges + block_size - 1U) / block_size, device_id);
    graphmine_mce_gpu_upstream::GPUArray<DataType> split_ptr(
        "Split Ptr", AllocationTypeEnum::unified, vertex_count + 1ULL,
        device_id);
    tmp_block.setAll(0, true);
    split_ptr.setAll(0, true);
    execKernel((graphmine_mce_gpu_set_priority<DataType>),
               (directed_edges + block_size - 1U) / block_size, block_size,
               device_id, false, original, directed_edges,
               kcore.nodePriority.gdata(), tmp_block.gdata(),
               split_ptr.gdata());
    CUDA_RUNTIME(cudaMemcpy(oriented.splitPtr, split_ptr.gdata(),
                            sizeof(DataType) * (vertex_count + 1ULL),
                            cudaMemcpyDefault));
    execKernel((graphmine_mce_gpu_split_pointer<DataType>),
               (vertex_count + 1ULL + block_size - 1U) / block_size,
               block_size, device_id, false, original, oriented.splitPtr);
    CUBScanExclusive<DataType, DataType>(
        split_ptr.gdata(), split_ptr.gdata(), vertex_count + 1U, device_id, 0);
    CUBScanExclusive<DataType, DataType>(
        tmp_block.gdata(), tmp_block.gdata(),
        (directed_edges + block_size - 1U) / block_size, device_id, 0);
    execKernel((graphmine_mce_gpu_split_data<DataType, block_size>),
               (directed_edges + block_size - 1U) / block_size, block_size,
               device_id, false, original, directed_edges,
               kcore.nodePriority.gdata(), tmp_block.gdata(),
               split_ptr.gdata(), oriented.splitPtr, oriented.colInd);
    tmp_block.freeGPU();
    split_ptr.freeGPU();

    CUDA_RUNTIME(cudaFree(original.rowPtr));
    CUDA_RUNTIME(cudaFree(original.rowInd));
    CUDA_RUNTIME(cudaFree(original.colInd));

    GraphMineMceGpuConfig config{};
    config.mt = MAINTASK::MCE;
    config.level = PARLEVEL::L2;
    config.induced = INDUCEDSUBGRAPH::IPX;
    config.workerlist = WORKERLIST::WL;
    config.deviceId = device_id;
    config.gpus = {device_id};

    graphmine_mce_gpu_upstream::MultiGPU_MCE<DataType> counter(device_id, 0,
                                                               1);
    const auto started = std::chrono::steady_clock::now();
    if (kcore.count() <= 300U) {
      counter.mce_count<1>(oriented, config);
    } else {
      counter.mce_count<8>(oriented, config);
    }
    counter.sync();
    const auto count = counter.mce_counter.getSingle(0);
    const auto finished = std::chrono::steady_clock::now();

    CUDA_RUNTIME(cudaFree(oriented.colInd));
    CUDA_RUNTIME(cudaFree(oriented.splitPtr));
    CUDA_RUNTIME(cudaFree(oriented.rowPtr));
    CUDA_RUNTIME(cudaFree(oriented.rowInd));

    return {Status::success(), static_cast<std::uint64_t>(count),
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("mce-gpu execution failed: ") + error.what()},
            0, 0.0};
  }
}

}  // namespace graphmine::detail

#undef gpuAssert
