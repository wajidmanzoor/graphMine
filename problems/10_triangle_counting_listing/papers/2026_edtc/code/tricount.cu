#include "tricount.h"
#include "Graph.h"
#include "IndexType.h"
#include "common.h"
#include <cuda_runtime.h>
#include <fstream>
#include <iostream>
#include <thrust/sort.h>
#include <thrust/device_ptr.h>
#include <thrust/device_vector.h>
#include <cub/cub.cuh>
#include <stdexcept>
#include <string>
using std::cout;
using std::endl;
#define gpuErrchk(ans)                    \
  {                                       \
    gpuAssert((ans), __FILE__, __LINE__); \
  }
inline void gpuAssert(cudaError_t code, const char *file, int line, bool abort = true)
{
  if (code != cudaSuccess)
  {
#ifdef GRAPHMINE_LIBRARY
    throw std::runtime_error(std::string("EDTC CUDA failure at ") + file +
                             ":" + std::to_string(line) + ": " +
                             cudaGetErrorString(code));
#else
    fprintf(stderr, "GPUassert: %s %s %d\n", cudaGetErrorString(code), file, line);
    if (abort)
      exit(code);
#endif
  }
}
#define bucket_limit 96
#define bucket_num_l 65535
void __global__ Generate_InitD(UpdateEdge *updates, edge_type batch_size, Edge *operations, edge_type *operations_size, edge_type *active);
void __global__ Generate_InitA(UpdateEdge *updates, edge_type batch_size, Edge *operations, edge_type *operations_size, edge_type *active);
void __global__ Generate_bucket_count(edge_type *bucket_count, Edge *operations, edge_type operations_size);
// void __global__ Generate_hash(edge_type *hash_bucket_s, edge_type *bucket_count_s, offset_type *bucket_count_s_offset, hash_type *hash_bucket_l, edge_type *bucket_count_l, offset_type *bucket_count_l_offset, Edge *operations, edge_type operations_size, bool *limit, edge_type *d_hash_active_s, edge_type *d_hash_active_l, edge_type *d_hash_index_s, edge_type *d_hash_index_l);
void __global__ Generate_hash(edge_type *hash_bucket_s, edge_type *bucket_count_s, offset_type *bucket_count_s_offset, hash_type *hash_bucket_l, edge_type *bucket_count_l, offset_type *bucket_count_l_offset, Edge *operations, edge_type operations_size, bool *limit);
void __global__ Generate_limit(edge_type *bucket_count, edge_type node_num, bool *limit);
void __global__ Generate_updates_degree(Edge *d_updates, Edge *d_updates_degree, offset_type *d_degrees, edge_type updates_size);
void __global__ Split_hash(edge_type *bucket_count_s, edge_type *bucket_count_l, edge_type *bucket_count, Edge *updates, edge_type updates_size, bool *limit);
void __global__ Split_updates(Edge *d_updates_s, Edge *d_updates_l, bool *limit, Edge *updates, edge_type updates_size, edge_type *updates_l_num, edge_type *updates_s_num, offset_type *d_updates_degrees);
void __global__ TC_kernel_large __launch_bounds__(256, 8)(edge_type min_, edge_type max_, edge_type *d_updates_adjList, offset_type *d_updates_offset, edge_type *d_updates_index, Edge *d_updates_l, edge_type *d_updates_cnt_l, unsigned long long int *d_change_count, hash_type *d_hash_bucket_l, edge_type *d_bucket_count_l, offset_type *d_bucket_count_l_offset, edge_type *d_now_Edge, offset_type *d_bucket_count_s_suboffset, edge_type *d_sub_s_cnt, edge_type sh_size);
void __global__ TC_kernel_small __launch_bounds__(256, 8)(edge_type *d_updates_adjList, offset_type *d_updates_offset, edge_type *d_updates_index, Edge *d_updates_s, edge_type *d_updates_cnt_s, unsigned long long int *d_change_count, edge_type *d_hash_bucket_s, edge_type *d_bucket_count_s, offset_type *d_bucket_count_s_offset, edge_type *d_now_Edge, offset_type *d_bucket_count_s_suboffset, edge_type *d_sub_s_cnt);
void __global__ TC_kernel __launch_bounds__(256, 8)(edge_type *d_updates_adjList, offset_type *d_updates_offset, edge_type *d_updates_index, Edge *d_operations_updates, edge_type operations_size, unsigned long long int *d_change_count, edge_type *d_hash_bucket_s, edge_type *d_bucket_count_s, offset_type *d_bucket_count_s_offset, hash_type *d_hash_bucket_l, edge_type *d_bucket_count_l, offset_type *d_bucket_count_l_offset, edge_type *d_now_Edge, bool *limit);

