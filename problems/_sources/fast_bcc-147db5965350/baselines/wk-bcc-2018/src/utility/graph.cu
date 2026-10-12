#include <fstream>
#include <cassert>
#include <cuda_runtime.h>

#include "graph.cuh"
#include "cuda_utility.cuh"

undirected_graph::undirected_graph(const std::string& filename) : filepath(filename) {
    try {
        auto start = std::chrono::high_resolution_clock::now();
        readGraphFile();
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
    // std::cout << "Reading edges file: " << getFilename() << std::endl;
    std::ifstream inFile(filepath);
    if (!inFile) {
        throw std::runtime_error("Error opening file: ");
    }
    inFile >> numVert >> numEdges;

    // Allocate host pinned memories
    
    edgelist.resize(numEdges);

    long ctr = 0;
    std::vector<std::vector<int>> adjlist(numVert);
    int u, v;
    for(long i = 0; i < numEdges; ++i) {
        inFile >> u >> v;
        adjlist[u].push_back(v);
    }

    for(int i = 0; i < numVert; ++i) {
        for(size_t j = 0; j < adjlist[i].size(); ++j) {
            int dest = adjlist[i][j];
            edgelist[ctr++] = (long)i << 32  | ( (long)dest & 0xffffffffL );
        }
    }

    assert(ctr == numEdges);
    create_csr(adjlist);
}

void undirected_graph::readECLgraph() {
    // std::cout << "Reading ECL file: " << getFilename() << std::endl;

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

void undirected_graph::print_CSR() {
    for (int i = 0; i < numVert; ++i) {
        std::cout << "Vertex " << i << " is connected to: ";
        for (int j = vertices[i]; j < vertices[i + 1]; ++j) {
            std::cout << edges[j] << " ";
        }
        std::cout << "\n";
    }
}

void undirected_graph::print_edgelist() {
    for(int i = 0; i < numEdges; ++i) {
        uint64_t edge = edgelist[i];
        int u = edge >> 32;
        int v = edge & 0xffffffffL;
        std::cout << "(" << u << ", " << v << ") \n";
    }
    std::cout << std::endl;
}

void undirected_graph::create_csr(const std::vector<std::vector<int>>& adjlist) {
    vertices.push_back(edges.size());
    for (int i = 0; i < numVert; i++) {
        edges.insert(edges.end(), adjlist[i].begin(), adjlist[i].end());
        vertices.push_back(edges.size());
    }
}

void undirected_graph::csr_to_coo() {
    edgelist.resize(numEdges);
    long ctr = 0;

    for (int i = 0; i < numVert; ++i) {
        for (long j = vertices[i]; j < vertices[i + 1]; ++j) {    
            int src  = i;
            int dest = edges[j];
            edgelist[ctr++] = (long)src << 32  | ( (long)dest & 0xffffffffL );
        }
    }    

    assert(ctr == numEdges);
}

undirected_graph::~undirected_graph() {
}