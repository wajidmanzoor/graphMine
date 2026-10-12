#include "refinement_no_uvm_kernels.cuh"

__host__ __device__ int getMoveGain1(int* nodes, int nodeN, unsigned nodeid) {
    return nodes[nodeid + N_FS1(nodeN)] - (nodes[nodeid + N_TE1(nodeN)] + nodes[nodeid + N_COUNTER1(nodeN)]);
}

__global__ void collect_part_info1(int* nodes, int nodeN, int hedgeN, int totalsize, unsigned* adj_list, unsigned* hedge_id, int* p1_num, int* p2_num) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        int part = nodes[adj_list[tid] - hedgeN + N_PARTITION1(nodeN)];
        int hid = hedge_id[tid];
        part == 0 ? atomicAdd(&p1_num[hid], 1) : atomicAdd(&p2_num[hid], 1);
    }
}

__global__ void init_refine_boundary_nodes(int* nodes, unsigned* adj_list, int hedgeN, int nodeN, unsigned* hedge_id, int totalsize, int* p1_num, int* p2_num) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        int hid = hedge_id[tid];
        int p1 = p1_num[hid];
        int p2 = p2_num[hid];
        if (!(p1 > 1 && p2 > 1) && (p1 + p2 > 1)) {
            unsigned dst = adj_list[tid];
            int tmpnode = nodes[dst - hedgeN + N_PARTITION1(nodeN)] == 0 ? p1 : p2;
            if (tmpnode == 1) {
                atomicAdd(&nodes[dst - hedgeN + N_FS1(nodeN)], 1);
            } else if (tmpnode == p1 + p2) {
                atomicAdd(&nodes[dst - hedgeN + N_TE1(nodeN)], 1);
            }
        }
    }
}

__global__ void set_adj_nodes_part(int* nodes, int nodeN, int hedgeN, int totalsize, unsigned* adj_list, int* adj_part_list) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        adj_part_list[tid] = nodes[adj_list[tid] - hedgeN + N_PARTITION1(nodeN)];
    }
}

__global__ void collect_part_info2(int* nodes, int nodeN, int hedgeN, int totalsize, unsigned* adj_list, unsigned* hedge_id, int* p1_num, int* p2_num, int* adj_part_list) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        int part = adj_part_list[tid];
        int hid = hedge_id[tid];
        part == 0 ? atomicAdd(&p1_num[hid], 1) : atomicAdd(&p2_num[hid], 1);
    }
}

__global__ void init_refine_boundary_nodes1(int* nodes, unsigned* adj_list, int hedgeN, int nodeN, unsigned* hedge_id, int totalsize, int* p1_num, int* p2_num, int* adj_part_list) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        int hid = hedge_id[tid];
        int p1 = p1_num[hid];
        int p2 = p2_num[hid];
        if (!(p1 > 1 && p2 > 1) && (p1 + p2 > 1)) {
            unsigned dst = adj_list[tid];
            int tmpnode = adj_part_list[tid] == 0 ? p1 : p2;
            if (tmpnode == 1) {
                atomicAdd(&nodes[dst - hedgeN + N_FS1(nodeN)], 1);
            } else if (tmpnode == p1 + p2) {
                atomicAdd(&nodes[dst - hedgeN + N_TE1(nodeN)], 1);
            }
        }
    }
}

__global__ void createTwoNodeLists(int* nodes, int nodeN, tmpNode_nouvm* nodelistz, tmpNode_nouvm* nodelistn, unsigned* zerow, unsigned* nonzerow) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (nodes[tid + N_FS1(nodeN)] == 0 && nodes[tid + N_TE1(nodeN)] == 0) {
            return;
        }
        int gain = getMoveGain1(nodes, nodeN, tid);
        if (gain < 0) {
            return;
        }
        unsigned pp = nodes[tid + N_PARTITION1(nodeN)];
        if (pp == 0) {
            unsigned index = atomicAdd(&zerow[0], 1);
            nodelistz[index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
            nodelistz[index].gain = gain;
            nodelistz[index].weight = nodes[tid + N_WEIGHT1(nodeN)];
        } else {
            unsigned index = atomicAdd(&nonzerow[0], 1);
            nodelistn[index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
            nodelistn[index].gain = gain;
            nodelistn[index].weight = nodes[tid + N_WEIGHT1(nodeN)];
        }
    }
}

