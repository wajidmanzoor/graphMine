#include "backends/maximal_biclique_backend.hpp"

#include <algorithm>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <cuda_runtime.h>

// cuMBE is header-based. These are the original initialization and enumeration
// kernels; GraphMine replaces only the executable/file boundary around them.
#include <src/header.cuh>
#include <src/global_extension.cuh>
#include <src/mbe_cuMBE.cuh>

namespace graphmine::detail {
namespace {

std::mutex cumbe_mutex;

void check_cuda(cudaError_t code, const char* operation) {
  if (code != cudaSuccess) {
    throw std::runtime_error(std::string(operation) + ": " +
                             cudaGetErrorString(code));
  }
}

class ManagedArena {
 public:
  ManagedArena() = default;
  ManagedArena(const ManagedArena&) = delete;
  ManagedArena& operator=(const ManagedArena&) = delete;

  ~ManagedArena() {
    for (auto it = allocations_.rbegin(); it != allocations_.rend(); ++it) {
      cudaFree(*it);
    }
  }

  template <typename T>
  T* allocate(std::size_t count) {
    if (count == 0) {
      return nullptr;
    }
    if (count > std::numeric_limits<std::size_t>::max() / sizeof(T)) {
      throw std::overflow_error("cuMBE allocation size overflow");
    }
    T* pointer = nullptr;
    check_cuda(cudaMallocManaged(reinterpret_cast<void**>(&pointer),
                                 sizeof(T) * count),
               "allocating cuMBE managed memory");
    allocations_.push_back(pointer);
    return pointer;
  }