void tricount(offset_type *offSet, edge_type *adjList, uint32_t gpu_id,
              offset_type batch_size, offset_type batch_num,
              string filepath_batch, edge_type node_num, offset_type edge_num,
              const char *update_types, const edge_type *update_sources,
              const edge_type *update_destinations,
              unsigned long long *deleted_triangle_counts,
              unsigned long long *inserted_triangle_counts,
              float *delete_times_ms, float *insert_times_ms) {
#ifndef GRAPHMINE_LIBRARY
    cout << "node_num: " << node_num << endl;
    cout << "edge_num: " << edge_num << endl;
#endif
    gpuErrchk(cudaSetDevice(gpu_id));
    Graph G(node_num);
    #pragma omp parallel for
    for (edge_type i = 0; i < node_num; ++i) {
        G.V[i].init(offSet[i + 1] - offSet[i]);
        G.degrees[i] = offSet[i + 1] - offSet[i];
        offset_type offset = offSet[i];
        for (offset_type j = 0; j < G.degrees[i]; ++j) {
            G.V[i].Neighbors[j] = adjList[offset + j];
        }
    }
    std::ifstream file_batch;
    if (update_types == nullptr) {
      file_batch.open(filepath_batch, std::ios::in);
    }
    if(update_types == nullptr && !file_batch) {
#ifdef GRAPHMINE_LIBRARY
        throw std::runtime_error("EDTC could not open its update stream");
#else
        cout << "error opening file_batch" << endl;
        exit(0);
#endif
    }
    if (update_types != nullptr &&
        (update_sources == nullptr || update_destinations == nullptr)) {
        throw std::invalid_argument(
            "EDTC in-memory updates require types, sources, and destinations");
    }
    UpdateEdge *updates, *d_updates;
    updates = CPUAlloc(UpdateEdge, batch_size);
    gpuErrchk(cudaMalloc(&d_updates, sizeof(UpdateEdge) * batch_size));
    edge_type additions_size, deletions_size;
    edge_type *d_updates_cnt;
    gpuErrchk(cudaMalloc(&d_updates_cnt, sizeof(edge_type)));
    edge_type *d_sub_l_cnt, *d_sub_s_cnt;
    edge_type *d_add_l_cnt, *d_add_s_cnt;
    gpuErrchk(cudaMalloc(&d_sub_l_cnt, sizeof(edge_type)));
    gpuErrchk(cudaMalloc(&d_sub_s_cnt, sizeof(edge_type)));
    gpuErrchk(cudaMalloc(&d_add_l_cnt, sizeof(edge_type)));
    gpuErrchk(cudaMalloc(&d_add_s_cnt, sizeof(edge_type)));
    Edge *deletions, *additions;
    Edge *d_deletions_degrees, *d_additions_degrees;
    Edge *d_deletions_l, *d_deletions_s;
    Edge *d_additions_l, *d_additions_s;
    Edge *d_deletions, *d_additions;
    edge_type *d_deletions_cnt, *d_additions_cnt;
    gpuErrchk(cudaMalloc(&d_deletions_cnt, sizeof(edge_type)));
    gpuErrchk(cudaMalloc(&d_additions_cnt, sizeof(edge_type)));
    edge_type *d_bucket_count, *d_bucket_count_s, *d_bucket_count_l;
    edge_type *bucket_count_l;
    bucket_count_l = CPUAlloc(edge_type, (node_num + 1));
    offset_type *d_bucket_count_s_offset, *d_bucket_count_l_offset;
    edge_type *d_hash_active_s, *d_hash_active_l;
    edge_type *d_hash_index_s, *d_hash_index_l;
    gpuErrchk(cudaMalloc(&d_hash_index_s, sizeof(edge_type) * (node_num + 1)));
    gpuErrchk(cudaMalloc(&d_hash_index_l, sizeof(edge_type) * (node_num + 1)));
    gpuErrchk(cudaMalloc(&d_hash_active_s, sizeof(edge_type) * (node_num + 1)));
    gpuErrchk(cudaMalloc(&d_hash_active_l, sizeof(edge_type) * (node_num + 1)));
    offset_type *d_bucket_count_s_suboffset, *d_bucket_count_l_suboffset;
    gpuErrchk(cudaMalloc(&d_bucket_count_s_offset, sizeof(offset_type) * (node_num + 1)));
    gpuErrchk(cudaMalloc(&d_bucket_count_l_offset, sizeof(offset_type) * (node_num + 1)));
    gpuErrchk(cudaMalloc(&d_bucket_count_s_suboffset, sizeof(offset_type) * (node_num + 1)));
    gpuErrchk(cudaMalloc(&d_bucket_count_l_suboffset, sizeof(offset_type) * (node_num + 1)));
    bool *d_limit;
    gpuErrchk(cudaMalloc(&d_limit, sizeof(bool) * (node_num)));
    void *dev_temp_storage = nullptr;
    size_t temp_storage_bytes = 0;
    gpuErrchk(cudaMalloc(&d_bucket_count, sizeof(edge_type) * (node_num + 1)));
    gpuErrchk(cudaMalloc(&d_bucket_count_s, sizeof(edge_type) * (node_num + 1)));
    gpuErrchk(cudaMalloc(&d_bucket_count_l, sizeof(edge_type) * (node_num + 1)));
    edge_type *d_updates_active;
    edge_type *updates_active;
    updates_active = CPUAlloc(edge_type, node_num);
    edge_type *d_updates_index;
    edge_type *updates_index;
    // gpuErrchk(cudaMalloc(&updates_index, sizeof(edge_type) * node_num));
    updates_index = CPUAlloc(edge_type, node_num);
    offset_type *d_updates_degrees;
    offset_type *d_updates_suboffset;
    offset_type *d_updates_offset;
    offset_type *updates_offset;

    edge_type *d_updates_adjList;
    edge_type *d_deletions_cnt_l, *d_deletions_cnt_s;
    edge_type *d_additions_cnt_l, *d_additions_cnt_s;
    // gpuErrchk(cudaMalloc(&d_deletions_cnt_l, sizeof(edge_type) * (node_num + 1)));
    // gpuErrchk(cudaMalloc(&d_deletions_cnt_s, sizeof(edge_type) * (node_num + 1)));
    unsigned long long int *d_change_count_del, *d_change_count_add;
    edge_type *d_now_Edge_del, *d_now_Edge_add;
    gpuErrchk(cudaMalloc(&d_change_count_del, sizeof(unsigned long long int)));
    gpuErrchk(cudaMalloc(&d_change_count_add, sizeof(unsigned long long int)));
    gpuErrchk(cudaMalloc(&d_now_Edge_del, sizeof(edge_type)));
    gpuErrchk(cudaMalloc(&d_now_Edge_add, sizeof(edge_type)));
    gpuErrchk(cudaMalloc(&d_updates_active, sizeof(edge_type) * (node_num)));
    gpuErrchk(cudaMalloc(&d_updates_index, sizeof(edge_type) * (node_num)));
    gpuErrchk(cudaMalloc(&d_updates_degrees, sizeof(offset_type) * (node_num)));
    gpuErrchk(cudaMalloc(&d_updates_suboffset, sizeof(offset_type) * (node_num)));
    edge_type small_sum, large_sum;
    // edge_type *d_hash_bucket_l, *d_hash_bucket_s;
    edge_type *d_hash_bucket_s;
    hash_type *d_hash_bucket_l;
    edge_type deletions_cnt, additions_cnt;
    edge_type *updates_adjList;
    // uint64_t pre_csr_mem = 0, now_csr_mem = 0;
    // pre_csr_mem = (uint64_t)((uint64_t)node_num + 1 + (uint64_t)edge_num) * 4;
    // uint64_t pre_hash_mem = 0, now_hash_mem = 0;
    // edge_type test_size = 192;
    // edge_type test_num = MyPow(2, 16);
    // if(batch_size < 10000000) {
    //     for (edge_type i = 10; i >= 1; --i) {
    //         if(node_num >= MyPow(2, 25 - i)) {
    //             test_size = 192;
    //             test_num = MyPow(2, 26 - i);
    //         } else {
    //             break;
    //         }
    //     }
    //     if(node_num >= MyPow(2, 25)) {
    //         test_size = 96;
    //         test_num = MyPow(2, 26);
    //     }
    // }  else {
    //     for (edge_type i = 9; i >= 1; --i) {
    //         if(node_num >= MyPow(2, 25 - i)) {
    //             test_size = 192;
    //             test_num = MyPow(2, 26 - i);
    //         } else {
    //             break;
    //         }
    //     }
    //     if(node_num >= MyPow(2, 24)) {
    //         test_size = 96;
    //         test_num = MyPow(2, 25);
    //     }
    //     if(node_num >= MyPow(2, 25)) {
    //         test_size = 64;
    //         test_num = MyPow(2, 26);
    //     }
    // }
    // pre_hash_mem = 4 * (uint64_t)test_num * (uint64_t)test_size + 65535 * 96 * 8 + 65535 * 4 + (uint64_t)test_num * 4;
    // now_hash_mem = (uint64_t)((uint64_t)node_num + 1) * 8;
    offset_type batch_index = 0;
    while(batch_num -- ) {
        unsigned long long int change_count_del = 0;
        unsigned long long int change_count_add = 0;
        float del_time = 0.0f;
        float add_time = 0.0f;
        additions_size = 0, deletions_size = 0;
        for (edge_type i = 0; i < batch_size; ++i) {
            if (update_types != nullptr) {
                const offset_type update_index = batch_index * batch_size + i;
                updates[i].UpdateType = update_types[update_index];
                updates[i].source = update_sources[update_index];
                updates[i].destination = update_destinations[update_index];
            } else {
                file_batch >> updates[i].UpdateType >> updates[i].source >> updates[i].destination;
            }
            if(updates[i].UpdateType == 'a') {
                additions_size += 2;
            } else if(updates[i].UpdateType =='d') {
                deletions_size += 2;
            } else {
#ifdef GRAPHMINE_LIBRARY
                throw std::invalid_argument("EDTC update type must be 'a' or 'd'");
#else
                cout << "batch file error!" << endl;
                exit(0);
#endif
            }
        }

        deletions = CPUAlloc(Edge, deletions_size);
        gpuErrchk(cudaMalloc(&d_deletions_degrees, sizeof(Edge) * deletions_size / 2));
        gpuErrchk(cudaMalloc(&d_deletions, sizeof(Edge) * deletions_size));;
        cudaMemset(d_deletions_cnt, 0, sizeof(edge_type));
        gpuErrchk(cudaMemcpy(d_updates, updates, sizeof(UpdateEdge) * batch_size, cudaMemcpyHostToDevice));
        gpuErrchk(cudaMemset(d_updates_active, 0, sizeof(edge_type) * node_num));
        gpuErrchk(cudaDeviceSynchronize());
        // cout << "batch_size: " << batch_size << endl;
        Generate_InitD<<<(batch_size + 1023) / 1024, 1024>>>(d_updates, batch_size, d_deletions, d_deletions_cnt, d_updates_active); 
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaMemcpy(deletions, d_deletions, sizeof(Edge) * deletions_size, cudaMemcpyDeviceToHost));
        gpuErrchk(cudaMemcpy(updates_active, d_updates_active, sizeof(edge_type) * node_num, cudaMemcpyDeviceToHost));
        gpuErrchk(cudaMemset(d_bucket_count, 0, sizeof(edge_type) * (node_num + 1)));
        
        Generate_bucket_count<<<1024, 256>>>(d_bucket_count, d_deletions, deletions_size); 
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaMemset(d_limit, 0, sizeof(bool) * node_num));

        // thrust::device_ptr<Edge> d_deletions_ptr(d_deletions);
        // thrust::sort(d_deletions_ptr, d_deletions_ptr + deletions_size);
        gpuErrchk(cudaMemset(d_bucket_count_s, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaMemset(d_bucket_count_l, 0, sizeof(edge_type) * (node_num + 1)));
        Generate_limit<<<(node_num + 1023) / 1024, 1024>>>(d_bucket_count, node_num, d_limit);
        gpuErrchk(cudaDeviceSynchronize());
        Split_hash<<<(deletions_size + 1023) / 1024, 1024>>>(d_bucket_count_s, d_bucket_count_l, d_bucket_count, d_deletions, deletions_size, d_limit);
        // Split_hash<<<(deletions_size / 2 + 1023) / 1024, 1024>>>(d_bucket_count, d_deletions, deletions_size, d_limit, d_hash_active_l);
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaMemcpy(bucket_count_l, d_bucket_count_l, sizeof(edge_type) * (node_num + 1), cudaMemcpyDeviceToHost));

        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_bucket_count_s, d_bucket_count_s_offset, (node_num + 1));
        gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_bucket_count_s, d_bucket_count_s_offset, (node_num + 1));
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaFree(dev_temp_storage));
        dev_temp_storage = nullptr;
        temp_storage_bytes = 0;

        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_bucket_count_l, d_bucket_count_l_offset, (node_num + 1));
        gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_bucket_count_l, d_bucket_count_l_offset, (node_num + 1));
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaFree(dev_temp_storage));
        dev_temp_storage = nullptr;
        temp_storage_bytes = 0;

        // cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_bucket_count_s_offset, d_bucket_count_s, d_bucket_count_s_suboffset, d_sub_s_cnt, node_num);
        // gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        // cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_bucket_count_s_offset, d_bucket_count_s, d_bucket_count_s_suboffset, d_sub_s_cnt, node_num);
        // gpuErrchk(cudaFree(dev_temp_storage));
        // dev_temp_storage = nullptr;
        // temp_storage_bytes = 0;

        // cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_bucket_count_l_offset, d_bucket_count_l, d_bucket_count_l_suboffset, d_sub_l_cnt, node_num);
        // gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        // cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_bucket_count_l_offset, d_bucket_count_l, d_bucket_count_l_suboffset, d_sub_l_cnt, node_num);
        // gpuErrchk(cudaFree(dev_temp_storage));
        // dev_temp_storage = nullptr;
        // temp_storage_bytes = 0;


        gpuErrchk(cudaMemcpy(&small_sum, d_bucket_count_s_offset + node_num, sizeof(offset_type), cudaMemcpyDeviceToHost));
        gpuErrchk(cudaMemcpy(&large_sum, d_bucket_count_l_offset + node_num, sizeof(offset_type), cudaMemcpyDeviceToHost));
        // cout << "small_sum: " << small_sum << endl;
        // cout << "large_sum: " << large_sum << endl;

        // gpuErrchk(cudaMalloc(&d_hash_bucket_l, sizeof(edge_type) * large_sum));
        // now_hash_mem += (uint64_t)large_sum * 8;
        // now_hash_mem += (uint64_t)small_sum * 4;
        gpuErrchk(cudaMalloc(&d_hash_bucket_l, sizeof(hash_type) * large_sum));
        gpuErrchk(cudaMalloc(&d_hash_bucket_s, sizeof(edge_type) * small_sum));
        gpuErrchk(cudaMalloc(&d_deletions_l, sizeof(Edge) * large_sum / 2));
        gpuErrchk(cudaMalloc(&d_deletions_s, sizeof(Edge) * small_sum / 2));
        gpuErrchk(cudaMalloc(&d_deletions_cnt_l, sizeof(edge_type)));
        gpuErrchk(cudaMalloc(&d_deletions_cnt_s, sizeof(edge_type)));
        gpuErrchk(cudaMemset(d_deletions_cnt_l, 0, sizeof(edge_type)));
        gpuErrchk(cudaMemset(d_deletions_cnt_s, 0, sizeof(edge_type)));
        gpuErrchk(cudaMemcpy(d_updates_degrees, G.degrees, sizeof(offset_type) * node_num, cudaMemcpyHostToDevice));
        gpuErrchk(cudaDeviceSynchronize());
        // cout << "deletions_size : " << deletions_size << endl;
        // Split_updates<<<(deletions_size / 2 + 1023) / 1024, 1024>>>(d_deletions_s, d_deletions_l, d_limit, d_deletions, deletions_size, d_deletions_cnt_s, d_deletions_cnt_l, d_updates_degrees);
        // gpuErrchk(cudaDeviceSynchronize());
        // void __global__ Split_updates(Edge *d_updates_l, Edge *d_updates_s, bool *limit, edge_type *updates, edge_type updates_size, edge_type *updates_l_num, edge_type *updates_s_num) {
        gpuErrchk(cudaMemset(d_hash_active_l, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaMemset(d_hash_active_s, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaMemset(d_bucket_count_s, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaMemset(d_bucket_count_l, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaMemset(d_hash_index_s, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaMemset(d_hash_index_l, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaDeviceSynchronize());

        Generate_hash<<<(deletions_size + 1023) / 1024, 1024>>>(d_hash_bucket_s, d_bucket_count_s, d_bucket_count_s_offset, d_hash_bucket_l, d_bucket_count_l, d_bucket_count_l_offset, d_deletions, deletions_size, d_limit);
        gpuErrchk(cudaDeviceSynchronize());
        // cout << "Now1" << endl;
        // cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_hash_active_s, d_bucket_count_s_suboffset, node_num + 1);

        // cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_hash_index_s, d_hash_active_s, d_bucket_count_s_suboffset, d_sub_s_cnt, node_num);
        // gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        // cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_hash_index_s, d_hash_active_s, d_bucket_count_s_suboffset, d_sub_s_cnt, node_num);
        // gpuErrchk(cudaDeviceSynchronize());
        // gpuErrchk(cudaFree(dev_temp_storage));
        // dev_temp_storage = nullptr;
        // temp_storage_bytes = 0;

        // cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_hash_index_l, d_hash_active_l, d_bucket_count_l_suboffset, d_sub_l_cnt, node_num);
        // gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        // cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_hash_index_l, d_hash_active_l, d_bucket_count_l_suboffset, d_sub_l_cnt, node_num);
        // gpuErrchk(cudaDeviceSynchronize());
        // gpuErrchk(cudaFree(dev_temp_storage));
        // dev_temp_storage = nullptr;
        // temp_storage_bytes = 0;
        // // cout << "Now2" << endl;

        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_updates_active, d_updates_index, node_num);
        gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_updates_active, d_updates_index, node_num);
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaFree(dev_temp_storage));
        dev_temp_storage = nullptr;
        temp_storage_bytes = 0;

        gpuErrchk(cudaMemcpy(updates_index, d_updates_index, sizeof(edge_type) * node_num, cudaMemcpyDeviceToHost));
        gpuErrchk(cudaMemset(d_updates_suboffset, 0, sizeof(offset_type) * (node_num)));
        gpuErrchk(cudaDeviceSynchronize());

        cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_updates_degrees, d_updates_active, d_updates_suboffset, d_updates_cnt, node_num);
        gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_updates_degrees, d_updates_active, d_updates_suboffset, d_updates_cnt, node_num);
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaFree(dev_temp_storage));
        dev_temp_storage = nullptr;
        temp_storage_bytes = 0;

        
        gpuErrchk(cudaMemcpy(&deletions_cnt, d_updates_cnt, sizeof(edge_type), cudaMemcpyDeviceToHost));

        // deletions_offset = CPUAlloc(offset_type, (deletions_cnt + 1));
        gpuErrchk(cudaMalloc(&d_updates_offset, sizeof(offset_type) * (deletions_cnt + 1)));
        updates_offset = CPUAlloc(offset_type, deletions_cnt + 1);

        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_updates_suboffset, d_updates_offset, deletions_cnt + 1);
        gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_updates_suboffset, d_updates_offset, deletions_cnt + 1);
        gpuErrchk(cudaFree(dev_temp_storage));
        dev_temp_storage = nullptr;
        temp_storage_bytes = 0;
        
        // cout << "Now3" << endl;
        gpuErrchk(cudaMemcpy(updates_offset, d_updates_offset, sizeof(offset_type) * (deletions_cnt + 1), cudaMemcpyDeviceToHost));
        gpuErrchk(cudaDeviceSynchronize());



        // gpuErrchk(cudaDeviceSynchronize());
        // cout << "Now4" << endl;
