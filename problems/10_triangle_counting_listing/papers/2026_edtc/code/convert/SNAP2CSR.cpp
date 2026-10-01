#include <iostream>
#include <fstream>
#include <string>
#include <list>
#include <algorithm>
#include <unordered_map>
#include <map>
#include <vector>
#include <omp.h>
#include<sstream>
#include "IndexType.h"
#include <cuda_runtime.h>
// #include <cub/cub.cuh> 
#include <vector>
using std::vector;
using std::string;
using std::istringstream;
using std::ifstream;
using std::ofstream;
using std::max;
const uint32_t uint32_t_INF = 0xFFFFFFFF;
const uint64_t uint64_t_INF = 0xFFFFFFFFFFFFFFFF;
struct Edge {
    edge_type source;
    edge_type destination;
    Edge(edge_type s, edge_type d) {
        source = s;
        destination = d;
    }
    Edge(){}
};        
bool cmp(Edge a, Edge b) {
    return a.source < b.source || (a.source == b.source && a.destination < b.destination);
}
vector<Edge> edges;
int main(int argc, char *argv[]) {
    string input_path = string(argv[2]) + ".snap";
    string output_offset_path = string(argv[2]) + ".offset.bin";
    string output_edge_path = string(argv[2]) + ".edge.bin";
    string output_meta_path = string(argv[2]) + ".meta.txt";
    string output_adj_path = string(argv[2]) + ".adj";
    ofstream output_adj_file(output_adj_path.data());
    std::cout << "sizeof(edge_type): " << sizeof(edge_type) << std::endl;
    std::cout << "sizeof(offset_type): " << sizeof(offset_type) << std::endl;
    ifstream input_file(input_path);
    string line;
    edge_type source, destination;
    edge_type max_node = 0;
    offset_type edge_num = 0;
    while(getline(input_file, line)) {
        if(line[0] == '#')
            continue;
        istringstream string_converter(line);
        string_converter >> source >> destination;
        edges.push_back(Edge(source, destination));
        edges.push_back(Edge(destination, source));
        max_node = max(max_node, max(source, destination));
        edge_num += 2;
    }
    std::cout << "Loading completed" << std::endl;
    bool *vis = (bool *)malloc(sizeof(bool) * (max_node + 1));
    #pragma omp parallel for
    for (edge_type i = 0; i < max_node + 1; ++i) {
        vis[i] = false;
    }

    // offset_type edge_num = edges.size();
    #pragma omp parallel for
    for (offset_type i = 0; i < edge_num; ++i) {
        vis[edges[i].source] = true;
        vis[edges[i].destination] = true;
    }
    edge_type node_num = 0;
    edge_type *map1 = (edge_type *)malloc(sizeof(edge_type) * (max_node + 1));
    for (edge_type i = 0; i < max_node + 1; ++i) {
        if(vis[i]) {
            map1[i] = node_num;
            node_num ++;
        }
    }
    #pragma omp parallel for
    for(offset_type i = 0; i < edge_num; ++i) {
        edge_type source = map1[edges[i].source];
        edge_type destination = map1[edges[i].destination];
        edges[i].source = source;
        edges[i].destination = destination;
    }
    std::cout << "Mapping completed" << std:: endl;
    std::sort(edges.begin(), edges.end(), cmp);
    offset_type edge_num_temp = edge_num;
    edge_num = 0;

    offset_type *degree = (offset_type *)malloc(sizeof(offset_type) * (node_num + 1));
    #pragma omp parallel for
    for (edge_type i = 0; i < node_num + 1; ++i)
        degree[i] = 0;

    iedge_type pre_source = -1, pre_destination = -1;
    for (offset_type i = 0; i < edge_num_temp; ++i) {
        edge_type source = edges[i]. source;
        edge_type destination = edges[i].destination;
        if(source == pre_source && destination == pre_destination || source == destination)
            continue;
        edges[edge_num].source = source;
        edges[edge_num].destination = destination;
        degree[source]++;
        pre_source = source;
        pre_destination = destination;
        edge_num++;
    }

    std::cout << "Duplicate edges removed" << std::endl;
    edge_type *adjList = (edge_type *)malloc(sizeof(edge_type) * edge_num);
    offset_type *offSet = (offset_type *)malloc(sizeof(offset_type) * (node_num + 1));
    // iedge_type pre_source = -1;
    pre_source = -1;
    // edge_type offSet_index = 0;
    offSet[0] = 0;

    for(edge_type i = 1; i < node_num + 1; ++i) {
        offSet[i] = offSet[i - 1] + degree[i - 1];
    }
    // #pragma omp parallel for
    // for (offset_type i = 0; i < edge_num; ++i) {
    //     adjList[i] = edges[i].destination;
    // }
    #pragma omp parallel for
    for(offset_type i = 0; i < node_num; ++i) {
        for(offset_type j = 0; j < degree[i]; ++j) {
            adjList[offSet[i] + j] = edges[offSet[i] + j].destination;
        }
    }

    std::cout << "CSR format has been generated" << std::endl;
    ofstream output_offset_file;
    ofstream output_edge_file;
    output_adj_file << "AdjacencyGraph" << std::endl;
    output_adj_file << node_num + 1 << std::endl;
    output_adj_file << edge_num << std::endl;
    for (edge_type i = 0; i < node_num + 1; ++i) {
        output_adj_file << offSet[i] << std::endl;
    }
    for(offset_type i = 0; i < edge_num; ++i) {
        output_adj_file << adjList[i] << std::endl;
    }
    output_adj_file.close();
    output_offset_file.open(output_offset_path.data(), std::ofstream::binary);
    output_edge_file.open(output_edge_path.data(), std::ofstream::binary);
    output_offset_file.write(reinterpret_cast<const char*>(offSet), sizeof(offset_type) * (node_num + 1));
    output_edge_file.write(reinterpret_cast<const char*>(adjList), sizeof(edge_type) * (edge_num));
    output_offset_file.close();
    output_edge_file.close();
    std::cout << "Writing completed" << std::endl;
    free(vis);
    free(map1);
    free(adjList);
    free(offSet);
    free(degree);
    return 0;

}