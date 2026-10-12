#ifndef SPANNING_TREE_CUH
#define SPANNING_TREE_CUH

#include <iostream>
#include <cuda_runtime.h>
#include <fstream>

#include "common.hxx"
#include "euler.hxx"

//#define DEBUG
#define tb_size 1024

// marked
__device__ 
inline int custom_compress(int i, int* temp_label) {
    int j = i;
    if (temp_label[j] == j) {
        return j;
    }
    do {
        j = temp_label[j];
    } while (temp_label[j] != j);

    int tmp;
    while ((tmp = temp_label[i]) > j) {
        temp_label[i] = j;
        i = tmp;
    }
    return j;
}

// marked
__device__ 
inline bool union_async(long idx, int src, int dst, int* temp_label, uint64_t* edges, uint64_t* st_edges) {
    while (1) {
        int u = custom_compress(src, temp_label);
        int v = custom_compress(dst, temp_label);
        if (u == v) break;
        if (v > u) { int temp; temp = u; u = v; v = temp; }
        if (u == atomicCAS(&temp_label[u], u, v)) {
           st_edges[u] = edges[idx];
           return true;
        }
    }
    return false;
}

// marked
__global__ 
void union_find_gpu(long total_elt, int* temp_label, uint64_t* edges, uint64_t* st_edges) {
    long idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < total_elt) {
        int u = edges[idx] >> 32;
        int v = edges[idx] & 0xFFFFFFFF;
        if (u < v) {
            union_async(idx, u, v, temp_label, edges, st_edges);
        }
    }
}

// marked
__global__
void init_parent_label_st_edges(int* temp_label, uint64_t* st_edges, int V) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < V) {
        temp_label[idx] = idx;
        st_edges[idx] = INT_MAX;
    }
}

float construct_st(graph_data& d_input) {

    uint64_t* d_edgelist = d_input.edgelist; 
    int numVert = d_input.V;
    long numEdges = d_input.E;

    d_vector<int> temp_label(numVert);
    d_vector<uint64_t> st_edges(numVert);

    int grid_size_final = CEIL(numVert, tb_size);

    init_parent_label_st_edges<<<grid_size_final, tb_size>>>(
        temp_label.get(), 
        st_edges.get(), 
        numVert);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize");

    CudaTimer Timer;
    Timer.start();
    // run union-find 
    long grid_size_union = CEIL(numEdges, tb_size);
    union_find_gpu<<<grid_size_union, tb_size>>>(numEdges, temp_label.get(), d_edgelist, st_edges.get());
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize union_find_gpu_COO");
    
    auto dur = Timer.stop();
    add_function_time("AST Construction", dur);
    
    d_input.root = 0;
    auto euler_ms = cuda_euler_tour(st_edges.get(), numVert, d_input.root, d_input);

    return dur + euler_ms;
}

#endif // SPANNING_TREE_CUH