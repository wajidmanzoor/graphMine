#include <stdio.h>
#include <stdlib.h>
#include "include/graph.cuh"
#include "include/hbcg_utils.cuh"
#include "parlay/sequence.h"
#include "parlay/parallel.h"
#include "include/host_spanning_tree.cuh"
#include "include/GPUSpanningtree.cuh"
#include "include/ExternalSpanningTree.cuh"
#include "include/euler.cuh"
#include "include/SpanningForest.cuh"
#include "include/cuda_utility.cuh"
#include "include/sparse_table_min.cuh"
#include "include/sparse_table_max.cuh"
#include "include/CC.cuh"
#include "include/Timer.hpp"
#include <chrono>

using namespace std;

struct graph_data_host h_input;


struct graph_data d_input;
struct graph_data h_input_gpu;

int Batch_Size;

#define tb_size 1024
#define LOCAL_BLOCK_SIZE 100

__global__
void merge_w1_w2(int n, int* w1_copy, int* w2_copy, int* w1, int* w2){
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if(i < n){
        w1[i] = min(w1[i], w1_copy[i]);
        w2[i] = max(w2[i], w2_copy[i]);
    }
}

__global__
void fill_w1_w2(uint64_t* edge_list, long numEdges, int* w1, int* w2, int* parent , int* first_occ , int* last_occ) {
    long idx = blockIdx.x * blockDim.x + threadIdx.x ;
    if (idx < numEdges ) {
        if(edge_list[idx] == INT_MAX) return;
        int u = (edge_list[idx] >> 32) & 0xFFFFFFFF;
        int v = edge_list[idx] & 0xFFFFFFFF;
        if(u<v){
            if(first_occ[u] < first_occ[v]) {
                atomicMin(&w1[v], first_occ[u]);
                atomicMax(&w2[u], first_occ[v]);
            }
            else {
                atomicMin(&w1[u], first_occ[v]);
                atomicMax(&w2[v], first_occ[u]);
            }
        }
    }
}

__global__
void compute_a1(int* first_occ, int* last_occ, int numVert , int* w1 , int* a1) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numVert) {
        a1[first_occ[idx]] = w1[idx];
        a1[last_occ[idx]] = w1[idx];
    }
}

__global__
void fill_left_right(int* first_occ , int* last_occ, int numVert, int* left, int* right) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numVert) {
        left[idx] = first_occ[idx];
        right[idx] = last_occ[idx];
    }
}

__global__
void mark_fence(uint64_t* edge_list, long numEdges, int* low, int* high, int* first_occ, int* last_occ, int* d_parent, bool* fg) {
    long idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numEdges) {
        if(edge_list[idx] == INT_MAX){
            fg[idx] = false;
            return;
        }
        int u = (edge_list[idx] >> 32) & 0xFFFFFFFF;
        int v = edge_list[idx] & 0xFFFFFFFF;
        int f_u = first_occ[u];
        int l_u = last_occ[u];

        int f_v = first_occ[v];
        int l_v = last_occ[v];
        
        int low_u = low[u];
        int high_u = high[u];
        
        int low_v = low[v];
        int high_v = high[v];
        
        if(d_parent[u] != v && d_parent[v] != u) {
            if(f_u <= f_v && l_u>=f_v  || f_v <= f_u && l_v>=f_u) {
                // printf("u = %d , v = %d is a back edge\n", u, v);
                fg[idx] = false;
            }
            else{
                fg[idx] = true;
            }
        }
        else{
            if(f_u<=low_v && l_u>=high_v  || f_v<=low_u && l_v>=high_u) {
                // printf("u = %d , v = %d is a fence edge %d\n", u, v);
                fg[idx] = false;
            }
            else{
                fg[idx] = true;
            }

        }
    }
}

__global__ 
void give_label_to_root(int* rep, int* parent, int numVert, int root) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numVert && idx > 0) {
        int temp = parent[idx];
        if(temp == 0) {
            if(rep[idx] != 0)
            rep[0] = rep[idx];
        }
    }
}

