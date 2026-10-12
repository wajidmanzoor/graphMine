#include <iostream>
#include <cuda_runtime.h>
#include <fstream>
#include <stdlib.h>
#include <stdio.h>


using namespace std;


#include "include/GPUSpanningtree.cuh"
#include "include/hbcg_utils.cuh"

//#define DEBUG
#define tb_size 1024

#define CUDA_CHECK(call) do { cudaError_t err = call;if (err != cudaSuccess) {fprintf(stderr, "CUDA error at %s:%d code=%d(%s)\n", __FILE__, __LINE__, err, cudaGetErrorString(err)); exit(EXIT_FAILURE);}} while (0)

#define PARENT0(i) d_input.temp_label[i]
#define PARENTW(i) d_input.temp_label[i]



__device__ inline int compress(int i, struct graph_data d_input)
{
	int j = i;
	if (PARENT0(j) == j) {
		return j;
	}
	do {
		j = PARENT0(j);
	} while (PARENT0(j) != j);

	int tmp;
	while((tmp=PARENT0(i))>j) {
		PARENTW(i) = j;
		i = tmp;
	}
	return j;
}


__device__ inline bool union_(long i, long idx, int src, int dst, struct graph_data d_input)
{
    while(1) {
        int u = compress(src, d_input);
        int v = compress(dst, d_input);
        if(u == v) break;
        if(v > u) { int temp; temp = u; u = v; v = temp; }
        if(u == atomicCAS(&PARENTW(u),u,v)) {
           d_input.T2edges[u] = (uint64_t)src << 32 | dst;
	       return true;
        }
    }
    return false;
}

__device__ inline bool union_2(long i, long idx, int src, int dst, struct graph_data d_input)
{
    while(1) {
        int u = compress(src, d_input);
        int v = compress(dst, d_input);
        if(u == v) break;
        if(v > u) { int temp; temp = u; u = v; v = temp; }
        if(u == atomicCAS(&PARENTW(u),u,v)) {
           d_input.SpanningForest[u] = (uint64_t)src << 32 | dst;
	       return true;
        }
    }
    return false;
}


__global__ void union_find_gpu(long total_elt, struct graph_data d_input , uint64_t* extraedges){
    long idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < d_input.V[0]){
        uint64_t edge = d_input.T1edges[idx];
        if(edge != (uint64_t)INT_MAX){
        int u = edge >> 32;
        int v = edge & 0xFFFFFFFF;
        if(u<v){
            bool r = union_(idx, idx, u, v, d_input);
        }
        }
    }
    else if(idx < total_elt){
        uint64_t edge = extraedges[idx - d_input.V[0]];
        if(edge != (uint64_t)INT_MAX){
        int u = edge >> 32;
        int v = edge & 0xFFFFFFFF;
        if(u<v){
            bool r = union_(idx, idx, u, v, d_input);
        }
        }
    }
}

__global__ void union_find_gpu_2(long total_elt, struct graph_data d_input , uint64_t* extraedges){
    long idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < d_input.V[0]){
        uint64_t edge = d_input.T1edges[idx];
        if(edge != (uint64_t)INT_MAX){
        int u = edge >> 32;
        int v = edge & 0xFFFFFFFF;
        if(u<v){
            bool r = union_2(idx, idx, u, v, d_input);
        }
        }
    }
    else if(idx < total_elt){
        uint64_t edge = extraedges[idx - d_input.V[0]];
        if(edge != (uint64_t)INT_MAX){
        int u = edge >> 32;
        int v = edge & 0xFFFFFFFF;
        if(u<v){
            bool r = union_2(idx, idx, u, v, d_input);
        }
        }
    }
}

__global__ void cc(struct graph_data d_input)
{       
        int idx = blockIdx.x * blockDim.x + threadIdx.x;
        if(idx < d_input.V[0]) {
                d_input.label[idx] = compress(idx, d_input);
        }
}



__global__
void init_parent_label_T2edges(struct graph_data d_input, int V){
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < V){
        d_input.temp_label[idx] = idx;
        d_input.label[idx] = idx;
        d_input.T2edges[idx] = INT_MAX;
    }
}

__global__
void init_T1edges(struct graph_data d_input, int V){
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < V){
        d_input.temp_label[idx] = idx;
        d_input.label[idx] = idx;
        d_input.SpanningForest[idx] = INT_MAX;
    }
}

void union_find(struct graph_data* d_input , int V , uint64_t* extraedges){
    long total_elt = 2*V;
    long grid_size_union = (total_elt + tb_size - 1) / tb_size;
    int grid_size_final = (V + tb_size - 1) / tb_size;
    union_find_gpu<<<grid_size_union, tb_size>>>(total_elt , *d_input , extraedges);
    cc<<<grid_size_final, tb_size>>>(*d_input);
}

void union_find_2(struct graph_data* d_input , int V , uint64_t* extraedges){
    long total_elt = 2*V;
    long grid_size_union = (total_elt + tb_size - 1) / tb_size;
    int grid_size_final = (V + tb_size - 1) / tb_size;
    union_find_gpu_2<<<grid_size_union, tb_size>>>(total_elt , *d_input , extraedges);
    cc<<<grid_size_final, tb_size>>>(*d_input);
}


float gpu_spanning_tree(struct graph_data* d_input, uint64_t* extraedges , int vert){

    int grid_size_final = (vert + tb_size - 1) / tb_size;

    init_parent_label_T2edges<<<grid_size_final, tb_size>>>(*d_input, vert);
    CUDA_CHECK(cudaDeviceSynchronize());

    float time_ms=0.0;

    cudaEvent_t start, stop;
    cudaEventCreate(&start);
    cudaEventCreate(&stop);
 

    //start the timer...............................................
    cudaEventRecord(start);


    
    union_find(d_input , vert ,extraedges);



    cudaEventRecord(stop);
    cudaEventSynchronize(stop);
    cudaEventElapsedTime(&time_ms, start, stop);
    

    return time_ms;
}

float gpu_spanning_tree_2(struct graph_data* d_input, uint64_t* extraedges , int vert){

    int grid_size_final = (vert + tb_size - 1) / tb_size;

    init_T1edges<<<grid_size_final, tb_size>>>(*d_input, vert);
    CUDA_CHECK(cudaDeviceSynchronize());

    float time_ms=0.0;

    cudaEvent_t start, stop;
    cudaEventCreate(&start);
    cudaEventCreate(&stop);
 

    //start the timer...............................................
    cudaEventRecord(start);


    
    union_find_2(d_input , vert ,extraedges);



    cudaEventRecord(stop);
    cudaEventSynchronize(stop);
    cudaEventElapsedTime(&time_ms, start, stop);
    

    return time_ms;
}
