#ifndef CUDA_UTILITY_CUH
#define CUDA_UTILITY_CUH

#include <iostream>
#include <cub/cub.cuh> 
#include <cuda_runtime.h>

inline void check_for_error(cudaError_t error, const std::string& message, const std::string& file, int line) noexcept {
    if (error != cudaSuccess) {
        std::cerr << "CUDA Error at " << file << ":" << line << " - " << message << "\n";
        std::cerr << "CUDA Error description: " << cudaGetErrorString(error) << "\n";
        std::exit(EXIT_FAILURE);
    }
}

// #define DEBUG

#define CUDA_CHECK(err, msg) check_for_error(err, msg, __FILE__, __LINE__)

template <typename T>
__global__ 
void print_device_array_kernel(T* array, long size) {
    int index = threadIdx.x + blockIdx.x * blockDim.x;
    if (index == 0) { 
        for (int i = 0; i < size; ++i) {
            printf("Array[%d] = %lld\n", i, static_cast<long long>(array[i]));
        }
    }
}

inline void print_mem_info() {
    size_t free_byte;
    size_t total_byte;
    CUDA_CHECK(cudaMemGetInfo(&free_byte, &total_byte), "" );

    double free_db = static_cast<double>(free_byte); 
    double total_db = static_cast<double>(total_byte);
    double used_db = total_db - free_db;
    std::cout << "----------------------------------------\n"
          << "GPU Memory Usage Post-Allocation:\n"
          << "Used:     " << used_db / (1024.0 * 1024.0) << " MB\n"
          << "Free:     " << free_db / (1024.0 * 1024.0) << " MB\n"
          << "Total:    " << total_db / (1024.0 * 1024.0) << " MB\n"
          << "========================================\n\n";
}

template <typename T>
inline void print_device_array(const T* arr, long size) {
    print_device_array_kernel<<<1, 1>>>(arr, size);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize after print_device_array_kernel");
    std::cout << std::endl;
}

// Function to print the edge list
inline void print_edge_list(uint64_t* edge_list, long numEdges) {
    for (long i = 0; i < numEdges; ++i) {
        uint64_t edge = edge_list[i];
        int u = edge >> 32;          // Extract the upper 32 bits
        int v = edge & 0xFFFFFFFF;   // Extract the lower 32 bits
        std::cout << u << " " << v << std::endl;
    }
}

// CUDA kernel to print the edge list from device memory
template <typename T>
__global__ 
void print_device_edge_list_kernel(T* d_edge_list, long numEdges) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx == 0) {
        for(long i = 0; i < numEdges; ++i) {
            uint64_t edge = d_edge_list[i];
            int u = edge >> 32;          // Extract the upper 32 bits
            int v = edge & 0xFFFFFFFF;   // Extract the lower 32 bits
            printf("%ld: %d %d\n", i, u, v);
        }
    }
}
template <typename T>
void print_device_edges(T* d_edge_list, long numEdges) {
    print_device_edge_list_kernel<<<1,1>>>(d_edge_list, numEdges);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize");
}


// Function to display an edge list from device memory
inline void DisplayDeviceEdgeList(int* d_u, int* d_v, int num_edges) {
    // Allocate host memory for the edges
    int* h_u = new int[num_edges];
    int* h_v = new int[num_edges];

    // Check for memory allocation failure
    if (h_u == nullptr || h_v == nullptr) {
        std::cerr << "Failed to allocate host memory" << std::endl;
        return;
    }

    // Copy the edges from device to host
    CUDA_CHECK(cudaMemcpy(h_u, d_u, sizeof(int) * num_edges, cudaMemcpyDeviceToHost), "Failed to copy back tp cpu");
    CUDA_CHECK(cudaMemcpy(h_v, d_v, sizeof(int) * num_edges, cudaMemcpyDeviceToHost), "Failed to copy back tp cpu");

    // Print the edges
    std::cout << "Edge list:" << std::endl;
    for (int i = 0; i < num_edges; i++) {
        std::cout << i << " :(" << h_u[i] << ", " << h_v[i] << ")" << std::endl;
    }

    // Free host memory
    delete[] h_u;
    delete[] h_v;
}

// Function to find the maximum value using CUB
inline int findMax(const int *d_in, int num_items) {
    // Allocate memory for the result on the device
    int *d_max = nullptr;
    CUDA_CHECK(cudaMalloc(&d_max, sizeof(int)), "Failed to allocate d_max array");

    // Determine temporary device storage requirements
    void *d_temp_storage = nullptr;
    size_t temp_storage_bytes = 0;
    cub::DeviceReduce::Max(d_temp_storage, temp_storage_bytes, d_in, d_max, num_items);

    // Allocate temporary storage
    CUDA_CHECK(cudaMalloc(&d_temp_storage, temp_storage_bytes), "Failed to allocate temp storage array");

    // Run max-reduction
    cub::DeviceReduce::Max(d_temp_storage, temp_storage_bytes, d_in, d_max, num_items);

    // Copy the result back to the host
    int h_max;
    CUDA_CHECK(cudaMemcpy(&h_max, d_max, sizeof(int), cudaMemcpyDeviceToHost), "Failed to copy back h_max array");

    // Cleanup
    CUDA_CHECK(cudaFree(d_temp_storage), "Failed to free d_temp_storage array");
    CUDA_CHECK(cudaFree(d_max), "Failed to free d_max array");

    return h_max; // Return the maximum value
}

#endif // CUDA_UTILITY_CUH