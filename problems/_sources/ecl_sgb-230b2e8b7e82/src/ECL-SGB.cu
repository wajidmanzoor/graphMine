/*
ECL-SGB: Signed Graph Balancing algorithm for signed social network graphs

Copyright 2026, Texas State University. All rights reserved.

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

Authors: Avery VanAusdal and Martin Burtscher

URL: The latest version of this code is available at https://github.com/burtscher/ECL-SGB/.

Publication: This work is described in detail in the following paper.
Avery Vanausdal and Martin Burtscher. "Signed Graph Balancing in Linear Time." Proceedings of the 18th Workshop on General Purpose Processing Using GPUs. March 2026.

Sponsor: This code is based upon work supported by the U.S. National Science Foundation (NSF) under Award #1955367 and by an equipment donation from NVIDIA Corporation.

This code is partially based on graphB+, which is available at https://cs.txstate.edu/~burtscher/research/graphBplus/.
*/


#include <cstdio>
#include <climits>
#include <algorithm>
#include <set>
#include <map>
#include <sys/time.h>
#include <tuple>  
#include <vector>
#include <cuda.h>
#include <string>
#include <assert.h>

static const bool verify = false;  // set to false for better performance
static const int Device = 0;  // defaults to fastest available GPU; change this or CUDA_VISIBLE_DEVICES to switch GPUs
static const int ThreadsPerBlock = 512;
static const int warpsize = 32;

struct Graph {
  int nodes;
  int edges;
  int* nindex;  // first CSR array
  int* nlist;  // second CSR array
  bool* eweight;  // edge signs (false == positive; true == negative)
  int* origID;  // original node IDs
};


static void freeGraph(Graph &g)
{
  g.nodes = 0;
  g.edges = 0;
  delete [] g.nindex;
  delete [] g.nlist;
  delete [] g.eweight;
  delete [] g.origID;
  g.nindex = NULL;
  g.nlist = NULL;
  g.eweight = NULL;
  g.origID = NULL;
}

// source of hash function: https://stackoverflow.com/questions/664014/what-integer-hash-function-are-good-that-accepts-an-integer-hash-key
static __device__ __host__ unsigned int hash(unsigned int val)
{
  val = ((val >> 16) ^ val) * 0x45d9f3b;
  val = ((val >> 16) ^ val) * 0x45d9f3b;
  return (val >> 16) ^ val;
}

static void CheckCuda(const int line)
{
  cudaError_t e;
  cudaDeviceSynchronize();
  if (cudaSuccess != (e = cudaGetLastError())) {
    fprintf(stderr, "CUDA error %d on line %d: %s\n", e, line, cudaGetErrorString(e));
    exit(-1);
  }
}

static __device__ __host__ int representative(const int idx, int* const __restrict__ label)
{
  int curr = label[idx];
  if (curr != idx) {
    int next, prev = idx;
    while (curr > (next = label[curr])) {
      label[prev] = next;
      prev = curr;
      curr = next;
    }
  }
  return curr;
}

