#include <iostream>
#include <fstream>
#include <cstring>
#include <omp.h>
#include <cstdlib>
#include <algorithm>
#include <cstring>
#include "IndexType.h"
#include "tricount.h"
#include "common.h"

using std::cout;
using std::endl;

int main(int argc, char* argv[]) {
    std::string filepath_edge = std::string(argv[2]) + ".edge.bin";
    std::string filepath_offset = std::string(argv[2]) + ".offset.bin";
    uint32_t gpu_id = atoi(argv[5]);;
    std::ifstream file_edge(filepath_edge, std::ios::binary);
    file_edge.seekg(0, std::ios::end);
    size_t file_edge_size = file_edge.tellg();
    file_edge.seekg(0, std::ios::beg);
    edge_type edge_num = file_edge_size / sizeof(edge_type);

    edge_type *adjList;
    adjList = CPUAlloc(edge_type, edge_num);
    file_edge.read(reinterpret_cast<char *>(adjList), file_edge_size);
    file_edge.close();

    std::ifstream file_offset(filepath_offset, std::ios::binary);
    file_offset.seekg(0, std::ios::end);
    size_t file_offset_size = file_offset.tellg();
    file_offset.seekg(0, std::ios::beg);
    offset_type node_num = file_offset_size / sizeof(offset_type) - 1;
    offset_type *offSet;
    offSet = CPUAlloc(offset_type , (node_num + 1));
    file_offset.read(reinterpret_cast<char *>(&offSet[0]), file_offset_size);
    file_offset.close();
    std::string filepath_batch = std::string(argv[7]);
    offset_type batch_size = atoi(argv[3]);
    offset_type batch_number = atoi(argv[4]);
    // cout << "Now" << endl;
    tricount(offSet, adjList, gpu_id, batch_size, batch_number, filepath_batch, node_num, edge_num);
    return 0;
}