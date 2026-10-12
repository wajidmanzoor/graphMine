#ifndef CUT_VERTEX_H
#define CUT_VERTEX_H

#include <vector>
#include <string>
#include <iostream>
#include <cuda_runtime.h>

#include "bcc_memory_utils.cuh"

void assign_cut_vertex_BCC(const gpu_bcc& g_bcc_ds, int root, int child_of_root);

#endif // CUT_VERTEX_H