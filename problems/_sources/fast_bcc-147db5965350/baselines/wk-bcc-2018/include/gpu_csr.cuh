#ifndef GPU_CSH_H
#define GPU_CSH_H

int gpu_csr(uint64_t* d_edgelist, 
            long numEdges , 
            const int& numVert,
            long* d_vertices,
            int* d_edges,
            int* d_U,
            int* d_V);

#endif // GPU_CSH_H