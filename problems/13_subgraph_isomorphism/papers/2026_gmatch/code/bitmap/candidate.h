#ifndef CANDIDATE_H
#define CANDIDATE_H

#include <queue>
#include <unordered_set>
#include "helper.h"
#include "graph.h"
#include "params.h"

extern __constant__ int const_edge_offset[32 * 32];

#ifdef BITMAP_SET_INTERSECTION
extern __constant__ int bitmap_offset[32 * 32];
#endif

class candidate_graph {
    std::vector<std::vector<bool>> B;

public:
    Graph &Q, &G;

    std::vector<std::vector<int>> cand;
    std::vector<std::vector<int>> cand_idx;

    int tot_cand_cnt;
    int cand_set_max_len;

    int query_vertex_cnt;
    int query_edge_cnt;
    int data_vertex_cnt;

    int h_edge_offset[32 * 32];
    std::vector<int> h_cg_array;
    std::vector<int> h_cg_offset;

    candidate_graph(Graph &, Graph &);

    ~candidate_graph() {}

    void
    refine();

    void
    refine_bfs(int u, int v, std::unordered_set<ull> &refined);

    int *
    h_get_candidates(int u1, int u2, int i, int &len) const {
        int *start = (int *)h_cg_offset.data() + h_edge_offset[u1 * query_vertex_cnt + u2];
        len = start[i + 1] - start[i];
        return (int *)h_cg_array.data() + start[i];
    }
};


class candidate_graph_GPU {
public:
    int *d_cand_set;
    int *d_cand_offset;
    int *d_cand_len_32;

    int query_vertex_cnt;
    int data_vertex_cnt;

    int *d_cg_offset;
    CandLen_t *d_cg_array;

#ifdef BITMAP_SET_INTERSECTION
    int *bitmap_array;
#endif

public:
    candidate_graph_GPU(const candidate_graph &cg);

    __device__ __forceinline__ CandLen_t *
    d_get_candidates(char u1, char u2, CandLen_t i, CandLen_t &len) const {
        int *start = d_cg_offset + const_edge_offset[u1 * query_vertex_cnt + u2];
        len = start[i + 1] - start[i];
        return d_cg_array + start[i];
    }

    __device__ __forceinline__ int
    d_get_candidates_offset(char u1, char u2, CandLen_t i, CandLen_t &len) const {
        int *start = d_cg_offset + const_edge_offset[u1 * query_vertex_cnt + u2];
        len = start[i + 1] - start[i];
        return start[i];
    }

    __device__ __forceinline__ int
    d_get_mapped_v(char u, CandLen_t i) const {
        int *cand_u = d_cand_set + d_cand_offset[u];
        return cand_u[i];
    }

#ifdef BITMAP_SET_INTERSECTION
    __device__ __forceinline__ bool
    d_check_existence(char u1, char u2, CandLen_t i, CandLen_t j) const {
        int bit_len = d_cand_len_32[u2];
        int *start = bitmap_array + bitmap_offset[u1 * query_vertex_cnt + u2] + i * bit_len;
        return start[j / 32] & (1 << (j % 32));
    }
#endif

    void
    deallocate() {
        cudaCheck(cudaFree(d_cand_set));
        cudaCheck(cudaFree(d_cand_offset));
        cudaCheck(cudaFree(d_cand_len_32));
        cudaCheck(cudaFree(d_cg_offset));
        cudaCheck(cudaFree(d_cg_array));
#ifdef BITMAP_SET_INTERSECTION
        cudaCheck(cudaFree(bitmap_array));
#endif
    }
};

#endif
