#ifndef COMMON_CXX
#define COMMON_CXX

#include <vector>
#include <iostream>
#include <algorithm>
#include <iomanip>
#include <cstring>
#include <unordered_map>

#include <cuda_runtime.h>

// Macro to check CUDA calls.
#define CUDA_CHECK(call, message)                                  \
    do {                                                           \
        cudaError_t err = call;                                    \
        if (err != cudaSuccess) {                                  \
            std::cerr << "CUDA Error: " << message                 \
                      << " - " << cudaGetErrorString(err)          \
                      << std::endl;                                \
            exit(EXIT_FAILURE);                                    \
        }                                                          \
    } while (0)

#define ERR std::cerr << "err" << std::endl;
#define CEIL(a, b) (((a) + (b) - 1) / (b))

typedef long long ll;
typedef unsigned long long ull;

// RAII wrapper for device memory.
template<typename T>
class d_vector {
public:
    explicit d_vector(size_t count) : count_(count), ptr_(nullptr) {
        CUDA_CHECK(cudaMallocManaged((void**)&ptr_, sizeof(T) * count_), "Allocation failed");
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
        
        CUDA_CHECK(cudaDeviceSynchronize(), "Failed to sync before host read");
        std::memcpy(hostData, ptr_, count_ * sizeof(T));

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

// A simple class to hold graph data.
class graph_data {
public:
    int       V;          // number of vertices
    long      E;          // number of edges
    int       root = -1;
    int      *parent;     // Spanning Tree parent array
    int      *first;      // For first occurrence, etc.
    int      *last;       // For last occurrence, etc.
    int      *flag;       // For identifying fence and back edges
    int      *label;      // Final BCC Labels
    int      *comp_head;  // Components Head array
    uint64_t *edgelist;   // Graph edges

    // Constructor
    graph_data() : parent(nullptr), first(nullptr), last(nullptr),
                   flag(nullptr), label(nullptr), comp_head(nullptr),
                   edgelist(nullptr) {}

    // Destructor: Free all allocated device memory
    ~graph_data() {
        if (parent)    CUDA_CHECK(cudaFree(parent), "Failed to free parent");
        if (first)     CUDA_CHECK(cudaFree(first),  "Failed to free first");
        if (last)      CUDA_CHECK(cudaFree(last),   "Failed to free last");
        if (flag)      CUDA_CHECK(cudaFree(flag),   "Failed to free flag");
        if (label)     CUDA_CHECK(cudaFree(label),  "Failed to free label");
        if (comp_head) CUDA_CHECK(cudaFree(comp_head), "Failed to free comp_head");
        if (edgelist)  CUDA_CHECK(cudaFree(edgelist), "Failed to free edgelist");
    }
};

// Helper function to print device edges.
// Note the conventional ordering: inline void function_name(...)
inline void print_device_edges(uint64_t* d_edges, long count, const char* label = "Device Edges") {
    // Allocate host memory.
    uint64_t* edges_host = (uint64_t*)std::malloc(count * sizeof(uint64_t));
    if (!edges_host) {
        std::cerr << "Failed to allocate host memory!" << std::endl;
        return;
    }

    // Copy data from device to host.
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to sync before host read");
    std::memcpy(edges_host, d_edges, count * sizeof(uint64_t));
 
    // Print values.
    std::cout << label << ":" << std::endl;
    for (long i = 0; i < count; i++) {
        int u = edges_host[i] >> 32;         // Extract the upper 32 bits.
        int v = edges_host[i] & 0xFFFFFFFF;    // Extract the lower 32 bits.
        std::cout << label << "[" << i << "] = " << u << " " << v << std::endl;
    }

    // Free host memory.
    std::free(edges_host);
}

// ------------------------
// CudaTimer Wrapper
// ------------------------
class CudaTimer {
public:
    CudaTimer() {
        CUDA_CHECK(cudaEventCreate(&start_timer), "Failed to create start event");
        CUDA_CHECK(cudaEventCreate(&stop_timer), "Failed to create stop event");
    }
    ~CudaTimer() {
        cudaEventDestroy(start_timer);
        cudaEventDestroy(stop_timer);
    }
    // Record the start event.
    void start() {
        CUDA_CHECK(cudaEventRecord(start_timer, 0), "Failed to record start event");
    }
    // Record the stop event and synchronize.
    float stop() {
        CUDA_CHECK(cudaEventRecord(stop_timer, 0), "Failed to record stop event");
        CUDA_CHECK(cudaEventSynchronize(stop_timer), "Failed to synchronize stop event");
        float ms;
        CUDA_CHECK(cudaEventElapsedTime(&ms, start_timer, stop_timer), "Failed to compute elapsed time");
        return ms;
    }
private:
    cudaEvent_t start_timer;
    cudaEvent_t stop_timer;
};

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

#endif // COMMON_CXX
