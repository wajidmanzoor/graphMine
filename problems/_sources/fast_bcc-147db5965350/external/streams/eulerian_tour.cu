#include <iostream>
#include <fstream>
#include <chrono>
#include <cub/cub.cuh>
#include <cuda_runtime.h>
#include <set>
#include "include/list_ranking.cuh"
#include "include/cuda_utility.cuh"
#include "include/util.cuh"

// #define DEBUG

__global__ 
void create_dup_edges(
    int *d_edges_to, 
    int *d_edges_from, 
    const uint64_t *d_edges_input, 
    const int root,
    int N) {
    int thid = blockIdx.x * blockDim.x + threadIdx.x;
    
    if (thid < N) {

        if (thid == root)
          return;

        int edge_count = N - 1;
        uint64_t i = d_edges_input[thid];

        int u = i >> 32;  // Extract higher 32 bits
        int v = i & 0xFFFFFFFF; // Extract lower 32 bits
        
        int afterRoot = thid > root;
        // printf("For thid: %d, thid - afterRoot: %d, thid - afterRoot + edge_count: %d\n", thid, thid - afterRoot, thid - afterRoot + edge_count);

        d_edges_from[thid - afterRoot + edge_count] = d_edges_to[thid - afterRoot] = v;
        d_edges_to[thid - afterRoot + edge_count] = d_edges_from[thid - afterRoot] = u;
    }
}

__global__
void init_nxt(int* d_next, int E) {
    int thid = blockIdx.x * blockDim.x + threadIdx.x;
    if (thid < E) {
        d_next[thid] = -1;
    }
}

__global__
void update_first_last_nxt(int* d_edges_from, int* d_edges_to, int* d_first, int* d_last, int* d_next, uint64_t* d_index, int E) {
    
    int thid = blockIdx.x * blockDim.x + threadIdx.x;
    if(thid < E) {
        int f = d_edges_from[d_index[thid]];
        int t = d_edges_to[d_index[thid]];

        if (thid == 0) {
            d_first[f] = d_index[thid];
            return;
        }

        if(thid == E - 1) {
            d_last[f] = d_index[thid];
        }

        int pf = d_edges_from[d_index[thid - 1]];
        int pt = d_edges_to[d_index[thid - 1]];

        // printf("For tid: %d, f: %d, t: %d, pf: %d, pt: %d\n", thid, f, t, pf, pt);

        // calculate the offset array
        if (f != pf) {
            d_first[f] = d_index[thid];
            // printf("d_last[%d] = d_index[%d] = %d\n", pf, thid - 1, d_index[thid - 1]);
            d_last[pf] = d_index[thid - 1];
        } else {
            d_next[d_index[thid - 1]] = d_index[thid];
        }
    }
}

__global__ 
void cal_succ(int* succ, const int* d_next, const int* d_first, const int* d_edges_from, int E) {
    int thid = blockIdx.x * blockDim.x + threadIdx.x;
    if (thid < E) {
        int revEdge = (thid + E / 2) % E;

        if (d_next[revEdge] == -1) {
            succ[thid] = d_first[d_edges_from[revEdge]];
        } else {
            succ[thid] = d_next[revEdge];
        }
    }
}

__global__ 
void break_cycle_kernel(int *d_last, int *d_succ, int* d_roots, int roots_count, int E) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < roots_count) {
        int root = d_roots[idx];
        // printf("Root: %d\n", root);
        if (d_last[root] != -1) {
            int last_edge = d_last[root];
            int rev_edge = (last_edge + E / 2) % E;
            // printf("\nFor root: %d, last_edge: %d, rev_edge: %d\n", root, last_edge, rev_edge);
            // Set the successor of the last edge to point to itself
            d_succ[rev_edge] = -1;
        }
    }
}

__global__
void init_parent(int* d_parent, int N) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < N) {
        d_parent[idx] = idx;
    }
}

