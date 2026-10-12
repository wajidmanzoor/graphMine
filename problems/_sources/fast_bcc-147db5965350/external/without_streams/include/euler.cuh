#ifndef EULER_TOUR_CUH
#define EULER_TOUR_CUH

float cuda_euler_tour(
    int N, 
    int root, 
    uint64_t* d_edges_input,
    int* d_first_occ,
    int* d_last_occ,
    int* d_parent
);

#endif // EULER_TOUR_CUH