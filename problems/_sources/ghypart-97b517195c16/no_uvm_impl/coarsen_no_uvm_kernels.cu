#include "coarsen_no_uvm_kernels.cuh"
#include <cuda/atomic>

__host__ __device__ int hash1(unsigned val) {
    unsigned long int seed = val * 1103515245 + 12345;
    return ((unsigned)(seed / 65536) % 32768);
}

__global__ void setHyperedgePriority(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, unsigned matching_policy, int* eRand, int* ePrior) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        // hedges[E_RAND1(hedgeN) + tid] = hash1(hedges[E_IDNUM1(hedgeN) + tid]);
        eRand[tid] = hash1(hedges[E_IDNUM1(hedgeN) + tid]);
        if (matching_policy == 0) {
            // hedges[E_PRIORITY1(hedgeN) + tid] = -hedges[E_RAND1(hedgeN) + tid];
            // hedges[E_RAND1(hedgeN) + tid] = -hedges[E_IDNUM1(hedgeN) + tid];
            // hedges[E_PRIORITY1(hedgeN) + tid] = -eRand[tid];
            ePrior[tid] = -eRand[tid];
            eRand[tid] = -hedges[E_IDNUM1(hedgeN) + tid];
        } else if (matching_policy == 1) {
            // hedges[E_PRIORITY1(hedgeN) + tid] = hedges[E_DEGREE1(hedgeN) + tid];
            ePrior[tid] = hedges[E_DEGREE1(hedgeN) + tid];
        } else if (matching_policy == 2) {
            // hedges[E_PRIORITY1(hedgeN) + tid] = -hedges[E_DEGREE1(hedgeN) + tid];
            ePrior[tid] = -hedges[E_DEGREE1(hedgeN) + tid];
        } else if (matching_policy == 3) {
            for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
                unsigned w = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_WEIGHT1(nodeN)];
                // hedges[E_PRIORITY1(hedgeN) + tid] += -w;
                ePrior[tid] += -w;
            }
        } else if (matching_policy == 4) {
            for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
                unsigned w = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_WEIGHT1(nodeN)];
                // hedges[E_PRIORITY1(hedgeN) + tid] += w;
                ePrior[tid] += w;
            }
        } else if (matching_policy == 5) {
            unsigned w = 0;
            for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
                w += nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_WEIGHT1(nodeN)];
            }
            // hedges[E_PRIORITY1(hedgeN) + tid] = -(w / hedges[E_DEGREE1(hedgeN) + tid]);
            ePrior[tid] = -(w / hedges[E_DEGREE1(hedgeN) + tid]);
        }
        else if (matching_policy == 6) {
            unsigned w = 0;
            for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
                w += nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_WEIGHT1(nodeN)];
            }
            // hedges[E_PRIORITY1(hedgeN) + tid] = -(w / hedges[E_DEGREE1(hedgeN) + tid]);
            ePrior[tid] = w / hedges[E_DEGREE1(hedgeN) + tid];
        }
    }
}

__global__ void multiNodeMatching1(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* ePrior, int* nPrior) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            int hedgePrior = ePrior[tid];
            int index = adj_list[hedges[E_OFFSET1(hedgeN) + tid] + i] - hedgeN;
            int* nodePrior = &nPrior[index];
            atomicMin(nodePrior, hedgePrior);
        }
    }
}

__global__ void multiNodeMatching2(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* eRand, int* ePrior, int* nPrior, int* nRand) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            // int hedgePrior = hedges[E_PRIORITY1(hedgeN) + tid];
            int hedgePrior = ePrior[tid];
            int index = adj_list[hedges[E_OFFSET1(hedgeN) + tid] + i] - hedgeN;
            // int nodePrior = nodes[N_PRIORITY1(nodeN) + index];
            int nodePrior = nPrior[index];
            if (hedgePrior == nodePrior) {
                // int hedgeRand = hedges[E_RAND1(hedgeN) + tid];
                int hedgeRand = eRand[tid];
                int idx = adj_list[hedges[E_OFFSET1(hedgeN) + tid] + i] - hedgeN;
                // int* nodeRand = &nodes[N_RAND1(nodeN) + idx];
                int* nodeRand = &nRand[idx];
                atomicMin(nodeRand, hedgeRand);
            }
        }
    }
}

__global__ void multiNodeMatching3(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* eRand, int* nRand, int* nHedgeId) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            // int hedgeRand = hedges[E_RAND1(hedgeN) + tid];
            int hedgeRand = eRand[tid];
            int index = adj_list[hedges[E_OFFSET1(hedgeN) + tid] + i] - hedgeN;
            // int nodeRand = nodes[N_RAND1(nodeN) + index];
            int nodeRand = nRand[index];
            if (hedgeRand == nodeRand) {
                int idnum = hedges[E_IDNUM1(hedgeN) + tid];
                int idx = adj_list[hedges[E_OFFSET1(hedgeN) + tid] + i] - hedgeN;
                // int* hedgeid = &nodes[N_HEDGEID1(nodeN) + idx];
                int* hedgeid = &nHedgeId[idx];
                atomicMin(hedgeid, idnum);
            }
        }
    }
}

__global__ void assignPriorityToNode_P2(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* ePrior, int* nPrior) {
    int bid = blockIdx.x;
    if (bid < hedgeN) {
        unsigned tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + bid]) {
            int hedgePrior = ePrior[bid];
            int index = adj_list[hedges[E_OFFSET1(hedgeN) + bid] + tid] - hedgeN;
            int* nodePrior = &nPrior[index];
            atomicMin(nodePrior, hedgePrior);
            tid += blockDim.x;
        }
    }
}

__global__ void assignHashHedgeIdToNode_P2(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* eRand, int* ePrior, int* nPrior, int* nRand) {
    int bid = blockIdx.x;
    if (bid < hedgeN) {
        unsigned tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + bid]) {
            int hedgePrior = ePrior[bid];
            int index = adj_list[hedges[E_OFFSET1(hedgeN) + bid] + tid] - hedgeN;
            int nodePrior = nPrior[index];
            if (hedgePrior == nodePrior) {
                int hedgeRand = eRand[bid];
                int* nodeRand = &nRand[index];
                atomicMin(nodeRand, hedgeRand);
            }
            tid += blockDim.x;
        }
    }
}

__global__ void assignNodeToIncidentHedgeWithMinimalID_P2(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* eRand, int* nRand, int* nHedgeId) {
    int bid = blockIdx.x;
    if (bid < hedgeN) {
        unsigned tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + bid]) {
            int hedgeRand = eRand[bid];
            int index = adj_list[hedges[E_OFFSET1(hedgeN) + bid] + tid] - hedgeN;
            int nodeRand = nRand[index];
            if (hedgeRand == nodeRand) {
                int idnum = hedges[E_IDNUM1(hedgeN) + bid];
                int* hedgeid = &nHedgeId[index];
                atomicMin(hedgeid, idnum);
            }
            tid += blockDim.x;
        }
    }
}

__global__ void assignPriorityToNode(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, int nodeN, int hedgeN, int totalsize, int* ePrior, int* nPrior) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        // int* nodePrior = &nodes[adj_list[tid] - hedgeN + N_PRIORITY1(nodeN)];
        int* nodePrior = &nPrior[adj_list[tid] - hedgeN];
        // atomicMin(nodePrior, hedges[E_PRIORITY1(hedgeN) + hedge_id[tid]]);
        atomicMin(nodePrior, ePrior[hedge_id[tid]]);
    }
}

__global__ void assignHashHedgeIdToNode(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, int nodeN, int hedgeN, int totalsize, int* eRand, int* ePrior, int* nPrior, int* nRand) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        // int nodePrior = nodes[N_PRIORITY1(nodeN) + adj_list[tid] - hedgeN];
        int nodePrior = nPrior[adj_list[tid] - hedgeN];
        // if (nodePrior == hedges[E_PRIORITY1(hedgeN) + hedge_id[tid]]) {
        if (nodePrior == ePrior[hedge_id[tid]]) {
            // int* nodeRand = &nodes[adj_list[tid] - hedgeN + N_RAND1(nodeN)];
            int* nodeRand = &nRand[adj_list[tid] - hedgeN];
            // atomicMin(nodeRand, hedges[E_RAND1(hedgeN) + hedge_id[tid]]);
            atomicMin(nodeRand, eRand[hedge_id[tid]]);
        }
    }
}

__global__ void assignNodeToIncidentHedgeWithMinimalID(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, int nodeN, int hedgeN, int totalsize, int* eRand, int* nRand, int* nHedgeId) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        // int nodeRand = nodes[N_RAND1(nodeN) + adj_list[tid] - hedgeN];
        int nodeRand = nRand[adj_list[tid] - hedgeN];
        // if (nodeRand == hedges[E_RAND1(hedgeN) + hedge_id[tid]]) {
        if (nodeRand == eRand[hedge_id[tid]]) {
            // int* hedgeid = &nodes[adj_list[tid] - hedgeN + N_HEDGEID1(nodeN)];
            int* hedgeid = &nHedgeId[adj_list[tid] - hedgeN];
            atomicMin(hedgeid, hedges[E_IDNUM1(hedgeN) + hedge_id[tid]]);
        }
    }
}

__global__ void selectCandidatesTest(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN,
                                    int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                    int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId) {
    // int tid = blockIdx.x * blockDim.x + threadIdx.x;
    // if (tid < hedgeN) {
    //     bool flag = false;
    //     unsigned nodeid = INT_MAX;
    //     int count = 0;
    //     int w = 0;
    //     for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
    //         int isMatched = nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
    //         if (isMatched) { // return old value
    //             flag = true;
    //             continue;
    //         }
    //         unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
    //         int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
    //         unsigned int dst = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
    //         int weight = nodes[dst - hedgeN + N_WEIGHT1(nodeN)];
    //         if (idnum == hedgeid) {
    //             if (w + weight > LIMIT) {
    //                 break;
    //             }
    //             nodeid = min(nodeid, dst);
    //             count++;
    //             candidates[dst - hedgeN] = 1;
    //             w += weight;
    //         } else {
    //             flag = true;
    //         }
    //     }
    // }
}

__global__ void collectCandidateWeights(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, 
                                        int* weights, unsigned* hedge_id, int* nHedgeId, int totalsize, long long* timer, int* real_work_cnt) {
    // if (threadIdx.x == 0)   timer[blockIdx.x] = clock();
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        // timer[tid] = clock64();
        int idnum = hedges[hedge_id[tid] + E_IDNUM1(hedgeN)];
        int hedgeid = nHedgeId[adj_list[tid] - hedgeN];
        int weight = nodes[adj_list[tid] - hedgeN + N_WEIGHT1(nodeN)];
        weights[tid] = (idnum == hedgeid) ? weight : 0;
        // if (tid == 24) printf("%d %d\n", hedge_id[tid], idnum);
        // real_work_cnt[tid] = 7;
        // timer[tid] = clock64() - timer[tid];
    }
    // __syncthreads();
    // if (threadIdx.x == 0)   timer[blockIdx.x + gridDim.x] = clock();
}

__global__ void collectCandidateNodes(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int LIMIT, int iter, unsigned* hedge_id, int* nHedgeId, 
                                        int totalsize, int* weights, int* candidates, int* flag, int* nodeid, int* cand_count, long long* timer, int* real_work_cnt) {
    // if (threadIdx.x == 0)   timer[blockIdx.x] = clock();
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        // timer[tid] = clock64();
        int hid = hedge_id[tid];
        int cur_weight = hid > 0 ? weights[tid] - weights[hedges[hid + E_OFFSET1(hedgeN)] - 1] : weights[tid];
        int weight_diff = tid > 0 ? weights[tid] - weights[tid - 1] : weights[tid];
        // real_work_cnt[tid] = 5;
        if (weight_diff == 0) {
            flag[hedge_id[tid]] = true;
            // real_work_cnt[tid] += 2;
        } else if (cur_weight <= LIMIT) {
            unsigned dst = adj_list[tid];
            atomicMin(&nodeid[hedge_id[tid]], dst);
            atomicAdd(&cand_count[hedge_id[tid]], 1);
            candidates[dst - hedgeN] = 1;
            // real_work_cnt[tid] += 6;
        }
        // timer[tid] = clock64() - timer[tid];
    }
    // __syncthreads();
    // if (threadIdx.x == 0)   timer[blockIdx.x + gridDim.x] = clock();
}

__global__ void assignMatchStatusAndSuperNodeToCandidates(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter,
                                                        int totalsize, unsigned* hedge_id, int* nHedgeId, int* newHedgeN, int* newNodeN, 
                                                        int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* parent,
                                                        int* candidates, int* flag, int* nodeid, int* cand_count, long long* timer) {
    // if (threadIdx.x == 0)   timer[blockIdx.x] = clock();
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        int hid = hedge_id[tid];
        // timer[tid] = clock64();
        if (cand_count[hid]) {
            if (!flag[hid] || cand_count[hid] > 1) {
                if (tid == 0 || (tid > 0 && hid > hedge_id[tid-1])) {
                    eMatch[hid] = 1;
                    if (flag[hid]) {
                        eInBag[hid] = 1;
                        atomicAdd(&newHedgeN[0], 1);
                    }
                    nBag[nodeid[hid] - hedgeN] = 1;
                    atomicAdd(&newNodeN[0], 1);
                }
                int represent = nodeid[hid];
                int idnum = hedges[hedge_id[tid] + E_IDNUM1(hedgeN)];
                int hedgeid = nHedgeId[adj_list[tid] - hedgeN];
                if (candidates[adj_list[tid] - hedgeN] && idnum == hedgeid) {
                    nMatch[adj_list[tid] - hedgeN] = 1;
                    parent[adj_list[tid] - hedgeN] = represent;
                    int tmpW = nodes[adj_list[tid] - hedgeN + N_WEIGHT1(nodeN)];
                    atomicAdd(&accW[represent - hedgeN], tmpW);
                }
            }
        }
        // timer[tid] = clock64() - timer[tid];
    }
    // __syncthreads();
    // if (threadIdx.x == 0)   timer[blockIdx.x + gridDim.x] = clock();
}

__global__ void mergeNodesInsideHyperedges(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN,
                                            int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                            int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId, 
                                            /*int* counts, unsigned* pnodes, int* flags,*/
                                            long long* timer, long long* timer1, long long* timer2, int* real_work_cnt, int* real_work_cnt1) {
    // if (threadIdx.x == 0)   timer[blockIdx.x] = clock64();
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        // timer2[tid] = clock64();
        // if (threadIdx.x == 0)   timer[blockIdx.x] = clock64();
        bool flag = false;
        unsigned nodeid = INT_MAX;
        int count = 0;
        int w = 0;
        int i = 0;
        // timer2[tid] = clock64();
        // for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
        for (; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            // unsigned int isMatched = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_MATCHED1(nodeN)];
            int isMatched = nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
            // real_work_cnt[tid] += 4;
            if (isMatched) { // return old value
                flag = true;
                continue;
            }
            unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
            // unsigned int hedgeid = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_HEDGEID1(nodeN)];
            int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
            unsigned int dst = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
            int weight = nodes[dst - hedgeN + N_WEIGHT1(nodeN)];
            // real_work_cnt[tid] += 7;
            if (idnum == hedgeid) {
                if (w + weight > LIMIT) {
                    break;
                }
                nodeid = min(nodeid, dst);
                count++;
                // nodes[dst - hedgeN + N_FOR_UPDATE1(nodeN)] = 1;//true;
                candidates[dst - hedgeN] = 1;
                w += weight;
                // real_work_cnt[tid] += 1;
            } else {
                flag = true;
            }
        }
        // timer2[tid] = clock64() - timer2[tid];
        // real_work_cnt[tid] = i;
        // __syncthreads();
        // if (threadIdx.x == 0) {
        //     timer[blockIdx.x + gridDim.x] = clock();
        //     timer1[blockIdx.x] = clock();
        // }
        // timer1[tid] = clock64();
        if (count) {
            if (flag && count == 1) { // do not update this node to match this hedge, leave later matching
                return;
            }
            // hedges[tid + E_MATCHED1(hedgeN)] = 1;
            eMatch[tid] = 1;
            if (flag) {
                // hedges[tid + E_INBAG1(hedgeN)] = 1;//true;
                eInBag[tid] = 1;
                atomicAdd(&newHedgeN[0], 1);
            }
            // nodes[nodeid - hedgeN + N_INBAG1(nodeN)] = 1;//true;
            // timer1[tid] = clock64();
            nBag[nodeid - hedgeN] = 1;
            atomicAdd(&newNodeN[0], 1);
            for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
                unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
                // unsigned int hedgeid = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_HEDGEID1(nodeN)];
                int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                // if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_FOR_UPDATE1(nodeN)] && idnum == hedgeid) {
                int candidate = candidates[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                if (candidate && idnum == hedgeid) {
                    // nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_MATCHED1(nodeN)] = 1;
                    nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = 1;
                    nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] = nodeid;
                    int tmpW = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
                    // atomicAdd(&nodes[nodeid - hedgeN + N_TMPW1(nodeN)], tmpW);
                    atomicAdd(&accW[nodeid - hedgeN], tmpW);
                }
            }
            // timer1[tid] = clock64() - timer1[tid];
            // real_work_cnt1[tid] = hedges[E_DEGREE1(hedgeN) + tid];
        }
        // timer1[tid] = clock64() - timer1[tid];
        // __syncthreads();
        // // if (threadIdx.x == 0)   timer1[blockIdx.x + gridDim.x] = clock();
        // if (threadIdx.x == 0)   timer[blockIdx.x + gridDim.x] = clock64();
        // timer2[tid] = clock64() - timer2[tid];
        // real_work_cnt[tid] = i;
    }
    // __syncthreads();
    // if (threadIdx.x == 0)   timer[blockIdx.x + gridDim.x] = clock64();
}

__global__ void mergeNodesInsideHyperedges_split1(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN,
                                            int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                            int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId, 
                                            int* counts, unsigned* pnodes, int* flags) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        bool flag = false;
        unsigned nodeid = INT_MAX;
        int count = 0;
        int w = 0;
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            // unsigned int isMatched = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_MATCHED1(nodeN)];
            int isMatched = nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
            if (isMatched) { // return old value
                flag = true;
                continue;
            }
            unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
            // unsigned int hedgeid = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_HEDGEID1(nodeN)];
            int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
            unsigned int dst = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
            int weight = nodes[dst - hedgeN + N_WEIGHT1(nodeN)];
            if (idnum == hedgeid) {
                if (w + weight > LIMIT) {
                    break;
                }
                nodeid = min(nodeid, dst);
                count++;
                // nodes[dst - hedgeN + N_FOR_UPDATE1(nodeN)] = 1;//true;
                candidates[dst - hedgeN] = 1;
                w += weight;
            } else {
                flag = true;
            }
        }
        counts[tid] = count;
        pnodes[tid] = nodeid;
        flags[tid] = flag;
    }
}

