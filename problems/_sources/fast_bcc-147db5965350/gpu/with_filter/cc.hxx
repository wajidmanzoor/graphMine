#ifndef CC_HXX
#define CC_HXX

#include <iostream>
#include <cuda_runtime.h>
#include "common.hxx"

#define tb_size 1024

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
    // printf("Doing union_async for src: %d and dst: %d\n", src, dst);
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
void union_find_gpu_COO(
    int numVert, int* temp_label, 
    int* d_parent, uint64_t* d_sf_edges,
    int* d_first, int* d_last, 
    int* d_low, int* d_high) {

    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numVert) {
        // The first group of n threads operates on d_parent.
        int u = idx;
        int v = d_parent[idx];

        if(u == v) return;

        int f_u = d_first[u];
        int l_u = d_last[u];

        int f_v = d_first[v];
        int l_v = d_last[v];
        
        int low_u = d_low[u];
        int high_u = d_high[u];
        
        int low_v = d_low[v];
        int high_v = d_high[v];
        
        // if it a fence edge; ignore, else do CC.
        if( (f_u <= low_v and l_u >= high_v) or (f_v <= low_u and l_v >= high_u) ) return;

        // printf("Calling union_async for tree edges src: %d and dst: %d\n", u, v);
        union_async(idx, u, v, temp_label);
        
    } else if (idx < 2 * numVert) {
        // The second group of n threads operates on d_sf_edges.
        int index = idx - numVert;
        if(d_sf_edges[index] == INT_MAX) {
            // printf("Returning for the cross-edges src: %ld\n", d_sf_edges[index]);    
            return;
        }
        // all these are cross-edges; so do CC for all
        int u = (d_sf_edges[index] >> 32) & 0xFFFFFFFF;
        int v = (d_sf_edges[index]) & 0xFFFFFFFF;
        // #ifdef DEBUG
        // printf("Calling union_async for cross-edges src: %d and dst: %d\n", u, v);
        // #endif
        union_async(idx, u, v, temp_label);
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
void init_parent_label(int* temp_label, int* label, int* d_comp_head, int V) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < V) {
        temp_label[idx] = idx;
        label[idx] = idx;
        d_comp_head[idx] = -1;
    }
}

__global__
void assign_comp_head(int* label, int* parent, int* d_comp_head, int V, int root) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < V) {
        if(parent[idx] != idx) {
            if(label[idx] != label[parent[idx]])
                d_comp_head[label[idx]] = parent[idx];
        }

        if(parent[idx] == root and idx != root) {
            if(label[idx] != root) 
                label[root] = label[idx];
        }
    }
}

float CC(graph_data& d_input) {

    uint64_t* d_sf_edges = d_input.sf_edges; 
    int V                = d_input.V;
    int root             = d_input.root;
    
    int* d_parent = d_input.parent;
    int* d_first = d_input.first;
    int* d_last  = d_input.last;
    int* d_low   = d_input.low; 
    int* d_high  = d_input.high;

    d_vector<int> temp_label(V);
    d_vector<int> label(V); // this is the final BCC labels
    d_vector<int> d_comp_head(V);

    int grid_size_final = CEIL(V, tb_size);

    init_parent_label<<<grid_size_final, tb_size>>>(temp_label.get(), label.get(), d_comp_head.get(), V);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize init_parent_label_cc kernel");

    auto start = std::chrono::high_resolution_clock::now();
    CudaTimer Timer;
    Timer.start();
    grid_size_final = CEIL(2*V, tb_size);
    // count, rep array, edgelist, first, last, low, high
    union_find_gpu_COO<<<grid_size_final, tb_size>>>(
        V, 
        temp_label.get(), 
        d_parent, d_sf_edges,
        d_first, d_last,
        d_low, d_high);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize union_find_gpu_COO_cc kernel");

    grid_size_final = CEIL(V, tb_size);
    cc_gpu<<<grid_size_final, tb_size>>>(label.get(), temp_label.get(), V);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize cc_gpu_cc kernel");

    // label.print("BCC Labels");

    assign_comp_head<<<grid_size_final, tb_size>>>(label.get(), d_input.parent, d_comp_head.get(), V, root);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize assign_comp_head kernel");


    auto dur = Timer.stop();
    add_function_time("Last CC", dur);
    
    auto stop = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration<double, std::milli>(stop - start).count();
    std::cout << "Last CC time using chrono: " << duration << " ms." << std::endl;
    #ifdef DEBUG
        label.print("BCC_Labels");
    #endif

    d_input.label = label.release(); // final bcc numbers for all vertices
    d_input.comp_head = d_comp_head.release();

    return dur;
}


#endif // CC_HXX
