#include "backends/k_core_backend.hpp"

#include <algorithm>
#include <chrono>
#include <limits>
#include <stdexcept>
#include <string>

#include <cuda_runtime.h>

#include "graph.h"
#include "gpu_memory_allocation.h"

// These are the original KCoreGPU buffer helpers and peeling kernels. Keeping
// them included in one CUDA translation unit avoids changing their launch and
// device logic while replacing only the file-oriented host boundary.
#include "buffer.cc"
#include "ours.cc"

namespace graphmine::detail {
namespace {

Status cuda_status(cudaError_t code, const char* operation) {
  if (code == cudaSuccess) {
    return Status::success();
  }
  return {StatusCode::execution_failed,
          std::string(operation) + ": " + cudaGetErrorString(code)};
}

class BackendGraph {
 public:
  explicit BackendGraph(const CsrGraph& graph) {
    graph_.neighbors = nullptr;
    graph_.neighbors_offset = nullptr;
    graph_.degrees = nullptr;
    if (graph.vertex_count() >
            static_cast<std::size_t>(std::numeric_limits<unsigned int>::max()) ||
        graph.neighbors.size() >
            static_cast<std::size_t>(std::numeric_limits<unsigned int>::max())) {
      throw std::invalid_argument("KCoreGPU uses 32-bit graph indices");
    }

    graph_.V = static_cast<unsigned int>(graph.vertex_count());
    graph_.E = static_cast<unsigned int>(graph.neighbors.size());
    graph_.AVG_DEGREE = graph_.V == 0 ? 0 : graph_.E / graph_.V;
    graph_.neighbors = new unsigned int[graph_.E];
    graph_.neighbors_offset = new unsigned int[graph_.V + 1];
    graph_.degrees = new unsigned int[graph_.V];
    graph_.kmax = 0;
    graph_.dmax = 0;

    for (unsigned int vertex = 0; vertex <= graph_.V; ++vertex) {
      if (graph.offsets[vertex] >
          static_cast<std::uint64_t>(std::numeric_limits<unsigned int>::max())) {
        throw std::invalid_argument("KCoreGPU CSR offset exceeds 32 bits");
      }
      graph_.neighbors_offset[vertex] =
          static_cast<unsigned int>(graph.offsets[vertex]);
      if (vertex < graph_.V) {
        graph_.degrees[vertex] = static_cast<unsigned int>(
            graph.offsets[vertex + 1] - graph.offsets[vertex]);
        graph_.dmax = std::max(graph_.dmax, graph_.degrees[vertex]);
      }
    }
    std::copy(graph.neighbors.begin(), graph.neighbors.end(),
              graph_.neighbors);
  }

  ::Graph& get() noexcept { return graph_; }

