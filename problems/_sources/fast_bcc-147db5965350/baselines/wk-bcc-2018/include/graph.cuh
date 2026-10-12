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
#include <chrono>

class undirected_graph {
public:
    undirected_graph(const std::string&);
    ~undirected_graph();

    void print_CSR();
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

    // Getter for the vectors
    const std::vector<long>& getVertices() const {
        return vertices;
    }
    // Getter for the edges
    const std::vector<int>& getEdges() const {
        return edges;
    }

    // Getter for edgelist
    const std::vector<uint64_t>& getEdgeList() const {
        return edgelist;
    }
    
    std::string getFilename() const {
        return filepath.filename().string();
    }

    std::string getFullPath() const {
        return filepath.string();
    }

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

    // edge-list
    std::vector<uint64_t> edgelist;

    void readGraphFile();
    void readEdgeList();
    void readECLgraph();
    void csr_to_coo();

    void create_csr(const std::vector<std::vector<int>>&);
};

#endif // GRAPH_H
