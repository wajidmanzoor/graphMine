/*
This code was written as a preprocessor for ECL-MaxFlow.

Copyright (c) 2025, Avery VanAusdal and Martin Burtscher

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

   * Redistributions of source code must retain the above copyright
     notice, this list of conditions and the following disclaimer.
   * Redistributions in binary form must reproduce the above copyright
     notice, this list of conditions and the following disclaimer in the
     documentation and/or other materials provided with the distribution.
   * Neither the name of Texas State University nor the names of its
     contributors may be used to endorse or promote products derived from
     this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL TEXAS STATE UNIVERSITY BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

URL: The latest version of this code is available at
https://github.com/burtscher/ECL-MaxFlow.

Publication: This work is described in detail in the following paper.
Avery Vanausdal and Martin Burtscher. An Efficient Push-Relabel Implementation for Max-Flow Computations on GPUs. Proceedings of the 44th IEEE International Performance Computing and Communications Conference. November 2025.

Sponsor: This code is based upon work supported by the U.S. National Science Foundation (NSF) under Award #1955367 and by an equipment donation from NVIDIA Corporation.
*/

#define EXISTING_WEIGHT_DIVISION_FACTOR 3
#define NEW_WEIGHT_MIN 100
#define NEW_WEIGHT_MAX 10000

#define NEW_WEIGHT_MODULO NEW_WEIGHT_MAX - NEW_WEIGHT_MIN

#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <vector>
#include <tuple>
#include <algorithm>
#include <iostream>
#include <fstream>
#include <cassert>
#include <set>
#include <map>
#include <atomic>
#include "ECLgraph.h"
#include "IndigoCC.cpp"

// not tested on directed graphs

static double CPUcc_vertex(const ECLgraph g, int* label, const int threadCount);

static void verify(const int v, const int id, const int* const __restrict__ nidx, const int* const __restrict__ nlist, data_type* const __restrict__ nstat, const int nodes)
{
  if (nstat[v] < nodes) {
    if (nstat[v] != id) {fprintf(stderr, "ERROR: found incorrect ID value\n\n");  exit(-1);}
    nstat[v] = nodes;
    for (int i = nidx[v]; i < nidx[v + 1]; i++) {
      verify(nlist[i], id, nidx, nlist, nstat, nodes);
    }
  }
}

static void verifyCC(const ECLgraph g, int* const label, std::set<int>& s1)
{
  for (int v = 0; v < g.nodes; v++) {
    for (int i = g.nindex[v]; i < g.nindex[v + 1]; i++) {
      if (label[g.nlist[i]] != label[v]) {fprintf(stderr, "ERROR: found adjacent nodes in different components\n\n");  exit(-1);}
    }
  }

  for (int v = 0; v < g.nodes; v++) {
    if (label[v] >= g.nodes) {fprintf(stderr, "ERROR: found sentinel number\n\n");  exit(-1);}
  }

  printf("CC verification passed\n");
}

