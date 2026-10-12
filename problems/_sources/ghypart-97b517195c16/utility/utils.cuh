#pragma once
#include "../include/graph.h"
#include <bits/stdc++.h>
#include <chrono>
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/execution_policy.h>
#include <cusparse.h>
#include <stdlib.h>

#define UP_DIV(n, a)    (n + a - 1) / a
#define ROUND_UP(n, a)  UP_DIV(n, a) * a

// error macro
#define CHECK_ERROR(err)    checkCudaError(err, __FILE__, __LINE__)
#define GET_LAST_ERR()      getCudaLastErr(__FILE__, __LINE__)

inline void getCudaLastErr(const char *file, const int line) {
    cudaError_t err;
    if ((err = cudaGetLastError()) != cudaSuccess) {
        std::cerr << "CUDA error: " << file << "(" << line << "): " << cudaGetErrorString(err) << "\n";
        exit(EXIT_FAILURE);
    }
}

inline void checkCudaError(cudaError_t err, const char *file, const int line) {
    if (err != cudaSuccess) {
        std::cerr << "CUDA error: " << file << "(" << line << "): " << cudaGetErrorString(err) << "\n";
        exit(EXIT_FAILURE);
    }
}

// convenient timers
#define TIMERSTART(label)                                                    \
        cudaSetDevice(0);                                                    \
        cudaEvent_t start##label, stop##label;                               \
        float time##label;                                                   \
        cudaEventCreate(&start##label);                                      \
        cudaEventCreate(&stop##label);                                       \
        cudaEventRecord(start##label, 0);

#define TIMERSTOP(label)                                                     \
        cudaSetDevice(0);                                                    \
        cudaEventRecord(stop##label, 0);                                     \
        cudaEventSynchronize(stop##label);                                   \
        cudaEventElapsedTime(&time##label, start##label, stop##label);       \
        std::cout << "kernel execution time: #" << time##label                                      \
                  << " ms (" << #label << ")" << std::endl;

#define CHECK_CUDA(func)                                                       \
{                                                                              \
    cudaError_t status = (func);                                               \
    if (status != cudaSuccess) {                                               \
        printf("CUDA API failed at line %d with error: %s (%d)\n",             \
               __LINE__, cudaGetErrorString(status), status);                  \
        return EXIT_FAILURE;                                                   \
    }                                                                          \
}

// #define CHECK_CUSPARSE(func)                                                   \
// {                                                                              \
//     cusparseStatus_t status = (func);                                          \
//     if (status != CUSPARSE_STATUS_SUCCESS) {                                   \
//         printf("CUSPARSE API failed at line %d with error: %s (%d)\n",         \
//                __LINE__, cusparseGetErrorString(status), status);              \
//         return EXIT_FAILURE;                                                   \
//     }                                                                          \
// }

#define CHECK_CUSPARSE(status)     checkCuSparse(status, __FILE__, __LINE__)
inline void checkCuSparse(cusparseStatus_t status, const char *file, const int line) {
    if (status != CUSPARSE_STATUS_SUCCESS) {
        std::cerr << "CUDA error: " << file << "(" << line << "): " << cusparseGetErrorString(status) << "\n";
        exit(EXIT_FAILURE);
    }
}

int computeHyperedgeCut(Hypergraph* hgr, bool useUVM = true);

void printBalanceResult(Hypergraph* hgr, int numPartitions, float imbalance, bool useUVM = true);

void computeBalanceResult(Hypergraph* hgr, int numPartitions, float imbalance, std::vector<int>& parts, bool useUVM = true);

void allocTempData(Auxillary* aux, Hypergraph* hgr);

void deallocTempData(Auxillary* aux);

bool isPowerOfTwo(int x);
