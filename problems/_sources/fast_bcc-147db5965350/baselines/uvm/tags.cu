#include <iostream>
#include <fstream>
#include <cub/cub.cuh>
#include <cuda_runtime.h>

#include "common.hxx"
#include "sparse_table_min.hxx"
#include "sparse_table_max.hxx"

#define LOCAL_BLOCK_SIZE 20

// #define DEBUG

__global__
void init_w1_w2(int* w1, int* w2, int numVert, int* first_occ, int* last_occ) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numVert) {
        w1[idx] = first_occ[idx];
        w2[idx] = last_occ[idx];
    }
}

__global__
void fill_w1_w2(uint64_t* edge_list, long numEdges, int* w1, int* w2, int* parent , int* first_occ , int* last_occ) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numEdges) {
        int u = (edge_list[idx] >> 32) & 0xFFFFFFFF;
        int v = edge_list[idx] & 0xFFFFFFFF;
        // if non tree edge
        if(parent[u] != v && parent[v] != u) {
            atomicMin(&w1[v], first_occ[u]);
            atomicMin(&w1[u], first_occ[v]);
            atomicMax(&w2[v], last_occ[u]);
            atomicMax(&w2[u], last_occ[v]);
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
void mark_fence_back(uint64_t* edge_list, long numEdges, int* low, int* high, int* first_occ, int* last_occ, int* d_parent, int* fg) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numEdges) {
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
                fg[idx] = 0;
            }
            else{
                fg[idx] = 1;
            }
        }
        else{
            if(f_u<=low_v && l_u>=high_v  || f_v<=low_u && l_v>=high_u) {
                fg[idx] = 0;
            }
            else{
                fg[idx] = 1;
            }

        }
    }
}

__global__
void fill_d_from_to1(uint64_t* edge_list, long numEdges, int* d_from, int* d_to) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numEdges) {
        d_from[idx] = (edge_list[idx] >> 32) & 0xFFFFFFFF;
        d_to[idx] = edge_list[idx] & 0xFFFFFFFF;
    }
}

__global__
void my_copy(int* rep_temp, int* rep, int numVert) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numVert) {
        rep[idx] = rep_temp[idx];
    }
}

__global__
void mark_neg_one(int* rep, int* iscutVertex, int numVert) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numVert) {
        if(iscutVertex[idx]){
            rep[idx] = numVert + idx+1;
        }
    }
}

__global__
void mark_rem_vertices(int* rep, int numVert, int* prefix_sum) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numVert) {
        prefix_sum[rep[idx]] = 1;
    }
}


__global__
void update_rep(int* temp_rep, int* rep , int* prefix_sum, int numVert) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numVert) {
        temp_rep[idx] = prefix_sum[rep[idx]];
    }
}

float assign_tags(graph_data& d_input) {

	int numVert             = 	d_input.V;
    int numEdges            = 	d_input.E;
    int root                =   d_input.root;
    int* d_first_occ        =   d_input.first;
    int* d_last_occ         =   d_input.last;
    uint64_t* d_edgelist    =   d_input.edgelist;
    int* d_parent           =   d_input.parent;

    int n_asize = CEIL(2 * numVert, LOCAL_BLOCK_SIZE);

    int tb_size = 1024;

    d_vector<int> d_w1(numVert);
    d_vector<int> d_w2(numVert);
    d_vector<int> d_low(numVert);
    d_vector<int> d_high(numVert);
    d_vector<int> d_left(numVert);
    d_vector<int> d_right(numVert);
    
    d_vector<int> d_a1(2*numVert);
    d_vector<int> d_a2(2*numVert);

    d_vector<int> d_na1(n_asize);
    d_vector<int> d_na2(n_asize);

    d_vector<int> d_fg(numEdges);

    CudaTimer Timer;
    Timer.start();

    // step 2: Compute w1, w2, low and high using first and last
    init_w1_w2<<<CEIL(numVert, tb_size), tb_size>>>(
        d_w1.get(), 
        d_w2.get(), 
        numVert, 
        d_first_occ, 
        d_last_occ);

    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize device");

    fill_w1_w2<<<CEIL(numEdges, tb_size), tb_size>>>(
        d_edgelist, 
        numEdges, 
        d_w1.get(), 
        d_w2.get(), 
        d_parent, 
        d_first_occ, 
        d_last_occ);

    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize device");

    compute_a1<<<CEIL(numVert, tb_size), tb_size>>>(
        d_first_occ, d_last_occ, 
        numVert, 
        d_w1.get(),
        d_a1.get()
    );
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize device");

    compute_a1<<<CEIL(numVert, tb_size), tb_size>>>(
        d_first_occ, 
        d_last_occ, 
        numVert, 
        d_w2.get(), 
        d_a2.get()
    );
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize device");

    fill_left_right<<<CEIL(numEdges, tb_size), tb_size>>>(
        d_first_occ, 
        d_last_occ, 
        numVert, 
        d_left.get(), 
        d_right.get()
    );
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize device");

    main_min(2*numVert, numVert, d_a1.get(), d_left.get(), d_right.get(), d_low.get(), n_asize , d_na1.get());
    main_max(2*numVert, numVert, d_a2.get(), d_left.get(), d_right.get(), d_high.get(), n_asize , d_na2.get());

    // Step 3: Mark Fence and Back Edges using the above 4 tags
    mark_fence_back<<<CEIL(numEdges, tb_size), tb_size>>>(
        d_edgelist, 
        numEdges, 
        d_low.get(), 
        d_high.get(), 
        d_first_occ, 
        d_last_occ, 
        d_parent, 
        d_fg.get()
    );
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize device");

    auto dur = Timer.stop();
    add_function_time("Tages", dur);
    // std::cout << "Tages were computed in: " << dur << " ms." << std::endl;

    d_input.flag = d_fg.release();

    return dur;
}