#include "backends/maximum_clique_backend.hpp"

#include <algorithm>
#include <chrono>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <mutex>
#include <string>
#include <vector>

#include <cuda_runtime.h>

// The artifact is header implemented and shares generic names with mce-gpu.
// Prefix those names so both validated implementations can be linked into one
// process without changing either algorithm's kernels.
#define graph graphmine_maximum_clique_on_gpu_upstream
#define Config GraphMineMaximumCliqueOnGpuConfig
#define CUDAContext GraphMineMaximumCliqueOnGpuCudaContext
#define gpuAssert graphmine_maximum_clique_on_gpu_assert
#define setelements graphmine_maximum_clique_on_gpu_setelements
#define getVal graphmine_maximum_clique_on_gpu_get_value
#define CUBSelect graphmine_maximum_clique_on_gpu_cub_select
#define CUBScanExclusive graphmine_maximum_clique_on_gpu_cub_scan
#define init_asc graphmine_maximum_clique_on_gpu_init_asc
#define filter_window graphmine_maximum_clique_on_gpu_filter_window
#define filter_with_random_append graphmine_maximum_clique_on_gpu_filter_append
#define update_priority graphmine_maximum_clique_on_gpu_update_priority
#define getNodeDegree_kernel graphmine_maximum_clique_on_gpu_degree_kernel
#define set_priority graphmine_maximum_clique_on_gpu_set_priority
#define set_priority_2 graphmine_maximum_clique_on_gpu_set_priority_2
#define split_pointer graphmine_maximum_clique_on_gpu_split_pointer
#define split_data graphmine_maximum_clique_on_gpu_split_data
#define PARTSIZE GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_PARTSIZE
#define NUMPART GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_NUMPART
#define MAXLEVEL GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_MAXLEVEL
#define NUMDIVS GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_NUMDIVS
#define MAXDEG GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_MAXDEG
#define MAXUNDEG GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_MAXUNDEG
#define CBPSM GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_CBPSM
#define MSGCNT GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_MSGCNT
#define CB GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_CB
#define WARPS GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_WARPS
#include "config.h"
#include "csrcoo.cuh"
#include "kcore.cuh"
#include "main_support.cuh"
#include "mcp.cuh"
#undef WARPS
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
#undef set_priority_2
#undef set_priority
#undef getNodeDegree_kernel
#undef update_priority
#undef filter_with_random_append
#undef filter_window
#undef init_asc
#undef CUBScanExclusive
#undef CUBSelect
#undef getVal
#undef setelements
#undef CUDAContext
#undef Config
#undef graph

namespace graphmine::detail {
namespace {

using UpstreamGraph =
    graphmine_maximum_clique_on_gpu_upstream::COOCSRGraph_d<DataType>;

std::mutex maximum_clique_on_gpu_mutex;

struct DeviceGraphStorage {
  UpstreamGraph value{};

  DeviceGraphStorage() = default;
  DeviceGraphStorage(const DeviceGraphStorage&) = delete;
  DeviceGraphStorage& operator=(const DeviceGraphStorage&) = delete;

  ~DeviceGraphStorage() {
    if (value.colInd != nullptr) cudaFree(value.colInd);
    if (value.rowInd != nullptr) cudaFree(value.rowInd);
    if (value.rowPtr != nullptr) cudaFree(value.rowPtr);
    if (value.splitPtr != nullptr) cudaFree(value.splitPtr);
  }
};

std::vector<VertexIndex> copy_original_vertices(
    graphmine_maximum_clique_on_gpu_upstream::GPUArray<DataType>& values,
    std::size_t count) {
  std::vector<VertexIndex> result;
  if (count == 0 || values.N < count) return result;
  DataType* copied = values.copytocpu(0, count, true);
  result.reserve(count);
  for (std::size_t i = 0; i < count; ++i) {
    // Vertex zero is the isolated sentinel used by the artifact's converter.
    if (copied[i] != 0) result.push_back(copied[i] - 1U);
  }
  std::free(copied);
  return result;
}

}  // namespace

bool maximum_clique_on_gpu_backend_compiled() noexcept { return true; }

MaximumCliqueBackendResult run_maximum_clique_on_gpu(
    const CsrGraph& graph, int device_id, std::uint32_t known_lower_bound) {
  if (graph.vertex_count() == 0) {
    return {Status::success(), {}, 0, 0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(UINT_MAX - 1U) ||
      graph.neighbors.size() > static_cast<std::size_t>(UINT_MAX)) {
    return {{StatusCode::unsupported,
             "Maximum-Clique-on-GPU uses unsigned 32-bit graph indices"},
            {}, 0, 0.0};
  }

  int device_count = 0;
  if (device_id < 0 || cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count || cudaSetDevice(device_id) != cudaSuccess) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for Maximum-Clique-on-GPU"},
            {}, 0, 0.0};
  }