__global__ void mergeNodesInsideHyperedges_split2(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN,
                                            int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                            int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId, 
                                            int* counts, unsigned* pnodes, int* flags) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        if (counts[tid]) {
            if (flags[tid] && counts[tid] == 1) { // do not update this node to match this hedge, leave later matching
                return;
            }
            eMatch[tid] = 1;
            if (flags[tid]) {
                // hedges[tid + E_INBAG1(hedgeN)] = 1;//true;
                eInBag[tid] = 1;
                atomicAdd(&newHedgeN[0], 1);
            }
            // nodes[nodeid - hedgeN + N_INBAG1(nodeN)] = 1;//true;
            nBag[pnodes[tid] - hedgeN] = 1;
            atomicAdd(&newNodeN[0], 1);
            for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
                unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
                // unsigned int hedgeid = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_HEDGEID1(nodeN)];
                int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                // if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_FOR_UPDATE1(nodeN)] && idnum == hedgeid) {
                int candidate = candidates[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                if (candidate && idnum == hedgeid) {
                    // nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_MATCHED1(nodeN)] = 1;
                    nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = 1;
                    nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] = pnodes[tid];
                    int tmpW = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
                    // atomicAdd(&nodes[nodeid - hedgeN + N_TMPW1(nodeN)], tmpW);
                    atomicAdd(&accW[pnodes[tid] - hedgeN], tmpW);
                }
            }
        }
    }
}

__global__ void PrepareForFurtherMatching(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int* eMatch, int* nMatch, int* nPrior/*,
                                            int* best, int* represent, int* count*/) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        // if (hedges[E_MATCHED1(hedgeN) + tid]) {
        if (eMatch[tid]) {
            return;
        }
        // int bbest = INT_MAX;
        // unsigned rep = 0;
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            // if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_MATCHED1(nodeN)]) {
            if (nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN]) {
                // nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PRIORITY1(nodeN)] = INT_MIN;
                nPrior[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = INT_MIN;
                
                // count[tid]++;
                // if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] < bbest) {
                //     bbest = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
                //     rep = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                // } else if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] == bbest) {
                //     if (adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] < rep) {
                //         rep = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                //     }
                // }
            }
        }
        // best[tid] = bbest;
        // represent[tid] = rep;
    }
}

__global__ void resetAlreadyMatchedNodePriorityInUnmatchedHedge(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, 
                                        int nodeN, int hedgeN, int totalsize, int* eMatch, int* nMatch, int* nPrior/*,
                                        int* counts, int* keys, int* weight_vals, int* num_items, tmp_nodes* tNodesAttr*/) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        // if (!hedges[E_MATCHED1(hedgeN) + hedge_id[tid]]) {
        // int hid = hedge_id[tid];
        if (!eMatch[hedge_id[tid]]) {
            // if (nodes[adj_list[tid] - hedgeN + N_MATCHED1(nodeN)]) {
            if (nMatch[adj_list[tid] - hedgeN]) {
                // nodes[adj_list[tid] - hedgeN + N_PRIORITY1(nodeN)] = INT_MIN;
                nPrior[adj_list[tid] - hedgeN] = INT_MIN;

                // int index = atomicAdd(&counts[hid], 1);
                // atomicAdd(&num_items[0], 1);
                // keys[index] = adj_list[tid];
                // weight_vals[index] = nodes[adj_list[tid] - hedgeN + N_WEIGHT1(nodeN)];
                // tNodesAttr[tid].prior = INT_MIN;
                // tNodesAttr[tid].id_key = adj_list[tid];
                // tNodesAttr[tid].w_vals = nodes[adj_list[tid] - hedgeN + N_WEIGHT1(nodeN)];
                // tNodesAttr[tid].eMatch = 0;
                // tNodesAttr[tid].nMatch = 1;
                // tNodesAttr[tid].hedgeid = hid;
                // tNodesAttr[hedges[hid + E_OFFSET1(hedgeN)] + index].id_key = adj_list[tid];
                // tNodesAttr[hedges[hid + E_OFFSET1(hedgeN)] + index].w_vals = nodes[adj_list[tid] - hedgeN + N_WEIGHT1(nodeN)];
            }
            // else {
            //     tNodesAttr[tid].w_vals = INT_MAX;
            //     tNodesAttr[tid].hedgeid = hid;
            //     tNodesAttr[tid].id_key = adj_list[tid];
            // }
        }
    }
}

__global__ void parallelFindingCandsWithAtomicMin(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, unsigned* hedge_id, int* nHedgeId, 
                                            int* eMatch, int* nMatch, int* cand_counts, int* candidates, int totalsize/*, int* nPrior, 
                                            int* counts, int* keys, int* weight_vals, int* num_items*/) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        int hid = hedge_id[tid];
        if (!eMatch[hid]) {
            int nmatch = nMatch[adj_list[tid] - hedgeN];
            int idnum = hedges[hid + E_IDNUM1(hedgeN)];
            int hedgeid = nHedgeId[adj_list[tid] - hedgeN];
            if (!nmatch && idnum == hedgeid) {
                atomicAdd(&cand_counts[hid], 1);
                candidates[adj_list[tid] - hedgeN] = 1;
            } 
            // else if (nPrior[adj_list[tid] - hedgeN] == INT_MIN) {
            //     // int index = atomicAdd(&counts[hid], 1);
            //     // atomicAdd(&num_items[0], 1);
            //     // keys[index] = adj_list[tid];
            //     // weight_vals[index] = nodes[adj_list[tid] - hedgeN + N_WEIGHT1(nodeN)];
            // }
        }
    }
}

__global__ void collectRepresentNodes(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, unsigned* hedge_id, int* nHedgeId, 
                                        int* eMatch, int* nMatch, int* nPrior, int* cand_counts, int* candidates, int totalsize,
                                        int* counts, int* keys, int* weight_vals, int* num_items, tmp_nodes* tNodesAttr) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        int hid = hedge_id[tid];
        if (!eMatch[hid] && nMatch[adj_list[tid] - hedgeN]) {
            int index = atomicAdd(&counts[hid], 1);
            atomicAdd(&num_items[0], 1);
            tNodesAttr[hedges[hid + E_OFFSET1(hedgeN)] + index].id_key = adj_list[tid];
            tNodesAttr[hedges[hid + E_OFFSET1(hedgeN)] + index].w_vals = nodes[adj_list[tid] - hedgeN + N_WEIGHT1(nodeN)];
        }
    }
}

__global__ void assignMatchStatusAndSuperNodeToNewCands(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, unsigned* hedge_id, int* nHedgeId, 
                                                        int* nMatch, int* nBag1, int* accW, int* cand_counts, int* candidates, int totalsize, int* keys, int* weight_vals) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        int hid = hedge_id[tid];
        if (cand_counts[hid]) {
            if (weight_vals[hedges[E_OFFSET1(hedgeN)]] < INT_MAX) {
                int represent = keys[hedges[E_OFFSET1(hedgeN)]];
                int parent = nodes[represent - hedgeN + N_PARENT1(nodeN)];
                int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                int hedgeid = nHedgeId[adj_list[tid] - hedgeN];
                if (candidates[adj_list[tid] - hedgeN] && idnum == hedgeid) {
                    int cur_weight = nodes[adj_list[tid] - hedgeN + N_WEIGHT1(nodeN)];
                    if (cur_weight + accW[parent - hedgeN] <= LIMIT) {
                        nBag1[adj_list[tid] - hedgeN] = 1;
                        nMatch[adj_list[tid] - hedgeN] = 1;
                        nodes[adj_list[tid] - hedgeN + N_PARENT1(nodeN)] = parent;
                        nHedgeId[adj_list[tid] - hedgeN] = nHedgeId[represent - hedgeN];
                    }
                }
            }
        }
    }
}


__global__ void selectRepresentNodes(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, 
                                    int* eMatch, int* nMatch, int* nPrior, 
                                    int* t_best, int* t_rep, int* t_count, int* keys, int* weight_vals, tmp_nodes* tNodesAttr) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN && !eMatch[tid]) {
        int best = INT_MAX;
        unsigned represent = 0;//INT_MAX;
        // int counts = 0;
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            int nmatch = nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
            if (nmatch && nPrior[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] == INT_MIN) {
                if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] < best) {
                    best = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
                    represent = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                    // tNodesAttr[tid].w_vals = best;
                    // tNodesAttr[tid].id_key = represent;
                } else if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] == best) {
                    if (adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] < represent) {
                        represent = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                        // tNodesAttr[tid].id_key = represent;
                    }
                }

                // keys[hedges[E_DEGREE1(hedgeN) + tid] + i] = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                // weight_vals[hedges[E_DEGREE1(hedgeN) + tid] + i] = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
            }
            // keys[hedges[E_DEGREE1(hedgeN) + tid] + i] = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
            // weight_vals[hedges[E_DEGREE1(hedgeN) + tid] + i] = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
        }
        t_best[tid] = best;
        t_rep[tid] = represent;
        // tNodesAttr[tid].w_vals = best;
        // tNodesAttr[tid].id_key = represent;
    }
}

__global__ void parallelFindingCandidatesForEachHedge(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                                    int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nHedgeId,// int* nPrior, int* parents,
                                                    int* cand_counts/*, int* represents, int* best, int* keys, int* weight_vals, tmp_nodes* tNodesAttr*/) {
    int hid = blockIdx.x;
    if (hid < hedgeN && !eMatch[hid]) {
        int tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
            // if (hid == 71) {
            //     printf("$$heree!!\n");
            // }
            if (!nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                // if (hid == 71) {
                //     printf("##heree!! hedgeid:%d, idnum:%d\n", hedgeid, idnum);
                // }
                if (hedgeid == idnum) {
                    atomicAdd(&cand_counts[hid], 1);
                    candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = 1;
                    // if (hid == 71) {
                    //     printf("@@heree!!\n");
                    // }
                }
            }
            tid += blockDim.x;
        }
        // if (threadIdx.x == 0) {
        //     for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + hid]; ++i) {
        //         if (!nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN]) {
        //             int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN];
        //             unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
        //             if (hedgeid == idnum) {
        //                 cand_counts[hid]++;
        //                 candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN] = 1;
        //             }
        //         }
        //     }
        // }
        // __syncthreads();
        // if (hid == 71) {
        //     printf("blockDim:%d, count:%d, deg:%d\n", blockDim.x, cand_counts[hid], hedges[E_DEGREE1(hedgeN) + hid]);
        // }
        // if (cand_counts[hid] && best[hid] < INT_MAX) {
        //     int parent = nodes[represents[hid] - hedgeN + N_PARENT1(nodeN)];
        //     tid = threadIdx.x;
        //     while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
        //         int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
        //         unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
        //         int candidate = candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
        //         if (candidate && hedgeid == idnum) {
        //             int tmpW = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]-hedgeN + N_WEIGHT1(nodeN)];
        //             if (tmpW + accW[parent - hedgeN] <= LIMIT) {
        //                 nBag1[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = 1;
        //                 nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = 1;
        //                 // nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)] = parent;
        //                 parents[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = parent;
        //                 nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = nHedgeId[represents[tid] - hedgeN];
        //             }
        //         }
        //         tid += blockDim.x;
        //     }
        // }
    }
}

__global__ void collectNodeAttrForFurtherReduce(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, unsigned* hedge_id,
                                                int* eMatch, int* nMatch, int totalsize, tmp_nodes* tNodesAttr) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        int hid = hedge_id[tid];
        tNodesAttr[tid].id_key = adj_list[tid];
        tNodesAttr[tid].w_vals = nodes[adj_list[tid] - hedgeN + N_WEIGHT1(nodeN)];
        tNodesAttr[tid].eMatch = eMatch[hid];
        tNodesAttr[tid].nMatch = nMatch[adj_list[tid] - hedgeN];
    }
}


// template<int block_thread_num>
__global__ void parallelFindingRepresentWithReduceMin(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, unsigned* hedge_id, int* nHedgeId, 
                                        int* eMatch, int* nMatch, int* nPrior, int* weight_vals, int* keys, int totalsize) {
    int hid = blockIdx.x;
    if (hid < hedgeN && !eMatch[hid]) {
    // while (hid < hedgeN && !eMatch[hid]) {
        // if (hedges[E_DEGREE1(hedgeN) + hid] > 6000) {
        int tid = threadIdx.x;
        // int aggregate = INT_MAX;
        // while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
            // typedef cub::WarpReduce<int> WarpReduce;
            // __shared__ typename WarpReduce::TempStorage temp_storage[4];
            // int thread_data = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
            // int warp_id = threadIdx.x / 32;
            // aggregate = WarpReduce(temp_storage[warp_id]).Reduce(thread_data, cub::Min());
            
        // }
        int _minwt = INT_MAX;
        int _minid = INT_MAX;
        for (int i = tid; i < hedges[E_DEGREE1(hedgeN) + hid]; i += blockDim.x) {
            if (nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN]) {
                int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
                if (weight < _minwt) {
                    _minwt = min(_minwt, weight);
                    _minid = adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i];
                } else if (_minwt == weight) {
                    _minid = min(_minid, adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i]);
                }
            }
        }
        extern __shared__ int smem[];
        int* sm_weight = smem;
        int* sm_nodeid = smem + blockDim.x;
        sm_weight[threadIdx.x] = _minwt;
        sm_nodeid[threadIdx.x] = _minid;
        __syncthreads();
        for (int s = blockDim.x >> 1; s > 0; s >>= 1) {
            if (threadIdx.x < s) {
                if (sm_weight[threadIdx.x] > sm_weight[threadIdx.x + s]) {
                    sm_weight[threadIdx.x] = sm_weight[threadIdx.x + s];
                    sm_nodeid[threadIdx.x] = sm_nodeid[threadIdx.x + s];
                } else if (sm_weight[threadIdx.x] == sm_weight[threadIdx.x + s]) {
                    sm_nodeid[threadIdx.x] = min(sm_nodeid[threadIdx.x], sm_nodeid[threadIdx.x + s]);
                }
            }
        }

        if (!threadIdx.x) {
            weight_vals[hid] = sm_weight[0];
            keys[hid] = sm_nodeid[0];
        }
        // }
        // hid += gridDim.x;
    }
}

__global__ void parallelFindingRepresentWithAtomicMin(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, unsigned* hedge_id, int* nHedgeId, 
                                        int* eMatch, int* nMatch, int* nPrior, int* weight_vals, int totalsize, int* keys) {
    int hid = blockIdx.x;
    if (hid < hedgeN && !eMatch[hid]) {
        int tid = threadIdx.x;
#if 1
        while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
            if (nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN]) {
                int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                atomicMin(&weight_vals[hid], weight);
                // min_weight = min(min_weight, weight);
            }
            tid += blockDim.x;
        }
        __syncthreads();
        tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
            if (nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN]) {
                int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                if (weight == weight_vals[hid]) {
                    atomicMin(&keys[hid], adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]);
                }
                // min_rep = (weight == min_weight) ? (min(min_rep, adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid])) : min_rep;
            }
            tid += blockDim.x;
        }
        __syncthreads();
#else
        while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
            // unsigned mask = __ballot_sync(0xFFFFFFFF, nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] == true);
            // int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
            // weight_vals[hid] = __reduce_min_sync(mask, weight);
            unsigned mask = __ballot_sync(0xFFFFFFFF, true);
            tid += blockDim.x;
        }
        __syncthreads();
        // tid = threadIdx.x;
        // while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
        //     int isMatch = nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
        //     int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
        //     unsigned mask = __ballot_sync(0xFFFFFFFF, isMatch && weight == weight_vals[hid]);
        //     keys[hid] = __reduce_min_sync(mask, adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]);
        //     tid += blockDim.x;
        // }
        // __syncthreads();
#endif
    }
}

__global__ void parallelSelectMinWeightMinNodeId(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT,
                                                int* eMatch, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId, int* nBag1,
                                                int* represents, int* bests) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    while (tid < hedgeN && !eMatch[tid]) {
        int best = INT_MAX;
        unsigned represent = 0;
        int counts = 0;
        // bool hasProcessed = false;
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            if (!nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN]) {
                int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    counts++;
                    candidates[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = 1;
                }
            }
            else if (nPrior[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] == INT_MIN) {
                // hasProcessed = true;
                if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] < best) {
                    best = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
                    represent = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                } else if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] == best) {
                    if (adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] < represent) {
                        represent = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                    }
                }
            }
        }
        // bests[tid] = best;
        // represents[tid] = hasProcessed ? represent : represents[tid];

        if (counts) {
            if (best < INT_MAX) {
                int parent = nodes[represent-hedgeN + N_PARENT1(nodeN)];
                for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
                    int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                    unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
                    int candidate = candidates[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                    if (candidate && hedgeid == idnum) {
                        int tmpW = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_WEIGHT1(nodeN)];
                        int weight = accW[parent - hedgeN];
                        if (tmpW + weight > LIMIT) {
                            continue;
                        }
                        nBag1[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN] = 1;
                        nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN] = 1;
                        nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_PARENT1(nodeN)] = parent;
                        nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = nHedgeId[represent-hedgeN];
                    }
                }
            }
        }

        tid += blockDim.x * gridDim.x;
    }
}

__global__ void parallelMergingNodesForEachHedges0(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                                    int* eMatch, int* nMatch, int* candidates, int* nHedgeId, int* cand_counts) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN && !eMatch[tid]) {
        int counts = 0;
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            if (!nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN]) {
                int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    counts++;
                    candidates[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = 1;
                }
            }
        }
        cand_counts[tid] = counts;
    }
}

