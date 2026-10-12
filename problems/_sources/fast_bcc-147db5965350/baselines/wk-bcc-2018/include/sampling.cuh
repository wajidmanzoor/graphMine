#ifndef SAMPLING_CUH
#define SAMPLING_CUH

#include <tuple>
#include "gpu_csr.cuh"

std::tuple<long*, int*, int*, int*, long> k_out_sampling(long* d_row_offsets, 
    uint64_t* d_edgelist,
    int num_vert, 
    long num_edges, 
    int k);

#endif // SAMPLING_CUH