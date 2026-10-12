#include <iostream>
#include <cuda_runtime.h>
#include <fstream>
#include <stdlib.h>
#include <stdio.h>

#include "include/cuda_utility.cuh"
#include "include/CC.cuh"
#include "include/hbcg_utils.cuh"

using namespace std;

//#define DEBUG
#define tb_size 1024

__device__ inline 
int find_compress_cc(int i, struct graph_data d_input) {
	int j = i;
	if (d_input.temp_label[j] == j) {
		return j;
	}
	do {
		j = d_input.temp_label[j];
	} while (d_input.temp_label[j] != j);

	int tmp;
	while((tmp=d_input.temp_label[i])>j) {
		d_input.temp_label[i] = j;
		i = tmp;
	}
	return j;
}


__device__ inline 
bool union_async_cc(long i, long idx, int src, int dst, struct graph_data d_input) {
    while(1) {
        int u = find_compress_cc(src, d_input);
        int v = find_compress_cc(dst, d_input);
        if(u == v) break;
        if(v > u) { int temp; temp = u; u = v; v = temp; }
        if(u == atomicCAS(&d_input.temp_label[u],u,v)) {
	       return true;
        } 
    }
    return false;
}

__global__ 
void union_find_gpu_COO_cc(long total_elt, struct graph_data d_input){
    long idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < total_elt){
        if(d_input.fg1[idx] == true && d_input.T2edges[idx]!=INT_MAX){
            int u = d_input.T2edges[idx] >> 32;
            int v = d_input.T2edges[idx] & 0xFFFFFFFF;
            if( u < v ){
                bool r = union_async_cc(idx, idx, u, v, d_input);
            }
        }
        if(d_input.SpanningForest[idx] != INT_MAX){
            int u = d_input.SpanningForest[idx] >> 32;
            int v = d_input.SpanningForest[idx] & 0xFFFFFFFF;
            if( u < v ){
                bool r = union_async_cc(idx, idx, u, v, d_input);
            }
        }
    }
}


__global__ 
void cc_gpu_cc(struct graph_data d_input) {       
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < d_input.V[0]) {
        //printf("printing vertices : %d\n",d_input.V[0]);
        d_input.label[idx] = find_compress_cc(idx, d_input);
        //printf("label[%d] : %d\n",idx,d_input.label[idx]);
    }
}



__global__
void init_parent_label_cc(struct graph_data d_input, int V){
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < V){
        d_input.temp_label[idx] = idx;
        d_input.label[idx] = idx;
    }
}

void run_union_find_cc(struct graph_data* d_input , int V){
    int grid_size_final = (V + tb_size - 1) / tb_size;
    long total_elt = V;

    union_find_gpu_COO_cc<<<grid_size_final, tb_size>>>(total_elt , *d_input);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize union_find_gpu_COO_cc kernel");
    cc_gpu_cc<<<grid_size_final, tb_size>>>(*d_input);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize cc_gpu_cc kernel");
}


float CC(struct graph_data* d_input, int v){

    int grid_size_final = (v + tb_size - 1) / tb_size;

    init_parent_label_cc<<<grid_size_final, tb_size>>>(*d_input, v);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize init_parent_label_cc kernel");

    auto start = std::chrono::high_resolution_clock::now();
    run_union_find_cc(d_input, v);

    auto stop = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration<double, std::milli>(stop - start).count();

    return duration;
}
