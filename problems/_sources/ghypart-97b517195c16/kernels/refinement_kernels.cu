#include "refinement_kernels.cuh"

__host__ __device__ int getGains(Hypergraph* hgr, unsigned nodeid) {
    return hgr->nodes[nodeid + N_FS(hgr)] - (hgr->nodes[nodeid + N_TE(hgr)] + hgr->nodes[nodeid + N_COUNTER(hgr)]);
}

__global__ void initGains(Hypergraph* hgr, int hedgeN) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        int p1 = 0;
        int p2 = 0;
        for (int i = 0; i < hgr->hedges[tid + E_DEGREE(hgr)]; ++i) {
            int part = hgr->nodes[hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i]-hgr->hedgeNum + N_PARTITION(hgr)];
            part == 0 ? p1++ : p2++;
            if (p1 > 1 && p2 > 1) {
                break;
            }
        }
        if (!(p1 > 1 && p2 > 1) && (p1 + p2 > 1)) {
        // if (p1 + p2 > 1) {
            for (int i = 0; i < hgr->hedges[tid + E_DEGREE(hgr)]; ++i) {
                unsigned int dst = hgr->adj_list[hgr->hedges[tid + E_OFFSET(hgr)] + i];
                int part = hgr->nodes[dst - hgr->hedgeNum + N_PARTITION(hgr)];
                int tmpnode = part == 0 ? p1 : p2;
                if (tmpnode == 1) {
                    atomicAdd(&hgr->nodes[dst-hgr->hedgeNum + N_FS(hgr)], 1);
                } else if (tmpnode == p1 + p2) {
                    atomicAdd(&hgr->nodes[dst-hgr->hedgeNum + N_TE(hgr)], 1);
                }
            }
        }
    }
}

__global__ void createNodeLists(Hypergraph* hgr, tmpNode* nodelistz, tmpNode* nodelistn, 
                                unsigned* zerow, unsigned* nonzerow) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hgr->nodeNum) {
        if (hgr->nodes[tid + N_FS(hgr)] == 0 && hgr->nodes[tid + N_TE(hgr)] == 0) {
            return;
        }
        int gain = getGains(hgr, tid);
        if (gain < 0) {
            return;
        }
        unsigned pp = hgr->nodes[tid + N_PARTITION(hgr)];
        if (pp == 0) {
            unsigned index = atomicAdd(&zerow[0], 1);
            nodelistz[index].nodeid = hgr->nodes[tid + N_ELEMID(hgr)];
            nodelistz[index].gain = gain;
            nodelistz[index].weight = hgr->nodes[tid + N_WEIGHT(hgr)];
        } else {
            unsigned index = atomicAdd(&nonzerow[0], 1);
            nodelistn[index].nodeid = hgr->nodes[tid + N_ELEMID(hgr)];
            nodelistn[index].gain = gain;
            nodelistn[index].weight = hgr->nodes[tid + N_WEIGHT(hgr)];
        }
    }
}

__global__ void createNodeLists1(Hypergraph* hgr, tmpNode* nodelistz, tmpNode* nodelistn, 
                                unsigned* zerow, unsigned* nonzerow) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hgr->nodeNum) {
        int gain = getGains(hgr, tid);
        unsigned pp = hgr->nodes[tid + N_PARTITION(hgr)];
        if (pp == 0) {
            unsigned index = atomicAdd(&zerow[0], 1);
            nodelistz[index].nodeid = hgr->nodes[tid + N_ELEMID(hgr)];
            nodelistz[index].gain = gain;
            nodelistz[index].weight = hgr->nodes[tid + N_WEIGHT(hgr)];
        } else {
            unsigned index = atomicAdd(&nonzerow[0], 1);
            nodelistn[index].nodeid = hgr->nodes[tid + N_ELEMID(hgr)];
            nodelistn[index].gain = gain;
            nodelistn[index].weight = hgr->nodes[tid + N_WEIGHT(hgr)];
        }
    }
}

