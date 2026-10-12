/*
graphB+ balancing algorithm for signed social network graphs

Copyright (c) 2021, Texas State University
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

Authors: Ghadeer Alabandi and Martin Burtscher

URL: The latest version of this code is available at
https://cs.txstate.edu/~burtscher/research/graphBplus/.
*/


#include <cstdio>
#include <climits>
#include <algorithm>
#include <set>
#include <map>
#include <sys/time.h>

static const bool verify = false;  // set to false for better performance
static const int Device = 0;
static const int ThreadsPerBlock = 512;
static const int warpsize = 32;
static const unsigned int mask = 0xffffffff;
static __device__ unsigned long long hi = 0;
static __device__ int wSize = 0;

struct EdgeInfo {
  int beg;  // beginning of range (shifted by 1) | is range inverted or not
  int end;  // end of range (shifted by 1) | plus or minus (1 = minus, 0 = plus or zero)
};

struct Graph {
  int nodes;
  int edges;
  int* nindex;  // first CSR array
  int* nlist;  // second CSR array
  int* eweight;  // edge weights (-1, 0, 1)
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

template <typename T>
static __device__ void swap(T& a, T& b)
{
  T c = a;
  a = b;
  b = c;
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
  g.eweight = new int [g.edges];
  int acc = 0;
  for (int v = 0; v < g.nodes; v++) {
    g.nindex[v] = acc;
    for (auto ele: node[v]) {
      const int dst = ele.first;
      const int wei = ele.second;
      g.nlist[acc] = dst;
      g.eweight[acc] = wei;
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

// source of hash function: https://stackoverflow.com/questions/664014/what-integer-hash-function-are-good-that-accepts-an-integer-hash-key
static __device__ __host__ unsigned int hash(unsigned int val)
{
  val = ((val >> 16) ^ val) * 0x45d9f3b;
  val = ((val >> 16) ^ val) * 0x45d9f3b;
  return (val >> 16) ^ val;
}

static __global__ void init(const int edges, const int nodes, int* const nlist, int* const eweight, int* const inCC, EdgeInfo* const einfo, int* const inTree, int* const negCnt)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;

  for (int j = from; j < edges; j += incr) {
    nlist[j] <<= 1;
  }

  // zero out inCC
  for (int v = from; v < nodes; v += incr) {
    inCC[v] = 0;
  }

  // set minus if graph weight is -1
  for (int j = from; j < edges; j += incr) {
    einfo[j].end = (eweight[j] == -1) ? 1 : 0;
  }

  // zero out inTree and negCnt
  for (int j = from; j < edges; j += incr) {
    inTree[j] = 0;
    negCnt[j] = 0;
  }
}


static __global__ void init2(const int edges, const int nodes, const int root, int* const nlist, int* const parent, int* const queue, int* const label, int* const tail)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;
  // initialize
  for (int j = from; j < edges; j += incr) nlist[j] &= ~1;
  for (int j = from; j < nodes; j += incr) parent[j] = (root == j) ? (INT_MAX & ~3) : -1;
  for (int j = from; j < nodes; j += incr) label[j] = 1;
  if (from == 0) {
    queue[0] = root;
    *tail = 1;
  }
}

static __global__ void generateSpanningTree(const int nodes, const int* const __restrict__ nindex, const int* const __restrict__ nlist, const int seed, EdgeInfo* const einfo, volatile int* const parent, int* const queue, const int level, int* const tail, int start, int end)
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
        } while (((val < 0) || (((val & 3) == bit) && ((hash_val < hash_me) || ((hash_val == hash_me) && (val < me))))) && (atomicCAS((int*)&parent[neighbor], val, me) != val));
        if (val < 0) {
          val = atomicAdd(tail, 1);
          queue[val] = neighbor;
      }
    }
    __syncwarp();
  }
}

static __global__ void verfiy_generateSpanningTree(const int nodes, const int edges, const int* const nindex, const int* const nlist, const int seed, const int* const parent, const int level, const int* const tail, int end)
{
  if (verify) {
    const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
    const int incr = gridDim.x * ThreadsPerBlock;
    if (end != *tail) {printf("ERROR: head mismatch\n"); asm("trap;");}
    if (*tail != nodes) {printf("ERROR: tail mismatch tail %d nodes %d \n", *tail, nodes); asm("trap;");}
    for (int i = from; i < nodes; i += incr) {
      if (parent[i] < 0) {printf("ERROR: found unvisited node %d\n", i); asm("trap;");}
    }
  }
}