 private:
  ::Graph graph_;
};

}  // namespace

bool kcore_gpu_backend_compiled() noexcept { return true; }

KCoreBackendResult run_kcore_gpu(const CsrGraph& graph, int device_id) {
  if (graph.vertex_count() == 0) {
    return {Status::success(), {}, 0.0};
  }
  if (device_id < 0) {
    return {{StatusCode::invalid_argument,
             "CUDA device id must be non-negative"},
            {}, 0.0};
  }

  int device_count = 0;
  auto status = cuda_status(cudaGetDeviceCount(&device_count),
                            "cudaGetDeviceCount failed");
  if (!status.ok() || device_id >= device_count) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for KCoreGPU"},
            {}, 0.0};
  }
  status = cuda_status(cudaSetDevice(device_id), "cudaSetDevice failed");
  if (!status.ok()) {
    return {status, {}, 0.0};
  }

  try {
    BackendGraph owner(graph);
    auto& backend_graph = owner.get();
    G_pointers device_graph{};
    unsigned int* global_count = nullptr;
    unsigned int* buffer_tails = nullptr;
    unsigned int* global_buffers = nullptr;

    const auto cleanup = [&]() {
      if (device_graph.neighbors != nullptr) cudaFree(device_graph.neighbors);
      if (device_graph.neighbors_offset != nullptr)
        cudaFree(device_graph.neighbors_offset);
      if (device_graph.degrees != nullptr) cudaFree(device_graph.degrees);
      if (global_count != nullptr) cudaFree(global_count);
      if (buffer_tails != nullptr) cudaFree(buffer_tails);
      if (global_buffers != nullptr) cudaFree(global_buffers);
    };

    const auto allocate = [&](void** pointer, std::size_t bytes,
                              const char* operation) {
      const auto result = cuda_status(cudaMalloc(pointer, bytes), operation);
      if (!result.ok()) {
        cleanup();
        throw std::runtime_error(result.message());
      }
    };

    allocate(reinterpret_cast<void**>(&device_graph.neighbors),
             backend_graph.E * sizeof(unsigned int),
             "allocating KCoreGPU neighbors failed");
    allocate(reinterpret_cast<void**>(&device_graph.neighbors_offset),
             (backend_graph.V + 1ULL) * sizeof(unsigned int),
             "allocating KCoreGPU offsets failed");
    allocate(reinterpret_cast<void**>(&device_graph.degrees),
             backend_graph.V * sizeof(unsigned int),
             "allocating KCoreGPU degrees failed");
    device_graph.V = backend_graph.V;

    status = cuda_status(cudaMemcpy(device_graph.neighbors,
                                    backend_graph.neighbors,
                                    backend_graph.E * sizeof(unsigned int),
                                    cudaMemcpyHostToDevice),
                         "copying KCoreGPU neighbors failed");
    if (!status.ok()) {
      cleanup();
      return {status, {}, 0.0};
    }
    status = cuda_status(cudaMemcpy(device_graph.neighbors_offset,
                                    backend_graph.neighbors_offset,
                                    (backend_graph.V + 1ULL) *
                                        sizeof(unsigned int),
                                    cudaMemcpyHostToDevice),
                         "copying KCoreGPU offsets failed");
    if (!status.ok()) {
      cleanup();
      return {status, {}, 0.0};
    }
    status = cuda_status(cudaMemcpy(device_graph.degrees,
                                    backend_graph.degrees,
                                    backend_graph.V * sizeof(unsigned int),
                                    cudaMemcpyHostToDevice),
                         "copying KCoreGPU degrees failed");
    if (!status.ok()) {
      cleanup();
      return {status, {}, 0.0};
    }

    allocate(reinterpret_cast<void**>(&global_count), sizeof(unsigned int),
             "allocating KCoreGPU count failed");
    allocate(reinterpret_cast<void**>(&buffer_tails),
             BLK_NUMS * sizeof(unsigned int),
             "allocating KCoreGPU buffer tails failed");
    allocate(reinterpret_cast<void**>(&global_buffers),
             static_cast<std::size_t>(BLK_NUMS) * GLBUFFER_SIZE *
                 sizeof(unsigned int),
             "allocating KCoreGPU work buffers failed");
    cudaMemset(global_count, 0, sizeof(unsigned int));

    unsigned int level = 0;
    unsigned int count = 0;
    const auto started = std::chrono::steady_clock::now();
    while (count < backend_graph.V) {
      cudaMemset(buffer_tails, 0, BLK_NUMS * sizeof(unsigned int));
      selectNodesAtLevel1<<<BLK_NUMS, BLK_DIM>>>(
          device_graph.degrees, level, backend_graph.V, buffer_tails,
          global_buffers);
      processNodes1<<<BLK_NUMS, BLK_DIM>>>(
          device_graph, level, backend_graph.V, buffer_tails, global_buffers,
          global_count);
      status = cuda_status(cudaDeviceSynchronize(),
                           "KCoreGPU peeling kernel failed");
      if (!status.ok()) {
        cleanup();
        return {status, {}, 0.0};
      }
      status = cuda_status(cudaMemcpy(&count, global_count,
                                      sizeof(unsigned int),
                                      cudaMemcpyDeviceToHost),
                           "copying KCoreGPU progress failed");
      if (!status.ok()) {
        cleanup();
        return {status, {}, 0.0};
      }
      ++level;
    }
    const auto finished = std::chrono::steady_clock::now();

    std::vector<std::uint32_t> core_numbers(backend_graph.V);
    status = cuda_status(cudaMemcpy(core_numbers.data(), device_graph.degrees,
                                    backend_graph.V * sizeof(unsigned int),
                                    cudaMemcpyDeviceToHost),
                         "copying KCoreGPU result failed");
    cleanup();
    if (!status.ok()) {
      return {status, {}, 0.0};
    }

    const auto elapsed =
        std::chrono::duration<double, std::milli>(finished - started).count();
    return {Status::success(), std::move(core_numbers), elapsed};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("KCoreGPU execution failed: ") + error.what()},
            {}, 0.0};
  }
}

}  // namespace graphmine::detail
