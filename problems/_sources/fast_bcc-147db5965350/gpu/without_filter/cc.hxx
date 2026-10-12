#ifndef CC_HXX
#define CC_HXX

#include <iostream>
#include <cuda_runtime.h>
#include "common.hxx"

#define tb_size 1024
// #define DEBUG

__device__ inline 
int find_compress(int i, int* temp_label) {
    int j = i;
    if (temp_label[j] == j) {
        return j;
    }
    do {
        j = temp_label[j];
    } while (temp_label[j] != j);

    int tmp;
    while((tmp = temp_label[i])>j) {
        temp_label[i] = j;
        i = tmp;
    }
    return j;
}


__device__ inline 
bool union_async(long idx, int src, int dst, int* temp_label) {
    while(1) {
        int u = find_compress(src, temp_label);
        int v = find_compress(dst, temp_label);

        if(u == v) break;
        if(v > u) { int temp; temp = u; u = v; v = temp; }
        if(u == atomicCAS(&temp_label[u], u, v)) {
           return true;
        } 
    }
    return false;
}

__global__ 
void union_find_gpu_COO(long numEdges, int* temp_label, int* fg, uint64_t* edges){
    long idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < numEdges) {
        if(fg[idx] == true && edges[idx]!= INT_MAX) {
            int u = edges[idx] >> 32;
            int v = edges[idx] & 0xFFFFFFFF;
            if( u < v ){
                bool r = union_async(idx, u, v, temp_label);
            }
        }
    }
}


__global__ 
void cc_gpu(int* label, int* temp_label, int V) {       
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < V) {
        label[idx] = find_compress(idx, temp_label);
    }
}

__global__
void init_parent_label(int* temp_label, int* label, int V){
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < V) {
        temp_label[idx] = idx;
        label[idx] = idx;
    }
}

__global__
void assign_comp_head(int* label, int* parent, int* d_comp_head, int V) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < V) {
        if(parent[idx] != idx) {
            if(label[idx] != label[parent[idx]])
                d_comp_head[label[idx]] = parent[idx];
        }
    }
}

float CC(graph_data& d_input) {

    uint64_t* d_edgelist = d_input.edgelist; 
    int* fg              = d_input.flag;
    int V                = d_input.V;
    long E               = d_input.E;

    d_vector<int> temp_label(V);
    d_vector<int> label(V);
    d_vector<int> d_comp_head(V);

    int grid_size_final = CEIL(V, tb_size);

    init_parent_label<<<grid_size_final, tb_size>>>(temp_label.get(), label.get(), V);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize init_parent_label_cc kernel");

    auto start = std::chrono::high_resolution_clock::now();
    CudaTimer Timer;
    Timer.start();
    grid_size_final = CEIL(E, tb_size);

    union_find_gpu_COO<<<grid_size_final, tb_size>>>(E, temp_label.get(), fg, d_edgelist);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize union_find_gpu_COO_cc kernel");

    grid_size_final = CEIL(V, tb_size);
    cc_gpu<<<grid_size_final, tb_size>>>(label.get(), temp_label.get(), V);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize cc_gpu_cc kernel");

    assign_comp_head<<<grid_size_final, tb_size>>>(label.get(), d_input.parent, d_comp_head.get(), V);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize assign_comp_head kernel");
    auto dur = Timer.stop();
    add_function_time("Last CC", dur);
    
    auto stop = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration<double, std::milli>(stop - start).count();
    std::cout << "Last CC time using chrono: " << duration << " ms." << std::endl;
    #ifdef DEBUG
        label.print("BCC_Labels");
    #endif

    d_input.label = label.release();
    d_input.comp_head = d_comp_head.release();

    return dur;
}


#endif // CC_HXX
