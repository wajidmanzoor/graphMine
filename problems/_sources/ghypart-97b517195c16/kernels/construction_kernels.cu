#include "construction_kernels.cuh"
#include <thrust/find.h>
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/unique.h>
#include <thrust/execution_policy.h>

__global__ void setParentEdgeList(Hypergraph* hgr, int N, Hypergraph* coarsenHgr) {
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidy = blockIdx.y * blockDim.y + threadIdx.y;
#if 1
    if (tidx < N) {
        if (hgr->hedges[E_INBAG(hgr) + tidx]) {
            unsigned h_id = hgr->hedges[tidx + E_NEXTID(hgr)];
            int id = h_id;
            while (tidy < hgr->hedges[tidx + E_DEGREE(hgr)]) {
                unsigned pid = hgr->nodes[hgr->adj_list[hgr->hedges[tidx + E_OFFSET(hgr)] + tidy] - hgr->hedgeNum + N_PARENT(hgr)];
                bool isfind = false;
                for (int i = 0; i < tidy; i++) {
                    if (hgr->nodes[hgr->adj_list[hgr->hedges[tidx + E_OFFSET(hgr)] + i] - hgr->hedgeNum + N_PARENT(hgr)] == pid) {
                        isfind = true;
                        break;
                    }
                }
                if (!isfind) {
                    hgr->par_list[hgr->hedges[tidx + E_OFFSET(hgr)] + tidy] = true;
                    // hgr->par_list1[hgr->hedges[tidx + E_OFFSET(hgr)] + tidy] = 1;
                    atomicAdd(&coarsenHgr->hedges[id + E_DEGREE(coarsenHgr)], 1);
                    atomicAdd(&coarsenHgr->totalEdgeDegree, 1);
                    // if (tidx == 24 && tidy == 0) {
                    //     printf("%d\n", hgr->par_list1[hgr->hedges[tidx + E_OFFSET(hgr)] + tidy]);
                    // }
                }
                tidy += gridDim.y * blockDim.y;
            }
        }
    }
#endif
}

__global__ void constructCoarserAdjList(Hypergraph* hgr, Hypergraph* coarsenHgr, unsigned N) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < N) {
        if (tid < hgr->hedgeNum) {
            if (hgr->hedges[E_INBAG(hgr) + tid]) {
                unsigned h_id = hgr->hedges[tid + E_NEXTID(hgr)];
                coarsenHgr->hedges[E_IDNUM(coarsenHgr) + h_id] = hgr->hedges[E_IDNUM(hgr) + tid];
                hgr->hedges[E_ELEMID(hgr) + tid] = h_id;
                int id = hgr->hedges[E_ELEMID(hgr) + tid];
                int count = 0;
                for (unsigned j = 0; j < hgr->hedges[tid + E_DEGREE(hgr)]; ++j) {
                    if (hgr->par_list[hgr->hedges[tid + E_OFFSET(hgr)] + j] == true) {
                    // if (hgr->par_list1[hgr->hedges[tid + E_OFFSET(hgr)] + j] == 1) {
                        unsigned pid = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + j] - hgr->hedgeNum + N_PARENT(hgr)];
                        coarsenHgr->adj_list[coarsenHgr->hedges[E_OFFSET(coarsenHgr) + id] + count] = pid;
                        count++;
                        atomicAdd(&coarsenHgr->nodes[N_DEGREE(coarsenHgr) + (pid - coarsenHgr->hedgeNum)], 1);
                        atomicAdd(&coarsenHgr->totalNodeDegree, 1);
                    }
                }
                atomicMin(&coarsenHgr->minDegree, coarsenHgr->hedges[E_DEGREE(coarsenHgr) + id]);
                atomicMax(&coarsenHgr->maxDegree, coarsenHgr->hedges[E_DEGREE(coarsenHgr) + id]);
                coarsenHgr->hedges[E_PRIORITY(coarsenHgr) + id] = INT_MAX;
            }
        } else { // coarsenHgr->nodeNum
            int index = tid - hgr->hedgeNum;
            coarsenHgr->nodes[N_PRIORITY(coarsenHgr) + index] = INT_MAX;
            coarsenHgr->nodes[N_RAND(coarsenHgr) + index] = INT_MAX;
            coarsenHgr->nodes[N_HEDGEID(coarsenHgr) + index] = INT_MAX;
            coarsenHgr->nodes[N_ELEMID(coarsenHgr) + index] = index + coarsenHgr->hedgeNum;
            coarsenHgr->nodes[N_WEIGHT(coarsenHgr) + index] = coarsenHgr->nodes[N_TMPW(coarsenHgr) + index];
            coarsenHgr->nodes[N_TMPW(coarsenHgr) + index] = 0;
            atomicMin(&coarsenHgr->minWeight, coarsenHgr->nodes[N_WEIGHT(coarsenHgr) + index]);
            atomicMax(&coarsenHgr->maxWeight, coarsenHgr->nodes[N_WEIGHT(coarsenHgr) + index]);
        }
    }
}

