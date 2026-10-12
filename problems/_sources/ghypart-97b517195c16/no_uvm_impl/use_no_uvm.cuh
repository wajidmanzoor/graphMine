#pragma once
#include <iostream>
#include <stdio.h>
#include <stdlib.h>
#include <vector>
#include <set>
#include <map>
#include <string.h>
#include <algorithm>
#include <string>
#include <unordered_set>
#include <tuple>
#include <experimental/filesystem>
#include "../include/graph.h"
#include "../utility/utils.cuh"
#include "../utility/param_config.h"
#include <thrust/device_vector.h>
#include <thrust/execution_policy.h>



struct sum_min_max {
    int sum, min, max;
    sum_min_max() {
        sum = 0, min = INT_MAX, max = 0;
    }
    __device__ __host__ sum_min_max(int value) {
        sum = value, min = value, max = value;
    }
};

struct mycombiner {
    __host__ __device__
    sum_min_max operator()(sum_min_max a, sum_min_max b) {
        a.sum += b.sum;
        if (a.min > b.min)  a.min = b.min;
        if (a.max < b.max)  a.max = b.max;
        return a;
  }
};

void SetupWithoutUVM(OptionConfigs optCfgs, char **argv, cudaDeviceProp deviceProp);

Hypergraph* coarsen_no_uvm(Hypergraph* hgr, int iter, int LIMIT, float& time, float& other_time, OptionConfigs& optcfgs, 
                            unsigned long& memBytes, std::vector<std::pair<std::string, float>>& perfs, Auxillary* aux, 
                            std::vector<std::vector<std::pair<std::string, float>>>& iter_perfs, float& selectionOverhead, float& alloc_time);

Hypergraph* coarsen_no_uvm_brute_force(Hypergraph* hgr, int iter, int LIMIT, float& time, float& other_time, OptionConfigs& optcfgs, 
                            unsigned long& memBytes, std::vector<std::pair<std::string, float>>& perfs, Auxillary* aux, 
                            std::vector<std::vector<std::pair<std::string, float>>>& iter_perfs);

void init_partition_no_uvm(Hypergraph* hgr, unsigned int K, bool use_curr_precision, float& time, float& other_time, OptionConfigs& optcfgs);

void refine_no_uvm(Hypergraph* hgr, unsigned refineTo, float& time, float& cur, float& other_time, int curr_idx, OptionConfigs& optCfgs);

void rebalance_no_uvm(Hypergraph* hgr, float ratio, unsigned int K, float imbalance, float& time, float& cur_bal, 
                        float& other_time, int& rebalance, int curr_idx, OptionConfigs& optCfgs, unsigned long& memBytes);

void project_no_uvm(Hypergraph* coarsenHgr, Hypergraph* fineHgr, float& time, float& other_time, float& cur, int cur_iter);

void rebalance_no_uvm_without_multiple_sort(Hypergraph* hgr, float ratio, unsigned int K, float imbalance, float& time, float& cur_bal, 
                                            float& other_time, int& rebalance, int curr_idx, OptionConfigs& optCfgs, unsigned long& memBytes);


void kway_partition_no_uvm(Hypergraph* hgr, unsigned int K, float& time, float& other_time, OptionConfigs& optcfgs);

struct tmpNode_nouvm {
    unsigned nodeid;
    int gain;
    int weight;
    int real_gain;
    int move_direction;
    int src_part;
};

struct adjNode_nouvm {
    int degree;
    int offset;
    int parent;
};

struct mycmpG {
    __host__ __device__
    bool operator()(const tmpNode_nouvm& node_a, const tmpNode_nouvm& node_b) {
        if (node_a.gain == node_b.gain) {
            return node_a.nodeid < node_b.nodeid;
        }
        return node_a.gain > node_b.gain;
  }
};


struct mycmpG_non_det {
    __host__ __device__
    bool operator()(const tmpNode_nouvm& node_a, const tmpNode_nouvm& node_b) {
        return node_a.gain > node_b.gain;
  }
};

struct cmpGbyW_d {
    __host__ __device__
    bool operator()(const tmpNode_nouvm& node_a, const tmpNode_nouvm& node_b) {
        if (fabs((double)(node_a.gain * (1.0f / node_a.weight)) - (double)(node_b.gain * (1.0f / node_b.weight))) < 0.000001f) {
            return (float)node_a.nodeid < (float)node_b.nodeid;
        }
        return (double)(node_a.gain * (1.0f / node_a.weight)) > (double)(node_b.gain * (1.0f / node_b.weight));
  }
};

struct cmpGbyW_d_non_det {
    __host__ __device__
    bool operator()(const tmpNode_nouvm& node_a, const tmpNode_nouvm& node_b) {
        return (double)(node_a.gain * (1.0f / node_a.weight)) > (double)(node_b.gain * (1.0f / node_b.weight));
  }
};

// for ecology1.mtx, we use 0.00001f
struct cmpGbyW_f {
    __host__ __device__
    bool operator()(const tmpNode_nouvm& node_a, const tmpNode_nouvm& node_b) {
        if (fabs((float)(node_a.gain * (1.0f / node_a.weight)) - (float)(node_b.gain * (1.0f / node_b.weight))) < 0.000001f) {
            return node_a.nodeid < node_b.nodeid;
        }
        return (float)(node_a.gain * (1.0f / node_a.weight)) > (float)(node_b.gain * (1.0f / node_b.weight));
  }
};