int main(int argc, char* argv[])
{
  printf("ECL Graph Preprocessor - Largest Component Subgraph (%s)\n", __FILE__);
  printf("Copyright 2025 Avery VanAusdal and Martin Burtscher\n");

  if (argc < 3) {fprintf(stderr, "USAGE: %s input_graph output_graph old_source(optional) old_sink(optional)\n\nIf old_source or old_sink are specified, the code will output what their new indices are in the output_graph.\n", argv[0]);  exit(-1);}

  ECLgraph g = readECLgraph(argv[1]);
  
  int source = -1;
  int sink = -1;
  if (argc >= 4) source = atoi(argv[3]);  // original source node
  if (argc >= 5) sink = atoi(argv[4]);  // original sink node
  
  if ((source < -1) || (source >= g.nodes)) {fprintf(stderr, "ERROR: source_node must be between 0 and %d\n", g.nodes - 1); exit(-1);}
  if ((sink < -1) || (sink >= g.nodes)) {fprintf(stderr, "ERROR: sink_node must be between 0 and %d\n", g.nodes-1); exit(-1);}
  
  int* const label = new int [g.nodes];
  
  int threadCount = std::thread::hardware_concurrency();  // use all available threads for Indigo3 CC
  
  CPUcc_vertex(g, label, threadCount);  // run Indigo3 CC on graph
  
  // print CC result
  std::set<int> s1;
  std::map<int, int> cc_size;
  for (int v = 0; v < g.nodes; v++) {
    s1.insert(label[v]);
    if (cc_size.count(label[v]) == 0) {
      cc_size[label[v]] = 1;
    } else {
      cc_size[label[v]] += 1;
    }
  }
  printf("number of connected components: %lu\n", s1.size());
  verifyCC(g, label, s1);
  
  if (s1.size() == 1) {
    printf("Only 1 CC found, writing to output file with no node changes; updating weights\n");
    
    if (g.eweight != NULL) {
      printf("dividing existing edge weights by %i \n", EXISTING_WEIGHT_DIVISION_FACTOR);
      for (int e = 0; e < g.edges; e++) {
        g.eweight[e] = (abs(g.eweight[e]) / EXISTING_WEIGHT_DIVISION_FACTOR) + 1;  // use existing weights if they exist
      }
    } else {
      printf("generating edge weights with srand(%i) and capacities from [%i,%i] \n", g.nodes, NEW_WEIGHT_MIN, NEW_WEIGHT_MAX);
      g.eweight = new int [g.edges];
      srand(g.nodes);
      for (int e = 0; e < g.edges; e++) {
        g.eweight[e] = (rand() % NEW_WEIGHT_MODULO) + NEW_WEIGHT_MIN;
      }
    }
    
    if (source != -1) printf("new source node: %i \n", source);
    if (sink != -1) printf("new sink node: %i \n", sink);
    writeECLgraph(g, argv[2]);
    return 0;
  }
  
  int max_cc = -1;
  int max_cc_size = -1;
  for (const auto &cc : s1) {
    int size = cc_size[cc];
    if (size > max_cc_size) {
      max_cc = cc;
      max_cc_size = size;
    }
  }
  const int num_outside_cc = g.nodes - max_cc_size;
  printf("largest CC has %i nodes, removing %i (%.2f%%) outside nodes\n", max_cc_size, num_outside_cc, (100.0 * num_outside_cc) / g.nodes);
  
  int* nodes_skipped = new int[g.nodes];
  int* edges_skipped = new int[g.nodes];
  int num_nodes_skipped = 0;
  int num_edges_skipped = 0;
  int included_edges = 0;
  for (int v = 0; v < g.nodes; v++) {
    nodes_skipped[v] = num_nodes_skipped;  // mark how many nodes before v were skipped
    edges_skipped[v] = num_edges_skipped;
    if (label[v] != max_cc) {
      num_nodes_skipped++;
      num_edges_skipped += g.nindex[v + 1] - g.nindex[v];  // skip all outgoing edges
    } else {
      included_edges += g.nindex[v + 1] - g.nindex[v];
    }
  }
  assert(max_cc_size == (g.nodes - num_nodes_skipped));
  assert(included_edges == (g.edges - num_edges_skipped));
  printf("skipped %i nodes (%.2f%%) and %i edges (%.2f%%)\n", num_nodes_skipped, num_nodes_skipped * 100.0 / g.nodes, num_edges_skipped, num_edges_skipped * 100.0 / g.edges);
  
  ECLgraph ng;
  ng.nodes = max_cc_size;
  ng.edges = included_edges;
  ng.nindex = new int [ng.nodes + 1];
  ng.nlist = new int [ng.edges];
  ng.eweight = new int [ng.edges];
  
  for (int v = 0; v < (ng.nodes + 1); v++) {
    ng.nindex[v] = -1;  // sentinel value
  }
  for (int e = 0; e < ng.edges; e++) {
    ng.nlist[e] = -1;  // sentinel value
  }
  if (g.eweight == NULL) {  // if no existing weights, generate them now
    printf("generating edge weights with srand(%i) and capacities from [%i,%i] \n", ng.nodes, NEW_WEIGHT_MIN, NEW_WEIGHT_MAX);
    srand(ng.nodes);
    for (int ne = 0; ne < ng.edges; ne++) {
      ng.eweight[ne] = (rand() % NEW_WEIGHT_MODULO) + NEW_WEIGHT_MIN;
    }
  } else {
    printf("dividing existing edge weights by %i \n", EXISTING_WEIGHT_DIVISION_FACTOR);
  }
  
  ng.nindex[0] = 0;
  for (int v = 0; v < g.nodes; v++) {
    if (label[v] == max_cc) {
      const int nv = v - nodes_skipped[v];  // new graph's vertex index
      
      ng.nindex[nv + 1] = g.nindex[v + 1] - edges_skipped[v];
      
      assert(ng.nindex[nv] == g.nindex[v] - edges_skipped[v]);
      assert((g.nindex[v + 1] - g.nindex[v]) == (ng.nindex[nv + 1] - ng.nindex[nv]));
      
      int ne = ng.nindex[nv];  // new graph's edge index
      for (int e = g.nindex[v]; e < g.nindex[v + 1]; e++) {
        if (g.eweight != NULL) ng.eweight[ne] = (abs(g.eweight[e]) / EXISTING_WEIGHT_DIVISION_FACTOR) + 1;  // use existing weights if they exist
        
        const int dst = g.nlist[e];  // original destination index
        ng.nlist[ne] = dst - nodes_skipped[dst];
        ne++;
      }
    }
  }
  assert(ng.nindex[ng.nodes] == ng.edges);
  
  for (int v = 0; v < (ng.nodes + 1); v++) {
    if (ng.nindex[v] == -1) {  // check for sentinel value
      printf("ng.nindex[%i] was never set \n", v); return -1;
    }
  }
  for (int e = 0; e < ng.edges; e++) {
    if (ng.nlist[e] == -1) {  // check for sentinel value
      printf("ng.nlist[%i] was never set \n", e); return -1;
    }
  }
  
  printf("output graph: %i nodes and %i edges\n", ng.nodes, ng.edges);
  
  if (source != -1) {
    int offset = nodes_skipped[source];
    printf("new source node: %i \n", source - offset);
  }
  if (sink != -1) {
    int offset = nodes_skipped[sink];
    printf("new sink node: %i \n", sink - offset);
  }
  
  // write output file
  writeECLgraph(ng, argv[2]);
  
  // free memory
  freeECLgraph(g);
  freeECLgraph(ng);
  delete [] label;
  delete [] nodes_skipped;
  delete [] edges_skipped;

  return 0;
}
