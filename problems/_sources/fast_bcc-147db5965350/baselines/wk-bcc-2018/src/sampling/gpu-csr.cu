//---------------------------------------------------------------------
// Standard Libraries
//---------------------------------------------------------------------
#include <vector>
#include <chrono>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <filesystem>
#include <cassert>

//---------------------------------------------------------------------
// CUDA Libraries
//---------------------------------------------------------------------
#include <cub/cub.cuh>
#include <cuda_runtime.h>

//---------------------------------------------------------------------
// CSR Specific funtions & utilities
//---------------------------------------------------------------------
#include "gpu_csr.cuh"
#include "cuda_utility.cuh"

// #define DEBUG

//---------------------------------------------------------------------
// CUDA Kernels
//---------------------------------------------------------------------
__global__ 
void unpackPairs(
	const uint64_t *d_edgelist, 
	int *d_U, int *d_V, 
	int* d_flags,
	long num_edges) {
    int64_t idx = blockIdx.x * blockDim.x + threadIdx.x;

    if (idx < num_edges) {
		int u = d_edgelist[idx] >> 32;
		int v = d_edgelist[idx] & 0xFFFFFFFFLL;

		// select all unique edges (u,v) where u > v
		if(u > v)
			d_flags[idx] = 1;

        // Extract the upper 32 bits
        d_U[idx] = u;
        // Extract the lower 32 bits, ensuring it's treated as a signed int
        d_V[idx] = v;  

    }
}

// CSR starts
__global__
void cal_offset(
	int no_of_vertices, 
	long no_of_edges, int* dir_U, long* offset) {

    // based on the assumption that the graph is connected and graph size is > 2
    long tid = (blockIdx.x * blockDim.x) + threadIdx.x;

    if(tid == 0) 
        offset[tid] = 0;

    if(tid == no_of_vertices) 
        offset[tid] = no_of_edges;

    if(tid < no_of_edges - 1) {
        
        if(dir_U[tid] != dir_U[tid + 1]) {

            int v = dir_U[tid + 1];
            offset[v] = tid + 1;
        }
    }
}  

