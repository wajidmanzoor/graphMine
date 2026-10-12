#pragma once
#include "../include/graph.h"

__host__ __device__ int hash(unsigned val);

__global__ void hedgePrioritySetting(Hypergraph* hgr, int hedgeN, unsigned matching_policy);

__global__ void multiNodeMatchingI(Hypergraph* hgr, int hedgeN);

__global__ void multiNodeMatchingII(Hypergraph* hgr, int hedgeN);

__global__ void multiNodeMatchingIII(Hypergraph* hgr, int hedgeN);

__global__ void createNodePhaseI(Hypergraph* hgr, int hedgeN, int LIMIT, Hypergraph* coarsen, int iter);

__global__ void ResetPrioForUpdateUnmatchNodes(Hypergraph* hgr, int hedgeN);

__global__ void coarseMoreNodes(Hypergraph* hgr, int hedgeN, int iter, int LIMIT);

__global__ void coarsenPhaseII(Hypergraph* hgr, int hedgeN, Hypergraph* coarsen);

__global__ void noedgeNodeMatching(Hypergraph* hgr, int nodeN, Hypergraph* coarsen);

__global__ void createNodeMapping(Hypergraph* hgr, int nodeN, Hypergraph* coarsen);

__global__ void updateSuperVertexId(Hypergraph* hgr, int nodeN);
