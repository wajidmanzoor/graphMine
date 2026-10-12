#include "coarsening_kernels.cuh"

__host__ __device__ int hash(unsigned val) {
    unsigned long int seed = val * 1103515245 + 12345;
    return ((unsigned)(seed / 65536) % 32768);
}

__global__ void hedgePrioritySetting(Hypergraph* hgr, int hedgeN, unsigned matching_policy) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        hgr->hedges[E_RAND(hgr) + tid] = hash(hgr->hedges[E_IDNUM(hgr) + tid]);
        if (matching_policy == 0) {
            hgr->hedges[E_PRIORITY(hgr) + tid] = -hgr->hedges[E_RAND(hgr) + tid];
            hgr->hedges[E_RAND(hgr) + tid] = -hgr->hedges[E_IDNUM(hgr) + tid];
        } else if (matching_policy == 1) {
            hgr->hedges[E_PRIORITY(hgr) + tid] = hgr->hedges[E_DEGREE(hgr) + tid];
        } else if (matching_policy == 2) {
            hgr->hedges[E_PRIORITY(hgr) + tid] = -hgr->hedges[E_DEGREE(hgr) + tid];
        } else if (matching_policy == 3) {
            for (int i = 0; i < hgr->hedges[E_DEGREE(hgr) + tid]; ++i) {
                unsigned w = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_WEIGHT(hgr)];
                hgr->hedges[E_PRIORITY(hgr) + tid] += -w;
            }
        } else if (matching_policy == 4) {
            for (int i = 0; i < hgr->hedges[E_DEGREE(hgr) + tid]; ++i) {
                unsigned w = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_WEIGHT(hgr)];
                hgr->hedges[E_PRIORITY(hgr) + tid] += w;
            }
        } else if (matching_policy == 5) {
            unsigned w = 0;
            for (int i = 0; i < hgr->hedges[E_DEGREE(hgr) + tid]; ++i) {
                w += hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_WEIGHT(hgr)];
            }
            hgr->hedges[E_PRIORITY(hgr) + tid] = -(w / hgr->hedges[E_DEGREE(hgr) + tid]);
        }
    }
}

__global__ void multiNodeMatchingI(Hypergraph* hgr, int hedgeN) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        for (int i = 0; i < hgr->hedges[E_DEGREE(hgr) + tid]; ++i) {
            int hedgePrior = hgr->hedges[E_PRIORITY(hgr) + tid];
            int index = hgr->adj_list[hgr->hedges[E_OFFSET(hgr) + tid] + i]-hgr->hedgeNum;
            int* nodePrior = &hgr->nodes[N_PRIORITY(hgr) + index];
            atomicMin(nodePrior, hedgePrior);
        }
    }
}

__global__ void multiNodeMatchingII(Hypergraph* hgr, int hedgeN) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        for (int i = 0; i < hgr->hedges[E_DEGREE(hgr) + tid]; ++i) {
            int hedgePrior = hgr->hedges[E_PRIORITY(hgr) + tid];
            int index = hgr->adj_list[hgr->hedges[E_OFFSET(hgr) + tid] + i]-hgr->hedgeNum;
            int nodePrior = hgr->nodes[N_PRIORITY(hgr) + index];
            if (hedgePrior == nodePrior) {
                int hedgeRand = hgr->hedges[E_RAND(hgr) + tid];
                int idx = hgr->adj_list[hgr->hedges[E_OFFSET(hgr) + tid] + i]-hgr->hedgeNum;
                int* nodeRand = &hgr->nodes[N_RAND(hgr) + idx];
                atomicMin(nodeRand, hedgeRand);
            }
        }
    }
}

__global__ void multiNodeMatchingIII(Hypergraph* hgr, int hedgeN) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        for (int i = 0; i < hgr->hedges[E_DEGREE(hgr) + tid]; ++i) {
            int hedgeRand = hgr->hedges[E_RAND(hgr) + tid];
            int index = hgr->adj_list[hgr->hedges[E_OFFSET(hgr) + tid] + i]-hgr->hedgeNum;
            int nodeRand = hgr->nodes[N_RAND(hgr) + index];
            if (hedgeRand == nodeRand) {
                int idnum = hgr->hedges[E_IDNUM(hgr) + tid];
                int idx = hgr->adj_list[hgr->hedges[E_OFFSET(hgr) + tid] + i]-hgr->hedgeNum;
                int* hedgeid = &hgr->nodes[N_HEDGEID(hgr) + idx];
                atomicMin(hedgeid, idnum);
            }
        }
    }
}

