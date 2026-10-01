#include "backends/triangle_backend.hpp"

#include <chrono>
#include <climits>
#include <string>

#include <cuda_runtime.h>
#include <thrust/copy.h>
#include <thrust/fill.h>
#include <thrust/host_vector.h>

#include <tot.h>

namespace graphmine::detail {

bool tot_backend_compiled() noexcept { return true; }

TriangleBackendResult run_tot(const CsrGraph& graph, int device_id) {
  if (graph.vertex_count() < 3 || graph.undirected_edge_count() < 3) {
    return {Status::success(), 0, 0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(INT_MAX) ||
      graph.neighbors.size() > static_cast<std::size_t>(INT_MAX)) {
    return {{StatusCode::unsupported, "ToT uses signed 32-bit graph indices"},
            0, 0.0};
  }
  int device_count = 0;
  if (device_id < 0 || cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count || cudaSetDevice(device_id) != cudaSuccess) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for ToT"},
            0, 0.0};
  }

  try {
    const auto n = static_cast<int>(graph.vertex_count());
    const auto nnz = static_cast<int>(graph.neighbors.size());
    thrust::host_vector<int> rows(nnz);
    thrust::host_vector<int> columns(nnz);
    for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
      for (auto offset = graph.offsets[vertex];
           offset < graph.offsets[vertex + 1]; ++offset) {
        rows[offset] = static_cast<int>(vertex);
        columns[offset] = static_cast<int>(graph.neighbors[offset]);
      }
    }

    tot::CooMatrix<int, float, tot::device_memory> coo;
    coo.resize(n, n, nnz);
    thrust::copy(rows.begin(), rows.end(), coo.row_indices.begin());
    thrust::copy(columns.begin(), columns.end(), coo.column_indices.begin());
    thrust::fill(coo.values.begin(), coo.values.end(), 1.0F);

    const auto started = std::chrono::steady_clock::now();
    tot::BitmapCOO<int, float, tot::bmp64_t, 4, tot::device_memory>
        bitmap;
    tot::convert_coo2bmp(coo, bitmap);
    const auto directed_closed_walks =
        tot::count_triangles_on_tensors(bitmap, bitmap, bitmap);
    const auto cuda_result = cudaDeviceSynchronize();
    const auto finished = std::chrono::steady_clock::now();
    if (cuda_result != cudaSuccess) {
      return {{StatusCode::execution_failed,
               std::string("ToT failed: ") + cudaGetErrorString(cuda_result)},
              0, 0.0};
    }
    if (directed_closed_walks % 6 != 0) {
      return {{StatusCode::correctness_mismatch,
               "ToT symmetric count was not divisible by six"},
              0, 0.0};
    }
    const auto elapsed =
        std::chrono::duration<double, std::milli>(finished - started).count();
    return {Status::success(),
            static_cast<std::uint64_t>(directed_closed_walks / 6), elapsed};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("ToT execution failed: ") + error.what()},
            0, 0.0};
  }
}

}  // namespace graphmine::detail
