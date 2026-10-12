#include <iostream>
#include <fstream>
#include <cub/cub.cuh>
#include <cuda_runtime.h>

#include "list_ranking.hxx"
#include "common.hxx"

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
void update_first_last_nxt(int* d_edges_from, int* d_edges_to, int* d_first, int* d_last, int* d_next, uint64_t* d_index, int E) {
    
    int thid = blockIdx.x * blockDim.x + threadIdx.x;
    if(thid < E) {
        int f = d_edges_from[d_index[thid]];
        // int t = d_edges_to[d_index[thid]];

        if (thid == 0) {
            d_first[f] = d_index[thid];
            return;
        }

        if(thid == E - 1) {
            d_last[f] = d_index[thid];
        }

        int pf = d_edges_from[d_index[thid - 1]];
        // int pt = d_edges_to[d_index[thid - 1]];

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

    // if(idx == 0) {
    //     for(int i = 0; i < E; ++i) {
    //         printf("devW1Sum: %d\n", devW1Sum[i]);
    //     }
    // }

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
void finalise_level_kernel(
    int* d_edges_from, int* d_edges_to, 
    int* d_parent, 
    int* devRank, 
    int* d_prefix_sum, 
    int* d_level, 
    int E) {
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

// remove memory allocations from here
// removed
void LexSortIndices(
    int* d_keys, int* d_values, 
    uint64_t* d_indices_sorted, 
    uint64_t* d_merged, 
    uint64_t* d_merged_keys_sorted,
    uint64_t* d_indices,
    int num_items) {

    // uint64_t *d_merged, *d_merged_keys_sorted;
    // cudaMalloc(&d_merged, sizeof(uint64_t) * num_items);
    // cudaMalloc(&d_merged_keys_sorted, sizeof(uint64_t) * num_items);

    // uint64_t* d_indices;
    // cudaMalloc(&d_indices, sizeof(uint64_t)* num_items);   

    int blockSize = 1024;
    int numBlocks = (num_items + blockSize - 1) / blockSize; 

    // Initialize indices to 0, 1, 2, ..., num_items-1 also here
    merge_key_value<<<numBlocks, blockSize>>>(
        d_keys, 
        d_values, 
        d_merged, 
        d_indices, 
        num_items);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize");

    void *d_temp_storage = nullptr;
    size_t temp_storage_bytes = 0;
    
    // Determine temporary storage requirements
    cub::DeviceRadixSort::SortPairs(d_temp_storage, temp_storage_bytes, d_merged, d_merged_keys_sorted, d_indices, d_indices_sorted, num_items);
    cudaMalloc(&d_temp_storage, temp_storage_bytes);
    // Sort indices based on keys
    cub::DeviceRadixSort::SortPairs(d_temp_storage, temp_storage_bytes, d_merged, d_merged_keys_sorted, d_indices, d_indices_sorted, num_items);
}

// remove memory allocations from here
// removed
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

    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize");

    void *d_temp_storage = NULL;
    size_t temp_storage_bytes = 0;

    // int* d_level_info;
    // CUCHECK(cudaMalloc(&d_level_info, sizeof(int)*E));

    cub::DeviceScan::InclusiveSum(d_temp_storage, temp_storage_bytes, devW1Sum, d_level_info, E);
    // Allocate temporary storage
    CUDA_CHECK(cudaMalloc(&d_temp_storage, temp_storage_bytes), "Failed to allocate d_temp_storage");
    // Run inclusive prefix sum
    cub::DeviceScan::InclusiveSum(d_temp_storage, temp_storage_bytes, devW1Sum, d_level_info, E);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize");

    // devRank contains the prefix sum result
    finalise_level_kernel<<<numBlocks, blockSize>>>(
        d_edges_from, d_edges_to, 
        d_parent, devRank, d_level_info,
        d_level, E);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize");
}

__global__ 
void init_arrays(
    int *d_next, int *d_parent, int *d_level,
    int *d_first, int *d_last, 
    int* d_first_occ, int* d_last_occ, 
    int root, int E, int N) {

    int idx = blockIdx.x * blockDim.x + threadIdx.x;

    if (idx < E) {
        // Initialize d_next array
        d_next[idx] = -1;  // You can modify this initialization as per your requirement
    }

    if (idx < N) {
        // Initialize d_parent, d_first, and d_last arrays
        d_parent[idx] = idx;
        d_first[idx] = -1;
        d_last[idx] = -1;
        d_level[idx] = 0;

        if (idx == root) {
            d_first_occ[idx] = 0;
            d_last_occ[idx] = (2 * N) - 1;
        } else {
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
    uint64_t* d_edges_input,
    int N, 
    int root,
    graph_data& d_input) {

    int E = N * 2 - 2;
    int roots_count = 1;

    // Temporary device buffers
    d_vector<int> d_edges_to(E);
    d_vector<int> d_edges_from(E);

    d_vector<uint64_t> d_index(E);
    d_vector<int> d_next(E);
    d_vector<int> d_roots(1);

    d_vector<int> d_first(N);
    d_vector<int> d_last(N);

    d_vector<int> succ(E);
    d_vector<int> devRank(E);

    // List Ranking parameters 
    int* notAllDone = nullptr;
    CUDA_CHECK(cudaMallocHost((void **)&notAllDone, sizeof(int)), "Failed to allocate notAllDone");
    d_vector<ull> devRankNext(E);
    d_vector<int> devNotAllDone(1);
    d_vector<int> devW1Sum(E);

    // Output buffers that we want to return as raw pointers.
    d_vector<int> d_parent(N);
    d_vector<int> d_level(N);
    d_vector<int> d_first_occ(N);
    d_vector<int> d_last_occ(N);

    // Additional temporary buffers.
    d_vector<int> d_level_info(E);
    d_vector<uint64_t> d_merged(E);
    d_vector<uint64_t> d_merged_keys_sorted(E);
    d_vector<uint64_t> d_indices(E);

    // Copy the root value to device memory.
    CUDA_CHECK(cudaMemcpy(d_roots.get(), &root, sizeof(int), cudaMemcpyHostToDevice), "Failed to copy root");

    int blockSize = 1024;
    int numBlocks = (E + blockSize - 1) / blockSize;

    init_arrays<<<numBlocks, blockSize>>>(
        d_next.get(), 
        d_parent.get(), 
        d_level.get(), 
        d_first.get(), 
        d_last.get(),
        d_first_occ.get(),
        d_last_occ.get(),
        root,
        E, N);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize init_arrays kernel");

    // auto start = std::chrono::high_resolution_clock::now();
    CudaTimer Timer;
    Timer.start();
    numBlocks = (N - 1 + blockSize - 1) / blockSize;
    create_dup_edges<<<numBlocks, blockSize>>>(
        d_edges_to.get(), 
        d_edges_from.get(), 
        d_edges_input, 
        root, 
        N);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize create_dup_edges kernel");

    // #ifdef DEBUG
    //     std::cout << "Printing from Euler Tour after creating duplicates:\n";
    //     DisplayDeviceEdgeList(d_edges_from.get(), d_edges_to.get(), E);
    // #endif

    numBlocks = (E + blockSize - 1) / blockSize;
    LexSortIndices(d_edges_from.get(), d_edges_to.get(), d_index.get(),
                   d_merged.get(), d_merged_keys_sorted.get(), d_indices.get(), E);

    // #ifdef DEBUG
    //     std::cout << "Index array:\n";
    //     print_device_array(d_index.get(), E);
    // #endif

    update_first_last_nxt<<<numBlocks, blockSize>>>(
        d_edges_from.get(), 
        d_edges_to.get(), 
        d_first.get(), 
        d_last.get(), 
        d_next.get(), 
        d_index.get(), 
        E);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize update_first_last_nxt");

    cal_succ<<<numBlocks, blockSize>>>(succ.get(), d_next.get(), d_first.get(), d_edges_from.get(), E);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize cal_succ");

    // #ifdef DEBUG
    //     std::cout << "Successor array before break_cycle_kernel:\n";
    //     print_device_array(succ.get(), E);
    // #endif

    numBlocks = (roots_count + blockSize - 1) / blockSize;
    break_cycle_kernel<<<numBlocks, blockSize>>>(d_last.get(), succ.get(), d_roots.get(), roots_count, E);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize break_cycle_kernel");

    CudaSimpleListRank(
        devRank.get(), E, succ.get(), 
        notAllDone, devRankNext.get(), devNotAllDone.get());

    // #ifdef DEBUG
    //     std::cout << "Euler Path array:\n";
    //     print_device_array(devRank.get(), E);
    // #endif

    numBlocks = (E + blockSize - 1) / blockSize;
    find_parent<<<numBlocks, blockSize>>>(E, devRank.get(), d_edges_to.get(), d_edges_from.get(), d_parent.get());
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize");

    compute_level(devRank.get(), d_edges_from.get(), d_edges_to.get(), d_parent.get(),
                  devW1Sum.get(), d_level.get(), d_level_info.get(), N, E);
    
    // #ifdef DEBUG
    //     std::cout << "Parent array:" << std::endl;
    //     print_device_array(d_parent.get(), N);
    //     std::cout << "Level array:" << std::endl;
    //     print_device_array(d_level.get(), N);
    // #endif

    numBlocks = (E + blockSize - 1) / blockSize;
    compute_first_last_occ<<<numBlocks, blockSize>>>(
        d_edges_from.get(), 
        d_edges_to.get(), 
        d_first_occ.get(), 
        d_last_occ.get(), 
        d_level.get(),
        devRank.get(), 
        E);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize");

    // auto end = std::chrono::high_resolution_clock::now();
    // auto dur = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
    auto dur = Timer.stop();
    // std::cout << "Eulerian Tour Construction time: " << dur << " ms." << std::endl;
    add_function_time("Eulerian Tour", dur);

    #ifdef DEBUG
        d_parent.print("Parent");
        d_level.print("Level");
        d_first_occ.print("First");
        d_last_occ.print("Last");
    #endif

    // Free pinned host memory.
    CUDA_CHECK(cudaFreeHost(notAllDone), "Failed to free notAllDone");

    // **Release the output buffers so that ownership is transferred:**
    // The caller will now be responsible for freeing these device arrays.
    d_input.parent = d_parent.release();
    d_input.first = d_first_occ.release();
    d_input.last  = d_last_occ.release();

    return dur;
}