static Graph readGraph(const char* const name)
{
  // read input from file
  FILE* fin = fopen(name, "rt");
  if (fin == NULL) {printf("ERROR: could not open input file %s\n", name); exit(-1);}
  size_t linesize = 256;
  char buf[linesize];
  char* ptr = buf;
  getline(&ptr, &linesize, fin);  // skip first line

  int selfedges = 0, wrongweights = 0, duplicates = 0, inconsistent = 0, line = 1, cnt = 0;
  int src, dst, wei;
  std::map<int, int> map;  // map node IDs to contiguous IDs
  std::set<std::pair<int, int>> set2;
  std::set<std::tuple<int, int, int>> set3;
  while (fscanf(fin, "%d,%d,%d", &src, &dst, &wei) == 3) {
    if (src == dst) {
      selfedges++;
    } else if ((wei < -1) || (wei > 1)) {
      wrongweights++;
    } else if (set2.find(std::make_pair(std::min(src, dst), std::max(src, dst))) != set2.end()) {
      if (set3.find(std::make_tuple(std::min(src, dst), std::max(src, dst), wei)) != set3.end()) {
        duplicates++;
      } else {
        inconsistent++;
      }
    } else {
      set2.insert(std::make_pair(std::min(src, dst), std::max(src, dst)));
      set3.insert(std::make_tuple(std::min(src, dst), std::max(src, dst), wei));
      if (map.find(src) == map.end()) {
        map[src] = cnt++;
      }
      if (map.find(dst) == map.end()) {
        map[dst] = cnt++;
      }
    }
    line++;
  }
  fclose(fin);

  // print stats
  printf("  read %d lines\n", line);
  if (selfedges > 0) printf("  skipped %d self-edges\n", selfedges);
  if (wrongweights > 0) printf("  skipped %d edges with out-of-range weights\n", wrongweights);
  if (duplicates > 0) printf("  skipped %d duplicate edges\n", duplicates);
  if (inconsistent > 0) printf("  skipped %d inconsistent edges\n", inconsistent);
  if (verify) {
    if ((int)map.size() != cnt) {printf("ERROR: wrong node count\n"); exit(-1);}
    printf("  number of unique nodes: %d\n", (int)map.size());
    printf("  number of unique edges: %d\n", (int)set3.size());
  }

  // compute CCs with union find
  int* const label = new int [cnt];
  for (int v = 0; v < cnt; v++) {
    label[v] = v;
  }
  for (auto ele: set3) {
    const int src = map[std::get<0>(ele)];
    const int dst = map[std::get<1>(ele)];
    const int vstat = representative(src, label);
    const int ostat = representative(dst, label);
    if (vstat != ostat) {
      if (vstat < ostat) {
        label[ostat] = vstat;
      } else {
        label[vstat] = ostat;
      }
    }
  }
  for (int v = 0; v < cnt; v++) {
    int next, vstat = label[v];
    while (vstat > (next = label[vstat])) {
      vstat = next;
    }
    label[v] = vstat;
  }

  // determine CC sizes
  int* const size = new int [cnt];
  for (int v = 0; v < cnt; v++) {
    size[v] = 0;
  }
  for (int v = 0; v < cnt; v++) {
    size[label[v]]++;
  }

  // find largest CC
  int hi = 0;
  for (int v = 1; v < cnt; v++) {
    if (size[hi] < size[v]) hi = v;
  }

  // keep if in largest CC and convert graph into set format
  Graph g;
  g.origID = new int [cnt];  // upper bound on size
  int nodes = 0, edges = 0;
  std::map<int, int> newmap;  // map node IDs to contiguous IDs
  std::set<std::pair<int, int>>* const node = new std::set<std::pair<int, int>> [cnt];  // upper bound on size
  for (auto ele: set3) {
    const int src = std::get<0>(ele);
    const int dst = std::get<1>(ele);
    const int wei = std::get<2>(ele);
    if (label[map[src]] == hi) {  // in largest CC
      if (newmap.find(src) == newmap.end()) {
        g.origID[nodes] = src;
        newmap[src] = nodes++;
      }
      if (newmap.find(dst) == newmap.end()) {
        g.origID[nodes] = dst;
        newmap[dst] = nodes++;
      }
      node[newmap[src]].insert(std::make_pair(newmap[dst], wei));
      node[newmap[dst]].insert(std::make_pair(newmap[src], wei));
      edges += 2;
    }
  }
  if (verify) {
    if (nodes > cnt) {printf("ERROR: too many nodes\n"); exit(-1);}
    if (edges > (int)set3.size() * 2) {printf("ERROR: too many edges\n"); exit(-1);}
  }

  // create graph in CSR format
  g.nodes = nodes;
  g.edges = edges;
  g.nindex = new int [g.nodes + 1];
  g.nlist = new int [g.edges];
  g.eweight = new bool [g.edges];
  int acc = 0;
  for (int v = 0; v < g.nodes; v++) {
    g.nindex[v] = acc;
    for (auto ele: node[v]) {
      const int dst = ele.first;
      const int wei = ele.second;
      g.nlist[acc] = dst;
      g.eweight[acc] = (wei == -1);  // true weight == negative edge
      acc++;
    }
  }
  g.nindex[g.nodes] = acc;
  if (verify) {
    if (acc != edges) {printf("ERROR: wrong edge count in final graph\n"); exit(-1);}
  }

  delete [] label;
  delete [] size;
  delete [] node;

  return g;
}

