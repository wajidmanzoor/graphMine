#include "backends/dynamic_triangle_backend.hpp"

#include <chrono>
#include <climits>
#include <cstdint>
#include <exception>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "tricount.h"

namespace graphmine::detail {

bool edtc_backend_compiled() noexcept { return true; }

DynamicTriangleBackendResult run_edtc(
    const CsrGraph& graph, const std::vector<DenseTriangleUpdate>& updates,
    int device_id) {
  if (updates.empty()) {
    return {Status::success(), 0, 0, 0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(UINT_MAX - 2U) ||
      graph.neighbors.size() > static_cast<std::size_t>(UINT_MAX - 2U) ||
      updates.size() > static_cast<std::size_t>(UINT_MAX - 2U)) {
    return {{StatusCode::unsupported,
             "EDTC uses unsigned 32-bit vertex, offset, and batch indices"},
            0, 0, 0.0};
  }

  int device_count = 0;
  if (device_id < 0 || cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for EDTC"},
            0, 0, 0.0};
  }

  try {
    // EDTC's validated pipeline assumes that each batch has at least one
    // deletion and one insertion.  Two new isolated vertices and their edge
    // provide a zero-triangle delete/reinsert pair, preserving the algorithm's
    // execution path for arbitrary non-empty user batches.
    const auto original_vertices =
        static_cast<std::uint32_t>(graph.vertex_count());
    const auto sentinel_source = original_vertices;
    const auto sentinel_target = original_vertices + 1U;

    std::vector<std::uint32_t> offsets(graph.offsets.begin(),
                                       graph.offsets.end());
    std::vector<std::uint32_t> neighbors(graph.neighbors.begin(),
                                         graph.neighbors.end());
    offsets.push_back(static_cast<std::uint32_t>(neighbors.size() + 1U));
    offsets.push_back(static_cast<std::uint32_t>(neighbors.size() + 2U));
    neighbors.push_back(sentinel_target);
    neighbors.push_back(sentinel_source);

    std::vector<char> types;
    std::vector<std::uint32_t> sources;
    std::vector<std::uint32_t> targets;
    types.reserve(updates.size() + 2U);
    sources.reserve(updates.size() + 2U);
    targets.reserve(updates.size() + 2U);
    for (const auto& update : updates) {
      types.push_back(update.insertion ? 'a' : 'd');
      sources.push_back(update.source);
      targets.push_back(update.target);
    }
    types.push_back('d');
    sources.push_back(sentinel_source);
    targets.push_back(sentinel_target);
    types.push_back('a');
    sources.push_back(sentinel_source);
    targets.push_back(sentinel_target);

    unsigned long long deleted = 0;
    unsigned long long inserted = 0;
    float delete_ms = 0.0F;
    float insert_ms = 0.0F;
    const auto started = std::chrono::steady_clock::now();
    graphmine_edtc_tricount(
        offsets.data(), neighbors.data(), static_cast<std::uint32_t>(device_id),
        static_cast<std::uint32_t>(types.size()), 1U, std::string{},
        original_vertices + 2U, static_cast<std::uint32_t>(neighbors.size()),
        types.data(), sources.data(), targets.data(), &deleted, &inserted,
        &delete_ms, &insert_ms);
    const auto finished = std::chrono::steady_clock::now();

    const auto cuda_result = cudaGetLastError();
    if (cuda_result != cudaSuccess) {
      return {{StatusCode::execution_failed,
               std::string("EDTC failed: ") +
                   cudaGetErrorString(cuda_result)},
              0, 0, 0.0};
    }
    return {Status::success(), static_cast<std::uint64_t>(deleted),
            static_cast<std::uint64_t>(inserted),
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("EDTC execution failed: ") + error.what()},
            0, 0, 0.0};
  }
}

}  // namespace graphmine::detail
