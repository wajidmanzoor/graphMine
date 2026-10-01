#include "backends/k_clique_backend.hpp"

#include <algorithm>
#include <chrono>
#include <climits>
#include <cstdint>
#include <mutex>
#include <stdexcept>
#include <string>

#include <cuda_runtime.h>
#include <thrust/copy.h>
#include <thrust/execution_policy.h>
#include <thrust/sequence.h>

#include "utils.h"
#include "accessMode.cuh"

__global__ void set_validation(OffsetT* row_start,
                               std::uint8_t* valid_candidates,
                               std::uint32_t vertex_count,
                               std::uint32_t minimum_degree) {
  const auto thread = threadIdx.x + blockDim.x * blockIdx.x;
  for (std::uint32_t vertex = thread; vertex < vertex_count;
       vertex += blockDim.x * gridDim.x) {
    if (row_start[vertex + 1] - row_start[vertex] >= minimum_degree) {
      valid_candidates[vertex] = 1;
    }
  }
}

namespace graphmine::detail {
namespace {

std::mutex gamma_mutex;

void release_gamma_resources(CSRGraph& data_graph, EmbeddingList& embeddings,
                             access_mode_controller& access_controller,
                             bool embeddings_initialized,
                             bool access_initialized) noexcept {
  try {
    if (embeddings_initialized) embeddings.clean();
  } catch (...) {
  }
  try {
    if (access_initialized) access_controller.clean();
  } catch (...) {
  }
  try {
    data_graph.clean();
  } catch (...) {
  }
}

}  // namespace

bool gamma_kclique_backend_compiled() noexcept { return true; }

KCliqueBackendResult run_gamma_kclique(const CsrGraph& graph,
                                        std::uint32_t k,
                                        int device_id) {
  if (k < 3 || k > 5) {
    return {{StatusCode::unsupported,
             "the validated GAMMA path supports 3 <= k <= 5"},
            0, 0.0};
  }
  if (graph.vertex_count() < k) {
    return {Status::success(), 0, 0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(UINT_MAX) ||
      graph.neighbors.size() > static_cast<std::size_t>(UINT_MAX)) {
    return {{StatusCode::unsupported,
             "GAMMA uses unsigned 32-bit vertex and frontier indices"},
            0, 0.0};
  }

  std::size_t valid_roots = 0;
  for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    if (graph.offsets[vertex + 1] - graph.offsets[vertex] >= k - 1U) {
      ++valid_roots;
    }
  }
  if (valid_roots == 0) {
    return {Status::success(), 0, 0.0};
  }

  int device_count = 0;
  if (device_id < 0 || cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count || cudaSetDevice(device_id) != cudaSuccess) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for GAMMA"},
            0, 0.0};
  }

  const std::lock_guard<std::mutex> lock(gamma_mutex);
  CSRGraph data_graph;
  EmbeddingList embeddings;
  access_mode_controller access_controller;
  bool embeddings_initialized = false;
  bool access_initialized = false;
  KeyT* sequence = nullptr;
  KeyT* roots = nullptr;
  std::uint8_t* valid_candidates = nullptr;

  try {
    data_graph.memory_type = UNIFIED_MEM;
    data_graph.nnodes = static_cast<std::uint32_t>(graph.vertex_count());
    data_graph.nedges = static_cast<std::uint64_t>(graph.neighbors.size());

    check_cuda_error(cudaMalloc(
        reinterpret_cast<void**>(&data_graph.row_start),
        graph.offsets.size() * sizeof(OffsetT)));
    check_cuda_error(cudaMemcpy(data_graph.row_start, graph.offsets.data(),
                                graph.offsets.size() * sizeof(OffsetT),
                                cudaMemcpyHostToDevice));
    check_cuda_error(cudaMallocManaged(
        reinterpret_cast<void**>(&data_graph.edge_dst),
        graph.neighbors.size() * sizeof(KeyT)));
    check_cuda_error(cudaMemcpy(data_graph.edge_dst, graph.neighbors.data(),
                                graph.neighbors.size() * sizeof(KeyT),
                                cudaMemcpyHostToDevice));
    check_cuda_error(cudaMemAdvise(data_graph.edge_dst,
                                   graph.neighbors.size() * sizeof(KeyT),
                                   cudaMemAdviseSetReadMostly, device_id));
    check_cuda_error(cudaMalloc(
        reinterpret_cast<void**>(&data_graph.access_mode),
        graph.vertex_count() * sizeof(std::uint8_t)));
    check_cuda_error(cudaMemset(data_graph.access_mode, 0xff,
                               graph.vertex_count() * sizeof(std::uint8_t)));
    check_cuda_error(cudaDeviceSynchronize());

    log_set_quiet(1);
    const auto started = std::chrono::steady_clock::now();

    check_cuda_error(cudaMalloc(reinterpret_cast<void**>(&sequence),
                                graph.vertex_count() * sizeof(KeyT)));
    check_cuda_error(cudaMalloc(reinterpret_cast<void**>(&roots),
                                graph.vertex_count() * sizeof(KeyT)));
    check_cuda_error(cudaMemset(roots, 0xff,
                               graph.vertex_count() * sizeof(KeyT)));
    check_cuda_error(cudaMalloc(
        reinterpret_cast<void**>(&valid_candidates),
        graph.vertex_count() * sizeof(std::uint8_t)));
    check_cuda_error(cudaMemset(valid_candidates, 0,
                               graph.vertex_count() * sizeof(std::uint8_t)));

    set_validation<<<10000, 256>>>(data_graph.row_start, valid_candidates,
                                   data_graph.nnodes, k - 1U);
    thrust::sequence(thrust::device, sequence,
                     sequence + data_graph.nnodes);
    const auto root_count = static_cast<std::uint32_t>(
        thrust::copy_if(thrust::device, sequence,
                        sequence + data_graph.nnodes, valid_candidates,
                        roots, is_valid()) -
        roots);
    check_cuda_error(cudaDeviceSynchronize());
    check_cuda_error(cudaFree(sequence));
    sequence = nullptr;
    check_cuda_error(cudaFree(valid_candidates));
    valid_candidates = nullptr;

    embeddings_initialized = true;
    embeddings.init(root_count, k, UNIFIED_MEM, false);
    embeddings.copy_to_level(0, roots, 0, root_count);
    check_cuda_error(cudaFree(roots));
    roots = nullptr;

    access_initialized = true;
    access_controller.set_vertex_page_border(data_graph);

    emb_off_type count = 0;
    for (std::uint32_t level = 1; level < k; ++level) {
      std::uint64_t neighbors = 0;
      std::uint64_t ordered_neighbors = 0;
      for (std::uint8_t prior = 0; prior < level; ++prior) {
        neighbors |= static_cast<std::uint64_t>(prior) << (prior * 8U);
        ordered_neighbors |=
            static_cast<std::uint64_t>(prior) << (prior * 8U);
      }
      expand_constraint constraint(
          static_cast<node_data_type>(0xff),
          static_cast<std::uint8_t>(k - 1U), neighbors,
          static_cast<std::uint8_t>(level), static_cast<emb_order>(1),
          ordered_neighbors, static_cast<std::uint8_t>(level));
      count = expand_dynamic(data_graph, embeddings,
                             static_cast<int>(level), constraint,
                             level != k - 1U);
    }
    check_cuda_error(cudaDeviceSynchronize());
    const auto finished = std::chrono::steady_clock::now();

    release_gamma_resources(data_graph, embeddings, access_controller,
                            embeddings_initialized, access_initialized);
    return {Status::success(), static_cast<std::uint64_t>(count),
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    if (sequence != nullptr) cudaFree(sequence);
    if (roots != nullptr) cudaFree(roots);
    if (valid_candidates != nullptr) cudaFree(valid_candidates);
    release_gamma_resources(data_graph, embeddings, access_controller,
                            embeddings_initialized, access_initialized);
    return {{StatusCode::execution_failed,
             std::string("GAMMA execution failed: ") + error.what()},
            0, 0.0};
  }
}

}  // namespace graphmine::detail