__global__ void createTwoNodeListsWithMarkingDirection(int* nodes, int nodeN, tmpNode_nouvm* nodelistz, 
                                                    tmpNode_nouvm* nodelistn, unsigned* zerow, unsigned* nonzerow) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (nodes[tid + N_FS1(nodeN)] == 0 && nodes[tid + N_TE1(nodeN)] == 0) {
            return;
        }
        int gain = getMoveGain1(nodes, nodeN, tid);
        if (gain < 0) {
            return;
        }
        unsigned pp = nodes[tid + N_PARTITION1(nodeN)];
        if (pp == 0) {
            unsigned index = atomicAdd(&zerow[0], 1);
            nodelistz[index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
            nodelistz[index].gain = gain;
            nodelistz[index].weight = nodes[tid + N_WEIGHT1(nodeN)];
            nodelistz[index].move_direction = 1;
        } else {
            unsigned index = atomicAdd(&nonzerow[0], 1);
            nodelistn[index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
            nodelistn[index].gain = gain;
            nodelistn[index].weight = nodes[tid + N_WEIGHT1(nodeN)];
            nodelistn[index].move_direction = -1;
        }
    }
}

__global__ void performNodeSwapInShorterLength(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodelistz, tmpNode_nouvm* nodelistn, 
                                                unsigned* zerow, unsigned* nonzerow, unsigned workLen) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < workLen) {
        int nodeid = tid % 2 == 0 ? nodelistn[tid / 2].nodeid : nodelistz[tid / 2].nodeid;
        nodes[nodeid - hedgeN + N_PARTITION1(nodeN)] == 0 ? nodes[nodeid - hedgeN + N_PARTITION1(nodeN)] = 1 : 
                                                            nodes[nodeid - hedgeN + N_PARTITION1(nodeN)] = 0;
        nodes[nodeid - hedgeN + N_COUNTER1(nodeN)]++;
    }
}

__global__ void countTotalNonzeroPartWeight(int* nodes, int nodeN, unsigned* nonzeroPartWeight) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (nodes[tid + N_PARTITION1(nodeN)] > 0) {
            atomicAdd(&nonzeroPartWeight[0], nodes[tid + N_WEIGHT1(nodeN)]);
        }
    }
}

__global__ void countTotalNonzeroPartWeightWithoutHeaviestNode(int* nodes, int nodeN, 
                                            unsigned* nonzeroPartWeight, int cur_idx, int maxWeight) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (nodes[tid + N_PARTITION1(nodeN)] > 0) {
            if (cur_idx) {
                if (nodes[tid + N_WEIGHT1(nodeN)] < maxWeight) {
                    atomicAdd(&nonzeroPartWeight[0], nodes[tid + N_WEIGHT1(nodeN)]);
                }
            } else {
                atomicAdd(&nonzeroPartWeight[0], nodes[tid + N_WEIGHT1(nodeN)]);
            }
        }
    }
}

