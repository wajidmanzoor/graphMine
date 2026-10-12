#pragma once
#include "../include/graph.h"
#include "use_no_uvm.cuh"

__global__ void swapPartition(int* nodes, int nodeN, int k);


__global__ void subHgrNodeCounting(int* nodes, int nodeN, int partID, int* nodeCnt);


__global__ void distributeHedgePartition(int* nodes, int* hedges, unsigned* adj_list, 
                                         int hedgeN, int nodeN, int partID, int* newHedgeN);


__global__ void subHgrEdgeListCounting(int* subNodes, int* subHedges, int* nodes, int* hedges, unsigned* adj_list, 
                                int hedgeN, int nodeN, int subHedgeN, int subNodeN, 
                                int* newTotalPinSize, int partID);


__global__ void subHgrAdjListConstruction(int* subHedges, int* hedges, int* nodes, 
                                unsigned* sub_adjlist, unsigned* adj_list,
                                int hedgeN, int nodeN, int subHedgeN, unsigned* pins_hedgeid_list, int partID);


__global__ void setSubHgrNodesProperties(int* subNodes, int subNodeN, int subHedgeN);


__global__ void updateSubHgrNodesPartition(int* nodes, int nodeN, int* subNodes, int subNodeN, int subHedgeN,
                                           int partID, int tmpID/*, int* count*/);


__global__ void swapPartition(int* nodes, int nodeN, int k, int part0weight, int part1weight) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        nodes[tid + N_PARTITION1(nodeN)] = part0weight < part1weight ? 
                                            1 - nodes[tid + N_PARTITION1(nodeN)] : nodes[tid + N_PARTITION1(nodeN)];
        if (nodes[tid + N_PARTITION1(nodeN)] == 1) {
            nodes[tid + N_PARTITION1(nodeN)] = (k + 1) / 2;
        }
    }
}


__global__ void subHgrNodeCounting(int* nodes, int nodeN, int partID, int* nodeCnt) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (nodes[tid + N_PARTITION1(nodeN)] == partID) {
            nodes[tid + N_ELEMID1(nodeN)] = 1;
            atomicAdd(nodeCnt, 1);
        }
    }
}


__global__ void distributeHedgePartition(int* nodes, int* hedges, unsigned* adj_list, 
                                         int hedgeN, int nodeN, int partID, int* newHedgeN) {
    // int tid = blockIdx.x * blockDim.x + threadIdx.x;
    int hid = blockIdx.x;
    __shared__ bool flag[1];
    flag[0] = true;
    __shared__ int parts[1];
    parts[0] = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)]] - hedgeN + N_PARTITION1(nodeN)];
    int tid = threadIdx.x;
    __syncthreads();

    while (tid < hedges[E_DEGREE1(hedgeN) + hid]) {
        int part = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_PARTITION1(nodeN)];
        if (part != parts[0]) {
            flag[0] = false;
            break;
        }
        tid += blockDim.x;
    }
    __syncthreads();

    if (threadIdx.x == 0) {
        if (flag[0]) {
            hedges[hid + E_PARTITION1(hedgeN)] = parts[0];
            if (parts[0] == partID) {
                hedges[hid + E_IDNUM1(hedgeN)] = 1;
                atomicAdd(&newHedgeN[0], 1);
            }
        } else {
            hedges[hid + E_PARTITION1(hedgeN)] = -1;
        }
    }
}


__global__ void subHgrEdgeListCounting(int* subHedges, int* hedges, unsigned* adj_list, 
                                        int hedgeN, int subHedgeN, int* newTotalPinSize, int partID) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        if (hedges[tid + E_PARTITION1(hedgeN)] == partID) {
            int newhid = hedges[tid + E_IDNUM1(hedgeN)];
            subHedges[newhid + E_IDNUM1(subHedgeN)] = newhid + 1;
            subHedges[newhid + E_DEGREE1(subHedgeN)] = hedges[tid + E_DEGREE1(hedgeN)];
            atomicAdd(&newTotalPinSize[0], hedges[tid + E_DEGREE1(hedgeN)]);
        }
    }
}


__global__ void subHgrAdjListConstruction(int* subHedges, int* hedges, int* nodes, 
                                          unsigned* sub_adjlist, unsigned* adj_list,
                                          int hedgeN, int nodeN, int subHedgeN, unsigned* pins_hedgeid_list, int partID) {
    int hid = blockIdx.x;

    if (hedges[hid + E_PARTITION1(hedgeN)] == partID) {
        int newhid = hedges[hid + E_IDNUM1(hedgeN)];// - 1;
        int tid = threadIdx.x;
        while (tid < hedges[hid + E_DEGREE1(hedgeN)]) {
            int nodeid = nodes[adj_list[hedges[hid + E_OFFSET1(hedgeN)] + tid] - hedgeN + N_ELEMID1(nodeN)];
            sub_adjlist[subHedges[newhid + E_OFFSET1(subHedgeN)] + tid] = nodeid;
            pins_hedgeid_list[subHedges[newhid + E_OFFSET1(subHedgeN)] + tid] = newhid;
            
            tid += blockDim.x;
        }
    }
}


__global__ void setSubHgrNodesProperties(int* subNodes, int subNodeN, int subHedgeN) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < subNodeN) {
        subNodes[tid + N_WEIGHT1(subNodeN)] = 1;
        subNodes[tid + N_ELEMID1(subNodeN)] = tid + subHedgeN;
    }
}

__global__ void updateSubHgrNodesPartition(int* nodes, int nodeN, int* subNodes, int subNodeN, int subHedgeN,
                                           int partID, int tmpID/*, int* count*/) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (nodes[tid + N_PARTITION1(nodeN)] == partID) {
            int index = nodes[tid + N_ELEMID1(nodeN)];
            int part = subNodes[index + N_PARTITION1(subNodeN) - subHedgeN];
            if (part == 0) {
                nodes[tid + N_PARTITION1(nodeN)] = partID;
                // atomicAdd(&count[0], 1);
            } else if (part == 1) {
                nodes[tid + N_PARTITION1(nodeN)] = partID + (tmpID + 1) / 2;
            }
        }
    }
}