int gpu_csr(uint64_t* d_edgelist, 
            long numEdges , 
            const int& numVert,
            long* d_vertices,
            int* d_edges,
            int* d_U,
            int* d_V) {
	
    // std::cout << "From gpu-csr: numEdges: " << numEdges << ", numVert: " << numVert << std::endl;
    #ifdef DEBUG
        // print d_edgelist
        std::cout << "Edgelist input to GPU CSR:\n";
        std::vector<uint64_t> h_edgelist(numEdges);
        CUDA_CHECK(cudaMemcpy(h_edgelist.data(), d_edgelist,
            numEdges * sizeof(uint64_t),
            cudaMemcpyDeviceToHost), "Copying d_edgelist to host failed");
        std::cout << "Edgelist:\n";
        for (size_t i = 0; i < h_edgelist.size(); ++i) {
            uint64_t e = h_edgelist[i];
            uint32_t u = e >> 32;
            uint32_t v = e & 0xFFFFFFFFu;
            std::cout << "(" << u << ", " << v << ") \n";
        }
        std::cout << std::endl;
    #endif
    // 1.1. Unpack edgelist into two arrays
    d_vector<int> d_U_tmp(numEdges);
    // d_edges serves as d_V_tmp here

	long maxThreadsPerBlock = 1024;
	long blocksPerGrid = (numEdges + maxThreadsPerBlock - 1) / maxThreadsPerBlock;
	
    // flag array to mark unique edges
    d_vector<int> d_flags(numEdges, 0);
    d_vector<uint64_t> d_edgelist_tmp(numEdges);
    d_vector<long> d_num_selected(1);

    auto start = std::chrono::high_resolution_clock::now();
    unpackPairs<<<blocksPerGrid, maxThreadsPerBlock>>>(
		d_edgelist, 
		d_U_tmp.get(), 
		d_edges,
		d_flags.get(), 
		numEdges);
	CUDA_CHECK(cudaDeviceSynchronize(), "Unpacking edgelist failed");

    #ifdef DEBUG
        // print d_flags
        std::vector<int> h_flags(numEdges);
        CUDA_CHECK(cudaMemcpy(h_flags.data(), d_flags.get(),
            numEdges * sizeof(int),
            cudaMemcpyDeviceToHost), "Copying d_flags to host failed");
        std::cout << "Flags after unpacking:\n";
        for (size_t i = 0; i < h_flags.size(); ++i) {
            std::cout << h_flags[i] << " ";
        }
        std::cout << std::endl;
        
        // print d_U_tmp and d_edges
        std::vector<int> h_U_tmp(numEdges);
        std::vector<int> h_V_tmp(numEdges);
        
        CUDA_CHECK(cudaMemcpy(h_U_tmp.data(), d_U_tmp.get(),
            numEdges * sizeof(int),
            cudaMemcpyDeviceToHost), "Copying d_U_tmp to host failed");
        
        CUDA_CHECK(cudaMemcpy(h_V_tmp.data(), d_edges,
            numEdges * sizeof(int),
            cudaMemcpyDeviceToHost), "Copying d_edges to host failed");
        
        std::cout << "\nUnpacked Edgelist (Before selecting unique edges):\n";
        for (size_t i = 0; i < h_U_tmp.size(); ++i) {
            std::cout << "(" << h_U_tmp[i] << ", " << h_V_tmp[i] << ") \n";
        }   
    #endif

	// Launch the kernel to compute offsets
	long numBlocks = (numEdges + maxThreadsPerBlock - 1) / maxThreadsPerBlock;
    cal_offset<<<numBlocks, maxThreadsPerBlock>>>(
		numVert, numEdges, d_U_tmp.get(), d_vertices);
    CUDA_CHECK(cudaGetLastError(), "cal_offset kernel launch failed");
    CUDA_CHECK(cudaDeviceSynchronize(), "cal_offset kernel execution failed");

    // Select unique edges using CUB
    size_t temp_storage_bytes = 0;
    void* d_temp_storage = nullptr;
    
    cub::DeviceSelect::Flagged(
        nullptr, 
        temp_storage_bytes,
        d_edgelist, 
        d_flags.get(),
        d_edgelist_tmp.get(), 
        d_num_selected.get(),
        numEdges);
    CUDA_CHECK(cudaMalloc(&d_temp_storage, temp_storage_bytes), "Allocating temp storage failed");
    
    cub::DeviceSelect::Flagged(
        d_temp_storage, 
        temp_storage_bytes,
        d_edgelist, 
        d_flags.get(), 
        d_edgelist_tmp.get(), 
        d_num_selected.get(), 
        numEdges);

    CUDA_CHECK(cudaDeviceSynchronize(), "DeviceSelect failed");

    // Copy number of selected edges
    long h_num_selected = 0;
    CUDA_CHECK(cudaMemcpy(&h_num_selected, d_num_selected.get(), sizeof(long), cudaMemcpyDeviceToHost), "Copying num_selected failed");

    // assert(h_num_selected == numEdges/2);
    
    // Unpack the selected edges
    long blocksPerGrid2 = (h_num_selected + maxThreadsPerBlock - 1) / maxThreadsPerBlock;
    unpackPairs<<<blocksPerGrid2, maxThreadsPerBlock>>>(
        d_edgelist_tmp.get(),
        d_U, 
        d_V, 
        d_flags.get(), 
        h_num_selected);
    CUDA_CHECK(cudaDeviceSynchronize(), "Unpacking selected edgelist failed");
    auto end = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double, std::milli> duration = end - start;

    CUDA_CHECK(cudaFree(d_temp_storage), "Freeing temp storage failed");

    /* Output:
     1. CSR arrays:
        d_vertices (size: numVert + 1)
        d_edges (size: numEdges)
     2. Unique edgelist arrays:
        d_U (size: numEdges/2)
        d_V (size: numEdges/2)
    */

    return duration.count();
}

// ====[ End of gpu_csr Code ]====