__global__ void createNodePhaseI(Hypergraph* hgr, int hedgeN, int LIMIT, Hypergraph* coarsen, int iter) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        bool flag = false;
        unsigned nodeid = INT_MAX;
        int count = 0;
        int w = 0;
        for (int i = 0; i < hgr->hedges[E_DEGREE(hgr) + tid]; ++i) {
            unsigned int isMatched = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_MATCHED(hgr)];
            if (isMatched) { // return old value
                flag = true;
                continue;
            }
            unsigned int idnum = hgr->hedges[tid + E_IDNUM(hgr)];
            unsigned int hedgeid = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_HEDGEID(hgr)];
            unsigned int dst = hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i];
            int weight = hgr->nodes[dst - hgr->hedgeNum + N_WEIGHT(hgr)];
            if (idnum == hedgeid) {
                if (w + weight > LIMIT) {
                    // printf("==========w:%d weight:%d\n", w, weight);
                    break;
                }
                nodeid = min(nodeid, dst);
                count++;
                hgr->nodes[dst-hgr->hedgeNum + N_FOR_UPDATE(hgr)] = true;
                w += weight;
            } else {
                flag = true;
            }
        }
        if (iter == 1 && tid + E_MATCHED(hgr) == 96779) {
            printf("%d, %d, %d\n", tid, flag, count);
        }
        if (count) {
            if (flag && count == 1) { // do not update this node to match this hedge, leave later matching
                return;
            }
            hgr->hedges[tid + E_MATCHED(hgr)] = 1;
            if (flag) {
                hgr->hedges[tid + E_INBAG(hgr)] = true;
                atomicAdd(&coarsen->hedgeNum, 1);
            }
            // if (hgr->nodes[nodeid - hgr->hedgeNum + N_INBAG(hgr)] == 0) {
            hgr->nodes[nodeid - hgr->hedgeNum + N_INBAG(hgr)] = 1;//true;
            atomicAdd(&coarsen->nodeNum, 1);
            // }
            // if (iter == 1) {
            //     printf("%d\n", nodeid);
            // }
            for (int i = 0; i < hgr->hedges[E_DEGREE(hgr) + tid]; ++i) {
                unsigned int idnum = hgr->hedges[tid + E_IDNUM(hgr)];
                unsigned int hedgeid = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_HEDGEID(hgr)];
                if (hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_FOR_UPDATE(hgr)] && idnum == hedgeid) {
                    // if (iter == 2)  printf("matched!!!\n");
                    hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_MATCHED(hgr)] = 1;
                    hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_PARENT(hgr)] = nodeid;
                    int tmpW = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_WEIGHT(hgr)];
                    atomicAdd(&hgr->nodes[nodeid - hgr->hedgeNum + N_TMPW(hgr)], tmpW);
                }
            }
        }
    }
}

__global__ void ResetPrioForUpdateUnmatchNodes(Hypergraph* hgr, int hedgeN) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        if (hgr->hedges[E_MATCHED(hgr) + tid]) {
            return;
        }
        for (int i = 0; i < hgr->hedges[E_DEGREE(hgr) + tid]; ++i) {
            if (hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_MATCHED(hgr)]) {
                hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_PRIORITY(hgr)] = INT_MIN;
            }
        }
    }
}
__global__ void coarseMoreNodes(Hypergraph* hgr, int hedgeN, int iter, int LIMIT) {
// __global__ void coarseMoreNodes(Hypergraph* hgr, int hedgeN, int iter, int LIMIT, int* tmp_bag) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        if (hgr->hedges[tid + E_MATCHED(hgr)]) {
            return;
        }
        int best = INT_MAX;
        unsigned represent = 0;//INT_MAX;
        int counts = 0;
        for (int i = 0; i < hgr->hedges[E_DEGREE(hgr) + tid]; ++i) {
            if (!hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_MATCHED(hgr)]) {
                unsigned int hedgeid = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_HEDGEID(hgr)];
                unsigned int idnum = hgr->hedges[tid + E_IDNUM(hgr)];
                if (hedgeid == idnum) {
                    counts++;
                    hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_MORE_UPDATE(hgr)] = true;
                }
            } else if (hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_PRIORITY(hgr)] == INT_MIN) {
                if (hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_WEIGHT(hgr)] < best) {
                    best = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_WEIGHT(hgr)];
                    represent = hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i];
                } else if (hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_WEIGHT(hgr)] == best) {
                    if (hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i] < represent) {
                        represent = hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i];
                    }
                }
            }
        }
        if (counts) {
            if (best < INT_MAX) {
                int parent = hgr->nodes[represent-hgr->hedgeNum + N_PARENT(hgr)];
                for (int i = 0; i < hgr->hedges[E_DEGREE(hgr) + tid]; ++i) {
                    unsigned int hedgeid = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_HEDGEID(hgr)];
                    unsigned int idnum = hgr->hedges[tid + E_IDNUM(hgr)];
                    if (hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_MORE_UPDATE(hgr)] && hedgeid == idnum) {
                        int tmpW = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_WEIGHT(hgr)];
                        int weight = hgr->nodes[parent-hgr->hedgeNum + N_TMPW(hgr)];
                        if (tmpW + weight > LIMIT) {
                            break;
                            // continue;
                        }
                        // tmp_bag[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum] = 1;
                        hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_TMPBAG(hgr)] = 1;
                        hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_MATCHED(hgr)] = 1;
                        hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_PARENT(hgr)] = parent;
                        // int tmpW = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_WEIGHT(hgr)];
                        // atomicAdd(&hgr->nodes[parent-hgr->hedgeNum + N_TMPW(hgr)], tmpW);
                        hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_HEDGEID(hgr)] 
                                = hgr->nodes[represent-hgr->hedgeNum + N_HEDGEID(hgr)];
                    }
                }
            }
        }
    }
}

