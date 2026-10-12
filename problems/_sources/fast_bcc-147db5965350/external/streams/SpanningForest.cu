#include <iostream>
#include <cuda_runtime.h>
#include <fstream>
#include <stdlib.h>
#include <stdio.h>

#include "include/cuda_utility.cuh"
#include "include/hbcg_utils.cuh"
#include "include/SpanningForest.cuh"
#include "include/host_spanning_tree.cuh"

using namespace std;

extern int Batch_Size;
extern float GPU_share;

//#define DEBUG
#define tb_size 1024

__device__ inline 
int find_compress_SF(int i, struct graph_data d_input)
{
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
bool union_async_SF(long i, long idx, int src, int dst, struct graph_data d_input)
{
    while(1) {
        int u = find_compress_SF(src, d_input);
        int v = find_compress_SF(dst, d_input);
        if(u == v) break;
        if(v > u) { int temp; temp = u; u = v; v = temp; }
        if(u == atomicCAS(&d_input.temp_label[u],u,v)) {
           d_input.T1edges[u] = d_input.edges[idx];
	       return true;
        } 
    }
    return false;
}

__device__ inline 
bool union_async_SF1(long i, long idx, int src, int dst, struct graph_data d_input)
{
    while(1) {
        int u = find_compress_SF(src, d_input);
        int v = find_compress_SF(dst, d_input);
        if(u == v) break;
        if(v > u) { int temp; temp = u; u = v; v = temp; }
        if(u == atomicCAS(&d_input.temp_label[u],u,v)) {
           d_input.T1edges[u] = d_input.edges2[idx];
	       return true;
        } 
    }
    return false;
}


__global__ 
void union_find_gpu_COO_SF(long total_elt, struct graph_data d_input){
    long idx = blockIdx.x * blockDim.x + threadIdx.x;
    
    if(idx < total_elt){
        int u = d_input.edges[idx] >> 32;
        int v = d_input.edges[idx] & 0xFFFFFFFF;
        int f_u = d_input.first_occ[u];
        int l_u = d_input.last_occ[u];
        int f_v = d_input.first_occ[v];
        int l_v = d_input.last_occ[v];
        
        if(u<v && d_input.parent[u] != v && d_input.parent[v] != u){
            //All non Tree edges
            if(!(f_u <= f_v && l_u>=f_v  || f_v <= f_u && l_v>=f_u)){
                //Edge is not back edge 
                bool r = union_async_SF(idx, idx, u, v, d_input);
            }
            else{
                //Edge is back edge
                if(f_u < f_v) {
                    atomicMin(&d_input.w1[v], f_u);
                    atomicMax(&d_input.w2[u], f_v);
                }
                else {
                    atomicMin(&d_input.w1[u], f_v);
                    atomicMax(&d_input.w2[v], f_u);
                }
            }
        }
    }
}

__global__ 
void union_find_gpu_COO_SF1(long total_elt, struct graph_data d_input) {
    long idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < total_elt){
        int u = d_input.edges2[idx] >> 32;
        int v = d_input.edges2[idx] & 0xFFFFFFFF;
        int f_u = d_input.first_occ[u];
        int l_u = d_input.last_occ[u];
        int f_v = d_input.first_occ[v];
        int l_v = d_input.last_occ[v];
        if(u<v && d_input.parent[u] != v && d_input.parent[v] != u){
            //All non Tree edges
            if(!(f_u <= f_v && l_u>=f_v  || f_v <= f_u && l_v>=f_u)){
                //Edge is cross edge
                bool r = union_async_SF1(idx, idx, u, v, d_input);
            }
            else {
                if(f_u < f_v) {
                    atomicMin(&d_input.w1[v], f_u);
                    atomicMax(&d_input.w2[u], f_v);
                }
                else {
                    atomicMin(&d_input.w1[u], f_v);
                    atomicMax(&d_input.w2[v], f_u);
                }
            }
        }
    }
}

__global__ 
void cc_gpu_SF(struct graph_data d_input) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < d_input.V[0]) {
        d_input.label[idx] = find_compress_SF(idx, d_input);
    }
}



__global__
void init_parent_label(struct graph_data d_input, int V){
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < V){
        d_input.temp_label[idx] = idx;
        d_input.T1edges[idx] = INT_MAX;
    }
}

__global__
void init_w1_w2(struct graph_data d_input, int V){
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < V){
        d_input.w1[idx] = d_input.first_occ[idx];
        d_input.w2[idx] = d_input.last_occ[idx];
    }
}

