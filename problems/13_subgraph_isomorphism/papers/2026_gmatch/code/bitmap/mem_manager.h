#ifndef _MEM_MANAGER_H_
#define _MEM_MANAGER_H_

#include <cub/cub.cuh>
#include "mem_pool.h"
#include "helper.h"
#include "params.h"


struct partial_props {
    int *start_addr;
    int partial_len;
    int partial_cnt;
};

#define props_max_num memPoolBlockNum


class MemManager {
public:
    partial_props *_props_array[2];
    int _props_array_len[2];
    MemPool _mem_pool[2];

    int current_props_array_id;     // ID of MemPool with unfinished partial matchings

    int *cnt_prefix_sum;
    int *tot_partial_cnt;

    // previous memory block address for each warp
    // length = total number of warps
    int **prev_head;

    // block writing counter for each warp
    // number of partial matchings that already existed in this memory block
    // length = total number of warps
    int *blk_write_cnt;

public:
    MemManager() {
        _props_array[0] = nullptr;
        _props_array[1] = nullptr;

        _props_array_len[0] = 0;
        _props_array_len[1] = 0;

        current_props_array_id = 0;

        cudaCheck(cudaMalloc(&cnt_prefix_sum, sizeof(int) * props_max_num));
        cudaCheck(cudaMalloc(&tot_partial_cnt, sizeof(int) * 2));

        cudaCheck(cudaMalloc(&prev_head, sizeof(int *) * maxBlocks * warpsPerBlock));
        cudaCheck(cudaMalloc(&blk_write_cnt, sizeof(int) * maxBlocks * warpsPerBlock));

        init_prev_head();
    }

    __host__ void
    init_prev_head() {
        cudaCheck(cudaMemset(prev_head, 0, sizeof(int *) * maxBlocks * warpsPerBlock));
        cudaCheck(cudaMemset(blk_write_cnt, 0,
                             sizeof(int) * maxBlocks * warpsPerBlock));
    }

    __host__ void
    init(int *partial_matching_addr, int partial_matching_cnt, int begin_offset,
         int begin_size) {

        init_prev_head();

        // Selective initialization for the range [begin_offset : begin_offset + begin_size)
        partial_matching_addr = partial_matching_addr + begin_offset * 2;
        int tmp = partial_matching_cnt - begin_offset;
        partial_matching_cnt = begin_size;

        if (tmp < begin_size) {
            partial_matching_cnt = tmp;
        }
        assert(partial_matching_cnt > 0);

        current_props_array_id = 0;

        const int partial_matching_num_per_blk = memPoolBlockIntNum / 2;
        assert(memPoolBlockIntNum % 2 == 0);
        int need_blk_num = GMATCH_CEIL_DIV(partial_matching_cnt, partial_matching_num_per_blk);

        assert(need_blk_num >= 1);
        assert(need_blk_num <= props_max_num);

        partial_props *h_first_props_array = (partial_props *)malloc(sizeof(
                partial_props) * need_blk_num);
        assert(h_first_props_array != nullptr);

        int i = 0;
        for (i = 0; i + 1 < need_blk_num; i++) {
            h_first_props_array[i].start_addr = partial_matching_addr + 2 * i *
                                                partial_matching_num_per_blk;
            h_first_props_array[i].partial_cnt = partial_matching_num_per_blk;
            h_first_props_array[i].partial_len = 2;
        }

        // Last block initialization
        assert(i + 1 == need_blk_num);
        h_first_props_array[i].start_addr = partial_matching_addr + 2 * i *
                                            partial_matching_num_per_blk;
        h_first_props_array[i].partial_cnt = partial_matching_cnt -
                                             partial_matching_num_per_blk * i;
        h_first_props_array[i].partial_len = 2;

        int tot = h_first_props_array[i].partial_cnt + (need_blk_num - 1) *
                  partial_matching_num_per_blk;

        assert(props_max_num == memPoolBlockNum);
        cudaCheck(cudaMalloc(&_props_array[0], sizeof(partial_props) * props_max_num));
        cudaCheck(cudaMalloc(&_props_array[1], sizeof(partial_props) * props_max_num));

        cudaCheck(cudaMemcpy(_props_array[0], h_first_props_array,
                             sizeof(partial_props) * need_blk_num, cudaMemcpyHostToDevice));

        _props_array_len[0] = need_blk_num;
        _props_array_len[1] = 0;

        free(h_first_props_array);

        cudaCheck(cudaMemcpy(tot_partial_cnt, &tot, sizeof(int),
                             cudaMemcpyHostToDevice));
        cudaCheck(cudaMemset(tot_partial_cnt + 1, 0, sizeof(int)));
    }

    __device__ __host__ MemPool *
    mempool_to_write() {
        return _mem_pool + (current_props_array_id ^ 1);
    }

    __device__ __host__ MemPool *
    mempool_to_read() {
        return _mem_pool + current_props_array_id;
    }

    __host__ void
    swap_mem_pool() {
        _mem_pool[current_props_array_id].freeAll();
        _props_array_len[current_props_array_id] = 0;

        cudaCheck(cudaMemset(tot_partial_cnt + current_props_array_id, 0, sizeof(int)));

        current_props_array_id ^= 1;
    }