static __global__ void rootcount(const int* const parent, const int* const queue, int* const __restrict__ label, const int level, int start, int end)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;
  // bottom up: push counts
  for (int i = start + from; i < end; i += incr) {
    const int node = queue[i];
    atomicAdd(&label[parent[node] >> 2], label[node]);
  }
}

static __global__ void treelabel(const int nodes, const int* const __restrict__ nindex, volatile int* const __restrict__ nlist, EdgeInfo* const __restrict__ einfo, volatile int* const __restrict__ inTree, volatile int* const __restrict__ negCnt, const int* const __restrict__ parent, const int* const __restrict__ queue, int* const __restrict__ label, const int level, int start, int end)
{
  const int from = (threadIdx.x + blockIdx.x * ThreadsPerBlock) / warpsize;
  const int incr = (gridDim.x * ThreadsPerBlock) / warpsize;
  const int lane = threadIdx.x % warpsize;
  //cuv
  // top down: label tree + set nlist flag + set edge info + move tree nodes to front + make parent edge first in list
  for (int i = start + from; i < end; i += incr) {
    const int node = queue[i];
    const int par = parent[node] >> 2;
    const int nodelabel = label[node];
    const int beg = nindex[node];
    const int end = nindex[node + 1];

    // set nlist flag + set edge info
    int lbl = (nodelabel >> 1) + 1;
    for (int j = beg + lane; __any_sync(mask, j < end); j += warpsize) {
      int lblinc = 0;
      int neighbor = -1;
      bool cond = false;
      if (j < end) {
        neighbor = nlist[j] >> 1;
        cond = (neighbor != par) && ((parent[neighbor] >> 2) == node);
        if (cond) {
          lblinc = label[neighbor];
        }
      }
      const int currcount = lblinc;
      for (int d = 1; d < 32; d *= 2) {
        const int tmp = __shfl_up_sync(mask, lblinc, d);
        if (lane >= d) lblinc += tmp;
      }
      lbl += lblinc;

      if (cond) {
        const int lblval = (lbl - currcount) << 1;
        label[neighbor] = lblval;
        einfo[j].beg = lblval;
        einfo[j].end = (einfo[j].end & 1) | ((lbl - 1) << 1);
        nlist[j] |= 1;  // child edge is in tree
      }
      lbl = __shfl_sync(mask, lbl, 31);
    }

    // move tree nodes to front
    const int len = end - beg;
    if (len > 0) {
      enum {none, some, left, right};
      if (len <= warpsize) {
        const int src = beg + lane;
        int b, e, in, neg,  n, state = none;
        if (lane < len) {
          b = einfo[src].beg;
          e = einfo[src].end;
          in = inTree[src];
          neg = negCnt[src];
          n = nlist[src];
          const int neighbor = n >> 1;
          state = ((neighbor != par) && ((parent[neighbor] >> 2) == node)) ? left : right;  // partitioning condition
        }
        const int ball = __ballot_sync(mask, state == left);
        const int balr = __ballot_sync(mask, state == right);
        const int pfsl = __popc(ball & ~(-1 << lane));
        const int pfsr = __popc(balr & ~(-1 << lane));
        const int pos = beg + ((state == right) ? (len - 1 - pfsr) : pfsl);
        if (state != none) {
          einfo[pos].beg = b;
          einfo[pos].end = e;
          inTree[pos] = in;
          negCnt[pos] = neg;
          nlist[pos] = n;
        }
      } else {
        int lp = beg;
        int rp = end - 1;
        int state = some;
        int read = beg + min(warpsize, len);
        int src = beg + lane;
        int b = einfo[src].beg;
        int e = einfo[src].end;
        int n = nlist[src];
        int in = inTree[src];
        int neg = negCnt[src];

        do {
          if (state == some) {
            const int neighbor = n >> 1;
            state = ((neighbor != par) && ((parent[neighbor] >> 2) == node)) ? left : right;  // partitioning condition
          }
          const int ball = __ballot_sync(mask, state == left);
          const int pfsl = __popc(ball & ~(-1 << lane));
          if (state == left) {
            int oldb, olde, oldin, oldneg, oldn;
            const int pos = lp + pfsl;
            if (pos >= read) {
              oldb = einfo[pos].beg;
              olde = einfo[pos].end;
              oldin = inTree[pos];
              oldneg = negCnt[pos];
              oldn = nlist[pos];
            }
            einfo[pos].beg = b;
            einfo[pos].end = e;
            inTree[pos] = in;
            negCnt[pos] = neg;
            nlist[pos] = n;
            b = oldb;
            e = olde;
            in = oldin;
            neg = oldneg;
            n = oldn;
            state = (pos < read) ? none : some;
          }
          lp += __popc(ball);
          read = max(read, lp);
          const int balr = __ballot_sync(mask, state == right);
          const int pfsr = __popc(balr & ~(-1 << lane));
          if (state == right) {
            int oldb, olde, oldin, oldneg, oldn;
            const int pos = rp - pfsr;
            if (pos >= read) {
              oldb = einfo[pos].beg;
              olde = einfo[pos].end;
              oldin = inTree[pos];
              oldneg = negCnt[pos];
              oldn = nlist[pos];
            }
            einfo[pos].beg = b;
            einfo[pos].end = e;
            inTree[pos] = in;
            negCnt[pos] = neg;
            nlist[pos] = n;
            b = oldb;
            e = olde;
            in = oldin;
            neg = oldneg;
            n = oldn;
            state = (pos < read) ? none : some;
          }
          rp -= __popc(balr);
          if (read <= rp) {
            const int bal = __ballot_sync(mask, state == none);
            const int pfs = __popc(bal & ~(-1 << lane));
            if (state == none) {
              const int pos = read + pfs;
              if (pos <= rp) {
                b = einfo[pos].beg;
                e = einfo[pos].end;
                in = inTree[pos];
                neg = negCnt[pos];
                n = nlist[pos];
                state = some;
              }
            }
            read += __popc(bal);  // may be too high but okay
          }
        } while (__any_sync(mask, state == some));
      }
    }

    //find paredge here
    int paredge = -1;
    for (int j = beg + lane; __any_sync(mask, j < end); j += warpsize) {
      if (j < end) {
        const int neighbor = nlist[j] >> 1;
        if (neighbor == par) {
          paredge = j;
        }
      }
      if (__any_sync(mask, paredge >= 0)) break;
    }
    int pos = -1;
    for (int j = beg + lane; __any_sync(mask, j < end); j += warpsize) {
      if (j < end) {
        const int neighbor = nlist[j] >> 1;
        if (((parent[neighbor] >> 2) != node)) {
          pos = j;
        }
      }
      if (__any_sync(mask, pos >= 0)) break;
    }
    unsigned int bal = __ballot_sync(mask, pos >= 0);
    const int lid = __ffs(bal) - 1;
    pos = __shfl_sync(mask, pos, lid);
    if (paredge >= 0) {  // only one thread per warp
      einfo[paredge].beg = nodelabel | 1;
      einfo[paredge].end = (einfo[paredge].end & 1) | ((lbl - 1) << 1);
      nlist[paredge] |= 1;
      if (paredge != beg) {
        if (paredge != pos) {
          swap(nlist[pos], nlist[paredge]);
          swap(einfo[pos], einfo[paredge]);
          swap(inTree[pos], inTree[paredge]);
          swap(negCnt[pos], negCnt[paredge]);
          paredge = pos;
        }
        if (paredge != beg) {
          swap(nlist[beg], nlist[paredge]);
          swap(einfo[beg], einfo[paredge]);
          swap(inTree[beg], inTree[paredge]);
          swap(negCnt[beg], negCnt[paredge]);
        }
      }
    }
    __syncwarp();

    if (verify && (lane == 0)) {
      if (i == 0) {
        if (lbl != nodes) {printf("ERROR: lbl mismatch, lbl %d nodes %d\n", lbl, nodes); asm("trap;");}
      }
      int j = beg;
      while ((j < end) && (nlist[j] & 1)) j++;
      while ((j < end) && !(nlist[j] & 1)) j++;
      if (j != end) {printf("ERROR: not moved %d %d %d\n", beg, j, end); asm("trap;");}
    }
  }
}