__global__
void find_parent(int E, int *rank, int *d_edges_to, int *d_edges_from, int *parent) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if(tid < E) {
        int f = d_edges_from[tid];
        int t = d_edges_to[tid];
        int rev_edge = (tid + E / 2) % E;
        // printf("for tid: %d, f: %d, t: %d, rev_edge: %d\n", tid, f, t, rev_edge);
        if(rank[tid] > rank[rev_edge]) {
            parent[t] = f;
        }
        else {
            parent[f] = t;
        }
    }
}

__global__ 
void merge_key_value(const int *arrayU, const int *arrayV, uint64_t *arrayE, uint64_t *d_indices, long size) {
    int64_t idx = blockIdx.x * blockDim.x + threadIdx.x;

    if (idx < size) {
        // Cast to int64_t to ensure the shift operates on 64 bits
        uint64_t u = arrayU[idx];
        uint64_t v = arrayV[idx];

        arrayE[idx] = (u << 32) | (v & 0xFFFFFFFFLL);

        d_indices[idx] = idx;
    }
}

__global__
void compute_level_kernel(
    int* devRank, int* d_edges_from, int* d_edges_to, 
    int* d_parent, int* devW1Sum, int N, int E) {

    int idx = blockIdx.x * blockDim.x + threadIdx.x;

    if (idx < E) {
        int loc = E - 1 - devRank[idx];
        // idx is the edge number, so lets retrive the edge first
        int u = d_edges_from[idx];
        int v = d_edges_to[idx];
        
        if(d_parent[v] == u)
            devW1Sum[loc] = 1;
        else
            devW1Sum[loc] = -1;
    }
}

__global__
void finalise_level_kernel(int* d_edges_from, int* d_edges_to, int* d_parent, int* devRank, int* d_prefix_sum, int* d_level, int E) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;

    if(idx < E) {
        int loc = E - 1 - devRank[idx];
        int u = d_edges_from[idx];
        int v = d_edges_to[idx];

        // (p(V)，v)
        if(d_parent[v] == u) {
            //printf("u: %d, v: %d, d_prefix_sum[%d]: %d \n", u, v, idx, d_prefix_sum[idx]);
            d_level[v] = d_prefix_sum[loc];
        }
    }
}

void LexSortIndices(
    int* d_keys, int* d_values, 
    uint64_t* d_indices_sorted, 
    uint64_t *d_merged, 
    uint64_t *d_merged_keys_sorted, 
    uint64_t* d_indices,
    int num_items) {

    int blockSize = 1024;
    int numBlocks = (num_items + blockSize - 1) / blockSize; 

    // Initialize indices to 0, 1, 2, ..., num_items-1 also here
    merge_key_value<<<numBlocks, blockSize>>>(
        d_keys, 
        d_values, 
        d_merged, 
        d_indices, 
        num_items);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize merge_key_value kernel");

    void *d_temp_storage = nullptr;
    size_t temp_storage_bytes = 0;
    
    // Determine temporary storage requirements
    cub::DeviceRadixSort::SortPairs(d_temp_storage, temp_storage_bytes, d_merged, d_merged_keys_sorted, d_indices, d_indices_sorted, num_items);
    cudaMalloc(&d_temp_storage, temp_storage_bytes);
    // Sort indices based on keys
    cub::DeviceRadixSort::SortPairs(d_temp_storage, temp_storage_bytes, d_merged, d_merged_keys_sorted, d_indices, d_indices_sorted, num_items);

    cudaFree(d_temp_storage);
}

