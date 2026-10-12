#include <cooperative_groups.h>
// Optionally include for memcpy_async() collective
#include <cooperative_groups/memcpy_async.h>
// Optionally include for reduce() collective
#include <cooperative_groups/reduce.h>
// Optionally include for inclusive_scan() and exclusive_scan() collectives
#include <cooperative_groups/scan.h>
namespace cg = cooperative_groups;
#include <thrust/execution_policy.h>
#include <cub/device/device_scan.cuh>

__global__ void combined_kernel12(
                                int* hedges, int* nodes, unsigned* adj_list, 
                                int hedgeN, int nodeN, 
                                int* weights, unsigned* hedge_id, int* nHedgeId, int totalsize,
                                int LIMIT, int* candidates, int* flag, int* nodeid, int* cand_count,
                                int* newHedgeN, int* newNodeN, 
                                int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* parent
                                ) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        int idnum = hedges[hedge_id[tid] + E_IDNUM1(hedgeN)];
        int hedgeid = nHedgeId[adj_list[tid] - hedgeN];
        int weight = nodes[adj_list[tid] - hedgeN + N_WEIGHT1(nodeN)];
        weights[tid] = (idnum == hedgeid) ? weight : 0;
    }
    cg::grid_group g = cg::this_grid();
    g.sync();

    if (tid == 0)   thrust::inclusive_scan(thrust::device, weights, weights + totalsize, weights);

    // g.sync();
    
    // if (tid < totalsize) {
    //     int hid = hedge_id[tid];
    //     int cur_weight = hid > 0 ? weights[tid] - weights[hedges[hid + E_OFFSET1(hedgeN)] - 1] : weights[tid];
    //     int weight_diff = tid > 0 ? weights[tid] - weights[tid - 1] : weights[tid];
    //     if (weight_diff == 0) {
    //         flag[hedge_id[tid]] = true;
    //     } else if (cur_weight <= LIMIT) {
    //         unsigned dst = adj_list[tid];
    //         atomicMin(&nodeid[hedge_id[tid]], dst);
    //         atomicAdd(&cand_count[hedge_id[tid]], 1);
    //         candidates[dst - hedgeN] = 1;
    //     }
    // }

    // g.sync();

    // if (tid < totalsize) {
    //     int hid = hedge_id[tid];
    //     if (cand_count[hid]) {
    //         if (!flag[hid] || cand_count[hid] > 1) {
    //             if (tid == 0 || (tid > 0 && hid > hedge_id[tid-1])) {
    //                 eMatch[hid] = 1;
    //                 if (flag[hid]) {
    //                     eInBag[hid] = 1;
    //                     atomicAdd(&newHedgeN[0], 1);
    //                 }
    //                 nBag[nodeid[hid] - hedgeN] = 1;
    //                 atomicAdd(&newNodeN[0], 1);
    //             }
    //             int represent = nodeid[hid];
    //             int idnum = hedges[hedge_id[tid] + E_IDNUM1(hedgeN)];
    //             int hedgeid = nHedgeId[adj_list[tid] - hedgeN];
    //             if (candidates[adj_list[tid] - hedgeN] && idnum == hedgeid) {
    //                 nMatch[adj_list[tid] - hedgeN] = 1;
    //                 parent[adj_list[tid] - hedgeN] = represent;
    //                 int tmpW = nodes[adj_list[tid] - hedgeN + N_WEIGHT1(nodeN)];
    //                 atomicAdd(&accW[represent - hedgeN], tmpW);
    //             }
    //         }
    //     }
    // }
}

__global__ void combined_kernel34(
                                int* hedges, int* nodes, unsigned* adj_list, 
                                int hedgeN, int nodeN, 
                                int* weights, unsigned* hedge_id, int* nHedgeId, int totalsize,
                                int LIMIT, int* candidates, int* flag, int* nodeid, int* cand_count,
                                int* newHedgeN, int* newNodeN, 
                                int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* parent
                                ) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        int hid = hedge_id[tid];
        int cur_weight = hid > 0 ? weights[tid] - weights[hedges[hid + E_OFFSET1(hedgeN)] - 1] : weights[tid];
        int weight_diff = tid > 0 ? weights[tid] - weights[tid - 1] : weights[tid];
        if (weight_diff == 0) {
            flag[hedge_id[tid]] = true;
        } else if (cur_weight <= LIMIT) {
            unsigned dst = adj_list[tid];
            atomicMin(&nodeid[hedge_id[tid]], dst);
            atomicAdd(&cand_count[hedge_id[tid]], 1);
            candidates[dst - hedgeN] = 1;
        }
    }

    // cg::grid_group g = cg::this_grid();
    // g.sync();

    // tid = blockIdx.x * blockDim.x + threadIdx.x;
    // if (tid < totalsize) {
    //     int hid = hedge_id[tid];
    //     if (cand_count[hid]) {
    //         if (!flag[hid] || cand_count[hid] > 1) {
    //             if (tid == 0 || (tid > 0 && hid > hedge_id[tid-1])) {
    //                 eMatch[hid] = 1;
    //                 if (flag[hid]) {
    //                     eInBag[hid] = 1;
    //                     atomicAdd(&newHedgeN[0], 1);
    //                 }
    //                 nBag[nodeid[hid] - hedgeN] = 1;
    //                 atomicAdd(&newNodeN[0], 1);
    //             }
    //             int represent = nodeid[hid];
    //             int idnum = hedges[hedge_id[tid] + E_IDNUM1(hedgeN)];
    //             int hedgeid = nHedgeId[adj_list[tid] - hedgeN];
    //             if (candidates[adj_list[tid] - hedgeN] && idnum == hedgeid) {
    //                 nMatch[adj_list[tid] - hedgeN] = 1;
    //                 parent[adj_list[tid] - hedgeN] = represent;
    //                 int tmpW = nodes[adj_list[tid] - hedgeN + N_WEIGHT1(nodeN)];
    //                 atomicAdd(&accW[represent - hedgeN], tmpW);
    //             }
    //         }
    //     }
    // }
}
