#include "backends/maximum_clique_backend.hpp"

#include <algorithm>
#include <chrono>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <new>
#include <string>
#include <vector>

#include <cuda_runtime.h>

extern "C" {
#include "bitops.h"
#include "cudams.h"
#include "motzkin_cuda.h"
}

extern int cuda_device;

namespace graphmine::detail {

bool cuda_ms_backend_compiled() noexcept { return true; }

MaximumCliqueBackendResult run_cuda_ms(const CsrGraph& graph, int device_id) {
  if (graph.vertex_count() == 0) {
    return {Status::success(), {}, 0, 0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(INT_MAX)) {
    return {{StatusCode::unsupported,
             "CUDA-MS uses signed 32-bit vertex indices"},
            {}, 0, 0.0};
  }
  if (device_id < 0) {
    return {{StatusCode::invalid_argument,
             "CUDA device id must be non-negative"},
            {}, 0, 0.0};
  }

  int device_count = 0;
  if (cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for CUDA-MS"},
            {}, 0, 0.0};
  }
  if (cudaSetDevice(device_id) != cudaSuccess) {
    return {{StatusCode::backend_unavailable,
             "failed to select the requested CUDA device for CUDA-MS"},
            {}, 0, 0.0};
  }

  const auto n = static_cast<int>(graph.vertex_count());
  if (static_cast<std::uint64_t>(n) * static_cast<std::uint64_t>(n) >
      std::numeric_limits<std::size_t>::max()) {
    return {{StatusCode::resource_exhausted,
             "CUDA-MS dense adjacency matrix size overflow"},
            {}, 0, 0.0};
  }

  std::vector<std::unique_ptr<char[]>> rows;
  std::vector<char*> row_pointers;
  rows.reserve(n);
  row_pointers.reserve(n);
  try {
    for (int row = 0; row < n; ++row) {
      rows.push_back(std::make_unique<char[]>(static_cast<std::size_t>(n)));
      std::fill_n(rows.back().get(), n, char{0});
      row_pointers.push_back(rows.back().get());
    }
  } catch (const std::bad_alloc&) {
    return {{StatusCode::resource_exhausted,
             "CUDA-MS could not allocate its dense adjacency matrix"},
            {}, 0, 0.0};
  }

  for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    for (auto offset = graph.offsets[vertex];
         offset < graph.offsets[vertex + 1]; ++offset) {
      row_pointers[vertex][graph.neighbors[offset]] = 1;
    }
  }

  // CUDA-MS stores its selected device in an OpenMP thread-local global.
  // Setting it explicitly preserves the public execution option instead of
  // allowing the upstream random-device chooser to override the caller.
  cuda_device = device_id;
  quiet = 1;

  t_bitmask clique_mask = nullptr;
  t_bitmask upper_mask = nullptr;
  const auto started = std::chrono::steady_clock::now();
  graph_clique_cuda(&clique_mask, &upper_mask, row_pointers.data(), n, nullptr,
                    5, 0.001F, 0.5F, 5, MODE_REPL);
  const auto cuda_result = cudaDeviceSynchronize();
  const auto finished = std::chrono::steady_clock::now();
  if (cuda_result != cudaSuccess || clique_mask == nullptr) {
    if (clique_mask != nullptr) mask_free(clique_mask);
    if (upper_mask != nullptr) mask_free(upper_mask);
    return {{StatusCode::execution_failed,
             std::string("CUDA-MS failed: ") +
                 cudaGetErrorString(cuda_result)},
            {}, 0, 0.0};
  }

  MaximumCliqueBackendResult result;
  result.status = Status::success();
  for (int vertex = 0; vertex < n; ++vertex) {
    const auto cell = static_cast<std::size_t>(vertex) / MASK_CELL_SIZE;
    const auto bit = static_cast<unsigned int>(vertex) % MASK_CELL_SIZE;
    if ((clique_mask[cell] & (static_cast<t_maskcell>(1) << bit)) != 0) {
      result.clique.push_back(static_cast<VertexIndex>(vertex));
    }
  }
  result.relaxation_upper_size =
      upper_mask == nullptr ? 0U
                            : static_cast<std::uint32_t>(
                                  mask_size(upper_mask, n));
  result.elapsed_ms =
      std::chrono::duration<double, std::milli>(finished - started).count();
  mask_free(clique_mask);
  if (upper_mask != nullptr) mask_free(upper_mask);
  return result;
}

}  // namespace graphmine::detail
