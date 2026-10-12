/*
 * // For IJPP'22 paper at https://doi.org/10.1007/s10766-021-00723-0.
 *
 * // For compiling
 * nvcc gpuSteiner6-oddAgainWithKtimer2Sh3.cu -o gpuSteiner6-oddAgainWithKtimer2Sh3.out -Wno-deprecated-gpu-targets -std=c++11 
 *
 * // Authors
 * Rajesh Pandian M | https://mrprajesh.co.in
 * Rupesh Nasre     | www.cse.iitm.ac.in/~rupesh
 * N.S.Narayanaswamy| www.cse.iitm.ac.in/~swamy
 *
 * MIT LICENSE
 *
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <map>
#include <set>
#include <unordered_map>
#include <vector>

#include "CUDAMST.cu"
using namespace std;

#define MAX_INT_IN_SHARED_PER_BLOCK 12288
#define SH_REGS_PER_THREAD 24

#define cudaCheckError()                                                               \
  {                                                                                    \
    cudaError_t e = cudaGetLastError();                                                \
    if (e != cudaSuccess) {                                                            \
      printf("Cuda failure %s:%d: '%s'\n", __FILE__, __LINE__, cudaGetErrorString(e)); \
      exit(1);                                                                         \
    }                                                                                  \
  }
#define TRUE 1
#define FALSE 0

//~ #define MAX_THREADS_PER_BLOCK 1024 // It is defined in CUDAMST.h

#define MAX_COST 1073741823
#define LEVEL 0
// 0 submit level-- no print
// 1 debug level -- prints as needed.

#define DEBUG if (LEVEL)

cudaEvent_t tstart, tstop;
float totalTimeMilliSec = 0.0;
int sCount = 2;  // DEFAULT

__global__ void cpyParentArrayNew(int N, int index, int* d_parentArrays, int* d_parent, int sCount, int tempScount) {
  unsigned id = blockIdx.x * blockDim.x + threadIdx.x;  // Changed
  if (id < tempScount * N) {
    d_parentArrays[sCount * N * index + id] = d_parent[id];  // next block after sCount*N many
  }
}

__global__ void kernelInitDistAndParent(int N, int* minDist, int* parent, int tempScount) {  // FOR KSSSP

  unsigned id = threadIdx.x + blockDim.x * blockIdx.x;
  if (id < tempScount * N) {
    minDist[id] = INT_MAX / 2;
    parent[id] = -1;
  }
}

__global__ void kernelInitSources(int N, int* source, int* minDist, int tempScount) {  // FOR KSSSP
  unsigned id = threadIdx.x + blockDim.x * blockIdx.x;
  if (id == 0) {
    for (int ii = 0; ii < tempScount; ++ii)
      minDist[N * ii + source[ii]] = 0;
  }
}

__global__ void csrKernelBellmanFordMoore(int N, int* source,  // K SSSP  PULLL//PULLL
                                          int* csrM, int* csrD, int* csrW,
                                          bool* changed,
                                          int* minDist, int* parent,
                                          int sCount,
                                          int tempScount) {
  unsigned id = threadIdx.x + blockDim.x * blockIdx.x;

  if (id < tempScount * N) {
    int u = id;             // may not be needed but easier to code! -- ok! .For reading output
    int uIn = id % N;       // for read from input
    int start = csrM[uIn];  // may not be needed but easier to code! --refereed once :P
    int end = csrM[uIn + 1];
    int i, v, old, newDist, minSize;

    // variables to implement ShMEM
    int size = end - start;  // adjList size per thread
    int j;
    __shared__ int shD[MAX_INT_IN_SHARED_PER_BLOCK];  // for now. 12288  min(12288, _2M) -- it can never spill over

    // Sh MEM: cp csD
    for (i = start, j = 0, minSize = (size < SH_REGS_PER_THREAD ? size : SH_REGS_PER_THREAD); i < end && j < minSize; ++i, ++j)
      shD[threadIdx.x * SH_REGS_PER_THREAD + j] = csrD[i];

    //******** 1 PULL SH MEM **********
    for (i = start, j = 0; i < end; i++, j++) {  // 1 PULL SH MEM
      if (j < SH_REGS_PER_THREAD)
        v = shD[threadIdx.x * SH_REGS_PER_THREAD + j];  // If in ShMem take it
      else
        v = csrD[i];  // Else Read from Global
      newDist = minDist[(id / N) * N + v] + csrW[i];
      old = minDist[u];
      if (newDist < old) {
        minDist[u] = newDist;
        parent[u] = v;
        changed[0] = 1;
      }
    }
    //******** 2 PULL SH MEM **********
    for (i = start, j = 0; i < end; i++, j++) {  // 1 PULL SH MEM
      if (j < SH_REGS_PER_THREAD)
        v = shD[threadIdx.x * SH_REGS_PER_THREAD + j];  // If in ShMem take it
      else
        v = csrD[i];  // Else Read from Global
      newDist = minDist[(id / N) * N + v] + csrW[i];
      old = minDist[u];
      if (newDist < old) {
        minDist[u] = newDist;
        parent[u] = v;
        changed[0] = 1;
      }
    }
    //******** 3 PULL SH MEM **********
    for (i = start, j = 0; i < end; i++, j++) {  // 1 PULL SH MEM
      if (j < SH_REGS_PER_THREAD)
        v = shD[threadIdx.x * SH_REGS_PER_THREAD + j];  // If in ShMem take it
      else
        v = csrD[i];  // Else Read from Global
      newDist = minDist[(id / N) * N + v] + csrW[i];
      old = minDist[u];
      if (newDist < old) {
        minDist[u] = newDist;
        parent[u] = v;
        changed[0] = 1;
      }
    }
  }
}

void PrintParentOf(int n, int* pArray, int shift, int u, int v, set<pair<int, int>>& stEdges) {
  int idx = v;
  while (pArray[n * shift + idx] != -1) {
    int oldIdx = idx;

    idx = pArray[n * shift + idx];

    if (oldIdx < idx) {
      stEdges.insert(make_pair(oldIdx, idx));
    } else {
      stEdges.insert(make_pair(idx, oldIdx));
    }
  }
}

void KMBAlgo(int argc, char** argv);

////////////////////////////////////////////////////////////////////////////////
// Main Program
////////////////////////////////////////////////////////////////////////////////
bool printEdges = false;
bool printHash = false;

int main(int argc, char** argv) {
  if (argc == 1) {
    printf("Usage: %s <p> -v < tcSelected/instance137.gr.txt	 \n 	\
     p: # of SSSPs in parallel. 								 \n 	\
    -v: prints steiner tree edges. Default: Steiner VALUE and times \n  ", argv[0]);
    exit(0);
  }
  if (argc > 0) {
    //~ printEdges=true; //prints edges
    sCount = ((atoi(argv[1]) == 0) ? 2 : atoi(argv[1])); //DEFAULT IS 2
    printHash = true;
  }
  if (argc > 2) { // infact any 3rd will do.
    printEdges = true;
  }

  no_of_nodes = 0;
  edge_list_size = 0;
  KMBAlgo(argc, argv);

  return EXIT_SUCCESS;
}

int *edges, *edges_wt;
int* h_parentArrays;
int* d_parentArrays;
int N;
set<pair<int, int>> eSet;
set<int> vSet;

void MSTGraph(int t, int* terminals, map<pair<int, int>, int>& W, set<pair<int, int>>& stEdges, set<int>& nodeSet) {
  DEBUG printf("in MST Graph1\n");
  N = no_of_nodes;
  DEBUG
  for (int i = 0; i < t; i++)
    printf("T %d\n", terminals[i]);

  // for printing  the parent arrays
  DEBUG
  for (int i = 0; i < t; i++) {
    printf("Parent of %d\n", terminals[i]);
    for (int j = 0; j < N; j++) {
      printf("P[%d]=%d\n", j, h_parentArrays[j + i * N]);
    }
  }

  DEBUG printf("Reading INPUT \n");

  // IMPORTANT CONSTRUCT G' on TE
  no_of_nodes = t;
  edge_list_size = t * (t - 1);

  // allocate host memory
  hostMemAllocationNodes();

  // initalize the memory
  for (int i = 0; i < no_of_nodes; i++) {
    start = i * (t - 1);
    edgeno = t - 1;
    h_graph_nodes[i].starting = start;
    h_graph_nodes[i].no_of_edges = edgeno;
    sameindex[i] = i;
    falseval[i] = false;
    trueval[i] = true;
    infinity[i] = INF;
    zero[i] = 0;
    h_maxid_maxdegree[i] = -1;
  }

  // read the source node from the file, not needed here though
  source = 0;

  DEBUG
  for (int i = 0; i < no_of_nodes; i++)
    printf("V %d: %d,%d\n", i, h_graph_nodes[i].starting, h_graph_nodes[i].no_of_edges);

  DEBUG printf("n=%d 2m=%d \n", no_of_nodes, edge_list_size);

  DEBUG printf("Reading %d edges\n", edge_list_size);

  hostMemAllocationEdges();
  DEBUG printf("BFORE for\n");
  for (int i = 0; i < edge_list_size; i++) {
    h_graph_edges[i] = edges[i];
    h_graph_weights[i] = edges_wt[i];

    h_graph_MST_edges[i] = false;
    DEBUG printf("%d: -- %d: %d\n", i, h_graph_edges[i], h_graph_weights[i]);
  }

  // Copy the Node list to device memory
  deviceMemAllocateNodes();
  deviceMemAllocateEdges();
  deviceMemCopy();

  GPUMST();

  DEBUG printf("MST1 Compleet\n");
  cudaMemcpy(test, d_graph_colorindex, sizeof(int) * no_of_nodes, cudaMemcpyDeviceToHost);
  for (int i = 0; i < no_of_nodes; i++) {
    if (test[i] != 0) {
      printf("1:All Colors not 0, Error at %d\n", i);
      break;
    }
  }

  int q = 0;
  int minimumCost = 0;
  DEBUG printf("Final edges present in MST\n");
  cudaMemcpy(h_graph_MST_edges, d_graph_MST_edges, sizeof(bool) * edge_list_size, cudaMemcpyDeviceToHost);

  int v1 = 0;  // IMP to

  for (int i = 0; i < int(edge_list_size); i++) {
    int v1Limit = h_graph_nodes[v1].starting + h_graph_nodes[v1].no_of_edges;
    if (i == v1Limit)  // if limit reached, move to next v1
      v1++;

    //~ printf("%d :",i);
    if (h_graph_MST_edges[i]) {
      int v2 = h_graph_edges[i];
      int edgeweight = h_graph_weights[i];

      vSet.insert(v1);
      vSet.insert(v2);
      if (v1 < v2)
        eSet.insert(make_pair(v1, v2));
      else
        eSet.insert(make_pair(v2, v1));

      minimumCost += edgeweight;
      q++;
    }
    // Post increment after printing!
  }

  DEBUG printf("Printing Parent array\n");

  for (std::set<pair<int, int>>::iterator it = eSet.begin(), end = eSet.end(); it != end; ++it) {
    int v1 = it->first;
    int u = terminals[v1];
    int v2 = it->second;
    int v = terminals[v2];

    //~ printf("%d -- %d\n", u,v);
    PrintParentOf(N, h_parentArrays, v1, u, v, stEdges);  // populates stEdges
  }

  unsigned mstVal = 0;

  for (std::set<pair<int, int>>::iterator it = stEdges.begin(), end = stEdges.end(); it != end; ++it) {
    int v1 = it->first;
    int v2 = it->second;
    mstVal += W[make_pair(v1, v2)];
    nodeSet.insert(v1);
    nodeSet.insert(v2);
  }

  if (stEdges.size() == nodeSet.size() - 1) {  // MST(G') is tree alread then we do not have to do G"
                                               // TIMER STOP
    cudaEventRecord(tstop);
    cudaEventSynchronize(tstop);
    float milliseconds = 0;
    cudaEventElapsedTime(&milliseconds, tstart, tstop);
    totalTimeMilliSec += milliseconds;

    if (printEdges) {
      for (std::set<pair<int, int>>::iterator it = stEdges.begin(), end = stEdges.end(); it != end; ++it) {
        int v1 = it->first;
        int v2 = it->second;
        printf("%d %d\n", v1 + 1, v2 + 1);
      }
    }
    printf("VALUE %d,%f ms\n", mstVal, totalTimeMilliSec);
  }

  //! freeMem(); // This frees the GPU memory as well! OMG!
  DEBUG printf("in MST Graph1\n");
}

// Construct G" and MST(G")
void MSTGraphG2(set<pair<int, int>>& stEdges, set<int>& nodeSet, map<pair<int, int>, int>& W) {
  DEBUG printf("in MST Graph2\n");
  N = nodeSet.size();  // need to be modified.
  vector<vector<int>> graph(N);

  unordered_map<int, int> vMap;
  vector<int> nodeVec(nodeSet.begin(), nodeSet.end());
  int i = 0;
  for (auto& a : nodeVec) {
    vMap[a] = i++;
  }

  for (auto& a : stEdges) {
    int v1 = vMap[a.first];
    int v2 = vMap[a.second];
    graph[v2].push_back(v1);
    graph[v1].push_back(v2);
  }

  //~ printf("In MST\n");
  int eSize = stEdges.size() * 2;

  DEBUG printf("Reading INPUT \n");
  //~ scanf("%d",&no_of_nodes);

  // allocate host memory
  DEBUG printf("Reading %d nodes	", no_of_nodes);

  // IMPORTANT
  no_of_nodes = N;         // n
  edge_list_size = eSize;  // 2m

  hostMemAllocationNodes();
  int cumSum = 0;
  // initalize the memory
  for (int i = 0; i < no_of_nodes; i++) {
    //~ fscanf(fp,"%d %d",&start,&edgeno);
    //~ scanf("%d %d",&start,&edgeno);
    start = cumSum;  // start of csr(i) for i \in V
    auto adjSize = graph[i].size();
    cumSum += adjSize;
    edgeno = adjSize;  // |N(i)|
    h_graph_nodes[i].starting = start;
    h_graph_nodes[i].no_of_edges = edgeno;
    sameindex[i] = i;  // i // this is good!
    falseval[i] = false;
    trueval[i] = true;
    infinity[i] = INF;
    zero[i] = 0;
    h_maxid_maxdegree[i] = -1;
  }

  // read the source node from the file, not needed here though
  //~ scanf("%d",&source);.
  source = 0;

  //~ scanf("%d",&edge_list_size);
  DEBUG
  for (int i = 0; i < no_of_nodes; i++)
    printf("V %d: %d,%d\n", i, h_graph_nodes[i].starting, h_graph_nodes[i].no_of_edges);

  DEBUG printf("n=%d 2m=%d \n", no_of_nodes, edge_list_size);

  DEBUG printf("Reading %d edges\n", edge_list_size);

  //~ int id,cost;

  hostMemAllocationEdges();
  DEBUG printf("BFORE for\n");

  int u = 0;
  i = 0;
  for (auto adjList : graph) {
    int v1 = nodeVec[u];  // Thanks Rupesh!

    for (auto v : adjList) {
      int v2 = nodeVec[v];

      //! printf(" %d %d: %d\n",v1,v2 , W[{v1,v2}]);

      h_graph_edges[i] = v;
      h_graph_weights[i] = W[{v1, v2}];
      h_graph_MST_edges[i] = false;

      ++i;
    }
    ++u;
  }

  //~ DEBUG printf("Finished Reading INPUT\n");
  //~ DEBUG printf("Copying Everything to GPU memory\n");

  //~ Copy the Node list to device memory
  deviceMemAllocateNodes();
  deviceMemAllocateEdges();
  deviceMemCopy();

  GPUMST();

  cudaMemcpy(test, d_graph_colorindex, sizeof(int) * no_of_nodes, cudaMemcpyDeviceToHost);
  for (int i = 0; i < no_of_nodes; i++) {
    if (test[i] != 0) {
      printf("2:All Colors not 0, Error at %d\n", i);
      break;
    }
  }

  int q = 0;
  int minimumCost = 0;
  DEBUG printf("Final edges present in MST\n");
  cudaMemcpy(h_graph_MST_edges, d_graph_MST_edges, sizeof(bool) * edge_list_size, cudaMemcpyDeviceToHost);

  // TIMER STOP
  cudaEventRecord(tstop);
  cudaEventSynchronize(tstop);
  float milliseconds = 0;
  cudaEventElapsedTime(&milliseconds, tstart, tstop);
  totalTimeMilliSec += milliseconds;

  int v1 = 0;    // IMPORTANT to INIT
  eSet.clear();  // reset!
  for (int i = 0; i < int(edge_list_size); ++i) {
    int v1Limit = h_graph_nodes[v1].starting + h_graph_nodes[v1].no_of_edges;
    if (i == v1Limit)  // if limit reached, move to next v1
      v1++;

    if (h_graph_MST_edges[i]) {
      int v2 = h_graph_edges[i];
      int edgeweight = h_graph_weights[i];

      int u = nodeVec[v1] + 1;  // for printing
      int v = nodeVec[v2] + 1;

      if (printEdges)
        printf("%d %d \n", u, v);

      minimumCost += edgeweight;
      q++;
    }
  }
  // For each terminal on their respective parent array!

  printf("VALUE %d,%f ms, %f ms\n", minimumCost, totalTimeMilliSec, milliseconds);

  DEBUG printf("in MST Graph2\n");
  freeMem();
}

////////////////////////////////////////////////////////////////////////////////
// KMBGPU ALGORITHM using CUDA
////////////////////////////////////////////////////////////////////////////////

void KMBAlgo(int argc, char** argv) {
  DEBUG printf("Using sCount:%d\n", sCount);

  // Use if required on multiGPU device
  // cudaSetDevice(1);

  size_t mf, ma;
  cudaError_t err = cudaMemGetInfo(&mf, &ma);
  if (err != cudaSuccess)
    printf("ALERT: %s \n", cudaGetErrorString(err));

  int* source = (int*)malloc(sizeof(int) * (sCount));

  scanf("%d", &no_of_nodes);
  DEBUG printf("|V|: %d\n", no_of_nodes);

  int num_of_blocks = 1;
  int num_of_threads_per_block = no_of_nodes;

  // Make execution Parameters according to the number of nodes
  // Distribute threads across multiple Blocks if necessary
  if (no_of_nodes > MAX_THREADS_PER_BLOCK) {
    num_of_blocks = (int)ceil(no_of_nodes / (double)MAX_THREADS_PER_BLOCK);
    num_of_threads_per_block = MAX_THREADS_PER_BLOCK;
  }
  // initalize the memory
  // allocate host memory
  int* h_graph_nodes = (int*)malloc(sizeof(int) * (no_of_nodes + 1));  //  +1 for csrM

  int start, edgeno;

  int no = 0;
  for (unsigned int i = 0; i < no_of_nodes; i++) {
    scanf("%d %d", &start, &edgeno);
    DEBUG printf("%d %d\n", start, edgeno);
    if (edgeno > 100)
      no++;
    h_graph_nodes[i] = start;
  }

  h_graph_nodes[no_of_nodes] = start + edgeno;

  // read the source int from the file

  int dummy;
  scanf("%d", &dummy);  // not use else where

  scanf("%d", &edge_list_size);

  int* h_graph_edges = (int*)malloc(sizeof(int) * edge_list_size);
  int* h_graph_weights = (int*)malloc(sizeof(int) * edge_list_size);

  map<pair<int, int>, int> W;

  int id;

  for (int i = 0, j = 0; i < edge_list_size; i++) {
    int id1;
    if (i >= h_graph_nodes[j + 1]) j++;
    scanf("%d %d", &id, &id1);
    h_graph_edges[i] = id;
    h_graph_weights[i] = id1;
    DEBUG printf("%d %d\n", h_graph_edges[i], h_graph_weights[i]);

    W[make_pair(j, id)] = id1;
    W[make_pair(id, j)] = id1;
  }

  int terminalSize;

  scanf("%d", &terminalSize);

  int terminals[terminalSize];

  for (int i = 0; i < terminalSize; i++) {
    scanf("%d", &id);
    terminals[i] = id;
  }

  h_parentArrays = (int*)malloc(sizeof(int) * (no_of_nodes * terminalSize));
  cudaMalloc((void**)&d_parentArrays, sizeof(int) * no_of_nodes * terminalSize);

  int edgeId = 0;

  edges = (int*)malloc(sizeof(int) * terminalSize * (terminalSize - 1));  // For MST
  edges_wt = (int*)malloc(sizeof(int) * terminalSize * (terminalSize - 1));

  // setup execution parameters
  dim3 grid(num_of_blocks, 1, 1);
  dim3 threads(num_of_threads_per_block, 1, 1);

  // Copy the int list to device memory
  int* d_graph_nodes;
  cudaMalloc((void**)&d_graph_nodes, sizeof(int) * (no_of_nodes + 1));  //+1 for csrM

  // Copy the Edge List to device Memory
  int* d_graph_edges;
  cudaMalloc((void**)&d_graph_edges, sizeof(int) * edge_list_size);

  int* d_graph_weights;
  cudaMalloc((void**)&d_graph_weights, sizeof(int) * edge_list_size);

  // allocate mem for the result on host side
  int* h_cost = (int*)malloc(sizeof(int) * no_of_nodes * sCount);  // Rupesh

  // allocate device memory for result / OUTPUT
  int* d_cost;
  cudaMalloc((void**)&d_cost, sizeof(int) * no_of_nodes * sCount);

  int* h_parent = (int*)malloc(sizeof(int) * no_of_nodes * sCount);

  // copy the parent array
  int* d_parent;
  cudaMalloc((void**)&d_parent, sizeof(int) * no_of_nodes * sCount);

  bool* d_changed;
  bool* changed = (bool*)malloc(sizeof(bool));
  cudaMalloc((void**)&d_changed, sizeof(bool));
  cudaCheckError();

  // new for kSSSP
  int* d_sources;
  cudaMalloc((void**)&d_sources, sizeof(int) * sCount);
  cudaCheckError();

  /*************
   * TIMER START
   *************/
  cudaEventCreate(&tstart);
  cudaEventCreate(&tstop);
  cudaEventRecord(tstart);
  cudaCheckError();

  cudaMemcpy(d_graph_nodes, h_graph_nodes, (sizeof(int) * (no_of_nodes + 1)), cudaMemcpyHostToDevice);  // +1 for csrM
  cudaCheckError();

  cudaMemcpy(d_graph_weights, h_graph_weights, sizeof(int) * edge_list_size, cudaMemcpyHostToDevice);
  cudaCheckError();

  cudaMemcpy(d_graph_edges, h_graph_edges, sizeof(int) * edge_list_size, cudaMemcpyHostToDevice);
  cudaCheckError();

  int tempScount = sCount;  // Just to ensure the last run runs < sCount times
  printf("sCount:%d terminalSize:%d n:%d m:%d\n", sCount, terminalSize, no_of_nodes, edge_list_size);

  for (int it = 0, end = (terminalSize + sCount - 1) / sCount; it < end; ++it) {  // ceil(terminalSize/sCount)

    if (terminalSize % sCount == 0 || it != end - 1) {  // Thanks Rupesh. termSize%sCount==0 || it!=end-1
      tempScount = sCount;
      for (int ii = 0; ii < sCount; ++ii) {
        source[ii] = terminals[sCount * it + ii];
        DEBUG printf("\t #%d SSSP from %d\n", ii + 1, source[ii]);
      }
      num_of_blocks = (sCount * no_of_nodes + MAX_THREADS_PER_BLOCK - 1) / MAX_THREADS_PER_BLOCK;

    } else {
      tempScount = terminalSize % sCount;  // suposedly 1 t0 sCount-1 for the last round when sCount does not divide terminalSize
      for (int ii = 0, endII = tempScount; ii < endII; ++ii) {
        source[ii] = terminals[sCount * it + ii];
        DEBUG printf("\t #%d SSSP from %d\n", ii + 1, source[ii]);
      }

      num_of_blocks = (tempScount * no_of_nodes + MAX_THREADS_PER_BLOCK - 1) / MAX_THREADS_PER_BLOCK;
    }

    num_of_threads_per_block = MAX_THREADS_PER_BLOCK;  //(no_of_nodes<MAX_THREADS_PER_BLOCK? no_of_nodes: MAX_THREADS_PER_BLOCK);
    dim3 gridKN(num_of_blocks, 1, 1);
    dim3 threadsKN(num_of_threads_per_block, 1, 1);

    int k = 0;

    cudaMemcpy(d_sources, source, (sizeof(int) * (tempScount)), cudaMemcpyHostToDevice);        //
    kernelInitDistAndParent<<<gridKN, threadsKN>>>(no_of_nodes, d_cost, d_parent, tempScount);  // SAME grid
    kernelInitSources<<<1, 1>>>(no_of_nodes, d_sources, d_cost, tempScount);                    //

    cudaCheckError();

    do {
      changed[0] = false;

      cudaMemcpy(d_changed, changed, sizeof(bool), cudaMemcpyHostToDevice);

      cudaCheckError();

      csrKernelBellmanFordMoore<<<gridKN, threadsKN>>>(no_of_nodes, d_sources,
                                                       d_graph_nodes, d_graph_edges, d_graph_weights,  // inputs
                                                       d_changed,                                      // fixed pt var
                                                       d_cost, d_parent,                               // these are outputs
                                                       sCount,
                                                       tempScount);

      cudaCheckError();

      cudaMemcpy(changed, d_changed, sizeof(bool), cudaMemcpyDeviceToHost);
      cudaCheckError();

      k++;

      DEBUG printf("%d -- FINSHED? %s\n", k, (!changed[0] ? "Yes" : "No"));
    } while (changed[0] == true);
    DEBUG printf("AFTER LAUNCH\n");

    DEBUG printf("\nTOTAL IT:%d\n", k);

    cpyParentArrayNew<<<gridKN, threadsKN>>>(no_of_nodes, it, d_parentArrays, d_parent, sCount, tempScount);  //~DOUBLE~  K COPY
    cudaCheckError();

    // copy result from device to host
    cudaMemcpy(h_cost, d_cost, sizeof(int) * no_of_nodes * tempScount, cudaMemcpyDeviceToHost);  //~DOUBLE~  K COPY

    unsigned long long int sol;

    DEBUG printf("N=%d %d\n", no_of_nodes, INT_MAX / 2);
    DEBUG
    for (int jj = 0; jj < tempScount; ++jj) {
      sol = 0;
      for (int i = 0; i < no_of_nodes; ++i) {
        sol += h_cost[jj * no_of_nodes + i];
      }
      /// for debugging
      if (printHash) printf("iterat:%d SSSP %d on src %d HASH VAL %lld\n", it, jj + 1, source[jj], sol);
    }

    for (int ii = 0; ii < tempScount; ++ii) {
      int pt1 = terminals[sCount * it + ii];
      for (int j = 0; j < terminalSize; ++j) {
        int pt2 = terminals[j];
        if (pt1 != pt2) {
          edges[edgeId] = j;
          edges_wt[edgeId] = h_cost[no_of_nodes * ii + pt2];  /// Mod
          edgeId++;
        }
      }
    }
  }

  cudaMemcpy(h_parentArrays, d_parentArrays, sizeof(int) * no_of_nodes * terminalSize, cudaMemcpyDeviceToHost);  // why is this needed? It is used inside MST1

  DEBUG printf("GPU [ms]:%f\n", totalTimeMilliSec);

  // Construct G' and Launch the kernel for the MST(G')
  set<pair<int, int>> stEdges;
  set<int> nodeSet;
  DEBUG printf("In main before MST\n");
  MSTGraph(terminalSize, terminals, W, stEdges, nodeSet);

  // Construct G" and Launch the kernel for the MST(G")
  if (stEdges.size() != nodeSet.size() - 1)  //|E| != |V|-1
    MSTGraphG2(stEdges, nodeSet, W);

  free(h_graph_nodes);
  free(h_graph_edges);
  free(h_graph_weights);
  free(h_cost);

  cudaFree(d_graph_nodes);
  cudaFree(d_graph_edges);

  cudaFree(d_graph_weights);

  cudaFree(d_cost);
  cudaFree(d_parentArrays);
}