static __global__ void init(const int edges, const int nodes, int* const nlist, int* const inTree, int* const negCnt)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;

  for (int j = from; j < edges; j += incr) {
    nlist[j] <<= 1;  // make room for 1-bit tree membership flag
  }

  // zero out edge arrays
  for (int j = from; j < edges; j += incr) {
    inTree[j] = 0;
    negCnt[j] = 0;
  }
}

// runs before each new tree run
static __global__ void init2(const int edges, const int nodes, const int root, int* const nlist, int* const queue, int* const tail, int* const time, bool* const pathsign, int* const minusCnt, int* const parent)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;
  // initialize
  for (int j = from; j < edges; j += incr) nlist[j] &= ~1;
  for (int j = from; j < nodes; j += incr) parent[j] = (root == j) ? (INT_MAX & ~3) : -1;
  for (int j = from; j < nodes; j += incr) time[j] = (root == j) ? 0 : -1;
  for (int j = from; j < nodes; j += incr) pathsign[j] = false;  // pathsign[root] starts positive
  if (from == 0) {
    queue[0] = root;
    *tail = 1;
    *minusCnt = 0;
  }
}

struct GPUTimer
{
  cudaEvent_t beg, end;
  GPUTimer() {cudaEventCreate(&beg);  cudaEventCreate(&end);}
  ~GPUTimer() {cudaEventDestroy(beg);  cudaEventDestroy(end);}
  void start() {cudaEventRecord(beg, 0);}
  float stop() {cudaEventRecord(end, 0);  cudaEventSynchronize(end);  float ms;  cudaEventElapsedTime(&ms, beg, end);  return 0.001f * ms;}
};

// labels vertices with the signs of paths from root
// top-down tree traversal
static __global__ void calcPathSigns(const int* const __restrict__ nindex, const int* const __restrict__ nlist, const bool* const __restrict__ eweight, bool* const __restrict__ pathsign, const int* const __restrict__ queue, int* const __restrict__ time, int start, int end)
{
  const int from = (threadIdx.x + blockIdx.x * ThreadsPerBlock) / warpsize;
  const int incr = (gridDim.x * ThreadsPerBlock) / warpsize;
  const int lane = threadIdx.x % warpsize;
  
  for (int i = start + from; i < end; i += incr) {
    const int src = queue[i];
    const int src_pathsign = pathsign[src];
    for (int e = nindex[src] + lane; e < nindex[src + 1]; e += warpsize) {
      const int e_val = nlist[e];
      if (e_val & 1) {  // if edge is in tree
        const int dst = e_val >> 1;
        if (time[dst] == -1) {  // if child is unvisited
          pathsign[dst] = src_pathsign != eweight[e];  // label child (pathsign[src] * sign[e])
          time[dst] = 1;  // set child as visited
        }
      }
    }
    __syncwarp();
  }
}

static __global__ void findMajority(const int nodes, const bool* const pathsign, int* const minusCnt)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;
  
  int my_minusCnt = 0;
  for (int v = from; v < nodes; v += incr) {
    my_minusCnt += pathsign[v];  // true == negative path sign
  }
  atomicAdd(minusCnt, my_minusCnt);
}

static __global__ void incrementMajorityNodes(const int nodes, int* const nodeInMajority, const bool* const pathsign, bool majority)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;
  // increment nodes in majority
  for (int v = from; v < nodes; v += incr) {
    nodeInMajority[v] += (pathsign[v] == majority) * 2;  // will be divided by 2 later, equivalent to adding 1.0
  }
}

static __global__ void incrementMajorityTieNodes(const int nodes, int* const nodeInMajority)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;
  // tie, increment all nodes by half
  for (int v = from; v < nodes; v += incr) {
    nodeInMajority[v] += 1;  // will be divided by 2 later, equivalent to adding 0.5
  }
}

