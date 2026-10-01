#include <iostream>
#include <fstream>
#include <string>
#include <list>
#include <algorithm>
#include <unordered_map>
#include <map>
#include <vector>
#include <omp.h>
#include <sstream>
#include "IndexType.h"

#include <time.h>


#include <cstdlib>
using std::string;
using std::istringstream;
using std::ifstream;
using std::ofstream;
using std::cout;
using std::endl;
struct Edge {
    edge_type source, destination;
};
int main(int argc, char *argv[]) {
    std::string filepath_edge = std::string(argv[2]) + ".edge.bin";
    std::string filepath_offset = std::string(argv[2]) + ".offset.bin";
    std::string filepath_adj = std::string(argv[2]) + ".adj";
    std::string filepath_snap = std::string(argv[2]) + ".snap";

    std::ifstream file_edge(filepath_edge, std::ios::binary);
    file_edge.seekg(0, std::ios::end);
    size_t file_edge_size = file_edge.tellg();
    file_edge.seekg(0, std::ios::beg);
    offset_type edge_num = file_edge_size / sizeof(edge_type); 
    edge_type *adjList = (edge_type *)aligned_alloc(4096, sizeof(edge_type) * edge_num);
    file_edge.read(reinterpret_cast<char*>(adjList), file_edge_size);
    file_edge.close();

    std::ifstream file_offset(filepath_offset, std::ios::binary);
    file_offset.seekg(0, std::ios::end);
    size_t file_offset_size = file_offset.tellg();
    file_offset.seekg(0, std::ios::beg);
    edge_type node_num = file_offset_size / sizeof(offset_type) - 1;
    offset_type *offSet = (offset_type *)aligned_alloc(4096, sizeof(offset_type) * (node_num + 1));
    file_offset.read(reinterpret_cast<char*>(offSet), file_offset_size);
    file_offset.close();
    ofstream output_adj_file(filepath_adj.data());
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
    ofstream output_snap_file(filepath_snap.data());
    edge_type source, destination;
    for (edge_type i = 0; i < node_num; ++i) {
        for (offset_type j = offSet[i]; j < offSet[i + 1]; ++j) {
            // source = i;
            // destination = adjList[j];
            // output_snap_file << source << " " << destination << std:: endl;
            output_snap_file << i << " " << adjList[j] << std::endl;
        }
    }
    output_snap_file.close();
    return 0;
}