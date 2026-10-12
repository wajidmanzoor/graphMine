#pragma once
#include "../include/graph.h"

__host__ __device__ int getGains(Hypergraph* hgr, unsigned nodeid);

__global__ void projection(Hypergraph* coarsenHgr, Hypergraph* fineHgr);

__global__ void initGains(Hypergraph* hgr, int hedgeN);

struct tmpNode {
    unsigned nodeid;
    int gain;
    int weight;
    int real_gain;
    int tmp_FS;
    int tmp_TE;
    int move_direction;
};

__global__ void createNodeLists(Hypergraph* hgr, tmpNode* nodelistz, tmpNode* nodelistn, 
                                unsigned* zerow, unsigned* nonzerow);

__global__ void parallelSwapNodes(Hypergraph* hgr, tmpNode* nodelistz, tmpNode* nodelistn, 
                                unsigned* zerow, unsigned* nonzerow, unsigned workLen);

__global__ void placeNodesInBuckets(Hypergraph* hgr, tmpNode* nodeList, unsigned* bucketcnt, 
                                    tmpNode* negGainlist, unsigned* negCnt, unsigned partID);

__global__ void createNodeLists1(Hypergraph* hgr, tmpNode* nodelistz, tmpNode* nodelistn, unsigned* zerow, unsigned* nonzerow);

__global__ void reComputeGains(Hypergraph* hgr, int hedgeN, tmpNode* nodelistz, tmpNode* nodelistn, 
                                unsigned* zerow, unsigned* nonzerow, int* move_flag, unsigned nodeListLen);

__global__ void reComputeGainInBuckets(Hypergraph* hgr, tmpNode* nodeList, unsigned* bucketcnt, int total_count, int* move_flag);

__global__ void parallelMoveNodes(Hypergraph* hgr, tmpNode* nodelistz, tmpNode* nodelistn, unsigned workLen);

__global__ void parallelMoveNodes1(Hypergraph* hgr, tmpNode* nodelistz, tmpNode* nodelistn, unsigned posNum0, unsigned posNum1, unsigned posNum);

struct mycmp {
    __host__ __device__
    bool operator()(const tmpNode& node_a, const tmpNode& node_b) {
        if (node_a.gain == node_b.gain) {
            return node_a.nodeid < node_b.nodeid;
        }
        return node_a.gain > node_b.gain;
  }
};

struct mycmp1 {
    __host__ __device__
    bool operator()(const tmpNode& node_a, const tmpNode& node_b) {
        if (fabs((double)(node_a.real_gain * (1.0f / node_a.weight)) - (double)(node_b.real_gain * (1.0f / node_b.weight))) < 0.000001f) {
            return (float)node_a.nodeid < (float)node_b.nodeid;
        }
        return (double)(node_a.real_gain * (1.0f / node_a.weight)) > (double)(node_b.real_gain * (1.0f / node_b.weight));
  }
};

struct cmpGbyW {
    __host__ __device__
    bool operator()(const tmpNode& node_a, const tmpNode& node_b) {
        if (fabs((double)(node_a.gain * (1.0f / node_a.weight)) - (double)(node_b.gain * (1.0f / node_b.weight))) < 0.000001f) {
            return (float)node_a.nodeid < (float)node_b.nodeid;
        }
        return (double)(node_a.gain * (1.0f / node_a.weight)) > (double)(node_b.gain * (1.0f / node_b.weight));
  }
};

struct mycmp2 {
    __host__ __device__
    bool operator()(const tmpNode& node_a, const tmpNode& node_b) {
        if (node_a.weight == node_b.weight) {
            if (node_a.real_gain == node_b.real_gain) {
                return node_a.nodeid < node_b.nodeid;
            }
            return node_a.real_gain > node_b.real_gain;
        }
        return node_a.weight > node_b.weight;
  }
};

struct mycmp3 {
    __host__ __device__
    bool operator()(const tmpNode& node_a, const tmpNode& node_b) {
        if (node_a.gain == node_b.gain) {
            if (node_a.weight == node_b.weight) {
                return node_a.nodeid < node_b.nodeid;
            }
            return node_a.weight > node_b.weight;
        }
        return node_a.gain > node_b.gain;
  }
};
