#include "join.h"
#include "candidate.h"
#include "params.h"


__host__ int *
set_beginning_partial_matchings(
    const Graph &Q,
    const Graph &G,
    const candidate_graph &cg,
    int &cnt
) {

    const int u0 = 0;
    const int u1 = 1;
    assert(Q.is_adjacent(u0, u1));

    std::vector<std::pair<int, int>> h_beginning_partial_matching;
    h_beginning_partial_matching.reserve(1e3);

    for (int i = 0; i < cg.cand[u0].size(); i++) {
        int this_len = 0;
        int *this_set = cg.h_get_candidates(u0, u1, i, this_len);
        for (int j = 0; j < this_len; j++) {
            h_beginning_partial_matching.emplace_back(i, this_set[j]);
        }
    }

    int beginning_partial_matching_cnt = h_beginning_partial_matching.size();

    if (beginning_partial_matching_cnt == 0) {
        cnt = 0;
        return nullptr;
    }

    int *d_dst = nullptr;
    cudaCheck(cudaMalloc(&d_dst, sizeof(std::pair<int, int>) * beginning_partial_matching_cnt));
    cudaCheck(cudaMemcpy(d_dst, h_beginning_partial_matching.data(),
                         sizeof(std::pair<int, int>) * beginning_partial_matching_cnt,
                         cudaMemcpyHostToDevice));
    printf("%d beginning partial results have been moved to the GPU.\n", beginning_partial_matching_cnt);

    cnt = beginning_partial_matching_cnt;

    return d_dst;
}


