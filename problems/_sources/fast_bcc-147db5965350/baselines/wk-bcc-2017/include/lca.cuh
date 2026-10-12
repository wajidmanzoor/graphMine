#ifndef LCA_H
#define LCA_H

#include <vector>
#include <string>
#include <iostream>
#include <cuda_runtime.h>

#include "bcc_memory_utils.cuh"

void naive_lca(gpu_bcc& g_bcc_ds, int root, int child_of_root);

#endif // LCA_H