#include "backends/k_clique_backend.hpp"

#include <algorithm>
#include <chrono>
#include <climits>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "Logger.cuh"
#include "CGArray.cuh"
#include "TriCountPrim.cuh"
#include "CSRCOO.cuh"
#include "main_support.cuh"
#include "kcore.cuh"
#include "kclique.cuh"
#include "Config.h"
#include "ScanLarge.cuh"

namespace graphmine::detail {
namespace {

std::mutex kcgpu_mutex;

struct DeviceGraph {
  graph::COOCSRGraph_d<uint> value{};

  ~DeviceGraph() {
    if (value.rowPtr != nullptr) cudaFree(value.rowPtr);
    if (value.rowInd != nullptr) cudaFree(value.rowInd);
    if (value.colInd != nullptr) cudaFree(value.colInd);
  }
};

}  // namespace

bool kcgpu_backend_compiled() noexcept { return true; }

KCliqueBackendResult run_kcgpu(const CsrGraph& graph, std::uint32_t k,
                               int device_id) {
  if (k < 3 || k > 5) {
    return {{StatusCode::unsupported,
             "the validated KCGPU path supports 3 <= k <= 5"},
            0, 0.0};
  }
  if (graph.vertex_count() < k) {
    return {Status::success(), 0, 0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(UINT_MAX) ||
      graph.undirected_edge_count() > static_cast<std::uint64_t>(UINT_MAX)) {
    return {{StatusCode::unsupported, "KCGPU uses unsigned 32-bit indices"},
            0, 0.0};
  }

  int device_count = 0;
  if (device_id < 0 || cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count || cudaSetDevice(device_id) != cudaSuccess) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for KCGPU"},
            0, 0.0};
  }

  try {
    std::vector<std::uint32_t> degrees(graph.vertex_count());
    for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
      degrees[vertex] = static_cast<std::uint32_t>(
          graph.offsets[vertex + 1] - graph.offsets[vertex]);
    }

    // KCGPU's validated MatrixMarket path retains the format's one-based
    // vertex numbering (vertex zero is an empty sentinel).  Preserve that
    // internal layout while the public GraphMine graph remains zero-based.
    const auto upstream_vertex_count = graph.vertex_count() + 1;
    std::vector<std::uint32_t> offsets(upstream_vertex_count + 1, 0);
    std::vector<std::uint32_t> rows;
    std::vector<std::uint32_t> columns;
    rows.reserve(graph.undirected_edge_count());
    columns.reserve(graph.undirected_edge_count());
    for (VertexIndex source = 0; source < graph.vertex_count(); ++source) {
      for (auto offset = graph.offsets[source];
           offset < graph.offsets[source + 1]; ++offset) {
        const auto target = graph.neighbors[offset];
        // This is the exact Degree mode used by the validated executable:
        // lower degree to higher degree, then lower ID to higher ID.
        if (degrees[source] < degrees[target] ||
            (degrees[target] == degrees[source] && source < target)) {
          rows.push_back(source + 1);
          columns.push_back(target + 1);
          ++offsets[source + 2];
        }
      }
    }
    for (std::size_t index = 1; index < offsets.size(); ++index) {
      offsets[index] += offsets[index - 1];
    }

    DeviceGraph device;
    device.value.numNodes = static_cast<uint>(upstream_vertex_count);
    device.value.numEdges = static_cast<uint>(columns.size());
    device.value.capacity = device.value.numEdges;
    if (cudaMalloc(&device.value.rowPtr,
                   offsets.size() * sizeof(std::uint32_t)) != cudaSuccess ||
        cudaMalloc(&device.value.rowInd,
                   rows.size() * sizeof(std::uint32_t)) != cudaSuccess ||
        cudaMalloc(&device.value.colInd,
                   columns.size() * sizeof(std::uint32_t)) != cudaSuccess) {
      return {{StatusCode::resource_exhausted,
               "KCGPU device graph allocation failed"},
              0, 0.0};
    }
    if (cudaMemcpy(device.value.rowPtr, offsets.data(),
                   offsets.size() * sizeof(std::uint32_t),
                   cudaMemcpyHostToDevice) != cudaSuccess ||
        cudaMemcpy(device.value.rowInd, rows.data(),
                   rows.size() * sizeof(std::uint32_t),
                   cudaMemcpyHostToDevice) != cudaSuccess ||
        cudaMemcpy(device.value.colInd, columns.data(),
                   columns.size() * sizeof(std::uint32_t),
                   cudaMemcpyHostToDevice) != cudaSuccess) {
      return {{StatusCode::execution_failed,
               "KCGPU device graph transfer failed"},
              0, 0.0};
    }

    const std::lock_guard<std::mutex> lock(kcgpu_mutex);
    graph::SingleGPU_Kclique<uint> algorithm(device_id, device.value);
    const auto started = std::chrono::steady_clock::now();
    // PIV-8-BE is the exact KCGPU configuration that passed validation.
    algorithm.findKclqueIncremental_node_pivot_async<8>(
        static_cast<int>(k), device.value, BlockWarp);
    algorithm.sync();
    const auto count = algorithm.result_count();
    const auto cuda_result = cudaGetLastError();
    const auto finished = std::chrono::steady_clock::now();
    algorithm.free();
    cudaStreamDestroy(algorithm.stream());
    if (cuda_result != cudaSuccess) {
      return {{StatusCode::execution_failed,
               std::string("KCGPU failed: ") +
                   cudaGetErrorString(cuda_result)},
              0, 0.0};
    }
    return {Status::success(), count,
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("KCGPU execution failed: ") + error.what()},
            0, 0.0};
  }
}

}  // namespace graphmine::detail
