#include "backends/graph_motif_backend.hpp"

#include <algorithm>
#include <chrono>
#include <climits>
#include <cstdint>
#include <limits>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <vector>

#include <cuda_runtime.h>

// GraphSet is an application-style artifact whose types live in the global
// namespace. Keep its original implementation intact while giving this copy a
// backend-specific ABI so it can be linked beside the other library backends.
#define Bitmap GraphMineGraphsetMotifBitmap
#define DataLoader GraphMineGraphsetMotifDataLoader
#define DataType GraphMineGraphsetMotifDataType
#define DisjointSetUnion GraphMineGraphsetMotifDisjointSetUnion
#define Graph GraphMineGraphsetMotifGraph
#define Graphmpi GraphMineGraphsetMotifGraphmpi
#define LabeledGraph GraphMineGraphsetMotifLabeledGraph
#define MotifGenerator GraphMineGraphsetMotifGenerator
#define Pattern GraphMineGraphsetMotifPattern
#define PatternType GraphMineGraphsetMotifPatternType
#define Prefix GraphMineGraphsetMotifPrefix
#define Schedule_IEP GraphMineGraphsetMotifSchedule
#define VertexSet GraphMineGraphsetMotifVertexSet
#include "graph.h"
#undef VertexSet
#undef Schedule_IEP
#undef Prefix
#undef PatternType
#undef Pattern
#undef MotifGenerator
#undef LabeledGraph
#undef Graphmpi
#undef Graph
#undef DisjointSetUnion
#undef DataType
#undef DataLoader
#undef Bitmap

void graphmine_graphset_motif_counts(
    GraphMineGraphsetMotifGraph* graph, int pattern_size,
    std::vector<unsigned long long>& counts);

namespace graphmine::detail {
namespace {

std::mutex graphset_motif_mutex;

std::uint64_t count_triangles(const CsrGraph& graph) {
  std::uint64_t triangles = 0;
  for (VertexIndex source = 0; source < graph.vertex_count(); ++source) {
    for (auto offset = graph.offsets[source];
         offset < graph.offsets[source + 1]; ++offset) {
      const auto middle = graph.neighbors[offset];
      if (middle <= source) continue;
      for (auto other = graph.offsets[middle];
           other < graph.offsets[middle + 1]; ++other) {
        const auto target = graph.neighbors[other];
        if (target <= middle) continue;
        const auto first = graph.neighbors.begin() + graph.offsets[source];
        const auto last = graph.neighbors.begin() + graph.offsets[source + 1];
        if (std::binary_search(first, last, target)) ++triangles;
      }
    }
  }
  return triangles;
}

std::vector<std::uint64_t> common_order(
    std::uint32_t motif_size,
    const std::vector<unsigned long long>& graphset_counts) {
  if (motif_size == 3 && graphset_counts.size() == 2) {
    return {graphset_counts[0], graphset_counts[1]};
  }
  if (motif_size == 4 && graphset_counts.size() == 6) {
    // MotifGenerator emits clique, diamond, tailed triangle, 3-star,
    // 4-cycle, path. The facade's common order is star, path, tailed
    // triangle, cycle, diamond, clique.
    return {graphset_counts[3], graphset_counts[5], graphset_counts[2],
            graphset_counts[4], graphset_counts[1], graphset_counts[0]};
  }
  return {};
}

}  // namespace

bool graphset_motif_backend_compiled() noexcept { return true; }

GraphMotifBackendResult run_graphset_motifs(const CsrGraph& graph,
                                            std::uint32_t motif_size,
                                            int device_id) {
  const auto result_size = motif_size == 3 ? 2U : 6U;
  if (motif_size < 3 || motif_size > 4) {
    return {{StatusCode::unsupported,
             "the validated GraphSet motif path supports sizes 3 and 4"},
            {}, 0.0};
  }
  if (graph.vertex_count() < motif_size || graph.neighbors.empty()) {
    return {Status::success(), std::vector<std::uint64_t>(result_size, 0),
            0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(INT_MAX) ||
      graph.neighbors.size() >
          static_cast<std::size_t>(std::numeric_limits<std::int64_t>::max())) {
    return {{StatusCode::unsupported,
             "GraphSet uses signed 32-bit vertices and signed 64-bit offsets"},
            {}, 0.0};
  }

  std::size_t maximum_degree = 0;
  for (VertexIndex vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    maximum_degree = std::max(
        maximum_degree,
        static_cast<std::size_t>(graph.offsets[vertex + 1] -
                                 graph.offsets[vertex]));
  }
  if (maximum_degree > static_cast<std::size_t>(INT_MAX)) {
    return {{StatusCode::unsupported,
             "GraphSet uses signed 32-bit neighborhood sizes"},
            {}, 0.0};
  }

  int device_count = 0;
  if (device_id < 0 || cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count || cudaSetDevice(device_id) != cudaSuccess) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for GraphSet motifs"},
            {}, 0.0};
  }

  try {
    const auto triangle_count = count_triangles(graph);
    if (triangle_count >
        static_cast<std::uint64_t>(std::numeric_limits<long long>::max())) {
      return {{StatusCode::unsupported,
               "GraphSet's triangle statistic exceeds signed 64-bit range"},
              {}, 0.0};
    }

    auto original = std::make_unique<GraphMineGraphsetMotifGraph>();
    original->v_cnt = static_cast<std::int32_t>(graph.vertex_count());
    original->e_cnt = static_cast<std::int64_t>(graph.neighbors.size());
    original->tri_cnt = static_cast<long long>(triangle_count);
    original->vertex = new std::int64_t[graph.offsets.size()];
    original->edge = new std::int32_t[graph.neighbors.size()];
    std::copy(graph.offsets.begin(), graph.offsets.end(), original->vertex);
    std::copy(graph.neighbors.begin(), graph.neighbors.end(), original->edge);

    const std::lock_guard<std::mutex> lock(graphset_motif_mutex);
    GraphMineGraphsetMotifVertexSet::max_intersection_size =
        static_cast<int>(maximum_degree);
    std::vector<unsigned long long> raw_counts;
    const auto started = std::chrono::steady_clock::now();
    graphmine_graphset_motif_counts(original.get(),
                                    static_cast<int>(motif_size), raw_counts);
    const auto cuda_status = cudaDeviceSynchronize();
    const auto finished = std::chrono::steady_clock::now();
    if (cuda_status != cudaSuccess) {
      return {{StatusCode::execution_failed,
               std::string("GraphSet motif execution failed: ") +
                   cudaGetErrorString(cuda_status)},
              {}, 0.0};
    }
    auto counts = common_order(motif_size, raw_counts);
    if (counts.size() != result_size) {
      return {{StatusCode::internal_error,
               "GraphSet returned an unexpected motif count vector"},
              {}, 0.0};
    }
    return {Status::success(), std::move(counts),
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::bad_alloc&) {
    return {{StatusCode::resource_exhausted,
             "GraphSet motif host allocation failed"},
            {}, 0.0};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("GraphSet motif execution failed: ") + error.what()},
            {}, 0.0};
  }
}

}  // namespace graphmine::detail
