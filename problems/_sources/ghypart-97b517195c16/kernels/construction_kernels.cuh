#pragma once
#include "../include/graph.h"

__global__ void setParentEdgeList(Hypergraph* hgr, int N, Hypergraph* coarsenHgr);

__global__ void constructCoarserAdjList(Hypergraph* hgr, Hypergraph* coarsenHgr, unsigned N);

__global__ void constructIncidentNetLists(Hypergraph* coarsenHgr, int hedgeN);

__global__ void fillNextLevelAdjacentListWithoutDuplicates_nouvm(
                                        int* hedges, int* nodes, unsigned* adj_list, unsigned* isDuplica, 
                                        int hedgeN, int nodeN, int* newHedges, int* newNodes, unsigned* newAdjList, 
                                        int newNodeN, int newHedgeN, int* newTotalNodeDeg, 
                                        int* maxDegree, int* minDegree, int* newAdjListCounter);

__global__ void setCoarsenNodesProperties_nouvm(int* newNodes, int newNodeN, int newHedgeN, int* maxWeight, int* minWeight);

__global__ void markDuplicasInNextLevelAdjacentList1(Hypergraph* hgr, int hedgeN, int nodeN, Hypergraph* coarsenHgr, 
                                                    int newHedgeN, int bitLen, int num_hedges);

__global__ void markDuplicasInNextLevelAdjacentList2(Hypergraph* hgr, int hedgeN, int nodeN, Hypergraph* coarsenHgr, 
                                                    int newHedgeN, int bitLen, int num_hedges);

__global__ void markDuplicasInNextLevelAdjacentList3(Hypergraph* hgr, int hedgeN, int nodeN, Hypergraph* coarsenHgr, 
                                                    int newHedgeN, int bitLen, int num_hedges);

__global__ void markDuplicasInNextLevelAdjacentList4(Hypergraph* hgr, int hedgeN, int nodeN, Hypergraph* coarsenHgr, 
                                                    int newHedgeN, int bitLen, int num_hedges);

__global__ void constructCoarserAdjList1(Hypergraph* hgr, Hypergraph* coarsenHgr, unsigned N);

__global__ void setParentEdgeList1(Hypergraph* hgr, int N, Hypergraph* coarsenHgr);
