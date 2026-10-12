#include "../coarsen_no_uvm_kernels.cuh"
#include "nondeterministic_coarsen_no_uvm_kernels.cuh"
#include <thrust/find.h>
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/unique.h>
#include <thrust/execution_policy.h>
#include <thrust/sort.h>

__global__ void assignPriorityToNodeND(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, int nodeN, int hedgeN, int totalsize, int* ePrior, int* nPrior) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        // int* nodePrior = &nodes[adj_list[tid] - hedgeN + N_PRIORITY1(nodeN)];
        // int* nodePrior = &nPrior[adj_list[tid] - hedgeN];
        // atomicMin(nodePrior, hedges[E_PRIORITY1(hedgeN) + hedge_id[tid]]);
        // atomicMin(nodePrior, ePrior[hedge_id[tid]]);
        nPrior[adj_list[tid] - hedgeN] = min(nPrior[adj_list[tid] - hedgeN], ePrior[hedge_id[tid]]);
    }
}

__global__ void assignHashHedgeIdToNodeND(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, int nodeN, int hedgeN, int totalsize, int* eRand, int* ePrior, int* nPrior, int* nRand) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        // int nodePrior = nodes[N_PRIORITY1(nodeN) + adj_list[tid] - hedgeN];
        int nodePrior = nPrior[adj_list[tid] - hedgeN];
        // if (nodePrior == hedges[E_PRIORITY1(hedgeN) + hedge_id[tid]]) {
        if (nodePrior == ePrior[hedge_id[tid]]) {
            // int* nodeRand = &nodes[adj_list[tid] - hedgeN + N_RAND1(nodeN)];
            // int* nodeRand = &nRand[adj_list[tid] - hedgeN];
            // atomicMin(nodeRand, hedges[E_RAND1(hedgeN) + hedge_id[tid]]);
            // atomicMin(nodeRand, eRand[hedge_id[tid]]);
            nRand[adj_list[tid] - hedgeN] = min(nRand[adj_list[tid] - hedgeN], eRand[hedge_id[tid]]);
        }
    }
}

__global__ void assignNodeToIncidentHedgeND(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, int nodeN, int hedgeN, int totalsize, int* eRand, int* nRand, int* nHedgeId) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < totalsize) {
        // int nodeRand = nodes[N_RAND1(nodeN) + adj_list[tid] - hedgeN];
        int nodeRand = nRand[adj_list[tid] - hedgeN];
        // if (nodeRand == hedges[E_RAND1(hedgeN) + hedge_id[tid]]) {
        if (nodeRand == eRand[hedge_id[tid]]) {
            // int* hedgeid = &nodes[adj_list[tid] - hedgeN + N_HEDGEID1(nodeN)];
            // int* hedgeid = &nHedgeId[adj_list[tid] - hedgeN];
            // atomicMin(hedgeid, hedges[E_IDNUM1(hedgeN) + hedge_id[tid]]);
            nHedgeId[adj_list[tid] - hedgeN] = min(nHedgeId[adj_list[tid] - hedgeN], hedges[E_IDNUM1(hedgeN) + hedge_id[tid]]);
        }
    }
}

__global__ void assignPriorityToNodeND1(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* ePrior, int* nPrior) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            int hedgePrior = ePrior[tid];
            int index = adj_list[hedges[E_OFFSET1(hedgeN) + tid] + i] - hedgeN;
            nPrior[index] = min(nPrior[index], hedgePrior);
        }
    }
}

__global__ void assignHashHedgeIdToNodeND1(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* eRand, int* ePrior, int* nPrior, int* nRand) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            int hedgePrior = ePrior[tid];
            int index = adj_list[hedges[E_OFFSET1(hedgeN) + tid] + i] - hedgeN;
            int nodePrior = nPrior[index];
            if (hedgePrior == nodePrior) {
                int idx = adj_list[hedges[E_OFFSET1(hedgeN) + tid] + i] - hedgeN;
                nRand[idx] = min(nRand[idx], eRand[tid]);
            }
        }
    }
}

__global__ void assignNodeToIncidentHedgeND1(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* eRand, int* nRand, int* nHedgeId) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hedgeN) {
        for (int i = 0; i < hedges[E_DEGREE1(hedgeN) + tid]; ++i) {
            int hedgeRand = eRand[tid];
            int index = adj_list[hedges[E_OFFSET1(hedgeN) + tid] + i] - hedgeN;
            int nodeRand = nRand[index];
            if (hedgeRand == nodeRand) {
                int idnum = hedges[E_IDNUM1(hedgeN) + tid];
                int idx = adj_list[hedges[E_OFFSET1(hedgeN) + tid] + i] - hedgeN;
                nHedgeId[idx] = min(nHedgeId[idx], hedges[E_IDNUM1(hedgeN) + tid]);
            }
        }
    }
}

__global__ void mergeNodes(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                        int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId, int* weights) {
    
}