__host__ int *
set_beginning_partial_matchings_sym(
    const Graph &Q,
    const Graph &G,
    const candidate_graph &cg,
    int &cnt,
    const std::vector<uint32_t> &partial_order
) {

    const int u0 = 0;
    const int u1 = 1;
    assert(Q.is_adjacent(u0, u1));

    std::vector<std::pair<int, int>> h_beginning_partial_matching;
    h_beginning_partial_matching.reserve(1e3);

    if (partial_order[u0] & (1 << u1)) {
        for (int i = 0; i < cg.cand[u0].size(); i++) {
            int this_len = 0;
            int *this_set = cg.h_get_candidates(u0, u1, i, this_len);
            for (int j = 0; j < this_len; j++) {
                if (cg.cand[u0][i] > cg.cand[u1][this_set[j]]) {
                    h_beginning_partial_matching.emplace_back(i, this_set[j]);
                }
            }
        }
    }
    else {
        for (int i = 0; i < cg.cand[u0].size(); i++) {
            int this_len = 0;
            int *this_set = cg.h_get_candidates(u0, u1, i, this_len);
            for (int j = 0; j < this_len; j++) {
                h_beginning_partial_matching.emplace_back(i, this_set[j]);
            }
        }
    }

    int beginning_partial_matching_cnt = h_beginning_partial_matching.size();

    if (beginning_partial_matching_cnt == 0) {
        cnt = 0;
        return nullptr;
    }

    int *d_dst = nullptr;
    cudaCheck(cudaMalloc(&d_dst, sizeof(std::pair<int, int>) * beginning_partial_matching_cnt));
    cudaCheck(cudaMemcpy(d_dst, h_beginning_partial_matching.data(),
                         sizeof(std::pair<int, int>) * beginning_partial_matching_cnt,
                         cudaMemcpyHostToDevice));
    printf("%d beginning partial results have been moved to the GPU.\n", beginning_partial_matching_cnt);

    cnt = beginning_partial_matching_cnt;

    return d_dst;
}


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
) {

    /**
     * After the function ends, the values of prev_head and blk_write_cnt are retained for the next call
     * and cached in shared memory to reduce global memory access.
     */

    __shared__ int shared_blk_write_cnt[warpsPerBlock];
    __shared__ int *shared_prev_head[warpsPerBlock];

    int warp_id = (threadIdx.x + blockDim.x * blockIdx.x) / warpSize;
    char lane_id = (threadIdx.x + blockDim.x * blockIdx.x) % warpSize;
    char warp_id_within_blk = warp_id % warpsPerBlock;

    __shared__ CandLen_t *s_nbr_set[warpsPerBlock * QVMAX];
    __shared__ CandLen_t s_nbr_len[warpsPerBlock * QVMAX];
    __shared__ int s_prev_mapped_v[warpsPerBlock * QVMAX];

    CandLen_t **bk_nbr_set = s_nbr_set + warp_id_within_blk * QVMAX;
    CandLen_t *bk_nbr_len = s_nbr_len + warp_id_within_blk * QVMAX;
    int bk_nbr_cnt = 0;

    if (lane_id == 0) {
        shared_prev_head[warp_id_within_blk] = d_MM->prev_head[warp_id];
        shared_blk_write_cnt[warp_id_within_blk] = d_MM->blk_write_cnt[warp_id];
    }
    __syncwarp();

    // If last_flag is 1, it indicates this is the last call to BFS_Extend
    // Record all partial matchings not yet recorded in d_MM
    if (last_flag == 1) {
        if (lane_id == 0) {
            if (shared_blk_write_cnt[warp_id_within_blk] > 0) {
                // Use partial_offset to temporarily denote the length of partial matching
                d_MM->add_new_props(shared_prev_head[warp_id_within_blk], partial_offset, shared_blk_write_cnt[warp_id_within_blk]);
            }
            d_MM->prev_head[warp_id] = nullptr;
            d_MM->blk_write_cnt[warp_id] = 0;
        }
        return;
    }

    // Assign partial matching to each warp
    if (warp_id + partial_offset >= partial_matching_cnt) {
        return;
    }

    int *this_partial_matching = nullptr;
    unsigned int ptr_low = 0, ptr_high = 0;
    if (lane_id == 0) {
        this_partial_matching = d_MM->get_partial(warp_id + partial_offset);
        unsigned long long ptr_val = (unsigned long long)this_partial_matching;
        ptr_low = (unsigned int)(ptr_val & 0xFFFFFFFF);
        ptr_high = (unsigned int)(ptr_val >> 32);
    }
    ptr_low = __shfl_sync(FULL_MASK, ptr_low, 0);
    ptr_high = __shfl_sync(FULL_MASK, ptr_high, 0);
    this_partial_matching = (int *)(((unsigned long long)ptr_high << 32) | ptr_low);

    int *prev_mapped_v = s_prev_mapped_v + warp_id_within_blk * QVMAX;
    if (lane_id < cur_query_vertex) {
        prev_mapped_v[lane_id] = cg.d_get_mapped_v(lane_id, this_partial_matching[lane_id]);
    }
    __syncwarp();

    // Each block can write a maximum number of partial matchings
    const int blk_partial_max_num = memPoolBlockIntNum / (cur_query_vertex + 1);
    const unsigned bn_mask_u = Q.d_bknbrs_[cur_query_vertex];

    unsigned bn_mask = bn_mask_u;
    char first_uu = __ffs(bn_mask) - 1;
    bn_mask &= ~(1u << first_uu);

    CandLen_t min_len = 0;
    CandLen_t *min_set = cg.d_get_candidates(first_uu, cur_query_vertex, this_partial_matching[first_uu], min_len);

    bk_nbr_set[0] = min_set;
    bk_nbr_len[0] = min_len;
    bk_nbr_cnt = 1;

    while (bn_mask) {
        char uu = __ffs(bn_mask) - 1;
        bn_mask &= ~(1u << uu);
        CandLen_t this_len = 0;
        CandLen_t *this_set = cg.d_get_candidates(uu, cur_query_vertex, this_partial_matching[uu], this_len);

        if (this_len < min_len) {
            min_len = this_len;
            min_set = this_set;

            bk_nbr_set[bk_nbr_cnt] = bk_nbr_set[0];
            bk_nbr_len[bk_nbr_cnt] = bk_nbr_len[0];
            bk_nbr_cnt++;

            bk_nbr_set[0] = min_set;
            bk_nbr_len[0] = min_len;
        }
        else {
            bk_nbr_set[bk_nbr_cnt] = this_set;
            bk_nbr_len[bk_nbr_cnt] = this_len;
            bk_nbr_cnt++;
        }
    }

    // Ensure there is one memory block for each warp
    if (lane_id == 0 && shared_prev_head[warp_id_within_blk] == nullptr) {
        shared_prev_head[warp_id_within_blk] = d_MM->mempool_to_write()->alloc();
        shared_blk_write_cnt[warp_id_within_blk] = 0;
    }
    __syncwarp();

    // Compute extendable candidate set
    // Each thread in the warp is responsible for one candidate, and handles the next candidate with a step size of 32
    for (int t = lane_id; t < min_len; t += warpSize) {
        // For each vertex v in min_set
        CandLen_t v = min_set[t];
        bool flag = true;
        // Make sure that the real v has not been mapped before
        int real_v = cg.d_get_mapped_v(cur_query_vertex, v);
        for (char j = 0; j < cur_query_vertex; j++) {
            if (prev_mapped_v[j] == real_v) {
                flag = false;
                break;
            }
        }

        for (int k = 1; flag && k < bk_nbr_cnt; k++) {
            flag = binary_search<CandLen_t>(bk_nbr_set[k], bk_nbr_len[k], v);
        }
        __syncwarp();

        // Use ballot_sync to collect flag values from all threads and generate a mask
        unsigned int flag_mask = __ballot_sync(FULL_MASK, flag);
        // Use popc to count the number of bits set to 1 in the mask, i.e., the total number of threads with flag true
        // unsigned int flag_cnt = __popc(flag_mask);

        // flag_idx indicates the position of each thread in its warp where flag == true
        // flag_idx starts counting from 0
        // For threads with flag == false, flag_idx is meaningless
        char flag_idx = __popc(flag_mask & ((1 << lane_id) - 1));

        // For the current process, it will write partial matching to a block that already has thread_old_cnt partial matchings
        int thread_old_cnt = shared_blk_write_cnt[warp_id_within_blk] + flag_idx;
        // Indicates whether the current process needs to write the partial matching to a new block instead of the old one
        bool thread_need_new_blk = false;

        // rest_cnt_in_blk indicates the number of partial matchings that can still be written to the old block
        int rest_cnt_in_blk = blk_partial_max_num - shared_blk_write_cnt[warp_id_within_blk];

        if (flag && thread_old_cnt + 1 > blk_partial_max_num) {
            // For this thread, it will write partial matching to a new block because the old block is full
            thread_need_new_blk = true;
            // Mark shared_blk_write_cnt[warp_id_within_blk] == -1
            // to indicate that there are threads in the current warp that need to request a new block
            shared_blk_write_cnt[warp_id_within_blk] = -1;
            // In the new block, the number of blocks that already exist before this thread
            thread_old_cnt = flag_idx - rest_cnt_in_blk;

            if (thread_old_cnt >= blk_partial_max_num) {
                // Ensure that the number of partial matchings that can be written in a block blk_partial_max_num is greater than warpSize
                // Otherwise, more than two blocks need to be requested in one round of 32-thread parallel execution
                // printf("The program should not reach here.\n");
                // printf("Debug Info - Thread %d in warp %d:\n", tid, warp_id);
                // printf("Old count: %d\n", thread_old_cnt);
                // printf("Rest count in block: %d\n", rest_cnt_in_blk);
                // printf("Limit: %d\n", blk_partial_max_num);
                // printf("Partial matching length: %d\n", partial_matching_len);
                // printf("Flag index: %d\n", flag_idx);
                // printf("Flag count: %d\n", flag_cnt);
                // printf("Need new block: %d\n", thread_need_new_blk);
                // printf("Block write count: %d\n", shared_blk_write_cnt[warp_id_within_blk]);
                // assert(0);
            }
        }
        __syncwarp();

        // Address of the newly allocated block
        int *d_new_head = 0;
        unsigned int d_new_head_lower = 0;
        unsigned int d_new_head_upper = 0;

        if (lane_id == 0 && shared_blk_write_cnt[warp_id_within_blk] == -1) {
            // If shared_blk_write_cnt[warp_id_within_blk] == -1,
            // it means there are threads in this warp that need to write results to a new memory block
            // Register this block and allocate a new block for this warp
            shared_blk_write_cnt[warp_id_within_blk] = -rest_cnt_in_blk;
            d_MM->add_new_props(shared_prev_head[warp_id_within_blk], cur_query_vertex + 1, blk_partial_max_num);

            d_new_head = d_MM->mempool_to_write()->alloc();
            d_new_head_lower = (unsigned)d_new_head;
            d_new_head_upper = (unsigned)((unsigned long long)d_new_head >> 32);
        }
        __syncwarp();

        d_new_head_lower = __shfl_sync(FULL_MASK, d_new_head_lower, 0);
        d_new_head_upper = __shfl_sync(FULL_MASK, d_new_head_upper, 0);
        d_new_head = (int *)(((unsigned long long)d_new_head_upper << 32) |
                             (unsigned long long)d_new_head_lower);
        // d_new_head is null if no new block is allocated

        if (lane_id == 0) {
            // If shared_blk_write_cnt[warp_id_within_blk] != -1, it means no new block is needed
            shared_blk_write_cnt[warp_id_within_blk] += __popc(flag_mask);
        }
        __syncwarp();

        // Some threads write to the new block, some write to the old block
        int *blk_to_write = shared_prev_head[warp_id_within_blk];
        if (thread_need_new_blk == true) {
            blk_to_write = d_new_head;
            shared_prev_head[warp_id_within_blk] = d_new_head;
        }
        __syncwarp();

        if (blk_to_write == nullptr) {
            *d_error_flag = 1;
            return;
        }

        if (flag) {
            // Write the newly found partial matching
            int idx = thread_old_cnt * (cur_query_vertex + 1) + cur_query_vertex;
            if (idx >= memPoolBlockIntNum || idx < 0) {
                // printf("idx: %d, memPoolBlockIntNum: %lld\n", idx, memPoolBlockIntNum);
                // assert(0);
            }
            blk_to_write[idx] = v;
            for (char i = 0; i < cur_query_vertex; i++) {
                idx = thread_old_cnt * (cur_query_vertex + 1) + i;
                blk_to_write[idx] = this_partial_matching[i];
            }
        }
    }

    if (lane_id == 0) {
        d_MM->prev_head[warp_id] = shared_prev_head[warp_id_within_blk];
        d_MM->blk_write_cnt[warp_id] = shared_blk_write_cnt[warp_id_within_blk];
    }
}


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
) {

    __shared__ int shared_blk_write_cnt[warpsPerBlock];
    __shared__ int *shared_prev_head[warpsPerBlock];
    __shared__ uint32_t s_partial_order[32];

    int warp_id = (threadIdx.x + blockDim.x * blockIdx.x) / warpSize;
    char lane_id = (threadIdx.x + blockDim.x * blockIdx.x) % warpSize;
    char warp_id_within_blk = warp_id % warpsPerBlock;

    if (lane_id == 0) {
        shared_prev_head[warp_id_within_blk] = d_MM->prev_head[warp_id];
        shared_blk_write_cnt[warp_id_within_blk] = d_MM->blk_write_cnt[warp_id];
    }

    if (threadIdx.x < Q.vcount()) {
        s_partial_order[threadIdx.x] = d_partial_order[threadIdx.x];
    }

    __syncwarp();

    if (last_flag == 1) {
        if (lane_id == 0) {
            if (shared_blk_write_cnt[warp_id_within_blk] > 0) {
                d_MM->add_new_props(shared_prev_head[warp_id_within_blk], partial_offset, shared_blk_write_cnt[warp_id_within_blk]);
            }
            d_MM->prev_head[warp_id] = nullptr;
            d_MM->blk_write_cnt[warp_id] = 0;
        }
        return;
    }

    int *this_partial_matching = d_MM->get_partial(warp_id + partial_offset);
    if (this_partial_matching == nullptr) {
        return;
    }

    const int blk_partial_max_num = memPoolBlockIntNum / (cur_query_vertex + 1);

    unsigned bn_mask = Q.d_bknbrs_[cur_query_vertex];
    char first_uu = __ffs(bn_mask) - 1;
    bn_mask &= ~(1u << first_uu);

    CandLen_t min_len = 0;
    CandLen_t *min_set = cg.d_get_candidates(first_uu, cur_query_vertex, this_partial_matching[first_uu], min_len);

    while (bn_mask) {
        char uu = __ffs(bn_mask) - 1;
        bn_mask &= ~(1u << uu);
        CandLen_t this_len = 0;
        CandLen_t *this_set = cg.d_get_candidates(uu, cur_query_vertex, this_partial_matching[uu], this_len);
        if (this_len < min_len) {
            min_len = this_len;
            min_set = this_set;
        }
    }

    if (lane_id == 0 && shared_prev_head[warp_id_within_blk] == nullptr) {
        shared_prev_head[warp_id_within_blk] = d_MM->mempool_to_write()->alloc();
        shared_blk_write_cnt[warp_id_within_blk] = 0;
    }
    __syncwarp();

    for (int t = lane_id; t < min_len; t += warpSize) {
        CandLen_t v = min_set[t];
        bool flag = true;
        int real_v = cg.d_get_mapped_v(cur_query_vertex, v);
        for (char j = 0; j < cur_query_vertex; j++) {
            int mv = cg.d_get_mapped_v(j, this_partial_matching[j]);
            if (mv == real_v) {
                flag = false;
                break;
            }
            else if (s_partial_order[j] & (1 << cur_query_vertex)) {
                if (real_v > mv) {
                    flag = false;
                    break;
                }
            }
        }

        if (flag) {
            unsigned bn_mask = Q.d_bknbrs_[cur_query_vertex];
            while (bn_mask) {
                char uu = __ffs(bn_mask) - 1;
                bn_mask &= ~(1u << uu);
                CandLen_t this_len = 0;
                CandLen_t *this_set = cg.d_get_candidates(uu, cur_query_vertex, this_partial_matching[uu], this_len);
                if (this_set == min_set) {
                    continue;
                }
                if (!binary_search<CandLen_t>(this_set, this_len, v)) {
                    flag = false;
                    break;
                }
            }
        }
        __syncwarp();

        unsigned int flag_mask = __ballot_sync(FULL_MASK, flag);
        char flag_idx = __popc(flag_mask & ((1 << lane_id) - 1));
        int thread_old_cnt = shared_blk_write_cnt[warp_id_within_blk] + flag_idx;
        bool thread_need_new_blk = false;
        int rest_cnt_in_blk = blk_partial_max_num - shared_blk_write_cnt[warp_id_within_blk];

        if (flag && thread_old_cnt + 1 > blk_partial_max_num) {
            thread_need_new_blk = true;
            shared_blk_write_cnt[warp_id_within_blk] = -1;
            thread_old_cnt = flag_idx - rest_cnt_in_blk;
        }
        __syncwarp();

        int *d_new_head = 0;
        unsigned int d_new_head_lower = 0;
        unsigned int d_new_head_upper = 0;

        if (lane_id == 0 && shared_blk_write_cnt[warp_id_within_blk] == -1) {
            shared_blk_write_cnt[warp_id_within_blk] = -rest_cnt_in_blk;
            d_MM->add_new_props(shared_prev_head[warp_id_within_blk], cur_query_vertex + 1, blk_partial_max_num);
            d_new_head = d_MM->mempool_to_write()->alloc();
            d_new_head_lower = (unsigned)d_new_head;
            d_new_head_upper = (unsigned)((unsigned long long)d_new_head >> 32);
        }
        __syncwarp();

        d_new_head_lower = __shfl_sync(FULL_MASK, d_new_head_lower, 0);
        d_new_head_upper = __shfl_sync(FULL_MASK, d_new_head_upper, 0);
        d_new_head = (int *)(((unsigned long long)d_new_head_upper << 32) |
                             (unsigned long long)d_new_head_lower);

        if (lane_id == 0) {
            shared_blk_write_cnt[warp_id_within_blk] += __popc(flag_mask);
        }
        __syncwarp();

        int *blk_to_write = shared_prev_head[warp_id_within_blk];
        if (thread_need_new_blk == true) {
            blk_to_write = d_new_head;
            shared_prev_head[warp_id_within_blk] = d_new_head;
        }
        __syncwarp();

        if (blk_to_write == nullptr) {
            *d_error_flag = 1;
            return;
        }

        if (flag) {
            int idx = thread_old_cnt * (cur_query_vertex + 1) + cur_query_vertex;
            blk_to_write[idx] = v;
            for (char i = 0; i < cur_query_vertex; i++) {
                idx = thread_old_cnt * (cur_query_vertex + 1) + i;
                blk_to_write[idx] = this_partial_matching[i];
            }
        }
    }

    if (lane_id == 0) {
        d_MM->prev_head[warp_id] = shared_prev_head[warp_id_within_blk];
        d_MM->blk_write_cnt[warp_id] = shared_blk_write_cnt[warp_id_within_blk];
    }
}
