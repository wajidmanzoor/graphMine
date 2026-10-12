#include <iostream>
#include <cmath>
#include <cuda.h>
#include <cuda_runtime.h>

#include "common.hxx"
#include "sparse_table_max.hxx"

#define LOCAL_BLOCK_SIZE 20

using namespace std;

__global__ 
void computeblocks_max(int* d_na, int m , int* d_a, int n){
    //store maximum values of local blocks
    int i = blockIdx.x*blockDim.x + threadIdx.x;
    if(i>=0 && i < m){
        int maxval = INT_MIN;
        for(int j=0; j<LOCAL_BLOCK_SIZE; j++){
            int index = i*LOCAL_BLOCK_SIZE + j;
            if(index < n){
                maxval = max(maxval , d_a[index]);
            }
        }
        d_na[i] = maxval;
    }
}



__global__ 
void preprocess_init_max(int* d_a, int* d_lookupmax, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) {
        d_lookupmax[i] = d_a[i];
    }
}

__global__ 
void build_sparse_table_max(int* d_lookupmax, int k, int i, int threads) {
    int j = blockIdx.x * blockDim.x + threadIdx.x;
    if (j < threads) {
        int index = j + i * k;
        int half_interval = 1 << (i - 1);
        d_lookupmax[index] = max(d_lookupmax[j + (i - 1) * k], d_lookupmax[j + (i - 1) * k + half_interval]);
    }
}

__device__ __host__ __inline__ int log2_floor(int x) {
    if (x <= 0) return -1; // Undefined for non-positive numbers
    int result = 0;
    while (x >>= 1) result++;
    return result;
}

__global__ 
void query_sol_max(int* d_lookupmax, int* d_qleft, int* d_qright, int m, int q, int* d_ansmax, int* d_a , int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < q) {
        int a = d_qleft[i];
        int b = d_qright[i];
        int b_l = b / LOCAL_BLOCK_SIZE;
        int a_l = a / LOCAL_BLOCK_SIZE;
        int n_l,n_r;
        if(a_l == b_l){
            int maxval = INT_MIN;
            for(int j=a; j<=b; j++){
                maxval = max(maxval , d_a[j]);
            }
            d_ansmax[i] = maxval;
        }
        else if(a_l + 1 == b_l){
            int maxval = INT_MIN;
            for(int j=a; j<=b; j++){
                maxval = max(maxval , d_a[j]);
            }
            d_ansmax[i] = maxval;   
        }
        else{
            n_l = a_l + 1;
            n_r = b_l - 1;
            int maxval = INT_MIN;
            for(int j=a; j<(a_l+1)*LOCAL_BLOCK_SIZE; j++){
                maxval = max(maxval , d_a[j]);
            }
            for(int j=b_l*LOCAL_BLOCK_SIZE; j<=b; j++){
                maxval = max(maxval , d_a[j]);
            }
            int len = n_r - n_l + 1;
            int l = log2_floor(len);
            int index1 = n_l + l * m;
            int index2 = n_r - (1 << l) + 1 + l * m;
            maxval = max(maxval , max(d_lookupmax[index1], d_lookupmax[index2]));
            d_ansmax[i] = maxval;
        }
    }
}

void solveQ_max(int m, int* d_na, int q, int* d_left, int* d_right, int* d_ansmax , int* d_a , int n) {
    // mytimer mt{};

    int* d_lookupmax;
    int k = (int)log2(m);

    size_t lookupmax_size = (k + 1) * m * sizeof(int);
    CUDA_CHECK(cudaMalloc(&d_lookupmax, lookupmax_size), "Failed to allocate memory");

    int blocks = (m + 1023) / 1024;
    preprocess_init_max<<<blocks, 1024>>>(d_na, d_lookupmax, m);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize preprocess_init_max kernel");

    int len = 1;
    for (int i = 1; i <= k; i++) {
        len *= 2;
        int threads = m - len + 1;
        blocks = (threads + 1023) / 1024;
        build_sparse_table_max<<<blocks, 1024>>>(d_lookupmax, m, i, threads);
        CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize build_sparse_table_max kernel");
    }

    //mt.timetaken_reset("built table", 1);

    blocks = (q + 1023) / 1024;
    query_sol_max<<<blocks, 1024>>>(d_lookupmax, d_left, d_right, m, q, d_ansmax, d_a , n);
    CUDA_CHECK(cudaDeviceSynchronize(), "Failed to synchronize query_sol_max kernel");

    // CUDA_CHECK(cudaFree(d_lookupmax), "Failed to synchronize");
}

void main_max(int n, int q, int* d_a, int* d_left, int* d_right, int* d_ansmax, int n_asize, int* d_na) {
    
    int blocks = (n_asize + 1023) / 1024;
    computeblocks_max<<<blocks, 1024>>>(d_na, n_asize, d_a, n);

    solveQ_max(n_asize, d_na, q, d_left, d_right, d_ansmax , d_a , n);

}
