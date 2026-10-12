#include "coarsen_no_uvm_kernels.cuh"

__global__ void transform_edge_mapping_list_to_csr_format(int hedgeN, int newHedgeN, int* eInBag, int* eNext, int* eCsrOff, int* eCsrCol, float* eCsrVal) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        if (tid < hedgeN - 1) {
            if (eNext[tid] < eNext[tid+1]) {
            // if (eInBag[tid]) {
                eCsrCol[eNext[tid]] = tid;
                eCsrVal[eNext[tid]] = 1;
                eCsrOff[eNext[tid]] = eNext[tid];
            }
        } else {
            if (eNext[tid] > eNext[tid-1]) {
            // if (eInBag[tid] && !eInBag[tid-1]) {
                eCsrCol[eNext[tid]] = tid;
                eCsrVal[eNext[tid]] = 1;
                eCsrOff[eNext[tid]] = eNext[tid];
            }
            eCsrOff[newHedgeN] = newHedgeN;
        }
    }
}

__global__ void transform_node_mapping_list_to_csr_format(int newHedgeN, int* nodes, int nodeN, int* nCsrOff, int* nCsrCol, float* nCsrVal) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        nCsrOff[tid] = tid;
        nCsrCol[tid] = nodes[tid + N_PARENT1(nodeN)] - newHedgeN;
        nCsrVal[tid] = 1;
        if (tid == nodeN - 1) {
            nCsrOff[nodeN] = nodeN;
        }
    }
}

__global__ void transform_adjlist_to_csr_format(unsigned* adjlist, int hedgeN, int totalsize, int* adjCsrCol, float* adjCsrVal) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        adjCsrCol[tid] = adjlist[tid] - hedgeN;
        adjCsrVal[tid] = 1;
    }
}

__global__ void compute_new_adjlist_with_duplicate(int* eCsrOff, int* eCsrCol, int* eCsrVal, int* adjCsrOff, int* adjCsrCol, int* adjCsrVal,
                                                int hedgeN, int newHedgeN, int nodeN,
                                                int* tmpCsrOff, int* tmpCsrCol, int* tmpCsrVal) {
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidy = blockIdx.y * blockDim.y + threadIdx.y;
    if (tidx < nodeN && tidy < newHedgeN) {

    }
}

__global__ void computeAxB(int* matA, int* matB, int* matTmp, int hedgeN, int newHedgeN, int nodeN) {
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidy = blockIdx.y * blockDim.y + threadIdx.y;
    if (tidx < nodeN && tidy < newHedgeN) {
        int res = 0;
        for (int i = 0; i < hedgeN; ++i) {
            res += matA[tidy * hedgeN + i] * matB[i * nodeN + tidx];
        }
        matTmp[tidy * nodeN + tidx] = res;
    }
}

__global__ void multiNodeMatching_new(int* hedges, unsigned* adj_list, int hedgeN, int* ePrior, int* nPrior, 
                                    int* hedge_off_per_thread, int total_thread_num) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < total_thread_num) {
        if (tid == 0) {
            for (int i = 0; i <= hedge_off_per_thread[tid]; ++i) {
                for (int j = 0; j < hedges[E_DEGREE1(hedgeN) + i]; ++j) {
                    int hedgePrior = ePrior[i];
                    int index = adj_list[hedges[E_OFFSET1(hedgeN) + i] + j] - hedgeN;
                    int* nodePrior = &nPrior[index];
                    atomicMin(nodePrior, hedgePrior);
                }
            }
        } else {
            for (int i = hedge_off_per_thread[tid-1]+1; i <= hedge_off_per_thread[tid]; ++i) {
                for (int j = 0; j < hedges[E_DEGREE1(hedgeN) + i]; ++j) {
                    int hedgePrior = ePrior[i];
                    int index = adj_list[hedges[E_OFFSET1(hedgeN) + i] + j] - hedgeN;
                    int* nodePrior = &nPrior[index];
                    atomicMin(nodePrior, hedgePrior);
                }
            }
        }
    }
}

