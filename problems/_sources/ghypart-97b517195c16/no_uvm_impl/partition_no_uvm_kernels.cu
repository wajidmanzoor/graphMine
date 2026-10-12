#include "partition_no_uvm_kernels.cuh"

__host__ __device__ int getMoveGain(int* nodes, int nodeN, unsigned nodeid) {
    return nodes[nodeid + N_FS1(nodeN)] - (nodes[nodeid + N_TE1(nodeN)] + nodes[nodeid + N_COUNTER1(nodeN)]);
}

__global__ void setupInitPartition(int* nodes, int nodeN, unsigned* part0Weight) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (nodes[tid + N_DEGREE1(nodeN)] == 0) {
            nodes[tid + N_PARTITION1(nodeN)] = 1;
        } else {
            nodes[tid + N_PARTITION1(nodeN)] = 0;
            atomicAdd(&part0Weight[0], nodes[tid + N_WEIGHT1(nodeN)]);
        }
    }
}

__global__ void setupInitPartition1(int* nodes, int nodeN, unsigned* part0Weight, int* hedges, int hedgeN, int totalsize, 
                                    unsigned* adj_list, unsigned* hedge_id, int* adj_part_list, int* p1_num, int* p2_num) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN + totalsize) {
        if (tid < totalsize) {
            adj_part_list[tid] = 0;
            int hid = hedge_id[tid];
            // if (hid == 0) {
            //     printf("@@here!! %d %d\n", tid, adj_list[hid + E_OFFSET1(hedgeN)]);
            // }
            if (tid == hedges[hid + E_OFFSET1(hedgeN)]) {
                p1_num[hid] = hedges[hid + E_DEGREE1(hedgeN)];
                // if (hid == 0) {
                //     printf("here!! %d\n", tid);
                // }
            }
        } else {
            if (nodes[tid - totalsize + N_DEGREE1(nodeN)] == 0) {
                nodes[tid - totalsize + N_PARTITION1(nodeN)] = 1;
            } else {
                nodes[tid - totalsize + N_PARTITION1(nodeN)] = 0;
                atomicAdd(&part0Weight[0], nodes[tid - totalsize + N_WEIGHT1(nodeN)]);
            }
        }
    }
}

__global__ void init_move_gain(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN) {
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
        // if (p1 + p2 > 1) {
            for (int i = 0; i < hedges[tid + E_DEGREE1(hedgeN)]; ++i) {
                unsigned int dst = adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i];
                int part = nodes[dst - hedgeN + N_PARTITION1(nodeN)];
                int tmpnode = part == 0 ? p1 : p2;
                if (tmpnode == 1) {
                    atomicAdd(&nodes[dst - hedgeN + N_FS1(nodeN)], 1);
                } else if (tmpnode == p1 + p2) {
                    atomicAdd(&nodes[dst - hedgeN + N_TE1(nodeN)], 1);
                }
            }
        }
    }
}

__global__ void init_move_gain1(int* nodes, unsigned* adj_list, int hedgeN, int nodeN, unsigned* hedge_id, int* adj_part_list, int totalsize, int* p1_num, int* p2_num, int* hedges) {
    // int tid = blockIdx.x * blockDim.x + threadIdx.x;
    // if (tid < totalsize) {
    //     int hid = hedge_id[tid];
    //     int p1 = p1_num[hid];
    //     int p2 = p2_num[hid];
    //     if (!(p1 > 1 && p2 > 1) && (p1 + p2 > 1)) {
    //         int tmpnode = adj_part_list[tid] == 0 ? p1 : p2;
    //         unsigned dst = adj_list[tid];
    //         if (tmpnode == 1) {
    //             atomicAdd(&nodes[dst - hedgeN + N_FS1(nodeN)], 1);
    //         } else if (tmpnode == p1 + p2) {
    //             atomicAdd(&nodes[dst - hedgeN + N_TE1(nodeN)], 1);
    //         }
    //     }
    // }
    int bid = blockIdx.x;
    if (bid < hedgeN) {
        __shared__ int parts[2];
        __shared__ bool jump[1];
        // int p1 = 0;
        // int p2 = 0;
        parts[0] = 0, parts[1] = 0;
        jump[0] = false;
        int tid = threadIdx.x;
        int deg = hedges[tid + E_DEGREE1(hedgeN)];
        // for (int i = 0; i < hedges[tid + E_DEGREE1(hedgeN)]; ++i) {
        while (tid < deg) {
            if (jump[0]) {
                break;
            }
            // int part = nodes[adj_list[hedges[tid + E_OFFSET1(hedgeN)] + i] - hedgeN + N_PARTITION1(nodeN)];
            // part == 0 ? p1++ : p2++;
            int part = nodes[adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARTITION1(nodeN)];
            part == 0 ? atomicAdd(&parts[0], 1) : atomicAdd(&parts[1], 1);
            if (parts[0] > 1 && parts[1] > 1) {
                jump[0] = true;
                break;
            }
            tid += blockDim.x;
        }
        __syncthreads();
        tid = threadIdx.x;
        // if (!(p1 > 1 && p2 > 1) && (p1 + p2 > 1)) {
        if (!(parts[0] > 1 && parts[1] > 1) && (parts[0] + parts[1] > 1)) {
            // for (int i = 0; i < hedges[tid + E_DEGREE1(hedgeN)]; ++i) {
            while (tid < deg) {
                unsigned int dst = adj_list[hedges[bid + E_OFFSET1(hedgeN)] + tid];
                int part = nodes[dst - hedgeN + N_PARTITION1(nodeN)];
                int tmpnode = part == 0 ? parts[0] : parts[1];
                if (tmpnode == 1) {
                    atomicAdd(&nodes[dst - hedgeN + N_FS1(nodeN)], 1);
                } else if (tmpnode == parts[0] + parts[1]) {
                    atomicAdd(&nodes[dst - hedgeN + N_TE1(nodeN)], 1);
                }
                tid += blockDim.x;
            }
        }
    }
}