__global__ void divideNodesIntoBuckets(int* nodes, int nodeN, tmpNode_nouvm* nodeList, unsigned* bucketcnt, 
                                        tmpNode_nouvm* negGainlist, unsigned* negCnt, unsigned partID) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        float gain = ((float)getMoveGain1(nodes, nodeN, tid)) / ((float)nodes[tid + N_WEIGHT1(nodeN)]);
        if (nodes[tid + N_PARTITION1(nodeN)] == partID) {
            if (gain >= 1.0f) { // nodes with gain >= 1.0f are in one bucket
                int index = atomicAdd(&bucketcnt[0], 1);
                nodeList[0 * nodeN + index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
                nodeList[0 * nodeN + index].gain = getMoveGain1(nodes, nodeN, tid);
                nodeList[0 * nodeN + index].weight = nodes[tid + N_WEIGHT1(nodeN)];
            } else if (gain >= 0.0f) {
                int d   = gain * 10.0f;
                int idx = 10 - d;
                int index = atomicAdd(&bucketcnt[idx], 1);
                nodeList[idx * nodeN + index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
                nodeList[idx * nodeN + index].gain = getMoveGain1(nodes, nodeN, tid);
                nodeList[idx * nodeN + index].weight = nodes[tid + N_WEIGHT1(nodeN)];
            } else if (gain > -9.0f) {
                int d   = gain * 10.0f - 1;
                int idx = 10 - d;
                int index = atomicAdd(&bucketcnt[idx], 1);
                nodeList[idx * nodeN + index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
                nodeList[idx * nodeN + index].gain = getMoveGain1(nodes, nodeN, tid);
                nodeList[idx * nodeN + index].weight = nodes[tid + N_WEIGHT1(nodeN)];
            } else { // NODES with gain by weight ratio <= -9.0f are in one bucket
                int index = atomicAdd(&negCnt[0], 1);
                negGainlist[index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
                negGainlist[index].gain = getMoveGain1(nodes, nodeN, tid);
                negGainlist[index].weight = nodes[tid + N_WEIGHT1(nodeN)];
            }
        }
    }
}

__global__ void computeBucketCounts(int* nodes, int nodeN, unsigned* bucketcnt, unsigned* partWeight, unsigned partID) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        float gain = ((float)getMoveGain1(nodes, nodeN, tid)) / ((float)nodes[tid + N_WEIGHT1(nodeN)]);
        if (nodes[tid + N_PARTITION1(nodeN)] == partID) {
            atomicAdd(&partWeight[0], 1);
            if (gain >= 1.f) {
                atomicAdd(&bucketcnt[0], 1);
            } else if (gain >= 0.0f) {
                int d   = gain * 10.0f;
                int idx = 10 - d;
                atomicAdd(&bucketcnt[idx], 1);
            } else if (gain > -9.0f) {
                int d   = gain * 10.0f - 1;
                int idx = 10 - d;
                atomicAdd(&bucketcnt[idx], 1);
            } else { // NODES with gain by weight ratio <= -9.0f are in one bucket
                atomicAdd(&bucketcnt[101], 1);
            }
        }
    }
}

__global__ void createSingleNodelist(int* nodes, int nodeN, tmpNode_nouvm* nodeList, unsigned* partWeight, unsigned partID) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (nodes[tid + N_PARTITION1(nodeN)] == partID) {
            // float gain = ((float)getMoveGain1(nodes, nodeN, tid)) / ((float)nodes[tid + N_WEIGHT1(nodeN)]);
            int index = atomicAdd(&partWeight[0], 1);
            nodeList[index].gain = getMoveGain1(nodes, nodeN, tid);
            nodeList[index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
            nodeList[index].weight = nodes[tid + N_WEIGHT1(nodeN)];
        }
    }
}

