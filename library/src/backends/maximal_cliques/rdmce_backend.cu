#include "backends/maximal_cliques/backend.hpp"

#include <algorithm>
#include <chrono>
#include <limits>
#include <stdexcept>

#include <cuda_runtime.h>

#include "graph.h"
#include "kernels/BkPivotBitBalance.cuh"

namespace {

class CanonicalRdmceGraph final : public ::Graph {
 public:
  explicit CanonicalRdmceGraph(const graphmine::CsrGraph& graph) {
    if (graph.vertex_count() >
        static_cast<std::size_t>(std::numeric_limits<vid_t>::max())) {
      throw std::invalid_argument("RDMCE supports at most 2^32-1 vertices");
    }
    if (graph.neighbors.size() % 2U != 0U) {
      throw std::invalid_argument("RDMCE requires a symmetric undirected CSR");
    }

    name_ = "graphmine-canonical";
    num_vertices_ = graph.vertex_count();
    num_edges_ = graph.undirected_edge_count();
    V_.resize(num_vertices_);
    labels_.resize(num_vertices_);
    max_degree_ = 0;

    for (std::size_t vertex = 0; vertex < num_vertices_; ++vertex) {
      const auto begin = graph.offsets[vertex];
      const auto end = graph.offsets[vertex + 1];
      V_[vertex].assign(graph.neighbors.begin() + begin,
                        graph.neighbors.begin() + end);
      labels_[vertex] = static_cast<vid_t>(vertex);
      max_degree_ = std::max(max_degree_, V_[vertex].size());
    }
    degeneracy_ = max_degree_;
  }
};

}  // namespace

namespace graphmine::detail {

bool rdmce_backend_compiled() noexcept { return true; }

BackendCountResult run_rdmce_count(const CsrGraph& graph, int device_id) {
  if (graph.vertex_count() == 0) {
    return {Status::success(), 0, 0.0};
  }
  if (device_id < 0) {
    return {Status{StatusCode::invalid_argument,
                   "CUDA device id must be non-negative"},
            0, 0.0};
  }

  int device_count = 0;
  const auto count_status = cudaGetDeviceCount(&device_count);
  if (count_status != cudaSuccess || device_id >= device_count) {
    return {Status{StatusCode::backend_unavailable,
                   "requested CUDA device is unavailable for RDMCE"},
            0, 0.0};
  }

  const auto set_status = cudaSetDevice(device_id);
  if (set_status != cudaSuccess) {
    return {Status{StatusCode::backend_unavailable,
                   "failed to select the requested CUDA device for RDMCE"},
            0, 0.0};
  }

  try {
    CanonicalRdmceGraph backend_graph(graph);
    backend_graph.SortByOrder(OrderType::DEG);
    backend_graph.ConvertToCsr();

    const auto started = std::chrono::steady_clock::now();
    const auto count = BkSolverWrapper(backend_graph,
                                       static_cast<std::size_t>(device_id));
    const auto finished = std::chrono::steady_clock::now();
    const auto elapsed =
        std::chrono::duration<double, std::milli>(finished - started).count();
    return {Status::success(), static_cast<std::uint64_t>(count), elapsed};
  } catch (const std::exception& error) {
    return {Status{StatusCode::execution_failed,
                   std::string("RDMCE execution failed: ") + error.what()},
            0, 0.0};
  }
}

}  // namespace graphmine::detail
