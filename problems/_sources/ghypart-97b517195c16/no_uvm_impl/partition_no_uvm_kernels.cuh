#pragma once
#include "../include/graph.h"
#include "use_no_uvm.cuh"

// __host__ __device__ int getMoveGain(int* nodes, int nodeN, unsigned nodeid);

__global__ void setupInitPartition(int* nodes, int nodeN, unsigned* part0Weight);

__global__ void setupInitPartition1(int* nodes, int nodeN, unsigned* part0Weight, int* hedges, int hedgeN, int totalsize, 
                                    unsigned* adj_list, unsigned* hedge_id, int* adj_part_list, int* p1_num, int* p2_num);



__global__ void createPotentialNodeList(int* nodes, int nodeN, tmpNode_nouvm* nodeList, unsigned* count, unsigned partID);


__global__ void performInitMove(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodeList, unsigned partID, unsigned* count,
                                int* gain, unsigned* processed, unsigned targetWeight, int totalWeight);

__global__ void setupInitPartitionWithoutHeaviestNode(int* nodes, int nodeN, unsigned* part0Weight, int maxWeight);

__global__ void performInitMoveWithoutHeaviestNode(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodeList, unsigned partID, unsigned* count,
                                int* gain, unsigned* processed, unsigned targetWeight, int totalWeight, int maxWeight);

// for ecology1.mtx, we use 0.00001f
// struct mycmp {
//     __host__ __device__
//     bool operator()(const tmpNode_nouvm& node_a, const tmpNode_nouvm& node_b) {
//         if (fabs((float)(node_a.gain * (1.0f / node_a.weight)) - (float)(node_b.gain * (1.0f / node_b.weight))) < 0.000001f) {
//             return node_a.nodeid < node_b.nodeid;
//         }
//         return (float)(node_a.gain * (1.0f / node_a.weight)) > (float)(node_b.gain * (1.0f / node_b.weight));
//   }
// };

// struct mycmp1 {
//     __host__ __device__
//     bool operator()(const tmpNode_nouvm& node_a, const tmpNode_nouvm& node_b) {
//         if (fabs((float)(node_a.gain * (1.0f / node_a.weight)) - (float)(node_b.gain * (1.0f / node_b.weight))) < 0.00001f) {
//             return node_a.nodeid < node_b.nodeid;
//         }
//         return (float)(node_a.gain * (1.0f / node_a.weight)) > (float)(node_b.gain * (1.0f / node_b.weight));
//   }
// };
