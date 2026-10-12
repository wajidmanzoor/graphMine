#include "partitioning_kernels.cuh"

__global__ void initGain(Hypergraph* hgr, int hedgeN) {
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

__host__ __device__ int getGain(Hypergraph* hgr, unsigned nodeid) {
    return hgr->nodes[nodeid + N_FS(hgr)] - (hgr->nodes[nodeid + N_TE(hgr)] + hgr->nodes[nodeid + N_COUNTER(hgr)]);
}

__global__ void createNodeList(Hypergraph* hgr, tmpNode* nodeList, unsigned* count, unsigned partID) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < hgr->nodeNum) {
        if (hgr->nodes[tid + N_PARTITION(hgr)] == partID) {
            unsigned idx = atomicAdd(&count[0], 1);
            nodeList[idx].nodeid = hgr->nodes[tid + N_ELEMID(hgr)];
            nodeList[idx].gain = getGain(hgr, tid);
            nodeList[idx].weight = hgr->nodes[tid + N_WEIGHT(hgr)];
        }
    }
}

__global__ void reComputeGain(Hypergraph* hgr, tmpNode* nodeList, unsigned* count, int* move_flag) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < count[0]) {
        // nodeList[tid].real_gain = 0;
        unsigned nodeid = nodeList[tid].nodeid;
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
                    part == 0 ? p1++ : p2++;
                }
            }
            if (p2 == degree - 1) {
                nodeList[tid].real_gain++;
            } else if (p1 == degree - 1) {
                nodeList[tid].real_gain--;
            }
        }
    }
}