__global__ void constructIncidentNetLists(Hypergraph* coarsenHgr, int hedgeN) {
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidy = blockIdx.y * blockDim.y + threadIdx.y;
    if (tidx < hedgeN) {
        while (tidy < coarsenHgr->hedges[tidx + E_DEGREE(coarsenHgr)]) {
            unsigned nodeid = coarsenHgr->adj_list[coarsenHgr->hedges[E_OFFSET(coarsenHgr) + tidx] + tidy];
            unsigned index = atomicAdd(&coarsenHgr->nodes[N_NETCOUNT(coarsenHgr) + nodeid - coarsenHgr->hedgeNum], 1);
            coarsenHgr->incident_nets[coarsenHgr->nodes[N_OFFSET(coarsenHgr) + nodeid - coarsenHgr->hedgeNum] + index] = tidx;
            tidy += gridDim.y * blockDim.y;
        }
    }
}

#if 0
__global__ void fillNextLevelAdjacentListWithoutDuplicates_nouvm(
                                        int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, 
                                        int hedgeN, int nodeN, int* newHedges, int* newNodes, unsigned* newAdjList, 
                                        int newNodeN, int newHedgeN, int* newTotalNodeDeg, 
                                        int* maxDegree, int* minDegree, int* newAdjListCounter/*, unsigned* offset*/) {
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    // __shared__ int count[1];// = {0};
    // count[0] = 0;
    if (tidx < hedgeN) {
        if (hedges[E_INBAG1(hedgeN) + tidx]) {
            unsigned h_id = hedges[tidx + E_NEXTID1(hedgeN)];
            newHedges[E_IDNUM1(newHedgeN) + h_id] = hedges[E_IDNUM1(hedgeN) + tidx];
            hedges[E_ELEMID1(hedgeN) + tidx] = h_id;
            int id = h_id;
            int tidy = blockIdx.y * blockDim.y + threadIdx.y;
            // if (tidx == 0 && tidy == 0) {
            //     printf("%d %d\n", blockDim.x, gridDim.x);
            // }
            while (tidy < hedges[tidx + E_DEGREE1(hedgeN)]) {
                if (isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] == 1) {
                    unsigned pid = nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] - hedgeN + N_PARENT1(nodeN)];
                    newAdjList[newHedges[E_OFFSET1(newHedgeN) + id] + atomicAdd(&newAdjListCounter[id], 1)] = pid;
                    // newAdjList[newHedges[E_OFFSET1(newHedgeN) + id] + offset[hedges[tidx + E_OFFSET1(hedgeN)] + tidy]] = pid;
                    // newAdjList[newHedges[E_OFFSET1(newHedgeN) + id] + atomicAdd(&count[0], 1)] = pid;
                    atomicAdd(&newNodes[N_DEGREE1(newNodeN) + (pid - newHedgeN)], 1);
                    atomicAdd(&newTotalNodeDeg[0], 1);
                }
                tidy += gridDim.y * blockDim.y;
            }
            __syncthreads();
            // count[0] = 0;
            tidy = blockIdx.y * blockDim.y + threadIdx.y;
            if (tidy == 0) {
                atomicMin(&minDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                atomicMax(&maxDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                newHedges[E_PRIORITY1(newHedgeN) + id] = INT_MAX;
            }
            __syncthreads();
        }
        // tidx += gridDim.x * blockDim.x;
    }
}

__global__ void setCoarsenNodesProperties_nouvm(int* newNodes, int newNodeN, int newHedgeN, int* maxWeight, int* minWeight) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < newNodeN) {
        newNodes[N_PRIORITY1(newNodeN) + tid] = INT_MAX;
        newNodes[N_RAND1(newNodeN) + tid] = INT_MAX;
        newNodes[N_HEDGEID1(newNodeN) + tid] = INT_MAX;
        newNodes[N_ELEMID1(newNodeN) + tid] = tid + newHedgeN;
        newNodes[N_WEIGHT1(newNodeN) + tid] = newNodes[N_TMPW1(newNodeN) + tid];
        newNodes[N_TMPW1(newNodeN) + tid] = 0;
        atomicMin(&minWeight[0], newNodes[N_WEIGHT1(newNodeN) + tid]);
        atomicMax(&maxWeight[0], newNodes[N_WEIGHT1(newNodeN) + tid]);
    }
}