__global__ void reComputeGains(Hypergraph* hgr, int hedgeN, tmpNode* nodelistz, tmpNode* nodelistn, 
                                unsigned* zerow, unsigned* nonzerow, int* move_flag, unsigned nodeListLen/*, tmpNode* mergeNodeList*/) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeListLen) {
        if (tid < zerow[0]) {
            // mergeNodeList[tid].nodeid = nodelistz[tid].nodeid;
            // mergeNodeList[tid].gain = nodelistz[tid].gain;
            // mergeNodeList[tid].weight = nodelistz[tid].weight;
            unsigned nodeid = nodelistz[tid].nodeid;
            for (int i = 0; i < hgr->nodes[N_DEGREE(hgr) + nodeid - hgr->hedgeNum]; ++i) {
                unsigned hedgeid = hgr->incident_nets[hgr->nodes[N_OFFSET(hgr) + nodeid - hgr->hedgeNum] + i];
                unsigned degree = hgr->hedges[E_DEGREE(hgr) + hedgeid];
                int p1 = 0;
                int p2 = 0;
                for (int j = 0; j < degree; ++j) {
                    unsigned neigh = hgr->adj_list[hgr->hedges[hedgeid + E_OFFSET(hgr)] + j];
                    if (neigh != nodeid) {
                        int part = hgr->nodes[neigh - hgr->hedgeNum + N_PARTITION(hgr)];
                        if (move_flag[neigh - hgr->hedgeNum] == 1) { // move from 0 to 1
                            part = 1;
                        } else if (move_flag[neigh - hgr->hedgeNum] == -1) {
                            part = 0;
                        }
                        part == 1 ? p1++ : p2++;
                    }
                }
                if (p1 == degree - 1) {
                    nodelistz[tid].real_gain++;
                    nodelistz[tid].tmp_FS++;
                    // mergeNodeList[tid].real_gain++;
                } else if (p2 == degree - 1) {
                    nodelistz[tid].real_gain--;
                    nodelistz[tid].tmp_TE++;
                    // mergeNodeList[tid].real_gain--;
                }
            }
        } else if (tid >= zerow[0] && tid < nodeListLen) {
            // mergeNodeList[tid].nodeid = nodelistz[tid - zerow[0]].nodeid;
            // mergeNodeList[tid].gain = nodelistz[tid - zerow[0]].gain;
            // mergeNodeList[tid].weight = nodelistz[tid - zerow[0]].weight;
            unsigned nodeid = nodelistn[tid - zerow[0]].nodeid;
            for (int i = 0; i < hgr->nodes[N_DEGREE(hgr) + nodeid - hgr->hedgeNum]; ++i) {
                unsigned hedgeid = hgr->incident_nets[hgr->nodes[N_OFFSET(hgr) + nodeid - hgr->hedgeNum] + i];
                unsigned degree = hgr->hedges[E_DEGREE(hgr) + hedgeid];
                int p1 = 0;
                int p2 = 0;
                for (int j = 0; j < degree; ++j) {
                    unsigned neigh = hgr->adj_list[hgr->hedges[hedgeid + E_OFFSET(hgr)] + j];
                    if (neigh != nodeid) {
                        int part = hgr->nodes[neigh - hgr->hedgeNum + N_PARTITION(hgr)];
                        if (move_flag[neigh - hgr->hedgeNum] == 1) { // move from 1 to 0
                            part = 1;
                        } else if (move_flag[neigh - hgr->hedgeNum] == -1) {
                            part = 0;
                        }
                        part == 1 ? p1++ : p2++;
                    }
                }
                if (p2 == degree - 1) {
                    nodelistn[tid - zerow[0]].real_gain++;
                    // mergeNodeList[tid].real_gain++;
                } else if (p1 == degree - 1) {
                    nodelistn[tid - zerow[0]].real_gain--;
                    // mergeNodeList[tid].real_gain--;
                }
            }
        }
    }
}

__global__ void parallelMoveNodes(Hypergraph* hgr, tmpNode* nodelistz, tmpNode* nodelistn, unsigned workLen/*, int* reduction*/) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    // if (tid < moveLenSum) {
    //     tid < zeroPartMoveLen ? hgr->nodes[nodelistz[tid].nodeid - hgr->hedgeNum + N_PARTITION(hgr)] = 1
    //                           : hgr->nodes[nodelistz[tid - zeroPartMoveLen].nodeid - hgr->hedgeNum + N_PARTITION(hgr)] = 0;
    // }
    if (tid < workLen) {
        if (nodelistz[tid].real_gain > 0) {
            hgr->nodes[nodelistz[tid].nodeid - hgr->hedgeNum + N_PARTITION(hgr)] = 1;
            // atomicAdd(&reduction[0], nodelistz[tid].real_gain);
        }
        if (nodelistn[tid].real_gain > 0) {
            hgr->nodes[nodelistn[tid].nodeid - hgr->hedgeNum + N_PARTITION(hgr)] = 0;
            // atomicAdd(&reduction[0], -nodelistn[tid].real_gain);
        }
    }
}

__global__ void parallelMoveNodes1(Hypergraph* hgr, tmpNode* nodelistz, tmpNode* nodelistn, unsigned posNum0, unsigned posNum1, unsigned posNum) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < posNum) {
        if (tid < posNum0) {
            hgr->nodes[nodelistz[tid].nodeid - hgr->hedgeNum + N_PARTITION(hgr)] = 1;
        } else {
            hgr->nodes[nodelistn[tid - posNum0].nodeid - hgr->hedgeNum + N_PARTITION(hgr)] = 0;
        }
    }
}


