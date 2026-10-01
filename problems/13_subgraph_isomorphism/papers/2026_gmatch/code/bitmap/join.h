#ifndef JOIN_BFS_H
#define JOIN_BFS_H

#include "candidate.h"
#include "mem_manager.h"

__host__ int *
set_beginning_partial_matchings(
    const Graph &Q,
    const Graph &G,
    const candidate_graph &cg,
    int &cnt
);

__host__ int *
set_beginning_partial_matchings_sym(
    const Graph &Q,
    const Graph &G,
    const candidate_graph &cg,
    int &cnt,
    const std::vector<uint32_t> &partial_order
);

void __global__
BFS_Extend(
    const Graph_GPU Q,
    const Graph_GPU G,
    const candidate_graph_GPU cg,
    MemManager *d_MM,
    int cur_query_vertex,
    int partial_offset,
    int partial_matching_cnt,
    int last_flag,
    int *d_error_flag
);

void __global__
BFS_Extend_sym(
    const Graph_GPU Q,
    const Graph_GPU G,
    const candidate_graph_GPU cg,
    MemManager *d_MM,
    int cur_query_vertex,
    int partial_offset,
    int last_flag,
    int *d_error_flag,
    int *d_partial_order
);

ull
join_bfs_dfs(
    const Graph &q,
    const Graph &g,
    const Graph_GPU &Q,
    const Graph_GPU &G,
    const candidate_graph &_cg,
    const candidate_graph_GPU &cg,
    const unsigned label_mask,
    const unsigned backward_mask,
    const int expected_init_num
);

ull
join_bfs_dfs_sym(
    const Graph &q,
    const Graph &g,
    const Graph_GPU &Q,
    const Graph_GPU &G,
    const candidate_graph &_cg,
    const candidate_graph_GPU &cg,
    const unsigned label_mask,
    const unsigned backward_mask,
    const int expected_init_num,
    const std::vector<uint32_t> &partial_order
);

#endif