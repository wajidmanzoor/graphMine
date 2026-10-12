// gpu_bcc.h
#ifndef BCC_MEM_UTILS_H
#define BCC_MEM_UTILS_H

#include <cuda_runtime.h>

class gpu_bcc {
public:
    gpu_bcc(int vertices, long edges);
    ~gpu_bcc();

    void init(int numVert, long num_non_tree_edges);

    int numVert; 
    long numEdges;
    long E;  // Double the edge count (e,g. for edge (2,3), (3,2) is also counted)
    long num_non_tree_edges;  // Count of non-tree edges

    /* Pointers for dynamic memory */

    // input set of unique edges
    int *original_u, *original_v;

    // csr data-structures
    // offset array for csr
    long* d_vertices;
    // edges array
    int *d_edges;

    // Spanning tree data
    int *d_parent, *d_level;

    // BCC-related parameters
    int *d_isSafe, *d_isPartofFund, *d_cut_vertex;
    int *d_baseVertex;  // Every non - tree edge has an associated base vertex
    int* d_is_baseVertex; // My parent is lca or not
    long *d_nonTreeEdgeId;
    int* d_imp_bcc_num; // Final Output
    
    // Connected Components (CC) specific parameters
    int *d_baseU, *d_baseV, *d_rep, *d_flag;
};

#endif // BCC_MEM_UTILS_H
