#ifndef __TRICOUNT_H_
#define __TRICOUNT_H_
#include <cstdio>
#include <iostream>
#include <cstring>
#include "IndexType.h"
// #include "Graph.h"
using std::string;
template<typename T1, typename T2>
hash_type MyPow(T1 a, T2 b) {
  hash_type temp = 1;
  for (T2 i = 0; i < b; ++i) {
    temp *= a;
  }
  return temp;
}
// The final arguments let embedders provide update batches in memory and
// collect the original EDTC change counts without parsing stdout.  They are
// optional so the artifact's command-line entry point and file format remain
// source compatible.
void tricount(offset_type *offSet, edge_type *adjList, uint32_t gpu_id,
              offset_type batch_size, offset_type batch_num,
              string filepath_batch, edge_type node_num, offset_type edge_num,
              const char *update_types = nullptr,
              const edge_type *update_sources = nullptr,
              const edge_type *update_destinations = nullptr,
              unsigned long long *deleted_triangle_counts = nullptr,
              unsigned long long *inserted_triangle_counts = nullptr,
              float *delete_times_ms = nullptr,
              float *insert_times_ms = nullptr);

#endif
