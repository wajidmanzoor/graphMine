#include <fstream>
#include <cassert>
#include <omp.h>
#include <random>
#include <cuda_runtime.h>

#include "include/graph.cuh"
#include "include/cuda_utility.cuh"
#include "parlay/sequence.h"


extern float GPU_share;

undirected_graph::undirected_graph(const std::string& filename) : filepath(filename) {
    try {
        auto start = std::chrono::high_resolution_clock::now();
        readGraphFile();
        auto end = std::chrono::high_resolution_clock::now();
        read_duration = end - start;
    }   
    catch (const std::runtime_error& e) {
            std::cerr << "Error: " << e.what() << std::endl;
            throw;
    }
}

void undirected_graph::readGraphFile() {
    if (!std::filesystem::exists(filepath)) {
        throw std::runtime_error("File does not exist: " + filepath.string());
    }

    std::string ext = filepath.extension().string();
    if (ext == ".edges" || ext == ".eg2" || ext == ".txt") {
        readEdgeList();
    }
    else if (ext == ".egr" || ext == ".bin" || ".csr") {
        readECLgraph();
    }
    else {
        throw std::runtime_error("Unsupported graph format: " + ext);
    }
}

void undirected_graph::readEdgeList() {
    std::ifstream inFile(filepath);
    if (!inFile) {
        throw std::runtime_error("Error opening file: ");
    }
    inFile >> numVert >> numEdges;

    printf("GPU_share: %f\n", GPU_share);

    int is_one  = (int)GPU_share;


    long num_edges_for_gpu = (long)(GPU_share * (numEdges/2));
    size_t bytes = num_edges_for_gpu * sizeof(uint64_t);
    long num_edges_for_cpu = (numEdges/2) - num_edges_for_gpu;

    if(is_one == 1){
        num_edges_for_gpu = numEdges/2;
        num_edges_for_cpu = 0;
        bytes = num_edges_for_gpu * sizeof(uint64_t);
    }

    CUDA_CHECK(cudaMallocHost((void**)&h_edgelist, bytes),  "Failed to allocate pinned memory for edgelist");
    edges64.resize(num_edges_for_cpu);

    long ctr = 0;
    int u, v;
    for(long i = 0; i < numEdges; ++i) {
        inFile >> u >> v;
        if(u < v){
            if(ctr < num_edges_for_gpu){
            h_edgelist[ctr] = (static_cast<uint64_t>(u) << 32) | (v);
            ctr++;
            }
            else{
                edges64[ctr - num_edges_for_gpu] = (static_cast<uint64_t>(u) << 32) | (v);
                ctr++;
            }
        }
    }
    assert(ctr == numEdges/2);

    numEdges = ctr;
}   

void undirected_graph::readECLgraph() {
    std::ifstream inFile(filepath, std::ios::binary);
    if (!inFile) {
        throw std::runtime_error("Error opening file: ");
    }

    // Reading sizes
    size_t size;
    inFile.read(reinterpret_cast<char*>(&size), sizeof(size));
    vertices.resize(size);
    inFile.read(reinterpret_cast<char*>(&size), sizeof(size));
    edges.resize(size);

    // Reading data
    inFile.read(reinterpret_cast<char*>(vertices.data()), vertices.size() * sizeof(long));
    inFile.read(reinterpret_cast<char*>(edges.data()), edges.size() * sizeof(int));

    numVert = vertices.size() - 1;
    numEdges = edges.size();

    csr_to_coo();
}

void undirected_graph::print_edgelist() {
    for(long i = 0; i < numEdges/2; ++i) {
        uint64_t edge = h_edgelist[i];
        int u = edge >> 32;          // Extract the upper 32 bits
        int v = edge & 0xFFFFFFFF;   // Extract the lower 32 bits
        std::cout << "(" << u << ", " << v << ") \n";
    }
    std::cout << std::endl;
}

void undirected_graph::basic_stats(const long& maxThreadsPerBlock, const bool& g_verbose, const bool& checker) {
    
    // const std::string border = "========================================";

    // std::cout << border << "\n"
    // << "       Graph Properties & Execution Settings Overview\n"
    // << border << "\n\n"
    // << "Graph reading and CSR creation completed in " << formatDuration(read_duration.count()) << "\n"
    // << "|V|: " << getNumVertices() << "\n"
    // << "|E|: " << getNumEdges() / 2 << "\n"
    // << "maxThreadsPerBlock: " << maxThreadsPerBlock << "\n"
    // << "Verbose Mode: "     << (g_verbose ? "✅" : "❌") << "\n"
    // << "Checker Enabled: "  << (checker ?   "✅" : "❌") << "\n"
    // << border << "\n\n";
}

void undirected_graph::csr_to_coo() {

    long num_edges_for_gpu = (long)(GPU_share * (numEdges/2));
    size_t bytes = num_edges_for_gpu * sizeof(uint64_t);
    long num_edges_for_cpu = (numEdges/2) - num_edges_for_gpu;

    int isone = (int)GPU_share;
    if(isone == 1){
        num_edges_for_gpu = numEdges/2;
        num_edges_for_cpu = 0;
        bytes = num_edges_for_gpu * sizeof(uint64_t);
    }

    CUDA_CHECK(cudaMallocHost((void**)&h_edgelist,  bytes),  "Failed to allocate pinned memory for edgelist");
    
    if(num_edges_for_cpu > 0)
    edges64.resize(num_edges_for_cpu);



    long ctr = 0;
    for (int i = 0; i < numVert; ++i) {
        for (long j = vertices[i]; j < vertices[i + 1]; ++j) {
            if(i < edges[j]) {
                int u  = i;
                int v = edges[j];
                if(ctr < num_edges_for_gpu){
                    h_edgelist[ctr] = (static_cast<uint64_t>(u) << 32) | (v);
                    ctr++;
                }
                else{
                    if(num_edges_for_cpu > 0){
                    edges64[ctr - num_edges_for_gpu] = (static_cast<uint64_t>(u) << 32) | (v);
                    ctr++;
                    }
                }
            }
        }
    }    

    assert(ctr == numEdges/2);
    numEdges = ctr;

    //free vertices and edges
    vertices.clear();
    edges.clear();
}

undirected_graph::~undirected_graph() {
    // free host pinned memories
    // if(h_edgelist) CUDA_CHECK(cudaFreeHost(h_edgelist), "Failed to free pinned memory for h_edge_list");

    // CUDA_CHECK(cudaDeviceReset(), "Failed to reset device");
}