__global__ void parallelFindingRepresentForEachHedge(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                                    int* eMatch, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId, int* nBag1,// int* parents,
                                                    int* cand_counts, int* represents, int* bests/*, int* keys, int* weight_vals, tmp_nodes* tNodesAttr*/) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN && !eMatch[tid]) {
        int best = INT_MAX;
        unsigned represent = 0;//INT_MAX;//
        // int counts = 0;
        bool hasProcessed = false;
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            // if (!nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_MATCHED1(nodeN)]) {
            /*if (!nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN]) {
                int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    counts++;
                    // cand_counts[tid]++;
                    candidates[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = 1;
                    if (tid == 71) {
                        printf("dst:%d, i:%d\n", adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i], i);
                    }
                }
            }

            else*/ if (nPrior[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] == INT_MIN) {
                hasProcessed = true;
                if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] < best) {
                    best = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
                    represent = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                } else if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] == best) {
                    if (adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] < represent) {
                        represent = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                    }
                }
            }
        }
        bests[tid] = best;
        represents[tid] = hasProcessed ? represent : represents[tid];
        // cand_counts[tid] = counts;
        // if (cand_counts[tid] && best[tid] < INT_MAX) {
        // if (cand_counts[tid] && best < INT_MAX) {
        //     // int parent = nodes[represents[tid] - hedgeN + N_PARENT1(nodeN)];
        //     int parent = nodes[represent - hedgeN + N_PARENT1(nodeN)];
        //     for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
        //         int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
        //         unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
        //         int candidate = candidates[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
        //         if (candidate && hedgeid == idnum) {
        //             int tmpW = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_WEIGHT1(nodeN)];
        //             int weight = accW[parent - hedgeN];
        //             if (tmpW + weight <= LIMIT) {
        //                 nBag1[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN] = 1;
        //                 nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN] = 1;
        //                 // parents[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = parent;
        //                 nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] = parent;
        //                 // nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = nHedgeId[represents[tid] - hedgeN];
        //                 nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = nHedgeId[represent - hedgeN];
        //             }
        //         }
        //     }
        // }
    }
}

__global__ void parallelMergingNodesForEachHedge(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                                    int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nHedgeId,// int* nPrior, int* parents,
                                                    int* cand_counts, int* represents, int* bests/*, int* keys, int* weight_vals, tmp_nodes* tNodesAttr*/) {
    int hid = blockIdx.x;
    if (hid < hedgeN && !eMatch[hid]) {
        if (cand_counts[hid] && bests[hid] < INT_MAX) {
            int tid = threadIdx.x;
            int parent = nodes[represents[hid] - hedgeN + N_PARENT1(nodeN)];
            while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                int candidate = candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                if (candidate && hedgeid == idnum) {
                    int tmpW = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                    if (tmpW + accW[parent - hedgeN] <= LIMIT) {
                        nBag1[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
                        nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
                        nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)] = parent;
                        nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = nHedgeId[represents[hid] - hedgeN];
                    }
                }
                tid += blockDim.x;
            }
        }
    }
}

__global__ void parallelMergingNodesForEachAdjElement(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT,
                                                int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nHedgeId,// int* nPrior, int* parents,
                                                int* cand_counts, int* represents, int* bests, unsigned* hedge_id, int totalsize) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        int hid = hedge_id[tid];
        if (!eMatch[hid] && cand_counts[hid] && bests[hid] < INT_MAX) {
            int parent = nodes[represents[hid] - hedgeN + N_PARENT1(nodeN)];
            int hedgeid = nHedgeId[adj_list[tid] - hedgeN];
            unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
            int candidate = candidates[adj_list[tid] - hedgeN];
            if (candidate && hedgeid == idnum) {
                int tmpW = nodes[adj_list[tid] - hedgeN + N_WEIGHT1(nodeN)];
                if (tmpW + accW[parent - hedgeN] <= LIMIT) {
                    nBag1[adj_list[tid]-hedgeN] = 1;
                    nMatch[adj_list[tid]-hedgeN] = 1;
                    // parents[adj_list[tid] - hedgeN] = parent;
                    nodes[adj_list[tid] - hedgeN + N_PARENT1(nodeN)] = parent;
                    nHedgeId[adj_list[tid] - hedgeN] = nHedgeId[represents[hid] - hedgeN];
                }
            }
        }
    }
}

__global__ void mergeMoreNodesAcrossHyperedges(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, 
                                                int LIMIT, int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId/*, 
                                                int* t_best, int* t_rep, int* t_count, int lo, int hi, int* hedgelist*/) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    // printf("%d\n", tid);
    // tid = 6961113;
    if (tid < hedgeN) {
    // while (tid < hedgeN) {
        // if (hedges[tid + E_MATCHED1(hedgeN)]) {
        if (eMatch[tid]) {
            // tNodesInfo[tid].eMatch = 1;
            // tNodesInfo[tid].hedgesize = hedges[E_DEGREE1(hedgeN) + tid];
            return;
        }
        int best = INT_MAX;
        unsigned represent = 0;//INT_MAX;
        int counts = 0;
        // if (hedges[E_DEGREE1(hedgeN) + tid] >= 1000 && hedges[E_DEGREE1(hedgeN) + tid] < 10000) {
        //     hedgelist[atomicAdd(&t_count[0], 1)] = tid;
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            // if (!nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_MATCHED1(nodeN)]) {
            if (!nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN]) {
                // unsigned int hedgeid = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_HEDGEID1(nodeN)];
                int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    counts++;
                    // nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_MORE_UPDATE1(nodeN)] = true;
                    candidates[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = 1;
                }
            }
            // else if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_PRIORITY1(nodeN)] == INT_MIN) {
            else if (nPrior[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] == INT_MIN) {
                // t_count[tid]++;
                if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] < best) {
                    best = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
                    represent = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                } else if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] == best) {
                    if (adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] < represent) {
                        represent = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                    }
                }
            }
        }
        // t_best[tid] = best;
        // t_rep[tid] = represent;
        // t_count[tid] = counts;
        // tNodesInfo[tid].eMatch = 0;
        // tNodesInfo[tid].hedgesize = hedges[E_DEGREE1(hedgeN) + tid];
        if (counts) {
            if (best < INT_MAX) {
                int parent = nodes[represent-hedgeN + N_PARENT1(nodeN)];
                for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
                    // unsigned int hedgeid = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_HEDGEID1(nodeN)];
                    int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                    unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
                    // if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_MORE_UPDATE1(nodeN)] && hedgeid == idnum) {
                    int candidate = candidates[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                    if (candidate && hedgeid == idnum) {
                        int tmpW = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
                        // int weight = nodes[parent-hedgeN + N_TMPW1(nodeN)];
                        int weight = accW[parent - hedgeN];
                        if (tmpW + weight > LIMIT) {
                            // real_access_size[tid] = i;
                            // break;
                            continue;
                        }
                        // nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_TMPBAG1(nodeN)] = 1;
                        nBag1[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN] = 1;
                        // nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_MATCHED1(nodeN)] = 1;
                        nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN] = 1;
                        nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_PARENT1(nodeN)] = parent;
                        // nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_HEDGEID1(nodeN)] 
                        //         = nodes[represent-hedgeN + N_HEDGEID1(nodeN)];
                        // atomicAdd(&accW[parent - hedgeN], tmpW);
                        nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = nHedgeId[represent-hedgeN];
                    }
                }
            }
        }
        // }
        // tid += blockDim.x * gridDim.x;
    }
}

__global__ void countingHyperedgesRetainInCoarserLevel(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int* newHedgeN, 
                                                    int* eInBag, int* eMatch, int* nMatch) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        // if (hedges[tid + E_MATCHED1(hedgeN)]) {
        if (eMatch[tid]) {
            return;
        }
        unsigned nodeid;
        int count = 0;
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            // if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_MATCHED1(nodeN)]) {
            if (nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN]) {
                if (count == 0) {
                    nodeid = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_PARENT1(nodeN)];
                    count++;
                } else if (nodeid != nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_PARENT1(nodeN)]) {
                    count++;
                    break;
                }
            } else {
                count = 0;
                break;
            }
        }
        if (count == 1) {
            // hedges[tid + E_MATCHED1(hedgeN)] = 1;
            eMatch[tid] = 1;
        } else {
            // hedges[tid + E_INBAG1(hedgeN)] = 1;//true;
            eInBag[tid] = 1;
            atomicAdd(&newHedgeN[0], 1);
            // hedges[tid + E_MATCHED1(hedgeN)] = 1;
            eMatch[tid] = 1;
        }
    }
}

__global__ void selfMergeSingletonNodes(int* nodes, int nodeN, int hedgeN, int* newNodeN, 
                                        int* nBag1, int* nBag, int* accW, int* nMatch, int* nHedgeId, unsigned* isSelfMergeNodes) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        // if (nodes[N_TMPBAG1(nodeN) + tid]) {
        if (nBag1[tid]) {
            // atomicAdd(&nodes[N_TMPW1(nodeN) + nodes[tid + N_PARENT1(nodeN)] - hedgeN], nodes[N_WEIGHT1(nodeN) + tid]);
            atomicAdd(&accW[nodes[tid + N_PARENT1(nodeN)] - hedgeN], nodes[N_WEIGHT1(nodeN) + tid]);
        }
        // if (!nodes[N_MATCHED1(nodeN) + tid]) {
        if (!nMatch[tid]) {
            // nodes[tid + N_INBAG1(nodeN)] = 1;//true;
            nBag[tid] = 1;
            isSelfMergeNodes[tid] = 1;
            // if (tid == 9544 - 9449) {
            //     printf("here!!\n");
            // }
            atomicAdd(&newNodeN[0], 1);
            // nodes[tid + N_MATCHED1(nodeN)] = 1;
            nMatch[tid] = 1;
            nodes[tid + N_PARENT1(nodeN)] = tid + hedgeN;
            // nodes[tid + N_HEDGEID1(nodeN)] = INT_MAX;
            nHedgeId[tid] = INT_MAX;
            // nodes[N_TMPW1(nodeN) + tid] = nodes[N_WEIGHT1(nodeN) + tid];
            accW[tid] = nodes[N_WEIGHT1(nodeN) + tid];
        }
    }
}

__global__ void setupNodeMapping(int* nodes, int nodeN, int hedgeN, int* newNodes, int newNodeN, int newHedgeN, 
                                int* nBag, int* nNextId, int* accW, int* accW1) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        // if (nodes[N_INBAG1(nodeN) + tid]) {
        if (nBag[tid]) {
            // newNodes[nodes[N_MAP_PARENT1(nodeN) + tid] - newHedgeN + N_TMPW1(newNodeN)] = nodes[N_TMPW1(nodeN) + tid];
            // newNodes[nNextId[tid] - newHedgeN + N_TMPW1(newNodeN)] = nodes[N_TMPW1(nodeN) + tid];
            accW1[nNextId[tid] - newHedgeN] = accW[tid];
        }
    }
}

__global__ void updateCoarsenNodeId(int* nodes, int nodeN, int hedgeN, int* nNextId) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        int index = nodes[N_PARENT1(nodeN) + tid] - hedgeN;
        // nodes[N_PARENT1(nodeN) + tid] = nodes[N_MAP_PARENT1(nodeN) + index]; // mapParentTO
        nodes[N_PARENT1(nodeN) + tid] = nNextId[index];
    }
}

__global__ void markParentsForPinsLists(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, 
                                        int maxHedgeSize, /*int* checkCounts, int* adj_elem_cnt*/unsigned* isSelfMergeNodes, int* dupCnts) {
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidy = blockIdx.y * blockDim.y + threadIdx.y;
    if (tidx < hedgeN) {
        // if (eInBag[tidx] && hedges[tidx + E_DEGREE1(hedgeN)] == maxHedgeSize) {
        if (eInBag[tidx]) {
            // unsigned h_id = hedges[tidx + E_NEXTID1(hedgeN)];
            unsigned h_id = next_id[tidx];
            int id = h_id;
            while (tidy < hedges[tidx + E_DEGREE1(hedgeN)]) {
                unsigned cur_nid = adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] - hedgeN;
                // if (isSelfMergeNodes[cur_nid] == 1) {
                //     isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] = 1;
                //     // atomicAdd(&dupCnts[0], 1);
                //     atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                //     atomicAdd(&newTotalPinSize[0], 1);
                //     tidy += gridDim.y * blockDim.y;
                //     continue;
                // }
                // else {
                // if (isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] == 1) {
                //     atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                //     atomicAdd(&newTotalPinSize[0], 1);
                //     tidy += gridDim.y * blockDim.y;
                //     continue;
                // }
                // unsigned cur_nid = adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] - hedgeN;
                // unsigned pid = nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] - hedgeN + N_PARENT1(nodeN)];
                unsigned pid = nodes[cur_nid + N_PARENT1(nodeN)];
                bool isfind = false;
                for (int i = 0; i < tidy; i++) {
                    if (nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                        isfind = true;
                        break;
                    }
                }
                if (!isfind) {
                    isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] = 1;//true;
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                }
                // }
                tidy += gridDim.y * blockDim.y;
            }
        }
    }
}

__global__ void markParentsForPinsLists1(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int maxHedgeSize) {
    int tidx = blockIdx.x;
    if (tidx < hedgeN) {
        // if (eInBag[tidx] && hedges[tidx + E_DEGREE1(hedgeN)] < 100) {
        if (eInBag[tidx]) {
            // unsigned h_id = hedges[tidx + E_NEXTID1(hedgeN)];
            unsigned h_id = next_id[tidx];
            int id = h_id;
            int tid = threadIdx.x;
            while (tid < hedges[tidx + E_DEGREE1(hedgeN)]) {
                unsigned pid = nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)];
                // unsigned pid = nodes[tidx + N_PARENT1(nodeN)];
                bool isfind = false;
                for (int i = 0; i < tid; i++) {
                    if (nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                    // if (nodes[id + N_PARENT1(nodeN)] == pid) {
                        isfind = true;
                        // atomicAdd(&checkCounts[0], i);
                        break;
                    }
                }
                // parlist[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] = pid;
                if (!isfind) {
                    isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tid] = 1;//true;
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                }
                tid += blockDim.x;
            }
        }
    }
}

__global__ void markDuplicateWithBasePattern(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag) {
    int tidx = threadIdx.x + blockDim.x * blockIdx.x;
    if (tidx < hedgeN) {
        if (eInBag[tidx]) {
            unsigned h_id = next_id[tidx];
            int id = h_id;
            int beg_off = hedges[tidx + E_OFFSET1(hedgeN)];
            int cur_deg = hedges[tidx + E_DEGREE1(hedgeN)];

            for (int tid = beg_off; tid < beg_off + cur_deg; tid++) {
                unsigned pid = nodes[adj_list[tid] - hedgeN + N_PARENT1(nodeN)];
                // unsigned pid = nodes[adj_list[beg_off + tid] - hedgeN + N_PARENT1(nodeN)];
                bool isfind = false;
                for (int i = beg_off; i < tid; i++) {
                    if (nodes[adj_list[i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                    // if (nodes[adj_list[beg_off + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                        isfind = true;
                        break;
                    }
                }
                if (!isfind) {
                    isDuplica[tid] = 1;
                    newHedges[id + E_DEGREE1(newHedgeN)]++;
                    atomicAdd(&newTotalPinSize[0], 1);
                }
            }
        }
    }
}

#if 0
// __global__ void setupNextLevelAdjacentList(int* hedges, int* nodes, unsigned* adj_list, bool* par_list, int hedgeN, int nodeN,
//                                             int* newHedges, int* newNodes, unsigned* newAdjList, 
//                                             int newNodeN, int newHedgeN, unsigned N, int* newTotalNodeDeg, 
//                                             int* maxDegree, int* minDegree, int* maxWeight, int* minWeight) {
__global__ void setupNextLevelAdjacentList(int* hedges, int* nodes, unsigned* adj_list, unsigned* par_list, int hedgeN, int nodeN,
                                            int* newHedges, int* newNodes, unsigned* newAdjList, 
                                            int newNodeN, int newHedgeN, unsigned N, int* newTotalNodeDeg, 
                                            int* maxDegree, int* minDegree, int* maxWeight, int* minWeight) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < N) {
        if (tid < hedgeN) {
            if (hedges[E_INBAG1(hedgeN) + tid]) {
                unsigned h_id = hedges[tid + E_NEXTID1(hedgeN)];
                newHedges[E_IDNUM1(newHedgeN) + h_id] = hedges[E_IDNUM1(hedgeN) + tid];
                hedges[E_ELEMID1(hedgeN) + tid] = h_id;
                int id = hedges[E_ELEMID1(hedgeN) + tid];
                int count = 0;
                for (unsigned j = 0; j < hedges[tid + E_DEGREE1(hedgeN)]; ++j) {
                    // if (par_list[hedges[tid + E_OFFSET1(hedgeN)] + j] == true) {
                    if (par_list[hedges[tid + E_OFFSET1(hedgeN)] + j] == 1) {
                        unsigned pid = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + j] - hedgeN + N_PARENT1(nodeN)];
                        newAdjList[newHedges[E_OFFSET1(newHedgeN) + id] + count] = pid;
                        count++;
                        atomicAdd(&newNodes[N_DEGREE1(newNodeN) + (pid - newHedgeN)], 1);
                        atomicAdd(&newTotalNodeDeg[0], 1);
                    }
                }
                atomicMin(&minDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                atomicMax(&maxDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                newHedges[E_PRIORITY1(newHedgeN) + id] = INT_MAX;
            }
        } else { // coarsenHgr->nodeNum
            int index = tid - hedgeN;
            newNodes[N_PRIORITY1(newNodeN) + index] = INT_MAX;
            newNodes[N_RAND1(newNodeN) + index] = INT_MAX;
            newNodes[N_HEDGEID1(newNodeN) + index] = INT_MAX;
            newNodes[N_ELEMID1(newNodeN) + index] = index + newHedgeN;
            newNodes[N_WEIGHT1(newNodeN) + index] = newNodes[N_TMPW1(newNodeN) + index];
            newNodes[N_TMPW1(newNodeN) + index] = 0;
            atomicMin(&minWeight[0], newNodes[N_WEIGHT1(newNodeN) + index]);
            atomicMax(&maxWeight[0], newNodes[N_WEIGHT1(newNodeN) + index]);
        }
    }
}

