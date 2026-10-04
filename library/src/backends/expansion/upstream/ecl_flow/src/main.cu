/*
ECL-MaxFlow: This code computes the maximum flow of a directed or undirected graph.

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

#include "maxflow.cu"
 
int main(int argc, char* argv[])
{
  printf("ECL-Maxflow\n");
  printf("Copyright 2025 Avery VanAusdal and Martin Burtscher\n");
  if (argc < 4) {fprintf(stderr, "USAGE: %s input_file_name source_node sink_node runs(default=%i)\n\nThe optional 'runs' parameter runs the code multiple times and returns the median runtime and throughput\n", argv[0], default_runs); exit(-1);}
  
  GPUTimer header_timer, rcsr_timer;
  header_timer.start();
  
  // process command line
  ECLgraph g = readECLgraph(argv[1]);
  printf("input: %s\n", argv[1]);
  printf("nodes: %d\n", g.nodes);
  printf("edges: %d\n", g.edges);
  
  const int source = atoi(argv[2]);
  if ((source < 0) || (source >= g.nodes)) {fprintf(stderr, "ERROR: source_node must be between 0 and %d\n", g.nodes-1); exit(-1);}
  printf("source: %d\n", source);
  
  const int sink = atoi(argv[3]);
  if ((sink < 0) || (sink >= g.nodes)) {fprintf(stderr, "ERROR: sink_node must be between 0 and %d\n", g.nodes-1); exit(-1);}
  if (sink == source) {fprintf(stderr, "ERROR: sink_node and source_node cannot be the same node\n"); exit(-1);}
  printf("sink:   %d\n", sink);
  
  int runs = default_runs;
  if (argc >= 5) {
    if (const int runsInt = atoi(argv[4])) {
      runs = runsInt;
    }
  }
  printf("runs: %d\n", runs);
  
  GPUinfo(0);
  
  int* const flow = new int [g.edges];  // stores output too
  int* const capacity = new int [g.edges];
  ECLgraph d_g = g;
  if (cudaSuccess != cudaMalloc((void **)&d_g.nindex, (g.nodes + 1) * sizeof(int))) fprintf(stderr, "ERROR: could not allocate nindex\n");
  if (cudaSuccess != cudaMalloc((void **)&d_g.nlist, g.edges * sizeof(int))) fprintf(stderr, "ERROR: could not allocate nlist\n");
  if (cudaSuccess != cudaMemcpy(d_g.nindex, g.nindex, (g.nodes + 1) * sizeof(int), cudaMemcpyHostToDevice)) fprintf(stderr, "ERROR: copying of index to device failed\n");
  if (cudaSuccess != cudaMemcpy(d_g.nlist, g.nlist, g.edges * sizeof(int), cudaMemcpyHostToDevice)) fprintf(stderr, "ERROR: copying of nlist to device failed\n");
  
  // create "reverse" neighbor list for backwards traversal
  int* const rnindex = new int [g.nodes + 1];
  int* const rnlist = new int [g.edges];
  int* const retoe = new int [g.edges];  // maps reverse edge index to edge index; retoe[re] == e;
  
  rcsr_timer.start();
  std::vector<std::pair<int,int>>* const incoming = new std::vector<std::pair<int,int>> [g.nodes];  // track nbors' incoming edges 
  for (int v = 0; v < g.nodes; v++) {
    for (int e = g.nindex[v]; e < g.nindex[v + 1]; e++) {
      const int nbor = g.nlist[e];
      incoming[nbor].push_back(std::make_pair(e, v));  // (fwd edge, starting vertex)
    }
  }
  int reidx = 0;  // reverse edge index
  rnindex[0] = 0;
  for (int v = 0; v < g.nodes; v++) {
    for (std::pair<int, int> p : incoming[v]) {  // add each rnbor and move counter to next open space
      int e = p.first;  // fwd edge
      int src = p.second;  // starting vertex
      rnlist[reidx] = src;  // endpoint of reverse edge = starting vertex
      retoe[reidx] = e;  // map reverse edge back to fwd edge 
      ++reidx;
    }
    rnindex[v + 1] = reidx;  // set next list's start point
  }
  delete [] incoming;
  const double rcsr_time = rcsr_timer.stop();
  
  // assign capacities
  if (g.eweight == NULL) {  // assign random capacities
    srand(source);
    for (int e = 0; e < g.edges; e++) {
      capacity[e] = rand() % g.nodes;  // random capacity value
    }
  } else {  // use absolute value of edge weights
    for (int e = 0; e < g.edges; e++) {
      capacity[e] = abs(g.eweight[e]);
    }
  }
  
  long sink_cap = 0;
  for (int re = rnindex[sink]; re < rnindex[sink + 1]; re++) {
    const int e = retoe[re];
    sink_cap += capacity[e];
  }
  printf("source info: %i in-edges, %i out-edges\n", rnindex[source + 1] - rnindex[source], g.nindex[source + 1] - g.nindex[source]);
  printf("sink max capacity: %li across %i in-edges\n", sink_cap, rnindex[sink + 1] - rnindex[sink]);
  
  int* d_rnindex;
  if (cudaSuccess != cudaMalloc((void **)&d_rnindex, (g.nodes + 1) * sizeof(int))) fprintf(stderr, "ERROR: could not allocate nindex\n");
  if (cudaSuccess != cudaMemcpy(d_rnindex, rnindex, (g.nodes + 1) * sizeof(int), cudaMemcpyHostToDevice)) fprintf(stderr, "ERROR: copying of index to device failed\n");
  delete [] rnindex;
  
  int* d_rnlist;
  if (cudaSuccess != cudaMalloc((void **)&d_rnlist, g.edges * sizeof(int))) fprintf(stderr, "ERROR: could not allocate nlist\n");
  if (cudaSuccess != cudaMemcpy(d_rnlist, rnlist, g.edges * sizeof(int), cudaMemcpyHostToDevice)) fprintf(stderr, "ERROR: copying of nlist to device failed\n");
  delete [] rnlist;
  
  int* d_retoe;
  if (cudaSuccess != cudaMalloc((void **)&d_retoe, g.edges * sizeof(int))) fprintf(stderr, "ERROR: could not allocate nlist\n");
  if (cudaSuccess != cudaMemcpy(d_retoe, retoe, g.edges * sizeof(int), cudaMemcpyHostToDevice)) fprintf(stderr, "ERROR: copying of nlist to device failed\n");
  delete [] retoe;
  
  printf("header total init time: %.6fs (including building rcsr: %.6fs)\n", header_timer.stop(), rcsr_time);
  
  double runtimes [runs];
  for (int i = 0; i < runs; i++) {
    runtimes[i] = GPUmaxflow(g, d_g, source, sink, flow, capacity, d_rnindex, d_rnlist, d_retoe);
    fflush(NULL);
  }
  const double med = median(runtimes, runs);
  
  printf("median runtime: %.6fs\n", med);
  printf("Throughput: %.6f gigaedges/s\n", 0.000000001 * g.edges / med);
  
  cudaFree(d_g.nindex);
  cudaFree(d_g.nlist);
  cudaFree(d_rnindex);
  cudaFree(d_rnlist);
  cudaFree(d_retoe);
  delete [] flow;
  delete [] capacity;
}