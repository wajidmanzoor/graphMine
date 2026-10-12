#pragma once
#include "../include/graph.h"

__host__ __device__ int getGain(Hypergraph* hgr, unsigned nodeid);

struct tmpNode {
    unsigned nodeid;
    int gain;
    int weight;
    int real_gain;
};

__global__ void initGain(Hypergraph* hgr, int hedgeN);

__global__ void createNodeList(Hypergraph* hgr, tmpNode* nodeList, unsigned* count, unsigned partID);

__global__ void reComputeGain(Hypergraph* hgr, tmpNode* nodeList, unsigned* count, int* move_flag);

__global__ void createNodeList(Hypergraph* hgr, tmpNode* nodeList, unsigned* count, unsigned partID);

__global__ void reComputeGain(Hypergraph* hgr, tmpNode* nodeList, unsigned* count, int* move_flag);

// for ecology1.mtx, we use 0.00001f
struct mycmp {
    __host__ __device__
    bool operator()(const tmpNode& node_a, const tmpNode& node_b) {
        if (fabs((float)(node_a.gain * (1.0f / node_a.weight)) - (float)(node_b.gain * (1.0f / node_b.weight))) < 0.000001f) {
            return node_a.nodeid < node_b.nodeid;
        }
        return (float)(node_a.gain * (1.0f / node_a.weight)) > (float)(node_b.gain * (1.0f / node_b.weight));
  }
};

struct mycmp1 {
    __host__ __device__
    bool operator()(const tmpNode& node_a, const tmpNode& node_b) {
        if (fabs((float)(node_a.gain * (1.0f / node_a.weight)) - (float)(node_b.gain * (1.0f / node_b.weight))) < 0.00001f) {
            return node_a.nodeid < node_b.nodeid;
        }
        return (float)(node_a.gain * (1.0f / node_a.weight)) > (float)(node_b.gain * (1.0f / node_b.weight));
  }
};

struct mycmp2 {
    __host__ __device__
    bool operator()(const tmpNode& node_a, const tmpNode& node_b) {
        if (fabs((float)(node_a.real_gain * (1.0f / node_a.weight)) - (float)(node_b.real_gain * (1.0f / node_b.weight))) < 0.000001f) {
            return node_a.nodeid < node_b.nodeid;
        }
        return (float)(node_a.real_gain * (1.0f / node_a.weight)) > (float)(node_b.real_gain * (1.0f / node_b.weight));
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

struct sortweight {
    __host__ __device__
    bool operator()(const tmpNode& node_a, const tmpNode& node_b) {
        if (node_a.weight == node_b.weight) {
            return node_a.nodeid < node_b.nodeid;
        }
        return node_a.weight > node_b.weight;
  }
};