__global__ void setupNextLevelAdjacentList1(int* hedges, int* nodes, unsigned* adj_list, unsigned* par_list, int hedgeN, int nodeN,
                                            int* newHedges, int* newNodes, unsigned* newAdjList, unsigned* pinsHedgeidList,
                                            int newNodeN, int newHedgeN, unsigned N, int* newTotalNodeDeg, 
                                            int* maxDegree, int* minDegree, int* maxWeight, int* minWeight) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < N) {
        if (tid < hedgeN) {
            if (hedges[E_INBAG1(hedgeN) + tid]) {
                unsigned h_id = hedges[tid + E_NEXTID1(hedgeN)];
                newHedges[E_IDNUM1(newHedgeN) + h_id] = hedges[E_IDNUM1(hedgeN) + tid];
                hedges[E_ELEMID1(hedgeN) + tid] = h_id;
                int id = hedges[E_ELEMID1(hedgeN) + tid];
                int count = 0;
                for (unsigned j = 0; j < hedges[tid + E_DEGREE1(hedgeN)]; ++j) {
                    // if (par_list[hedges[tid + E_OFFSET1(hedgeN)] + j] == true) {
                    if (par_list[hedges[tid + E_OFFSET1(hedgeN)] + j] == 1) {
                        unsigned pid = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + j] - hedgeN + N_PARENT1(nodeN)];
                        newAdjList[newHedges[E_OFFSET1(newHedgeN) + id] + count] = pid;
                        pinsHedgeidList[newHedges[E_OFFSET1(newHedgeN) + id] + count] = id; // add here!
                        count++;
                        atomicAdd(&newNodes[N_DEGREE1(newNodeN) + (pid - newHedgeN)], 1);
                        atomicAdd(&newTotalNodeDeg[0], 1);
                    }
                }
                atomicMin(&minDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                atomicMax(&maxDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                newHedges[E_PRIORITY1(newHedgeN) + id] = INT_MAX;
            }
        } else { // coarsenHgr->nodeNum
            int index = tid - hedgeN;
            newNodes[N_PRIORITY1(newNodeN) + index] = INT_MAX;
            newNodes[N_RAND1(newNodeN) + index] = INT_MAX;
            newNodes[N_HEDGEID1(newNodeN) + index] = INT_MAX;
            newNodes[N_ELEMID1(newNodeN) + index] = index + newHedgeN;
            newNodes[N_WEIGHT1(newNodeN) + index] = newNodes[N_TMPW1(newNodeN) + index];
            newNodes[N_TMPW1(newNodeN) + index] = 0;
            atomicMin(&minWeight[0], newNodes[N_WEIGHT1(newNodeN) + index]);
            atomicMax(&maxWeight[0], newNodes[N_WEIGHT1(newNodeN) + index]);
        }
    }
}
#endif

#if 0
__global__ void markDuplicasInNextLevelAdjacentList(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN,
                                                    int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize) {
    
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidy = blockIdx.y * blockDim.y + threadIdx.y;
    while (tidx < hedgeN) {
        if (hedges[E_INBAG1(hedgeN) + tidx]) {
            unsigned h_id = hedges[tidx + E_NEXTID1(hedgeN)];
            int id = h_id;
            tidy = blockIdx.y * blockDim.y + threadIdx.y;
            while (tidy < hedges[tidx + E_DEGREE1(hedgeN)]) {
                unsigned curr_loc = hedges[tidx + E_OFFSET1(hedgeN)] + tidy;
                unsigned candidate = nodes[adj_list[curr_loc] - hedgeN + N_PARENT1(nodeN)] - newHedgeN;
                // unsigned curr_loc = offset[tidx] + tidy;
                unsigned bitset_idx = candidate / 32;
                unsigned bit_offset = candidate & 31;
                unsigned shift_bits = 31 - bit_offset;
                unsigned bitset_loc = (tidx % num_hedges) * bitLen + bitset_idx;
                int cur_bit = atomicOr(&bitset[bitset_loc], (0x80000000 >> bit_offset));
                int extract_bit_val = (cur_bit & (1 << shift_bits)) >> shift_bits;
                if (extract_bit_val == 0) {
                    isDuplica[curr_loc] = 1;
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                } 
                // else {
                //     isDuplica[curr_loc] = 0;
                // }
                tidy += gridDim.y * blockDim.y;
            }
            // if (threadIdx.x == 0)   newHedges[E_PRIORITY1(newHedgeN) + id] = INT_MAX;
            __syncthreads();
            tidy = blockIdx.y * blockDim.y + threadIdx.y;
            while (tidy < hedges[tidx + E_DEGREE1(hedgeN)]) {
                unsigned curr_loc = hedges[tidx + E_OFFSET1(hedgeN)] + tidy;
                unsigned candidate = nodes[adj_list[curr_loc] - hedgeN + N_PARENT1(nodeN)] - newHedgeN;
                // unsigned curr_loc = offset[tidx] + tidy;
                unsigned bitset_idx = candidate / 32;
                unsigned bitset_loc = (tidx % num_hedges) * bitLen + bitset_idx;
                bitset[bitset_loc] = 0;
                tidy += gridDim.y * blockDim.y;
            }
            // if (threadIdx.y == 0) {
            //     for (int i = 0; i < bitLen; ++i) {
            //         bitset[(tidx % num_hedges) * bitLen + i] = 0;
            //     }
            // }
            __syncthreads();
        }
        tidx += gridDim.x * blockDim.x;
    }
}

__global__ void markDuplicasInNextLevelAdjacentList_1(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN,
                                                    int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize) {
    
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidy = blockIdx.y * blockDim.y + threadIdx.y;
    if (tidx < hedgeN) {
        if (hedges[E_INBAG1(hedgeN) + tidx]) {
            unsigned h_id = hedges[tidx + E_NEXTID1(hedgeN)];
            int id = h_id;
            tidy = blockIdx.y * blockDim.y + threadIdx.y;
            while (tidy < hedges[tidx + E_DEGREE1(hedgeN)]) {
                unsigned curr_loc = hedges[tidx + E_OFFSET1(hedgeN)] + tidy;
                unsigned candidate = nodes[adj_list[curr_loc] - hedgeN + N_PARENT1(nodeN)] - newHedgeN;
                unsigned bitset_loc = (tidx % num_hedges) * bitLen + candidate;
                int cur_bit = atomicOr(&bitset[bitset_loc], 1);
                if (cur_bit == 0) {
                    isDuplica[curr_loc] = 1;
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                }
                tidy += gridDim.y * blockDim.y;
            }

        }
        // tidx += gridDim.x * blockDim.x;
    }
}

#endif

__global__ void markDuplicasInNextLevelAdjacentList_2(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int* next_id, int* eInBag,
                                                    int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize) {
    
    int tidx = blockIdx.x;
    if (eInBag[tidx]) {
        unsigned h_id = next_id[tidx];
        int id = h_id;
        int tid = threadIdx.x;
        while (tid < hedges[tidx + E_DEGREE1(hedgeN)]) {
            unsigned curr_loc = hedges[tidx + E_OFFSET1(hedgeN)] + tid;
            unsigned candidate = nodes[adj_list[curr_loc] - hedgeN + N_PARENT1(nodeN)] - newHedgeN;
            unsigned bitset_idx = candidate / 32;
            unsigned bitset_loc = tidx * bitLen + bitset_idx;
            unsigned bit_offset = candidate & 31;
            int cur_bit = atomicOr(&bitset[bitset_loc], (0x80000000 >> bit_offset));
            unsigned shift_bits = 31 - bit_offset;
            int extract_bit_val = (cur_bit & (1 << shift_bits)) >> shift_bits;
            // atomicAdd(&checkCounts[0], 1);
            if (extract_bit_val == 0) {
                isDuplica[curr_loc] = 1;
                atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                atomicAdd(&newTotalPinSize[0], 1);
            }
            tid += blockDim.x;
        }

    }
}

__global__ void markDuplicasInNextLevelAdjacentList_3(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int* next_id, int* eInBag,
                                                    int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize, int maxHedgeSize/*, int* checkCounts*/) {
    int tidx = blockIdx.x;
    while (tidx < hedgeN) {
        // if (eInBag[tidx] && hedges[tidx + E_DEGREE1(hedgeN)] >= 100) {
        if (eInBag[tidx]) {
            // unsigned h_id = hedges[tidx + E_NEXTID1(hedgeN)];
            unsigned h_id = next_id[tidx];
            int id = h_id;
            int tid = threadIdx.x;
            // if (threadIdx.x == 0 && hedges[tidx + E_DEGREE1(hedgeN)] == 1331) {
            //     printf("here!!!\n");
            // }
            while (tid < hedges[tidx + E_DEGREE1(hedgeN)]) {
                unsigned curr_loc = hedges[tidx + E_OFFSET1(hedgeN)] + tid;
                unsigned candidate = nodes[adj_list[curr_loc] - hedgeN + N_PARENT1(nodeN)] - newHedgeN;
                unsigned bitset_idx = candidate / 32;
                unsigned bit_offset = candidate & 31;
                unsigned bitset_loc = (tidx % num_hedges) * bitLen + bitset_idx;
                int cur_bit = atomicOr(&bitset[bitset_loc], (0x80000000 >> bit_offset));
                unsigned shift_bits = 31 - bit_offset;
                int extract_bit_val = (cur_bit & (1 << shift_bits)) >> shift_bits;
                // atomicAdd(&checkCounts[0], 1);
                if (extract_bit_val == 0) {
                    isDuplica[curr_loc] = 1;
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                }
                tid += blockDim.x;
            }
            __syncthreads();
            tid = threadIdx.x;
            while (tid < hedges[tidx + E_DEGREE1(hedgeN)]) {
                unsigned curr_loc = hedges[tidx + E_OFFSET1(hedgeN)] + tid;
                unsigned candidate = nodes[adj_list[curr_loc] - hedgeN + N_PARENT1(nodeN)] - newHedgeN;
                unsigned bitset_idx = candidate / 32;
                unsigned bitset_loc = (tidx % num_hedges) * bitLen + bitset_idx;
                bitset[bitset_loc] = 0;
                tid += blockDim.x;
            }
            __syncthreads();
        }
        tidx += gridDim.x;
    }
}

__global__ void fillNextLevelAdjacentListWithoutDuplicates0(
                                            int* hedges, int* nodes, unsigned* adj_list, unsigned* par_list, int hedgeN, int nodeN,
                                            int* newHedges, int* newNodes, unsigned* newAdjList, unsigned* pinsHedgeidList, int* next_id, int* eInBag,
                                            int newNodeN, int newHedgeN, unsigned N, int* newTotalNodeDeg, 
                                            int* maxDegree, int* minDegree, int* maxWeight, int* minWeight,
                                            int* sdv, long double avg) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        // if (hedges[E_INBAG1(hedgeN) + tid]) {
        if (eInBag[tid]) {
            // unsigned h_id = hedges[tid + E_NEXTID1(hedgeN)];
            unsigned h_id = next_id[tid];
            newHedges[E_IDNUM1(newHedgeN) + h_id] = hedges[E_IDNUM1(hedgeN) + tid];
            // hedges[E_ELEMID1(hedgeN) + tid] = h_id;
            int id = h_id;//hedges[E_ELEMID1(hedgeN) + tid];
            int count = 0;
            for (unsigned j = 0; j < hedges[tid + E_DEGREE1(hedgeN)]; ++j) {
                if (par_list[hedges[tid + E_OFFSET1(hedgeN)] + j] == 1) {
                    unsigned pid = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + j] - hedgeN + N_PARENT1(nodeN)];
                    newAdjList[newHedges[E_OFFSET1(newHedgeN) + id] + count] = pid;
                    pinsHedgeidList[newHedges[E_OFFSET1(newHedgeN) + id] + count] = id; // add here!
                    count++;
                    atomicAdd(&newNodes[N_DEGREE1(newNodeN) + (pid - newHedgeN)], 1);
                    atomicAdd(&newTotalNodeDeg[0], 1);
                }
            }
            atomicMin(&minDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
            atomicMax(&maxDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
            // newHedges[E_PRIORITY1(newHedgeN) + id] = INT_MAX;
            // int diff = (int)(newHedges[E_DEGREE1(newHedgeN) + id] - avg);
            // atomicAdd(&sdv[0], diff * diff);
        }
    }
}

#if 0
__global__ void fillNextLevelAdjacentListWithoutDuplicates(
                                        int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, 
                                        int hedgeN, int nodeN, int* newHedges, int* newNodes, unsigned* newAdjList, 
                                        int newNodeN, int newHedgeN, int* newTotalNodeDeg, 
                                        int* maxDegree, int* minDegree, int* newAdjListCounter) {
    // int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidx = blockIdx.x;
    if (tidx < hedgeN) {
    // while (tidx < hedgeN) {
        if (hedges[E_INBAG1(hedgeN) + tidx]) {
            unsigned h_id = hedges[tidx + E_NEXTID1(hedgeN)];
            newHedges[E_IDNUM1(newHedgeN) + h_id] = hedges[E_IDNUM1(hedgeN) + tidx];
            hedges[E_ELEMID1(hedgeN) + tidx] = h_id;
            int id = h_id;
            int tid = threadIdx.x;
            while (tid < hedges[tidx + E_DEGREE1(hedgeN)]) {
                if (isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tid] == 1) {
                    unsigned pid = nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)];
                    newAdjList[newHedges[E_OFFSET1(newHedgeN) + id] + atomicAdd(&newAdjListCounter[id], 1)] = pid;
                    atomicAdd(&newNodes[N_DEGREE1(newNodeN) + (pid - newHedgeN)], 1);
                    atomicAdd(&newTotalNodeDeg[0], 1);
                }
                tid += blockDim.x;
            }
            __syncthreads();
            if (threadIdx.x == 0) {
                atomicMin(&minDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                atomicMax(&maxDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                newHedges[E_PRIORITY1(newHedgeN) + id] = INT_MAX;
            }
        }
        // tidx += gridDim.x * blockDim.x;
    }
}

__global__ void fillNextLevelAdjacentListWithoutDuplicates1(
                                        int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, 
                                        int hedgeN, int nodeN, int* newHedges, int* newNodes, unsigned* newAdjList, 
                                        int newNodeN, int newHedgeN, int* newTotalNodeDeg, 
                                        int* maxDegree, int* minDegree, int* newAdjListCounter) {
    int tidx = blockIdx.x;
    while (tidx < hedgeN) {
        if (hedges[E_INBAG1(hedgeN) + tidx]) {
            unsigned h_id = hedges[tidx + E_NEXTID1(hedgeN)];
            newHedges[E_IDNUM1(newHedgeN) + h_id] = hedges[E_IDNUM1(hedgeN) + tidx];
            hedges[E_ELEMID1(hedgeN) + tidx] = h_id;
            int id = h_id;
            int tid = threadIdx.x;
            while (tid < hedges[tidx + E_DEGREE1(hedgeN)]) {
                if (isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tid] == 1) {
                    unsigned pid = nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)];
                    newAdjList[newHedges[E_OFFSET1(newHedgeN) + id] + atomicAdd(&newAdjListCounter[id], 1)] = pid;
                    atomicAdd(&newNodes[N_DEGREE1(newNodeN) + (pid - newHedgeN)], 1);
                    atomicAdd(&newTotalNodeDeg[0], 1);
                }
                tid += blockDim.x;
            }
            __syncthreads();
            if (threadIdx.x == 0) {
                atomicMin(&minDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                atomicMax(&maxDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                newHedges[E_PRIORITY1(newHedgeN) + id] = INT_MAX;
            }
        }
        tidx += gridDim.x;
    }
}
#endif

__global__ void fillNextLevelAdjacentListWithoutDuplicates2(
                                        int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int* newNodes, unsigned* newAdjList, unsigned* pinsHedgeidList, int* next_id, int* eInBag,
                                        int newNodeN, int newHedgeN, int* newTotalNodeDeg, 
                                        int* maxDegree, int* minDegree, int* newAdjListCounter, 
                                        int* sdv, long double avg) {
    int tidx = blockIdx.x;
    if (tidx < hedgeN) {
        // if (hedges[E_INBAG1(hedgeN) + tidx]) {
        if (eInBag[tidx]) {
            // unsigned h_id = hedges[tidx + E_NEXTID1(hedgeN)];
            unsigned h_id = next_id[tidx];
            newHedges[E_IDNUM1(newHedgeN) + h_id] = hedges[E_IDNUM1(hedgeN) + tidx];
            // hedges[E_ELEMID1(hedgeN) + tidx] = h_id;
            int id = h_id;
            int tid = threadIdx.x;
            while (tid < hedges[tidx + E_DEGREE1(hedgeN)]) {
                if (isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tid] == 1) {
                    unsigned pid = nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)];
                    int count = atomicAdd(&newAdjListCounter[id], 1);
                    newAdjList[newHedges[E_OFFSET1(newHedgeN) + id] + count] = pid;
                    pinsHedgeidList[newHedges[E_OFFSET1(newHedgeN) + id] + count] = id;
                    atomicAdd(&newNodes[N_DEGREE1(newNodeN) + (pid - newHedgeN)], 1);
                    atomicAdd(&newTotalNodeDeg[0], 1);
                }
                tid += blockDim.x;
            }
            __syncthreads();
            if (threadIdx.x == 0) {
                atomicMin(&minDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                atomicMax(&maxDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                // newHedges[E_PRIORITY1(newHedgeN) + id] = INT_MAX;
                // int diff = (int)(newHedges[E_DEGREE1(newHedgeN) + id] - avg);
                // atomicAdd(&sdv[0], diff * diff);
            }
        }
    }
}

__global__ void fillNextLevelAdjacentList(
                                        int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, 
                                        int hedgeN, int nodeN, int* newHedges, int* newNodes, unsigned* newAdjList, 
                                        int newNodeN, int newHedgeN, int* newTotalNodeDeg, 
                                        int* maxDegree, int* minDegree, int* newAdjListCounter, unsigned* offset) {
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    if (tidx < hedgeN) {
        // if (hedges[E_INBAG1(hedgeN) + tidx]) {
        //     unsigned h_id = hedges[tidx + E_NEXTID1(hedgeN)];
        //     newHedges[E_IDNUM1(newHedgeN) + h_id] = hedges[E_IDNUM1(hedgeN) + tidx];
        //     hedges[E_ELEMID1(hedgeN) + tidx] = h_id;
        //     int id = h_id;
        //     int tidy = blockIdx.y * blockDim.y + threadIdx.y;
        //     while (tidy < hedges[tidx + E_DEGREE1(hedgeN)]) {
        //         if (isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] == 1) {
        //             unsigned pid = nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] - hedgeN + N_PARENT1(nodeN)];
        //             newAdjList[newHedges[E_OFFSET1(newHedgeN) + id] + offset[hedges[tidx + E_OFFSET1(hedgeN)] + tidy]] = pid;
        //         }
        //         tidy += gridDim.y * blockDim.y;
        //     }
        //     __syncthreads();
        //     tidy = blockIdx.y * blockDim.y + threadIdx.y;
        //     if (tidy == 0) {
        //         atomicMin(&minDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
        //         atomicMax(&maxDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
        //         newHedges[E_PRIORITY1(newHedgeN) + id] = INT_MAX;
        //     }
        // }
    }
}

