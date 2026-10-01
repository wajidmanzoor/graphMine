#include <vector>
#include <unordered_set>
#include "graph.h"
#include "candidate.h"

__constant__ int const_edge_offset[32 * 32];

#ifdef BITMAP_SET_INTERSECTION
__constant__ int bitmap_offset[32 * 32];
#endif

candidate_graph::candidate_graph(Graph &q, Graph &g) : Q(q), G(g) {
    tot_cand_cnt = 0;
    query_vertex_cnt = Q.vcount();
    query_edge_cnt = Q.ecount();
    data_vertex_cnt = G.vcount();
    cand.resize(query_vertex_cnt);

    for (auto &vec : cand) {
        vec.reserve(1000);
    }

    TIME_INIT();
    TIME_START();

    for (int u = 0; u < query_vertex_cnt; u++) {
        int label = Q.label(u);
        for (int v : G.label_vertex_mapping_[label]) {
            bool fail = false;
            for (auto p : Q.nlf_[u]) {
                int label = p.first;
                int count = p.second;
                if (count > G.nlf_[v][label]) {
                    fail = true;
                    break;
                }
            }
            if (!fail) {
                cand[u].emplace_back(v);
            }
        }
    }

    for (int i = 0; i < cand.size(); i++) {
        std::sort(cand[i].begin(), cand[i].end());
    }

    B.resize(Q.vcount());
    for (int u = 0; u < Q.vcount(); u++) {
        B[u].resize(G.vcount(), false);
        for (int v : cand[u]) {
            B[u][v] = true;
        }
    }

    // Refine candidate sets.
    refine();

    TIME_END();
    PRINT_LOCAL_TIME("Candidate Filtering");

    cand_set_max_len = 0;
    tot_cand_cnt = 0;

    for (int i = 0; i < cand.size(); i++) {
        tot_cand_cnt += cand[i].size();
        std::cout << "|C(" << i << ")| = " << cand[i].size() << std::endl;
        if (cand[i].size() > cand_set_max_len) {
            cand_set_max_len = cand[i].size();
        }
    }

    std::cout << "Total number of candidates: " << tot_cand_cnt << std::endl;
    std::cout << "Maximal size of candidate set: " << cand_set_max_len << std::endl;

#ifdef SHORT_CANDIDATE_SET
    if (cand_set_max_len > SHRT_MAX) {
        printf("Error: The length of the candidate set exceeds the maximum value of a `short` (%d).\n", SHRT_MAX);
        printf("Please comment out `#define SHORT_CANDIDATE_SET` and then recompile.\n");
        exit(-1);
    }
#endif

    // Store the index of each candidate
    cand_idx.resize(query_vertex_cnt);
    for (int u = 0; u < query_vertex_cnt; u++) {
        cand_idx[u].resize(data_vertex_cnt);
        for (int i = 0; i < cand[u].size(); i++) {
            cand_idx[u][cand[u][i]] = i;
        }
    }

    TIME_START();

    // Build candidate graph on the CPU.
    h_cg_offset.reserve(1e6);
    h_cg_array.reserve(1e6);

    for (int u1 = 0; u1 < query_vertex_cnt; u1++) {
        for (int u2 : Q.adj_[u1]) {
            if (u1 >= u2) {
                continue;
            }
            // for each query edge (u1, u2) where u1 < u2

            int tmp = h_cg_offset.size();
            h_edge_offset[u1 * query_vertex_cnt + u2] = tmp;
            h_cg_offset.resize(tmp + cand[u1].size() + 1);
            int *start = h_cg_offset.data() + tmp;

            int vi = 0;
            for (; vi < cand[u1].size(); vi++) {
                int v = cand[u1][vi];
                // When u1 is mapped to v, what are the candidates of u2?
                start[vi] = h_cg_array.size();

                // Intersect C(u2) and N(v)
                for (int vv : G.adj_[v]) {
                    if (B[u2][vv]) {
                        h_cg_array.push_back(cand_idx[u2][vv]);
                    }
                }
            }
            start[vi] = h_cg_array.size();
        }
    }

    TIME_END();
    PRINT_LOCAL_TIME("Build Candidate Graph");
}