// markDuplicasInNextLevelAdjacentList1(hgr, hgr->hedgeNum, hgr->nodeNum, coarsenHgr, coarsenHgr->hedgeNum, bit_length, num_hedges)
__global__ void markDuplicasInNextLevelAdjacentList1(Hypergraph* hgr, int hedgeN, int nodeN, Hypergraph* coarsenHgr, 
                                                    int newHedgeN, int bitLen, int num_hedges) {
    
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidy = blockIdx.y * blockDim.y + threadIdx.y;
    // printf("%d %d %d %d\n", blockDim.x, gridDim.x, blockDim.y, gridDim.y);
    while (tidx < hedgeN) {
    // if (tidx < hedgeN) {
        if (hgr->hedges[E_INBAG(hgr) + tidx]) {
            unsigned h_id = hgr->hedges[tidx + E_NEXTID(hgr)];
            int id = h_id;
            tidy = blockIdx.y * blockDim.y + threadIdx.y;
            while (tidy < hgr->hedges[tidx + E_DEGREE(hgr)]) {
                unsigned curr_loc = hgr->hedges[tidx + E_OFFSET(hgr)] + tidy;
                unsigned candidate = hgr->nodes[hgr->adj_list[curr_loc] - hedgeN + N_PARENT(hgr)] - newHedgeN;
                unsigned bitset_idx = candidate / 32;
                unsigned bit_offset = candidate & 31;
                unsigned shift_bits = 31 - bit_offset;
                unsigned bitset_loc = (tidx % num_hedges) * bitLen + bitset_idx;
                // int cur_bit0 = hgr->bitset[curr_loc];
                // printf("[%d %d %d]  ", tidx, tidy, curr_loc);
                // int cur_bit = atomicOr(&hgr->bitset[curr_loc], 1);
                int cur_bit = atomicOr(&hgr->bitset[bitset_loc], (0x80000000 >> bit_offset));
                int extract_bit_val = (cur_bit & (1 << shift_bits)) >> shift_bits;
                if (extract_bit_val == 0) {
                    // hgr->par_list1[curr_loc] = 1;
                    hgr->par_list[curr_loc] = true;
                    atomicAdd(&coarsenHgr->hedges[id + E_DEGREE(coarsenHgr)], 1);
                    atomicAdd(&coarsenHgr->totalEdgeDegree, 1);
                } 
                // else {
                //     hgr->par_list1[curr_loc] = 0;
                // }
                tidy += gridDim.y * blockDim.y;
            }
            // __syncthreads();
            // tidy = blockIdx.y * blockDim.y + threadIdx.y;
            // while (tidy < hgr->hedges[tidx + E_DEGREE(hgr)]) {
            //     unsigned curr_loc = hgr->hedges[tidx + E_OFFSET(hgr)] + tidy;
            //     unsigned candidate = hgr->nodes[hgr->adj_list[curr_loc] - hedgeN + N_PARENT(hgr)] - newHedgeN;
            //     // unsigned curr_loc = offset[tidx] + tidy;
            //     unsigned bitset_idx = candidate / 32;
            //     unsigned bitset_loc = (tidx % num_hedges) * bitLen + bitset_idx;
            //     hgr->bitset[bitset_loc] = 0;
            //     tidy += gridDim.y * blockDim.y;
            // }
            // if (threadIdx.y == 0) {
            //     for (int i = 0; i < bitLen; ++i) {
            //         bitset[(tidx % num_hedges) * bitLen + i] = 0;
            //     }
            // }
            // __syncthreads();
        }
        tidx += gridDim.x * blockDim.x;
    }
}