__global__ void setCoarsenNodesProperties(int* newNodes, int newNodeN, int newHedgeN, int* maxWeight, int* minWeight,
                                        int* accW1) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < newNodeN) {
        // newNodes[N_PRIORITY1(newNodeN) + tid] = INT_MAX;
        // newNodes[N_RAND1(newNodeN) + tid] = INT_MAX;
        // newNodes[N_HEDGEID1(newNodeN) + tid] = INT_MAX;
        newNodes[N_ELEMID1(newNodeN) + tid] = tid + newHedgeN;
        // newNodes[N_WEIGHT1(newNodeN) + tid] = newNodes[N_TMPW1(newNodeN) + tid];
        // newNodes[N_TMPW1(newNodeN) + tid] = 0;
        newNodes[N_WEIGHT1(newNodeN) + tid] = accW1[tid];
        atomicMin(&minWeight[0], newNodes[N_WEIGHT1(newNodeN) + tid]);
        atomicMax(&maxWeight[0], newNodes[N_WEIGHT1(newNodeN) + tid]);
    }
}


// __global__ void getThreadNumBasedOnHedgeSize(int* hedge, int hedgeN, int* thread_num_each_hedge) {
//     int tid = blockIdx.x * blockDim.x + threadIdx.x;
//     if (tid < hedgeN) {
//         int hedgesize = hedge[tid + E_DEGREE1(hedgeN)];
//         if (hedgesize < 100) {
//             thread_num_each_hedge[tid] = 1;
//         } else if (hedgesize >= 100 && hedgesize < 1000) {
//             thread_num_each_hedge[tid] = 32;
//         } else if (hedgesize >= 1000 && hedgesize < 10000) {
//             thread_num_each_hedge[tid] = 128;
//         } else {
//             thread_num_each_hedge[tid] = 1024;
//         }
//     }
// }

__global__ void assignEachHedgeToCorrespondingKernel(int* hedge, int hedgeN, int* eMatch, int* s_cnt, int* m_cnt, int* l_cnt, int* u_cnt, 
                                                    int* s_list, int* m_list, int* l_list, int* u_list) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN && !eMatch[tid]) {
        int hedgesize = hedge[tid + E_DEGREE1(hedgeN)];
        if (hedgesize < 50) {
            s_list[atomicAdd(&s_cnt[0], 1)] = tid;
        } else if (hedgesize >= 50 && hedgesize < 1000) {
            m_list[atomicAdd(&m_cnt[0], 1)] = tid;
        } else if (hedgesize >= 1000 && hedgesize < 10000) {
            l_list[atomicAdd(&l_cnt[0], 1)] = tid;
        } else {
            u_list[atomicAdd(&u_cnt[0], 1)] = tid;
        }
    }
}

__global__ void markHedgeInCorrespondingWorkLists(int* hedge, int hedgeN, int* eMatch, int* s_list, int* m_list, int* l_list, int* u_list) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN && !eMatch[tid]) {
        int hedgesize = hedge[tid + E_DEGREE1(hedgeN)];
        if (hedgesize < 50) {
            s_list[tid] = 1;
        } else if (hedgesize >= 50 && hedgesize < 1000) {
            m_list[tid] = 1;
        } else if (hedgesize >= 1000 && hedgesize < 10000) {
            l_list[tid] = 1;
        } else {
            u_list[tid] = 1;
        }
    }
}

// __global__ void putValidHedgeIntoCorrespondingList(int* hedge, int hedgeN, int* mark_list, int* hedge_list) {
//     int tid = blockIdx.x * blockDim.x + threadIdx.x;
//     if (tid < hedgeN) {
//         if (tid == 0 && mark_list[tid]) {
//             hedge_list[0] = 0;
//         }
//         else if (tid > 0 && mark_list[tid] > mark_list[tid-1]) {
//             hedge_list[mark_list[tid]-1] = tid;
//         }
//     }
// }

__global__ void putValidHedgeIntoCorrespondingList(int* hedge, int hedgeN, int* mark_list1, int* hedge_list1, int* mark_list2, int* hedge_list2, 
                                                    int* mark_list3, int* hedge_list3, int* mark_list4, int* hedge_list4) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        if (tid == 0) {
            if (mark_list1[tid]) {
                hedge_list1[0] = tid;
            }
            if (mark_list2[tid]) {
                hedge_list2[0] = tid;
            }
            if (mark_list3[tid]) {
                hedge_list3[0] = tid;
            }
            if (mark_list4[tid]) {
                hedge_list4[0] = tid;
            }
        }
        else {
            if (mark_list1[tid] > mark_list1[tid-1]) {
                hedge_list1[mark_list1[tid]-1] = tid;
            }
            if (mark_list2[tid] > mark_list2[tid-1]) {
                hedge_list2[mark_list2[tid]-1] = tid;
            }
            if (mark_list3[tid] > mark_list3[tid-1]) {
                hedge_list3[mark_list3[tid]-1] = tid;
            }
            if (mark_list4[tid] > mark_list4[tid-1]) {
                hedge_list4[mark_list4[tid]-1] = tid;
            }
        }
    }
}

__global__ void assignTWCHedgeWorkListsWithTunableThresholds(int* hedge, int hedgeN, int* eMatch, int* s_cnt, int* m_cnt, int* l_cnt, 
                                                    int* s_list, int* m_list, int* l_list,
                                                    int s_threshod, int m_threshold/*, int* hedgesize*/) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN && !eMatch[tid]) 
    {
        int hedgesize = hedge[tid + E_DEGREE1(hedgeN)];
        if (hedgesize < s_threshod) {
            s_list[atomicAdd(&s_cnt[0], 1)] = tid;
        } else if (hedgesize >= s_threshod && hedgesize < m_threshold) {
            m_list[atomicAdd(&m_cnt[0], 1)] = tid;
        } else if (hedgesize >= m_threshold) {
            l_list[atomicAdd(&l_cnt[0], 1)] = tid;
        }
        // if (tid < hedgeN && hedge[tid + E_DEGREE1(hedgeN)] < INT_MAX) {
        //     s_list[atomicAdd(&s_cnt[0], 1)] = tid;
        // }
    }
    // if (tid < hedgeN) {
    //     if (hedgesize[tid] == 1) {
    //         s_list[atomicAdd(&s_cnt[0], 1)] = tid;
    //     } else if (hedgesize[tid] == 2) {
    //         m_list[atomicAdd(&m_cnt[0], 1)] = tid;
    //     } else if (hedgesize[tid] == 3) {
    //         l_list[atomicAdd(&l_cnt[0], 1)] = tid;
    //     }
    // }
}

__global__ void markHedgeInCorrespondingWorkLists1(int* hedge, int hedgeN, int* eMatch, int* s_list, int* m_list, int* l_list, int s_threshod, int m_threshold/*, int* hedgesize*/) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN && !eMatch[tid]) 
    {
        int hedgesize = hedge[tid + E_DEGREE1(hedgeN)];
        if (hedgesize < s_threshod) {
            s_list[tid] = 1;
        } else if (hedgesize >= s_threshod && hedgesize < m_threshold) {
            m_list[tid] = 1;
        } else if (hedgesize >= m_threshold) {
            l_list[tid] = 1;
        }
        // if (tid < hedgeN && hedge[tid + E_DEGREE1(hedgeN)] < INT_MAX) {
        //     s_list[tid] = 1;
        // }
    }
    // if (tid < hedgeN) {
    //     if (hedgesize[tid] == 1) {
    //         s_list[tid] = 1;
    //     } else if (hedgesize[tid] == 2) {
    //         m_list[tid] = 1;
    //     } else if (hedgesize[tid] == 3) {
    //         l_list[tid] = 1;
    //     }
    // }
}

__global__ void assignHedgeInfo(int* hedge, int hedgeN, int* eMatch, tmp_hedge* hedgelist) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    hedgelist[tid].eMatch = eMatch[tid];
    hedgelist[tid].id_key = tid;
    hedgelist[tid].size = hedge[tid + E_DEGREE1(hedgeN)];
}

__global__ void processHedgesInThreadLevel(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, int* s_list, int* s_cnt,
                                        int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    int hid = s_list[tid];
    if (tid < s_cnt[0]) {
        int best = INT_MAX;
        unsigned represent = 0;//INT_MAX;
        int counts = 0;
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + hid]; ++i) {
            if (!nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    counts++;
                    candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN] = 1;
                }
            }
            else if (nPrior[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN] == INT_MIN) {
                if (nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] < best) {
                    best = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
                    represent = adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i];
                } else if (nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] == best) {
                    if (adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] < represent) {
                        represent = adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i];
                    }
                }
            }
        }
        if (counts) {
            if (best < INT_MAX) {
                int parent = nodes[represent-hedgeN + N_PARENT1(nodeN)];
                for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + hid]; ++i) {
                    int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                    unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                    int candidate = candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                    if (candidate && hedgeid == idnum) {
                        int tmpW = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_WEIGHT1(nodeN)];
                        if (tmpW + accW[parent - hedgeN] <= LIMIT) {
                            nBag1[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i]-hedgeN] = 1;
                            nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i]-hedgeN] = 1;
                            nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_PARENT1(nodeN)] = parent;
                            nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN] = nHedgeId[represent-hedgeN];
                        }
                    }
                }
            }
        }
    }
}

// for tmp_hedge list from thrust
__global__ void processHedgesInThreadLevel_(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, tmp_hedge* s_list, int s_cnt,
                                        int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    int hid = s_list[tid].id_key;
    if (tid < s_cnt) {
        int best = INT_MAX;
        unsigned represent = 0;//INT_MAX;
        int counts = 0;
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + hid]; ++i) {
            if (!nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    counts++;
                    candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN] = 1;
                }
            }
            else if (nPrior[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN] == INT_MIN) {
                if (nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] < best) {
                    best = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
                    represent = adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i];
                } else if (nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] == best) {
                    if (adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] < represent) {
                        represent = adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i];
                    }
                }
            }
        }
        if (counts) {
            if (best < INT_MAX) {
                int parent = nodes[represent-hedgeN + N_PARENT1(nodeN)];
                for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + hid]; ++i) {
                    int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                    unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                    int candidate = candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN];
                    if (candidate && hedgeid == idnum) {
                        int tmpW = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_WEIGHT1(nodeN)];
                        if (tmpW + accW[parent - hedgeN] <= LIMIT) {
                            nBag1[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i]-hedgeN] = 1;
                            nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i]-hedgeN] = 1;
                            nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_PARENT1(nodeN)] = parent;
                            nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + i] - hedgeN] = nHedgeId[represent-hedgeN];
                        }
                    }
                }
            }
        }
    }
}

// __global__ void processSmallSizeHedges1(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, int s_threshod,
//                                         int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId) {
//     int tid = blockIdx.x * blockDim.x + threadIdx.x;
//     if (tid < hedgeN && !eMatch[tid]) {
//         int hedgesize = hedges[tid + E_DEGREE1(hedgeN)];
//         if (hedgesize < s_threshod) {
//             int best = INT_MAX;
//             unsigned represent = 0;//INT_MAX;
//             int counts = 0;
//             for (int i = 0; i < hedgesize; ++i) {
//                 if (!nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN]) {
//                     int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
//                     unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
//                     if (hedgeid == idnum) {
//                         counts++;
//                         candidates[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = 1;
//                     }
//                 }
//                 else if (nPrior[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] == INT_MIN) {
//                     if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] < best) {
//                         best = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)];
//                         represent = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
//                     } else if (nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_WEIGHT1(nodeN)] == best) {
//                         if (adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] < represent) {
//                             represent = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
//                         }
//                     }
//                 }
//             }
//             if (counts) {
//                 if (best < INT_MAX) {
//                     int parent = nodes[represent-hedgeN + N_PARENT1(nodeN)];
//                     for (int i = 0; i < hedgesize; ++i) {
//                         int hedgeid = nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
//                         unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
//                         int candidate = candidates[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN];
//                         if (candidate && hedgeid == idnum) {
//                             int tmpW = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_WEIGHT1(nodeN)];
//                             if (tmpW + accW[parent - hedgeN] <= LIMIT) {
//                                 nBag1[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN] = 1;
//                                 nMatch[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN] = 1;
//                                 nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i]-hedgeN + N_PARENT1(nodeN)] = parent;
//                                 nHedgeId[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN] = nHedgeId[represent-hedgeN];
//                             }
//                         }
//                     }
//                 }
//             }
//         }
//     }
// }



__global__ void processHedgesInWarpLevel(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                        int* hedge_list, int* hedge_cnt, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
                                        int* cand_counts, int* represents, int* bests) {
    int xid = (threadIdx.x + blockDim.x * blockIdx.x) >> 5;
    int hid = hedge_list[xid];
    if (xid < hedge_cnt[0]) {
        int lid = threadIdx.x & 31; // laneID
        while (lid < hedges[E_DEGREE1(hedgeN) + hid]) {
            if (!nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    atomicAdd(&cand_counts[hid], 1);
                    candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN] = 1;
                }
            }
            else if (nPrior[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN] == INT_MIN) {
                int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN + N_WEIGHT1(nodeN)];
                atomicMin(&bests[hid], weight);
            }
            lid += 32;
        }
        __syncthreads();
        lid = threadIdx.x & 31;
        while (lid < hedges[E_DEGREE1(hedgeN) + hid]) {
            if (nPrior[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN] == INT_MIN) {
                int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN + N_WEIGHT1(nodeN)];
                if (weight == bests[hid]) {
                    atomicMin(&represents[hid], adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid]);
                }
            }
            lid += 32;
        }
        __syncthreads();
        if (cand_counts[hid] && bests[hid] < INT_MAX) {
            int parent = nodes[represents[hid] - hedgeN + N_PARENT1(nodeN)];
            lid = threadIdx.x & 31;
            while (lid < hedges[E_DEGREE1(hedgeN) + hid]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                int candidate = candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN];
                if (candidate && hedgeid == idnum) {
                    int tmpW = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN + N_WEIGHT1(nodeN)];
                    if (tmpW + accW[parent - hedgeN] <= LIMIT) {
                        nBag1[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid]-hedgeN] = 1;
                        nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid]-hedgeN] = 1;
                        nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN + N_PARENT1(nodeN)] = parent;
                        nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN] = nHedgeId[represents[hid] - hedgeN];
                    }
                }
                lid += 32;
            }
        }
    }
}

// for tmp_hedge list from thrust
__global__ void processHedgesInWarpLevel_(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                        tmp_hedge* hedge_list, int hedge_cnt, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
                                        int* cand_counts, int* represents, int* bests) {
    int xid = (threadIdx.x + blockDim.x * blockIdx.x) >> 5;
    int hid = hedge_list[xid].id_key;
    if (xid < hedge_cnt) {
        int lid = threadIdx.x & 31; // laneID
        while (lid < hedges[E_DEGREE1(hedgeN) + hid]) {
            if (!nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    atomicAdd(&cand_counts[hid], 1);
                    candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN] = 1;
                }
            }
            else if (nPrior[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN] == INT_MIN) {
                int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN + N_WEIGHT1(nodeN)];
                atomicMin(&bests[hid], weight);
            }
            lid += 32;
        }
        __syncthreads();
        lid = threadIdx.x & 31;
        while (lid < hedges[E_DEGREE1(hedgeN) + hid]) {
            if (nPrior[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN] == INT_MIN) {
                int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN + N_WEIGHT1(nodeN)];
                if (weight == bests[hid]) {
                    atomicMin(&represents[hid], adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid]);
                }
            }
            lid += 32;
        }
        __syncthreads();
        if (cand_counts[hid] && bests[hid] < INT_MAX) {
            int parent = nodes[represents[hid] - hedgeN + N_PARENT1(nodeN)];
            lid = threadIdx.x & 31;
            while (lid < hedges[E_DEGREE1(hedgeN) + hid]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                int candidate = candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN];
                if (candidate && hedgeid == idnum) {
                    int tmpW = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN + N_WEIGHT1(nodeN)];
                    if (tmpW + accW[parent - hedgeN] <= LIMIT) {
                        nBag1[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid]-hedgeN] = 1;
                        nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid]-hedgeN] = 1;
                        nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN + N_PARENT1(nodeN)] = parent;
                        nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN] = nHedgeId[represents[hid] - hedgeN];
                    }
                }
                lid += 32;
            }
        }
    }
}


__global__ void processHedgesInWarpLevelWithSharedMemReduce(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                            int* hedge_list, int* hedge_cnt, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
                                            int* cand_counts, int* represents, int* bests) {
    int xid = (threadIdx.x + blockDim.x * blockIdx.x) >> 5;
    int hid = hedge_list[xid];
    if (xid < hedge_cnt[0]) {
        int lid = threadIdx.x & 31; // laneID in warp
        int wid = threadIdx.x >> 5; // warpID in block
        int _minwt = INT_MAX;
        int _minid = INT_MAX;
        while (lid < hedges[E_DEGREE1(hedgeN) + hid]) {
            if (!nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    atomicAdd(&cand_counts[hid], 1);
                    candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN] = 1;
                }
            }
            else if (nPrior[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN] == INT_MIN) {
                int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN + N_WEIGHT1(nodeN)];
                if (weight < _minwt) {
                    _minwt = min(_minwt, weight);
                    _minid = adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid];
                } else if (_minwt == weight) {
                    _minid = min(_minid, adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid]);
                }
            }
            lid += 32;
        }
        extern __shared__ int smem[];
        int* sm_weight = smem;
        int* sm_nodeid = smem + blockDim.x;
        sm_weight[threadIdx.x] = _minwt;
        sm_nodeid[threadIdx.x] = _minid;
        __syncwarp();
        lid = threadIdx.x & 31;
        for (int s = 32 >> 1; s > 0; s >>= 1) { // may be use shfl func
            if (lid < s) {
                if (sm_weight[threadIdx.x] > sm_weight[threadIdx.x + s]) {
                    sm_weight[threadIdx.x] = sm_weight[threadIdx.x + s];
                    sm_nodeid[threadIdx.x] = sm_nodeid[threadIdx.x + s];
                } else if (sm_weight[threadIdx.x] == sm_weight[threadIdx.x + s]) {
                    sm_nodeid[threadIdx.x] = min(sm_nodeid[threadIdx.x], sm_nodeid[threadIdx.x + s]);
                }
            }
            __syncwarp();
        }
        if (cand_counts[hid] && sm_weight[wid << 5] < INT_MAX) {
            int parent = nodes[sm_nodeid[wid << 5] - hedgeN + N_PARENT1(nodeN)];
            lid = threadIdx.x & 31;
            while (lid < hedges[E_DEGREE1(hedgeN) + hid]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                int candidate = candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN];
                if (candidate && hedgeid == idnum) {
                    int tmpW = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN + N_WEIGHT1(nodeN)];
                    if (tmpW + accW[parent - hedgeN] <= LIMIT) {
                        nBag1[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid]-hedgeN] = 1;
                        nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid]-hedgeN] = 1;
                        nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN + N_PARENT1(nodeN)] = parent;
                        nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + lid] - hedgeN] = nHedgeId[sm_nodeid[wid << 5] - hedgeN];
                    }
                }
                lid += 32;
            }
        }
    }
}