__global__ void collect_part_info(int* nodes, int nodeN, int hedgeN, int totalsize, unsigned* adj_list, unsigned* hedge_id, int* adj_part_list, int* p1_num, int* p2_num) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        adj_part_list[tid] = nodes[adj_list[tid] - hedgeN + N_PARTITION1(nodeN)];
        int hid = hedge_id[tid];
        adj_part_list[tid] == 0 ? atomicAdd(&p1_num[hid], 1) : atomicAdd(&p2_num[hid], 1);
    }
}


__global__ void createPotentialNodeList(int* nodes, int nodeN, tmpNode_nouvm* nodeList, unsigned* count, unsigned partID) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (nodes[tid + N_PARTITION1(nodeN)] == partID) {
            unsigned idx = atomicAdd(&count[0], 1);
            nodeList[idx].nodeid = nodes[tid + N_ELEMID1(nodeN)];
            nodeList[idx].gain = getMoveGain(nodes, nodeN, tid);
            nodeList[idx].weight = nodes[tid + N_WEIGHT1(nodeN)];
        }
    }
    // while (tid < nodeN) {
    //     if (nodes[tid + N_PARTITION1(nodeN)] == partID) {
    //         unsigned idx = atomicAdd(&count[0], 1);
    //         nodeList[idx].nodeid = nodes[tid + N_ELEMID1(nodeN)];
    //         nodeList[idx].gain = getMoveGain(nodes, nodeN, tid);
    //         nodeList[idx].weight = nodes[tid + N_WEIGHT1(nodeN)];
    //     }
    //     tid += blockDim.x * gridDim.x;
    // }
}

__global__ void performInitMove(int* nodes, int hedgeN, int nodeN, tmpNode_nouvm* nodeList, unsigned partID, unsigned* count,
                                int* gain, unsigned* processed, unsigned targetWeight, int totalWeight) {
    for (; processed[0] < count[0]; ) {
        nodes[nodeList[processed[0]].nodeid - hedgeN + N_PARTITION1(nodeN)] = partID == 0 ? 1 : 0;
        gain[0] += nodes[nodeList[processed[0]].nodeid - hedgeN + N_WEIGHT1(nodeN)];
        processed[0]++;
        if (gain[0] >= static_cast<long>(targetWeight)) {
            break;
        }
        if (processed[0] > (unsigned)sqrt((float)totalWeight)) {
            break;
        }
    }
}

__global__ void setupInitPartitionWithoutHeaviestNode(int* nodes, int nodeN, unsigned* part0Weight, int maxWeight) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (nodes[tid + N_DEGREE1(nodeN)] == 0) {
            nodes[tid + N_PARTITION1(nodeN)] = 1;
        } else {
            nodes[tid + N_PARTITION1(nodeN)] = 0;
            if (nodes[tid + N_WEIGHT1(nodeN)] < maxWeight) {
                atomicAdd(&part0Weight[0], nodes[tid + N_WEIGHT1(nodeN)]);
            }
        }
    }
}

__global__ void performInitMoveWithoutHeaviestNode(int* nodes, int hedgeN, int nodeN, tmpNode_nouvm* nodeList, unsigned partID, unsigned* count,
                                int* gain, unsigned* processed, unsigned targetWeight, int totalWeight, int maxWeight) {
    for (; processed[0] < count[0]; ) {
        if (nodeList[processed[0]].weight == maxWeight) {
            processed[0]++;
            continue;
        }
        nodes[nodeList[processed[0]].nodeid - hedgeN + N_PARTITION1(nodeN)] = partID == 0 ? 1 : 0;
        gain[0] += nodes[nodeList[processed[0]].nodeid - hedgeN + N_WEIGHT1(nodeN)];
        processed[0]++;
        if (gain[0] >= static_cast<long>(targetWeight)) {
            break;
        }
        if (processed[0] > (unsigned)sqrt((float)totalWeight)) {
            break;
        }
    }
}
