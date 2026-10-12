#include <iostream>
#include <cuda_runtime.h>
#include <fstream>
#include <stdlib.h>
#include <stdio.h>

extern int Batch_Size;
extern float GPU_share;

using namespace std;


#include "include/ExternalSpanningTree.cuh"
#include "include/hbcg_utils.cuh"
#include "include/host_spanning_tree.cuh"

//#define DEBUG
#define tb_size 1024

#define CUDA_CHECK(call) do { cudaError_t err = call;if (err != cudaSuccess) {fprintf(stderr, "CUDA error at %s:%d code=%d(%s)\n", __FILE__, __LINE__, err, cudaGetErrorString(err)); exit(EXIT_FAILURE);}} while (0)

#define PARENT0(i) d_input.temp_label[i]
#define PARENTW(i) d_input.temp_label[i]

__device__ inline int custom_compress(int i, struct graph_data d_input)
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


__device__ inline bool union_async(long i, long idx, int src, int dst, struct graph_data d_input)
{
    while(1) {
        int u = custom_compress(src, d_input);
        int v = custom_compress(dst, d_input);
        if(u == v) break;
        if(v > u) { int temp; temp = u; u = v; v = temp; }
        if(u == atomicCAS(&PARENTW(u),u,v)) {
           d_input.T1edges[u] = d_input.edges[idx];
	       return true;
        }
    }
    return false;
}

__device__ inline bool union_async1(long i, long idx, int src, int dst, struct graph_data d_input)
{
    while(1) {
        int u = custom_compress(src, d_input);
        int v = custom_compress(dst, d_input);
        if(u == v) break;
        if(v > u) { int temp; temp = u; u = v; v = temp; }
        if(u == atomicCAS(&PARENTW(u),u,v)) {
           d_input.T1edges[u] = d_input.edges2[idx];
	       return true;
        } 
    }
    return false;
}


__global__ void union_find_gpu_COO(long total_elt, struct graph_data d_input){
    long idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < total_elt){
        int u = d_input.edges[idx] >> 32;
        int v = d_input.edges[idx] & 0xFFFFFFFF;
        if( u < v ){
            //printf("u = %d v = %d is gpu edge in even\n", u, v);
            bool r = union_async(idx, idx, u, v, d_input);
        }
    }
}

__global__ void union_find_gpu_COO1(long total_elt, struct graph_data d_input){
    long idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < total_elt){
        int u = d_input.edges2[idx] >> 32;
        int v = d_input.edges2[idx] & 0xFFFFFFFF;
        if( u < v ){
            bool r = union_async1(idx, idx, u, v, d_input);
        }
    }
}

__global__ void cc_gpu(struct graph_data d_input)
{       
        int idx = blockIdx.x * blockDim.x + threadIdx.x;
        if(idx < d_input.V[0]) {
                d_input.label[idx] = custom_compress(idx, d_input);
        }
}



__global__
void init_parent_label_T1edges(struct graph_data d_input, int V){
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < V){
        d_input.temp_label[idx] = idx;
        d_input.label[idx] = idx;
        d_input.T1edges[idx] = INT_MAX;
    }
}

void run_union_find(struct graph_data* d_input , int V , long SIZ , int f){
    long grid_size_union = (SIZ + tb_size - 1) / tb_size;
    int grid_size_final = (V + tb_size - 1) / tb_size;

    long total_elt = SIZ;
    union_find_gpu_COO<<<grid_size_union, tb_size>>>(total_elt , *d_input);
}


float SpanningTree( struct graph_data* h_input , struct graph_data* d_input, struct graph_data_host* h_input_host){

    // printf("vertices are %d tb_size %d\n", h_input->V[0], tb_size);

    int grid_size_final = (h_input->V[0] + tb_size - 1) / tb_size;

    init_parent_label_T1edges<<<grid_size_final, tb_size>>>(*d_input, h_input->V[0]);
    CUDA_CHECK(cudaDeviceSynchronize());

    float time_ms=0.0;

    cudaEvent_t start, stop;

    cudaEventCreate(&start);
    cudaEventCreate(&stop);

    long batch_size = Batch_Size;

    long edges_for_gpu = (long)(GPU_share * h_input->E[0]);

    if((int)GPU_share == 1){
        edges_for_gpu = h_input->E[0];
    }

    cout << "Edges for GPU : " << edges_for_gpu << endl;
    cout << "Edges for CPU : " << h_input->E[0] - edges_for_gpu << endl;
    
    cout<<"Total Batches for gpu : " << (edges_for_gpu + batch_size - 1) / batch_size << endl;

    //start the timer...............................................
    cudaEventRecord(start);


    long i=0;

   
    long bat = (i + batch_size - 1) / batch_size;
    long total_elt = min(batch_size, edges_for_gpu - i);

    h_input->size[0] = total_elt;

    CUDA_CHECK(cudaMemcpy(d_input->size, h_input->size, sizeof(long), cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_input->edges, h_input->edges + i, min(batch_size, edges_for_gpu - i) * sizeof(uint64_t), cudaMemcpyHostToDevice));

    run_union_find(d_input , h_input->V[0] , total_elt , bat%2 );

    i+=batch_size;

    for(; i < edges_for_gpu; i += batch_size){
        
        long bat = (i + batch_size - 1) / batch_size;
        long total_elt = min(batch_size, edges_for_gpu - i);
        
        h_input->size[0] = total_elt;
        CUDA_CHECK(cudaMemcpy(d_input->size, h_input->size, sizeof(long), cudaMemcpyHostToDevice));
        CUDA_CHECK(cudaMemcpy(d_input->edges , h_input->edges + i, total_elt * sizeof(uint64_t), cudaMemcpyHostToDevice));

        run_union_find(d_input , h_input->V[0] , total_elt , bat%2);
        
        
    }

    host_spanning_tree(h_input_host);

    cudaEventRecord(stop);
    cudaEventSynchronize(stop);
    cudaEventElapsedTime(&time_ms, start, stop);
    
    return time_ms;
}
