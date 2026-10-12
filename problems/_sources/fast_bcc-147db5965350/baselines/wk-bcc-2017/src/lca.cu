#include "timer.hpp"
#include "utility.hpp"

#include "lca.cuh"
#include "bcc_memory_utils.cuh"
#include "connected_components.cuh"

// #define DEBUG

__global__
void find_LCA(long num_non_tree_edges, int* non_tree_u, int* non_tree_v, int* parent, int* distance,
              int* is_marked, int* is_safe, long* nonTreeId, int* base_u, int* base_v, int* baseVertex, int* d_isBaseVertex) {

    long i = blockIdx.x * blockDim.x + threadIdx.x;

    if(i < num_non_tree_edges) {

        int to = non_tree_u[i];
        int from = non_tree_v[i];

        if(parent[to] == from || parent[from] == to) {
            base_u[i] = 0;
            base_v[i] = 0;

            baseVertex[i] = -1;
            return;
        }

        int higher = distance[to] < distance[from] ? to : from;
        int lower = higher == to ? from : to;
        int diff = distance[lower] - distance[higher];

        // Equalize heights
        while (diff--) {

            is_safe[lower] = 1;
            is_marked[lower] = 1;
            nonTreeId[lower] = i;

            lower = parent[lower];
            is_marked[lower] = 1;
        }

        // Mark till LCA is found
        while (parent[lower] != parent[higher]) {

            is_safe[lower] = 1;
            is_marked[lower] = 1;
            nonTreeId[lower] = i;

            lower = parent[lower];

            is_safe[higher] = 1;
            is_marked[higher] = 1;
            nonTreeId[higher] = i;

            higher = parent[higher];
        }

        // Update base vertices
        base_u[i] = lower;
        base_v[i] = higher;

        d_isBaseVertex[lower] = 1;
        d_isBaseVertex[higher] = 1;

        is_marked[lower]  = 1;
        is_marked[higher] = 1;
        
        nonTreeId[lower] = i;
        nonTreeId[higher] = i;

        baseVertex[i] = lower;
    }
}

void naive_lca(gpu_bcc& g_bcc_ds, int root, int child_of_root) {

    int numVert            =    g_bcc_ds.numVert;
    long numNonTreeEdges   =    g_bcc_ds.numEdges;
    
    int *d_rep             =    g_bcc_ds.d_rep;
    int *d_baseU           =    g_bcc_ds.d_baseU;
    int *d_baseV           =    g_bcc_ds.d_baseV;
    int *d_level           =    g_bcc_ds.d_level;
    int *d_parent          =    g_bcc_ds.d_parent; 
    int *d_isSafe          =    g_bcc_ds.d_isSafe;
    int *d_nonTreeEdge_U   =    g_bcc_ds.original_u; 
    int *d_nonTreeEdge_V   =    g_bcc_ds.original_v;
    int *d_baseVertex      =    g_bcc_ds.d_baseVertex;  // Every non - tree edge has an associated base vertex
    int *d_isPartofFund    =    g_bcc_ds.d_isPartofFund;
    int *d_is_baseVertex   =    g_bcc_ds.d_is_baseVertex; // My parent is lca or not
    
    long *d_nonTreeEdgeId  =    g_bcc_ds.d_nonTreeEdgeId;
    
    cudaDeviceProp prop;
    CUDA_CHECK(cudaGetDeviceProperties(&prop, 0), "Failed to get device properties");

    const long threadsPerBlock = prop.maxThreadsPerBlock;
    long numBlocksEdges = (numNonTreeEdges + threadsPerBlock - 1) / threadsPerBlock;
    
    Timer moduleTimer;  
    auto start = std::chrono::high_resolution_clock::now();
    find_LCA<<<numBlocksEdges, threadsPerBlock>>>(
        numNonTreeEdges,     // Input
        d_nonTreeEdge_U,     // Input
        d_nonTreeEdge_V,     // Input
        d_parent,            // Input
        d_level,             // Input

        d_isPartofFund,      // Output
        d_isSafe,            // Output
        d_nonTreeEdgeId,     // Output
        d_baseU,             // Output
        d_baseV,             // Output
        d_baseVertex,        // Output
        d_is_baseVertex      // Output
    );

    CUDA_CHECK(cudaGetLastError(), "find_LCA Kernel launch failed");
    CUDA_CHECK(cudaDeviceSynchronize(), "Error during cudaDeviceSynchronize()");
    
    auto end = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
    std::cout <<"Fundamental cycle traversal took: " << duration <<" ms\n";

    #ifdef DEBUG
        size_t vert_size           = numVert * sizeof(int);
        size_t non_tree_edges_size = numNonTreeEdges * sizeof(int);
        std::vector<int> host_baseU(numNonTreeEdges);
        std::vector<int> host_baseV(numNonTreeEdges);
        
        CUDA_CHECK(cudaMemcpy(host_baseU.data(), d_baseU, non_tree_edges_size, cudaMemcpyDeviceToHost), "Failed to copy d_lca_u to host");
        CUDA_CHECK(cudaMemcpy(host_baseV.data(), d_baseV, non_tree_edges_size, cudaMemcpyDeviceToHost), "Failed to copy d_lca_v to host");

        // Host vectors
        std::vector<int> host_isPartofFund(numVert), host_isSafe(numVert),host_nonTreeEdgeId(numVert), host_baseVertex(numNonTreeEdges),host_isBaseVertex(numVert);

        // Copying data from device to host
        CUDA_CHECK(cudaMemcpy(host_isPartofFund.data(),  d_isPartofFund,  vert_size, cudaMemcpyDeviceToHost), "Failed to copy d_isPartofFund to host");
        CUDA_CHECK(cudaMemcpy(host_isSafe.data(),        d_isSafe,        vert_size, cudaMemcpyDeviceToHost), "Failed to copy d_isSafe to host");
        CUDA_CHECK(cudaMemcpy(host_nonTreeEdgeId.data(), d_nonTreeEdgeId, vert_size, cudaMemcpyDeviceToHost), "Failed to copy d_nonTreeEdgeId to host");
        CUDA_CHECK(cudaMemcpy(host_isBaseVertex.data(),  d_is_baseVertex, vert_size, cudaMemcpyDeviceToHost), "Failed to copy d_isBaseVertex to host");
        CUDA_CHECK(cudaMemcpy(host_baseVertex.data(),    d_baseVertex, non_tree_edges_size, cudaMemcpyDeviceToHost), "Failed to copy d_baseVertex to host");

        // Print the data
        print_vector(host_baseU, "Base U");
        print_vector(host_baseV, "Base V");
        
        print(host_isPartofFund, "isPartOfFund");
        print(host_isSafe, "isSafe");
        print_vector(host_nonTreeEdgeId, "Non Tree Edge ID");
        print_vector(host_baseVertex, "Base Vertex");
        print(host_isBaseVertex, "isBaseVertex");
    #endif

    moduleTimer.reset();
    start = std::chrono::high_resolution_clock::now();
    // call cc 
    connected_comp(numNonTreeEdges, d_baseU, d_baseV, numVert, d_rep, g_bcc_ds.d_flag);

    end = std::chrono::high_resolution_clock::now();
    duration = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
    std::cout <<"Last cc took: " << duration <<" ms\n";

    #ifdef DEBUG
        std::cout << "\ncc output:";
        std::vector<int> host_rep(numVert);
        CUDA_CHECK(cudaMemcpy(host_rep.data(), d_rep, vert_size, cudaMemcpyDeviceToHost), "Failed to copy d_rep to host");
        // Print the data
        print(host_rep, "host rep");
    #endif
}
