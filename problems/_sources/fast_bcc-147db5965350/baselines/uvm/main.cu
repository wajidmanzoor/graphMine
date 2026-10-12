// In this version I'm optimizing the finding of the largest CC part
// To Compile: nvcc -O3 -arch=sm_80 -o main main.cu -std=c++17

#include <cstdio>
#include <cstdlib>
#include <algorithm>
#include <cstring> 
#include <cuda_runtime.h>

#include "common.hxx"
#include "graph.hxx"
#include "rst.hxx"
#include "tags.hxx"
#include "cc.hxx"

#define DEBUG

// -----------------------------------------------------------------------------
// Main function
// -----------------------------------------------------------------------------
int main(int argc, char const *argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <graph filename>" << std::endl;
        return EXIT_FAILURE;
    }
    
    std::string filename = argv[1];
    
    // Read (or create) a graph on the host.
    undirected_graph g(filename);
    graph_data d_input;

    int num_vert = g.getNumVertices();
    long num_edges = g.getNumEdges() / 2;

    d_input.V = num_vert;
    d_input.E = num_edges;

    std::cout << "Number of vertices: " << num_vert << "\n";
    std::cout << "Number of edges: " << num_edges << "\n";

    d_input.edgelist = g.getEdgelist();


    auto st_time = construct_st(d_input);
    auto tag_time = assign_tags(d_input);
    auto cc_time = CC(d_input);

    print_total_function_time("Fast-BCC (Original)");

    // int* label = new (std::nothrow) int[num_vert];
    // if (!label) {
    //     std::cerr << "Error: Failed to allocate host memory for label array" << std::endl;
    // } else {
    //     CUDA_CHECK(cudaDeviceSynchronize(), "Failed to sync before host read");
    //     std::memcpy(label, d_input.label, sizeof(int) * num_vert);

    //     int num_bcc = 0;
    //     for(int i = 0; i < num_vert; ++i) {
    //         if(label[i] == i)
    //             num_bcc++;
    //     }

    //     std::cout << "Number of BCC Labels: " << num_bcc << std::endl;
    //     delete[] label;
    // }
    
    return EXIT_SUCCESS;
}