__global__ void coarsenPhaseII(Hypergraph* hgr, int hedgeN, Hypergraph* coarsen) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        if (hgr->hedges[tid + E_MATCHED(hgr)]) {
            return;
        }
        unsigned nodeid;
        int count = 0;
        for (int i = 0; i < hgr->hedges[E_DEGREE(hgr) + tid]; ++i) {
            if (hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_MATCHED(hgr)]) {
                if (count == 0) {
                    nodeid = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_PARENT(hgr)];
                    count++;
                } else if (nodeid != hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_PARENT(hgr)]) {
                    count++;
                    break;
                }
            } else {
                count = 0;
                break;
            }
        }
        if (count == 1) {
            hgr->hedges[tid + E_MATCHED(hgr)] = 1;
        } else {
            hgr->hedges[tid + E_INBAG(hgr)] = 1;//true;
            atomicAdd(&coarsen->hedgeNum, 1);
            hgr->hedges[tid + E_MATCHED(hgr)] = 1;
        }
    }
}

__global__ void noedgeNodeMatching(Hypergraph* hgr, int nodeN, Hypergraph* coarsen) {
// __global__ void noedgeNodeMatching(Hypergraph* hgr, int nodeN, Hypergraph* coarsen, int* tmp_bag) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        // if (tmp_bag[tid]) {
        if (hgr->nodes[N_TMPBAG(hgr) + tid]) {
            atomicAdd(&hgr->nodes[N_TMPW(hgr) + hgr->nodes[tid + N_PARENT(hgr)] - hgr->hedgeNum], hgr->nodes[N_WEIGHT(hgr) + tid]);
        }
        if (!hgr->nodes[N_MATCHED(hgr) + tid]) {
            hgr->nodes[tid + N_INBAG(hgr)] = 1;//true;
            atomicAdd(&coarsen->nodeNum, 1);
            hgr->nodes[tid + N_MATCHED(hgr)] = 1;
            hgr->nodes[tid + N_PARENT(hgr)] = tid + hgr->hedgeNum;
            hgr->nodes[tid + N_HEDGEID(hgr)] = INT_MAX;
            hgr->nodes[N_TMPW(hgr) + tid] = hgr->nodes[N_WEIGHT(hgr) + tid];
        }
    }
}

__global__ void createNodeMapping(Hypergraph* hgr, int nodeN, Hypergraph* coarsen) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (hgr->nodes[N_INBAG(hgr) + tid]) {
            coarsen->nodes[hgr->nodes[N_MAP_PARENT(hgr) + tid] - coarsen->hedgeNum + N_TMPW(coarsen)]
                     = hgr->nodes[N_TMPW(hgr) + tid];
        }
    }
}

__global__ void updateSuperVertexId(Hypergraph* hgr, int nodeN) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        int index = hgr->nodes[N_PARENT(hgr) + tid] - hgr->hedgeNum;
        hgr->nodes[N_PARENT(hgr) + tid] = hgr->nodes[N_MAP_PARENT(hgr) + index]; // mapParentTO
    }
}