    __device__ int *
    get_partial(int partial_id, int *partial_matching_len = nullptr) {
        partial_props *props = _props_array[current_props_array_id];
        int props_len = _props_array_len[current_props_array_id];

        if (partial_id >= tot_partial_cnt[current_props_array_id]) {
            return nullptr;
        }

        partial_id += 1;

        // Single thread binary search
        // Find the first cnt_prefix_sum[i] that is no less than partial_id
        int low = 0;
        int high = props_len - 1;
        int mid = ((low + high) >> 1);

        while (low < high) {
            if (cnt_prefix_sum[mid] < partial_id) {
                low = mid + 1;
            }
            else if (cnt_prefix_sum[mid] == partial_id) {
                break;
            }
            else {
                high = mid;
            }
            mid = ((low + high) >> 1);
        }

        if (cnt_prefix_sum[mid] < partial_id) {
            return nullptr;
        }

        int inner_idx = partial_id - 1;
        if (mid >= 1) {
            inner_idx -= cnt_prefix_sum[mid - 1];
        }

        if (partial_matching_len != nullptr) {
            *partial_matching_len = props[mid].partial_len;
        }
        int *ret = props[mid].start_addr + inner_idx * props[mid].partial_len;

        if (ret[0] == -1) {
            return nullptr;
        }

        return ret;
    }

    __device__ partial_props *
    get_partial_props(int warp_id) {
        return _props_array[current_props_array_id] + warp_id;
    }

    __device__ void
    add_new_props(partial_props props) {
        int old = atomicAdd(&_props_array_len[current_props_array_id ^ 1], 1);
        _props_array[current_props_array_id ^ 1][old] = props;
        atomicAdd(&tot_partial_cnt[current_props_array_id ^ 1], props.partial_cnt);
    }

    __device__ void
    add_new_props(int *addr_, int len_, int cnt_) {
        int old = atomicAdd(&_props_array_len[current_props_array_id ^ 1], 1);
        partial_props &P = _props_array[current_props_array_id ^ 1][old];
        P.start_addr = addr_;
        P.partial_len = len_;
        P.partial_cnt = cnt_;
        atomicAdd(&tot_partial_cnt[current_props_array_id ^ 1], cnt_);
    }

    __host__ int
    get_partial_cnt() {
        int ret = 0;
        cudaCheck(cudaMemcpy(&ret, tot_partial_cnt + current_props_array_id,
                             sizeof(int), cudaMemcpyDeviceToHost));
        return ret;
    }

    __device__ int
    d_get_partial_cnt() {
        return tot_partial_cnt[current_props_array_id];
    }

    __host__ void
    dump(const char *filename) {
        FILE *fp = fopen(filename, "w");
        assert(fp != nullptr);
        int props_array_len = _props_array_len[current_props_array_id];

        partial_props *props_array = (partial_props *)malloc(sizeof(
                                         partial_props) * props_array_len);
        assert(props_array != nullptr);
        cudaCheck(cudaMemcpy(props_array, _props_array[current_props_array_id],
                             sizeof(partial_props) * props_array_len, cudaMemcpyDeviceToHost));

        for (int i = 0; i < props_array_len; i++) {     // for each allocated block
            partial_props *p = props_array + i;
            int num = p->partial_cnt;
            int len = p->partial_len;
            int *d_addr = p->start_addr;
            int *h_addr = (int *)malloc(sizeof(int) * num * len);
            cudaCheck(cudaMemcpy(h_addr, d_addr, sizeof(int) * num * len,
                                 cudaMemcpyDeviceToHost));
            for (int j = 0; j < num; j++) {
                int *line = h_addr + len * j;
                for (int k = 0; k < len; k++) {
                    fprintf(fp, "%d,", line[k]);
                }
                fprintf(fp, "\n");
            }
            free(h_addr);
        }

        fclose(fp);
        printf("Result saved in %s\n", filename);
    }

    __host__ void
    deallocate() {
        _mem_pool[0].deallocate();
        _mem_pool[1].deallocate();
        cudaCheck(cudaFree(_props_array[0]));
        cudaCheck(cudaFree(_props_array[1]));
        cudaCheck(cudaFree(cnt_prefix_sum));
        cudaCheck(cudaFree(tot_partial_cnt));
        cudaCheck(cudaFree(prev_head));
        cudaCheck(cudaFree(blk_write_cnt));
    }
};

static __global__ void
copy_partial_cnt(const MemManager MM) {
    partial_props *props = MM._props_array[MM.current_props_array_id];
    int props_len = MM._props_array_len[MM.current_props_array_id];

    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    int tnum = gridDim.x * blockDim.x;

    for (int i = tid; i < props_len; i += tnum) {
        MM.cnt_prefix_sum[i] = props[i].partial_cnt;
    }
}

static __host__ void
get_partial_init(MemManager *MM) {
    int props_len = MM->_props_array_len[MM->current_props_array_id];

    copy_partial_cnt <<< maxBlocks, threadsPerBlock>>>(*MM);

    cudaCheck(cudaDeviceSynchronize());

    int *d_temp_storage = nullptr;
    size_t temp_storage_bytes = 0;

    cub::DeviceScan::InclusiveSum(d_temp_storage, temp_storage_bytes,
                                  MM->cnt_prefix_sum, props_len);
    cudaCheck(cudaMalloc(&d_temp_storage, temp_storage_bytes));
    cub::DeviceScan::InclusiveSum(d_temp_storage, temp_storage_bytes,
                                  MM->cnt_prefix_sum, props_len);
    cudaCheck(cudaFree(d_temp_storage));

    // int *h_cnt_prefix_sum = new int[props_len];
    // cudaCheck(cudaMemcpy(h_cnt_prefix_sum, MM->cnt_prefix_sum, props_len * sizeof(int), cudaMemcpyDeviceToHost));
    // for (int i = 1; i < props_len; i++) {
    //     h_cnt_prefix_sum[i] += h_cnt_prefix_sum[i - 1];
    // }
    // cudaCheck(cudaMemcpy(MM->cnt_prefix_sum, h_cnt_prefix_sum, props_len * sizeof(int), cudaMemcpyHostToDevice));
    // delete[] h_cnt_prefix_sum;
}

#endif