  try {
    std::lock_guard<std::mutex> lock(maximum_clique_on_gpu_mutex);
    const auto started = std::chrono::steady_clock::now();

    // The artifact's validated BEL converter reserves vertex zero.  Recreate
    // that representation in memory so preprocessing and search see exactly
    // the same indexing convention as the validation run.
    const DataType vertex_count =
        static_cast<DataType>(graph.vertex_count() + 1U);
    const DataType edge_count =
        static_cast<DataType>(graph.neighbors.size());
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

    DeviceGraphStorage original;
    original.value.numNodes = vertex_count;
    original.value.numEdges = edge_count;
    original.value.capacity = edge_count;
    CUDA_RUNTIME(cudaMallocManaged(
        &original.value.rowPtr, sizeof(DataType) * (vertex_count + 1ULL)));
    CUDA_RUNTIME(cudaMallocManaged(
        &original.value.rowInd, sizeof(DataType) * edge_count));
    CUDA_RUNTIME(cudaMallocManaged(
        &original.value.colInd, sizeof(DataType) * edge_count));
    CUDA_RUNTIME(cudaMemcpy(original.value.rowPtr, offsets.data(),
                            sizeof(DataType) * (vertex_count + 1ULL),
                            cudaMemcpyHostToDevice));
    CUDA_RUNTIME(cudaMemcpy(original.value.rowInd, row_indices.data(),
                            sizeof(DataType) * edge_count,
                            cudaMemcpyHostToDevice));
    CUDA_RUNTIME(cudaMemcpy(original.value.colInd, neighbors.data(),
                            sizeof(DataType) * edge_count,
                            cudaMemcpyHostToDevice));

    graphmine_maximum_clique_on_gpu_upstream::SingleGPU_Kcore<
        DataType, PeelType>
        kcore(device_id);
    kcore.findKcoreIncremental_async(original.value);
    const auto heuristic_size =
        static_cast<std::uint32_t>(kcore.heurCliqueSize.getSingle(0));
    auto heuristic_clique =
        copy_original_vertices(kcore.heurCliqueVertices, heuristic_size);
    if (heuristic_clique.size() != heuristic_size) {
      return {{StatusCode::execution_failed,
               "Maximum-Clique-on-GPU did not retain its preprocessing "
               "clique vertices"},
              {}, 0, 0.0};
    }

    const auto max_core = static_cast<DataType>(kcore.count());
    if (heuristic_size == max_core + 1U) {
      const auto finished = std::chrono::steady_clock::now();
      return {Status::success(), std::move(heuristic_clique), heuristic_size,
              std::chrono::duration<double, std::milli>(finished - started)
                  .count()};
    }

    // A caller-provided bound is checked by the common facade.  The search is
    // seeded with the artifact's concrete heuristic clique so that a valid
    // vertex set is always available if no larger clique exists.
    (void)known_lower_bound;
    GraphMineMaximumCliqueOnGpuConfig config{};
    config.mt = MAINTASK::MCP;
    config.deviceId = device_id;
    config.block_size = 64;
    config.warp_parallel = false;
    config.gpus = {device_id};
    config.lb = heuristic_size;
    config.verbose = false;
    config.colorAlg = COLORALG::PSANSE;

    GraphMineMaximumCliqueOnGpuCudaContext context;
    constexpr DataType block_size = 256;
    const DataType blocks =
        context.GetConCBlocks(block_size) * context.num_SMs;

    DataType* reduced_vertex_count_device = nullptr;
    CUDA_RUNTIME(cudaMalloc(&reduced_vertex_count_device, sizeof(DataType)));
    CUDA_RUNTIME(cudaMemset(reduced_vertex_count_device, 0, sizeof(DataType)));
    execKernel((getNodeNumberReducedByLB_kernel<DataType>), blocks, block_size,
               device_id, false, original.value, kcore.coreNumber.gdata(),
               config.lb, reduced_vertex_count_device);
    DataType reduced_vertex_count = 0;
    CUDA_RUNTIME(cudaMemcpy(&reduced_vertex_count,
                            reduced_vertex_count_device, sizeof(DataType),
                            cudaMemcpyDeviceToHost));
    CUDA_RUNTIME(cudaFree(reduced_vertex_count_device));
    if (reduced_vertex_count == 0) {
      const auto finished = std::chrono::steady_clock::now();
      return {Status::success(), std::move(heuristic_clique), heuristic_size,
              std::chrono::duration<double, std::milli>(finished - started)
                  .count()};
    }

    using UpstreamArray =
        graphmine_maximum_clique_on_gpu_upstream::GPUArray<DataType>;
    using UpstreamCharArray =
        graphmine_maximum_clique_on_gpu_upstream::GPUArray<char>;

    UpstreamArray reduced_degrees("Reduced degrees", unified, vertex_count,
                                  device_id);
    reduced_degrees.setAll(0, true);
    UpstreamCharArray flags("Reduction flags", unified, vertex_count,
                            device_id);
    flags.setAll(0, true);
    execKernel((computeFlags_kernel<DataType>), blocks, block_size, device_id,
               false, original.value, kcore.coreNumber.gdata(), config.lb,
               flags.gdata());

    DataType* reduced_edge_count_device = nullptr;
    CUDA_RUNTIME(cudaMalloc(&reduced_edge_count_device, sizeof(DataType)));
    CUDA_RUNTIME(cudaMemset(reduced_edge_count_device, 0, sizeof(DataType)));
    execKernel((getEdgeNumberAndDegreesReducedByLB_kernel<DataType>), blocks,
               block_size, device_id, false, original.value,
               kcore.coreNumber.gdata(), config.lb,
               reduced_edge_count_device, reduced_degrees.gdata());
    DataType reduced_edge_count = 0;
    CUDA_RUNTIME(cudaMemcpy(&reduced_edge_count, reduced_edge_count_device,
                            sizeof(DataType), cudaMemcpyDeviceToHost));
    CUDA_RUNTIME(cudaFree(reduced_edge_count_device));

    UpstreamArray compact_degrees("Compact reduced degrees", unified,
                                  reduced_vertex_count, device_id);
    graphmine_maximum_clique_on_gpu_cub_select(
        reduced_degrees.gdata(), compact_degrees.gdata(), flags.gdata(),
        vertex_count, device_id);
    reduced_degrees.freeGPU();

    UpstreamArray indices("Original indices", unified, vertex_count,
                          device_id);
    execKernel((generateIndices_kernel<DataType>),
               (vertex_count + block_size - 1U) / block_size, block_size,
               device_id, false, indices.gdata(), vertex_count);
    UpstreamArray temporary_old_names("Temporary original names", unified,
                                      reduced_vertex_count, device_id);
    graphmine_maximum_clique_on_gpu_cub_select(
        indices.gdata(), temporary_old_names.gdata(), flags.gdata(),
        vertex_count, device_id);
    indices.freeGPU();

    UpstreamArray reduced_core_numbers("Reduced core numbers", gpu,
                                       reduced_vertex_count, device_id);
    graphmine_maximum_clique_on_gpu_cub_select(
        kcore.coreNumber.gdata(), reduced_core_numbers.gdata(), flags.gdata(),
        vertex_count, device_id);
    flags.freeGPU();

    UpstreamArray old_names("Original names", unified, reduced_vertex_count,
                            device_id);
    void* temporary_storage = nullptr;
    std::size_t temporary_storage_bytes = 0;
    cub::DeviceRadixSort::SortPairsDescending(
        temporary_storage, temporary_storage_bytes,
        reduced_core_numbers.gdata(), reduced_core_numbers.gdata(),
        temporary_old_names.gdata(), old_names.gdata(), reduced_vertex_count);
    CUDA_RUNTIME(cudaMalloc(&temporary_storage, temporary_storage_bytes));
    cub::DeviceRadixSort::SortPairsDescending(
        temporary_storage, temporary_storage_bytes,
        reduced_core_numbers.gdata(), reduced_core_numbers.gdata(),
        temporary_old_names.gdata(), old_names.gdata(), reduced_vertex_count);
    CUDA_RUNTIME(cudaFree(temporary_storage));
    temporary_old_names.freeGPU();

    // Preserve the artifact's second key/value ordering step exactly.
    temporary_storage = nullptr;
    temporary_storage_bytes = 0;
    cub::DeviceRadixSort::SortPairsDescending(
        temporary_storage, temporary_storage_bytes,
        reduced_core_numbers.gdata(), reduced_core_numbers.gdata(),
        compact_degrees.gdata(), compact_degrees.gdata(),
        reduced_vertex_count);
    CUDA_RUNTIME(cudaMalloc(&temporary_storage, temporary_storage_bytes));
    cub::DeviceRadixSort::SortPairsDescending(
        temporary_storage, temporary_storage_bytes,
        reduced_core_numbers.gdata(), reduced_core_numbers.gdata(),
        compact_degrees.gdata(), compact_degrees.gdata(),
        reduced_vertex_count);
    CUDA_RUNTIME(cudaFree(temporary_storage));
    CUDA_RUNTIME(cudaDeviceSynchronize());

    DeviceGraphStorage reduced;
    reduced.value.numNodes = reduced_vertex_count;
    reduced.value.numEdges = reduced_edge_count;
    reduced.value.capacity = reduced_edge_count;
    CUDA_RUNTIME(cudaMallocManaged(
        &reduced.value.colInd, sizeof(DataType) * reduced_edge_count));
    CUDA_RUNTIME(cudaMallocManaged(
        &reduced.value.rowInd, sizeof(DataType) * reduced_edge_count));
    CUDA_RUNTIME(cudaMallocManaged(
        &reduced.value.rowPtr,
        sizeof(DataType) * (reduced_vertex_count + 1ULL)));
    graphmine_maximum_clique_on_gpu_cub_scan(
        compact_degrees.gdata(), reduced.value.rowPtr, reduced_vertex_count,
        device_id);
    CUDA_RUNTIME(cudaMemcpy(&reduced.value.rowPtr[reduced_vertex_count],
                            &reduced_edge_count, sizeof(DataType),
                            cudaMemcpyHostToDevice));
    compact_degrees.freeGPU();

    UpstreamArray new_names("New names", unified, vertex_count, device_id);
    execKernel((computeNewName_kernel<DataType>),
               (reduced_vertex_count + block_size - 1U) / block_size,
               block_size, device_id, false, old_names.gdata(),
               new_names.gdata(), reduced_vertex_count, vertex_count);
    execKernel((buildReducedByLBB_kernel<DataType, PeelType>),
               (reduced_vertex_count + block_size - 1U) / block_size,
               block_size, device_id, false, original.value, reduced.value,
               kcore.coreNumber.gdata(), old_names.gdata(), new_names.gdata(),
               config.lb);
    new_names.freeGPU();

    temporary_storage = nullptr;
    temporary_storage_bytes = 0;
    cub::DeviceSegmentedRadixSort::SortKeys(
        temporary_storage, temporary_storage_bytes, reduced.value.colInd,
        reduced.value.colInd, reduced_edge_count, reduced_vertex_count,
        reduced.value.rowPtr, reduced.value.rowPtr + 1);
    CUDA_RUNTIME(cudaMalloc(&temporary_storage, temporary_storage_bytes));
    cub::DeviceSegmentedRadixSort::SortKeys(
        temporary_storage, temporary_storage_bytes, reduced.value.colInd,
        reduced.value.colInd, reduced_edge_count, reduced_vertex_count,
        reduced.value.rowPtr, reduced.value.rowPtr + 1);
    CUDA_RUNTIME(cudaFree(temporary_storage));
    CUDA_RUNTIME(cudaDeviceSynchronize());

    DeviceGraphStorage split;
    split.value.numNodes = reduced_vertex_count;
    split.value.numEdges = reduced_edge_count;
    split.value.capacity = reduced_edge_count;
    CUDA_RUNTIME(cudaMallocManaged(
        &split.value.colInd, sizeof(DataType) * reduced_edge_count));
    CUDA_RUNTIME(cudaMallocManaged(
        &split.value.rowInd, sizeof(DataType) * reduced_edge_count));
    CUDA_RUNTIME(cudaMallocManaged(
        &split.value.rowPtr,
        sizeof(DataType) * (reduced_vertex_count + 1ULL)));
    CUDA_RUNTIME(cudaMallocManaged(
        &split.value.splitPtr,
        sizeof(DataType) * (reduced_vertex_count + 1ULL)));
    CUDA_RUNTIME(cudaMemcpy(split.value.colInd, reduced.value.colInd,
                            sizeof(DataType) * reduced_edge_count,
                            cudaMemcpyDeviceToDevice));
    CUDA_RUNTIME(cudaMemcpy(split.value.rowInd, reduced.value.rowInd,
                            sizeof(DataType) * reduced_edge_count,
                            cudaMemcpyDeviceToDevice));
    CUDA_RUNTIME(cudaMemcpy(split.value.rowPtr, reduced.value.rowPtr,
                            sizeof(DataType) * (reduced_vertex_count + 1ULL),
                            cudaMemcpyDeviceToDevice));
    CUDA_RUNTIME(cudaMemset(split.value.splitPtr, 0,
                           sizeof(DataType) *
                               (reduced_vertex_count + 1ULL)));
    execKernel((graphmine_maximum_clique_on_gpu_set_priority_2<DataType>),
               (reduced_edge_count + block_size - 1U) / block_size,
               block_size, device_id, false, split.value, reduced_edge_count,
               split.value.splitPtr);
    execKernel((graphmine_maximum_clique_on_gpu_split_pointer<DataType>),
               (reduced_vertex_count + 1U + block_size - 1U) / block_size,
               block_size, device_id, false, split.value,
               split.value.splitPtr);

    graphmine_maximum_clique_on_gpu_upstream::MultiGPU_MCP<DataType> solver(
        device_id, 0, 1, reduced_core_numbers.gdata(), max_core);
    solver.mcp_search<32>(split.value, config);
    solver.sync();
    CUDA_RUNTIME(cudaMemcpy(&solver.Cmax_size, solver.d_Cmax_size,
                            sizeof(std::uint32_t), cudaMemcpyDeviceToHost));

    std::vector<VertexIndex> clique = heuristic_clique;
    if (solver.Cmax_size > heuristic_size) {
      DataType* reduced_clique =
          solver.Cmax.copytocpu(0, solver.Cmax_size, true);
      DataType* original_names =
          old_names.copytocpu(0, reduced_vertex_count, true);
      clique.clear();
      clique.reserve(solver.Cmax_size);
      for (std::uint32_t i = 0; i < solver.Cmax_size; ++i) {
        const auto original_vertex = original_names[reduced_clique[i]];
        if (original_vertex != 0) clique.push_back(original_vertex - 1U);
      }
      std::free(reduced_clique);
      std::free(original_names);
    }

    old_names.freeGPU();
    reduced_core_numbers.freeGPU();
    const auto finished = std::chrono::steady_clock::now();
    return {Status::success(), std::move(clique), max_core + 1U,
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("Maximum-Clique-on-GPU execution failed: ") +
                 error.what()},
            {}, 0, 0.0};
  }
}

}  // namespace graphmine::detail

#undef gpuAssert