__global__ void markDuplicasInNextLevelAdjacentList2(Hypergraph* hgr, int hedgeN, int nodeN, Hypergraph* coarsenHgr, 
                                                    int newHedgeN, int bitLen, int num_hedges) {
    int tid = threadIdx.x;
    // if (tidx < hedgeN) {
        if (hgr->hedges[E_INBAG(hgr) + blockIdx.x]) {
            unsigned h_id = hgr->hedges[blockIdx.x + E_NEXTID(hgr)];
            int id = h_id;
            // tidy = blockIdx.y * blockDim.y + threadIdx.y;
            while (tid < hgr->hedges[blockIdx.x + E_DEGREE(hgr)]) {
                unsigned curr_loc = hgr->hedges[blockIdx.x + E_OFFSET(hgr)] + tid;
                unsigned candidate = hgr->nodes[hgr->adj_list[curr_loc] - hedgeN + N_PARENT(hgr)] - newHedgeN;
                unsigned bitset_loc = (blockIdx.x % num_hedges) * bitLen + candidate;
                int cur_bit = atomicOr(&hgr->bitset[bitset_loc], 1);
                if (cur_bit == 0) {
                    hgr->par_list[curr_loc] = true;
                    atomicAdd(&coarsenHgr->hedges[id + E_DEGREE(coarsenHgr)], 1);
                    atomicAdd(&coarsenHgr->totalEdgeDegree, 1);
                }
                tid += blockDim.x;
            }

        }
        // tidx += gridDim.x * blockDim.x;
    // }
}

__global__ void markDuplicasInNextLevelAdjacentList3(Hypergraph* hgr, int hedgeN, int nodeN, Hypergraph* coarsenHgr, 
                                                    int newHedgeN, int bitLen, int num_hedges) {
    int tid = threadIdx.x;
    // if (tidx < hedgeN) {
        if (hgr->hedges[E_INBAG(hgr) + blockIdx.x]) {
            unsigned h_id = hgr->hedges[blockIdx.x + E_NEXTID(hgr)];
            int id = h_id;
            // tidy = blockIdx.y * blockDim.y + threadIdx.y;
            while (tid < hgr->hedges[blockIdx.x + E_DEGREE(hgr)]) {
                unsigned curr_loc = hgr->hedges[blockIdx.x + E_OFFSET(hgr)] + tid;
                unsigned candidate = hgr->nodes[hgr->adj_list[curr_loc] - hedgeN + N_PARENT(hgr)] - newHedgeN;
                unsigned bitset_idx = candidate / 32;
                unsigned bit_offset = candidate & 31;
                unsigned bitset_loc = (blockIdx.x % num_hedges) * bitLen + bitset_idx;
                int cur_bit = atomicOr(&hgr->bitset[bitset_loc], (0x80000000 >> bit_offset));
                unsigned shift_bits = 31 - bit_offset;
                int extract_bit_val = (cur_bit & (1 << shift_bits)) >> shift_bits;
                if (extract_bit_val == 0) {
                    hgr->par_list[curr_loc] = true;
                    atomicAdd(&coarsenHgr->hedges[id + E_DEGREE(coarsenHgr)], 1);
                    atomicAdd(&coarsenHgr->totalEdgeDegree, 1);
                }
                tid += blockDim.x;
            }
        }
        // tidx += gridDim.x * blockDim.x;
    // }
}


__global__ void markDuplicasInNextLevelAdjacentList4(Hypergraph* hgr, int hedgeN, int nodeN, Hypergraph* coarsenHgr, 
                                                    int newHedgeN, int bitLen, int num_hedges) {
    int tid = threadIdx.x;
    // if (tidx < hedgeN) {
        if (hgr->hedges[E_INBAG(hgr) + blockIdx.x]) {
            unsigned h_id = hgr->hedges[blockIdx.x + E_NEXTID(hgr)];
            int id = h_id;
            // tidy = blockIdx.y * blockDim.y + threadIdx.y;
            while (tid < hgr->hedges[blockIdx.x + E_DEGREE(hgr)]) {
                unsigned curr_loc = hgr->hedges[blockIdx.x + E_OFFSET(hgr)] + tid;
                unsigned candidate = hgr->nodes[hgr->adj_list[curr_loc] - hedgeN + N_PARENT(hgr)] - newHedgeN;
                unsigned bitset_idx = candidate / 32;
                unsigned bit_offset = candidate & 31;
                unsigned bitset_loc = (blockIdx.x % num_hedges) * bitLen + bitset_idx;
                int cur_bit = atomicOr(&hgr->bitset[bitset_loc], (0x80000000 >> bit_offset));
                unsigned shift_bits = 31 - bit_offset;
                int extract_bit_val = (cur_bit & (1 << shift_bits)) >> shift_bits;
                if (extract_bit_val == 0) {
                    hgr->par_list1[curr_loc] = 1;
                    atomicAdd(&coarsenHgr->hedges[id + E_DEGREE(coarsenHgr)], 1);
                    atomicAdd(&coarsenHgr->totalEdgeDegree, 1);
                }
                tid += blockDim.x;
            }
        }
        // tidx += gridDim.x * blockDim.x;
    // }
}