void run_union_find_SF(struct graph_data* d_input , int V , long SIZ , int f, cudaStream_t stream){
    long grid_size_union = (SIZ + tb_size - 1) / tb_size;

    long total_elt = SIZ;

    if(f){
    union_find_gpu_COO_SF1<<<grid_size_union, tb_size, 0, stream>>>(total_elt , *d_input);
    }
    else{
    union_find_gpu_COO_SF<<<grid_size_union, tb_size, 0, stream>>>(total_elt , *d_input);
    }
}


float ComputeTagsAndSpanningForest( struct graph_data* h_input , struct graph_data* d_input , struct graph_data_host* h_input_host){

    // printf("vertices are %d tb_size %d\n", h_input->V[0], tb_size);

    int grid_size_final = (h_input->V[0] + tb_size - 1) / tb_size;

    init_parent_label<<<grid_size_final, tb_size>>>(*d_input, h_input->V[0]);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize init_parent_label kernel");

    init_w1_w2<<<grid_size_final, tb_size>>>(*d_input, h_input->V[0]);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize init_w1_w2 kernel");

    //create 2 streams for overlapping..............................
    cudaStream_t stream1, stream2;
    CUDA_CHECK(cudaStreamCreate(&stream1), "Failed to create stream1");
    CUDA_CHECK(cudaStreamCreate(&stream2), "Failed to create stream2");

    float time_ms = 0.0;
    cudaEvent_t start, stop;
    cudaEventCreate(&start);
    cudaEventCreate(&stop);

    long batch_size = Batch_Size;

    cout<<"GPU share : " << GPU_share << endl;
    cout<<"Batch Size : " << batch_size << endl;

    long edges_for_gpu = (long)(GPU_share * (h_input->E[0]));
    if((int)GPU_share == 1){
        edges_for_gpu = h_input->E[0];
    }

    cout << "Total Batches for GPU : " << (edges_for_gpu + batch_size - 1) / batch_size << endl;
    
    //start the timer...............................................
    cudaEventRecord(start);

    long i = 0;

    long bat = (i + batch_size - 1) / batch_size;
    long total_elt = min(batch_size, edges_for_gpu - i);

    h_input->size[0] = total_elt;

    CUDA_CHECK(cudaMemcpyAsync(d_input->size, h_input->size, sizeof(long), cudaMemcpyHostToDevice , stream1), "Failed to copy d->input size");
    CUDA_CHECK(cudaMemcpyAsync(d_input->edges, h_input->edges + i, min(batch_size, edges_for_gpu - i) * sizeof(uint64_t), cudaMemcpyHostToDevice , stream1), "Failed to copy edges");
    
    run_union_find_SF(d_input , h_input->V[0] , total_elt , bat%2 , stream1);

    i += batch_size;

    for(; i < edges_for_gpu ; i += batch_size){
        
        long bat = (i + batch_size - 1) / batch_size;
        long total_elt = min(batch_size, edges_for_gpu - i);
        
        if(bat%2) {
              
            h_input->size2[0] = total_elt;

            CUDA_CHECK(cudaMemcpyAsync(d_input->edges2, h_input->edges + i, total_elt * sizeof(uint64_t), cudaMemcpyHostToDevice, stream2), "Failed to copy edges");
            CUDA_CHECK(cudaMemcpyAsync(d_input->size2, h_input->size2, sizeof(long), cudaMemcpyHostToDevice, stream2), "Failed to copy size2");
        }
        else {
            
            h_input->size[0] = total_elt;

            CUDA_CHECK(cudaMemcpyAsync(d_input->size, h_input->size, sizeof(long), cudaMemcpyHostToDevice, stream1), "Failed to copy size");
            CUDA_CHECK(cudaMemcpyAsync(d_input->edges , h_input->edges + i, total_elt * sizeof(uint64_t), cudaMemcpyHostToDevice, stream1), "Failed to copy edges");
        }

        if(bat%2) {
            run_union_find_SF(d_input , h_input->V[0] , total_elt , bat%2 , stream2);
        }
        else {
            run_union_find_SF(d_input , h_input->V[0] , total_elt , bat%2 , stream1);
        }
        
    }

    ComputeTagsAndSpanningForest_host(h_input_host);

    cudaEventRecord(stop);
    cudaEventSynchronize(stop);
    cudaEventElapsedTime(&time_ms, start, stop);


    //destroy the streams...........................................
    CUDA_CHECK(cudaStreamDestroy(stream1), "Failed to destroy stream1");
    CUDA_CHECK(cudaStreamDestroy(stream2), "Failed to destroy stream2");
    

    return time_ms;
}