__global__ void placeNodesIntoSegments(int* nodes, int nodeN, tmpNode_nouvm* nodelist, 
                                        unsigned* bucketidx, unsigned* bucketoff, unsigned partID) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        float gain = ((float)getMoveGain1(nodes, nodeN, tid)) / ((float)nodes[tid + N_WEIGHT1(nodeN)]);
        if (nodes[tid + N_PARTITION1(nodeN)] == partID) {
            if (gain >= 1.0f) { // nodes with gain >= 1.0f are in one bucket
                int index = atomicAdd(&bucketidx[0], 1);
                nodelist[bucketoff[0] + index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
                nodelist[bucketoff[0] + index].gain = getMoveGain1(nodes, nodeN, tid);
                nodelist[bucketoff[0] + index].weight = nodes[tid + N_WEIGHT1(nodeN)];
            } else if (gain >= 0.0f) {
                int d   = gain * 10.0f;
                int idx = 10 - d;
                int index = atomicAdd(&bucketidx[idx], 1);
                nodelist[bucketoff[idx] + index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
                nodelist[bucketoff[idx] + index].gain = getMoveGain1(nodes, nodeN, tid);
                nodelist[bucketoff[idx] + index].weight = nodes[tid + N_WEIGHT1(nodeN)];
            } else if (gain > -9.0f) {
                int d   = gain * 10.0f - 1;
                int idx = 10 - d;
                int index = atomicAdd(&bucketidx[idx], 1);
                nodelist[bucketoff[idx] + index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
                nodelist[bucketoff[idx] + index].gain = getMoveGain1(nodes, nodeN, tid);
                nodelist[bucketoff[idx] + index].weight = nodes[tid + N_WEIGHT1(nodeN)];
            } else { // NODES with gain by weight ratio <= -9.0f are in one bucket
                int index = atomicAdd(&bucketidx[101], 1);
                nodelist[bucketoff[101] + index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
                nodelist[bucketoff[101] + index].gain = getMoveGain1(nodes, nodeN, tid);
                nodelist[bucketoff[101] + index].weight = nodes[tid + N_WEIGHT1(nodeN)];
            }
        }
    }
}

__global__ void performRebalanceMove(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodelist, unsigned* bucketcnt, 
                                    int* bal, int lo, int hi, unsigned* row, unsigned* processed, unsigned partID) {
    while (row[0] < 101) {
        if (bucketcnt[row[0]] == 0) {
            row[0]++;
            continue;
        }
        for (int k = 0; k < bucketcnt[row[0]]; ++k) {
            partID == 0 ? nodes[nodelist[row[0] * nodeN + k].nodeid - hedgeN + N_PARTITION1(nodeN)] = 1 : 
                          nodes[nodelist[row[0] * nodeN + k].nodeid - hedgeN + N_PARTITION1(nodeN)] = 0;
            partID == 0 ? bal[0] += nodes[nodelist[row[0] * nodeN + k].nodeid - hedgeN + N_WEIGHT1(nodeN)] : 
                          bal[0] -= nodes[nodelist[row[0] * nodeN + k].nodeid - hedgeN + N_WEIGHT1(nodeN)];
            bool expression = partID == 0 ? bal[0] >= lo : bal[0] <= hi;
            if (expression) {
                break;
            }
            processed[0]++;
            if (processed[0] > (int)sqrt((float)nodeN)) {
                break;
            }
        }
        bool expression = partID == 0 ? bal[0] >= lo : bal[0] <= hi;
        if (expression) {
            break;
        }
        if (processed[0] > (int)sqrt((float)nodeN)) {
            break;
        }
        row[0]++;
    }
}

__global__ void moveNegativeGainNodes(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodelist, unsigned* cnt, int* bal, int lo, int hi, unsigned* processed, unsigned partID) {
    for (int k = 0; k < cnt[0]; ++k) {
        partID == 0 ? nodes[nodelist[k].nodeid - hedgeN + N_PARTITION1(nodeN)] = 1 : 
                      nodes[nodelist[k].nodeid - hedgeN + N_PARTITION1(nodeN)] = 0;
        partID == 0 ? bal[0] += nodes[nodelist[k].nodeid - hedgeN + N_WEIGHT1(nodeN)] : 
                      bal[0] -= nodes[nodelist[k].nodeid - hedgeN + N_WEIGHT1(nodeN)];
        bool expression = partID == 0 ? bal[0] >= lo : bal[0] <= hi;
        if (expression) {
            break;
        }
        processed[0]++;
        if (processed[0] > (int)sqrt((float)nodeN)) {
            break;
        }
    }
}

__global__ void rebalanceMoveOnSingleNodeList(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodelist, 
                                            unsigned* cnt, int* bal, int lo, int hi, unsigned* processed, unsigned partID) {
    for (int k = 0; k < cnt[0]; ++k) {
        partID == 0 ? nodes[nodelist[k].nodeid - hedgeN + N_PARTITION1(nodeN)] = 1 : 
                      nodes[nodelist[k].nodeid - hedgeN + N_PARTITION1(nodeN)] = 0;
        partID == 0 ? bal[0] += nodes[nodelist[k].nodeid - hedgeN + N_WEIGHT1(nodeN)] : 
                      bal[0] -= nodes[nodelist[k].nodeid - hedgeN + N_WEIGHT1(nodeN)];
        bool expression = partID == 0 ? bal[0] >= lo : bal[0] <= hi;
        if (expression) {
            break;
        }
        processed[0]++;
        if (processed[0] > (int)sqrt((float)nodeN)) {
            break;
        }
    }
}

__global__ void performNodeSwapInShorterLengthWithoutHeaviestNode(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodelistz, tmpNode_nouvm* nodelistn, 
                                                unsigned* zerow, unsigned* nonzerow, unsigned workLen, int cur_idx, int maxWeight) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < workLen) {
        if (tid % 2 == 0) {
            if (nodelistn[tid / 2].weight < maxWeight) {
                int nodeid = nodelistn[tid / 2].nodeid;
                nodes[nodeid - hedgeN + N_PARTITION1(nodeN)] = 0;
                nodes[nodeid - hedgeN + N_COUNTER1(nodeN)]++;
            }
        } else {
            if (nodelistz[tid / 2].weight < maxWeight) {
                int nodeid = nodelistz[tid / 2].nodeid;
                nodes[nodeid - hedgeN + N_PARTITION1(nodeN)] = 1;
                nodes[nodeid - hedgeN + N_COUNTER1(nodeN)]++;
            }
        }
    }
}

