#ifndef __EDGE_H__
#define __EDGE_H__
#include "IndexType.h"
#include <cuda_runtime.h>
#include "common.h"
#include <malloc.h>
#include <stdlib.h>
#include <cstdio>
#include <stdexcept>
struct Edge {
    edge_type source, destination;
    __device__ inline void setEdge(edge_type s, edge_type d) {
        source = s;
        destination = d;
    }
    __host__ __device__
    bool operator<(const Edge& other) const {
        if(source != other.source)
            return source < other.source;
        else {
            return destination < other.destination;
        }
    }
};
struct UpdateEdge {
    char UpdateType;
    edge_type source, destination;
};
// struct EdgeArray {
//     Edge *E;
//     // EdgeArray(uint32_t edge_num) {
//     //     E = (Edge *)aligned_alloc(4096, sizeof(Edge) * edge_num);
//     // }
//     EdgeArray() {}
//     void init(offset_type edge_num) {
//         E = (Edge *)aligned_alloc(4096, sizeof(Edge) * edge_num);
//         // cudaHostAlloc(&E, sizeof(Edge) * edge_num, cudaHostAllocDefault);
//         size = edge_num;
//     }
//     offset_type size;
// };
// struct UpdateEdgeArray {
//     UpdateEdge *E;
//     UpdateEdgeArray(offset_type edge_num) {
//         E = (UpdateEdge *)aligned_alloc(4096, sizeof(UpdateEdge) * edge_num);
//         // cudaHostAlloc(&E, sizeof(UpdateEdge) * edge_num, cudaHostAllocDefault);
//         size = edge_num;
//     }
//     offset_type size;
// };

struct EdgeList {
    edge_type *Neighbors;
    offset_type degree;
    offset_type size;
    void init(edge_type nei_num) {
        Neighbors = (edge_type *)malloc(sizeof(edge_type) * nei_num);
        // cudaMallocHost(&Neighbors, sizeof(edge_type) * nei_num);
        degree = nei_num;
        size = nei_num;
    }
    void dinit() {
        free(Neighbors);
    }
    
};
struct Graph {
    EdgeList *V;
    offset_type *degrees;
    edge_type node_num;
    Graph(edge_type node_count) : node_num(node_count) {
        V = (EdgeList *)malloc(sizeof(EdgeList) * node_num);
        // cudaMallocHost(&V, sizeof(EdgeList) * node_num);
        // degrees = (offset_type *)malloc(sizeof(offset_type) * node_num);
        // cudaMallocHost(&degrees, sizeof(offset_type) * node_num);
        degrees = CPUAlloc(offset_type, node_num);
        #pragma omp parallel for
        for (edge_type i = 0; i < node_num; ++i) {
            V[i].Neighbors = nullptr;
            V[i].degree = 0;
            V[i].size = 0;
            degrees[i] = 0;
        }
    }

    ~Graph() {
        if (V != nullptr) {
            for (edge_type i = 0; i < node_num; ++i) {
                V[i].dinit();
            }
        }
        free(V);
        free(degrees);
    }

    Graph(const Graph&) = delete;
    Graph& operator=(const Graph&) = delete;

    void Insert(Edge* additions, edge_type additions_size) {
        edge_type source, destination;
        for (uint32_t i = 0; i < additions_size; i ++) {
            bool flag = false;
            source = additions[i].source;
            destination = additions[i].destination;
            if(V[source].degree == V[source].size) {
                V[source].Neighbors = (edge_type *)realloc(V[source].Neighbors, sizeof(edge_type) * (V[source].size + 1));
                if(V[source].Neighbors == nullptr) {
#ifdef GRAPHMINE_LIBRARY
                    throw std::bad_alloc();
#else
                    exit(-1);
#endif
                    // return ; 
                }
                // edge_type *temp;
                // cudaMallocHost(&temp, sizeof(edge_type) * (V[source].size + 1));
                // #pragma omp parallel for
                // for (edge_type i = 0; i < V[source].size; ++i) {
                //     temp[i] = V[source].Neighbors[i];
                // }
                // V[source].Neighbors = temp;
                V[source].size ++;
                ioffset_type j;
                for(j = V[source].degree - 1; j >= 0; --j) {
                    if(V[source].Neighbors[j] > destination) {
                        V[source].Neighbors[j + 1] = V[source].Neighbors[j];
                    } else if(V[source].Neighbors[j] < destination){
                        V[source].Neighbors[j + 1] = destination;
                        break;
                    } else {
                        flag = true; // have
                        break;
                    }
                }
                if(j == -1) { // head add
                    V[source].Neighbors[0] = destination;
                }
                if(flag)  {
                    for (j = j + 1; j < degrees[source]; ++j) {
                        V[source].Neighbors[j] = V[source].Neighbors[j + 1];
                    }
                    continue;
                }
                V[source].degree ++;
                degrees[source] ++;
            } else {
                ioffset_type j;
                for(j = V[source].degree - 1; j >= 0; --j) {
                    if(V[source].Neighbors[j] > destination) {
                        V[source].Neighbors[j + 1] = V[source].Neighbors[j];
                    } else if(V[source].Neighbors[j] < destination){
                        V[source].Neighbors[j + 1] = destination;
                        break;
                    } else {
                        flag = true; // have
                        break;
                    }
                }
                if(j == -1) {
                    V[source].Neighbors[0] = destination;
                }
                if(flag) {
                    for (j = j + 1; j < degrees[source]; ++j) {
                        V[source].Neighbors[j] = V[source].Neighbors[j + 1];
                    }
                    continue;
                }
                    
                V[source].degree ++;
                degrees[source] ++;
            }
        }
    }
    void Delete(Edge *deletions, edge_type deletions_size) {
        edge_type source, destination;
        for(uint32_t i = 0; i < deletions_size; i ++) {
            source = deletions[i].source;
            destination = deletions[i].destination;
            ioffset_type j;
            bool flag = false;
            for (j = 0; j < V[source].degree; ++j) {
                // cout << j << endl;
                // cout << V[source].degree << endl;
                // cout << V[source].Neighbors[j] << endl;
                
                if(V[source].Neighbors[j] == destination) {
                    flag = true; // have 
                    break;
                }
            }
            // cout << "Now1" << endl;
            if(flag) {
                for (;j < V[source].degree - 1; ++j) {
                    V[source].Neighbors[j] = V[source].Neighbors[j + 1];
                }
                V[source].degree--;
                degrees[source] --;
            }
            // cout << "Now2" << endl;
            // cout << i << " " << deletions_size << endl;
        }
    }
};
#endif
