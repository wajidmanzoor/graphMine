#include <iostream>
#include <fstream>
#include <cub/cub.cuh>
#include <cuda_runtime.h>

#include "common.hxx"
#include "sparse_table_min.hxx"
#include "sparse_table_max.hxx"

#define LOCAL_BLOCK_SIZE 20

__global__
void init_w1_w2(
    int* w1, int* w2, 
    int* temp_label, 
    uint64_t* sf_edges, 
    int numVert, 
    int* first_occ, int* last_occ) {

    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < numVert) {
        w1[idx] = first_occ[idx];
        w2[idx] = last_occ[idx];
        temp_label[idx] = idx;
        sf_edges[idx] = INT_MAX;
    }
}

__device__ inline 
int find_compress_SF(int i, int* temp_label) {
    int j = i;
    if (temp_label[j] == j) {
        return j;
    }
    do {
        j = temp_label[j];
    } while (temp_label[j] != j);

    int tmp;
    while((tmp = temp_label[i]) > j) {
        temp_label[i] = j;
        i = tmp;
    }
    return j;
}

__device__ inline 
bool union_async_SF(
    long idx, int src, int dst, 
    int* temp_label, uint64_t* sf_edges, uint64_t* edge_list) {
    while(1) {
        int u = find_compress_SF(src, temp_label);
        int v = find_compress_SF(dst, temp_label);

        if(u == v) break;
        
        if(v > u) { int temp; temp = u; u = v; v = temp; }
        
        if(u == atomicCAS(&temp_label[u], u, v)) {
           sf_edges[u] = edge_list[idx];
           return true;
        } 
    }
    return false;
}

__global__ 
void fill_w1_w2(uint64_t* edge_list, long numEdges, 
    int* w1, int* w2, int* parent, int* temp_label,
    uint64_t* sf_edges, int* first_occ , int* last_occ) {

    long idx = blockIdx.x * blockDim.x + threadIdx.x;
    
    if(idx < numEdges){
        int u = (edge_list[idx] >> 32) & 0xFFFFFFFF;
        int v = edge_list[idx] & 0xFFFFFFFF;

        int f_u = first_occ[u];
        int l_u = last_occ[u];
        int f_v = first_occ[v];
        int l_v = last_occ[v];

        // if it is a non-tree edge
        if(u < v and (parent[u] != v) and (parent[v] != u)) {
            // Checking if the edge is a back-edge; if yes then update the tages
            /*
             * A back edge connects a vertex to one of its ancestors:
             *   - For a back edge where u is a descendant of v, then:
             *         first_occ[v] < first_occ[u] && last_occ[u] < last_occ[v]
             *   - For a back edge where v is a descendant of u, then:
             *         first_occ[u] < first_occ[v] && last_occ[v] < last_occ[u]
             *
             * If neither condition holds, the edge is considered a cross edge.
             */
            if ((f_v < f_u and l_u < l_v) or (f_u < f_v && l_v < l_u)) {
                // It is a back edge
                // printf("u: %d, v: %d is a back-edge\n", u, v);
                if(f_u < f_v) {
                    atomicMin(&w1[v], f_u);
                    atomicMax(&w2[u], f_v);
                }
                else {
                    atomicMin(&w1[u], f_v);
                    atomicMax(&w2[v], f_u);
                }
            }
            else {
                // else construct the forest as it is a cross-edge
                // printf("u: %d, v: %d is a cross-edge\n", u, v);
                bool r = union_async_SF(idx, u, v, temp_label, sf_edges, edge_list);
            }
        }
    }
}

__global__
void update_w1_w2(
    uint64_t* sf_edges, int numVert, 
    int* w1, int* w2, 
    int* parent, int* first_occ, int* last_occ) {

    int idx = blockIdx.x * blockDim.x + threadIdx.x ;
    if (idx < numVert) {
        if(sf_edges[idx] == INT_MAX) return;

        int u = (sf_edges[idx] >> 32) & 0xFFFFFFFF;
        int v = sf_edges[idx] & 0xFFFFFFFF;
        
        if(u < v) {
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
    
    d_vector<int> d_left(numVert);
    d_vector<int> d_right(numVert);
    
    d_vector<int> d_a1(2*numVert);
    d_vector<int> d_a2(2*numVert);

    d_vector<int> d_na1(n_asize);
    d_vector<int> d_na2(n_asize);
    
    // d_vector<int> d_fg(numEdges);
    // sf on cross edges (need to be initialised with INT_MAX)
    d_vector<uint64_t> sf_edges(numVert);
    d_vector<int> temp_label(numVert);

    // output
    d_vector<int> d_low(numVert);
    d_vector<int> d_high(numVert);

    CudaTimer Timer;
    Timer.start();

    // step 2: Compute w1, w2, low and high using first and last
    init_w1_w2<<<CEIL(numVert, tb_size), tb_size>>>(
        d_w1.get(), 
        d_w2.get(), 
        temp_label.get(),
        sf_edges.get(),
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
        temp_label.get(),
        sf_edges.get(), 
        d_first_occ, 
        d_last_occ);

    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize device");

    // std::cout << "Printing from tags.cu\n";
    // print_device_edges(sf_edges.get(), numVert);

    update_w1_w2<<<CEIL(numVert, tb_size), tb_size>>>(
        sf_edges.get(), 
        numVert, 
        d_w1.get(), 
        d_w2.get(), 
        d_parent, 
        d_first_occ, 
        d_last_occ
    );
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

    auto dur = Timer.stop();

    dur += main_min(2*numVert, numVert, d_a1.get(), d_left.get(), d_right.get(), d_low.get(), n_asize , d_na1.get());
    dur += main_max(2*numVert, numVert, d_a2.get(), d_left.get(), d_right.get(), d_high.get(), n_asize , d_na2.get());

    add_function_time("Tags", dur);
    // std::cout << "Tages were computed in: " << dur << " ms." << std::endl;

    d_input.sf_edges = sf_edges.release();
    d_input.low  = d_low.release();
    d_input.high = d_high.release();

    return dur;
}