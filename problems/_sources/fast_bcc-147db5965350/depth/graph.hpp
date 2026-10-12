#ifndef GRAPH_H
#define GRAPH_H

#include <string>
#include <vector>
#include <fstream>
#include <iostream>
#include <filesystem>
#include <queue>

class undirected_graph {
public:
    int numVert;
    long numEdges;
    std::filesystem::path filepath;

    std::vector<int> u_arr;
    std::vector<int> v_arr;

    std::vector<long> vertices;
    std::vector<int> edges;

    int max_degree_vert = -1;
    double avg_out_degree = 0.0;
    
    undirected_graph(const std::string&);
    void create_csr(const std::vector<std::vector<int>>&);
    void readGraphFile();
    void readEdgeList();
    void readECLgraph();
    void csr_to_coo();
    
    // BFS function
    void bfs(int source);
};

#endif // GRAPH_H