static __global__ void inTreeUpdate(const int edges, const int* const __restrict__ nlist, volatile int* const __restrict__ inTree)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;
  // update inTree
  for (int j = from; j < edges; j += incr) {
    inTree[j] += nlist[j] & 1;
  }
}

static __global__ void processCycles(const int nodes, const int* const __restrict__ nindex, const int* const __restrict__ nlist, const int* const __restrict__ label, const EdgeInfo* const __restrict__ einfo, bool* const  __restrict__ minus)
{
  const int from = (threadIdx.x + blockIdx.x * ThreadsPerBlock) / warpsize;
  const int incr = (gridDim.x * ThreadsPerBlock) / warpsize;
  const int lane = threadIdx.x % warpsize;
  for (int i = from; i < nodes; i += incr) {
    const int target0 = label[i];
    const int target1 = target0 | 1;
    int j = nindex[i + 1] - 1 - lane;
    while ((j >= nindex[i]) && !(nlist[j] & 1)) {
      int curr = nlist[j] >> 1;
      if (curr > i) {  // only process edges in one direction
        int sum = 0;
        while (label[curr] != target0) {
          int k = nindex[curr];
          while ((einfo[k].beg & 1) == ((einfo[k].beg <= target1) && (target0 <= einfo[k].end))) k++;
          if (verify) {
            if ((k >= nindex[curr + 1]) || !(nlist[k] & 1)) {printf("ERROR: couldn't find path\n"); asm("trap;");}
          }
          sum += einfo[k].end & 1;
          curr = nlist[k] >> 1;
        }
        minus[j] = sum & 1;
      }
      j -= warpsize;
    }
   __syncwarp();
  }
}