__global__ void processHedgesInBlockLevel(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                        int* hedge_list, int* hedge_cnt, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
                                        int* cand_counts, int* represents, int* bests) {
    int bid = blockIdx.x;
    int hid = hedge_list[bid];
    if (bid < hedge_cnt[0]) {
        int tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
            if (!nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    // atomicAdd(&smem[0], 1);
                    atomicAdd(&cand_counts[hid], 1);
                    candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = 1;
                }
            }
            else if (nPrior[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] == INT_MIN) {
                int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                // atomicMin(&smem[2], weight);
                atomicMin(&bests[hid], weight);
            }
            tid += blockDim.x;
        }
        __syncthreads();
        tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
            if (nPrior[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] == INT_MIN) {
                int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                // if (weight == smem[2]) {
                if (weight == bests[hid]) {
                    // atomicMin(&smem[1], adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]);
                    atomicMin(&represents[hid], adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]);
                }
            }
            tid += blockDim.x;
        }
        __syncthreads();
        // if (smem[0] && smem[2] < INT_MAX) {
        if (cand_counts[hid] && bests[hid] < INT_MAX) {
            // int parent = nodes[smem[1] - hedgeN + N_PARENT1(nodeN)];
            int parent = nodes[represents[hid] - hedgeN + N_PARENT1(nodeN)];
            tid = threadIdx.x;
            while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                int candidate = candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                if (candidate && hedgeid == idnum) {
                    int tmpW = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                    if (tmpW + accW[parent - hedgeN] <= LIMIT) {
                        nBag1[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
                        nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
                        nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)] = parent;
                        // nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = nHedgeId[smem[1] - hedgeN];
                        nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = nHedgeId[represents[hid] - hedgeN];
                    }
                }
                tid += blockDim.x;
            }
        }
    }
}

// for tmp_hedge list from thrust
__global__ void processHedgesInBlockLevel_(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                        tmp_hedge* hedge_list, int hedge_cnt, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
                                        int* cand_counts, int* represents, int* bests) {
    int bid = blockIdx.x;
    int hid = hedge_list[bid].id_key;
    if (bid < hedge_cnt) {
        int tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
            if (!nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    // atomicAdd(&smem[0], 1);
                    atomicAdd(&cand_counts[hid], 1);
                    candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = 1;
                }
            }
            else if (nPrior[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] == INT_MIN) {
                int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                // atomicMin(&smem[2], weight);
                atomicMin(&bests[hid], weight);
            }
            tid += blockDim.x;
        }
        __syncthreads();
        tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
            if (nPrior[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] == INT_MIN) {
                int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                // if (weight == smem[2]) {
                if (weight == bests[hid]) {
                    // atomicMin(&smem[1], adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]);
                    atomicMin(&represents[hid], adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]);
                }
            }
            tid += blockDim.x;
        }
        __syncthreads();
        // if (smem[0] && smem[2] < INT_MAX) {
        if (cand_counts[hid] && bests[hid] < INT_MAX) {
            // int parent = nodes[smem[1] - hedgeN + N_PARENT1(nodeN)];
            int parent = nodes[represents[hid] - hedgeN + N_PARENT1(nodeN)];
            tid = threadIdx.x;
            while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                int candidate = candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                if (candidate && hedgeid == idnum) {
                    int tmpW = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                    if (tmpW + accW[parent - hedgeN] <= LIMIT) {
                        nBag1[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
                        nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
                        nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)] = parent;
                        // nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = nHedgeId[smem[1] - hedgeN];
                        nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = nHedgeId[represents[hid] - hedgeN];
                    }
                }
                tid += blockDim.x;
            }
        }
    }
}

__global__ void processHedgesInBlockLevelWithSharedMemReduce(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, 
                                        int* hedge_list, int* hedge_cnt, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
                                        int* cand_counts, int* represents, int* bests) {
    int bid = blockIdx.x;
    int hid = hedge_list[bid];
    if (bid < hedge_cnt[0]) {
        int tid = threadIdx.x;
        int _minwt = INT_MAX;
        int _minid = INT_MAX;
        while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
            if (!nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    atomicAdd(&cand_counts[hid], 1);
                    candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = 1;
                }
            }
            else if (nPrior[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] == INT_MIN) {
                int weight = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                if (weight < _minwt) {
                    _minwt = min(_minwt, weight);
                    _minid = adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid];
                } else if (_minwt == weight) {
                    _minid = min(_minid, adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]);
                }
            }
            tid += blockDim.x;
        }
        extern __shared__ int smem[];
        int* sm_weight = smem;
        int* sm_nodeid = smem + blockDim.x;
        sm_weight[threadIdx.x] = _minwt;
        sm_nodeid[threadIdx.x] = _minid;
        __syncthreads();
        for (int s = blockDim.x >> 1; s > 0; s >>= 1) {
            if (threadIdx.x < s) {
                if (sm_weight[threadIdx.x] > sm_weight[threadIdx.x + s]) {
                    sm_weight[threadIdx.x] = sm_weight[threadIdx.x + s];
                    sm_nodeid[threadIdx.x] = sm_nodeid[threadIdx.x + s];
                } else if (sm_weight[threadIdx.x] == sm_weight[threadIdx.x + s]) {
                    sm_nodeid[threadIdx.x] = min(sm_nodeid[threadIdx.x], sm_nodeid[threadIdx.x + s]);
                }
            }
            __syncthreads();
        }
        if (cand_counts[hid] && sm_weight[0] < INT_MAX) {
            int parent = nodes[sm_nodeid[0] - hedgeN + N_PARENT1(nodeN)];
            tid = threadIdx.x;
            while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
                int hedgeid = nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                unsigned int idnum = hedges[hid + E_IDNUM1(hedgeN)];
                int candidate = candidates[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                if (candidate && hedgeid == idnum) {
                    int tmpW = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                    if (tmpW + accW[parent - hedgeN] <= LIMIT) {
                        nBag1[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
                        nMatch[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
                        nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)] = parent;
                        nHedgeId[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = nHedgeId[sm_nodeid[0] - hedgeN];
                    }
                }
                tid += blockDim.x;
            }
        }
    }
}

// __global__ void processHedgesInBlockLevel2(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, int lo, int hi,
//                                         int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
//                                         int* cand_counts, int* represents, int* bests) {
//     int bid = blockIdx.x;
//     if (bid < hedgeN && !eMatch[bid]) {
//         int hedgesize = hedges[bid + E_DEGREE1(hedgeN)];
//         if (hedgesize >= lo && hedgesize < hi) {
//             int tid = threadIdx.x;
//             int _minwt = INT_MAX;
//             int _minid = INT_MAX;
//             while (tid < hedgesize) {
//                 if (!nMatch[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN]) {
//                     int hedgeid = nHedgeId[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
//                     unsigned int idnum = hedges[bid + E_IDNUM1(hedgeN)];
//                     if (hedgeid == idnum) {
//                         atomicAdd(&cand_counts[bid], 1);
//                         candidates[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = 1;
//                     }
//                 }
//                 else if (nPrior[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN] == INT_MIN) {
//                     int weight = nodes[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
//                     if (weight < _minwt) {
//                         _minwt = min(_minwt, weight);
//                         _minid = adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid];
//                     } else if (_minwt == weight) {
//                         _minid = min(_minid, adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid]);
//                     }
//                 }
//                 tid += blockDim.x;
//             }
//             extern __shared__ int smem[];
//             int* sm_weight = smem;
//             int* sm_nodeid = smem + blockDim.x;
//             sm_weight[threadIdx.x] = _minwt;
//             sm_nodeid[threadIdx.x] = _minid;
//             __syncthreads();
//             tid = threadIdx.x;
//             for (int s = blockDim.x >> 1; s > 0; s >>= 1) {
//                 if (threadIdx.x < s) {
//                     if (sm_weight[threadIdx.x] > sm_weight[threadIdx.x + s]) {
//                         sm_weight[threadIdx.x] = sm_weight[threadIdx.x + s];
//                         sm_nodeid[threadIdx.x] = sm_nodeid[threadIdx.x + s];
//                     } else if (sm_weight[threadIdx.x] == sm_weight[threadIdx.x + s]) {
//                         sm_nodeid[threadIdx.x] = min(sm_nodeid[threadIdx.x], sm_nodeid[threadIdx.x + s]);
//                     }
//                 }
//             }

//             // if (!threadIdx.x) {
//             //     weight_vals[hid] = sm_weight[0];
//             //     keys[hid] = sm_nodeid[0];
//             // }
//             __syncthreads();
//             if (cand_counts[bid] && sm_weight[0] < INT_MAX) {
//                 int parent = nodes[sm_nodeid[0] - hedgeN + N_PARENT1(nodeN)];
//                 tid = threadIdx.x;
//                 while (tid < hedgesize) {
//                     int hedgeid = nHedgeId[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
//                     unsigned int idnum = hedges[bid + E_IDNUM1(hedgeN)];
//                     int candidate = candidates[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
//                     if (candidate && hedgeid == idnum) {
//                         int tmpW = nodes[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
//                         if (tmpW + accW[parent - hedgeN] <= LIMIT) {
//                             nBag1[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
//                             nMatch[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
//                             nodes[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)] = parent;
//                             nHedgeId[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = nHedgeId[sm_nodeid[0] - hedgeN];
//                         }
//                     }
//                     tid += blockDim.x;
//                 }
//             }
//         }
//     }
// }

// __global__ void processHedgesInBlockLevel3(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, int lo, int hi,
//                                         int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId,
//                                         int* cand_counts, int* represents, int* bests) {
//     int bid = blockIdx.x;
//     if (bid < hedgeN && !eMatch[bid]) {
//         int hedgesize = hedges[bid + E_DEGREE1(hedgeN)];
//         if (hedgesize >= lo && hedgesize < hi) {
//             int tid = threadIdx.x;
//             while (tid < hedgesize) {
//                 if (!nMatch[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN]) {
//                     int hedgeid = nHedgeId[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
//                     unsigned int idnum = hedges[bid + E_IDNUM1(hedgeN)];
//                     if (hedgeid == idnum) {
//                         atomicAdd(&cand_counts[bid], 1);
//                         candidates[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = 1;
//                     }
//                 }
//                 else if (nPrior[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN] == INT_MIN) {
//                     int weight = nodes[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
//                     atomicMin(&bests[bid], weight);
//                 }
//                 tid += blockDim.x;
//             }
//             __syncthreads();
//             tid = threadIdx.x;
//             while (tid < hedgesize) {
//                 if (nPrior[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN] == INT_MIN) {
//                     int weight = nodes[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
//                     if (weight == bests[bid]) {
//                         atomicMin(&represents[bid], adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid]);
//                     }
//                 }
//                 tid += blockDim.x;
//             }
//             __syncthreads();
//             if (cand_counts[bid] && bests[bid] < INT_MAX) {
//                 int parent = nodes[represents[bid] - hedgeN + N_PARENT1(nodeN)];
//                 tid = threadIdx.x;
//                 while (tid < hedgesize) {
//                     int hedgeid = nHedgeId[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
//                     unsigned int idnum = hedges[bid + E_IDNUM1(hedgeN)];
//                     int candidate = candidates[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
//                     if (candidate && hedgeid == idnum) {
//                         int tmpW = nodes[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
//                         if (tmpW + accW[parent - hedgeN] <= LIMIT) {
//                             nBag1[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
//                             nMatch[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
//                             nodes[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)] = parent;
//                             nHedgeId[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = nHedgeId[represents[bid] - hedgeN];
//                         }
//                     }
//                     tid += blockDim.x;
//                 }
//             }
//         }
//     }
// }


__global__ void fillIncidentNetLists(int* hedges, int* nodes, unsigned* adj_list, unsigned* incident_nets, int hedgeN, int nodeN, int* netsListCounter) {
    // int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    // int tidy = blockIdx.y * blockDim.y + threadIdx.y;
    // if (tidx < hedgeN) {
    //     while (tidy < hedges[tidx + E_DEGREE1(hedgeN)]) {
    //         unsigned nodeid = adj_list[hedges[E_OFFSET1(hedgeN) + tidx] + tidy];
    //         unsigned index = atomicAdd(&netsListCounter[nodeid - hedgeN], 1);
    //         incident_nets[nodes[N_OFFSET1(nodeN) + nodeid - hedgeN] + index] = tidx;
    //         tidy += gridDim.y * blockDim.y;
    //     }
    // }

    int tidx = blockIdx.x;
    if (tidx < hedgeN) {
        int tid = threadIdx.x;
        while (tid < hedges[tidx + E_DEGREE1(hedgeN)]) {
            unsigned nodeid = adj_list[hedges[E_OFFSET1(hedgeN) + tidx] + tid];
            unsigned index = atomicAdd(&netsListCounter[nodeid - hedgeN], 1);//netsListCounter[nodeid - hedgeN];//
            incident_nets[nodes[N_OFFSET1(nodeN) + nodeid - hedgeN] + index] = tidx;
            tid += blockDim.x;
        }
    }
}

__global__ void fillIncidentNetLists1(int* hedges, int* nodes, unsigned* adj_list, unsigned* incident_nets, 
                                    int* newNodes, unsigned* newNetList, int hedgeN, int nodeN, int newHedgeN, int newNodeN, 
                                    int* netsListCounter, int* eInBag, int* nInBag, int* next_eid, int* next_nid) {
    int tidx = blockIdx.x;
    if (tidx < nodeN) {
        if (nInBag[tidx]) {
            int n_id = next_nid[tidx] - newHedgeN;
            int tid = threadIdx.x;
            // atomicAdd(&netsListCounter[0], 1);
            while (tid < nodes[tidx + N_DEGREE1(nodeN)]) {
                int hedgeid = incident_nets[nodes[tidx + E_OFFSET1(nodeN)] + tid];
                if (eInBag[hedgeid]) {
                    int h_id = next_eid[hedgeid];
                    int count = atomicAdd(&netsListCounter[n_id], 1);
                    newNetList[newNodes[N_OFFSET1(newNodeN) + n_id] + count] = h_id;
                }
                tid += blockDim.x;
            }
        }
    }
}

__global__ void updateAdjParentList(int* nodes, unsigned* adj_list, int* adj_parlist, int* nNextId, int nodeN, int hedgeN, int totalsize,
                                    int* eInBag, unsigned* hedge_id/*, int* dup_degree, int newHedgeN, unsigned* isSelfMergeNode, unsigned* isDuplica*/) {
    int tid = threadIdx.x + blockDim.x * blockIdx.x;
    if (tid < totalsize) {
        if (eInBag[hedge_id[tid]]) {
            adj_parlist[tid] = nodes[N_PARENT1(nodeN) + adj_list[tid] - hedgeN];
            // atomicAdd(&dup_degree[adj_parlist[tid] - newHedgeN], 1);
            // if (isSelfMergeNode[adj_list[tid] - hedgeN] == 1) {
            //     isDuplica[tid] = 1;
            // }
        }
    }
}

__global__ void updateNodesInFinerLevelCoordsInfo(int* nodes, unsigned* adj_list, int* adj_parlist, int* nNextId, int nodeN, int hedgeN, int totalsize,
                                    int* eInBag, unsigned* hedge_id, int* dup_offset, int newHedgeN, int* dup_counter, int* correspond_hedgeid, int* correspond_hoffset) {
    int tid = threadIdx.x + blockDim.x * blockIdx.x;
    if (tid < totalsize) {
        if (eInBag[hedge_id[tid]]) {
            adj_parlist[tid] = nodes[N_PARENT1(nodeN) + adj_list[tid] - hedgeN];
            int index = dup_counter[adj_parlist[tid] - newHedgeN];
        }
    }
}

__global__ void updateNodesInFinerLevelCoordsInfo1(int* nodes, unsigned* adj_list, int* adj_parlist, int* nNextId, int nodeN, int hedgeN, int totalsize,
                                    int* eInBag, unsigned* hedge_id, int* dup_offset, int newHedgeN, int* dup_counter, int* correspond_hedgeid, int* correspond_hoffset) {
    int tid = threadIdx.x + blockDim.x * blockIdx.x;
    if (tid < totalsize) {
        if (eInBag[hedge_id[tid]]) {
            adj_parlist[tid] = nodes[N_PARENT1(nodeN) + adj_list[tid] - hedgeN];
            int index = dup_counter[adj_parlist[tid] - newHedgeN];
            correspond_hedgeid[dup_offset[adj_parlist[tid] - newHedgeN] + index] = hedge_id[tid];

        }
    }
}

__global__ void markDuplicateParentInPins(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist) {
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidy = blockIdx.y * blockDim.y + threadIdx.y;
    if (tidx < hedgeN) {
        if (eInBag[tidx]) {
            unsigned h_id = next_id[tidx];
            int id = h_id;
            while (tidy < hedges[tidx + E_DEGREE1(hedgeN)]) {
                // unsigned pid = nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] - hedgeN + N_PARENT1(nodeN)];
                unsigned pid = adj_parlist[hedges[tidx + E_OFFSET1(hedgeN)] + tidy];
                bool isfind = false;
                for (int i = 0; i < tidy; i++) {
                    // if (nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                    if (adj_parlist[hedges[tidx + E_OFFSET1(hedgeN)] + i] == pid) {
                        isfind = true;
                        break;
                    }
                }
                if (!isfind) {
                    isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] = 1;
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                }
                tidy += gridDim.y * blockDim.y;
            }
        }
    }
}

#define TEST_NO_SCAN



__global__ void markDuplicateParentInPins1(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, int maxHedgeSize) {
    int tidx = blockIdx.x;
    if (tidx < hedgeN) {
        if (eInBag[tidx]/* && hedges[tidx + E_DEGREE1(hedgeN)] > 100*/) {
            unsigned h_id = next_id[tidx];
            int id = h_id;
            int tid = threadIdx.x;
            int beg_off = hedges[tidx + E_OFFSET1(hedgeN)];
            int cur_deg = hedges[tidx + E_DEGREE1(hedgeN)];
            while (tid < cur_deg) {
                // unsigned pid = nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)];
                // unsigned pid = adj_parlist[hedges[tidx + E_OFFSET1(hedgeN)] + tid];
                unsigned pid = adj_parlist[beg_off + tid];
                bool isfind = false;
                for (int i = 0; i < tid; i++) {
                    // if (nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                    // if (adj_parlist[hedges[tidx + E_OFFSET1(hedgeN)] + i] == pid) {
                    if (adj_parlist[beg_off + i] == pid) {
                        isfind = true;
                        break;
                    }
                }
                if (!isfind) {
                    // isDuplica[tid] = 1;
                    isDuplica[beg_off + tid] = 1;
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                }
                tid += blockDim.x;
            }
        }
    }
}

