#include "backends/k_clique_backend.hpp"

#include <algorithm>
#include <chrono>
#include <climits>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "graph.h"

unsigned long long k_clique_counting(Graph* graph, int k);

namespace graphmine::detail {
namespace {

std::mutex graphset_kclique_mutex;

}  // namespace

bool graphset_kclique_backend_compiled() noexcept { return true; }

KCliqueBackendResult run_graphset_kclique(const CsrGraph& graph,
                                          std::uint32_t k,
                                          int device_id) {
  if (k < 3 || k > 6) {
    return {{StatusCode::unsupported,
             "the validated GraphSet kernel supports 3 <= k <= 6"},
            0, 0.0};
  }
  if (graph.vertex_count() < k) {
    return {Status::success(), 0, 0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(INT_MAX) ||
      graph.undirected_edge_count() >
          static_cast<std::uint64_t>(LLONG_MAX)) {
    return {{StatusCode::unsupported,
             "GraphSet uses signed 32-bit vertices and signed 64-bit offsets"},
            0, 0.0};
  }

  int device_count = 0;
  if (device_id < 0 || cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count || cudaSetDevice(device_id) != cudaSuccess) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for GraphSet"},
            0, 0.0};
  }

  try {
    auto oriented = std::make_unique<::Graph>();
    oriented->v_cnt = static_cast<int>(graph.vertex_count());
    oriented->vertex = new std::int64_t[graph.vertex_count() + 1];

    std::vector<int> degrees(graph.vertex_count());
    for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
      degrees[vertex] = static_cast<int>(graph.offsets[vertex + 1] -
                                         graph.offsets[vertex]);
    }

    std::vector<int> forward_edges;
    forward_edges.reserve(graph.undirected_edge_count());
    std::size_t max_forward_degree = 0;
    for (VertexIndex source = 0; source < graph.vertex_count(); ++source) {
      oriented->vertex[source] =
          static_cast<std::int64_t>(forward_edges.size());
      for (auto offset = graph.offsets[source];
           offset < graph.offsets[source + 1]; ++offset) {
        const auto target = graph.neighbors[offset];
        if (degrees[source] < degrees[target] ||
            (degrees[source] == degrees[target] && source < target)) {
          forward_edges.push_back(static_cast<int>(target));
        }
      }
      max_forward_degree = std::max(
          max_forward_degree,
          forward_edges.size() -
              static_cast<std::size_t>(oriented->vertex[source]));
    }
    oriented->vertex[graph.vertex_count()] =
        static_cast<std::int64_t>(forward_edges.size());
    oriented->e_cnt = static_cast<std::int64_t>(forward_edges.size());
    oriented->edge = new int[forward_edges.size()];
    std::copy(forward_edges.begin(), forward_edges.end(), oriented->edge);

    // The original local stack reserves twenty 64-bit partitions.
    if (max_forward_degree > 20U * 64U) {
      return {{StatusCode::unsupported,
               "GraphSet oriented degree exceeds its validated local-stack capacity"},
              0, 0.0};
    }

    const std::lock_guard<std::mutex> lock(graphset_kclique_mutex);
    const auto started = std::chrono::steady_clock::now();
    const auto count = k_clique_counting(oriented.get(), static_cast<int>(k));
    const auto cuda_result = cudaDeviceSynchronize();
    const auto finished = std::chrono::steady_clock::now();
    if (cuda_result != cudaSuccess) {
      return {{StatusCode::execution_failed,
               std::string("GraphSet k-clique failed: ") +
                   cudaGetErrorString(cuda_result)},
              0, 0.0};
    }
    return {Status::success(), static_cast<std::uint64_t>(count),
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::bad_alloc&) {
    return {{StatusCode::resource_exhausted,
             "GraphSet k-clique host allocation failed"},
            0, 0.0};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("GraphSet k-clique failed: ") + error.what()},
            0, 0.0};
  }
}

}  // namespace graphmine::detail