void compute_level(
    int* devRank, int* d_edges_from, int* d_edges_to, 
    int* d_parent, int* devW1Sum, int* d_level, int* d_level_info, int N, int E) {

    int blockSize = 1024;
    int numBlocks = (E + blockSize - 1) / blockSize;

    compute_level_kernel<<<numBlocks, blockSize>>>(
        devRank, 
        d_edges_from, 
        d_edges_to, 
        d_parent, 
        devW1Sum, 
        N, E);

    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize compute_level_kernel kernel");

    void *d_temp_storage = NULL;
    size_t temp_storage_bytes = 0;

    cub::DeviceScan::InclusiveSum(d_temp_storage, temp_storage_bytes, devW1Sum, d_level_info, E);
    // Allocate temporary storage
    CUDA_CHECK(cudaMalloc(&d_temp_storage, temp_storage_bytes), "Failed to allocate d_temp_storage");
    // Run inclusive prefix sum
    cub::DeviceScan::InclusiveSum(d_temp_storage, temp_storage_bytes, devW1Sum, d_level_info, E);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize InclusiveSum kernel");

    // devRank contains the prefix sum result
    finalise_level_kernel<<<numBlocks, blockSize>>>(
        d_edges_from, d_edges_to, 
        d_parent, devRank, d_level_info,
        d_level, E);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize finalise_level_kernel kernel");
    CUDA_CHECK(cudaFree(d_temp_storage), "Failed to free d_temp_storage");
}

__global__
void init_firstandlast_occ(int* d_first_occ, int* d_last_occ, int N) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < N) {
        if(idx==0){
        d_first_occ[idx] = 0;
        d_last_occ[idx] = (2*N) - 1;
        }
        else{
        d_first_occ[idx] = -1;
        d_last_occ[idx] = -1;
        }
    }
}

__global__
void compute_first_last_occ(
    int* d_edges_from, 
    int* d_edges_to, 
    int* d_first_occ, 
    int* d_last_occ, 
    int* d_level,
    int* devRank, 
    int E) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < E) {
        int u = d_edges_to[idx];
        int v = d_edges_from[idx];  

        if(d_level[u] > d_level[v]) {
            d_last_occ[u] = devRank[idx] + 1;
        } else if(d_level[u] < d_level[v]) {
            d_first_occ[v] = devRank[idx] + 1;
        }
    }
}

