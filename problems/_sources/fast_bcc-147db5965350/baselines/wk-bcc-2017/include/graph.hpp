#ifndef GRAPH_H
#define GRAPH_H

#include <string>
#include <vector>
#include <fstream>
#include <iostream>
#include <filesystem>

class undirected_graph {
public:
    int numVert;
    int max_degree_vert;
    double avg_out_degree;
    long numEdges;
    std::filesystem::path filepath;

    std::vector<int> u_arr;
    std::vector<int> v_arr;

    std::vector<long> vertices;
    std::vector<int> edges;
    
    undirected_graph(const std::string&);
    void create_csr(const std::vector<std::vector<int>>&);
    void readGraphFile();
    void readEdgeList();
    void readECLgraph();
    void csr_to_coo();
};

#endif // GRAPH_H

