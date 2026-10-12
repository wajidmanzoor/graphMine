#ifndef BFS_H
#define BFS_H

#include <iostream>
#include <vector>
#include <cuda_runtime.h>
#include "cuda_utility.cuh"

void constructSpanningTree(int no_of_vertices, long numEdges, long* d_offset, int* d_neighbours, int* d_level, int* d_parent, int root, int& child_of_root);

#endif // BFS_H