int main(int argc, char *argv[]) {
    if (argc < 3){
        printf("Usage: %s <input_file> <Batch_Size>\n", argv[0]);
        exit(1);
    }
    const int GPU_share = 1;
    int root = 0;
    bool detail = false;
    
    if(argv[3])
        detail = true;

    printf("Started Reading\n");

    float time_ms = 0.0;
    Batch_Size = atoi(argv[2]);
    undirected_graph G(argv[1]);

    printf("Graph read successfully\n");

    long num_edges_for_gpu = (long)(GPU_share * (G.getNumEdges()));
    long num_edges_for_cpu = (G.getNumEdges()) - num_edges_for_gpu;  

    if(GPU_share == 1){
        num_edges_for_gpu = G.getNumEdges();
        num_edges_for_cpu = 0;
    }

    // Pinned memory allocation for h_input
    CUDA_CHECK(cudaMallocHost((void**)&h_input.V, sizeof(int)), "Failed to allocate pinned memory for h_input.V");
    CUDA_CHECK(cudaMallocHost((void**)&h_input.E, sizeof(long)), "Failed to allocate pinned memory for h_input.E");
    CUDA_CHECK(cudaMallocHost((void**)&h_input.edges_size, sizeof(long)), "Failed to allocate pinned memory for h_input.edges_size");
    CUDA_CHECK(cudaMallocHost((void**)&h_input.edge_list_size, sizeof(long)), "Failed to allocate pinned memory for h_input.edge_list_size");

    // Pinned memory allocation for h_input_gpu
    CUDA_CHECK(cudaMallocHost((void**)&h_input_gpu.V, sizeof(int)), "Failed to allocate pinned memory for h_input_gpu.V");
    CUDA_CHECK(cudaMallocHost((void**)&h_input_gpu.E, sizeof(int)), "Failed to allocate pinned memory for h_input_gpu.E");
    CUDA_CHECK(cudaMallocHost((void**)&h_input_gpu.size, sizeof(long)), "Failed to allocate pinned memory for h_input_gpu.size");
    CUDA_CHECK(cudaMallocHost((void**)&h_input_gpu.size2, sizeof(long)), "Failed to allocate pinned memory for h_input_gpu.size2");

    // Assigning edges to h_input_gpu
    h_input_gpu.edges = G.h_edgelist; // No error check needed for direct assignment

    // Device memory allocation for d_input
    CUDA_CHECK(cudaMalloc((void**)&d_input.V, sizeof(int)), "Failed to allocate device memory for d_input.V");
    CUDA_CHECK(cudaMalloc((void**)&d_input.E, sizeof(int)), "Failed to allocate device memory for d_input.E");
    CUDA_CHECK(cudaMalloc((void**)&d_input.size, sizeof(long)), "Failed to allocate device memory for d_input.size");
    CUDA_CHECK(cudaMalloc((void**)&d_input.size2, sizeof(long)), "Failed to allocate device memory for d_input.size2");
    CUDA_CHECK(cudaMalloc((void**)&d_input.edges, Batch_Size * sizeof(uint64_t)), "Failed to allocate device memory for d_input.edges");
    CUDA_CHECK(cudaMalloc((void**)&d_input.edges2, Batch_Size * sizeof(uint64_t)), "Failed to allocate device memory for d_input.edges2");
    CUDA_CHECK(cudaMalloc((void**)&d_input.label, G.getNumVertices() * sizeof(int)), "Failed to allocate device memory for d_input.label");
    CUDA_CHECK(cudaMalloc((void**)&d_input.temp_label, G.getNumVertices() * sizeof(int)), "Failed to allocate device memory for d_input.temp_label");
    CUDA_CHECK(cudaMalloc((void**)&d_input.T1edges, G.getNumVertices() * sizeof(uint64_t)), "Failed to allocate device memory for d_input.T1edges");
    CUDA_CHECK(cudaMalloc((void**)&d_input.T2edges, G.getNumVertices() * sizeof(uint64_t) ), "Failed to allocate memory for d_input.T2edges");

    #ifdef DETAIL
        printf("Allocations done successfully\n");
    #endif

    h_input.V[0]                =   G.getNumVertices();
    h_input.E[0]                =   G.getNumEdges();
    h_input.edges_size[0]       =   num_edges_for_cpu;
    h_input.edge_list_size[0]   =   num_edges_for_gpu;

    h_input_gpu.V[0] = G.getNumVertices();
    h_input_gpu.E[0] = G.getNumEdges(); 

    CUDA_CHECK(cudaMemcpy(d_input.V, h_input.V, sizeof(int), cudaMemcpyHostToDevice), "Failed to copy h_input.V to d_input.V");
    CUDA_CHECK(cudaMemcpy(d_input.E, h_input.E, sizeof(int), cudaMemcpyHostToDevice), "Failed to copy h_input.E to d_input.E");

    printf("Number of vertices: %d\n", h_input.V[0]);
    printf("Number of edges: %ld\n", h_input.E[0]);
    // printf("Number of edges for CPU: %ld\n", h_input.edges_size[0]);
    // printf("Number of edges for GPU: %ld\n", h_input.edge_list_size[0]);

    //h_input.edgelist = G.h_edgelist;
    h_input.label = parlay::sequence<int>::from_function(h_input.V[0], [&](size_t i) { return i; });
    h_input.temp_label = parlay::sequence<int>::from_function(h_input.V[0], [&](size_t i) { return i;});
    h_input.sptree = parlay::sequence<uint64_t>::from_function(h_input.V[0], [&](size_t i) { return INT_MAX;});
    h_input.edges = G.edges64;

    #ifdef DEBUG
        printf("Printing edge list given to gpu\n");
        for(long i=0;i<h_input.edge_list_size[0];i++){
            uint64_t edge = h_input_gpu.edges[i];
            int u = edge >> 32;          // Extract the upper 32 bits
            int v = edge & 0xFFFFFFFF;   // Extract the lower 32 bits
            printf("%d %d\n", u, v);
        }
        printf("Printing edge list given to cpu\n");
        for(long i = 0; i < h_input.edges_size[0]; ++i) {
            uint64_t edge = h_input.edges[i];
            int u = edge >> 32;          // Extract the upper 32 bits
            int v = edge & 0xFFFFFFFF;   // Extract the lower 32 bits
            printf("%d %d\n", u, v);
        }
    #endif

    //Step 1 :: Heterogeneous Spanning Tree Algorithm
    //Spanning tree is stored in d_input.T2edges
    time_ms = SpanningTree(&h_input_gpu, &d_input, &h_input);
    
    #ifdef DETAIL
        printf("Time taken for spanning tree : %f ms\n", time_ms);
    #endif

    #ifdef DEBUG
        int numCC_gpu =0 ;
        int numCC_cpu = 0;
        int* label = (int*)malloc(G.getNumVertices() * sizeof(int));
        cudaMemcpy(label, d_input.label, G.getNumVertices() * sizeof(int), cudaMemcpyDeviceToHost);
        //printf("Printing labels of gpu part\n");
        for(int i = 0; i < G.getNumVertices(); ++i){
            if(label[i] == i){
                numCC_gpu++;
            }
        }
        //printf("Printing labels of cpu part\n");
        for(int i = 0; i < G.getNumVertices(); ++i){
            if(h_input.label[i] == i){
                numCC_cpu++;
            }
        }
        printf("Number of connected components in GPU: %d\n", numCC_gpu);
        printf("Number of connected components in CPU: %d\n", numCC_cpu);

        //printing sptree and T1edges in gpu
        uint64_t* T1 = (uint64_t*)malloc(G.getNumVertices() * sizeof(uint64_t));
        cudaMemcpy(T1, d_input.T1edges, G.getNumVertices() * sizeof(uint64_t), cudaMemcpyDeviceToHost);
        printf("Printing T1edges\n");
        for(int i = 0; i < G.getNumVertices(); i++){
            printf("%d %d\n", T1[i] >> 32, T1[i] & 0xFFFFFFFF);
        }
        printf("Printing sptree\n");
        for(int i = 0; i < G.getNumVertices(); ++i){
            printf("%d %d\n", h_input.sptree[i] >> 32, h_input.sptree[i] & 0xFFFFFFFF);
        }
    #endif

    uint64_t* temp_array;
    // Allocate device memory for temp_array
    CUDA_CHECK(cudaMalloc((void**)&temp_array, G.getNumVertices() * sizeof(uint64_t)), 
               "Failed to allocate device memory for temp_array");

    // Copy data from host to device
    CUDA_CHECK(cudaMemcpy(temp_array, h_input.sptree.begin(), G.getNumVertices() * sizeof(uint64_t), cudaMemcpyHostToDevice), 
               "Failed to copy h_input.sptree to temp_array on device");

    float extraSptime = gpu_spanning_tree(&d_input, temp_array, G.getNumVertices());
    #ifdef DETAIL
        printf("Final Spanning Tree union time: %f\n", extraSptime);
    #endif
    time_ms += extraSptime;

    add_function_time("HAST: Hetero Spanning Tree", time_ms);

    //Step 2 :: Euler Tour Algorithm in GPU on d_input.T2edges
    
    //Allocate memory for first_occ, last_occ and parent
    // printf("After Spanning Tree\n");

    CUDA_CHECK(cudaFree(d_input.edges), "Failed to free memory for d_input.edges");
    CUDA_CHECK(cudaFree(d_input.edges2), "Failed to free memory for d_input.edges2");
    CUDA_CHECK(cudaFree(d_input.label), "Failed to free memory for d_input.label");
    CUDA_CHECK(cudaFree(d_input.temp_label), "Failed to free memory for d_input.temp_label");
    CUDA_CHECK(cudaFree(d_input.T1edges), "Failed to free memory for d_input.T1edges");

    // printf("Before Euler Tour\n");
    // print_mem_info();
    
    CUDA_CHECK(cudaMalloc((void**)&d_input.first_occ, G.getNumVertices() * sizeof(int)), 
           "Failed to allocate memory for d_input.first_occ");

    CUDA_CHECK(cudaMalloc((void**)&d_input.last_occ, G.getNumVertices() * sizeof(int)), 
               "Failed to allocate memory for d_input.last_occ");

    CUDA_CHECK(cudaMalloc((void**)&d_input.parent, G.getNumVertices() * sizeof(int)), 
               "Failed to allocate memory for d_input.parent");

    float eulertime = cuda_euler_tour(G.getNumVertices(), root, d_input.T2edges, d_input.first_occ, d_input.last_occ, d_input.parent);
    
    // printf("Time taken for tour : %f ms\n", eulertime);
    time_ms += eulertime;

    add_function_time("Eulerian Tour", eulertime);

    // printf("Mem after euler");
    // print_mem_info();

    CUDA_CHECK(cudaMalloc((void**)&d_input.edges, Batch_Size * sizeof(uint64_t)), "Failed to allocate memory for d_input.edges");
    CUDA_CHECK(cudaMalloc((void**)&d_input.edges2, Batch_Size * sizeof(uint64_t)), "Failed to allocate memory for d_input.edges2");
    CUDA_CHECK(cudaMalloc((void**)&d_input.label, G.getNumVertices() * sizeof(int)), "Failed to allocate memory for d_input.label");
    CUDA_CHECK(cudaMalloc((void**)&d_input.temp_label, G.getNumVertices() * sizeof(int)), "Failed to allocate memory for d_input.temp_label");
    CUDA_CHECK(cudaMalloc((void**)&d_input.T1edges, G.getNumVertices() * sizeof(uint64_t)), "Failed to allocate memory for d_input.T1edges");
    CUDA_CHECK(cudaMalloc((void**)&d_input.w1, G.getNumVertices() * sizeof(int)), "Failed to allocate memory for d_input.w1");
    CUDA_CHECK(cudaMalloc((void**)&d_input.w2, G.getNumVertices() * sizeof(int)), "Failed to allocate memory for d_input.w2");
    CUDA_CHECK(cudaMalloc((void**)&d_input.SpanningForest, G.getNumVertices() * sizeof(uint64_t)), "Failed to allocate memory for d_input.SpanningForest");
    CUDA_CHECK(cudaMalloc((void **)&(d_input.low), G.getNumVertices() * sizeof(int)), "Failed to allocate memory for d_input.low");
    CUDA_CHECK(cudaMalloc((void **)&(d_input.high), G.getNumVertices() * sizeof(int)), "Failed to allocate memory for d_input.high");
    CUDA_CHECK(cudaMalloc((void **)&(d_input.fg1), G.getNumVertices() *sizeof(bool)), "Failed to allocate memory for d_input.fg1");

    h_input.first_occ = parlay::sequence<int>::uninitialized(G.getNumVertices());
    h_input.last_occ = parlay::sequence<int>::uninitialized(G.getNumVertices());
    h_input.parent = parlay::sequence<int>::uninitialized(G.getNumVertices());
    
    //copy back the first_occ, last_occ and parent to h_input
    
    CUDA_CHECK(cudaMemcpy(h_input.first_occ.begin(), d_input.first_occ, G.getNumVertices() * sizeof(int), cudaMemcpyDeviceToHost), 
           "Failed to copy d_input.first_occ to h_input.first_occ");

    CUDA_CHECK(cudaMemcpy(h_input.last_occ.begin(), d_input.last_occ, G.getNumVertices() * sizeof(int), cudaMemcpyDeviceToHost), 
               "Failed to copy d_input.last_occ to h_input.last_occ");

    CUDA_CHECK(cudaMemcpy(h_input.parent.begin(), d_input.parent, G.getNumVertices() * sizeof(int), cudaMemcpyDeviceToHost), 
               "Failed to copy d_input.parent to h_input.parent");

    #ifdef DEBUG
        //validate first and last occurences and parent
        for(int i = 0; i < G.getNumVertices(); ++i){
            printf("Vertex %d: First Occurence: %d, Last Occurence: %d, Parent: %d\n", i, h_input.first_occ[i], h_input.last_occ[i], h_input.parent[i]);
        }
    #endif

    // printf("Mem after step 3 Allcocations\n");
    // print_mem_info();

    //w1 and w2 are filled with first and last occurences of vertices in the euler tour
    h_input.w1 = parlay::sequence<int>::from_function(G.getNumVertices(), [&](size_t i) { return h_input.first_occ[i]; });
    h_input.w2 = parlay::sequence<int>::from_function(G.getNumVertices(), [&](size_t i) { return h_input.last_occ[i]; });

    #ifdef DEBUG
        for(int i = 0; i < G.getNumVertices(); ++i){
            printf("Vertex %d: w1: %d, w2: %d\n", i, h_input.w1[i], h_input.w2[i]);
        }
    #endif
   
    //Step 3:: Spanning Forest on cross edges
    float tandsptime = ComputeTagsAndSpanningForest(&h_input_gpu, &d_input, &h_input);
    // printf("Time taken for tags and spanning forest : %f ms\n", tandsptime);
    time_ms += tandsptime;

    add_function_time("Tag Computation and SpanningForest", tandsptime);
    
    
    //print w1 and w2 and sptree
    #ifdef DEBUG
        for(int i = 0; i < G.getNumVertices(); ++i){
            printf("Vertex %d: w1: %d, w2: %d\n", i, h_input.w1[i], h_input.w2[i]);
        }
        printf("Printing sptree\n");
        for(int i = 0; i < G.getNumVertices(); ++i){
            printf("%d %d\n", h_input.sptree[i] >> 32, h_input.sptree[i] & 0xFFFFFFFF);
        }
    #endif

    // alloc w1_copy and w2_copy in gpu
    // Allocate device memory for w1_copy and w2_copy
    CUDA_CHECK(cudaMalloc((void**)&d_input.w1_copy, G.getNumVertices() * sizeof(int)), 
               "Failed to allocate device memory for d_input.w1_copy");
    CUDA_CHECK(cudaMalloc((void**)&d_input.w2_copy, G.getNumVertices() * sizeof(int)), 
               "Failed to allocate device memory for d_input.w2_copy");

    // Copy data from host to device for w1_copy and w2_copy
    CUDA_CHECK(cudaMemcpy(d_input.w1_copy, h_input.w1.begin(), G.getNumVertices() * sizeof(int), cudaMemcpyHostToDevice), 
               "Failed to copy h_input.w1 to d_input.w1_copy");
    CUDA_CHECK(cudaMemcpy(d_input.w2_copy, h_input.w2.begin(), G.getNumVertices() * sizeof(int), cudaMemcpyHostToDevice), 
               "Failed to copy h_input.w2 to d_input.w2_copy");

    merge_w1_w2<<<(G.getNumVertices() + tb_size - 1)/ tb_size, tb_size>>>(G.getNumVertices(), d_input.w1_copy, d_input.w2_copy, d_input.w1, d_input.w2);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize after merge_w1_w2");

    // Free device memory for w1_copy and w2_copy
    CUDA_CHECK(cudaFree(d_input.w1_copy), "Failed to free memory for d_input.w1_copy");
    CUDA_CHECK(cudaFree(d_input.w2_copy), "Failed to free memory for d_input.w2_copy");

    // Copy data from host to device for sptree
    CUDA_CHECK(cudaMemcpy(temp_array, h_input.sptree.begin(), G.getNumVertices() * sizeof(uint64_t), cudaMemcpyHostToDevice), 
               "Failed to copy h_input.sptree to temp_array on the device");

    // Measure GPU spanning tree time
    float gpusptreetime = gpu_spanning_tree_2(&d_input, temp_array, G.getNumVertices());
    printf("Time taken for gpu sptree : %f ms\n", gpusptreetime);
    time_ms += gpusptreetime;

    add_function_time("GPU Spanning Tree on cross edges ", gpusptreetime);

    // Free device memory for temp_array and T1edges
    CUDA_CHECK(cudaFree(temp_array), "Failed to free memory for temp_array");
    CUDA_CHECK(cudaFree(d_input.T1edges), "Failed to free memory for d_input.T1edges");


    //validate d_input.SpanningForest
    #ifdef DEBUG
        uint64_t* SpanningForest = (uint64_t*)malloc(G.getNumVertices() * sizeof(uint64_t));
        cudaMemcpy(SpanningForest, d_input.SpanningForest, G.getNumVertices() * sizeof(uint64_t), cudaMemcpyDeviceToHost);
        printf("Printing Spanning Forest\n");
        for(int i = 0; i < G.getNumVertices(); ++i)
            printf("%d %d\n", SpanningForest[i] >> 32, SpanningForest[i] & 0xFFFFFFFF);
    #endif

    int n_asize = (2*(h_input.V[0]) + LOCAL_BLOCK_SIZE - 1) / LOCAL_BLOCK_SIZE;
    int* d_na1;
    CUDA_CHECK(cudaMalloc((void**)&d_na1, n_asize * sizeof(int)), "Failed to allocate memory for d_na1");
    int* d_na2;
    CUDA_CHECK(cudaMalloc((void**)&d_na2, n_asize * sizeof(int)), "Failed to allocate memory for d_na2");
    int* d_a1;
    CUDA_CHECK(cudaMalloc((void**)&d_a1, 2*(h_input.V[0]) * sizeof(int)), "Failed to allocate memory for d_a1");
    int* d_a2;
    CUDA_CHECK(cudaMalloc((void**)&d_a2, 2*(h_input.V[0]) * sizeof(int)), "Failed to allocate memory for d_a2");
    int* d_left;
    CUDA_CHECK(cudaMalloc((void**)&d_left, (h_input.V[0]) * sizeof(int)), "Failed to allocate memory for d_left");
    int* d_right;
    CUDA_CHECK(cudaMalloc((void**)&d_right, (h_input.V[0]) * sizeof(int)), "Failed to allocate memory for d_right");

    printf("Mem after step 4 Allcocations\n");
    print_mem_info();

    auto start = chrono::high_resolution_clock::now();

    fill_w1_w2<<<(h_input.V[0] + 1023) / 1024, 1024>>>(d_input.SpanningForest, h_input.V[0], d_input.w1, d_input.w2, d_input.parent , d_input.first_occ , d_input.last_occ);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize after fill_w1_w2");

    compute_a1<<<(h_input.V[0] + 1023) / 1024, 1024>>>(d_input.first_occ, d_input.last_occ, h_input.V[0] , d_input.w1 , d_a1);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize after compute_a1");

    compute_a1<<<(h_input.V[0] + 1023) / 1024, 1024>>>(d_input.first_occ, d_input.last_occ, h_input.V[0] , d_input.w2 , d_a2);
    CUDA_CHECK(cudaDeviceSynchronize() , "Failed to synchronize after compute_a1");

    fill_left_right<<<(h_input.V[0] + 1023) / 1024, 1024>>>(d_input.first_occ , d_input.last_occ, h_input.V[0], d_left, d_right);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize after fill_left_right");

    //Step 4: Preprocess for Sparse Table Min and Max and solve
    main_min(2*(h_input.V[0]), (h_input.V[0]), d_a1, d_left, d_right, d_input.low , n_asize , d_na1);
    main_max(2*(h_input.V[0]), (h_input.V[0]), d_a2, d_left, d_right, d_input.high , n_asize , d_na2);

    auto end = chrono::high_resolution_clock::now();
    float duration = (float)chrono::duration_cast<chrono::milliseconds>(end - start).count();
    time_ms += duration;

    add_function_time("Sparse Table lookup: ", duration);

    CUDA_CHECK(cudaFree(d_left), "Failed to free memory for d_left");
    CUDA_CHECK(cudaFree(d_right), "Failed to free memory for d_right");
    CUDA_CHECK(cudaFree(d_a1), "Failed to free memory for d_a1");
    CUDA_CHECK(cudaFree(d_a2), "Failed to free memory for d_a2");
    CUDA_CHECK(cudaFree(d_na1), "Failed to free memory for d_na1");
    CUDA_CHECK(cudaFree(d_na2), "Failed to free memory for d_na2");
    CUDA_CHECK(cudaFree(d_input.w1), "Failed to free memory for d_input.w1");
    CUDA_CHECK(cudaFree(d_input.w2), "Failed to free memory for d_input.w2");


    //Step 5: Marking fence edges.
    
    start = chrono::high_resolution_clock::now();
	bool verbose = false;	
    if(verbose) {
	    std::cout << "Print is on in main line no.479:\n";
	    std::cout << "Low array\n";
	    print_device_array(d_input.low, h_input.V[0]);
	    std::cout << "High array:\n";
		print_device_array(d_input.high, h_input.V[0]);
    }
    mark_fence<<<(h_input.V[0] + 1023) / 1024, 1024>>>(d_input.T2edges, h_input.V[0], d_input.low, d_input.high, d_input.first_occ, d_input.last_occ, d_input.parent, d_input.fg1);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize after mark_fence");

    end = chrono::high_resolution_clock::now();
    duration = chrono::duration_cast<chrono::milliseconds>(end - start).count();
    add_function_time("Marking Fence Edges ", duration);
    time_ms += duration;

    //Step 6: Connected Components Algorithm on fg1==true and cross edges.
    auto cctime = CC(&d_input,h_input.V[0]);

    add_function_time("Last CC", cctime);
    time_ms += cctime;
    print_total_function_time("Hetero bcc", detail);

    //Step 7: Give label to root
    give_label_to_root<<<(h_input.V[0] + 1023) / 1024, 1024>>>(d_input.label, d_input.parent, h_input.V[0], 0);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize after give_label_to_root");

    //Step 8: Compute number of connected components
    CUDA_CHECK(cudaMemcpy(h_input.label.begin(), d_input.label, h_input.V[0] * sizeof(int), cudaMemcpyDeviceToHost), "Failed to copy label from device to host");
    
    int num_bcc = 0;
    for(int i = 0; i < h_input.V[0]; i++) {
        if(h_input.label[i] == i) {
            num_bcc++;
        }
    }
    printf("Number of bi-connected components in graph: %d\n", num_bcc);
    std::cout << "GPU Share: " <<  GPU_share << ", batch Size: " << Batch_Size << std::endl;
    printf("Total time taken: %f ms\n", time_ms);

    return 0;
}
