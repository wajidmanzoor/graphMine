#include "final_bcc/vertex_merging.cuh"
#include "cuda_utility.cuh"

#include "sampling.cuh"
#include "gpu_csr.cuh"
#include "cuda_bcc/bcc.cuh"

__global__
void create_condensed_graph(uint64_t* d_edgelist, long num_edges,
                             int* d_imp_bcc_num, uint64_t* d_new_edgelist) {
    long idx = blockIdx.x * blockDim.x + threadIdx.x;
    if(idx < num_edges) {
        uint64_t edge = d_edgelist[idx];
        int u = static_cast<int>(edge >> 32);
        int v = static_cast<int>(edge & 0xFFFFFFFF);

        int new_u = d_imp_bcc_num[u];
        int new_v = d_imp_bcc_num[v];

        uint64_t new_edge = (static_cast<uint64_t>(new_u) << 32) | static_cast<uint64_t>(new_v);
        d_new_edgelist[idx] = new_edge;
    }
}

// Kernel to mark self-loops and duplicates
__global__ 
void markForRemoval(uint64_t* d_edges, int* d_flags, size_t num_edges) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < num_edges) {
        // Mark self-loops
        int edges_u = static_cast<int>(d_edges[idx] >> 32);
        int edges_v = static_cast<int>(d_edges[idx] & 0xFFFFFFFF);
        if (edges_u == edges_v) {
            d_flags[idx] = false;
        }
        // Mark duplicates (assuming edges are sorted)
        else if (idx > 0 && d_edges[idx] == d_edges[idx - 1]) {
            d_flags[idx] = false;
        }
        else {
            d_flags[idx] = true;
        }
    }
}

void vertex_merging(int org_num_vert, gpu_bcc& g_bcc_ds, uint64_t* d_edgelist, long org_num_edges) {
    int* d_imp_bcc_num = g_bcc_ds.d_imp_bcc_num;
    
    g_verbose = false;
    // print original BCC numbers
    if(g_verbose) {
        std::cout << "Original BCC numbers before vertex merging:" << std::endl;
        kernelPrintArray(d_imp_bcc_num, org_num_vert);
    }
    
    d_vector<uint64_t> d_new_edgelist(org_num_edges);
    long new_num_edges = 0;
    int numThreads = 1024;
    size_t numBlocks = (org_num_edges + numThreads - 1) / numThreads;

    auto start = std::chrono::high_resolution_clock::now();
    create_condensed_graph<<< numBlocks, numThreads >>>(d_edgelist, org_num_edges,
                                       d_imp_bcc_num, d_new_edgelist.get());
    CUDA_CHECK(cudaDeviceSynchronize(), "create_condensed_graph kernel failed");

    // Sort the packed pairs
    size_t temp_storage_bytes = 0;
    void* d_temp_storage = NULL;
    
    cudaError_t status;
    status = cub::DeviceRadixSort::SortKeys(d_temp_storage, temp_storage_bytes, d_new_edgelist.get(), d_new_edgelist.get(), org_num_edges);
    CUDA_CHECK(status, "Error in CUB SortKeys");
    CUDA_CHECK(cudaMalloc(&d_temp_storage, temp_storage_bytes), "Failed to allocate temporary storage for CUB SortKeys");

    status = cub::DeviceRadixSort::SortKeys(d_temp_storage, temp_storage_bytes, d_new_edgelist.get(), d_new_edgelist.get(), org_num_edges);
    CUDA_CHECK(status, "Error in CUB SortKeys");

    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize stream after copying max prefix sums");

    auto end = std::chrono::high_resolution_clock::now();
    int duration = std::chrono::duration<double, std::milli>(end - start).count();
    
    cudaFree(d_temp_storage);
    // Select unique edges using CUB
    temp_storage_bytes = 0;
    d_vector<uint64_t> d_final_edgelist(org_num_edges);
    d_vector<long> d_num_selected(1);

    // Remove self-loops and duplicates
    int* d_edge_flags;
    CUDA_CHECK(cudaMalloc((void**)&d_edge_flags, org_num_edges * sizeof(int)), "Failed to allocate memory for edge flags");
    
    start = std::chrono::high_resolution_clock::now();
    markForRemoval<<< numBlocks, numThreads >>>(d_new_edgelist.get(), d_edge_flags, org_num_edges);
    CUDA_CHECK(cudaDeviceSynchronize(), "mark_for_removal kernel failed");

    cub::DeviceSelect::Flagged(
        nullptr, 
        temp_storage_bytes,
        d_new_edgelist.get(), 
        d_edge_flags,
        d_final_edgelist.get(), 
        d_num_selected.get(),
        org_num_edges);
    CUDA_CHECK(cudaMalloc(&d_temp_storage, temp_storage_bytes), "Allocating temp storage failed");

    cub::DeviceSelect::Flagged(
        d_temp_storage, 
        temp_storage_bytes,
        d_new_edgelist.get(), 
        d_edge_flags, 
        d_final_edgelist.get(), 
        d_num_selected.get(),
        org_num_edges);
    CUDA_CHECK(cudaDeviceSynchronize(), "cub::DeviceSelect::Flagged failed");
    

    // Copy number of selected edges
    long h_num_selected = 0;
    CUDA_CHECK(cudaMemcpy(&h_num_selected, d_num_selected.get(), sizeof(long), cudaMemcpyDeviceToHost), "Copying num_selected failed");     
    if(g_verbose) {
        std::cout << "Number of edges after vertex merging (self-loops and duplicates removed): " << h_num_selected << std::endl;
    }  
    end = std::chrono::high_resolution_clock::now();
    duration += std::chrono::duration<double, std::milli>(end - start).count();
    cudaFree(d_temp_storage);
    cudaFree(d_edge_flags);

    /* final output edges are in d_final_edgelist and size is d_num_selected.
        Create csr out of it */

    // ip: edgelist, edge count, num_vert
    // op: csr arrays (d_vertices & d_edges) and unique edges without duplicates (d_U & d_V)
    int num_vert = g_bcc_ds.numVert;
    long num_edges = h_num_selected;
    d_vector<long> d_vertices(num_vert + 1, 0);
    d_vector<int> d_edges(num_edges, 0);
    d_vector<int> d_U(num_edges/2);
    d_vector<int> d_V(num_edges/2);

    // start = std::chrono::high_resolution_clock::now();
    int dur = gpu_csr(
        d_final_edgelist.get(), 
        num_edges, 
        num_vert, 
        // outputs
        d_vertices.get(), 
        d_edges.get(), 
        d_U.get(), 
        d_V.get());
    duration += dur;
    gpu_bcc g_bcc_ds_(num_vert, num_edges/2);            
    // copy csr graph
    g_bcc_ds_.d_vertices = d_vertices.get();
    g_bcc_ds_.d_edges = d_edges.get();
    
    // Copy the edge-list
    g_bcc_ds_.original_u = d_U.get();
    g_bcc_ds_.original_v = d_V.get();

    // init data_structures
    g_bcc_ds_.init(num_vert, num_edges/2);

    add_function_time("Step 3: Vertex Merging", duration);
    
    // start cuda_bcc
    cuda_bcc(g_bcc_ds_, true);
}