#ifndef GRAPHMINE_LIBRARY
        cout << updates_offset[deletions_cnt] << endl;
#endif
        updates_adjList = CPUAlloc(edge_type, updates_offset[deletions_cnt]);
        gpuErrchk(cudaMalloc(&d_updates_adjList, sizeof(edge_type) * updates_offset[deletions_cnt]));
        // cout << "Now5" << endl;
        // cout << "updates_offset[deletions_cnt]: " << updates_offset[deletions_cnt] << endl;
        #pragma omp parallel for
        for (edge_type i = 0; i < node_num; ++i) {
            // cout << i << endl;
            if(!updates_active[i])
                continue;
            edge_type vertex = updates_index[i];
            for(offset_type j = updates_offset[vertex]; j < updates_offset[vertex + 1]; ++j) {
                updates_adjList[j] = G.V[i].Neighbors[j - updates_offset[vertex]];
            }
        }
        // cout << "updates_adjLis"
        // for ()
        // cout << deletions_cnt << endl;
        // cout << updates_offset[deletions_cnt] << endl;
        // cout << "Now6" << endl;
        // cout << updates_offset[deletions_cnt] << endl;

        gpuErrchk(cudaMemcpy(d_updates_adjList, updates_adjList, sizeof(edge_type) * updates_offset[deletions_cnt], cudaMemcpyHostToDevice));
        // gpuErrchk(cudaMemset())
        // cout << "Now7" << endl;

        // edge_type max_sub_degree = 0;
        // #pragma omp parallel for reduction(max:max_sub_degree) 
        // for (edge_type i = 0; i < node_num; ++i) {
        //     max_sub_degree = std::max(max_sub_degree, bucket_count_l[i]);
        // }
        // cout << "max_sub_degree: " << max_sub_degree << endl;
        // cout << "Now7" << endl;

        // cudaMemcpy(temp1, d_bucket_count_s_offset, sizeof(offset_type) * 20, cudaMemcpyDeviceToHost);
        // gpuErrchk(cudaDeviceSynchronize());
        // cout << temp1[19] << endl;

        // judge<<<1024, 256>>>(d_deletions_s, d_deletions);
        Generate_updates_degree<<<(deletions_size / 2 + 1023) / 1024, 1024>>>(d_deletions, d_deletions_degrees, d_updates_degrees, deletions_size / 2);
        gpuErrchk(cudaDeviceSynchronize());
        if(deletions_size != 0) {
            // cout << "sizeof(adjList): " << edge_num * 4 << endl;
            // cout << "sizeof(d_deletions_adjList): " << updates_offset[deletions_cnt] * 4 << endl;
            // cout << "sizeof(offset): " << (node_num + 1) * 4 << endl;
            // cout << "sizeof(d_deletions_offset): " << (deletions_cnt + 1) * 4 << endl;
            // cout << "sizeof(d_deletions_index): " << (node_num) * 4 << endl;
            // now_csr_mem = (uint64_t)updates_offset[deletions_cnt] * 4 + (uint64_t)(deletions_cnt + 1) * 4 + (uint64_t)node_num * 4;
            gpuErrchk(cudaMemset(d_change_count_del, 0, sizeof(unsigned long long int)));
            gpuErrchk(cudaMemset(d_now_Edge_del, 0, sizeof(edge_type)));
            cudaEvent_t start_del, end_del;
            cudaEventCreate(&start_del);
            cudaEventCreate(&end_del);
            gpuErrchk(cudaEventRecord(start_del, 0));
            TC_kernel<<<1024, 256>>>(d_updates_adjList, d_updates_offset, d_updates_index, d_deletions_degrees, deletions_size / 2, d_change_count_del, d_hash_bucket_s, d_bucket_count_s, d_bucket_count_s_offset, d_hash_bucket_l, d_bucket_count_l, d_bucket_count_l_offset, d_now_Edge_del, d_limit);
            cudaEventRecord(end_del, 0);
            // gpuErrchk(cudaEventSynchronize(end_del));
            cudaEventSynchronize(end_del);
            cudaEventElapsedTime(&del_time, start_del, end_del);
#ifndef GRAPHMINE_LIBRARY
            printf("del_time: %f ms\n", del_time);
#endif
            gpuErrchk(cudaMemcpy(&change_count_del, d_change_count_del, sizeof(unsigned long long int), cudaMemcpyDeviceToHost));
#ifndef GRAPHMINE_LIBRARY
            cout << "del change count: " << change_count_del << endl;
#endif
            G.Delete(deletions, deletions_size);
            gpuErrchk(cudaEventDestroy(start_del));
            gpuErrchk(cudaEventDestroy(end_del));
        }
        free(deletions);
        free(updates_offset);
        free(updates_adjList);
        gpuErrchk(cudaFree(d_deletions));
        gpuErrchk(cudaFree(d_hash_bucket_l));
        gpuErrchk(cudaFree(d_hash_bucket_s));
        gpuErrchk(cudaFree(d_deletions_l));
        gpuErrchk(cudaFree(d_deletions_s));
        gpuErrchk(cudaFree(d_deletions_cnt_l));
        gpuErrchk(cudaFree(d_deletions_cnt_s));
        gpuErrchk(cudaFree(d_deletions_degrees));
        gpuErrchk(cudaFree(d_updates_offset));
        gpuErrchk(cudaFree(d_updates_adjList));

        
        additions = CPUAlloc(Edge, additions_size);
        gpuErrchk(cudaMalloc(&d_additions, sizeof(Edge) * additions_size));
        gpuErrchk(cudaMalloc(&d_additions_degrees, sizeof(Edge) * additions_size / 2));
        cudaMemset(d_additions_cnt, 0, sizeof(edge_type));
        gpuErrchk(cudaMemcpy(d_updates, updates, sizeof(UpdateEdge) * batch_size, cudaMemcpyHostToDevice));
        gpuErrchk(cudaMemset(d_updates_active, 0, sizeof(edge_type) * node_num));
        gpuErrchk(cudaDeviceSynchronize());
        Generate_InitA<<<(batch_size + 1023) / 1024, 1024>>>(d_updates, batch_size, d_additions, d_additions_cnt, d_updates_active);
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaMemcpy(additions, d_additions, sizeof(Edge) * additions_size, cudaMemcpyDeviceToHost));
        G.Insert(additions, additions_size);
        gpuErrchk(cudaMemcpy(updates_active, d_updates_active, sizeof(edge_type) * node_num, cudaMemcpyDeviceToHost));
        gpuErrchk(cudaMemset(d_bucket_count, 0, sizeof(edge_type) * (node_num + 1)));

        Generate_bucket_count<<<1024, 256>>>(d_bucket_count, d_additions, additions_size);
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaMemset(d_limit, 0, sizeof(bool) * node_num));
        gpuErrchk(cudaMemset(d_bucket_count_s, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaMemset(d_bucket_count_l, 0, sizeof(edge_type) * (node_num + 1)));
        Generate_limit<<<(node_num + 1023) / 1024, 1024>>>(d_bucket_count, node_num, d_limit);
        gpuErrchk(cudaDeviceSynchronize());
        Split_hash<<<(additions_size + 1023) / 1024, 1024>>>(d_bucket_count_s, d_bucket_count_l, d_bucket_count, d_additions, additions_size, d_limit);
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaMemcpy(bucket_count_l, d_bucket_count_l, sizeof(edge_type) * (node_num + 1), cudaMemcpyDeviceToHost));

        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_bucket_count_s, d_bucket_count_s_offset, (node_num + 1));
        gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_bucket_count_s, d_bucket_count_s_offset, (node_num + 1));
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaFree(dev_temp_storage));
        dev_temp_storage = nullptr;
        temp_storage_bytes = 0;

        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_bucket_count_l, d_bucket_count_l_offset, (node_num + 1));
        gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_bucket_count_l, d_bucket_count_l_offset, (node_num + 1));
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaFree(dev_temp_storage));
        dev_temp_storage = nullptr;
        temp_storage_bytes = 0;

        gpuErrchk(cudaMemcpy(&small_sum, d_bucket_count_s_offset + node_num, sizeof(offset_type), cudaMemcpyDeviceToHost));
        gpuErrchk(cudaMemcpy(&large_sum, d_bucket_count_l_offset + node_num, sizeof(offset_type), cudaMemcpyDeviceToHost));
        // now_hash_mem += (uint64_t)large_sum * 8;
        // now_hash_mem += (uint64_t)small_sum * 4;
        
        gpuErrchk(cudaMalloc(&d_hash_bucket_l, sizeof(hash_type) * large_sum));
        gpuErrchk(cudaMalloc(&d_hash_bucket_s, sizeof(edge_type) * small_sum));
        gpuErrchk(cudaMalloc(&d_additions_l, sizeof(Edge) * large_sum / 2));
        gpuErrchk(cudaMalloc(&d_additions_s, sizeof(Edge) * small_sum / 2));
        gpuErrchk(cudaMalloc(&d_additions_cnt_l, sizeof(edge_type)));
        gpuErrchk(cudaMalloc(&d_additions_cnt_s, sizeof(edge_type)));
        gpuErrchk(cudaMemset(d_additions_cnt_l, 0, sizeof(edge_type)));
        gpuErrchk(cudaMemset(d_additions_cnt_s, 0, sizeof(edge_type)));
        gpuErrchk(cudaMemcpy(d_updates_degrees, G.degrees, sizeof(offset_type) * node_num, cudaMemcpyHostToDevice));
        gpuErrchk(cudaDeviceSynchronize());
        // Split_updates<<<(additions_size / 2 + 1023) / 1024, 1024>>>(d_additions_s, d_additions_l, d_limit, d_additions, additions_size / 2, d_additions_cnt_s, d_additions_cnt_l, d_updates_degrees);
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaMemset(d_hash_active_l, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaMemset(d_hash_active_s, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaMemset(d_bucket_count_s, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaMemset(d_bucket_count_l, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaMemset(d_hash_index_s, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaMemset(d_hash_index_l, 0, sizeof(edge_type) * (node_num + 1)));
        gpuErrchk(cudaDeviceSynchronize());

        Generate_hash<<<(additions_size + 1023) / 1024, 1024>>>(d_hash_bucket_s, d_bucket_count_s, d_bucket_count_s_offset, d_hash_bucket_l, d_bucket_count_l, d_bucket_count_l_offset, d_additions, additions_size, d_limit);
        gpuErrchk(cudaDeviceSynchronize());

        cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_hash_index_s, d_hash_active_s, d_bucket_count_s_suboffset, d_add_s_cnt, node_num);
        gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_hash_index_s, d_hash_active_s, d_bucket_count_s_suboffset, d_add_s_cnt, node_num);
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaFree(dev_temp_storage));
        dev_temp_storage = nullptr;
        temp_storage_bytes = 0;

        cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_hash_index_l, d_hash_active_l, d_bucket_count_l_suboffset, d_add_l_cnt, node_num);
        gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_hash_index_l, d_hash_active_l, d_bucket_count_l_suboffset, d_add_l_cnt, node_num);
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaFree(dev_temp_storage));
        dev_temp_storage = nullptr;
        temp_storage_bytes = 0;

        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_updates_active, d_updates_index, node_num);
        gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_updates_active, d_updates_index, node_num);
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaFree(dev_temp_storage));
        dev_temp_storage = nullptr;
        temp_storage_bytes = 0;

        gpuErrchk(cudaMemcpy(updates_index, d_updates_index, sizeof(edge_type) * node_num, cudaMemcpyDeviceToHost));
        gpuErrchk(cudaMemset(d_updates_suboffset, 0, sizeof(offset_type) * (node_num)));
        gpuErrchk(cudaDeviceSynchronize());

        cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_updates_degrees, d_updates_active, d_updates_suboffset, d_updates_cnt, node_num);
        gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        cub::DeviceSelect::Flagged(dev_temp_storage, temp_storage_bytes, d_updates_degrees, d_updates_active, d_updates_suboffset, d_updates_cnt, node_num);
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaFree(dev_temp_storage));
        dev_temp_storage = nullptr;
        temp_storage_bytes = 0;

        gpuErrchk(cudaMemcpy(&additions_cnt, d_updates_cnt, sizeof(edge_type), cudaMemcpyDeviceToHost));

        gpuErrchk(cudaMalloc(&d_updates_offset, sizeof(offset_type) * (additions_cnt + 1)));
        updates_offset = CPUAlloc(offset_type, additions_cnt + 1);

        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_updates_suboffset, d_updates_offset, additions_cnt + 1);
        gpuErrchk(cudaMalloc(&dev_temp_storage, temp_storage_bytes));
        cub::DeviceScan::ExclusiveSum(dev_temp_storage, temp_storage_bytes, d_updates_suboffset, d_updates_offset, additions_cnt + 1);
        gpuErrchk(cudaDeviceSynchronize());
        gpuErrchk(cudaFree(dev_temp_storage));
        dev_temp_storage = nullptr;
        temp_storage_bytes = 0;

        gpuErrchk(cudaMemcpy(updates_offset, d_updates_offset, sizeof(offset_type) * (additions_cnt + 1), cudaMemcpyDeviceToHost));
        gpuErrchk(cudaDeviceSynchronize());

        
        updates_adjList = CPUAlloc(edge_type, updates_offset[additions_cnt]);
        gpuErrchk(cudaMalloc(&d_updates_adjList, sizeof(edge_type) * updates_offset[additions_cnt]));
        #pragma omp parallel for
        for (edge_type i = 0; i < node_num; ++i) {
            if(!updates_active[i]) 
                continue;
            edge_type vertex = updates_index[i];
            for (offset_type j = updates_offset[vertex]; j < updates_offset[vertex + 1]; ++j) {
                updates_adjList[j] = G.V[i].Neighbors[j - updates_offset[vertex]];
            }
        }

        gpuErrchk(cudaMemcpy(d_updates_adjList, updates_adjList, sizeof(edge_type) * updates_offset[additions_cnt], cudaMemcpyHostToDevice));
        // edge_type max_add_degree = 0;
        // #pragma omp parallel for reduction(max:max_add_degree)
        // for (edge_type i = 0; i < node_num; ++i) {
        //     max_add_degree = std::max(max_add_degree, bucket_count_l[i]);
        // }

        Generate_updates_degree<<<(additions_size / 2 + 1023) / 1024, 1024>>>(d_additions, d_additions_degrees, d_updates_degrees, additions_size / 2);
        // gpuErrchk(cudaMemset(d_now_Edge_del, 0, sizeof(edge_type)));
        if(additions_size != 0) {
            // cout << "sizeof(adjList): " << edge_num * 4 << endl;
            // cout << "sizeof(d_additions_adjList): " << updates_offset[additions_cnt] * 4 << endl;
            // cout << "sizeof(offset): " << (node_num + 1) * 4 << endl;
            // cout << "sizeof(d_additions_offset): " << (additions_cnt + 1) * 4 << endl;
            // cout << "sizeof(d_additions_index): " << (node_num) * 4 << endl;
            // now_csr_mem = (uint64_t)updates_offset[additions_cnt] * 4 + (uint64_t)(additions_cnt + 1) * 4 + (uint64_t)(node_num) * 4;
            gpuErrchk(cudaMemset(d_now_Edge_add, 0, sizeof(edge_type)));
            gpuErrchk(cudaMemset(d_change_count_add, 0, sizeof(unsigned long long int)));
            cudaEvent_t start_add, end_add;
            cudaEventCreate(&start_add);
            cudaEventCreate(&end_add);
            gpuErrchk(cudaEventRecord(start_add, 0));
            TC_kernel<<<1024, 256>>>(d_updates_adjList, d_updates_offset, d_updates_index, d_additions_degrees, additions_size / 2, d_change_count_add, d_hash_bucket_s, d_bucket_count_s, d_bucket_count_s_offset, d_hash_bucket_l, d_bucket_count_l, d_bucket_count_l_offset, d_now_Edge_add, d_limit);
            cudaEventRecord(end_add, 0);
            cudaEventSynchronize(end_add);
            cudaEventElapsedTime(&add_time, start_add, end_add);
#ifndef GRAPHMINE_LIBRARY
            printf("add_time: %f ms\n", add_time);
#endif
            gpuErrchk(cudaMemcpy(&change_count_add, d_change_count_add, sizeof(unsigned long long int), cudaMemcpyDeviceToHost));
#ifndef GRAPHMINE_LIBRARY
            cout << "add change count: " << change_count_add << endl;
#endif
            gpuErrchk(cudaEventDestroy(start_add));
            gpuErrchk(cudaEventDestroy(end_add));
        }
        // cout << "pre_csr_mem: " << pre_csr_mem << endl;
        // cout << "now_csr_mem: " << now_csr_mem << endl;
        
        // cout << "pre_hash_mem: " << pre_hash_mem << endl;
        // cout << "now_hash_mem: " << now_hash_mem << endl;
        free(additions);
        free(updates_offset);
        free(updates_adjList);
        gpuErrchk(cudaFree(d_additions));
        gpuErrchk(cudaFree(d_additions_degrees));
        gpuErrchk(cudaFree(d_hash_bucket_l));
        gpuErrchk(cudaFree(d_hash_bucket_s));
        gpuErrchk(cudaFree(d_additions_l));
        gpuErrchk(cudaFree(d_additions_s));
        gpuErrchk(cudaFree(d_additions_cnt_l));
        gpuErrchk(cudaFree(d_additions_cnt_s));
        gpuErrchk(cudaFree(d_updates_offset));
        gpuErrchk(cudaFree(d_updates_adjList));

        if (deleted_triangle_counts != nullptr) {
            deleted_triangle_counts[batch_index] = change_count_del;
        }
        if (inserted_triangle_counts != nullptr) {
            inserted_triangle_counts[batch_index] = change_count_add;
        }
        if (delete_times_ms != nullptr) {
            delete_times_ms[batch_index] = del_time;
        }
        if (insert_times_ms != nullptr) {
            insert_times_ms[batch_index] = add_time;
        }
        ++batch_index;
    }

    free(updates);
    free(bucket_count_l);
    free(updates_active);
    free(updates_index);
    gpuErrchk(cudaFree(d_updates));
    gpuErrchk(cudaFree(d_updates_cnt));
    gpuErrchk(cudaFree(d_sub_l_cnt));
    gpuErrchk(cudaFree(d_sub_s_cnt));
    gpuErrchk(cudaFree(d_add_l_cnt));
    gpuErrchk(cudaFree(d_add_s_cnt));
    gpuErrchk(cudaFree(d_deletions_cnt));
    gpuErrchk(cudaFree(d_additions_cnt));
    gpuErrchk(cudaFree(d_hash_index_s));
    gpuErrchk(cudaFree(d_hash_index_l));
    gpuErrchk(cudaFree(d_hash_active_s));
    gpuErrchk(cudaFree(d_hash_active_l));
    gpuErrchk(cudaFree(d_bucket_count_s_offset));
    gpuErrchk(cudaFree(d_bucket_count_l_offset));
    gpuErrchk(cudaFree(d_bucket_count_s_suboffset));
    gpuErrchk(cudaFree(d_bucket_count_l_suboffset));
    gpuErrchk(cudaFree(d_limit));
    gpuErrchk(cudaFree(d_bucket_count));
    gpuErrchk(cudaFree(d_bucket_count_s));
    gpuErrchk(cudaFree(d_bucket_count_l));
    gpuErrchk(cudaFree(d_change_count_del));
    gpuErrchk(cudaFree(d_change_count_add));
    gpuErrchk(cudaFree(d_now_Edge_del));
    gpuErrchk(cudaFree(d_now_Edge_add));
    gpuErrchk(cudaFree(d_updates_active));
    gpuErrchk(cudaFree(d_updates_index));
    gpuErrchk(cudaFree(d_updates_degrees));
    gpuErrchk(cudaFree(d_updates_suboffset));
}
void __global__ Generate_InitD(UpdateEdge *updates, edge_type batch_size, Edge *operations, edge_type *operations_size, edge_type *active) {
    edge_type workid = threadIdx.x + blockIdx.x * blockDim.x;
    edge_type index;
    if(workid < batch_size) {
        if(updates[workid].UpdateType == 'd') {
            index = atomicAdd(operations_size , 2);
            // operations[index].source = updates[workid].source;
            // operations[index].destination = updates[workid].destination;
            // operations[index + 1].source = updates[workid].destination;
            // operations[index + 1].destination = updates[workid].source;
            operations[index].setEdge(updates[workid].source, updates[workid].destination);
            operations[index + 1].setEdge(updates[workid].destination, updates[workid].source);
            active[updates[workid].source]  = 1;
            active[updates[workid].destination] = 1;
        }
    }
}
void __global__ Generate_InitA(UpdateEdge *updates, edge_type batch_size, Edge *operations, edge_type *operations_size, edge_type *active) {
    edge_type workid = threadIdx.x + blockIdx.x * blockDim.x;
    edge_type index;
    if(workid < batch_size) {
        if(updates[workid].UpdateType == 'a') {
            index = atomicAdd(operations_size , 2);
            // operations[index].source = updates[workid].source;
            // operations[index].destination = updates[workid].destination;
            // operations[index + 1].source = updates[workid].destination;
            // operations[index + 1].destination = updates[workid].source;
            operations[index].setEdge(updates[workid].source, updates[workid].destination);
            operations[index + 1].setEdge(updates[workid].destination, updates[workid].source);
            active[updates[workid].source]  = 1;
            active[updates[workid].destination] = 1;
        }
    }

}