__global__ void markDuplicateParentInPins_idealcase_test(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, int maxHedgeSize) {
    int tidx = blockIdx.x;
    if (tidx < hedgeN) {
        if (eInBag[tidx]) {
            unsigned h_id = next_id[tidx];
            int id = h_id;
            int tid = threadIdx.x;
            int beg_off = hedges[tidx + E_OFFSET1(hedgeN)];
            int cur_deg = hedges[tidx + E_DEGREE1(hedgeN)];
            while (tid < cur_deg) {
                unsigned pid = adj_parlist[beg_off + tid];
                bool isfind = false;
                if (adj_parlist[beg_off] == pid) {
                    isfind = true;
                }
                if (!isfind) {
                    isDuplica[beg_off + tid] = 1;
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                }
                tid += blockDim.x;
            }
        }
    }
}

__global__ void markDuplicateCoarsePins_nocheck_longest_hedge_test(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int maxDegree,
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, int maxHedgeSize) {
    int tidx = blockIdx.x;
    if (tidx < hedgeN) {
        if (eInBag[tidx] && hedges[tidx + E_DEGREE1(hedgeN)] < 0.9 * maxDegree) {
            unsigned h_id = next_id[tidx];
            int id = h_id;
            int tid = threadIdx.x;
            int beg_off = hedges[tidx + E_OFFSET1(hedgeN)];
            int cur_deg = hedges[tidx + E_DEGREE1(hedgeN)];
            while (tid < cur_deg) {
                unsigned pid = adj_parlist[beg_off + tid];
                bool isfind = false;
                if (adj_parlist[beg_off] == pid) {
                    isfind = true;
                }
                if (!isfind) {
                    isDuplica[beg_off + tid] = 1;
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                }
                tid += blockDim.x;
            }
        }
    }
}


__global__ void markDuplicateParentInPins2(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int* next_id, int* eInBag,
                                        int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize, int* adj_parlist, int maxHedgeSize) {
    int tidx = blockIdx.x;
    while (tidx < hedgeN) {
        if (eInBag[tidx]/* && hedges[tidx + E_DEGREE1(hedgeN)] > 6*/) {
            unsigned h_id = next_id[tidx];
            int id = h_id;
            int tid = threadIdx.x;
            int cur_deg = hedges[tidx + E_DEGREE1(hedgeN)];
            int beg_off = hedges[tidx + E_OFFSET1(hedgeN)];
            while (tid < cur_deg) {
                unsigned curr_loc = beg_off + tid;
                unsigned candidate = adj_parlist[curr_loc] - newHedgeN;
                unsigned bitset_idx = candidate / 32;
                unsigned bit_offset = candidate & 31;
                unsigned bitset_loc = (tidx % num_hedges) * bitLen + bitset_idx;
                int cur_bit = atomicOr(&bitset[bitset_loc], (0x80000000 >> bit_offset));
                unsigned shift_bits = 31 - bit_offset;
                int extract_bit_val = (cur_bit & (1 << shift_bits)) >> shift_bits;
                if (extract_bit_val == 0) {
                    isDuplica[curr_loc] = 1;
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                }
                tid += blockDim.x;
            }
            __syncthreads();
            tid = threadIdx.x;
            while (tid < cur_deg) {
                unsigned curr_loc = beg_off + tid;
                unsigned candidate = adj_parlist[curr_loc] - newHedgeN;
                unsigned bitset_idx = candidate / 32;
                unsigned bitset_loc = (tidx % num_hedges) * bitLen + bitset_idx;
                bitset[bitset_loc] = 0;
                tid += blockDim.x;
            }
            __syncthreads();
        }
        tidx += gridDim.x;
    }
}

__global__ void markDuplicateParentInPins3(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int* next_id, int* eInBag, int totalsize,
                                        int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize, int* adj_parlist, int maxHedgeSize) {
    int tidx = blockIdx.x;
    while (tidx < hedgeN) {
        if (eInBag[tidx]) {
            unsigned h_id = next_id[tidx];
            int id = h_id;
            int tid = threadIdx.x;
            int cur_deg = hedges[tidx + E_DEGREE1(hedgeN)];
            int beg_off = hedges[tidx + E_OFFSET1(hedgeN)];
            // if (cur_deg >= 1000) {
            while (tid < cur_deg) {
                unsigned curr_loc = beg_off + tid;
                unsigned candidate = adj_parlist[curr_loc] - newHedgeN;
                unsigned bitset_loc = (tidx % num_hedges) * bitLen + candidate;
                atomicMin(&bitset[bitset_loc], tid + candidate);
                tid += blockDim.x;
            }
            __syncthreads();
            tid = threadIdx.x;
            while (tid < cur_deg) {
                unsigned curr_loc = beg_off + tid;
                unsigned candidate = adj_parlist[curr_loc] - newHedgeN;
                unsigned bitset_loc = (tidx % num_hedges) * bitLen + candidate;
                int min_loc = bitset[bitset_loc] - candidate + beg_off;
                
                if (!atomicOr(&isDuplica[min_loc], 1)) {
                    // printf("%d %d\n", tidx, tid);
                    isDuplica[min_loc] = 1;
                    // bitset[bitset_loc] = INT_MAX;
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                }
                // bitset[bitset_loc] = INT_MAX;
                tid += blockDim.x;
            }
            __syncthreads();
            tid = threadIdx.x;
            while (tid < cur_deg) {
                unsigned curr_loc = beg_off + tid;
                unsigned candidate = adj_parlist[curr_loc] - newHedgeN;
                unsigned bitset_loc = (tidx % num_hedges) * bitLen + candidate;
                bitset[bitset_loc] = INT_MAX;
                tid += blockDim.x;
            }
            __syncthreads();
        }
        tidx += gridDim.x;
    }
}

__global__ void mergeNodesInsideHyperedges_mod(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                            int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId, unsigned* isDuplica, int* dupCnts) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        bool flag = false;
        unsigned nodeid = INT_MAX;
        int count = 0;
        int w = 0;
        int p = 0;
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            int elemid = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
            int isMatched = nMatch[elemid - hedgeN];
            if (isMatched) { // return old value
                flag = true;
                // int parent = nodes[elemid - hedgeN + N_PARENT1(nodeN)];
                // if (p != parent) {
                //     p = parent;
                //     isDuplica[hedges[tid + E_OFFSET1(hedgeN)] + i] = 1;
                // }
                continue;
            }
            unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
            int hedgeid = nHedgeId[elemid - hedgeN];
            unsigned int dst = elemid;
            int weight = nodes[dst - hedgeN + N_WEIGHT1(nodeN)];
            if (idnum == hedgeid) {
                if (w + weight > LIMIT) {
                    break;
                }
                nodeid = min(nodeid, dst);
                count++;
                candidates[dst - hedgeN] = 1;
                w += weight;
            } else {
                flag = true;
            }
        }
        if (count) {
            if (flag && count == 1) { // do not update this node to match this hedge, leave later matching
                return;
            }
            eMatch[tid] = 1;
            if (flag) {
                eInBag[tid] = 1;
                atomicAdd(&newHedgeN[0], 1);
            }
            nBag[nodeid - hedgeN] = 1;
            atomicAdd(&newNodeN[0], 1);
            int num_merges = 0;
            if (tid == 3) {
                printf("here!!\n");
            }
            for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
                int elemid = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
                int hedgeid = nHedgeId[elemid - hedgeN];
                int candidate = candidates[elemid - hedgeN];
                if (candidate && idnum == hedgeid) {
                    nMatch[elemid - hedgeN] = 1;
                    nodes[elemid - hedgeN + N_PARENT1(nodeN)] = nodeid;
                    if (num_merges == 0) {
                        isDuplica[hedges[tid + E_OFFSET1(hedgeN)] + i] = 1;
                        // atomicAdd(&dupCnts[0], 1);
                    }
                    num_merges++;
                    int tmpW = nodes[elemid - hedgeN + N_WEIGHT1(nodeN)];
                    atomicAdd(&accW[nodeid - hedgeN], tmpW);
                }
            }
        }
    }
}

__global__ void mergeMoreNodesAcrossHyperedges_mod(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, int LIMIT, int* eMatch,
                                                int* nBag1, int* accW, int* nMatch, int* candidates, int* nPrior, int* nHedgeId, unsigned* isDuplica, int* dupCnts) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        if (eMatch[tid]) {
            return;
        }
        int best = INT_MAX;
        unsigned represent = 0;//INT_MAX;
        int counts = 0;
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            int elemid = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
            if (!nMatch[elemid - hedgeN]) {
                int hedgeid = nHedgeId[elemid - hedgeN];
                unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    counts++;
                    candidates[elemid - hedgeN] = 1;
                }
            }
            else if (nPrior[elemid - hedgeN] == INT_MIN) {
                if (nodes[elemid - hedgeN + N_WEIGHT1(nodeN)] < best) {
                    best = nodes[elemid - hedgeN + N_WEIGHT1(nodeN)];
                    represent = elemid;
                } else if (nodes[elemid - hedgeN + N_WEIGHT1(nodeN)] == best) {
                    if (elemid < represent) {
                        represent = elemid;
                    }
                }
            }
        }
        if (counts) {
            if (best < INT_MAX) {
                int parent = nodes[represent-hedgeN + N_PARENT1(nodeN)];
                int num_merges = 0;
                for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
                    int elemid = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                    int hedgeid = nHedgeId[elemid - hedgeN];
                    unsigned int idnum = hedges[tid + E_IDNUM1(hedgeN)];
                    int candidate = candidates[elemid - hedgeN];
                    if (candidate && hedgeid == idnum) {
                        int tmpW = nodes[elemid - hedgeN + N_WEIGHT1(nodeN)];
                        int weight = accW[parent - hedgeN];
                        if (tmpW + weight > LIMIT) {
                            // break;
                            continue;
                        }
                        nBag1[elemid - hedgeN] = 1;
                        nMatch[elemid - hedgeN] = 1;
                        nodes[elemid - hedgeN + N_PARENT1(nodeN)] = parent;
                        if (num_merges == 0) {
                            // isDuplica[hedges[tid + E_OFFSET1(hedgeN)] + i] = 1;
                            // atomicAdd(&dupCnts[0], 1);
                        }
                        num_merges++;
                        nHedgeId[elemid - hedgeN] = nHedgeId[represent - hedgeN];
                    }
                }
            }
        }
    }
}

__global__ void selfMergeSingletonNodes_mod(int* nodes, int nodeN, int hedgeN, int* newNodeN, int* nBag1, int* nBag, 
                                            int* accW, int* nMatch, int* nHedgeId, unsigned* isSelfMergeNodes) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (nBag1[tid]) {
            atomicAdd(&accW[nodes[tid + N_PARENT1(nodeN)] - hedgeN], nodes[N_WEIGHT1(nodeN) + tid]);
        }
        if (!nMatch[tid]) {
            nBag[tid] = 1;
            isSelfMergeNodes[tid] = 1;
            atomicAdd(&newNodeN[0], 1);
            nMatch[tid] = 1;
            nodes[tid + N_PARENT1(nodeN)] = tid + hedgeN;
            nHedgeId[tid] = INT_MAX;
            accW[tid] = nodes[N_WEIGHT1(nodeN) + tid];
        }
    }
}

__global__ void markParentsForPinsLists_early_duplica(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, unsigned* isSelfMergeNodes, int* dupCnts) {
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidy = blockIdx.y * blockDim.y + threadIdx.y;
    if (tidx < hedgeN) {
        if (eInBag[tidx]) {
            unsigned h_id = next_id[tidx];
            int id = h_id;
            while (tidy < hedges[tidx + E_DEGREE1(hedgeN)]) {
                unsigned cur_nid = adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] - hedgeN;
                if (isSelfMergeNodes[cur_nid] == 1) {
                    isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] = 1;
                    atomicAdd(&dupCnts[0], 1);
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                    tidy += gridDim.y * blockDim.y;
                    continue;
                }
                if (isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tidy] == 1) {
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                }
                tidy += gridDim.y * blockDim.y;
            }
        }
    }
}

__global__ void markDuplicateParentInPins2_mod(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int* next_id, int* eInBag,
                                        int* newHedges, int newHedgeN, unsigned* bitset, int bitLen, int num_hedges, int* newTotalPinSize, int* adj_parlist, unsigned* isSelfMergeNode) {
    int tidx = blockIdx.x;
    while (tidx < hedgeN) {
        if (eInBag[tidx]) {
            unsigned h_id = next_id[tidx];
            int id = h_id;
            int tid = threadIdx.x;
            while (tid < hedges[tidx + E_DEGREE1(hedgeN)]) {
                unsigned curr_loc = hedges[tidx + E_OFFSET1(hedgeN)] + tid;
                // unsigned candidate = nodes[adj_list[curr_loc] - hedgeN + N_PARENT1(nodeN)] - newHedgeN;
                // if (isSelfMergeNode[adj_list[curr_loc] - hedgeN] == 1) {
                //     isDuplica[curr_loc] = 1;
                //     atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                //     atomicAdd(&newTotalPinSize[0], 1);
                //     tid += blockDim.x;
                //     continue;
                // }
                if (isDuplica[curr_loc] == 1) {
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                    tid += blockDim.x;
                    continue;
                }
                unsigned candidate = adj_parlist[curr_loc] - newHedgeN;
                unsigned bitset_idx = candidate / 32;
                unsigned bit_offset = candidate & 31;
                unsigned bitset_loc = (tidx % num_hedges) * bitLen + bitset_idx;
                int cur_bit = atomicOr(&bitset[bitset_loc], (0x80000000 >> bit_offset));
                unsigned shift_bits = 31 - bit_offset;
                int extract_bit_val = (cur_bit & (1 << shift_bits)) >> shift_bits;
                if (extract_bit_val == 0) {
                    isDuplica[curr_loc] = 1;
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                }
                tid += blockDim.x;
            }
            __syncthreads();
            tid = threadIdx.x;
            while (tid < hedges[tidx + E_DEGREE1(hedgeN)]) {
                unsigned curr_loc = hedges[tidx + E_OFFSET1(hedgeN)] + tid;
                // unsigned candidate = nodes[adj_list[curr_loc] - hedgeN + N_PARENT1(nodeN)] - newHedgeN;
                unsigned candidate = adj_parlist[curr_loc] - newHedgeN;
                unsigned bitset_idx = candidate / 32;
                unsigned bitset_loc = (tidx % num_hedges) * bitLen + bitset_idx;
                bitset[bitset_loc] = 0;
                tid += blockDim.x;
            }
            __syncthreads();
        }
        tidx += gridDim.x;
    }
}


__global__ void markDuplicateParentInPins1_mod(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, int maxHedgeSize, 
                                        int large_hedge_threshold, int group_work_len) {
    int tidx = blockIdx.x;
    if (tidx < hedgeN) {
        int local_id = tidx % group_work_len;
        int cur_hsize = hedges[tidx + E_DEGREE1(hedgeN)];
        if (eInBag[tidx]) {
            unsigned h_id = next_id[tidx];
            int id = h_id;
            int tid = threadIdx.x;
            // int group_id = tidx / group_work_len;
            if (cur_hsize >= large_hedge_threshold) {
                int worklen = 0;
                if (local_id == 0 && hedges[tidx + 1 + E_DEGREE1(hedgeN)] < large_hedge_threshold) {
                    worklen = (hedges[tidx + 1 + E_DEGREE1(hedgeN)] + cur_hsize) / 2;
                } else if (local_id == 1 && hedges[tidx - 1 + E_DEGREE1(hedgeN)] < large_hedge_threshold) {
                    worklen = (hedges[tidx - 1 + E_DEGREE1(hedgeN)] + cur_hsize) / 2;
                }
                // __shared__ int count[1];
                // count[0] = 0;
                // __syncthreads();
                // while (tid < cur_hsize) {
                while (tid < worklen) {
                    unsigned pid = adj_parlist[hedges[tidx + E_OFFSET1(hedgeN)] + tid];
                    bool isfind = false;
                    for (int i = 0; i < tid; i++) {
                        // if (nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                        if (adj_parlist[hedges[tidx + E_OFFSET1(hedgeN)] + i] == pid) { 
                            isfind = true;
                            break;
                        }
                    }
                    if (!isfind) {
                        isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tid] = 1;
                        atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                        atomicAdd(&newTotalPinSize[0], 1);
                        // if (cur_hsize == 1205) {
                        //     atomicAdd(&count[0], 1);
                        //     if (threadIdx.x == 0)   printf("%d %d %d\n", tidx, id, worklen);
                        // }
                    }
                    tid += blockDim.x;
                }
                // __syncthreads();
                // if (threadIdx.x == 0 && cur_hsize == 1205)  printf("generated %d nodes in %d\n", count[0], tidx);
            } else {
                while (tid < cur_hsize) {
                    // unsigned pid = nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)];
                    unsigned pid = adj_parlist[hedges[tidx + E_OFFSET1(hedgeN)] + tid];
                    bool isfind = false;
                    for (int i = 0; i < tid; i++) {
                        // if (nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                        if (adj_parlist[hedges[tidx + E_OFFSET1(hedgeN)] + i] == pid) { 
                            isfind = true;
                            break;
                        }
                    }
                    if (!isfind) {
                        isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tid] = 1;
                        atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                        atomicAdd(&newTotalPinSize[0], 1);
                    }
                    tid += blockDim.x;
                }
                int steal_id = -1;
                // if (tid == 0) {
                    // for (int i = group_id * group_work_len; i < (group_id + 1) * group_work_len; ++i) {
                    //     if (hedges[i + E_DEGREE1(hedgeN)] >= large_hedge_threshold) {
                    //         hasLargeHyperedge = true;
                    //         steal_id = i;
                    //     }
                    // }
                    if (local_id == 0 && hedges[tidx + 1 + E_DEGREE1(hedgeN)] >= large_hedge_threshold) {
                        steal_id = tidx + 1;
                    } else if (local_id == 1 && hedges[tidx - 1 + E_DEGREE1(hedgeN)] >= large_hedge_threshold) {
                        steal_id = tidx - 1;
                    }
                // }
                // __syncthreads();
                if (steal_id >= 0) {
                    // if (threadIdx.x == 0 && cur_hsize == 1205) {
                    //     printf("here!!!\n");
                    // }
                    int beg = threadIdx.x + (hedges[steal_id + E_DEGREE1(hedgeN)] + cur_hsize) / 2;
                    int end = hedges[steal_id + E_DEGREE1(hedgeN)];
                    int steal_next_id = next_id[steal_id];
                    while (beg < end) {
                        unsigned pid = adj_parlist[hedges[steal_id + E_OFFSET1(hedgeN)] + beg];
                        bool isfind = false;
                        for (int i = 0; i < beg; i++) {
                            // if (nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                            if (adj_parlist[hedges[steal_id + E_OFFSET1(hedgeN)] + i] == pid) { 
                                isfind = true;
                                break;
                            }
                        }
                        if (!isfind) {
                            isDuplica[hedges[steal_id + E_OFFSET1(hedgeN)] + beg] = 1;
                            atomicAdd(&newHedges[steal_next_id + E_DEGREE1(newHedgeN)], 1);
                            atomicAdd(&newTotalPinSize[0], 1);
                        }
                        beg += blockDim.x;
                    }
                }
            }
        } else {
            int steal_id = -1;
            if (local_id == 0 && hedges[tidx + 1 + E_DEGREE1(hedgeN)] >= large_hedge_threshold) {
                steal_id = tidx + 1;
            } else if (local_id == 1 && hedges[tidx - 1 + E_DEGREE1(hedgeN)] >= large_hedge_threshold) {
                steal_id = tidx - 1;
            }
            if (steal_id >= 0) {
                int beg = threadIdx.x + (hedges[steal_id + E_DEGREE1(hedgeN)] + cur_hsize) / 2;
                int end = hedges[steal_id + E_DEGREE1(hedgeN)];
                int steal_next_id = next_id[steal_id];
                while (beg < end) {
                    unsigned pid = adj_parlist[hedges[steal_id + E_OFFSET1(hedgeN)] + beg];
                    bool isfind = false;
                    for (int i = 0; i < beg; i++) {
                        // if (nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                        if (adj_parlist[hedges[steal_id + E_OFFSET1(hedgeN)] + i] == pid) { 
                            isfind = true;
                            break;
                        }
                    }
                    if (!isfind) {
                        isDuplica[hedges[steal_id + E_OFFSET1(hedgeN)] + beg] = 1;
                        atomicAdd(&newHedges[steal_next_id + E_DEGREE1(newHedgeN)], 1);
                        atomicAdd(&newTotalPinSize[0], 1);
                    }
                    beg += blockDim.x;
                }
            }
        }
    }
}

