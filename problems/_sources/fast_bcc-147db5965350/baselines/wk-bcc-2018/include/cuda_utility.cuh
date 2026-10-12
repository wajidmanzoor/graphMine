/******************************************************************************
* Functionality: GPU related Utility manager
 ******************************************************************************/

#ifndef CUDA_UTILITY_H
#define CUDA_UTILITY_H

//---------------------------------------------------------------------
// Standard Libraries
//---------------------------------------------------------------------
#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <unordered_map>
#include <algorithm>
#include <chrono>
#include <iomanip>
#include <cub/cub.cuh>
#include <cuda_runtime.h>

//---------------------------------------------------------------------
// Globals, constants and typedefs
//---------------------------------------------------------------------
extern bool checker;
extern bool g_verbose;
extern long maxThreadsPerBlock;

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


inline bool CompareDeviceResults(int *host_data, int *device_data, int num_items, bool verbose) {
    int *device_data_host = new int[num_items];
    cudaMemcpy(device_data_host, device_data, num_items * sizeof(int), cudaMemcpyDeviceToHost);

    for (int i = 0; i < num_items; i++) {
        if (host_data[i] != device_data_host[i]) {
            if (verbose) {
                printf("Mismatch at %d: Host: %d, Device: %d\n", i, host_data[i], device_data_host[i]);
            }
            delete[] device_data_host;
            return false;
        }
    }

    delete[] device_data_host;
    return true;
}

template<typename T>
inline void DisplayDeviceArray(T *device_data, size_t num_items) {
    // Allocate memory for host data
    T *host_data = new T[num_items];

    // Copy data from device to host using the specified stream (default is stream 0, which is the default stream)
    cudaMemcpy(host_data, device_data, num_items * sizeof(T), cudaMemcpyDeviceToHost);

    // Wait for the cudaMemcpyAsync to complete
    cudaDeviceSynchronize();

    // Display the data
    for (size_t i = 0; i < num_items; ++i) {
        std::cout << "Data[" << i << "]: " << host_data[i] << "\n";
    }

    // Free host memory
    delete[] host_data;
}

template<typename T>
inline void DisplayDeviceArray(T *device_data, size_t num_items, const std::string& display_name) {
    std::cout << "\n" << display_name << " starts" << "\n";

    // Allocate memory for host data
    T *host_data = new T[num_items];

    // Copy data from device to host using the specified stream (default is stream 0, which is the default stream)
    cudaMemcpy(host_data, device_data, num_items * sizeof(T), cudaMemcpyDeviceToHost);

    // Wait for the cudaMemcpyAsync to complete
    cudaDeviceSynchronize();

    // Display the data
    for (size_t i = 0; i < num_items; ++i) {
        std::cout << "[" << i << "]: " << host_data[i] << "\n";
    }

    // Free host memory
    delete[] host_data;
}

// Renamed and combined function to display edge list from device arrays
inline void DisplayDeviceEdgeList(const int *device_u, const int *device_v, size_t num_edges) {
    std::cout << "\n" << "Edge List:" << "\n";
    int *host_u = new int[num_edges];
    int *host_v = new int[num_edges];
    cudaMemcpy(host_u, device_u, num_edges * sizeof(int), cudaMemcpyDeviceToHost);
    cudaMemcpy(host_v, device_v, num_edges * sizeof(int), cudaMemcpyDeviceToHost);
    cudaDeviceSynchronize();
    for (size_t i = 0; i < num_edges; ++i) {
        std::cout << " Edge[" << i << "]: (" << host_u[i] << ", " << host_v[i] << ")" << "\n";
    }
    delete[] host_u;
    delete[] host_v;
}

inline void WriteDeviceEdgeList(const int *device_u, const int *device_v, size_t num_vert, size_t num_edges = 0) {
    std::cout <<"Started writing to file :\n";
    std::string filename = "temp.txt";
    std::ofstream outFile(filename);
    
    if(!outFile) {
        std::cerr <<"Unable to create file.\n";
        exit(0);
    }

    // std::cout << std::endl << "Edge List:" << std::endl;
    int *host_u = new int[num_edges];
    int *host_v = new int[num_edges];

    cudaMemcpy(host_u, device_u, num_edges * sizeof(int), cudaMemcpyDeviceToHost);
    cudaMemcpy(host_v, device_v, num_edges * sizeof(int), cudaMemcpyDeviceToHost);
    cudaDeviceSynchronize();

    outFile << num_vert <<" " << num_edges << "\n";
    for (size_t i = 0; i < num_edges; ++i) {
        outFile << host_u[i] <<" " << host_v[i] << "\n";
    }
    delete[] host_u;
    delete[] host_v;

    std::cout <<"Writing to file over.\n";
}

// Function to print edge list from std::vector
inline void DisplayEdgeList(const std::vector<int>& u, const std::vector<int>& v) {
    std::cout << "\n" << "Edge List:" << "\n";
    size_t num_edges = u.size();
    for (size_t i = 0; i < num_edges; ++i) {
        std::cout << " Edge[" << i << "]: (" << u[i] << ", " << v[i] << ")" << "\n";
    }
}

// Declaration of kernel wrapper functions
void kernelPrintEdgeList(int* d_u_arr, int* d_v_arr, long numEdges);
void kernelPrintArray(int* d_arr, int numItems);
void kernelPrintCSRUnweighted(long* d_rowPtr, int* d_colIdx, int numRows);