void
candidate_graph::refine() {
    std::vector<int> bfs_order;
    Q.generate_bfs_order(bfs_order);

    for (int u : bfs_order) {
        for (int i = cand[u].size() - 1; i >= 0; i--) {
            int v = cand[u][i];
            for (int uu : Q.adj_[u]) {
                // Intersect C(uu) and N(v)
                unsigned result_length = 0;

                for (int vv : G.adj_[v]) {
                    if (B[uu][vv]) {
                        result_length = 1;
                        break;
                    }
                }

                if (result_length == 0) {
                    // Remove v from C(u)
                    auto it = std::lower_bound(cand[u].begin(), cand[u].end(), v);
                    cand[u].erase(it);
                    B[u][v] = 0;
                    break;
                }
            }
        }
    }

    for (int index = query_vertex_cnt - 1; index >= 0; index--) {
        int u = bfs_order[index];
        for (int i = cand[u].size() - 1; i >= 0; i--) {
            int v = cand[u][i];
            for (int uu : Q.adj_[u]) {
                // Intersect C(uu) and N(v)
                unsigned result_length = 0;

                for (int vv : G.adj_[v]) {
                    if (B[uu][vv]) {
                        result_length = 1;
                        break;
                    }
                }

                if (result_length == 0) {
                    // Remove v from C(u)
                    auto it = std::lower_bound(cand[u].begin(), cand[u].end(), v);
                    cand[u].erase(it);
                    B[u][v] = 0;
                    break;
                }
            }
        }
    }
}