 private:
  std::vector<void*> allocations_;
};

struct HostBipartiteGraph {
  int num_l = 0;
  int num_r = 0;
  int num_edges = 0;
  std::vector<Node> node_l;
  std::vector<int> edge_l;
  std::vector<Node> node_r;
  std::vector<int> edge_r;
};

HostBipartiteGraph prepare_graph(const BipartiteCsrGraph& input) {
  const auto left_count = static_cast<std::size_t>(input.left_vertex_count);
  const auto right_count = static_cast<std::size_t>(input.right_vertex_count);
  if (input.left_offsets.size() != left_count + 1 ||
      input.left_offsets.front() != 0 ||
      input.left_offsets.back() != input.right_neighbors.size()) {
    throw std::invalid_argument("invalid bipartite CSR offsets");
  }
  if (input.right_neighbors.size() >
      static_cast<std::size_t>(std::numeric_limits<int>::max())) {
    throw std::invalid_argument("cuMBE uses signed 32-bit edge indices");
  }

  std::vector<Node> left_nodes(left_count);
  std::vector<int> left_edges;
  left_edges.reserve(input.right_neighbors.size());
  std::vector<std::uint32_t> right_degrees(right_count, 0);
  for (std::size_t left = 0; left < left_count; ++left) {
    const auto begin = input.left_offsets[left];
    const auto end = input.left_offsets[left + 1];
    if (end < begin || end > input.right_neighbors.size()) {
      throw std::invalid_argument("invalid bipartite CSR row");
    }
    left_nodes[left] = {static_cast<int>(begin),
                        static_cast<int>(end - begin)};
    for (auto offset = begin; offset < end; ++offset) {
      const auto right = input.right_neighbors[offset];
      if (right >= right_count) {
        throw std::invalid_argument("bipartite neighbor is out of range");
      }
      left_edges.push_back(static_cast<int>(right));
      ++right_degrees[right];
    }
  }

  std::vector<Node> right_nodes(right_count);
  std::vector<std::size_t> cursor(right_count, 0);
  std::size_t offset = 0;
  for (std::size_t right = 0; right < right_count; ++right) {
    right_nodes[right] = {static_cast<int>(offset),
                          static_cast<int>(right_degrees[right])};
    cursor[right] = offset;
    offset += right_degrees[right];
  }
  std::vector<int> right_edges(input.right_neighbors.size());
  for (std::size_t left = 0; left < left_count; ++left) {
    for (auto edge = input.left_offsets[left];
         edge < input.left_offsets[left + 1]; ++edge) {
      const auto right = input.right_neighbors[edge];
      right_edges[cursor[right]++] = static_cast<int>(left);
    }
  }

  HostBipartiteGraph output;
  output.num_edges = static_cast<int>(left_edges.size());
  // The original executable transposes when its candidate side is larger.
  // Building both directions in memory lets us make the same choice directly.
  if (left_count <= right_count) {
    output.num_r = static_cast<int>(left_count);
    output.num_l = static_cast<int>(right_count);
    output.node_r = std::move(left_nodes);
    output.edge_r = std::move(left_edges);
    output.node_l = std::move(right_nodes);
    output.edge_l = std::move(right_edges);
  } else {
    output.num_r = static_cast<int>(right_count);
    output.num_l = static_cast<int>(left_count);
    output.node_r = std::move(right_nodes);
    output.edge_r = std::move(right_edges);
    output.node_l = std::move(left_nodes);
    output.edge_l = std::move(left_edges);
  }
  return output;
}

template <typename T>
void fill_values(T* destination, std::size_t count, T value) {
  std::fill(destination, destination + count, value);
}

}  // namespace

bool cumbe_backend_compiled() noexcept { return true; }

MaximalBicliqueBackendResult run_cumbe(const BipartiteCsrGraph& input,
                                       int device_id) {
  if (input.left_vertex_count == 0 || input.right_vertex_count == 0 ||
      input.right_neighbors.empty()) {
    return {Status::success(), 0, 0.0};
  }
  if (input.left_vertex_count >
          static_cast<std::uint32_t>(std::numeric_limits<int>::max()) ||
      input.right_vertex_count >
          static_cast<std::uint32_t>(std::numeric_limits<int>::max())) {
    return {{StatusCode::unsupported,
             "cuMBE uses signed 32-bit vertex indices"},
            0, 0.0};
  }

  try {
    const auto host = prepare_graph(input);
    std::lock_guard<std::mutex> lock(cumbe_mutex);
    check_cuda(cudaSetDevice(device_id), "selecting the cuMBE CUDA device");

    cudaDeviceProp properties{};
    check_cuda(cudaGetDeviceProperties(&properties, device_id),
               "querying the cuMBE CUDA device");
    if (!properties.cooperativeLaunch) {
      return {{StatusCode::unsupported,
               "cuMBE requires CUDA cooperative-kernel launch support"},
              0, 0.0};
    }
    if (properties.maxThreadsPerBlock < NUM_THDS) {
      return {{StatusCode::unsupported,
               "cuMBE requires at least 512 threads per block"},
              0, 0.0};
    }

    int blocks_per_sm = 0;
    check_cuda(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &blocks_per_sm, CUDA_MBE_cuMBE, NUM_THDS, 0),
               "computing cuMBE cooperative occupancy");
    const int block_count =
        std::max(1, std::min(NUM_BLKS,
                             properties.multiProcessorCount * blocks_per_sm));
    const std::size_t l = static_cast<std::size_t>(host.num_l);
    const std::size_t r = static_cast<std::size_t>(host.num_r);
    const std::size_t blocks = static_cast<std::size_t>(block_count);
    if (l > std::numeric_limits<std::size_t>::max() / blocks ||
        r > std::numeric_limits<std::size_t>::max() / blocks) {
      return {{StatusCode::resource_exhausted,
               "cuMBE workspace size overflow"},
              0, 0.0};
    }

    ManagedArena memory;
    int* num_l = memory.allocate<int>(1);
    int* num_r = memory.allocate<int>(1);
    int* num_edges = memory.allocate<int>(1);
    int* num_mb = memory.allocate<int>(1);
    long long* time_section = memory.allocate<long long>(NUM_CLK);
    *num_l = host.num_l;
    *num_r = host.num_r;
    *num_edges = host.num_edges;
    *num_mb = 0;
    fill_values(time_section, NUM_CLK, 0LL);

    Node* node_l = memory.allocate<Node>(l);
    int* edge_l = memory.allocate<int>(host.edge_l.size());
    Node* node_r = memory.allocate<Node>(r);
    int* edge_r = memory.allocate<int>(host.edge_r.size());
    std::copy(host.node_l.begin(), host.node_l.end(), node_l);
    std::copy(host.edge_l.begin(), host.edge_l.end(), edge_l);
    std::copy(host.node_r.begin(), host.node_r.end(), node_r);
    std::copy(host.edge_r.begin(), host.edge_r.end(), edge_r);

    int* u2L = memory.allocate<int>(l);
    int* v2P = memory.allocate<int>(r);
    int* v2Q = memory.allocate<int>(r);
    int* L = memory.allocate<int>(l);
    int* R = memory.allocate<int>(r);
    int* P = memory.allocate<int>(r);
    int* Q = memory.allocate<int>(r);
    int* x = memory.allocate<int>(r);
    int* L_lp = memory.allocate<int>(r);
    int* R_lp = memory.allocate<int>(r);
    int* P_lp = memory.allocate<int>(r);
    int* Q_lp = memory.allocate<int>(r);
    int* L_buf = memory.allocate<int>(l);
    int* num_N_u = memory.allocate<int>(r);
    int* pre_min = memory.allocate<int>(r);

    for (std::size_t i = 0; i < l; ++i) {
      u2L[i] = L[i] = static_cast<int>(i);
      L_buf[i] = 0;
    }
    for (std::size_t i = 0; i < r; ++i) {
      v2P[i] = v2Q[i] = R[i] = P[i] = Q[i] = static_cast<int>(i);
      x[i] = -1;
      L_lp[i] = host.num_l;
      R_lp[i] = 0;
      P_lp[i] = host.num_r;
      Q_lp[i] = 0;
      num_N_u[i] = 0;
      pre_min[i] = 1;
    }

    int* g_u2L = memory.allocate<int>(l * blocks);
    int* g_v2P = memory.allocate<int>(r * blocks);
    int* g_v2Q = memory.allocate<int>(r * blocks);
    int* g_L = memory.allocate<int>(l * blocks);
    int* g_R = memory.allocate<int>(r * blocks);
    int* g_P = memory.allocate<int>(r * blocks);
    int* g_Q = memory.allocate<int>(r * blocks);
    int* g_x = memory.allocate<int>(r * blocks);
    int* g_L_lp = memory.allocate<int>(r * blocks);
    int* g_R_lp = memory.allocate<int>(r * blocks);
    int* g_P_lp = memory.allocate<int>(r * blocks);
    int* g_Q_lp = memory.allocate<int>(r * blocks);
    int* g_L_buf = memory.allocate<int>(l * blocks);
    int* g_num_N_u = memory.allocate<int>(r * blocks);
    int* g_pre_min = memory.allocate<int>(r * blocks);
    int* ori_P = memory.allocate<int>(r);
    int* ori_P1 = memory.allocate<int>(r * blocks);
    int* ori_Q1 = memory.allocate<int>(r * blocks);
    int* ori_L1 = memory.allocate<int>(l * blocks);
    int* P_ptr1 = memory.allocate<int>(blocks);
    int* fix_P_ptr1 = memory.allocate<int>(blocks);
    int* fix_Q_ptr1 = memory.allocate<int>(blocks);

    dim3 grid(block_count, 1, 1);
    dim3 block(NUM_THDS, 1, 1);
    void* extension_args[] = {
        &g_u2L, &g_v2P, &g_v2Q, &g_L, &g_R, &g_P, &g_Q,
        &g_x, &g_L_lp, &g_R_lp, &g_P_lp, &g_Q_lp, &g_L_buf,
        &g_num_N_u, &g_pre_min, &u2L, &v2P, &v2Q, &L, &R, &P, &Q,
        &x, &L_lp, &R_lp, &P_lp, &Q_lp, &L_buf, &num_N_u, &pre_min,
        &num_l, &num_r};

    check_cuda(cudaLaunchCooperativeKernel(
                   reinterpret_cast<void*>(CUDA_GLOBAL_EXTENSION), grid,
                   block, extension_args),
               "launching cuMBE workspace initialization");
    check_cuda(cudaDeviceSynchronize(),
               "initializing the cuMBE workspace");
    my_memset_sort(ori_P, 0, host.num_r, node_r);

    void* mbe_args[] = {
        &num_l, &num_r, &num_edges, &node_l, &edge_l, &node_r, &edge_r,
        &g_u2L, &g_v2P, &g_v2Q, &g_L, &g_R, &g_P, &g_Q, &g_x,
        &g_L_lp, &g_R_lp, &g_P_lp, &g_Q_lp, &g_L_buf, &g_num_N_u,
        &g_pre_min, &ori_P, &ori_P1, &ori_Q1, &ori_L1, &P_ptr1,
        &fix_P_ptr1, &fix_Q_ptr1, &num_mb, &time_section};

    const auto started = std::chrono::steady_clock::now();
    check_cuda(cudaLaunchCooperativeKernel(
                   reinterpret_cast<void*>(CUDA_MBE_cuMBE), grid, block,
                   mbe_args),
               "launching cuMBE");
    check_cuda(cudaDeviceSynchronize(), "executing cuMBE");
    const auto finished = std::chrono::steady_clock::now();
    if (*num_mb < 0) {
      return {{StatusCode::resource_exhausted,
               "cuMBE's signed 32-bit result counter overflowed"},
              0, 0.0};
    }
    return {Status::success(), static_cast<std::uint64_t>(*num_mb),
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("cuMBE execution failed: ") + error.what()},
            0, 0.0};
  }
}

}  // namespace graphmine::detail
