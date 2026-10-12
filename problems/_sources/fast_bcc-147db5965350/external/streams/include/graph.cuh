#ifndef GRAPH_H
#define GRAPH_H

#include <vector>
#include <string>
#include <iostream>
#include <stdexcept>
#include <filesystem>
#include <functional>
#include <iterator>
#include <numeric>
#include <limits>

#include "../parlay/sequence.h"

class undirected_graph {
public:

    undirected_graph(const std::string&);
    ~undirected_graph();

    void print_edgelist();
    void basic_stats(const long&, const bool&, const bool&);
    
    // Getter for numVert
    int getNumVertices() const {
        return numVert;
    }
    // Getter for numEdges
    long getNumEdges() const {
        return numEdges;
    }

    // Getter for src
    const uint64_t* getList() const {
        return h_edgelist;
    }


    
    std::string getFilename() const {
        return filepath.filename().string();
    }

    std::string getFullPath() const {
        return filepath.string();
    }

    uint64_t* h_edgelist;

    parlay::sequence<uint64_t> edges64;
    

private:
    int numVert;
    long numEdges;
    std::filesystem::path filepath;

    // read timer
    std::chrono::duration<double, std::milli> read_duration;

    // instead you have myTimer T1, T2.

    // csr representation
    std::vector<long> vertices;
    std::vector<int>  edges;

    // Timer myTimer;
    void readGraphFile();
    void readEdgeList();
    void readMTXgraph();
    void readMETISgraph();
    void readECLgraph();
    void csr_to_coo();
};

#endif // GRAPH_H
