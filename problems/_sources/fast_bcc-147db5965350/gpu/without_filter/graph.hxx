#ifndef GRAPH_CXX
#define GRAPH_CXX

#include <fstream>
#include <iostream>
#include <vector>
#include <string>
#include <chrono>
#include <cassert>
#include <cuda_runtime.h>
#include <filesystem>

class undirected_graph {
private:
    std::filesystem::path filepath;
    std::vector<long> vertices;
    std::vector<int> edges;
    uint64_t* h_edgelist = nullptr;
    long numVert = 0;
    long numEdges = 0;
    std::chrono::duration<double> read_duration;

    void readGraphFile();
    void readEdgeList();
    void readECLgraph();
    void csr_to_coo();

public:
    undirected_graph(const std::string& filename);
    ~undirected_graph();
    void print_edgelist();
    void basic_stats(const long& maxThreadsPerBlock, const bool& g_verbose, const bool& checker);
    inline long getNumVertices() const { return numVert; }
    inline long getNumEdges() const { return numEdges; }
    inline uint64_t* getEdgelist() const { return h_edgelist; }
};

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
    else if (ext == ".egr" || ext == ".bin" || ext == ".csr") {
        readECLgraph();
    }
    else {
        throw std::runtime_error("Unsupported graph format: " + ext);
    }
}

void undirected_graph::readEdgeList() {
    std::ifstream inFile(filepath);
    if (!inFile) {
        throw std::runtime_error("Error opening file: " + filepath.string());
    }
    inFile >> numVert >> numEdges;

    size_t bytes = (numEdges / 2) * sizeof(uint64_t);
    CUDA_CHECK(cudaMallocHost((void**)&h_edgelist, bytes), "Failed to allocate pinned memory for edgelist");

    long ctr = 0;
    int u, v;
    for (long i = 0; i < numEdges; ++i) {
        inFile >> u >> v;
        if (u < v) {
            h_edgelist[ctr] = (static_cast<uint64_t>(u) << 32) | v;
            ctr++;
        }
    }
    assert(ctr == numEdges / 2);
}   

void undirected_graph::readECLgraph() {
    std::ifstream inFile(filepath, std::ios::binary);
    if (!inFile) {
        throw std::runtime_error("Error opening file: " + filepath.string());
    }

    size_t size;
    inFile.read(reinterpret_cast<char*>(&size), sizeof(size));
    vertices.resize(size);
    inFile.read(reinterpret_cast<char*>(&size), sizeof(size));
    edges.resize(size);

    inFile.read(reinterpret_cast<char*>(vertices.data()), vertices.size() * sizeof(long));
    inFile.read(reinterpret_cast<char*>(edges.data()), edges.size() * sizeof(int));

    numVert = vertices.size() - 1;
    numEdges = edges.size();

    csr_to_coo();
}

void undirected_graph::print_edgelist() {
    for (long i = 0; i < numEdges / 2; ++i) {
        uint64_t edge = h_edgelist[i];
        int u = edge >> 32;
        int v = edge & 0xFFFFFFFF;
        std::cout << "(" << u << ", " << v << ") \n";
    }
    std::cout << std::endl;
}

void undirected_graph::basic_stats(const long& maxThreadsPerBlock, const bool& g_verbose, const bool& checker) {
    const std::string border = "========================================";

    std::cout << border << "\n"
              << "       Graph Properties & Execution Settings Overview\n"
              << border << "\n\n"
              << "Graph reading and CSR creation completed in " << read_duration.count() << " seconds\n"
              << "|V|: " << getNumVertices() << "\n"
              << "|E|: " << getNumEdges() / 2 << "\n"
              << "maxThreadsPerBlock: " << maxThreadsPerBlock << "\n"
              << "Verbose Mode: "     << (g_verbose ? "✅" : "❌") << "\n"
              << "Checker Enabled: "  << (checker ? "✅" : "❌") << "\n"
              << border << "\n\n";
}

void undirected_graph::csr_to_coo() {
    size_t bytes = (numEdges / 2) * sizeof(uint64_t);
    CUDA_CHECK(cudaMallocHost((void**)&h_edgelist, bytes), "Failed to allocate pinned memory for edgelist");

    long ctr = 0;
    for (int i = 0; i < numVert; ++i) {
        for (long j = vertices[i]; j < vertices[i + 1]; ++j) {
            if (i < edges[j]) {
                h_edgelist[ctr] = (static_cast<uint64_t>(i) << 32) | edges[j];
                ctr++;
            }
        }
    }
    assert(ctr == numEdges / 2);
}

undirected_graph::~undirected_graph() {
    if (h_edgelist) CUDA_CHECK(cudaFreeHost(h_edgelist), "Failed to free pinned memory for h_edge_list");
    CUDA_CHECK(cudaDeviceReset(), "Failed to reset device");
}

#endif // GRAPH_CXX
