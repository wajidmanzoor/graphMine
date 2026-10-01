#pragma once
#include "common.cuh"
#include "graph.h"
#define LEVEL_2
#define EXPAND_R

#ifndef WARP_PER_BLOCK
  #define WARP_PER_BLOCK 5
#endif
#ifndef BLOCK_PER_SM
  #define BLOCK_PER_SM 4 // 2
#endif
#define WARP_PER_SM (BLOCK_PER_SM * WARP_PER_BLOCK)

class MceGpuSolver
{
public:
  MceGpuSolver(Graph &g, int device_id = 0); 
  void Solve();
  acc_t mce_count_;

private:
  int device_id_;
  Timer timer_;
  Graph &g_;
};


void GmceMultiGpuSolve(Graph &g, std::vector<int> device_ids);