float cuda_euler_tour(
    int N, 
    int root, 
    uint64_t* d_edges_input,
    int* d_first_occ,
    int* d_last_occ,
    int* d_parent) {


    float total_time = 0.0;

    int E = N * 2 - 2;
    int roots_count = 1;
    
    #ifdef DEBUG
        std::cout << "Edge input to Euler Tour:\n";
        print_device_edges(d_edges_input, N);
    #endif
    
    int *d_edges_to;
    int *d_edges_from;
    CUDA_CHECK(cudaMalloc((void **)&d_edges_to, sizeof(int) * E), "Failed to allocate d_edges_to");
    CUDA_CHECK(cudaMalloc((void **)&d_edges_from, sizeof(int) * E), "Failed to allocate d_edges_from");

    // index can be considered as edge_num
    uint64_t *d_index;
    CUDA_CHECK(cudaMalloc((void **)&d_index, sizeof(uint64_t) * E), "Failed to allocate d_index");

    int *d_next;
    CUDA_CHECK(cudaMalloc((void **)&d_next, sizeof(int) * E), "Failed to allocate d_next");

    int *d_roots;
    CUDA_CHECK(cudaMalloc((void **)&d_roots, sizeof(int) * roots_count), "Failed to allocate d_roots");

    // print_mem_info1();

    int *d_level;
    CUDA_CHECK(cudaMalloc((void **)&d_level, sizeof(int) * N), "Failed to allocate d_level");

    int *devW1Sum;
    CUDA_CHECK(cudaMalloc((void **)&devW1Sum, sizeof(int) * E), "Failed to allocate devW1Sum");

    CUDA_CHECK(cudaMemcpy(d_roots, &root, sizeof(int), cudaMemcpyHostToDevice), "Failed to copy root to device memory");

    // these three are LexSortIndices
    uint64_t *d_merged, *d_merged_keys_sorted, *d_indices;
    CUDA_CHECK(cudaMalloc(&d_merged, sizeof(uint64_t) * E), "Failed to allocate d_merged");
    CUDA_CHECK(cudaMalloc(&d_merged_keys_sorted, sizeof(uint64_t) * E), "Failed to allocate d_merged_keys_sorted");
    print_mem_info();
    std::cout << "Required memory for d_indices: " << sizeof(uint64_t) * E << std::endl;
    CUDA_CHECK(cudaMalloc(&d_indices, sizeof(uint64_t) * E), "Failed to allocate d_indices");

    // this is for compute_level
    int* d_level_info;
    CUDA_CHECK(cudaMalloc(&d_level_info, sizeof(int) * E), "Failed to allocate d_level_info");

    // final output arrays
    int *d_first;
    CUDA_CHECK(cudaMalloc((void **)&d_first, sizeof(int) * N), "Failed to allocate d_first");
    int *d_last;
    CUDA_CHECK(cudaMalloc((void **)&d_last, sizeof(int) * N), "Failed to allocate d_last");

    CUDA_CHECK(cudaMemset(d_first, -1, sizeof(int) * N), "Failed to initialize d_first with -1");
    CUDA_CHECK(cudaMemset(d_last, -1, sizeof(int) * N), "Failed to initialize d_last with -1");

    int *succ;
    CUDA_CHECK(cudaMalloc((void **)&succ, sizeof(int) * E), "Failed to allocate succ");

    int *devRank;
    CUDA_CHECK(cudaMalloc((void **)&devRank, sizeof(int) * E), "Failed to allocate devRank");

    int blockSize = 1024;
    int numBlocks = (N + blockSize - 1) / blockSize; 

    auto start = std::chrono::high_resolution_clock::now();
    
    // Launch the kernel
    create_dup_edges<<<numBlocks, blockSize>>>(
        d_edges_to, 
        d_edges_from, 
        d_edges_input, 
        root, 
        N);

    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize create_dup_edges kernel");

    // std::cout << "Completed Create dup kernel " << std::endl;
    
    #ifdef DEBUG
        std::cout << "Printing from Euler Tour after creating duplicates:\n";
        DisplayDeviceEdgeList(d_edges_from, d_edges_to, E);
    #endif

    numBlocks = (E + blockSize - 1) / blockSize;

    init_nxt<<<numBlocks, blockSize>>>(d_next, E);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize init_nxt kernel"); 

    // std::cout << "Completed init next kernel " << std::endl;

    LexSortIndices(
        d_edges_from, d_edges_to, 
        d_index, 
        d_merged, 
        d_merged_keys_sorted, 
        d_indices, E);

    // std::cout << "Completed Lex sorting " << std::endl;

    #ifdef DEBUG
        std::cout << "Index array:\n";
        print_device_array(d_index, E);

        std::vector<int> sorted_from(E), sorted_to(E);
        std::vector<uint64_t> sorted_index(E);
        
        CUDA_CHECK(cudaMemcpy(sorted_index.data(), d_index, sizeof(uint64_t) * E, cudaMemcpyDeviceToHost), "Failed to copy back d_index");
        CUDA_CHECK(cudaMemcpy(sorted_from.data(), d_edges_from, sizeof(int) * E, cudaMemcpyDeviceToHost), "Failed to copy back d_edges_from");
        CUDA_CHECK(cudaMemcpy(sorted_to.data(), d_edges_to, sizeof(int) * E, cudaMemcpyDeviceToHost), "Failed to copy back d_edges_to");

        // Print the sorted edges
        std::cout << "Sorted Edges:" << std::endl;
        for (int i = 0; i < E; ++i) {
            int idx = sorted_index[i];
            std::cout << i << ": (" << sorted_from[idx] << ", " << sorted_to[idx] << ")" << std::endl;
        }
    #endif

    update_first_last_nxt<<<numBlocks, blockSize>>>(
        d_edges_from, 
        d_edges_to, 
        d_first, 
        d_last, 
        d_next, 
        d_index, 
        E);

    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize update_first_last_nxt kernel");

    cal_succ<<<numBlocks, blockSize>>>(succ, d_next, d_first, d_edges_from, E);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize call_succ kernel");

    // std::cout << "Completed init update_first_last_nxt kernel " << std::endl;


    // std::cout << "successor array before break_cycle_kernel:\n";
    // print_device_array(succ, E);

    // break cycle_kernel
    numBlocks = (roots_count + blockSize - 1) / blockSize;
    break_cycle_kernel<<<numBlocks, blockSize>>>(d_last, succ, d_roots, roots_count, E);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize break_cycle_kernel kernel");

    // std::cout << "successor array after break_cycle_kernel:\n";
    // print_device_array(succ, E);

    // std::cout << "Completed Break Cycle Kernel" << std::endl;

    CudaSimpleListRank(devRank, E, succ);

    #ifdef DEBUG
        std::cout << "d_first array:\n";
        print_device_array(d_first, N);

        std::cout << "d_last array:\n";
        print_device_array(d_last, N);

        std::cout << "d_next array:\n";
        print_device_array(d_next, E);

        std::cout << "successor array:\n";
        print_device_array(succ, E);

        std::cout << "euler Path array:\n";
        print_device_array(devRank, E);
    #endif

    // std::cout << "Completed List Ranking" << std::endl;

    numBlocks = (N + blockSize - 1) / blockSize;

    init_parent<<<numBlocks, blockSize>>>(d_parent, N);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize init_parent kernel");

    numBlocks = (E + blockSize - 1) / blockSize;
    find_parent<<<numBlocks, blockSize>>>(E, devRank, d_edges_to, d_edges_from, d_parent);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize find_parent kernel");

    // compute level
    compute_level(devRank, d_edges_from, d_edges_to, d_parent, devW1Sum, d_level, d_level_info, N, E);
    // std::cout << "Completed calculating level " << std::endl;
    
    init_firstandlast_occ<<<(N + 1023)/1024 , 1024>>>(d_first_occ, d_last_occ, N);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize init_firstandlast_occ kernel");

    compute_first_last_occ<<<(E + 1023)/1024 , 1024>>>(
        d_edges_from, 
        d_edges_to, 
        d_first_occ, 
        d_last_occ, 
        d_level,
        devRank, 
        E);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize device");

    auto end = std::chrono::high_resolution_clock::now();
    total_time += std::chrono::duration<float, std::milli>(end - start).count();

    bool g_verbose = false;

    if(g_verbose) {
        std::cout << "Parent array:\n";
        print_device_array(d_parent, N);

        // std::cout << "devW1Sum array:\n";
        // print_device_array(devW1Sum, E);

        std::cout << "d_level array:\n";
        print_device_array(d_level, N);

        std::cout << "First array:\n";
        print_device_array(d_first_occ, N);

        std::cout << "Last array:\n";
        print_device_array(d_last_occ, N);
    }

    std::cout << "Going to find max level " << std::endl;
    int max_level = findMax(d_level, N);

    std::cout << "Max Level: " << max_level << std::endl;

    CUDA_CHECK(cudaFree(d_edges_to), "Failed to free d_edges_to");
    CUDA_CHECK(cudaFree(d_edges_from), "Failed to free d_edges_from");
    CUDA_CHECK(cudaFree(d_roots), "Failed to free d_roots");
    CUDA_CHECK(cudaFree(devRank), "Failed to free devRank");
    CUDA_CHECK(cudaFree(devW1Sum), "Failed to free devW1Sum");
    CUDA_CHECK(cudaFree(d_level), "Failed to free d_level");
    
    CUDA_CHECK(cudaFree(d_merged), "Failed to free d_merged");
    CUDA_CHECK(cudaFree(d_merged_keys_sorted), "Failed to free d_merged_keys_sorted");
    CUDA_CHECK(cudaFree(d_indices), "Failed to free d_indices");
    CUDA_CHECK(cudaFree(d_level_info), "Failed to free d_level_info");
    
    CUDA_CHECK(cudaFree(d_index), "Failed to free d_index");
    CUDA_CHECK(cudaFree(d_next), "Failed to free d_next");
    CUDA_CHECK(cudaFree(d_first), "Failed to free d_first");
    CUDA_CHECK(cudaFree(d_last), "Failed to free d_last");
    CUDA_CHECK(cudaFree(succ), "Failed to free succ");


    return total_time;
}
