#include<bits/stdc++.h>
using namespace std;

#include "include/hbcg_utils.cuh"
#include "parlay/sequence.h"
#include "parlay/parallel.h"
#include "bridge.h"


inline int find_compress(int i, int* parents) {
  int j = i;
  if (parents[j] == j) return j;
  do {
    j = parents[j];
  } while (parents[j] != j);
  int tmp;
  while ((tmp = parents[i]) > j) {
    parents[i] = j;
    i = tmp;
  }
  return j;
}


inline bool unite_impl(int u_orig, int v_orig, int* parents, uint64_t* sptree) {
  int u = u_orig;
  int v = v_orig;
  while (u != v) {
    u = find_compress(u, parents);
    v = find_compress(v, parents);
    if (u > v && parents[u] == u &&
             gbbs::atomic_compare_and_swap(&parents[u], u, v)) {
              sptree[u] = (uint64_t)u_orig << 32 | v_orig;
      return true;
    } else if (v > u && parents[v] == v &&
               gbbs::atomic_compare_and_swap(&parents[v], v, u)) {
              sptree[v] = (uint64_t)u_orig << 32 | v_orig;
      return true;
    }
  }
  return false;
}

inline void union_find_2(int u, int v, parlay::sequence<int> &parent , parlay::sequence<int> &temp_label , parlay::sequence<uint64_t> &sptree, parlay::sequence<int> &first_occ, parlay::sequence<int> &last_occ, parlay::sequence<int> &w1, parlay::sequence<int> &w2) { 

  int f_u = first_occ[u];
  int l_u = last_occ[u];
  int f_v = first_occ[v];
  int l_v = last_occ[v];
  if(parent[u]!=v && parent[v]!=u){
    if(!(f_u <= f_v && l_u>=f_v  || f_v <= f_u && l_v>=f_u)){
      bool r = unite_impl(u, v, temp_label.begin(), sptree.begin());
    }
    else{
      if(f_u < f_v){
        gbbs::write_min(&w1[v], f_u);
        gbbs::write_max(&w2[u], f_v);
      }
      else{
        gbbs::write_min(&w1[u], f_v);
        gbbs::write_max(&w2[v], f_u);
      }
    }
  }
}

void SimpleUnionAsync(int n, long m, parlay::sequence<uint64_t> &h_edgelist, parlay::sequence<int> &labels, parlay::sequence<int> &parents, parlay::sequence<uint64_t> &sptree) {

  auto start = chrono::high_resolution_clock::now();

  //unite
  parlay::parallel_for(0, m, [&](long i) {
      uint64_t edge = h_edgelist[i];
      int u = edge >> 32;          // Extract the upper 32 bits
      int v = edge & 0xFFFFFFFF;   // Extract the lower 32 bits
      unite_impl(u, v, parents.begin(), sptree.begin());
  });

  auto end = chrono::high_resolution_clock::now();
  cout << "Time taken by sub module cpu : " << chrono::duration_cast<chrono::milliseconds>(end - start).count() << " ms\n";
}


int host_spanning_tree(struct graph_data_host* h_input) {
    SimpleUnionAsync(h_input->V[0], h_input->edges_size[0], h_input->edges, h_input->label, h_input->temp_label , h_input->sptree);
    return 0;
}


float ComputeTagsAndSpanningForest_host(struct graph_data_host* h_input) {

    parlay::parallel_for(0, h_input->V[0], [&](int i) {
        h_input->temp_label[i] = i;
        h_input->sptree[i] = INT_MAX;
    });

    long m = h_input->edges_size[0];

    auto start = chrono::high_resolution_clock::now();
    parlay::parallel_for(0, m, [&](long i) {
        uint64_t edge = h_input->edges[i];
        int u = edge >> 32;          // Extract the upper 32 bits
        int v = edge & 0xFFFFFFFF;   // Extract the lower 32 bits
        if(u<v)
        {
          union_find_2(u, v, h_input->parent, h_input->temp_label, h_input->sptree, h_input->first_occ, h_input->last_occ, h_input->w1, h_input->w2);
        }
    });
    auto end = chrono::high_resolution_clock::now();
    printf("Time taken by sub module cpu : %f ms\n", (float)chrono::duration_cast<chrono::milliseconds>(end - start).count());
    return (float)chrono::duration_cast<chrono::milliseconds>(end - start).count();
}