__global__ void parallelSwapNodes(Hypergraph* hgr, tmpNode* nodelistz, tmpNode* nodelistn, 
                                unsigned* zerow, unsigned* nonzerow, unsigned workLen) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < workLen) {
        int nodeid = tid % 2 == 0 ? nodelistn[tid / 2].nodeid : nodelistz[tid / 2].nodeid;
        hgr->nodes[nodeid-hgr->hedgeNum + N_PARTITION(hgr)] == 0 ? hgr->nodes[nodeid-hgr->hedgeNum + N_PARTITION(hgr)] = 1 : 
                                                          hgr->nodes[nodeid-hgr->hedgeNum + N_PARTITION(hgr)] = 0;
        hgr->nodes[nodeid-hgr->hedgeNum + N_COUNTER(hgr)]++;
    }
}

__global__ void placeNodesInBuckets(Hypergraph* hgr, tmpNode* nodeList, unsigned* bucketcnt, 
                                    tmpNode* negGainlist, unsigned* negCnt, unsigned partID) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hgr->nodeNum) {
        float gain = ((float)getGains(hgr, tid)) / ((float)hgr->nodes[tid + N_WEIGHT(hgr)]);
        if (hgr->nodes[tid + N_PARTITION(hgr)] == partID) {
            if (gain >= 1.0f) { // nodes with gain >= 1.0f are in one bucket
                int index = atomicAdd(&bucketcnt[0], 1);
                nodeList[0 * hgr->nodeNum + index].nodeid = hgr->nodes[tid + N_ELEMID(hgr)];
                nodeList[0 * hgr->nodeNum + index].gain = getGains(hgr, tid);
                nodeList[0 * hgr->nodeNum + index].weight = hgr->nodes[tid + N_WEIGHT(hgr)];
            } else if (gain >= 0.0f) {
                int d   = gain * 10.0f;
                int idx = 10 - d;
                int index = atomicAdd(&bucketcnt[idx], 1);
                nodeList[idx * hgr->nodeNum + index].nodeid = hgr->nodes[tid + N_ELEMID(hgr)];
                nodeList[idx * hgr->nodeNum + index].gain = getGains(hgr, tid);
                nodeList[idx * hgr->nodeNum + index].weight = hgr->nodes[tid + N_WEIGHT(hgr)];
            } else if (gain > -9.0f) {
                int d   = gain * 10.0f - 1;
                int idx = 10 - d;
                int index = atomicAdd(&bucketcnt[idx], 1);
                nodeList[idx * hgr->nodeNum + index].nodeid = hgr->nodes[tid + N_ELEMID(hgr)];
                nodeList[idx * hgr->nodeNum + index].gain = getGains(hgr, tid);
                nodeList[idx * hgr->nodeNum + index].weight = hgr->nodes[tid + N_WEIGHT(hgr)];
            } else { // NODES with gain by weight ratio <= -9.0f are in one bucket
                int index = atomicAdd(&negCnt[0], 1);
                negGainlist[index].nodeid = hgr->nodes[tid + N_ELEMID(hgr)];
                negGainlist[index].gain = getGains(hgr, tid);
                negGainlist[index].weight = hgr->nodes[tid + N_WEIGHT(hgr)];
            }
        }
    }
}

__global__ void reComputeGainInBuckets(Hypergraph* hgr, tmpNode* nodeList, unsigned* bucketcnt, int total_count, int* move_flag) {
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidy = blockIdx.y * blockDim.y + threadIdx.y;
    if (tidy < bucketcnt[tidx]) {
        unsigned nodeid = nodeList[tidx * hgr->nodeNum + tidy].nodeid;
        for (int i = 0; i < hgr->nodes[N_DEGREE(hgr) + nodeid - hgr->hedgeNum]; ++i) {
            unsigned hedgeid = hgr->incident_nets[hgr->nodes[N_OFFSET(hgr) + nodeid - hgr->hedgeNum] + i];
            unsigned degree = hgr->hedges[E_DEGREE(hgr) + hedgeid];
            int p1 = 0;
            int p2 = 0;
            for (int j = 0; j < degree; ++j) {
                unsigned neigh = hgr->adj_list[hgr->hedges[hedgeid + E_OFFSET(hgr)] + j];
                if (neigh != nodeid) {
                    int part = hgr->nodes[neigh - hgr->hedgeNum + N_PARTITION(hgr)];
                    if (move_flag[neigh - hgr->hedgeNum] == 1) { // move from 0 to 1
                        part = 1;
                    }
                    part == 1 ? p1++ : p2++;
                }
            }
            if (p1 == degree - 1) {
                nodeList[tidx * hgr->nodeNum + tidy].real_gain++;
            } else if (p2 == degree - 1) {
                nodeList[tidx * hgr->nodeNum + tidy].real_gain--;
            }
        }
    }
}

