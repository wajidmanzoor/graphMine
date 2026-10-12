#pragma once
#include "../include/graph.h"
#include "use_no_uvm.cuh"

// struct tmpNode {
//     unsigned nodeid;
//     int gain;
//     int weight;
//     int real_gain;
//     int move_direction;
// };

__global__ void createTwoNodeLists(int* nodes, int nodeN, tmpNode_nouvm* nodelistz, tmpNode_nouvm* nodelistn, unsigned* zerow, unsigned* nonzerow);

__global__ void createTwoNodeListsWithMarkingDirection(int* nodes, int nodeN, tmpNode_nouvm* nodelistz, 
                                                    tmpNode_nouvm* nodelistn, unsigned* zerow, unsigned* nonzerow);

__global__ void performNodeSwapInShorterLength(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodelistz, tmpNode_nouvm* nodelistn, 
                                                unsigned* zerow, unsigned* nonzerow, unsigned workLen);

__global__ void countTotalNonzeroPartWeight(int* nodes, int nodeN, unsigned* nonzeroPartWeight);

__global__ void countTotalNonzeroPartWeightWithoutHeaviestNode(int* nodes, int nodeN, unsigned* nonzeroPartWeight, int cur_idx, int maxWeight);

__global__ void divideNodesIntoBuckets(int* nodes, int nodeN, tmpNode_nouvm* nodeList, unsigned* bucketcnt, 
                                        tmpNode_nouvm* negGainlist, unsigned* negCnt, unsigned partID);

__global__ void computeBucketCounts(int* nodes, int nodeN, unsigned* bucketcnt, unsigned* partWeight, unsigned partID);


__global__ void placeNodesIntoSegments(int* nodes, int nodeN, tmpNode_nouvm* nodelist, unsigned* bucketidx, unsigned* bucketoff, unsigned partID);

__global__ void performRebalanceMove(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodelist, unsigned* bucketcnt, 
                                    int* bal, int lo, int hi, unsigned* row, unsigned* processed, unsigned partID);

__global__ void moveNegativeGainNodes(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodelist,
                                    unsigned* cnt, int* bal, int lo, int hi, unsigned* processed, unsigned partID);


__global__ void rebalanceMoveOnSingleNodeList(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodelist, 
                                            unsigned* cnt, int* bal, int lo, int hi, unsigned* processed, unsigned partID);

__global__ void rebalanceMoveOnSingleNodeListWithoutHeaviestNode(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodelist, 
                                            unsigned* cnt, int* bal, int lo, int hi, unsigned* processed, unsigned partID, int cur_idx, int maxWeight);

__global__ void performNodeSwapInShorterLengthWithoutHeaviestNode(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* nodelistz, tmpNode_nouvm* nodelistn, 
                                                unsigned* zerow, unsigned* nonzerow, unsigned workLen, int cur_idx, int maxWeight);

__global__ void performMergingMovesWithoutHeaviestNode(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* mergelist, unsigned workLen, int cur_idx, int maxWeight);

__global__ void performMergingMoves(int* nodes, int nodeN, int hedgeN, tmpNode_nouvm* mergelist, unsigned workLen);

__global__ void createSingleNodelist(int* nodes, int nodeN, tmpNode_nouvm* nodeList, unsigned* partWeight, unsigned partID);

__global__ void createCandNodeListsWithSrcPartition(int* nodes, int nodeN, tmpNode_nouvm* nodelist, unsigned* candcount);

// struct mycmp {
//     __host__ __device__
//     bool operator()(const tmpNode& node_a, const tmpNode& node_b) {
//         if (node_a.gain == node_b.gain) {
//             return node_a.nodeid < node_b.nodeid;
//         }
//         return node_a.gain > node_b.gain;
//   }
// };

// struct cmpGbyW {
//     __host__ __device__
//     bool operator()(const tmpNode& node_a, const tmpNode& node_b) {
//         if (fabs((double)(node_a.gain * (1.0f / node_a.weight)) - (double)(node_b.gain * (1.0f / node_b.weight))) < 0.000001f) {
//             return (float)node_a.nodeid < (float)node_b.nodeid;
//         }
//         return (double)(node_a.gain * (1.0f / node_a.weight)) > (double)(node_b.gain * (1.0f / node_b.weight));
//   }
// };
