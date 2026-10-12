#include "bcc_memory_utils.cuh"

#include "timer.hpp"
#include "cuda_utility.cuh"

gpu_bcc::gpu_bcc(int vertices, long edges) : numVert(vertices), numEdges(edges) {
    
    E = 2 * numEdges; // Two times the original edges count

    size_t size = E * sizeof(int);
    size_t vert_size = numVert * sizeof(int);

    Timer myTimer;
    // Allocate memory for original edges
    CUDA_CHECK(cudaMalloc(&original_u, numEdges * sizeof(int)), "Failed to allocate original_u array");
    CUDA_CHECK(cudaMalloc(&original_v, numEdges * sizeof(int)), "Failed to allocate original_v array");

    // csr data-structures
    // Allocate vertices array for edge_offset
    CUDA_CHECK(cudaMalloc(&d_vertices, (numVert + 1) * sizeof(long)), "Failed to allocate vertices array.");
    // Allocate neighbour array
    CUDA_CHECK(cudaMalloc(&d_edges, size), "Failed to allocate u_arr array.");

    // Allocate arrays for spanning tree output
    CUDA_CHECK(cudaMalloc(&d_parent, numVert * sizeof(int)), "Failed to allocate parent array.");
    CUDA_CHECK(cudaMalloc(&d_level,  numVert * sizeof(int)), "Failed to allocate level array.");

    // Allocate arrays for the Fundamental cycle traversal
    CUDA_CHECK(cudaMalloc(&d_isSafe,        vert_size), "Failed to allocate memory for d_isSafe");
    CUDA_CHECK(cudaMalloc(&d_cut_vertex,    vert_size), "Failed to allocate memory for d_cut_vertex");
    CUDA_CHECK(cudaMalloc(&d_imp_bcc_num,   vert_size), "Failed to allocate memory for d_imp_bcc_num");
    CUDA_CHECK(cudaMalloc(&d_isPartofFund,  vert_size), "Failed to allocate memory for d_isPartofFund");
    CUDA_CHECK(cudaMalloc(&d_is_baseVertex, vert_size), "Failed to allocate memory for d_is_baseVertex");
    CUDA_CHECK(cudaMalloc(&d_nonTreeEdgeId, numVert * sizeof(long)), "Failed to allocate memory for d_nonTreeEdgeId");

    // For connected Components
    CUDA_CHECK(cudaMalloc(&d_rep,        vert_size), "Failed to allocate memory for d_rep");
    CUDA_CHECK(cudaMalloc(&d_baseU,      numEdges * sizeof(int)), "Failed to allocate memory for d_baseU");
    CUDA_CHECK(cudaMalloc(&d_baseV,      numEdges * sizeof(int)), "Failed to allocate memory for d_baseV");
    CUDA_CHECK(cudaMalloc(&d_baseVertex, numEdges * sizeof(int)), "Failed to allocate memory for d_baseVertex");

    // Common flag for bfs and cc
    CUDA_CHECK(cudaMalloc(&d_flag,                  sizeof(int)), "Unable to allocate flag value");

    auto dur = myTimer.stop();
    // std::cout <<"Allocation of all device memory took : " << dur << " ms.\n";
    // printMemoryInfo("After all Allocation done");
}

gpu_bcc::~gpu_bcc() {
    // Free allocated memory
    // std::cout <<"\nDestructor started\n";
    Timer myTimer;
    // Original_edge_stream
    CUDA_CHECK(cudaFree(original_u),        "Failed to free original_u array");
    CUDA_CHECK(cudaFree(original_v),        "Failed to free original_v array");

    // csr data-structures
    CUDA_CHECK(cudaFree(d_vertices),        "Failed to free vertices array");
    CUDA_CHECK(cudaFree(d_edges),           "Failed to free u_arr array");

    // BFS output
    CUDA_CHECK(cudaFree(d_parent),          "Failed to free parent array");
    CUDA_CHECK(cudaFree(d_level),           "Failed to free level array");

    // Part of cuda_BCC data-structure
    CUDA_CHECK(cudaFree(d_isSafe),          "Failed to free d_isSafe");
    CUDA_CHECK(cudaFree(d_cut_vertex),      "Failed to free d_cut_vertex");
    CUDA_CHECK(cudaFree(d_imp_bcc_num),     "Failed to free d_imp_bcc_num");
    CUDA_CHECK(cudaFree(d_isPartofFund),    "Failed to free d_isPartofFund");
    CUDA_CHECK(cudaFree(d_is_baseVertex),   "Failed to free d_is_baseVertex");
    CUDA_CHECK(cudaFree(d_nonTreeEdgeId),   "Failed to free d_nonTreeEdgeId");

    // CC
    CUDA_CHECK(cudaFree(d_rep),             "Failed to free d_rep");
    CUDA_CHECK(cudaFree(d_flag),            "Failed to free d_rep");
    CUDA_CHECK(cudaFree(d_baseU),           "Failed to free d_baseU");
    CUDA_CHECK(cudaFree(d_baseV),           "Failed to free d_baseV");
    CUDA_CHECK(cudaFree(d_baseVertex),      "Failed to free d_baseVertex");

    // Resetting the device before exiting
    CUDA_CHECK(cudaDeviceReset(), "          Failed to reset device");

    auto dur = myTimer.stop();
    // std::cout <<"Deallocation of device memory took : " << dur << " ms.\n";
    // std::cout <<"Destructor ended\n";
}

void gpu_bcc::init(int numVert, long num_non_tree_edges) {
    size_t vert_size = numVert * sizeof(int);
    Timer myTimer;
    // Initialize GPU memory
    CUDA_CHECK(cudaMemset(d_level,        -1, vert_size), "Failed to initialize level array.");
    CUDA_CHECK(cudaMemset(d_isSafe,        0, vert_size), "Failed to memset d_isSafe");
    CUDA_CHECK(cudaMemset(d_cut_vertex,    0, vert_size), "Failed to memset d_cut_vertex");
    CUDA_CHECK(cudaMemset(d_isPartofFund,  0, vert_size), "Failed to memset d_isPartofFund");
    CUDA_CHECK(cudaMemset(d_is_baseVertex, 0, vert_size), "Failed to memset d_is_baseVertex");

    auto dur = myTimer.stop();
    // std::cout <<"Initialization of device memory took : " << dur << " ms.\n";
}