// process all fundamental cycles (one exists per non-tree edge)
static __global__ void processCycles(const int edges, const int* const __restrict__ sp, const int* const __restrict__ nlist, const bool* const  __restrict__ pathsign, int* const  __restrict__ negCnt)
{
  const int e = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  if (e < edges && !(nlist[e] & 1)) {  // if edge is NOT in tree
    const int src = sp[e];
    const int dst = nlist[e] >> 1;
    if (dst > src) {  // only process edges in one direction
      const bool sign = (pathsign[src] != pathsign[dst]);  // new edge sign = path to src * path to dst
      
      if (sign) {  // if this non-tree edge is negative in the balanced cycle
        negCnt[e]++;
      }
    }
  }
}

// generate random BFS tree
static __global__ void generateSpanningTree(const int nodes, const int* const __restrict__ nindex, const int* const __restrict__ nlist, const int seed, volatile int* const __restrict__ parent, int* const __restrict__ queue, const int level, int* const __restrict__ tail, int start, int end)
{
  const int from = (threadIdx.x + blockIdx.x * ThreadsPerBlock) / warpsize;
  const int incr = (gridDim.x * ThreadsPerBlock) / warpsize;
  const int lane = threadIdx.x % warpsize;
  const int seed2 = seed * seed + seed;
  const int bit = (level & 1) | 2;

  for (int i = start + from; i < end; i += incr) {
    const int node = queue[i];
    const int me = (node << 2) | bit;
    if (lane == 0) atomicAnd((int*)&parent[node], ~3);
    for (int j = nindex[node + 1] - 1 - lane; j >= nindex[node]; j -= warpsize) {  // reverse order on purpose
      const int neighbor = nlist[j] >> 1;
      const int seed3 = neighbor ^ seed2;
      const int hash_me = hash(me ^ seed3);
      int val, hash_val;
      do {  // pick parent deterministically
          val = parent[neighbor];
          hash_val = hash(val ^ seed3);
        } while (((val < 0) || (((val & 3) == bit) && ((hash_val < hash_me) || ((hash_val == hash_me) && (val < me)))))
          && (atomicCAS((int*)&parent[neighbor], val, me) != val));
        if (val < 0) {
          val = atomicAdd(tail, 1);
          queue[val] = neighbor;
      }
    }
    __syncwarp();
  }
}

static __global__ void verify_generateSpanningTree(const int nodes, const int edges, const int* const nindex, const int* const nlist, const int seed, const int* const parent, const int level, const int* const tail, int end)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;
  if (end != *tail) {printf("ERROR: head mismatch\n"); asm("trap;");}
  if (*tail != nodes) {printf("ERROR: tail mismatch tail %d nodes %d \n", *tail, nodes); asm("trap;");}
  for (int i = from; i < nodes; i += incr) {
    if (parent[i] < 0) {printf("ERROR: found unvisited node %d\n", i); asm("trap;");}
  }
}

// mark edges in the tree
static __global__ void markTreeEdges(const int edges, const int* const __restrict__ nindex, int* const __restrict__ nlist, const int* const __restrict__ sp, const int* const __restrict__ parent, int* const __restrict__ inTree, const bool* const __restrict__ eweight, int* const  __restrict__ negCnt)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;

  for (int e = from; e < edges; e += incr) {
    const int src = sp[e];
    const int dst = nlist[e] >> 1;
    const int src_p = parent[src] >> 2;
    const int dst_p = parent[dst] >> 2;
    if ((src_p == dst) || (dst_p == src)) {
      nlist[e] |= 1; //mark edge as in tree
      inTree[e]++;
      if (eweight[e]) { // if tree edge is negative, mark it
        negCnt[e]++;
      }
    }
  }
}