__global__ void fillNextLevelAdjacentList_new(int* hedges, int* nodes, unsigned* adj_list, unsigned* par_list, int hedgeN, int nodeN,
                                            int* newHedges, int* newNodes, unsigned* newAdjList, unsigned* pinsHedgeidList, int* next_id, int* eInBag,
                                            int newNodeN, int newHedgeN, unsigned N, int* newTotalNodeDeg, 
                                            int* maxDegree, int* minDegree, int* maxWeight, int* minWeight,
                                            int* hedge_off_per_thread, int total_thread_num) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < total_thread_num) {
        if (tid == 0) {
            for (int i = 0; i <= hedge_off_per_thread[tid]; ++i) {
                if (eInBag[i]) {
                    unsigned h_id = next_id[i];
                    newHedges[E_IDNUM1(newHedgeN) + h_id] = hedges[E_IDNUM1(hedgeN) + i];
                    int id = h_id;
                    int count = 0;
                    for (unsigned j = 0; j < hedges[i + E_DEGREE1(hedgeN)]; ++j) {
                        if (par_list[hedges[i + E_OFFSET1(hedgeN)] + j] == 1) {
                            unsigned pid = nodes[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN + N_PARENT1(nodeN)];
                            newAdjList[newHedges[E_OFFSET1(newHedgeN) + id] + count] = pid;
                            pinsHedgeidList[newHedges[E_OFFSET1(newHedgeN) + id] + count] = id; // add here!
                            count++;
                            atomicAdd(&newNodes[N_DEGREE1(newNodeN) + (pid - newHedgeN)], 1);
                            atomicAdd(&newTotalNodeDeg[0], 1);
                        }
                    }
                    atomicMin(&minDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                    atomicMax(&maxDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                }
            }
        } else {
            for (int i = hedge_off_per_thread[tid-1]+1; i <= hedge_off_per_thread[tid]; ++i) {
                if (eInBag[i]) {
                    unsigned h_id = next_id[i];
                    newHedges[E_IDNUM1(newHedgeN) + h_id] = hedges[E_IDNUM1(hedgeN) + i];
                    int id = h_id;
                    int count = 0;
                    for (unsigned j = 0; j < hedges[i + E_DEGREE1(hedgeN)]; ++j) {
                        if (par_list[hedges[i + E_OFFSET1(hedgeN)] + j] == 1) {
                            unsigned pid = nodes[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN + N_PARENT1(nodeN)];
                            newAdjList[newHedges[E_OFFSET1(newHedgeN) + id] + count] = pid;
                            pinsHedgeidList[newHedges[E_OFFSET1(newHedgeN) + id] + count] = id; // add here!
                            count++;
                            atomicAdd(&newNodes[N_DEGREE1(newNodeN) + (pid - newHedgeN)], 1);
                            atomicAdd(&newTotalNodeDeg[0], 1);
                        }
                    }
                    atomicMin(&minDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                    atomicMax(&maxDegree[0], newHedges[E_DEGREE1(newHedgeN) + id]);
                }
            }
        }
    }
}

__global__ void mergeNodesInsideHyperedges_new(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN,
                                            int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                            int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId, 
                                            int* hedge_off_per_thread, int total_thread_num) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < total_thread_num) {
        if (tid == 0) {
            for (int i = 0; i <= hedge_off_per_thread[tid]; ++i) {
                bool flag = false;
                unsigned nodeid = INT_MAX;
                int count = 0;
                int w = 0;
                for (int j = 0; j < hedges[E_DEGREE1(hedgeN) + i]; ++j) {
                    int isMatched = nMatch[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN];
                    if (isMatched) { // return old value
                        flag = true;
                        continue;
                    }
                    unsigned int idnum = hedges[i + E_IDNUM1(hedgeN)];
                    int hedgeid = nHedgeId[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN];
                    unsigned int dst = adj_list[hedges[i + E_OFFSET1(hedgeN)] + j];
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
                    eMatch[i] = 1;
                    if (flag) {
                        eInBag[i] = 1;
                        atomicAdd(&newHedgeN[0], 1);
                    }
                    nBag[nodeid - hedgeN] = 1;
                    atomicAdd(&newNodeN[0], 1);
                    for (int j = 0; j < hedges[E_DEGREE1(hedgeN) + i]; ++j) {
                        unsigned int idnum = hedges[i + E_IDNUM1(hedgeN)];
                        int hedgeid = nHedgeId[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN];
                        int candidate = candidates[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN];
                        if (candidate && idnum == hedgeid) {
                            nMatch[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN] = 1;
                            nodes[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN + N_PARENT1(nodeN)] = nodeid;
                            int tmpW = nodes[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN + N_WEIGHT1(nodeN)];
                            atomicAdd(&accW[nodeid - hedgeN], tmpW);
                        }
                    }
                }
            }
        } else {
            for (int i = hedge_off_per_thread[tid-1]+1; i <= hedge_off_per_thread[tid]; ++i) {
                bool flag = false;
                unsigned nodeid = INT_MAX;
                int count = 0;
                int w = 0;
                for (int j = 0; j < hedges[E_DEGREE1(hedgeN) + i]; ++j) {
                    int isMatched = nMatch[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN];
                    if (isMatched) { // return old value
                        flag = true;
                        continue;
                    }
                    unsigned int idnum = hedges[i + E_IDNUM1(hedgeN)];
                    int hedgeid = nHedgeId[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN];
                    unsigned int dst = adj_list[hedges[i + E_OFFSET1(hedgeN)] + j];
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
                    eMatch[i] = 1;
                    if (flag) {
                        eInBag[i] = 1;
                        atomicAdd(&newHedgeN[0], 1);
                    }
                    nBag[nodeid - hedgeN] = 1;
                    atomicAdd(&newNodeN[0], 1);
                    for (int j = 0; j < hedges[E_DEGREE1(hedgeN) + i]; ++j) {
                        unsigned int idnum = hedges[i + E_IDNUM1(hedgeN)];
                        int hedgeid = nHedgeId[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN];
                        int candidate = candidates[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN];
                        if (candidate && idnum == hedgeid) {
                            nMatch[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN] = 1;
                            nodes[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN + N_PARENT1(nodeN)] = nodeid;
                            int tmpW = nodes[adj_list[hedges[i + E_OFFSET1(hedgeN)] + j] - hedgeN + N_WEIGHT1(nodeN)];
                            atomicAdd(&accW[nodeid - hedgeN], tmpW);
                        }
                    }
                }
            }
        }
    }
}