candidate_graph_GPU::candidate_graph_GPU(const candidate_graph &cg) {
    int V = cg.query_vertex_cnt;
    this->query_vertex_cnt = cg.query_vertex_cnt;
    this->data_vertex_cnt = cg.data_vertex_cnt;

    int *h_cand_offset = (int *)malloc(sizeof(int) * (V + 1));
    h_cand_offset[0] = 0;
    h_cand_offset[V] = cg.tot_cand_cnt;
    for (int i = 1; i < V; i++) {
        h_cand_offset[i] = h_cand_offset[i - 1] + cg.cand[i - 1].size();
    }
    cudaCheck(cudaMalloc(&d_cand_offset, (V + 1) * sizeof(int)));
    cudaCheck(cudaMemcpy(d_cand_offset, h_cand_offset, (V + 1) * sizeof(int),
                         cudaMemcpyHostToDevice));

    cudaCheck(cudaMalloc(&d_cand_set, cg.tot_cand_cnt * sizeof(int)));
    for (int i = 0; i < V; i++) {
        cudaCheck(cudaMemcpy(d_cand_set + h_cand_offset[i], cg.cand[i].data(),
                             sizeof(int) * (h_cand_offset[i + 1] - h_cand_offset[i]),
                             cudaMemcpyHostToDevice));
    }

    for (int i = 0; i < V; i++) {
        h_cand_offset[i] = GMATCH_CEIL_DIV(h_cand_offset[i + 1] - h_cand_offset[i], 32);
    }
    cudaCheck(cudaMalloc(&d_cand_len_32, V * sizeof(int)));
    cudaCheck(cudaMemcpy(d_cand_len_32, h_cand_offset, V * sizeof(int), cudaMemcpyHostToDevice));

    free(h_cand_offset);
    printf("Candidate set moved to GPU.\n");

    cudaCheck(cudaMemcpyToSymbol(const_edge_offset, cg.h_edge_offset, cg.query_vertex_cnt * cg.query_vertex_cnt * sizeof(int)));
    cudaCheck(cudaMalloc(&d_cg_array, sizeof(CandLen_t) * cg.h_cg_array.size()));

#ifdef SHORT_CANDIDATE_SET
    cudaCheck(cudaMemcpy(d_cg_array, intVectorToShortVector(cg.h_cg_array).data(),
                         sizeof(short) * cg.h_cg_array.size(), cudaMemcpyHostToDevice));
#else
    cudaCheck(cudaMemcpy(d_cg_array, cg.h_cg_array.data(),
                         sizeof(int) * cg.h_cg_array.size(), cudaMemcpyHostToDevice));
#endif

    cudaCheck(cudaMalloc(&d_cg_offset, cg.h_cg_offset.size() * sizeof(int)));
    cudaCheck(cudaMemcpy(d_cg_offset, cg.h_cg_offset.data(), cg.h_cg_offset.size() * sizeof(int),
                         cudaMemcpyHostToDevice));

    std::cout << "Total number of candidate edges in the candidate graph: " << cg.h_cg_array.size() << std::endl;

#ifdef BITMAP_SET_INTERSECTION
    std::vector<int> h_bitmap_array;
    std::vector<int> h_bitmap_offset(32 * 32);

    for (int u0 = 0; u0 < cg.query_vertex_cnt; u0++) {
        for (int u1 : cg.Q.adj_[u0]) {
            if (u0 >= u1) {
                continue;
            }
            // for each query edge (u0, u1) where u0 < u1

            int bit_len = GMATCH_CEIL_DIV(cg.cand[u1].size(), 32);

            h_bitmap_offset[u0 * cg.query_vertex_cnt + u1] = h_bitmap_array.size();
            h_bitmap_array.resize(h_bitmap_array.size() + bit_len * cg.cand[u0].size());

            // for each candidate of u0
            for (int vi = 0; vi < cg.cand[u0].size(); vi++) {
                int start_offset = h_bitmap_offset[u0 * cg.query_vertex_cnt + u1] + vi * bit_len;

                int this_set_len = 0;
                int *this_set = cg.h_get_candidates(u0, u1, vi, this_set_len);
                for (int i_ = 0; i_ < this_set_len; i_++) {
                    int tmp = this_set[i_];
                    h_bitmap_array[start_offset + tmp / 32] |= (1 << (tmp % 32));
                }
            }
        }
    }

    cudaCheck(cudaMalloc(&bitmap_array, h_bitmap_array.size() * sizeof(int)));
    cudaCheck(cudaMemcpy(bitmap_array, h_bitmap_array.data(), h_bitmap_array.size() * sizeof(int), cudaMemcpyHostToDevice));
    cudaCheck(cudaMemcpyToSymbol(bitmap_offset, h_bitmap_offset.data(), 32 * 32 * sizeof(int)));
#endif

    int _cand_set_size = cg.tot_cand_cnt * sizeof(int);
    int _cand_offset_size = (V + 1) * sizeof(int);
    int _cg_offset_size = cg.h_cg_offset.size() * sizeof(int);
    int _cg_array_size = cg.h_cg_array.size() * sizeof(CandLen_t);
    int _edge_offset_size = 32 * 32 * sizeof(int);
    int _bitmap_offset_size = 0;
    int _bitmap_array_size = 0;

#ifdef BITMAP_SET_INTERSECTION
    _bitmap_offset_size = 32 * 32 * sizeof(int);
    _bitmap_array_size = h_bitmap_array.size() * sizeof(int);
#endif
    int total_size = _cand_set_size + _cand_offset_size + _cg_offset_size +
                     _cg_array_size + _edge_offset_size + _bitmap_offset_size + _bitmap_array_size;

    printf("+------------------------------+---------------+\n");
    printf("| Memory Allocation Details    | Size (bytes)  |\n");
    printf("+------------------------------+---------------+\n");
    printf("| Candidate Set                | %-13d |\n", _cand_set_size);
    printf("| Candidate Offset             | %-13d |\n", _cand_offset_size);
    printf("| Edge Offset                  | %-13d |\n", _edge_offset_size);
    printf("| Candidate Graph Offset       | %-13d |\n", _cg_offset_size);
    printf("| Candidate Graph Array        | %-13d |\n", _cg_array_size);
    printf("| Bitmap Offset                | %-13d |\n", _bitmap_offset_size);
    printf("| Bitmap Array                 | %-13d |\n", _bitmap_array_size);
    printf("+------------------------------+---------------+\n");
    printf("| Total (bytes)                | %-13d |\n", total_size);
    if (total_size < 1024 * 1024) {
        printf("| Total (KB)                   | %-13.2f |\n", total_size / 1024.0);
    }
    else {
        printf("| Total (MB)                   | %-13.2f |\n", total_size / 1024.0 / 1024.0);
    }
    printf("+------------------------------+---------------+\n");
}