static __global__ void initMinus(const int edges, const int nodes, const int* const __restrict__ nindex, const int* const __restrict__ nlist, const EdgeInfo* const einfo, bool* const minus)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;
  // set minus info to true
  for (int j = from; j < edges; j += incr) {
    minus[j] = true;
  }
  // copy minus info of tree edges
  for (int i = from; i < nodes; i += incr) {
    int j = nindex[i];
    while ((j < nindex[i + 1]) && (nlist[j] & 1)) {
      minus[j] = einfo[j].end & 1;
      j++;
    }
  }
}

static __global__ void init3(const int nodes, const int* const __restrict__ nidx, const int* const __restrict__ nlist, int* const __restrict__ label, int* const __restrict__ count)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;

  for (int v = from; v < nodes; v += incr) {
    label[v] = v;
  }

  for (int v = from; v < nodes; v += incr) {
    count[v] = 0;
  }

}

static __global__ void compute1(const int nodes, const int* const __restrict__ nidx, const int* const __restrict__ nlist, int* const __restrict__ label, const bool* const __restrict__ minus, int* const __restrict__ negCnt)
{
  const int from = (threadIdx.x + blockIdx.x * ThreadsPerBlock) / warpsize;
  const int incr = (gridDim.x * ThreadsPerBlock) / warpsize;
  const int lane = threadIdx.x % warpsize;
  for (int v = from; v < nodes; v += incr) {
    const int beg = nidx[v];
    const int end = nidx[v + 1];
    int vstat = representative(v, label);
    for (int j = beg + lane; j < end; j += warpsize) {
      const int nli = nlist[j] >> 1;
      if (minus[j]) {
        negCnt[j]++;
      } else {
        int ostat = representative(nli, label);
        bool repeat;
        do {
          repeat = false;
          if (vstat != ostat) {
            int ret;
            if (vstat < ostat) {
              if ((ret = atomicCAS(&label[ostat], ostat, vstat)) != ostat) {
                ostat = ret;
                repeat = true;
              }
            } else {
              if ((ret = atomicCAS(&label[vstat], vstat, ostat)) != vstat) {
                vstat = ret;
                repeat = true;
              }
            }
          }
        } while (repeat);
      }
    }
  }
}