void __global__ Generate_bucket_count(edge_type *bucket_count, Edge *operations, edge_type operations_size) {
    uint32_t blockdim = blockDim.x;
    uint32_t griddim = gridDim.x;
    uint32_t workid = threadIdx.x + blockDim.x * blockIdx.x;
    // edge_type source, destination, index;
    edge_type source;
    while(workid < operations_size) {
        source = operations[workid].source;
        // destination = operations[workid].destination;
        // index = atomicAdd(&bucket_count[source], 1);
        atomicAdd(&bucket_count[source], 1);
        workid += blockdim * griddim;
    }
}
void __global__ Generate_limit(edge_type *bucket_count, edge_type node_num, bool *limit) {
    uint32_t workid = threadIdx.x + blockDim.x * blockIdx.x;
    if(workid < node_num) {
        // if(bucket_count[workid] <= bucket_limit) {
        //     bucket_count_s[workid] = bucket_count[workid];
        // } else {
        //     limit[workid] = true;
        //     bucket_count_l[workid] = bucket_count[workid];
        // }
        if(bucket_count[workid] > bucket_limit) {
            limit[workid] = true;
        }
    }
}
void __global__ Split_hash(edge_type *bucket_count_s, edge_type *bucket_count_l, edge_type *bucket_count, Edge *updates, edge_type updates_size, bool *limit) {
    uint32_t workid = threadIdx.x + blockDim.x * blockIdx.x;
    edge_type source, destination;
    hash_type key;
    edge_type bin;
    // edge_type index;
    if(workid < updates_size) {
        source = updates[workid].source;
        destination  = updates[workid].destination;
        if(limit[source] || limit[destination]) {
            // key = source << hash_move | destination;
            key = source;
            key = key << hash_move | destination;
            bin = key % bucket_num_l;
            atomicAdd(&bucket_count_l[bin], 1);
            
            // atomicAdd(&bucket_count_l[destination], 1);
        } else {
            // bucket_count_s[source] = bucket_count[source];
            // bucket_count_s[destination] = bucket_count[destination];
            // bucket_count_s[source] ++;
            // bucket_count_s[destination] ++;
            atomicAdd(&bucket_count_s[source], 1);
        }
    }
}
void __global__ Generate_updates_degree(Edge *d_updates, Edge *d_updates_degree, offset_type *d_degrees, edge_type updates_size) {
    uint32_t workid = threadIdx.x + blockDim.x * blockIdx.x;
    edge_type source, destination;
    // edge_type index;
    if(workid < updates_size) {
        source = d_updates[workid << 1].source;
        destination = d_updates[workid << 1].destination;
        if(d_degrees[source] < d_degrees[destination]) {
            d_updates_degree[workid].setEdge(source, destination);
        } else {
            d_updates_degree[workid].setEdge(destination, source);
        }
    }

}

