#ifndef GRAPH_H
#define GRAPH_H

#include <iostream>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <unordered_map>
#include <fstream>
#include <string>
#include <algorithm>
#include <queue>
#include "helper.h"
#include "params.h"

class Graph {
private:
    int vcount_;
    int ecount_;

    std::vector<int> deg_;
    std::vector<int> vertex_label_;

    std::vector<unsigned> bknbrs_;

public:

    friend class Graph_GPU;

    std::vector<std::vector<int>> adj_;
    std::vector<std::unordered_map<int, int>> nlf_;
    std::unordered_map<int, std::vector<int>> label_vertex_mapping_;

    int
    max_label() const {
        return *std::max_element(vertex_label_.begin(), vertex_label_.end());
    }

    int
    label(int u) const {
        return vertex_label_[u];
    }

    int
    vcount() const {
        return vcount_;
    }

    int
    ecount() const {
        return ecount_;
    }

    int
    degree(int u) const {
        return deg_[u];
    }

    Graph(const std::string &file_path);

    Graph(const std::string &file_path, std::vector<int> &matching_order);

#ifdef GRAPHMINE_LIBRARY
    Graph(const std::vector<std::vector<int>> &adjacency,
          const std::vector<int> &labels);

    Graph(const Graph &original, const std::vector<int> &matching_order);
#endif

    void
    print_meta() const {
        std::cout << "|V|=" << vcount_ << " |E|=" << ecount_ << " |\u03A3|=" <<
                  label_vertex_mapping_.size() << std::endl;
    }

    bool
    is_adjacent(int v1, int v2) const {
        if (adj_[v1].size() < adj_[v2].size()) {
            auto it = std::lower_bound(adj_[v1].begin(), adj_[v1].end(), v2);
            if (it == adj_[v1].end()) {
                return false;
            }
            else {
                return *it == v2;
            }
        }

        auto it = std::lower_bound(adj_[v2].begin(), adj_[v2].end(), v1);
        if (it == adj_[v2].end()) {
            return false;
        }
        else {
            return *it == v1;
        }
    }

    void
    generate_matching_order(std::vector<int> &matching_order) const;

    void
    generate_bfs_order(std::vector<int> &bfs_order, int start = 0) const;

    void
    generate_label_mask(unsigned &label_mask) const {
        label_mask = 0;
        for (int i = 0; i < vcount_; i++) {
            bool unique = true;
            for (int j = 0; j < vcount_; j++) {
                if (i == j) {
                    continue;
                }
                if (vertex_label_[j] == vertex_label_[i]) {
                    unique = false;
                    break;
                }
            }
            if (unique) {
                label_mask |= (1 << i);
            }
        }
        label_mask = ~label_mask;
    }

    void
    generate_backward_mask(unsigned &backward_mask) const {
        backward_mask = 0;
        for (int i = 0; i < vcount_; i++) {
            bool unique = true;
            for (int j = 0; j < i; j++) {
                if (vertex_label_[j] == vertex_label_[i]) {
                    unique = false;
                    break;
                }
            }
            if (unique) {
                backward_mask |= (1 << i);
            }
        }
        backward_mask = ~backward_mask;
    }

private:

    void
    generate_backward_neighborhood() {
        // Only query graph can call this function.
        assert(vcount_ <= 32);
        bknbrs_.resize(vcount_);

        for (int u = 0; u < vcount_; u++) {
            unsigned mask = 0;
            for (int uu = 0; uu < u; uu++) {
                if (is_adjacent(u, uu)) {
                    mask |= (1u << uu);
                }
            }
            bknbrs_[u] = mask;
        }
    }

private:
    int
    find_automorphisms(std::vector<std::vector<uint32_t>> &embeddings) const;

public:
    int
    restriction_generation(std::vector<uint32_t> &partial_order) const;
};


class Graph_GPU {
public:
    int vcount_;

    // int *d_adj_;
    // int *d_offset_;

    unsigned *d_bknbrs_;

public:
    __device__ __host__ __forceinline__ int
    vcount() const {
        return vcount_;
    }

    Graph_GPU(const Graph &G, bool is_query) {
        this->vcount_ = G.vcount_;

        // int *h_adj_ = (int *)malloc(sizeof(int) * G.ecount() * 2);
        // int *h_offset_ = (int *)malloc(sizeof(int) * (G.vcount() + 1));
        // int off = 0;
        // for (int i = 0; i < G.vcount(); i++) {
        //     h_offset_[i] = off;
        //     for (int j : G.adj_[i]) {
        //         h_adj_[off++] = j;
        //     }
        // }
        // h_offset_[G.vcount()] = G.ecount() * 2;

        // cudaCheck(cudaMalloc(&d_adj_, sizeof(int) * G.ecount() * 2));
        // cudaCheck(cudaMalloc(&d_offset_, sizeof(int) * (G.vcount() + 1)));
        // cudaCheck(cudaMemcpy(d_adj_, h_adj_, sizeof(int) * G.ecount() * 2,
        //                      cudaMemcpyHostToDevice));
        // cudaCheck(cudaMemcpy(d_offset_, h_offset_, sizeof(int) * (G.vcount() + 1),
        //                      cudaMemcpyHostToDevice));

        // free(h_adj_);
        // free(h_offset_);

        d_bknbrs_ = nullptr;

        if (is_query) {
            // Create index for backward neighbors.
            cudaCheck(cudaMalloc(&d_bknbrs_, sizeof(unsigned) * G.bknbrs_.size()));
            cudaCheck(cudaMemcpy(d_bknbrs_, G.bknbrs_.data(), 
                                 sizeof(unsigned) * G.bknbrs_.size(), cudaMemcpyHostToDevice));
        }
    }

    void __host__
    deallocate() {
        // cudaCheck(cudaFree(d_adj_));
        // cudaCheck(cudaFree(d_offset_));
        if (d_bknbrs_ != nullptr) {
            cudaCheck(cudaFree(d_bknbrs_));
        }
    }
};


#endif
