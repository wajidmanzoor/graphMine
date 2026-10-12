#pragma once
#include "../../include/graph.h"
#include "../use_no_uvm.cuh"

__global__ void assignPriorityToNodeND(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, int nodeN, int hedgeN, int totalsize, int* ePrior, int* nPrior);

__global__ void assignHashHedgeIdToNodeND(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, int nodeN, int hedgeN, int totalsize, int* eRand, int* ePrior, int* nPrior, int* nRand);

__global__ void assignNodeToIncidentHedgeND(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, int nodeN, int hedgeN, int totalsize, int* eRand, int* nRand, int* nHedgeId);

__global__ void assignPriorityToNodeND1(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* ePrior, int* nPrior);

__global__ void assignHashHedgeIdToNodeND1(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* eRand, int* ePrior, int* nPrior, int* nRand);

__global__ void assignNodeToIncidentHedgeND1(int* hedges, int* nodes, unsigned* adj_list, int nodeN, int hedgeN, int* eRand, int* nRand, int* nHedgeId);

__global__ void mergeNodes(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, int LIMIT, int* newHedgeN, int* newNodeN, int iter, 
                                        int* eInBag, int* eMatch, int* nBag, int* accW, int* nMatch, int* candidates, int* nHedgeId, int* weights);