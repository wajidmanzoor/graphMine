#include "bfs.cuh"

int totalThreads = 1024;

// #define DEBUG

__global__ 
void simpleBFS(int no_of_vertices, int level, int* d_parents, int* d_levels, long* d_offset, int* d_neighbour, bool* d_changed, int root, int* d_child_of_root) {
    
    int tid = blockIdx.x * blockDim.x + threadIdx.x;

    if (tid < no_of_vertices && d_levels[tid] == level) {
        int u = tid;
        for (long i = d_offset[u]; i < d_offset[u + 1]; i++) {
            int v = d_neighbour[i];
            if(d_levels[v] < 0) {
                d_levels[v] = level + 1;
                d_parents[v] = u;
                *d_changed = true;

                // Use atomicCAS for atomic compare-and-swap
                if (u == root && level == 0) {
                    int expected = -1;
                    atomicCAS(d_child_of_root, expected, v);
                }
            }
        }
    }
}

void constructSpanningTree(int no_of_vertices, long numEdges, long* d_offset, int* d_neighbours, int* d_level, int* d_parent, int root, int& child_of_root) {
    
    bool* d_changed;
    bool changed = true;
    int* d_child_of_root;
    int child = -1; // Initialize to -1 to indicate no child found yet
    CUDA_CHECK(cudaMalloc(&d_child_of_root, sizeof(int)) , "cannot allocate d_child_of_root");
    CUDA_CHECK(cudaMemcpy(d_child_of_root, &child, sizeof(int), cudaMemcpyHostToDevice), "cannot copy child_of_root to gpu");

    CUDA_CHECK(cudaMalloc(&d_changed, sizeof(bool)) , "cannot allocate d_changed");
    int level = 0;

    size_t no_of_blocks = (no_of_vertices + totalThreads - 1) / totalThreads;

    while(changed) {
        changed = false;
        CUDA_CHECK(cudaMemcpy(d_changed, &changed, sizeof(bool), cudaMemcpyHostToDevice) , "cannot copy changed flag to gpu");
        
        simpleBFS<<<no_of_blocks, totalThreads>>>(no_of_vertices, level, d_parent, d_level, d_offset, d_neighbours, d_changed, root, d_child_of_root);
        CUDA_CHECK(cudaMemcpy(&changed, d_changed, sizeof(bool), cudaMemcpyDeviceToHost), "cannot copy changed from gpu");
        ++level;
    }

    CUDA_CHECK(cudaMemcpy(&child_of_root, d_child_of_root, sizeof(int), cudaMemcpyDeviceToHost), "cannot copy child_of_root from gpu");
    CUDA_CHECK(cudaMemcpy(&d_parent[root], &root, sizeof(int), cudaMemcpyHostToDevice), "Failed to set parent of root.");
}