int main(int argc, char* argv[])
{
  printf("ECL-SGB signed graph balancing code for signed social network graphs (%s)\n", __FILE__);
  printf("Copyright 2026 Texas State University\n");

  // process command line and read input
  if (argc != 4) {printf("\nUSAGE: %s input_file_name iteration_count output_file_name\n", argv[0]); exit(-1);}
  
  cudaSetDevice(Device);
  
  GPUTimer timer;
  timer.start();
  printf("verification: %s\n", verify ? "on" : "off");
  printf("input: %s\n", argv[1]);
  Graph g = readGraph(argv[1]);
  printf("nodes: %d\n", g.nodes);
  printf("edges: %d\n", g.edges);
  const int iterations = atoi(argv[2]);  // number of trees to sample
  printf("input reading time: %.6f s\n", timer.stop());
  
  // allocate all memory
  int* const border = new int [g.nodes + 2];
  int* const inTree = new int [g.edges];  // how often edge was in tree
  int* const negCnt = new int [g.edges];  // how often edge was negative
  int* const nodeInMajority = new int [g.nodes];  // node status: how often node was in largest bipartition, times 2
  int* const sp = new int [g.edges];  // starting points of edges
  int* const roots = new int [g.nodes];  // tree roots

  // create starting point array
  for (int i = 0; i < g.nodes; i++) {
    for (int j = g.nindex[i]; j < g.nindex[i + 1]; j++) {
      sp[j] = i;
    }
  }
  
  // GPU code
  cudaDeviceProp deviceProp;
  cudaGetDeviceProperties(&deviceProp, Device);
  if ((deviceProp.major == 9999) && (deviceProp.minor == 9999)) {fprintf(stderr, "ERROR: there is no CUDA capable device\n\n");  exit(-1);}
  const int SMs = deviceProp.multiProcessorCount;
  const int mTpSM = deviceProp.maxThreadsPerMultiProcessor;
  printf("gpu: %s with %d SMs and %d mTpSM (%.1f MHz and %.1f MHz)\n", deviceProp.name, SMs, mTpSM, deviceProp.clockRate * 0.001, deviceProp.memoryClockRate * 0.001);

  Graph d_g = g;
  int* d_queue;
  int* d_tail;
  int* d_inTree;
  int* d_negCnt;
  int* d_time;  // if the node was visited this iteration (for calcPathSigns)
  bool* d_pathsign;
  int* d_minusCnt;
  int* d_nodeInMajority;  // node status: how often each node was in largest bipartition, times 2
  int* d_sp;  // starting points of edges
  int* d_parent;  // parent node in tree
  
  if (cudaSuccess != cudaMalloc((void **)&d_sp, sizeof(int) * g.edges)) {fprintf(stderr, "ERROR: could not allocate d_sp\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_g.eweight, sizeof(bool) * g.edges)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_g.nindex, sizeof(int) * (g.nodes + 1))) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_g.nlist, sizeof(int) * g.edges)) {fprintf(stderr, "ERROR: could not allocate memory\n");}
  if (cudaSuccess != cudaMalloc((void **)&d_inTree, sizeof(int) * g.edges)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_negCnt, sizeof(int) * g.edges)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_queue, sizeof(int) * g.nodes)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_tail, sizeof(int))) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_time, sizeof(int) * g.nodes)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_pathsign, sizeof(bool) * g.nodes)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_minusCnt, sizeof(int))) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_nodeInMajority, sizeof(int) * g.nodes)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_parent, sizeof(int) * g.nodes)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}

  // copy graph to device
  if (cudaSuccess != cudaMemcpy(d_g.nindex, g.nindex, sizeof(int) * (g.nodes + 1), cudaMemcpyHostToDevice)) {fprintf(stderr, "ERROR: copying g.nindex to device failed\n"); exit(-1);}
  if (cudaSuccess != cudaMemcpy(d_g.nlist, g.nlist, sizeof(int) * g.edges, cudaMemcpyHostToDevice)) {fprintf(stderr, "ERROR: copying g.nlist to device failed\n"); exit(-1);}
  if (cudaSuccess != cudaMemcpy(d_g.eweight, g.eweight, sizeof(bool) * g.edges, cudaMemcpyHostToDevice)) {fprintf(stderr, "ERROR: copying g.eweight to device failed\n"); exit(-1);}
  if (cudaSuccess != cudaMemcpy(d_sp, sp, sizeof(int) * g.edges, cudaMemcpyHostToDevice)) {fprintf(stderr, "ERROR: copying sp to device failed\n"); exit(-1);}

  const int blocks = SMs * mTpSM / ThreadsPerBlock;
  float treeGenTime = 0.0;
  float marktreeedgesTime = 0.0;
  float calcpathsignsTime = 0.0;
  float incrementmajorityTime = 0.0;
  float processcyclesTime = 0.0;
  timer.start();
  
  // sort roots by degree, descending
  for (int i = 0; i < g.nodes; i++) roots[i] = i;
  std::partial_sort(roots, roots + std::min(iterations, g.nodes), roots + g.nodes, [&](int a, int b) {
    return (g.nindex[a + 1] - g.nindex[a]) > (g.nindex[b + 1] - g.nindex[b]);
  });
  
  if (cudaSuccess != cudaMemset(d_nodeInMajority, 0, g.nodes * sizeof(int))) fprintf(stderr, "ERROR: initializing metric to 0 failed\n");

  init<<<blocks, ThreadsPerBlock>>>(g.edges, g.nodes, d_g.nlist, d_inTree, d_negCnt);
  CheckCuda(__LINE__);
  printf("init time:  %.6f s\n", timer.stop());
  
  GPUTimer overall;
  overall.start();
  
  int min_d = INT_MAX;
  int max_d = INT_MIN;
  int sum_d = 0;
  double avg_d = 0;
  for (int iter = 0; iter < iterations; iter++) {
    timer.start();
    
    const int seed = iter + 17;
    const int root = roots[iter % g.nodes];
    
    init2<<<blocks, ThreadsPerBlock>>>(g.edges, g.nodes, root, d_g.nlist, d_queue, d_tail, d_time, d_pathsign, d_minusCnt, d_parent);
    
    // generate a random spanning BFS tree
    int level = 0;
    int tail = 1;
    border[0] = 0;
    border[1] = tail;
    while (border[level + 1] < g.nodes) {
      generateSpanningTree<<<blocks, ThreadsPerBlock>>>(g.nodes, d_g.nindex, d_g.nlist, seed, d_parent, d_queue, level, d_tail, border[level],  border[level + 1]);
      if (cudaSuccess != cudaMemcpy(&tail, d_tail, sizeof(int), cudaMemcpyDeviceToHost)) {fprintf(stderr, "ERROR: copying to host failed \n"); exit(-1);}
      level++;
      border[level + 1] = tail;
    }
    const int levels = level + 1;
    
    if (verify) verify_generateSpanningTree<<<blocks, ThreadsPerBlock>>>(g.nodes, g.edges, d_g.nindex, d_g.nlist, iter, d_parent, level, d_tail, border[level + 1]);
    
    treeGenTime += timer.stop(); timer.start();
    
    markTreeEdges<<<blocks, ThreadsPerBlock>>>(g.edges, d_g.nindex, d_g.nlist, d_sp, d_parent, d_inTree, d_g.eweight, d_negCnt);
    
    marktreeedgesTime += timer.stop(); timer.start();
    
    // calculate path signs from root in top-down traversal
    for (int path_level = 0; path_level < levels; path_level++) {
      calcPathSigns<<<blocks, ThreadsPerBlock>>>(d_g.nindex, d_g.nlist, d_g.eweight, d_pathsign, d_queue, d_time, border[path_level], border[path_level + 1]);
    }
    
    calcpathsignsTime += timer.stop(); timer.start();
    
    // min, max and avg depth of the trees
    sum_d += level;
    if (level < min_d) min_d = level;
    if (level > max_d) max_d = level;
    
    // find majority set
    findMajority<<<blocks, ThreadsPerBlock>>>(g.nodes, d_pathsign, d_minusCnt);
    int minusCnt;
    if (cudaSuccess != cudaMemcpy(&minusCnt, d_minusCnt, sizeof(int), cudaMemcpyDeviceToHost)) fprintf(stderr, "ERROR: copying of minusCnt from device failed\n");
    const int plusCnt = g.nodes - minusCnt;
    
    if (plusCnt > minusCnt) {
      incrementMajorityNodes<<<blocks, ThreadsPerBlock>>>(g.nodes, d_nodeInMajority, d_pathsign, false);  // false == positive pathsign
    } else if (minusCnt > plusCnt) {
      incrementMajorityNodes<<<blocks, ThreadsPerBlock>>>(g.nodes, d_nodeInMajority, d_pathsign, true);  // true == negative pathsign
    } else if (minusCnt == plusCnt) {
      incrementMajorityTieNodes<<<blocks, ThreadsPerBlock>>>(g.nodes, d_nodeInMajority);
    }
    incrementmajorityTime += timer.stop(); timer.start();

    // process cycles
    processCycles<<<((g.edges + ThreadsPerBlock - 1) / ThreadsPerBlock), ThreadsPerBlock>>>(g.edges, d_sp, d_g.nlist, d_pathsign, d_negCnt);
    
    processcyclesTime += timer.stop();
  }
  const float overall_time = overall.stop();
  
  avg_d = sum_d/iterations;
  if (cudaSuccess != cudaMemcpy(inTree, d_inTree, sizeof(int) * g.edges, cudaMemcpyDeviceToHost)) fprintf(stderr, "ERROR: copying d_inTree to host failed\n");
  if (cudaSuccess != cudaMemcpy(negCnt, d_negCnt, sizeof(int) * g.edges, cudaMemcpyDeviceToHost)) fprintf(stderr, "ERROR: copying d_negCnt to host failed\n");
  if (cudaSuccess != cudaMemcpy(nodeInMajority, d_nodeInMajority, sizeof(int) * g.nodes, cudaMemcpyDeviceToHost)) fprintf(stderr, "ERROR: copying d_nodeInMajority to host failed\n");
  
  // print results
  if (verify) {
    printf("number of trees %d", iterations);
    printf("\n Min depth of the trees %d\n Avg depth of the trees %.4f\n Max depth of the trees %d\n", min_d, avg_d, max_d);
    for (int i = 0; i < g.nodes; i++) {
      if (i >= 10) break;  // to limit output
      printf("%6d: %6.1f   (%5.1f%%)  %d\n", i, (nodeInMajority[i] / 2.0), ((100.0 * nodeInMajority[i]) / (2.0 * iterations)), g.origID[i]);
    }
  }
  // output results to file
  std::string node_filename = argv[3];
  node_filename.append(".node-out.csv");
  std::string edge_filename = argv[3];
  edge_filename.append(".edge-out.csv");
  
  FILE *node_f = fopen(node_filename.c_str(), "wt");
  fprintf(node_f, "original node ID, percentage node was in agreeable majority\n");
  for (int i = 0; i < g.nodes; i++) {
    double v_status = ((double)nodeInMajority[i] / (2.0 * iterations));  // how often node is in majority (divided by 2 to allow +0.5 for ties in integer format)
    fprintf(node_f, "%d,%.2f\n", g.origID[i], v_status * 100.0);
  }
  fclose(node_f);
  
  FILE *edge_f = fopen(edge_filename.c_str(), "wt");
  fprintf(edge_f, "source node ID, destination node ID, percentage edge was in tree, percentage edge was negative\n");
  for (int v = 0; v < g.nodes; v++) {
    for (int j = g.nindex[v]; j < g.nindex[v + 1]; j++) {
      const int n = g.nlist[j];
      if (v < n) {  // only print one copy of each edge (other copy does not have correct negCnt)
        double inTreePercent = ((double)inTree[j] / iterations);
        double negativePercent = ((double)negCnt[j] / iterations);
        fprintf(edge_f, "%d,%d,%.2f,%.2f\n", g.origID[v], g.origID[n], inTreePercent * 100.0, negativePercent * 100.0);
      }
    }
  }
  fclose(edge_f);
  
  freeGraph(g);
  delete [] roots;
  delete [] border;
  delete [] inTree;
  delete [] negCnt;
  delete [] sp;
  delete [] nodeInMajority;
  cudaFree(d_sp);
  cudaFree(d_g.eweight);
  cudaFree(d_g.nindex);
  cudaFree(d_g.nlist);
  cudaFree(d_inTree);
  cudaFree(d_negCnt);
  cudaFree(d_queue);
  cudaFree(d_tail);
  cudaFree(d_time);
  cudaFree(d_pathsign);
  cudaFree(d_minusCnt);
  cudaFree(d_nodeInMajority);
  cudaFree(d_parent);
  
  //output timings
  printf("total time spent generating trees: %.6f s\n", treeGenTime);
  printf("total time spent marking tree edges: %.6f s\n", marktreeedgesTime);
  printf("total time spent calculating path signs: %.6f s\n", calcpathsignsTime);
  printf("total time spent processing cycles: %.6f s\n", processcyclesTime);
  printf("total time spent finding majority (Harary Cut): %.6f s\n", incrementmajorityTime);
  
  printf("overall runtime after init: %.6f s\n", overall_time);
}