__global__ void performMergingMovesWithoutHeaviestNode(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* mergelist, unsigned workLen, int cur_idx, int maxWeight) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < workLen) {
        if (cur_idx) {
            if (mergelist[tid].weight < maxWeight) {
                int nodeid = mergelist[tid].nodeid;
                mergelist[tid].move_direction == 1 ? nodes[nodeid - hedgeN + N_PARTITION1(nodeN)] = 1 : 
                                                    nodes[nodeid - hedgeN + N_PARTITION1(nodeN)] = 0;
                nodes[nodeid - hedgeN + N_COUNTER1(nodeN)]++;
            }
        } else {
            int nodeid = mergelist[tid].nodeid;
            mergelist[tid].move_direction == 1 ? nodes[nodeid - hedgeN + N_PARTITION1(nodeN)] = 1 : 
                                                nodes[nodeid - hedgeN + N_PARTITION1(nodeN)] = 0;
            // if (mergelist[tid].move_direction == 1) {
            //     nodes[nodeid - hedgeN + N_PARTITION1(nodeN)] = 1;
            // } else {
            //     nodes[nodeid - hedgeN + N_PARTITION1(nodeN)] = 0;
            // }
            nodes[nodeid - hedgeN + N_COUNTER1(nodeN)]++;
        }
        // printf("%d\n", workLen);
        // for (int i = 0; i < workLen; ++i) {
        //     if (mergelist[i].move_direction == 1) {
        //         nodes[N_PARTITION1(nodeN) + mergelist[i].nodeid - hedgeN] = 1;
        //     } else if (mergelist[i].move_direction == -1) {
        //         nodes[N_PARTITION1(nodeN) + mergelist[i].nodeid - hedgeN] = 0;
        //     }
        //     nodes[N_COUNTER1(nodeN) + mergelist[i].nodeid - hedgeN]++;
        // }
    }
}

__global__ void performMergingMoves(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* mergelist, unsigned workLen) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < workLen) {
        int nodeid = mergelist[tid].nodeid;
        mergelist[tid].move_direction == 1 ? nodes[nodeid - hedgeN + N_PARTITION1(nodeN)] = 1 : 
                                            nodes[nodeid - hedgeN + N_PARTITION1(nodeN)] = 0;
        nodes[nodeid - hedgeN + N_COUNTER1(nodeN)]++;
    }
}

__global__ void rebalanceMoveOnSingleNodeListWithoutHeaviestNode(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodelist, 
                                            unsigned* cnt, int* bal, int lo, int hi, unsigned* processed, unsigned partID, int cur_idx, int maxWeight) {
    for (int k = 0; k < cnt[0]; ++k) {
        if (cur_idx && nodelist[k].weight == maxWeight) {
            continue;
        }
        partID == 0 ? nodes[nodelist[k].nodeid - hedgeN + N_PARTITION1(nodeN)] = 1 : 
                      nodes[nodelist[k].nodeid - hedgeN + N_PARTITION1(nodeN)] = 0;
        partID == 0 ? bal[0] += nodes[nodelist[k].nodeid - hedgeN + N_WEIGHT1(nodeN)] : 
                      bal[0] -= nodes[nodelist[k].nodeid - hedgeN + N_WEIGHT1(nodeN)];
        bool expression = partID == 0 ? bal[0] >= lo : bal[0] <= hi;
        // printf("%d, weight:%d\n", nodelist[k].nodeid, nodes[nodelist[k].nodeid - hedgeN + N_WEIGHT1(nodeN)]);
        if (expression) {
            break;
        }
        processed[0]++;
        if (processed[0] > (int)sqrt((float)nodeN)) {
            break;
        }
    }
}

