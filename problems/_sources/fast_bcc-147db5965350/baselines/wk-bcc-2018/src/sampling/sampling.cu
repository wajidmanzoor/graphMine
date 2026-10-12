#include <cuda_runtime.h>
#include <cub/cub.cuh>
#include <vector>

#include "cuda_utility.cuh"
#include "sampling.cuh"

// #define DEBUG

__global__ 
void duplicate_edges_kernel(
    const uint64_t* d_out_edges,
    uint64_t* d_out_edges_dup,
    int num_edges) {

    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid >= num_edges) return;

    uint64_t e = d_out_edges[tid];

    uint32_t u = e >> 32;
    uint32_t v = e & 0xFFFFFFFFu;

    // original (u, v)
    d_out_edges_dup[2 * tid] =
        (static_cast<uint64_t>(u) << 32) | v;

    // duplicate (v, u)
    d_out_edges_dup[2 * tid + 1] =
        (static_cast<uint64_t>(v) << 32) | u;
}

// ============================================================================
// CUDA Kernel: k-out Sampling
// ============================================================================
__global__ 
void k_out_sampling_kernel(
    long* row_offsets, 
    int* flags, 
    int n, int k) {
    
    int v = blockIdx.x * blockDim.x + threadIdx.x;
    if (v >= n) return;

    int start = row_offsets[v];
    int end   = row_offsets[v + 1];

    int deg  = end - start;
    int take = (deg < k) ? deg : k;

    // Mark first 'take' edges as selected
    for (int i = 0; i < take; ++i) {
        flags[start + i] = 1;
    }
}

void remove_duplicates(
    // input:
    uint64_t* d_edges, long num_edges,
    // output:
    uint64_t* d_out, long& h_num_unique) {
    size_t temp_storage_bytes = 0;    
    void* temp_ptr = nullptr;

    cudaError_t status;
    status = cub::DeviceRadixSort::SortKeys(
        temp_ptr, temp_storage_bytes,
        d_edges, d_edges,
        num_edges
    );
    CUDA_CHECK(status, "Cub DeviceRadixSort::SortKeys temp storage allocation failed");
    CUDA_CHECK(cudaMalloc(&temp_ptr, temp_storage_bytes), "Allocating temp storage for SortKeys failed");
    status = cub::DeviceRadixSort::SortKeys(
        temp_ptr, temp_storage_bytes,
        d_edges, d_edges,
        num_edges
    );
    CUDA_CHECK(status, "Cub DeviceRadixSort::SortKeys failed");
    CUDA_CHECK(cudaFree(temp_ptr), "Freeing temp storage for SortKeys failed");
    
    // Now remove duplicates
    
    long* d_num_unique = nullptr;
    
    CUDA_CHECK(cudaMalloc(&d_num_unique, sizeof(long)), "Allocating d_num_unique failed");        
    CUDA_CHECK(cudaMemset(d_num_unique, 0, sizeof(long)), "Initializing d_num_unique failed");  
    
    status = cub::DeviceSelect::Unique(
        nullptr, temp_storage_bytes,
        d_edges,
        d_out,
        d_num_unique,
        num_edges
    );
    
    CUDA_CHECK(status, "Cub DeviceSelect::Unique temp storage allocation failed");
    CUDA_CHECK(cudaMalloc(&temp_ptr, temp_storage_bytes), "Allocating temp storage for Unique failed");
    
    status = cub::DeviceSelect::Unique(
        temp_ptr, temp_storage_bytes,
        d_edges,
        d_out,
        d_num_unique,
        num_edges
    );
    CUDA_CHECK(status, "Cub DeviceSelect::Unique failed");
    CUDA_CHECK(cudaFree(temp_ptr), "Freeing temp storage for Unique failed");   
    // Copy back the number of unique edges
    h_num_unique = 0;
    CUDA_CHECK(cudaMemcpy(&h_num_unique, d_num_unique,
               sizeof(long), cudaMemcpyDeviceToHost), "Copying d_num_unique to host failed");
    
    // Copy back the unique edges
    CUDA_CHECK(cudaMemcpy(d_edges, d_out,
               h_num_unique * sizeof(uint64_t),
               cudaMemcpyDeviceToDevice), "Copying unique edges back to d_edges failed");
    num_edges = h_num_unique;
    CUDA_CHECK(cudaFree(d_num_unique), "Freeing d_num_unique failed");
    return;
}

