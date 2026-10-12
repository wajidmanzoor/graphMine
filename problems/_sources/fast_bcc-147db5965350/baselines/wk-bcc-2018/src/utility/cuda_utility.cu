#include "cuda_utility.cuh"

//---------------------------------------------------------------------
// Global Variable Definitions
//---------------------------------------------------------------------
bool checker = false;
bool g_verbose = false;
long maxThreadsPerBlock = 1024;

/* Declaring the kernel function as static to limit its scope to this translation unit.
    This prevents linkage issues (e.g., multiple definition errors) when the same kernel
    might be included or compiled in different parts of the project. */

__global__ 
void print_edge_list(int* u_arr, int* v_arr, long numEdges) {
    if (threadIdx.x == 0 && blockIdx.x == 0) {
        printf("\nInside print_edge_list kernel.\n");
        for(int i = 0; i < numEdges; ++i) {
            printf("Edge %d: (%d, %d)\n", i, u_arr[i], v_arr[i]);
        }
    }
}

/* Using static for the same reason as above, to keep the function's linkage internal
    to this compilation unit, avoiding conflicts with other similarly named global functions. */

__global__ 
void print_array(int* arr, int numItems) {
    if (threadIdx.x == 0 && blockIdx.x == 0) {
        for (int i = 0; i < numItems; ++i) {
            printf("arr[%d] = %d \n",i, arr[i]);
        }
        printf("\n");
    }
}

__global__ 
void print_csr_unweighted(long* rowPtr, int* colIdx, int numRows) {
    // Ensure only a single thread does the printing
    if (threadIdx.x == 0 && blockIdx.x == 0) {
        for (int i = 0; i < numRows; ++i) {
            printf("Node %d is connected to: ", i);
            for (long j = rowPtr[i]; j < rowPtr[i + 1]; ++j) {
                printf("%d ", colIdx[j]);
            }
            printf("\n");
        }
    }
}

void kernelPrintEdgeList(int* d_u_arr, int* d_v_arr, long numEdges) {
    print_edge_list<<<1, 1>>>(d_u_arr, d_v_arr, numEdges);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize print_edge_list");
}

void kernelPrintArray(int* d_arr, int numItems) {
    print_array<<<1, 1>>>(d_arr, numItems);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize print_array");
}

void kernelPrintCSRUnweighted(long* d_rowPtr, int* d_colIdx, int numRows) {
    print_csr_unweighted<<<1, 1>>>(d_rowPtr, d_colIdx, numRows);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize print_csr_unweighted");
}
