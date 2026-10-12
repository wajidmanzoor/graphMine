#ifndef EULER_HXX
#define EULER_HXX

#include "common.hxx"

float cuda_euler_tour(
    uint64_t* d_edges_input,
    int N, 
    int root,
    graph_data& d_input);

#endif // EULER_HXX