#include <vector>
#include <iostream>
#include <cuda_runtime.h>

#include "include/util.cuh"
#include "include/list_ranking.cuh"

__global__
void initRankNext(unsigned long long *devRankNext, const int *devNext, int N) {
    int thid = blockIdx.x * blockDim.x + threadIdx.x;
    if (thid < N) {
        devRankNext[thid] = (((unsigned long long)0) << 32) + devNext[thid] + 1;
    }
}

__global__ 
void updateRankNext(int loopsWithoutSync, unsigned long long *devRankNext, int *devNotAllDone, int N) {
    int thid = blockIdx.x * blockDim.x + threadIdx.x;
    
    if (thid < N) {

        unsigned long long rankNext = devRankNext[thid];
        for (int i = 0; i < loopsWithoutSync; i++) {
            if (thid == 0) 
                *devNotAllDone = 0;

            int rank = rankNext >> 32;
            int nxt = rankNext - 1;

            if (nxt != -1) {
                unsigned long long grandNext = devRankNext[nxt];

                rank += (grandNext >> 32) + 1;
                nxt = grandNext - 1;

                rankNext = (((unsigned long long)rank) << 32) + nxt + 1;
                atomicExch(devRankNext + thid, rankNext);

                if (i == loopsWithoutSync - 1) {
                    *devNotAllDone = 1;
                }
            }
        }
    }
}

__global__ 
void extractHighBits(const unsigned long long *devRankNext, int *devRank, int N) {
    int thid = blockIdx.x * blockDim.x + threadIdx.x;
    if (thid < N) {
        devRank[thid] = devRankNext[thid] >> 32;  // Shift right by 32 bits to get the high part
    }
}

// param: int *devNext is the input array 
// param: int *devRank is the output array 
// param: int N is the size of input array
void CudaSimpleListRank(int *devRank, int N, int *devNext) {

    int *notAllDone;
    cudaMallocHost(&notAllDone, sizeof(int));

    ull *devRankNext;
    int *devNotAllDone;

    CUCHECK(cudaMalloc((void **)&devRankNext, sizeof(ull) * N));
    CUCHECK(cudaMalloc((void **)&devNotAllDone, sizeof(int)));

    int threadsPerBlock = 1024; // This can be tuned based on your device capabilities
    int numBlocks = (N + threadsPerBlock - 1) / threadsPerBlock;

    // Initialize devRankNext with initRankNext kernel
    initRankNext<<<numBlocks, threadsPerBlock>>>(devRankNext, devNext, N);
    CUCHECK(cudaDeviceSynchronize());
    const int loopsWithoutSync = 5;

    do {
        updateRankNext<<<numBlocks, threadsPerBlock>>>(loopsWithoutSync, devRankNext, devNotAllDone, N);
        CUCHECK(cudaDeviceSynchronize());
        CUCHECK(cudaMemcpy(notAllDone, devNotAllDone, sizeof(int), cudaMemcpyDeviceToHost));
    } while (*notAllDone);

    // Launch the kernel
    extractHighBits<<<numBlocks, threadsPerBlock>>>(devRankNext, devRank, N);
    CUCHECK(cudaDeviceSynchronize());

    // Free the memory
    CUCHECK(cudaFree(devRankNext));
    CUCHECK(cudaFree(devNotAllDone));
    CUCHECK(cudaFreeHost(notAllDone));
}