static __global__ void flatten(const int nodes, int* const __restrict__ label)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;

  for (int v = from; v < nodes; v += incr) {
    int next, vstat = label[v];
    const int old = vstat;
    while (vstat > (next = label[vstat])) {
      vstat = next;
    }
    if (old != vstat) label[v] = vstat;
  }
}

static __global__ void ccSize(const int nodes, const int* const __restrict__ label, int* const __restrict__ count)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;
  if (from == 0)
  {
    hi = 0;
    wSize = 0;
  }
  for (int v = from; v < nodes; v += incr) {
    atomicAdd(&count[label[v]],1);;
  }
}

static __global__ void largestCC(const int nodes, const int* const __restrict__ count)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;
  for (int v = from; v < nodes; v += incr) {
    const unsigned long long d_hi = (((unsigned long long)count[v]) << 32)| v;
    if (hi < d_hi) {
      atomicMax(&hi, d_hi);
    }
  }
}

static __global__ void ccHopCount(const int nodes, const int* const __restrict__ nidx, const int* const __restrict__ nlist, const int* const __restrict__ label, int* const __restrict__ count, int* const __restrict__ ws1, int* const __restrict__ ws2)
{
  const int from = (threadIdx.x + blockIdx.x * ThreadsPerBlock) / warpsize;
  const int incr = (gridDim.x * ThreadsPerBlock) / warpsize;
  const int lane = threadIdx.x % warpsize;

  const int hi2 = hi & 0xffffffff;
  for (int v = from; v < nodes; v += incr) {
    const int lblv = label[v];
    if (lblv == v) {
      count[lblv] = (lblv == hi2) ? 0 : INT_MAX - 1;  // init count
    }
    for (int j = nidx[v] + lane; j < nidx[v + 1]; j += warpsize) {
      const int nli = nlist[j] >> 1;
      const int lbln = label[nli];
      if (lblv < lbln) {  // only one direction
        const int idx = atomicAdd(&wSize, 1); //get the return value and use it
        ws1[idx] = lblv;
        ws2[idx] = lbln;
      }
    }
  }
}

static __global__ void BellmanFord(int* const __restrict__ count, bool* const __restrict__ changed, const int* const __restrict__ ws1, const int* const __restrict__ ws2)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;
  // use Bellman Ford to compute distances
  for (int i = from; i < wSize; i += incr) {
    const int lblv = ws1[i];
    const int lbln = ws2[i];
    const int distv = count[lblv];
    const int distn = count[lbln];
    if (distv + 1 < distn) {
      count[lbln] = distv + 1;
      *changed = true;
    } else if (distn + 1 < distv) {
      count[lblv] = distn + 1;
      *changed = true;
    }
  }
}

static __global__ void incrementCC(const int nodes, const int* const __restrict__ label, const int* const __restrict__ count, int* const __restrict__ inCC)
{
  const int from = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int incr = gridDim.x * ThreadsPerBlock;
  // increment inCC if node is at even hop count from source CC
  for (int v = from; v < nodes; v += incr) {
    inCC[v] += (count[label[v]] % 2) ^ 1;
  }
}