// Ensure function_times exists only once per translation unit
inline std::unordered_map<std::string, double>& function_times() {
    static std::unordered_map<std::string, double> times;
    return times;
}

// Function to add execution time for a function
inline void add_function_time(const std::string& function_name, double time) {
    function_times()[function_name] += time;
}

// Function to print execution times
inline void print_total_function_time(const std::string& function_name) {
    double total_time = 0;
    for (const auto& pair : function_times()) {
        total_time += pair.second;
    }
    
    std::cout << "\nTotal execution time for " << function_name << ": " << total_time << " ms.\n";

    // Convert unordered_map to a vector for sorting
    std::vector<std::pair<std::string, double>> sorted_times(
        function_times().begin(), function_times().end()
    );

    // Sort by execution time in descending order
    std::sort(sorted_times.begin(), sorted_times.end(), [](const auto& a, const auto& b) {
        return a.second > b.second;
    });

    std::cout << "\nFunction execution times:\n";
    for (const auto& pair : sorted_times) {
        std::cout << std::fixed << std::setprecision(2)
                  << "Time of " << pair.first << " : " << pair.second << " ms\n";
    }
    std::cout << std::endl;
}

template <typename T>
__global__ void fill_kernel(T* data, size_t n, T value) {
    size_t i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) {
        data[i] = value;
    }
}

// RAII wrapper for device memory.
// Usage examples:
/*
    Example 1: Create a device vector and use it
    d_vector<int> d_arr(1000);  // Allocate 1000 integers on device
    Automatically freed when d_arr goes out of scope

    // Example 2: Create with initialization
    d_vector<float> d_data(500, 0.0f);  // Allocate and initialize to 0.0

    // Example 3: Transfer ownership (move semantics)
    d_vector<int> d_temp(100);
    d_vector<int> d_final = std::move(d_temp);  // d_temp is now empty, d_final owns the memory

    // Example 4: Release ownership (don't auto-free)
    int* raw_ptr = d_arr.release();  // Caller is now responsible for freeing
    // ...
    cudaFree(raw_ptr);

    // Example 5: Print device array contents
    d_vector<int> d_result(100);
    d_result.print("My Array");  // Prints all elements after copying to host
*/
  
template<typename T>
class d_vector {
public:
    explicit d_vector(size_t count) : count_(count), ptr_(nullptr) {
        CUDA_CHECK(cudaMalloc((void**)&ptr_, sizeof(T) * count_), "Allocation failed");
    }

    explicit d_vector(size_t count, T init_val) : count_(count), ptr_(nullptr) {
        CUDA_CHECK(cudaMalloc((void**)&ptr_, sizeof(T) * count_), "Allocation failed");

        if (init_val == T{}) {
            CUDA_CHECK(cudaMemset(ptr_, 0, sizeof(T) * count_), "Memset failed");
        } else {
            const int threads = 1024;
            const int blocks  = (count_ + threads - 1) / threads;
            fill_kernel<<<blocks, threads>>>(ptr_, count_, init_val);
            CUDA_CHECK(cudaGetLastError(), "fill_kernel launch failed");
        }
    }

    // Delete copy constructor and assignment operator.
    d_vector(const d_vector&) = delete;
    d_vector& operator=(const d_vector&) = delete;

    // Allow move semantics.
    d_vector(d_vector&& other) noexcept
        : count_(other.count_), ptr_(other.ptr_) {
        other.ptr_ = nullptr;
    }

    d_vector& operator=(d_vector&& other) noexcept {
        if (this != &other) {
            if (ptr_) {
                cudaFree(ptr_);
            }
            count_ = other.count_;
            ptr_ = other.ptr_;
            other.ptr_ = nullptr;
        }
        return *this;
    }

    ~d_vector() {
        if (ptr_) {
            cudaFree(ptr_);
        }
    }

    // Get the raw pointer.
    T* get() const { return ptr_; }

    // Get the size of the allocated array.
    size_t size() const { return count_; }

    // Release ownership so the raw pointer is returned and will not be freed.
    T* release() {
        T* temp = ptr_;
        ptr_ = nullptr;
        return temp;
    }

    // Print the contents of the device array.
    // This function copies the data from device to host and prints it.
    void print(const char* label = "Device Array") const {
        if (count_ == 0) {
            std::cout << label << ": [empty]" << std::endl;
            return;
        }
        // Allocate host memory.
        T* hostData = new T[count_];
        CUDA_CHECK(cudaMemcpy(hostData, ptr_, count_ * sizeof(T), cudaMemcpyDeviceToHost),
                   "Failed to copy data from device");
        std::cout << label << " (" << count_ << " elements):" << std::endl;
        for (size_t i = 0; i < count_; i++) {
            std::cout << label << "[" << i << "] = " << hostData[i] << "\n";
        }
        std::cout << std::endl;
        delete[] hostData;
    }

private:
    size_t count_;
    T* ptr_;
};

//---------------------------------------------------------------------
// Timer Class for Performance Measurement
//---------------------------------------------------------------------
class Timer {
public:
    Timer() : start_time_(std::chrono::high_resolution_clock::now()) {}
    
    ~Timer() = default;
    
    double elapsed() const {
        auto end_time = std::chrono::high_resolution_clock::now();
        return std::chrono::duration<double>(end_time - start_time_).count();
    }
    
    void reset() {
        start_time_ = std::chrono::high_resolution_clock::now();
    }

private:
    std::chrono::high_resolution_clock::time_point start_time_;
};

#endif // CUDA_UTILITY_H
