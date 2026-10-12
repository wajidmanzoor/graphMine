#ifndef VERTEX_MERGING_CUH
#define VERTEX_MERGING_CUH

#include <iostream>
#include "cuda_bcc/bcc_memory_utils.cuh"
#include "cuda_utility.cuh"

/**
 * Merges vertices in the biconnected component structure.
 * 
 * @param org_num_vert Original number of vertices in the graph
 * @param g_bcc_ds Reference to the GPU BCC data structure
 */
void vertex_merging(int org_num_vert, gpu_bcc& g_bcc_ds, uint64_t* d_edgelist, long org_num_edges);

#endif // VERTEX_MERGING_CUH