struct cmpGbyW1_f {
    __host__ __device__
    bool operator()(const tmpNode_nouvm& node_a, const tmpNode_nouvm& node_b) {
        if (fabs((float)(node_a.gain * (1.0f / node_a.weight)) - (float)(node_b.gain * (1.0f / node_b.weight))) < 0.00001f) {
            return node_a.nodeid < node_b.nodeid;
        }
        return (float)(node_a.gain * (1.0f / node_a.weight)) > (float)(node_b.gain * (1.0f / node_b.weight));
  }
};


struct cmpGbyW_non_det {
    __host__ __device__
    bool operator()(const tmpNode_nouvm& node_a, const tmpNode_nouvm& node_b) {
        return (float)(node_a.gain * (1.0f / node_a.weight)) > (float)(node_b.gain * (1.0f / node_b.weight));
  }
};

struct cmpGbyW1_non_det {
    __host__ __device__
    bool operator()(const tmpNode_nouvm& node_a, const tmpNode_nouvm& node_b) {
        return (float)(node_a.gain * (1.0f / node_a.weight)) > (float)(node_b.gain * (1.0f / node_b.weight));
  }
};

__global__ void init_move_gain(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN);

__global__ void init_move_gain1(int* nodes, unsigned* adj_list, int hedgeN, int nodeN, unsigned* hedge_id, int* adj_part_list, int totalsize, int* p1_num, int* p2_num, int* hedges);

__global__ void collect_part_info(int* nodes, int nodeN, int hedgeN, int totalsize, unsigned* adj_list, unsigned* hedge_id, int* adj_part_list, int* p1_num, int* p2_num);

__global__ void collect_part_info1(int* nodes, int nodeN, int hedgeN, int totalsize, unsigned* adj_list, unsigned* hedge_id, int* p1_num, int* p2_num);

__global__ void init_refine_boundary_nodes(int* nodes, unsigned* adj_list, int hedgeN, int nodeN, unsigned* hedge_id, int totalsize, int* p1_num, int* p2_num);

__global__ void set_adj_nodes_part(int* nodes, int nodeN, int hedgeN, int totalsize, unsigned* adj_list, int* adj_part_list);

__global__ void collect_part_info2(int* nodes, int nodeN, int hedgeN, int totalsize, unsigned* adj_list, unsigned* hedge_id, int* p1_num, int* p2_num, int* adj_part_list);

__global__ void init_refine_boundary_nodes1(int* nodes, unsigned* adj_list, int hedgeN, int nodeN, unsigned* hedge_id, int totalsize, int* p1_num, int* p2_num, int* adj_part_list);

Hypergraph* non_det_coarsen_no_uvm(Hypergraph* hgr, int iter, int LIMIT, float& time, float& other_time, OptionConfigs& optcfgs, 
                            unsigned long& memBytes, std::vector<std::pair<std::string, float>>& perfs, Auxillary* aux);


void init_partition_fix_heaviest_node(Hypergraph* hgr, unsigned int K, bool use_curr_precision, float& time, float& other_time, OptionConfigs& optcfgs);

void rebalance_no_uvm_single_sort_fix_heaviest_node(Hypergraph* hgr, float ratio, unsigned int K, float imbalance, float& time, float& cur, 
                                            float& other_time, int& rebalance, int curr_idx, OptionConfigs& optCfgs, unsigned long& memBytes);

void refine_no_uvm_fix_heaviest_node(Hypergraph* hgr, unsigned refineTo, float& time, float& cur, float& other_time, int cur_iter, OptionConfigs& optcfgs);

void refine_no_uvm_fix_node_hybrid_move(Hypergraph* hgr, unsigned refineTo, float& time, float& cur, float& other_time, int cur_iter, OptionConfigs& optcfgs);

void refine_no_uvm_with_hybrid_move(Hypergraph* hgr, unsigned refineTo, float& time, float& cur, float& other_time, int cur_iter, OptionConfigs& optcfgs);

void refine_no_uvm_with_movegain_verify(Hypergraph* hgr, unsigned refineTo, float& time, float& cur, float& other_time, unsigned int K, int comb_len, float ratio, float imbalance, int cur_iter, OptionConfigs& optcfgs);

struct myPair {
    unsigned combinationID;
    int gain;
};

__global__ void parallelMoveCombinationGainComputation(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN, tmpNode_nouvm* nodelist, int K, myPair* bestPair);

__global__ void init_move_gain_in_refine(int* hedges, int* nodes, unsigned* adj_list, int hedgeN, int nodeN);

struct h_size {
    unsigned id;
    int size;
    int eInBag;
    int firstnode;
};

struct sort_by_size_ge
{
    __host__ __device__  __forceinline__
    bool operator()(const h_size &x, const h_size &y) {
        return x.size > y.size;
    }
};

struct sort_by_size_le
{
    __host__ __device__  __forceinline__
    bool operator()(const h_size &x, const h_size &y) {
        if (x.size == y.size) {
            return x.firstnode < y.firstnode;
        }
        return x.size < y.size;
    }
};

struct sort_by_first_node_then_size
{
    __host__ __device__  __forceinline__
    bool operator()(const h_size &x, const h_size &y) {
        if (x.firstnode == y.firstnode) {
            return x.size < y.size;
        }
        return x.firstnode < y.firstnode;
    }
};

struct local_node_info {
    unsigned id;
    int degree;
};