std::tuple<long*, int*, int*, int*, long> k_out_sampling(long* d_row_offsets, 
    uint64_t* d_edgelist,
    int num_vert, 
    long num_edges, 
    int k) {
    
    // -----------------------------------------------------------//
    // selecting atmost k edges per vertex (k-out sampling)
    
    // flag array is to mark which all edges to select 
    d_vector<int> d_flags(num_edges, 0);    
    // d_out_edges will contain the sampled edges
    d_vector<uint64_t> d_out_edges(k * num_vert);

    // Launch kernel to mark selected edges
    int blockSize = 1024;
    int gridSize = (num_vert + blockSize - 1) / blockSize;
    
    auto start = std::chrono::high_resolution_clock::now();
    // selecting atmost k edges per vertex (k-out sampling)
    k_out_sampling_kernel<<<gridSize, blockSize>>>(
        d_row_offsets, 
        d_flags.get(), 
        num_vert, 
        k
    );
    CUDA_CHECK(cudaDeviceSynchronize(), "k_out_sampling_kernel launch failed");

    // print the flag array for debugging
    #ifdef DEBUG
        std::vector<int> h_flags(num_edges);
        cudaMemcpy(h_flags.data(), d_flags.get(), num_edges * sizeof(int), cudaMemcpyDeviceToHost);
        std::cout << "Flags array: \n"; 
        for (int i = 0; i < num_edges; ++i) {
            std::cout << h_flags[i] << " ";
        }
        std::cout << std::endl;
    #endif

    // Determine temporary storage requirements and allocate
    long* d_num_selected = nullptr;
    void* d_temp = nullptr;
    size_t temp_bytes = 0;
    
    CUDA_CHECK(cudaMalloc(&d_num_selected, sizeof(long)), "Allocating d_num_selected failed");
    CUDA_CHECK(cudaMemset(d_num_selected, 0, sizeof(long)), "Initializing d_num_selected failed");

    cub::DeviceSelect::Flagged(
        d_temp, temp_bytes,
        d_edgelist,
        d_flags.get(),
        d_out_edges.get(),
        d_num_selected,
        num_edges
    );

    // Allocate temporary storage
    CUDA_CHECK(cudaMalloc(&d_temp, temp_bytes), "Allocating d_temp failed");

    // Perform the selection
    cub::DeviceSelect::Flagged(
        d_temp, temp_bytes,
        d_edgelist,
        d_flags.get(),
        d_out_edges.get(),
        d_num_selected,
        num_edges
    );
    CUDA_CHECK(cudaDeviceSynchronize(), "Device synchronization failed");

    // Copy back the actual number of edges
    long actual_sampled_edges = 0;
    CUDA_CHECK(cudaMemcpy(&actual_sampled_edges, d_num_selected,
            sizeof(long), cudaMemcpyDeviceToHost), "Copying d_num_selected to host failed");

    if(actual_sampled_edges > (long)k * (long)num_vert) {
        std::cerr << "Error: actual_sampled_edges > k * num_vert" << std::endl;
        exit(EXIT_FAILURE);
    }
    // std::cout << "Number of sampled edges: " << actual_sampled_edges << std::endl;

    #ifdef DEBUG
        std::vector<uint64_t> sampled_edges(actual_sampled_edges);
        CUDA_CHECK(cudaMemcpy(sampled_edges.data(), d_out_edges.get(),
        actual_sampled_edges * sizeof(uint64_t),
        cudaMemcpyDeviceToHost), "Copying d_out_edges to host failed");

        for(auto &edge : sampled_edges) 
            std::cout << "u: " << (edge >> 32) << ", v: " << (edge & 0xFFFFFFFF) << std::endl;
        std::cout << std::endl;
    #endif
    // ------------------------- end of k-out sampling ------------------------- //
    
    // ------- Create duplicate edges for sampled edges ------- //
    // d_out_edges_dup arrays is an intermediate arrays used to contains the duplicate edges
    // e.g. For (0,1), I have (1, 0) as well.
    d_vector<uint64_t> d_out_edges_dup(2 * k * num_vert);

    // the sampled edges are in d_out_edges 
    // now create duplicates in d_out_edges_dup as for every (u, v), as there maynot be (v, u) 
    gridSize = (actual_sampled_edges + blockSize - 1) / blockSize;
    duplicate_edges_kernel<<<gridSize, blockSize>>>(
        d_out_edges.get(),
        d_out_edges_dup.get(),
        actual_sampled_edges
    );
    CUDA_CHECK(cudaDeviceSynchronize(), "duplicate_edges_kernel launch failed");
    
    #ifdef DEBUG
        std::vector<uint64_t> h_out_edges_dup(2 * actual_sampled_edges);
        CUDA_CHECK(cudaMemcpy(h_out_edges_dup.data(), d_out_edges_dup.get(),
            2 * actual_sampled_edges * sizeof(uint64_t),
            cudaMemcpyDeviceToHost), "Copying d_out_edges_dup to host failed");
        
        std::cout << "\nSampled Edgelist with duplicates:\n";
        for (size_t i = 0; i < h_out_edges_dup.size(); ++i) {
            uint64_t e = h_out_edges_dup[i];
            uint32_t u = e >> 32;
            uint32_t v = e & 0xFFFFFFFFu;
            std::cout << "u: " << u << ", v: " << v << std::endl;
        }
        std::cout << std::endl;
    #endif
    
    // ------- end of duplicate edges creation ------- //

    // ------- Remove duplicates from d_out_edges_dup ------- //
    d_vector<uint64_t> d_out_edges_unique(2 * k * num_vert);
    // Remove duplicates from d_out_edges_dup

    long h_num_unique = 0;
    remove_duplicates(d_out_edges_dup.get(), 2 * actual_sampled_edges, d_out_edges_unique.get(), h_num_unique);
    
    // Free temporary device memory
    CUDA_CHECK(cudaFree(d_num_selected), "Freeing d_num_selected failed");
    CUDA_CHECK(cudaFree(d_temp), "Freeing d_temp failed");
    // ------- end of removing duplicates ------- //
    
    auto end = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double, std::milli> duration = end - start;

    // ------- csr creation from sampled unique edges ------- //
    /* final output edges are in d_out_edges_unique
    and size is h_num_unique
    create csr out of it */

    // ip: edgelist, edge count, num_vert
    // op: csr arrays (d_vertices & d_edges) and unique edges without duplicates (d_U & d_V)
    d_vector<long> d_vertices(num_vert + 1, 0);
    d_vector<int> d_edges(h_num_unique, 0);
    d_vector<int> d_U(h_num_unique/2);
    d_vector<int> d_V(h_num_unique/2);

    int dur = gpu_csr(d_out_edges_unique.get(), h_num_unique, num_vert,
        d_vertices.get(), d_edges.get(),
        d_U.get(), d_V.get());

    duration += std::chrono::duration<double, std::milli>(dur);
    add_function_time("step 1: k_out_sampling", duration.count());
    long* d_vertices_ptr = d_vertices.release();
    int* d_edges_ptr = d_edges.release();
    int* d_U_ptr = d_U.release();
    int* d_V_ptr = d_V.release();
    // ------- end of csr creation -------

    // print all edges
    #ifdef DEBUG
        std::vector<uint64_t> h_final_edges(h_num_unique);
        CUDA_CHECK(cudaMemcpy(h_final_edges.data(), d_out_edges_unique.get(),
            h_num_unique * sizeof(uint64_t),
            cudaMemcpyDeviceToHost), "Copying final edges to host failed"); 
        std::cout << "Final unique edges after k-out sampling: \n";
        for (size_t i = 0; i < h_num_unique; ++i) {
            uint64_t e = h_final_edges[i];
            uint32_t u = e >> 32;
            uint32_t v = e & 0xFFFFFFFFu;
            std::cout << "u: " << u << ", v: " << v << std::endl;
        }
    #endif

    return {d_vertices_ptr, d_edges_ptr, d_U_ptr, d_V_ptr, h_num_unique/2};
    // return {nullptr, nullptr, nullptr, nullptr, 0};
}