static void CudaTest()
{
  cudaError_t e;
  cudaDeviceSynchronize();
  if (cudaSuccess != (e = cudaGetLastError())) {
    fprintf(stderr, "CUDA ERROR: %s\n", cudaGetErrorString(e));
    exit(-1);
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

int main(int argc, char* argv[])
{
  printf("graphB+ balancing code for signed social network graphs (%s)\n", __FILE__);
  printf("Copyright 2021 Texas State University\n");
  cudaSetDevice(Device);

  GPUTimer overall;
  overall.start();

  // process command line and read input
  if (argc != 4) {printf("USAGE: %s input_file_name iteration_count output_file_name\n", argv[0]); exit(-1);}
  GPUTimer timer;
  timer.start();
  printf("verification: %s\n", verify ? "on" : "off");
  printf("input: %s\n", argv[1]);
  Graph g = readGraph(argv[1]);
  printf("nodes: %d\n", g.nodes);
  printf("edges: %d\n", g.edges);
  const int iterations = atoi(argv[2]);
  printf("input time: %.6f s\n", timer.stop());

  // allocate all memory
  int* const border = new int [g.nodes + 2];  // maybe make smaller
  int* const inTree = new int [g.edges];  // how often edge was in tree
  int* const label = new int [g.nodes];  // first used as count, then as label, and finally as CC label
  int* const inCC = new int [g.nodes];  // how often node was in largest CC or at an even distance from largest CC
  int* const negCnt = new int [g.edges];  // how often edge was negative
  int* const root = new int [g.nodes];  // tree roots

  timer.start();
  for (int i = 0; i < g.nodes; i++) root[i] = i;
  std::partial_sort(root, root + std::min(iterations, g.nodes), root + g.nodes, [&](int a, int b) {
    return (g.nindex[a + 1] - g.nindex[a]) > (g.nindex[b + 1] - g.nindex[b]);
  });
  //GPU code
  cudaDeviceProp deviceProp;
  cudaGetDeviceProperties(&deviceProp, Device);
  if ((deviceProp.major == 9999) && (deviceProp.minor == 9999)) {fprintf(stderr, "ERROR: there is no CUDA capable device\n\n");  exit(-1);}
  const int SMs = deviceProp.multiProcessorCount;
  const int mTpSM = deviceProp.maxThreadsPerMultiProcessor;
  printf("gpu: %s with %d SMs and %d mTpSM (%.1f MHz and %.1f MHz)\n", deviceProp.name, SMs, mTpSM, deviceProp.clockRate * 0.001, deviceProp.memoryClockRate * 0.001);

  Graph d_g = g;
  EdgeInfo* d_einfo;
  int* d_label;
  int* d_parent;
  int* d_queue;
  int* d_border;
  int* d_tail;
  int* d_inCC;
  int* d_inTree;
  int* d_negCnt;
  int* d_ws1;
  int* d_ws2;
  int* d_wSize;
  bool* d_minus;
  bool* changed_gpu;

  if (cudaSuccess != cudaMalloc((void **)&d_g.eweight, sizeof(int) * g.edges)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_g.nindex, sizeof(int) * (g.nodes + 1))) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_g.nlist, sizeof(int) * g.edges)) {fprintf(stderr, "ERROR: could not allocate memory\n");}
  if (cudaSuccess != cudaMalloc((void **)&d_inTree, sizeof(int) * g.edges)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_negCnt, sizeof(int) * g.edges)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_inCC, sizeof(int) * g.nodes)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_einfo, sizeof(EdgeInfo) * g.edges)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_label, sizeof(int) * g.nodes)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_parent, sizeof(int) * g.nodes)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_border, sizeof(int) * (g.nodes + 2))) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_queue, sizeof(int) * g.nodes)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_tail, sizeof(int))) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_ws1, sizeof(int) * g.edges)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_ws2, sizeof(int) * g.edges)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_wSize, sizeof(int))) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&d_minus, sizeof(bool) * g.edges)) {fprintf(stderr, "ERROR: could not allocate memory\n"); exit(-1);}
  if (cudaSuccess != cudaMalloc((void **)&changed_gpu, sizeof(bool))) fprintf(stderr, "ERROR: could not allocate updated\n");

  if (cudaSuccess != cudaMemcpy(d_g.nindex, g.nindex, sizeof(int) * (g.nodes + 1), cudaMemcpyHostToDevice)) {fprintf(stderr, "ERROR: copying to device failed\n"); exit(-1);}
  if (cudaSuccess != cudaMemcpy(d_g.nlist, g.nlist, sizeof(int) * g.edges, cudaMemcpyHostToDevice)) {fprintf(stderr, "ERROR: copying to device failed\n"); exit(-1);}
  if (cudaSuccess != cudaMemcpy(d_g.eweight, g.eweight, sizeof(int) * g.edges, cudaMemcpyHostToDevice)) {fprintf(stderr, "ERROR: copying to device failed\n"); exit(-1);}

  const int blocks = SMs * mTpSM / ThreadsPerBlock;
  float graphBtime = 0.0;
  // use random pluses and minuses
  timer.start();
  init<<<blocks, ThreadsPerBlock>>>(g.edges, g.nodes, d_g.nlist, d_g.eweight, d_inCC, d_einfo, d_inTree, d_negCnt);
  CudaTest();
  //printf("init time:  %.6f s\n", timer.stop());
  timer.start();
  int min_d = INT_MAX;
  int max_d = INT_MIN;
  int sum_d = 0;
  double avg_d = 0;
  for (int iter = 0; iter < iterations; iter++) {
    // generate tree
    timer.start();
    //const int root = hash(iter + 17) % g.nodes;  // pick random root
    init2<<<blocks, ThreadsPerBlock>>>(g.edges, g.nodes, root[iter % g.nodes], d_g.nlist, d_parent, d_queue, d_label, d_tail);
    int level = 0;
    int tail = 1;
    border[0] = 0;
    border[1] = tail;
    while (border[level + 1] < g.nodes) {
      generateSpanningTree<<<blocks, ThreadsPerBlock>>>(g.nodes, d_g.nindex, d_g.nlist, iter + 17, d_einfo, d_parent, d_queue, level, d_tail, border[level],  border[level + 1]);
      if (cudaSuccess != cudaMemcpy(&tail, d_tail, sizeof(int), cudaMemcpyDeviceToHost)) {fprintf(stderr, "ERROR: copying to host failed \n"); exit(-1);}
      level++;
      border[level + 1] = tail;
    }
    //if (iter == 0) printf("spanning tree time: %.6f s\n", timer.stop());
    const int levels = level + 1;

    //min , max and avg depth of the trees
    sum_d += level;
    if (level < min_d) min_d = level;
    if (level > max_d) max_d = level;


    if (verify) verfiy_generateSpanningTree<<<blocks, ThreadsPerBlock>>>(g.nodes, g.edges, d_g.nindex, d_g.nlist, iter, d_parent, level, d_tail, border[level + 1]);
    //root count
    //#1
    timer.start();
    for (int level = levels - 1; level > 0; level--) {
      rootcount<<<blocks, ThreadsPerBlock>>>(d_parent, d_queue, d_label, level, border[level],  border[level + 1]);
    }
    if (verify) {
      if (cudaSuccess != cudaMemcpy((void*)&label[root[iter % g.nodes]], (void*)&d_label[root[iter % g.nodes]], sizeof(int), cudaMemcpyDeviceToHost)) {fprintf(stderr, "ERROR: copying to host failed\n"); exit(-1);}
      if (label[root[iter % g.nodes]] != g.nodes) {printf("ERROR: root count mismatch\n"); exit(-1);}
    }
    graphBtime += timer.stop();

    // tree label
    label[root[iter % g.nodes]] = 0;
    if (cudaSuccess != cudaMemset((void*)&d_label[root[iter % g.nodes]], 0, sizeof(int))){fprintf(stderr, "ERROR: setting d_label failed\n"); exit(-1);}

    //#2
    timer.start();
    for (int level = 0; level < levels; level++) {
      treelabel<<<blocks, ThreadsPerBlock>>>(g.nodes, d_g.nindex, d_g.nlist, d_einfo, d_inTree, d_negCnt, d_parent, d_queue, d_label, level, border[level], border[level + 1]);
    }
    graphBtime += timer.stop();

    //#3
    inTreeUpdate<<<blocks, ThreadsPerBlock>>>(g.edges, d_g.nlist, d_inTree);
    timer.start();
    initMinus<<<blocks, ThreadsPerBlock>>>(g.edges, g.nodes, d_g.nindex, d_g.nlist, d_einfo, d_minus);
    graphBtime += timer.stop();
    //if (iter == 0) printf("pm time:    %.6f s\n", timer.stop());

    //#4
    timer.start();
    processCycles<<<blocks, ThreadsPerBlock>>>(g.nodes, d_g.nindex, d_g.nlist, d_label, d_einfo, d_minus);
    graphBtime += timer.stop();
    //if (iter == 0) printf("cycle time: %.6f s\n", timer.stop());

    timer.start();
    init3<<<blocks, ThreadsPerBlock>>> (g.nodes, d_g.nindex, d_g.nlist, d_label, d_queue);
    compute1<<<blocks, ThreadsPerBlock>>>(g.nodes, d_g.nindex, d_g.nlist, d_label, d_minus, d_negCnt);
    flatten<<<blocks, ThreadsPerBlock>>>(g.nodes, d_label);
    ccSize<<<blocks, ThreadsPerBlock>>>(g.nodes, d_label, d_queue);
    largestCC<<<blocks, ThreadsPerBlock>>>(g.nodes, d_queue);
    ccHopCount<<<blocks, ThreadsPerBlock>>>(g.nodes, d_g.nindex, d_g.nlist, d_label, d_queue, d_ws1, d_ws2);

    bool changed;
    do {
      changed = false;
      if (cudaSuccess != cudaMemset(changed_gpu, 0, sizeof(bool))) fprintf(stderr, "ERROR: setting changed failed\n");
      BellmanFord<<<blocks, ThreadsPerBlock>>>(d_queue, changed_gpu, d_ws1, d_ws2);
      BellmanFord<<<blocks, ThreadsPerBlock>>>(d_queue, changed_gpu, d_ws1, d_ws2);
      BellmanFord<<<blocks, ThreadsPerBlock>>>(d_queue, changed_gpu, d_ws1, d_ws2);
      if (cudaSuccess != cudaMemcpy(&changed, changed_gpu, sizeof(bool), cudaMemcpyDeviceToHost)) fprintf(stderr, "ERROR: copying of changed from device failed\n");
    } while (changed);

    incrementCC<<<blocks, ThreadsPerBlock>>>(g.nodes, d_label, d_queue, d_inCC);
    //if (iter == 0) printf("CC time: %.6f s\n", timer.stop());
  }
  printf("graph bal time: %.6f s\n", graphBtime);

  avg_d = sum_d/iterations;
  if (cudaSuccess != cudaMemcpy(inCC, d_inCC, sizeof(int) * g.nodes, cudaMemcpyDeviceToHost)) fprintf(stderr, "ERROR: copying incc from device failed\n");
  // print results
  if (verify) {
    printf("number of trees %d", iterations);
    printf("Min depth of the trees %d\n Max depth of the trees %d\n Avg depth of the trees %.4f\n",min_d, max_d, avg_d);
    for (int i = 0; i < g.nodes; i++) {
      if (i >= 10) break;  // to limit output
      printf("%6d: %6d   (%5.1f%%)  %d\n", i, inCC[i], 100.0 * inCC[i] / iterations, g.origID[i]);
    }
  }
  // output results to file
  FILE *f = fopen(argv[3], "wt");
  fprintf(f, "original node ID, percentage node was in agreeable majority\n");
  for (int i = 0; i < g.nodes; i++) {
    fprintf(f, "%d,%.1f\n", g.origID[i], 100.0 * inCC[i] / iterations);
  }
  fprintf(f, "source node ID, destination node ID, percentage edge was in tree, percentage edge was negative\n");
  for (int v = 0; v < g.nodes; v++) {
    for (int j = g.nindex[v]; j < g.nindex[v + 1]; j++) {
      const int n = g.nlist[j] >> 1;
      if (v < n) {  // only print one copy of each edge (other copy does not have correct negCnt)
        fprintf(f, "%d,%d,%.1f,%.1f\n", g.origID[v], g.origID[n], 100.0 * inTree[j] / iterations, 100.0 * negCnt[j] / iterations);
      }
    }
  }
  fclose(f);

  // finalize
  freeGraph(g);
  delete [] label;
  delete [] border;
  delete [] inCC;
  delete [] inTree;
  delete [] negCnt;
  delete [] root;
  cudaFree(d_g.nlist);
  cudaFree(d_g.nindex);
  cudaFree(d_einfo);
  cudaFree(d_inCC);
  cudaFree(d_negCnt);
  cudaFree(d_inTree);
  cudaFree(d_label);
  cudaFree(d_parent);
  cudaFree(d_queue);
  cudaFree(d_border);
  cudaFree(d_tail);
  cudaFree(changed_gpu);
  cudaFree(d_ws1);
  cudaFree(d_ws2);
  cudaFree(d_wSize);
  cudaFree(d_minus);
  cudaFree(d_ws1);
  printf("overall runtime with I/O: %.6f s\n", overall.stop());
}