__global__ void init_move_gain_in_refine(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        int p1 = 0;
        int p2 = 0;
        for (int i = 0; i < hedges[tid + E_DEGREE1(hedgeN)]; ++i) {
            int part = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARTITION1(nodeN)];
            part == 0 ? p1++ : p2++;
            if (p1 > 1 && p2 > 1) {
                break;
            }
        }
        if (!(p1 > 1 && p2 > 1) && (p1 + p2 > 1)) {
            if (p1 == hedges[tid + E_DEGREE1(hedgeN)] || p2 == hedges[tid + E_DEGREE1(hedgeN)]) { // uncut, increment retain value
                for (int i = 0; i < hedges[tid + E_DEGREE1(hedgeN)]; ++i) {
                    unsigned int dst = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                    atomicAdd(&nodes[dst - hedgeN + N_GAIN1(nodeN)], -1);
                    atomicAdd(&nodes[dst - hedgeN + N_TE1(nodeN)], 1);
                }
            } else if (p1 == 1 || p2 == 1) {
                for (int i = 0; i < hedges[tid + E_DEGREE1(hedgeN)]; ++i) {
                    unsigned int dst = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                    int part = nodes[dst - hedgeN + N_PARTITION1(nodeN)];
                    if ((p1 == 1 && part == 0) || (p2 == 1 && part == 1)) {
                        atomicAdd(&nodes[dst - hedgeN + N_GAIN1(nodeN)], 1);
                        atomicAdd(&nodes[dst - hedgeN + N_FS1(nodeN)], 1);
                        break;
                    }
                }
            }
        }
    }
}

__global__ void createCandNodeListsWithSrcPartition(int* nodes, int nodeN, tmpNode_nouvm* nodelist, unsigned* candcount) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (nodes[tid + N_FS1(nodeN)] == 0 && nodes[tid + N_TE1(nodeN)] == 0) {
            return;
        }
        int gain = nodes[tid + N_GAIN1(nodeN)];
        if (gain < 0) {
            return;
        }
        unsigned pp = nodes[tid + N_PARTITION1(nodeN)];
        if (pp == 0) {
            unsigned index = atomicAdd(&candcount[0], 1);
            nodelist[index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
            nodelist[index].gain = gain;
            nodelist[index].weight = nodes[tid + N_WEIGHT1(nodeN)];
            nodelist[index].src_part = 0;
        } else {
            unsigned index = atomicAdd(&candcount[0], 1);
            nodelist[index].nodeid = nodes[tid + N_ELEMID1(nodeN)];
            nodelist[index].gain = gain;
            nodelist[index].weight = nodes[tid + N_WEIGHT1(nodeN)];
            nodelist[index].src_part = pp;
        }
    }
}

__global__ void parallelMoveCombinationGainComputation(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, tmpNode_nouvm* nodelist, int K, myPair* bestPair) {
    int tidx = blockIdx.x * blockDim.x + threadIdx.x;
    int tidy = blockIdx.y * blockDim.y + threadIdx.y;
    if (tidy < hedgeN) {
        int warpIdx = tidx >> 5; // each warp process one combination like 0b01000001
        int wid_per_blk = threadIdx.x >> 5; // warpId in block
        extern __shared__ int smem[];
        while (tidx < hedges[tidy + E_DEGREE1(hedgeN)]) {
            int part = nodes[adj_list[hedges[tidy + E_OFFSET1(hedgeN)] + tidx] - hedgeN + N_PARTITION1(nodeN)];
            if (smem[wid_per_blk * 2 + 0] > 1 && smem[wid_per_blk * 2 + 1] > 1) { // p1 > 1 and p2 > 1
                break;
            } else {
                part == 0 ? atomicAdd(&smem[wid_per_blk * 2 + 0], 1) : atomicAdd(&smem[wid_per_blk * 2 + 1], 1);
            }
            tidx += 32;
        }
        __syncwarp();
    }
}