__global__ void markDuplicateParentInPins1_workstealing(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, int maxHedgeSize, 
                                        int large_hedge_threshold, int group_work_len) {
    int tidx = blockIdx.x;
    if (tidx < hedgeN) {
        int local_id = tidx % group_work_len;
        int group_id = tidx / group_work_len;
        int cur_hsize = hedges[tidx + E_DEGREE1(hedgeN)];
        int tid = threadIdx.x;
        if (eInBag[tidx] && cur_hsize >= large_hedge_threshold) {
            unsigned h_id = next_id[tidx];
            int id = h_id;
            int worklen = 0;
            int start = group_work_len * group_id;
            int end = min((group_id + 1) * group_work_len, hedgeN);
            int j = 0;
            while (start < end) {
                worklen += hedges[start + E_DEGREE1(hedgeN)];
                j++;
                start++;
            }
            worklen /= j;
            // if (threadIdx.x == 0 && hedges[tidx + E_DEGREE1(hedgeN)] == 1205) {
            //     printf("%d %d %d %d %d %d\n", tidx, group_id, worklen, group_work_len * group_id, end, j);
            // }
            while (tid < worklen) {
                unsigned pid = adj_parlist[hedges[tidx + E_OFFSET1(hedgeN)] + tid];
                bool isfind = false;
                for (int i = 0; i < tid; i++) {
                    // if (nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                    if (adj_parlist[hedges[tidx + E_OFFSET1(hedgeN)] + i] == pid) { 
                        isfind = true;
                        break;
                    }
                }
                if (!isfind) {
                    isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tid] = 1;
                    atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                    atomicAdd(&newTotalPinSize[0], 1);
                }
                tid += blockDim.x;
            }
        } else if (cur_hsize < large_hedge_threshold) {
            if (eInBag[tidx]) {
                unsigned h_id = next_id[tidx];
                int id = h_id;
                while (tid < cur_hsize) {
                    // unsigned pid = nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)];
                    unsigned pid = adj_parlist[hedges[tidx + E_OFFSET1(hedgeN)] + tid];
                    bool isfind = false;
                    for (int i = 0; i < tid; i++) {
                        // if (nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                        if (adj_parlist[hedges[tidx + E_OFFSET1(hedgeN)] + i] == pid) { 
                            isfind = true;
                            break;
                        }
                    }
                    if (!isfind) {
                        isDuplica[hedges[tidx + E_OFFSET1(hedgeN)] + tid] = 1;
                        atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                        atomicAdd(&newTotalPinSize[0], 1);
                    }
                    tid += blockDim.x;
                }
                int steal_id = -1;
                for (int i = group_work_len * group_id; i < min((group_id + 1) * group_work_len, hedgeN); ++i) {
                    if (hedges[i + E_DEGREE1(hedgeN)] >= large_hedge_threshold) {
                        steal_id = i;
                        // if (threadIdx.x == 0 && hedges[i + E_DEGREE1(hedgeN)] == 1205) {
                        //     printf("%d %d\n", group_id, steal_id);
                        // }
                        break;
                    }
                }
                // if (threadIdx.x == 0 && hedges[steal_id + E_DEGREE1(hedgeN)] == 1205) {
                //     printf("%d %d\n", group_id, steal_id);
                // }
                if (steal_id >= 0) {
                    int seg_id = local_id > (steal_id % group_work_len) ? local_id - 1 : local_id;
                    int worklen = 0;
                    int start = group_work_len * group_id;
                    int ends = min((group_id + 1) * group_work_len, hedgeN);
                    int j = 0;
                    while (start < ends) {
                        worklen += hedges[start + E_DEGREE1(hedgeN)];
                        j++;
                        start++;
                    }
                    worklen /= j;
                    int beg = threadIdx.x + worklen * (seg_id + 1);
                    int end = min(hedges[steal_id + E_DEGREE1(hedgeN)], worklen * (seg_id + 2));
                    int steal_next_id = next_id[steal_id];
                    // if (threadIdx.x == 0 && hedges[steal_id + E_DEGREE1(hedgeN)] == 1205) {
                    //     printf("here!! %d %d %d\n", beg, end, steal_id);
                    // }
                    while (beg < end) {
                        unsigned pid = adj_parlist[hedges[steal_id + E_OFFSET1(hedgeN)] + beg];
                        bool isfind = false;
                        for (int i = 0; i < beg; i++) {
                            // if (nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                            if (adj_parlist[hedges[steal_id + E_OFFSET1(hedgeN)] + i] == pid) { 
                                isfind = true;
                                break;
                            }
                        }
                        if (!isfind) {
                            isDuplica[hedges[steal_id + E_OFFSET1(hedgeN)] + beg] = 1;
                            atomicAdd(&newHedges[steal_next_id + E_DEGREE1(newHedgeN)], 1);
                            atomicAdd(&newTotalPinSize[0], 1);
                        }
                        beg += blockDim.x;
                    }
                }
            } else {
                int steal_id = -1;
                for (int i = group_work_len * group_id; i < min((group_id + 1) * group_work_len, hedgeN); ++i) {
                    if (hedges[i + E_DEGREE1(hedgeN)] >= large_hedge_threshold) {
                        steal_id = i;
                        break;
                    }
                }
                if (steal_id >= 0) {
                    int seg_id = local_id > (steal_id % group_work_len) ? local_id - 1 : local_id;
                    int worklen = 0;
                    int start = group_work_len * group_id;
                    int ends = min((group_id + 1) * group_work_len, hedgeN);
                    int j = 0;
                    while (start < ends) {
                        worklen += hedges[start + E_DEGREE1(hedgeN)];
                        j++;
                        start++;
                    }
                    worklen /= j;
                    int beg = threadIdx.x + worklen * (seg_id + 1);
                    int end = min(hedges[steal_id + E_DEGREE1(hedgeN)], worklen * (seg_id + 2));
                    int steal_next_id = next_id[steal_id];
                    while (beg < end) {
                        unsigned pid = adj_parlist[hedges[steal_id + E_OFFSET1(hedgeN)] + beg];
                        bool isfind = false;
                        for (int i = 0; i < beg; i++) {
                            // if (nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                            if (adj_parlist[hedges[steal_id + E_OFFSET1(hedgeN)] + i] == pid) { 
                                isfind = true;
                                break;
                            }
                        }
                        if (!isfind) {
                            isDuplica[hedges[steal_id + E_OFFSET1(hedgeN)] + beg] = 1;
                            atomicAdd(&newHedges[steal_next_id + E_DEGREE1(newHedgeN)], 1);
                            atomicAdd(&newTotalPinSize[0], 1);
                        }
                        beg += blockDim.x;
                    }
                }
            }
        }
    }
}

__global__ void markDuplicateParentInPins1_parallelism(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, 
                                        unsigned* pins_hedgeid_list, int totalsize, int maxHedgeSize) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        unsigned hid = pins_hedgeid_list[tid];
        if (eInBag[hid]) {
            unsigned h_id = next_id[hid];
            int id = h_id;
            unsigned pid = adj_parlist[tid];
            bool isfind = false;
            int beg_off = hedges[hid + E_OFFSET1(hedgeN)];
            int l_size = tid - beg_off;
            for (int i = 0; i < l_size; i++) {
                // if (nodes[adj_list[hedges[tidx + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                if (adj_parlist[beg_off + i] == pid) { 
                    isfind = true;
                    break;
                }
            }
            if (!isfind) {
                isDuplica[tid] = 1;
                atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                atomicAdd(&newTotalPinSize[0], 1);
            }
        }
    }
}

__global__ void parallel_markDuplicateParentInPins_base(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, 
                                        unsigned* pins_hedgeid_list, int totalsize, int maxHedgeSize) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        unsigned hid = pins_hedgeid_list[tid];
        if (eInBag[hid]) {
            unsigned h_id = next_id[hid];
            int id = h_id;
            unsigned pid = adj_parlist[tid];
            bool isfind = false;
            int beg_off = hedges[hid + E_OFFSET1(hedgeN)];
            int l_size = tid - beg_off;
            for (int i = 0; i < l_size; i++) {
                if (nodes[adj_list[beg_off + i] - hedgeN + N_PARENT1(nodeN)] == pid) {
                    isfind = true;
                    break;
                }
            }
            if (!isfind) {
                isDuplica[tid] = 1;
                atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                atomicAdd(&newTotalPinSize[0], 1);
            }
        }
    }
}

__global__ void markDuplicateParentInPins1_binsearch(int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, 
                                        int* newHedges, int newHedgeN, int* newTotalPinSize, int* next_id, int* eInBag, int* adj_parlist, 
                                        unsigned* pins_hedgeid_list, int totalsize, int maxHedgeSize) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        unsigned hid = pins_hedgeid_list[tid];
        if (eInBag[hid]) {
            unsigned h_id = next_id[hid];
            int id = h_id;
            unsigned pid = adj_parlist[tid];
            int isfind = -1;
            int pin_off = tid - hedges[hid + E_OFFSET1(hedgeN)];
            int beg = hedges[hid + E_OFFSET1(hedgeN)];
            int end = tid-1;
            while (beg < end) {
                int mid = (beg + end) / 2;
                if (pid < adj_parlist[mid]) {
                    end = mid -1;
                } else if (pid > adj_parlist[mid]) {
                    beg = mid + 1;
                } else {
                    isfind = mid;
                    break;
                }
            }
            if (isfind > 0) {
                isDuplica[tid] = 1;
                atomicAdd(&newHedges[id + E_DEGREE1(newHedgeN)], 1);
                atomicAdd(&newTotalPinSize[0], 1);
            }
        }
    }
}

__global__ void fillNextLevelAdjList_parallelbynode(
                                        int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, int hedgeN, int nodeN, int* newHedges, int* newNodes, 
                                        unsigned* newAdjList, unsigned* next_hedge_id, int* next_id, int* eInBag, int newNodeN, int newHedgeN, int* newTotalNodeDeg, 
                                        int* maxDegree, int* minDegree, int* newAdjListCounter, int* adj_parlist, unsigned* curr_hedge_id, int totalsize,
                                        int* sdv, long double avg) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        unsigned hid = curr_hedge_id[tid];
        if (eInBag[hid]) {
            unsigned h_id = next_id[hid];
            newHedges[E_IDNUM1(newHedgeN) + h_id] = hedges[E_IDNUM1(hedgeN) + hid];
            int id = h_id;
            if (isDuplica[tid] == 1) {
                unsigned pid = adj_parlist[tid];
                int count = atomicAdd(&newAdjListCounter[id], 1);
                newAdjList[newHedges[E_OFFSET1(newHedgeN) + id] + count] = pid;
                next_hedge_id[newHedges[E_OFFSET1(newHedgeN) + id] + count] = id;
                atomicAdd(&newNodes[N_DEGREE1(newNodeN) + (pid - newHedgeN)], 1);
                atomicAdd(&newTotalNodeDeg[0], 1);
            }
            if (tid == hedges[hid + E_OFFSET1(hedgeN)]) {
                atomicMin(&minDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                atomicMax(&maxDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                // newHedges[E_PRIORITY1(newHedgeN) + id] = INT_MAX;
                // int diff = (int)(newHedges[E_DEGREE1(newHedgeN) + id] - avg);
                // atomicAdd(&sdv[0], diff * diff);
            }
        }
    }
}

__global__ void mergeMoreNodesAcrossHyperedges_P2(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int iter, 
                                                int LIMIT, int* eMatch, int* nBag1, int* accW, int* nMatch, int* candidates, 
                                                int* nPrior, int* nHedgeId, int* cand_counts, int* represents, int* bests) {
    int bid = blockIdx.x;
    if (bid < hedgeN) {
        if (eMatch[bid]) {
            return;
        }

        int tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + bid]) {
            if (!nMatch[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN]) {
                int hedgeid = nHedgeId[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                unsigned int idnum = hedges[bid + E_IDNUM1(hedgeN)];
                if (hedgeid == idnum) {
                    atomicAdd(&cand_counts[bid], 1);
                    candidates[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = 1;
                }
            }
            else if (nPrior[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN] == INT_MIN) {
                int weight = nodes[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                atomicMin(&bests[bid], weight);
            }
            tid += blockDim.x;
        }
        __syncthreads();

        tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + bid]) {
            if (nPrior[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN] == INT_MIN) {
                int weight = nodes[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                if (weight == bests[bid]) {
                    atomicMin(&represents[bid], adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid]);
                }
            }
            tid += blockDim.x;
        }
        __syncthreads();

        if (cand_counts[bid] && bests[bid] < INT_MAX) {
            int parent = nodes[represents[bid] - hedgeN + N_PARENT1(nodeN)];
            tid = threadIdx.x;
            while (tid < hedges[E_DEGREE1(hedgeN) + bid]) {
                int hedgeid = nHedgeId[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                unsigned int idnum = hedges[bid + E_IDNUM1(hedgeN)];
                int candidate = candidates[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN];
                if (candidate && hedgeid == idnum) {
                    int tmpW = nodes[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_WEIGHT1(nodeN)];
                    if (tmpW + accW[parent - hedgeN] <= LIMIT) {
                        nBag1[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
                        nMatch[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid]-hedgeN] = 1;
                        nodes[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARENT1(nodeN)] = parent;
                        nHedgeId[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN] = nHedgeId[represents[bid] - hedgeN];
                    }
                }
                tid += blockDim.x;
            }
        }
    }
}

__global__ void collectCandidateWeights_P2(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, 
                                        int* weights, int* nHedgeId)
{
    int bid = blockIdx.x;
    if (bid < hedgeN) {
        int tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + bid]) {
            int idnum = hedges[bid + E_IDNUM1(hedgeN)];
            unsigned dst = adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid];
            int hedgeid = nHedgeId[dst - hedgeN];
            int weight = nodes[dst - hedgeN + N_WEIGHT1(nodeN)];
            weights[hedges[bid + E_OFFSET1(hedgeN)] + tid] = (idnum == hedgeid) ? weight : 0;
            tid += blockDim.x;
        }
    }
}

__global__ void collectCandidateNodes_P2(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int LIMIT, 
                                        int* weights, int* candidates, int* flag, int* nodeid, int* cand_count) 
{
    int bid = blockIdx.x;
    if (bid < hedgeN) {
        int tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + bid]) {
            unsigned index = hedges[bid + E_OFFSET1(hedgeN)] + tid;
            int cur_weight = bid > 0 ? weights[index] - weights[hedges[bid + E_OFFSET1(hedgeN)] - 1] : weights[index];
            int weight_diff = index > 0 ? weights[index] - weights[index - 1] : weights[index];
            if (weight_diff == 0) {
                flag[bid] = true;
            } else if (cur_weight <= LIMIT) {
                unsigned dst = adj_list[index];
                atomicMin(&nodeid[bid], dst);
                atomicAdd(&cand_count[bid], 1);
                candidates[dst - hedgeN] = 1;
            }
            tid += blockDim.x;
        }
    }
}

__global__ void assignSuperNodeToCandidates_P2(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, 
                                                int* nHedgeId, int* newHedgeN, int* newNodeN, 
                                                int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* parent,
                                                int* candidates, int* flag, int* nodeid, int* cand_count)
{
    int bid = blockIdx.x;
    if (bid < hedgeN) {
        int tid = threadIdx.x;
        while (tid < hedges[E_DEGREE1(hedgeN) + bid]) {
            if (cand_count[bid]) {
                if (!flag[bid] || cand_count[bid] > 1) {
                    if (tid == 0) {
                        eMatch[bid] = 1;
                        if (flag[bid]) {
                            eInBag[bid] = 1;
                            atomicAdd(&newHedgeN[0], 1);
                        }
                        nBag[nodeid[bid] - hedgeN] = 1;
                        atomicAdd(&newNodeN[0], 1);
                    }
                    int represent = nodeid[bid];
                    int idnum = hedges[bid + E_IDNUM1(hedgeN)];
                    unsigned dst = adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid];
                    int hedgeid = nHedgeId[dst - hedgeN];
                    if (candidates[dst - hedgeN] && idnum == hedgeid) {
                        nMatch[dst - hedgeN] = 1;
                        parent[dst - hedgeN] = represent;
                        int tmpW = nodes[dst - hedgeN + N_WEIGHT1(nodeN)];
                        atomicAdd(&accW[represent - hedgeN], tmpW);
                    }
                }
            }
            tid += blockDim.x;
        }
    }
}