// void __global__ Split_updates(Edge *d_updates_s, Edge *d_updates_l, bool *limit, Edge *updates, edge_type updates_size, edge_type *updates_s_num, edge_type *updates_l_num, offset_type *d_updates_degrees) {
//     uint32_t workid = threadIdx.x + blockDim.x * blockIdx.x;
//     edge_type source, destination;
//     edge_type index;
//     if(workid < updates_size) {
//         source = updates[workid << 1].source;
//         destination = updates[workid << 1].destination;
//         if(d_updates_degrees[source] < d_updates_degrees[destination]) {
//             if(limit[source] || limit[destination]) {
//                 index = atomicAdd(updates_l_num, 1);
//                 d_updates_l[index].source = source;
//                 // d_updates_l[index].destination = destination;
//             } else {
//                 index = atomicAdd(updates_s_num, 1);
//                 d_updates_s[index].source = source;
//                 // d_updates_s[index].destination = destination;
//             }
//         } else {
//             if(limit[source] || limit[destination]) {
//                 index = atomicAdd(updates_l_num, 1);
//                 d_updates_l[index].source = destination;
//                 // d_updates_l[index].destination = source;
//             } else {
//                 index = atomicAdd(updates_s_num, 1);
//                 d_updates_s[index].source = destination;
//                 // d_updates_s[index].destination = source;
//             }
//         }
//     }
// }

