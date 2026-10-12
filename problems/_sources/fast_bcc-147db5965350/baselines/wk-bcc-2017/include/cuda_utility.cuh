#ifndef CUDA_UTILITY_H
#define CUDA_UTILITY_H

#include <iostream>
#include <string>
#include <cuda_runtime.h>

inline void check_for_error(cudaError_t error, const std::string& message, const std::string& file, int line) noexcept {
    if (error != cudaSuccess) {
        std::cerr << "CUDA Error at " << file << ":" << line << " - " << message << "\n";
        std::cerr << "CUDA Error description: " << cudaGetErrorString(error) << "\n";
        std::exit(EXIT_FAILURE);
    }
}

#define CUDA_CHECK(err, msg) check_for_error(err, msg, __FILE__, __LINE__)

// Function to print available and total memory
inline void printMemoryInfo(const std::string& message) {
    size_t free_byte;
    size_t total_byte;
    cudaError_t cuda_status = cudaMemGetInfo(&free_byte, &total_byte);

    if (cudaSuccess != cuda_status) {
        printf("Error: cudaMemGetInfo fails, %s \n", cudaGetErrorString(cuda_status));
        exit(1);
    }

    double free_db = (double)free_byte;
    double total_db = (double)total_byte;
    double used_db = total_db - free_db;
    std::cout << message << ": Used GPU memory: " 
        << used_db / (1024.0 * 1024.0) << " MB, Free GPU Memory: " 
        << free_db / (1024.0 * 1024.0) << " MB, Total GPU Memory: " 
        << total_db / (1024.0 * 1024.0) << " MB" << std::endl;

}

#endif // CUDA_UTILITY_H