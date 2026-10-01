#include "backends/subgraph_isomorphism_backend.hpp"

#include <chrono>
#include <climits>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#define Graph GraphMineGmatchGraph
#define Graph_GPU GraphMineGmatchGraphGpu
#define candidate_graph GraphMineGmatchCandidateGraph
#define candidate_graph_GPU GraphMineGmatchCandidateGraphGpu
#define MemPool GraphMineGmatchMemPool
#define MemManager GraphMineGmatchMemManager
#define partial_props GraphMineGmatchPartialProps
#define idle_queue GraphMineGmatchIdleQueue
#define stk_elem_fixed GraphMineGmatchStackFixed
#define stk_elem_cand GraphMineGmatchStackCandidates
#define stk_elem GraphMineGmatchStackElement
#define const_edge_offset graphmine_gmatch_const_edge_offset
#define bitmap_offset graphmine_gmatch_bitmap_offset
#include "candidate.h"
#include "graph.h"
#include "join.h"
#undef bitmap_offset
#undef const_edge_offset
#undef stk_elem
#undef stk_elem_cand
#undef stk_elem_fixed
#undef idle_queue
#undef partial_props
#undef MemManager
#undef MemPool
#undef candidate_graph_GPU
#undef candidate_graph
#undef Graph_GPU
#undef Graph

namespace graphmine::detail {
namespace {

std::mutex gmatch_mutex;

std::vector<std::vector<int>> make_adjacency(const CsrGraph& graph) {
  std::vector<std::vector<int>> adjacency(graph.vertex_count());
  for (std::size_t vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    auto& row = adjacency[vertex];
    row.reserve(graph.offsets[vertex + 1] - graph.offsets[vertex]);
    for (auto edge = graph.offsets[vertex]; edge < graph.offsets[vertex + 1];
         ++edge) {
      row.push_back(static_cast<int>(graph.neighbors[edge]));
    }
  }
  return adjacency;
}

}  // namespace

bool gmatch_backend_compiled() noexcept { return true; }

SubgraphIsomorphismBackendResult run_gmatch(
    const CsrGraph& data_graph, const std::vector<int>& data_labels,
    const CsrGraph& query_graph, const std::vector<int>& query_labels,
    std::size_t initial_match_capacity, int device_id) {
  if (query_graph.vertex_count() == 0) {
    return {Status::success(), 1, 0.0};
  }
  if (query_graph.vertex_count() > data_graph.vertex_count()) {
    return {Status::success(), 0, 0.0};
  }
  if (query_graph.vertex_count() == 1) {
    std::uint64_t count = 0;
    for (const auto label : data_labels) {
      if (label == query_labels.front()) {
        ++count;
      }
    }
    return {Status::success(), count, 0.0};
  }
  if (initial_match_capacity == 0 ||
      initial_match_capacity > static_cast<std::size_t>(INT_MAX)) {
    return {{StatusCode::invalid_argument,
             "gMatch initial_match_capacity must fit a positive int"},
            0, 0.0};
  }

  try {
    std::lock_guard<std::mutex> lock(gmatch_mutex);
    cudaCheck(cudaSetDevice(device_id));
    cudaCheck(cudaDeviceSetCacheConfig(cudaFuncCachePreferShared));

    GraphMineGmatchGraph original_query(make_adjacency(query_graph),
                                        query_labels);
    std::vector<int> matching_order;
    original_query.generate_matching_order(matching_order);
    GraphMineGmatchGraph query(original_query, matching_order);
    GraphMineGmatchGraph data(make_adjacency(data_graph), data_labels);

    unsigned label_mask = 0;
    unsigned backward_mask = 0;
    query.generate_label_mask(label_mask);
    query.generate_backward_mask(backward_mask);

    int alpha = 0;
    std::vector<std::uint32_t> partial_order;
    alpha = query.restriction_generation(partial_order);

    const auto started = std::chrono::steady_clock::now();
    GraphMineGmatchCandidateGraph candidates(query, data);
    GraphMineGmatchCandidateGraphGpu candidates_gpu(candidates);
    GraphMineGmatchGraphGpu query_gpu(query, true);
    GraphMineGmatchGraphGpu data_gpu(data, false);

    unsigned long long raw_count = 0;
    if (alpha == 1) {
      raw_count = join_bfs_dfs(
          query, data, query_gpu, data_gpu, candidates,
          candidates_gpu, label_mask, backward_mask,
          static_cast<int>(initial_match_capacity));
    } else {
      raw_count = static_cast<unsigned long long>(alpha) *
                  join_bfs_dfs_sym(
                      query, data, query_gpu, data_gpu, candidates,
                      candidates_gpu, label_mask, backward_mask,
                      static_cast<int>(initial_match_capacity), partial_order);
    }
    cudaCheck(cudaDeviceSynchronize());
    const auto finished = std::chrono::steady_clock::now();

    query_gpu.deallocate();
    data_gpu.deallocate();
    candidates_gpu.deallocate();
    return {Status::success(), static_cast<std::uint64_t>(raw_count),
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("gMatch execution failed: ") + error.what()},
            0, 0.0};
  }
}

}  // namespace graphmine::detail