void __global__ Generate_hash(edge_type *hash_bucket_s, edge_type *bucket_count_s, offset_type *bucket_count_s_offset, hash_type *hash_bucket_l, edge_type *bucket_count_l, offset_type *bucket_count_l_offset, Edge *operations, edge_type operations_size, bool *limit){
    uint32_t workid = threadIdx.x + blockDim.x * blockIdx.x;
    // printf("workid: %u\n", workid);
    edge_type source, destination;
    edge_type index;
    hash_type key;
    edge_type bin;
    if(workid < operations_size) {
        source = operations[workid].source;
        destination = operations[workid].destination;
        if(limit[source] || limit[destination]) {
            // key = source << hash_move | destination;
            key = source;
            key = key << hash_move | destination;
            bin = key % bucket_num_l;
            index = atomicAdd(&bucket_count_l[bin], 1);
            // index = atomicAdd(&bucket_count_l[source], 1);
            hash_bucket_l[bucket_count_l_offset[bin] + index] = key;
            // d_hash_active_l[source] = source + 1;
            // d_hash_index_l[source] = source;
            // d_hash_active_l[source] = 1;
        } else {
            index = atomicAdd(&bucket_count_s[source], 1);
            hash_bucket_s[bucket_count_s_offset[source] + index] = destination;
            // d_hash_active_s[source] = source + 1;
            // d_hash_index_s[source] = source;
            // d_hash_active_s[source] = 1;
        }
    }
}