__global__ void setParentEdgeList1(Hypergraph* hgr, int N, Hypergraph* coarsenHgr) {
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidy = blockIdx.y * blockDim.y + threadIdx.y;

    if (tidx < N) {
        if (hgr->hedges[E_INBAG(hgr) + tidx]) {
            unsigned h_id = hgr->hedges[tidx + E_NEXTID(hgr)];
            int id = h_id;
            while (tidy < hgr->hedges[tidx + E_DEGREE(hgr)]) {
                unsigned pid = hgr->nodes[hgr->adj_list[hgr->hedges[tidx + E_OFFSET(hgr)] + tidy] - hgr->hedgeNum + N_PARENT(hgr)];
                bool isfind = false;
                for (int i = 0; i < tidy; i++) {
                    if (hgr->nodes[hgr->adj_list[hgr->hedges[tidx + E_OFFSET(hgr)] + i] - hgr->hedgeNum + N_PARENT(hgr)] == pid) {
                        isfind = true;
                        break;
                    }
                }
                if (!isfind) {
                    hgr->par_list1[hgr->hedges[tidx + E_OFFSET(hgr)] + tidy] = 1;
                    atomicAdd(&coarsenHgr->hedges[id + E_DEGREE(coarsenHgr)], 1);
                    atomicAdd(&coarsenHgr->totalEdgeDegree, 1);
                }
                tidy += gridDim.y * blockDim.y;
            }
        }
    }
}


__global__ void constructCoarserAdjList1(Hypergraph* hgr, Hypergraph* coarsenHgr, unsigned N) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < N) {
        if (tid < hgr->hedgeNum) {
            if (hgr->hedges[E_INBAG(hgr) + tid]) {
                unsigned h_id = hgr->hedges[tid + E_NEXTID(hgr)];
                coarsenHgr->hedges[E_IDNUM(coarsenHgr) + h_id] = hgr->hedges[E_IDNUM(hgr) + tid];
                hgr->hedges[E_ELEMID(hgr) + tid] = h_id;
                int id = hgr->hedges[E_ELEMID(hgr) + tid];
                int count = 0;
                for (unsigned j = 0; j < hgr->hedges[tid + E_DEGREE(hgr)]; ++j) {
                    // if (hgr->par_list[hgr->hedges[tid + E_OFFSET(hgr)] + j] == true) {
                    if (hgr->par_list1[hgr->hedges[tid + E_OFFSET(hgr)] + j] == 1) {
                        unsigned pid = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + j] - hgr->hedgeNum + N_PARENT(hgr)];
                        coarsenHgr->adj_list[coarsenHgr->hedges[E_OFFSET(coarsenHgr) + id] + count] = pid;
                        count++;
                        atomicAdd(&coarsenHgr->nodes[N_DEGREE(coarsenHgr) + (pid - coarsenHgr->hedgeNum)], 1);
                        atomicAdd(&coarsenHgr->totalNodeDegree, 1);
                    }
                }
                atomicMin(&coarsenHgr->minDegree, coarsenHgr->hedges[E_DEGREE(coarsenHgr) + id]);
                atomicMax(&coarsenHgr->maxDegree, coarsenHgr->hedges[E_DEGREE(coarsenHgr) + id]);
                coarsenHgr->hedges[E_PRIORITY(coarsenHgr) + id] = INT_MAX;
            }
        } else { // coarsenHgr->nodeNum
            int index = tid - hgr->hedgeNum;
            coarsenHgr->nodes[N_PRIORITY(coarsenHgr) + index] = INT_MAX;
            coarsenHgr->nodes[N_RAND(coarsenHgr) + index] = INT_MAX;
            coarsenHgr->nodes[N_HEDGEID(coarsenHgr) + index] = INT_MAX;
            coarsenHgr->nodes[N_ELEMID(coarsenHgr) + index] = index + coarsenHgr->hedgeNum;
            coarsenHgr->nodes[N_WEIGHT(coarsenHgr) + index] = coarsenHgr->nodes[N_TMPW(coarsenHgr) + index];
            coarsenHgr->nodes[N_TMPW(coarsenHgr) + index] = 0;
            atomicMin(&coarsenHgr->minWeight, coarsenHgr->nodes[N_WEIGHT(coarsenHgr) + index]);
            atomicMax(&coarsenHgr->maxWeight, coarsenHgr->nodes[N_WEIGHT(coarsenHgr) + index]);
        }
    }
}
#endif