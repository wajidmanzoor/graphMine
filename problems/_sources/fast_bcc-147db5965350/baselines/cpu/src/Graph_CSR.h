#ifndef __GRAPH__
#define __GRAPH__

#include <iostream>
#include <fstream>
#include <vector>
#include <set>
#include <map>
#include <chrono>
#include <filesystem>
#include <stdexcept>
#include <cassert>

using namespace std;

class unweightedGraph {
	public:
    std::filesystem::path filepath;
    vector<vector<int>> adjlist;    // Adjacency list representation
    vector<long> offset;          // CSR format: offset array
    vector<int> neighbour;              // CSR format: neighbour array
    vector<int> src, dest;          // For storing neighbour
    int totalVertices = 0;
    long totalEdges = 0;
    chrono::duration<double> read_duration; // Time taken to read graph

    // Helper methods to read different formats
    void readGraphFile();
    void readEdgeList();
    void readECLgraph();
    void create_csr(const vector<vector<int>>& adjlist);

    // Constructor
    unweightedGraph(const std::string& filename);

    // Getters
    int getTotalVertices() const { return totalVertices; }
    long getTotalEdges() const { return totalEdges; }

    // Function to print adjacency list
    void printAdjList() const;

    // Function to print CSR representation
    void printCSR() const;
};

unweightedGraph::unweightedGraph(const std::string& filename) : filepath(filename) {
    try {
        auto start = chrono::high_resolution_clock::now();
        readGraphFile();
        auto end = chrono::high_resolution_clock::now();
        read_duration = end - start;
        cout << "Graph loaded in " << read_duration.count() << " seconds." << endl;
    }   
    catch (const runtime_error& e) {
        cerr << "Error: " << e.what() << endl;
        throw;
    }
}

void unweightedGraph::readGraphFile() {
    if (!filesystem::exists(filepath)) {
        throw runtime_error("File does not exist: " + filepath.string());
    }

    string ext = filepath.extension().string();
    if (ext == ".neighbour" || ext == ".eg2" || ext == ".txt") {
        readEdgeList();
    }
    else if (ext == ".egr" || ext == ".bin" || ext == ".csr") {
        readECLgraph();
    }
    else {
        throw runtime_error("Unsupported graph format: " + ext);
    }
}

void unweightedGraph::readEdgeList() {
    ifstream inFile(filepath);
    if (!inFile) {
        throw runtime_error("Error opening file: " + filepath.string());
    }

    inFile >> totalVertices >> totalEdges;

    adjlist.resize(totalVertices);
    src.resize(totalEdges / 2);
    dest.resize(totalEdges / 2);

    long ctr = 0;
    int u, v;
    for (long i = 0; i < totalEdges; ++i) {
        inFile >> u >> v;
        adjlist[u].push_back(v);
        if (u < v) {
            src[ctr] = u;
            dest[ctr] = v;
            ctr++;
        }
    }

    assert(ctr == totalEdges / 2);
    create_csr(adjlist);
}

void unweightedGraph::readECLgraph() {
    ifstream inFile(filepath, ios::binary);
    if (!inFile) {
        throw runtime_error("Error opening file: " + filepath.string());
    }

    // Reading sizes
    size_t size;
    inFile.read(reinterpret_cast<char*>(&size), sizeof(size));
    offset.resize(size);
    inFile.read(reinterpret_cast<char*>(&size), sizeof(size));
    neighbour.resize(size);

    // Reading data
    inFile.read(reinterpret_cast<char*>(offset.data()), offset.size() * sizeof(long));
    inFile.read(reinterpret_cast<char*>(neighbour.data()), neighbour.size() * sizeof(int));

    totalVertices = offset.size() - 1;
    totalEdges = neighbour.size();
}

void unweightedGraph::create_csr(const vector<vector<int>>& adjlist) {
    // CSR format: adjacency list is converted to CSR
    // CSR (Compressed Sparse Row) has two arrays: offset and neighbour
    offset.resize(totalVertices + 1);
    neighbour.clear();

    size_t edgeCount = 0;
    for (int i = 0; i < totalVertices; ++i) {
        offset[i] = edgeCount;
        for (int v : adjlist[i]) {
            neighbour.push_back(v);
            edgeCount++;
        }
    }
    offset[totalVertices] = edgeCount;
}

void unweightedGraph::printAdjList() const {
    for (int i = 0; i < totalVertices; ++i) {
        cout << i << ": ";
        for (int v : adjlist[i]) {
            cout << v << " ";
        }
        cout << endl;
    }
}

void unweightedGraph::printCSR() const {
    cout << "CSR format:" << endl;
    cout << "offset: ";
    for (long v : offset) {
        cout << v << " ";
    }
    cout << endl;

    cout << "neighbour: ";
    for (int e : neighbour) {
        cout << e << " ";
    }
    cout << endl;
}

#endif