void __global__ TC_kernel __launch_bounds__(256, 8)(edge_type *d_updates_adjList, offset_type *d_updates_offset, edge_type *d_updates_index, Edge *d_operations_updates, edge_type operations_size, unsigned long long int *d_change_count, edge_type *d_hash_bucket_s, edge_type *d_bucket_count_s, offset_type *d_bucket_count_s_offset, hash_type *d_hash_bucket_l, edge_type *d_bucket_count_l, offset_type *d_bucket_count_l_offset, edge_type *d_now_Edge, bool *limit) {
    uint32_t tid = threadIdx.x;
    uint32_t warpid = tid / 32;
    uint32_t warptid = tid % 32;
    uint32_t workid;
    edge_type source, destination;
    edge_type source_idx, destination_idx;
    ioffset_type source_degree, destination_degree;
    offset_type source_start, destination_start;
    uint32_t re_change_count = 0;
    __shared__ edge_type small_hash[8][192];
    __shared__ edge_type large_hash[8][192];
    if(warptid == 0) {
        workid = atomicAdd(d_now_Edge, 1);
    }
    workid = __shfl_sync(0xFFFFFFFF, workid, 0);
    while(workid < operations_size) {
        source = d_operations_updates[workid].source;
        destination = d_operations_updates[workid].destination;
        source_idx = d_updates_index[source];
        destination_idx = d_updates_index[destination];
        source_degree = d_updates_offset[source_idx + 1] - d_updates_offset[source_idx];
        destination_degree = d_updates_offset[destination_idx + 1] - d_updates_offset[destination_idx];
        source_start = d_updates_offset[source_idx];
        destination_start = d_updates_offset[destination_idx];
        edge_type small, large;
        if(source < destination) {
            small = source;
            large = destination;
        } else {
            small = destination;
            large = source;
        }
        edge_type small_len, large_len;
        edge_type small_idx, large_idx;
        bool small_l = false, large_l = false;
        if(limit[small]) {
            small_l = true;
        } else {
            small_len = d_bucket_count_s[small];
            small_idx = d_bucket_count_s_offset[small];
            for (uint32_t i = warptid; i < small_len; i += 32) {
                small_hash[warpid][i] = d_hash_bucket_s[small_idx + i];
            }
        }
        if(limit[large]) {
            large_l = true;
        } else {
            large_len = d_bucket_count_s[large];
            large_idx = d_bucket_count_s_offset[large];
            for (uint32_t i = warptid; i < large_len; i += 32) {
                large_hash[warpid][i] = d_hash_bucket_s[large_idx + i];
           }
        }
        bool flag = false;
        short flag2 = 0;
        if(!small_l && !large_l) {

            for (offset_type i = warptid; i < source_degree; i += 32) {
                ioffset_type mid;
                ioffset_type l = 0, r = destination_degree - 1;
                edge_type target = d_updates_adjList[source_start + i];
                flag = false;
                flag2 = 0;
                edge_type key;
                while(l <= r) {
                    mid = l + r >> 1;
                    if(d_updates_adjList[mid + destination_start] == target) {
                        if(target > small && target > large) {
                            re_change_count ++;
                            flag2 = 1;
                            break;
                        }
                        flag2 = 2;
                        break;
                    } else if(d_updates_adjList[mid + destination_start] > target) {
                        r = mid - 1;
                    } else if(d_updates_adjList[mid + destination_start] < target) {
                        l = mid + 1;
                    }
                }
                if(flag2 == 1 || flag2 == 0)
                    continue;
                if(target < small && target < large) {
                    key = target;
                    for (edge_type k = 0; k < small_len; ++k) {
                        if(small_hash[warpid][k] == key) {
                            flag = true;
                            break;
                        }
                    }
                    if(flag)
                        continue;
                    for (edge_type k = 0; k < large_len; ++k) {
                        if(large_hash[warpid][k] == key) {
                            flag = true;
                            break;
                        }
                    }
                    if(flag)
                        continue;
                } 
                else {
                    key = target;
                    for (edge_type k = 0; k < small_len; ++k) {
                        if(small_hash[warpid][k] == key) {
                            flag = true;
                            break;
                        }
                    }
                    if(flag)
                        continue;
                }
                re_change_count++;
            }
        } 
        else if(!small_l && large_l) {
            // printf("Now2\n");
            
            for (offset_type i = warptid; i < source_degree; i += 32) {
                ioffset_type mid;
                ioffset_type l = 0, r = destination_degree - 1;
                edge_type target = d_updates_adjList[source_start + i];
                flag = false;
                flag2 = 0;
                edge_type key;
                hash_type key_l;
                edge_type bucket_len, bucket_idx, bin;
                while(l <= r) {
                    mid = l + r >> 1;
                    if(d_updates_adjList[mid + destination_start] == target) {
                        if(target > small && target > large) {
                            re_change_count++;
                            flag2 = 1;
                            break;
                        }
                        flag2 = 2;
                        break;
                    } else if(d_updates_adjList[mid + destination_start] > target) {
                        r = mid - 1;
                    } else if(d_updates_adjList[mid + destination_start] < target) {
                        l = mid + 1;
                    }
                }
                if(flag2 == 1 || flag2 == 0)
                    continue;
                if(target < small && target < large) {
                    key = target;
                    for (edge_type k = 0; k < small_len; ++k) {
                        if(small_hash[warpid][k] == key) {
                            flag = true;
                            break;
                        }
                    }
                    if(flag)
                        continue;
                    key_l = target;
                    key_l = key_l << hash_move | large;
                    bin = key_l % bucket_num_l;
                    bucket_idx = d_bucket_count_l_offset[bin];
                    bucket_len = d_bucket_count_l[bin];
                    for (edge_type k = 0; k < bucket_len; ++k) {
                        if(d_hash_bucket_l[bucket_idx + k] == key_l) {
                            flag = true;
                            break;
                        }
                    }
                    if(flag)
                        continue;
                } else {
                    key = target;
                    for (edge_type k = 0; k < small_len; ++k) {
                        if(small_hash[warpid][k] == key) {
                            flag = true;
                            break;
                        }
                    }
                    if(flag)
                        continue;
                }
                re_change_count++;
            }
        }
        else if(small_l && !large_l) {
            // printf("Now3\n");
            for (offset_type i = warptid; i < source_degree; i += 32) {
                ioffset_type mid;
                ioffset_type l = 0, r = destination_degree - 1;
                edge_type target = d_updates_adjList[source_start + i];
                flag = false;
                flag2 = 0;
                edge_type key;
                hash_type key_l;
                edge_type bucket_len;
                edge_type bucket_idx;
                edge_type bin;
                while(l <= r) {
                    // printf("Now4\n");
                    mid = l + r >> 1;
                    if(d_updates_adjList[mid + destination_start] == target) {
                        if(target > small && target > large) {
                            re_change_count ++;
                            flag2 = 1;
                            break;
                        }
                        flag2 = 2;
                        break;
                    } else if(d_updates_adjList[mid + destination_start] > target) {
                        r = mid - 1;
                    } else if(d_updates_adjList[mid + destination_start] < target ) {
                        l = mid + 1;
                    }
                }
                if(flag2 == 1 || flag2 == 0)
                    continue;
                if(target < small && target < large) {
                    key = target;
                    for (edge_type k = 0; k < large_len; ++k) {
                        if(large_hash[warpid][k] == key) {
                            flag = true;
                        }
                    }
                    if(flag)
                        continue;
                    key_l = target;
                    key_l = key_l << hash_move | small;
                    bin = key_l % bucket_num_l;
                    bucket_idx = d_bucket_count_l_offset[bin];
                    bucket_len = d_bucket_count_l[bin];
                    for (edge_type k = 0; k < bucket_len; ++k) {
                        if(d_hash_bucket_l[bucket_idx + k] == key_l) {
                            flag = true;
                            break;
                        }
                    }
                    if(flag)
                        continue;
                } 
                else {
                    key_l = target;
                    key_l = key_l << hash_move | small;
                    bin = key_l % bucket_num_l;
                    bucket_idx = d_bucket_count_l_offset[bin];
                    bucket_len = d_bucket_count_l[bin];
                    for (edge_type k = 0; k < bucket_len; ++k) {
                        if(d_hash_bucket_l[bucket_idx + k] == key_l) {
                            flag = true;
                            break;
                        }
                    }
                    if(flag)
                        continue;
                }
                re_change_count++;
            }
        }
        else if(small_l && large_l) {
            // printf("Now4\n");
            for (offset_type i = warptid; i < source_degree; i += 32) {
                ioffset_type mid;
                ioffset_type l = 0, r = destination_degree - 1;
                edge_type target = d_updates_adjList[source_start + i];
                flag = false;
                flag2 = 0;
                hash_type key_l;
                edge_type bucket_len, bucket_idx;
                edge_type bin;
                while(l <= r) {
                    mid = l + r >> 1;
                    if(d_updates_adjList[mid + destination_start] == target) {
                        if(target > small && target > large) {
                            re_change_count++;
                            flag2 = 1;
                            break;
                        }
                        flag2 = 2;
                        break;
                    } else if(d_updates_adjList[mid + destination_start] > target) {
                        r = mid - 1;
                    } else if(d_updates_adjList[mid + destination_start] < target) {
                        l = mid + 1;
                    }
                }
                if(flag2 == 1 || flag2 == 0) 
                    continue;
                if(target < small && target < large) {
                    key_l = target;
                    key_l = key_l << hash_move | small;
                    bin = key_l % bucket_num_l;
                    bucket_idx = d_bucket_count_l_offset[bin];
                    bucket_len = d_bucket_count_l[bin];
                    for (edge_type k = 0; k < bucket_len; ++k) {
                        if(d_hash_bucket_l[bucket_idx + k] == key_l) {
                            flag = true;
                            break;
                        }
                    }
                    if(flag)
                        continue;
                    key_l = target;
                    key_l = key_l << hash_move | large;
                    bin = key_l % bucket_num_l;
                    // bucket_idx = bin * bucket_size_l;
                    bucket_idx = d_bucket_count_l_offset[bin];
                    bucket_len = d_bucket_count_l[bin];
                    for (edge_type k = 0; k < bucket_len; ++k) {
                        if(d_hash_bucket_l[bucket_idx + k] == key_l) {
                            flag = true;
                            break;
                        }
                    }
                    if(flag)
                        continue;
                } else {
                    key_l = target;
                    key_l = key_l << hash_move | small;
                    bin = key_l % bucket_num_l;
                    bucket_idx = d_bucket_count_l_offset[bin];
                    bucket_len = d_bucket_count_l[bin];
                    for (edge_type k = 0; k < bucket_len; ++k) {
                        if(d_hash_bucket_l[bucket_idx + k] == key_l) {
                            flag = true;
                            break;
                        }
                    }
                    if(flag)
                        continue;
                }
                re_change_count++;
            }
        }
        if(warptid == 0)
            workid = atomicAdd(d_now_Edge, 1);
        workid = __shfl_sync(0xFFFFFFFF, workid, 0);
    }
    atomicAdd(d_change_count, re_change_count);
}
