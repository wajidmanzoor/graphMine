#include <iostream>
#include <cmath>
#include <cuda.h>
#include <cuda_runtime.h>

#include "sparse_table_min.hxx"
#include "common.hxx"

#define LOCAL_BLOCK_SIZE 20

using namespace std;

__global__ 
void computeblocks_min(int* d_na, int m , int* d_a, int n){
    //store minimum values of local blocks
    int i = blockIdx.x*blockDim.x + threadIdx.x;
    if(i>=0 && i < m){
        int minval = INT_MAX;
        for(int j=0; j<LOCAL_BLOCK_SIZE; j++){
            int index = i*LOCAL_BLOCK_SIZE + j;
            if(index < n){
                minval = min(minval , d_a[index]);
            }
        }
        d_na[i] = minval;
    }
}

__global__ 
void preprocess_init_min(int* d_a, int* d_lookupmin, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) {
        d_lookupmin[i] = d_a[i];
    }
}

__global__ 
void build_sparse_table_min(int* d_lookupmin, int k, int i, int threads) {
    int j = blockIdx.x * blockDim.x + threadIdx.x;
    if (j < threads) {
        int index = j + i * k;
        int half_interval = 1 << (i - 1);
        d_lookupmin[index] = min(d_lookupmin[j + (i - 1) * k], d_lookupmin[j + (i - 1) * k + half_interval]);
    }
}

__device__ __host__ __inline__ int log2_floor(int x) {
    if (x <= 0) return -1; // Undefined for non-positive numbers
    int result = 0;
    while (x >>= 1) result++;
    return result;
}


__global__ 
void query_sol_min(int* d_lookupmin, int* d_qleft, int* d_qright, int m, int q, int* d_ansmin, int* d_a , int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < q) {
        int a = d_qleft[i];
        int b = d_qright[i];
        int b_l = b / LOCAL_BLOCK_SIZE;
        int a_l = a / LOCAL_BLOCK_SIZE;
        int n_l,n_r;
        if(a_l == b_l){
            int minval = INT_MAX;
            for(int j=a; j<=b; j++){
                minval = min(minval , d_a[j]);
            }
            d_ansmin[i] = minval;
        }
        else if(a_l + 1 == b_l){
            int minval = INT_MAX;
            for(int j=a; j<=b; j++){
                minval = min(minval , d_a[j]);
            }
            d_ansmin[i] = minval;   
        }
        else{
            n_l = a_l + 1;
            n_r = b_l - 1;
            int minval = INT_MAX;
            for(int j=a; j<(a_l+1)*LOCAL_BLOCK_SIZE; j++){
                minval = min(minval , d_a[j]);
            }
            for(int j=b_l*LOCAL_BLOCK_SIZE; j<=b; j++){
                minval = min(minval , d_a[j]);
            }
            int len = n_r - n_l + 1;
            // int l = (int)log2(len);
            int l = log2_floor(len);
            int index1 = n_l + l * m;
            int index2 = n_r - (1 << l) + 1 + l * m;
            minval = min(minval , min(d_lookupmin[index1], d_lookupmin[index2]));
            d_ansmin[i] = minval;
        }
    }
}

void solveQ_min(int m, int* d_na, int q, int* d_left, int* d_right, int* d_ansmin , int* d_a , int n) {
    // mytimer mt{};

    int* d_lookupmin;
    int k = (int)log2(m);

    size_t lookupmin_size = (k + 1) * m * sizeof(int);
    CUDA_CHECK(cudaMalloc(&d_lookupmin, lookupmin_size), "Failed to allocate d_lookupmin");

    //mt.timetaken_reset("alloc", 0);

    int blocks = (m + 1023) / 1024;
    preprocess_init_min<<<blocks, 1024>>>(d_na, d_lookupmin, m);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize preprocess_init_min");

    int len = 1;
    for (int i = 1; i <= k; i++) {
        len *= 2;
        int threads = m - len + 1;
        blocks = (threads + 1023) / 1024;
        build_sparse_table_min<<<blocks, 1024>>>(d_lookupmin, m, i, threads);
        CUDA_CHECK(cudaDeviceSynchronize(), "Failed to build_sparse_table_min");
    }

    //mt.timetaken_reset("built table", 1);

    blocks = (q + 1023) / 1024;
    query_sol_min<<<blocks, 1024>>>(d_lookupmin, d_left, d_right, m, q, d_ansmin, d_a , n);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize query_sol_min kernel");

    // CUDA_CHECK(cudaFree(d_lookupmin));
}

void main_min(int n, int q, int* d_a , int* d_left , int* d_right , int* d_ansmin , int n_asize , int* d_na){

    int blocks = (n_asize + 1023) / 1024;
    computeblocks_min<<<blocks, 1024>>>(d_na, n_asize, d_a, n);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize computeblocks_min kernel");
    solveQ_min(n_asize, d_na, q, d_left, d_right, d_ansmin , d_a , n );
}
