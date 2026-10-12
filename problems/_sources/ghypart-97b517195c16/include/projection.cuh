#pragma once
#include "graph.h"

void projectPartition(Hypergraph* coarsenHgr, Hypergraph* fineHgr, float& time, float& cur, int cur_iter);

__global__ void projection(Hypergraph* coarsenHgr, Hypergraph* fineHgr);

