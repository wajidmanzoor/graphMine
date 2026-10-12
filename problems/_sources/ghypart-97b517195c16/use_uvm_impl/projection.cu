#include <iostream>
#include "utility/utils.cuh"
#include "include/projection.cuh"
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/sort.h>
#include <thrust/execution_policy.h>
#include <sys/time.h>
#include <algorithm>
#include <bits/stdc++.h>

// int computeHyperedgeCuts(Hypergraph* hgr) {
//     int count = 0;
//     for (int i = 0; i < hgr->hedgeNum; ++i) {
//         std::set<unsigned> partitions;
//         for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
//             unsigned part = hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j] - hgr->hedgeNum + N_PARTITION(hgr)];
//             partitions.insert(part);
//         }
//         count += partitions.size() - 1;
//     }
//     return count;
// }

__global__ void projection(Hypergraph* coarsenHgr, Hypergraph* fineHgr) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < fineHgr->nodeNum) {
        unsigned parent = fineHgr->nodes[tid + N_PARENT(fineHgr)];
        fineHgr->nodes[tid + N_PARTITION(fineHgr)] = coarsenHgr->nodes[parent - coarsenHgr->hedgeNum + N_PARTITION(coarsenHgr)];
    }
}

void projectPartition(Hypergraph* coarsenHgr, Hypergraph* fineHgr, float& time, float& cur, int cur_iter) {
    std::cout << __FUNCTION__ << "()===========\n";
    int blocksize = 128;
    int gridsize = UP_DIV(fineHgr->nodeNum, blocksize);
    std::cout << "fineNodes:" << fineHgr->nodeNum << ", coarseNodes:" << coarsenHgr->nodeNum << "\n";
    TIMERSTART(0)
    projection<<<gridsize, blocksize>>>(coarsenHgr, fineHgr);
    TIMERSTOP(0)
    time += time0 / 1000.f;
    cur += time0 / 1000.f;
    // std::cout << "prev_level edge cut quality:" << computeHyperedgeCut(fineHgr) << "\n";
}
