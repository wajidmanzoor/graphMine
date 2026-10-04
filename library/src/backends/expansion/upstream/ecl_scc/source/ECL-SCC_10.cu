/*
ECL-SCC: This code computes the Strongly Connected Components of a directed graph.

Copyright (c) 2023, Martin Burtscher

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

URL: The latest version of this code is available at https://cs.txstate.edu/~burtscher/research/ECL-SCC/ and at https://github.com/burtscher/ECL-SCC.

Publication: This work is described in detail in the following paper.
Ghadeer Alabandi, William Sands, George Biros, and Martin Burtscher. "A GPU Algorithm for Detecting Strongly Connected Components." Proceedings of the 2023 ACM/IEEE International Conference for High Performance Computing, Networking, Storage, and Analysis. November 2023.
*/


#include <cstdlib>
#include <cstdio>
#include <algorithm>
#include <functional>
#include <sys/time.h>
#include <cuda.h>
#include "ECLgraph.h"


static const int Device = 0;
static const int ThreadsPerBlock = 512;


static __global__
void globalInit(const ECLgraph g, int2* const __restrict__ wl1, int* const __restrict__ wl1size, int2* const __restrict__ iomax)
{
  const int thread = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int threads = gridDim.x * ThreadsPerBlock;
  for (int v = thread; v < g.nodes; v += threads) {
    const int beg = g.nindex[v];
    const int end = g.nindex[v + 1];
    int y = v;
    for (int j = beg; j < end; j++) {
      const int w = g.nlist[j];
      wl1[j] = int2{v, w};
      y = max(y, w);
    }
    iomax[v] = int2{v, y};
  }
  if (thread == 0) *wl1size = g.edges;
}


static __global__
void propagateMax(const int2* const __restrict__ wl1, const int wl1size, int2* const __restrict__ iomax, volatile bool* const __restrict__ goagain)
{
  const int thread = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int threads = gridDim.x * ThreadsPerBlock;
  bool updated, again = false;
  do {  // iterate locally
    updated = false;
    for (int i = thread; i < wl1size; i += threads) {
      const int2 el = wl1[i];
      const int v = el.x;
      const int w = el.y;

      const int2 iov = iomax[v];
      const int2 iow = iomax[w];
      int im = iov.x;
      int om = iow.y;
      if (im > v) im = iomax[im].x;  // 'path compress'
      if (om > w) om = iomax[om].y;  // 'path compress'

      // propagate
      if (iov.x < im) {iomax[v].x = im; updated = true;}
      if (iov.y < om) {iomax[v].y = om; updated = true;}
      if (iow.x < im) {iomax[w].x = im; updated = true;}
      if (iow.y < om) {iomax[w].y = om; updated = true;}

      // update other vertices on path
      if ((iov.x < om) && (iomax[iov.x].y < om)) {iomax[iov.x].y = om; updated = true;}
      if ((iov.x != iow.x) && (iow.x < om) && (iomax[iow.x].y < om)) {iomax[iow.x].y = om; updated = true;}
      if ((iov.y < im) && (iomax[iov.y].x < im)) {iomax[iov.y].x = im; updated = true;}
      if ((iov.y != iow.y) && (iow.y < im) && (iomax[iow.y].x < im)) {iomax[iow.y].x = im; updated = true;}
    }
    again |= updated;
  } while (__syncthreads_or(updated));
  again = __syncthreads_or(again);
  if ((threadIdx.x == 0) && again) *goagain = true;
}


static __global__
void removeEdges(const int2* const __restrict__ wl1, const int wl1size, int2* const __restrict__ wl2, int* const __restrict__ wl2size, const int2* const __restrict__ iomax)
{
  const int thread = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int threads = gridDim.x * ThreadsPerBlock;
  for (int i = thread; i < wl1size; i += threads) {
    const int2 el = wl1[i];
    const int v = el.x;
    const int w = el.y;
    const int2 iov = iomax[v];
    const int2 iow = iomax[w];
    if (iov.x != iov.y) {
      if ((iow.x == iov.x) && (iow.y == iov.y)) {
        const int k = atomicAdd(wl2size, 1);
        wl2[k] = el;
      }
    }
  }
}


static __global__
void localInit(const int nodes, int2* const __restrict__ iomax, volatile bool* const __restrict__ goagain)
{
  const int thread = threadIdx.x + blockIdx.x * ThreadsPerBlock;
  const int threads = gridDim.x * ThreadsPerBlock;
  bool again = false;
  for (int v = thread; v < nodes; v += threads) {
    const int2 iov = iomax[v];
    if (iov.x != iov.y) {
      iomax[v] = int2{v, v};
      again = true;
    }
  }
  again = __syncthreads_or(again);
  if ((threadIdx.x == 0) && again) *goagain = true;
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


struct GPUTimer
{
  cudaEvent_t beg, end;
  GPUTimer() {cudaEventCreate(&beg);  cudaEventCreate(&end);}
  ~GPUTimer() {cudaEventDestroy(beg);  cudaEventDestroy(end);}
  void start() {cudaEventRecord(beg, 0);}
  float stop() {cudaEventRecord(end, 0);  cudaEventSynchronize(end);  float ms;  cudaEventElapsedTime(&ms, beg, end);  return 0.001f * ms;}
};


int main(int argc, char* argv [])
{
  printf("ECL-SCC v1.0\n\n");  fflush(stdout);

  // process command line
  if (argc != 2) {printf("USAGE: %s input_file_name\n\n", argv[0]);  exit(-1);}

  ECLgraph g = readECLgraph(argv[1]);
  printf("input: %s\n", argv[1]);
  printf("nodes: %d\n", g.nodes);
  printf("edges: %d\n", g.edges);
  printf("avg degree: %.2f\n\n", 1.0 * g.edges / g.nodes);

  // get GPU info
  cudaSetDevice(Device);
  cudaDeviceProp deviceProp;
  cudaGetDeviceProperties(&deviceProp, Device);
  if ((deviceProp.major == 9999) && (deviceProp.minor == 9999)) {printf("ERROR: there is no CUDA capable device\n\n");  exit(-1);}
  const int SMs = deviceProp.multiProcessorCount;
  const int mTpSM = deviceProp.maxThreadsPerMultiProcessor;
  printf("GPU: %s with %d SMs and %d mTpSM (%.1f MHz and %.1f MHz)\n\n", deviceProp.name, SMs, mTpSM, deviceProp.clockRate * 0.001, deviceProp.memoryClockRate * 0.001);  fflush(stdout);
  const int blocks = SMs * (mTpSM / ThreadsPerBlock);

  // allocate GPU memory
  int2 *d_wl1, *d_wl2, *d_iomax;
  int *d_wl2size;
  bool *d_goagain;
  cudaMalloc((void **)&d_iomax, g.nodes * sizeof(int2));
  cudaMalloc((void **)&d_wl1, g.edges * sizeof(int2));
  cudaMalloc((void **)&d_wl2, g.edges * sizeof(int2));
  cudaMalloc((void **)&d_wl2size, sizeof(int));
  cudaMalloc((void **)&d_goagain, sizeof(bool));

  // copy graph to GPU
  ECLgraph d_g = g;
  cudaMalloc((void **)&d_g.nindex, (g.nodes + 1) * sizeof(int));
  cudaMemcpy(d_g.nindex, g.nindex, (g.nodes + 1) * sizeof(int), cudaMemcpyHostToDevice);
  cudaMalloc((void **)&d_g.nlist, g.edges * sizeof(int));
  cudaMemcpy(d_g.nlist, g.nlist, g.edges * sizeof(int), cudaMemcpyHostToDevice);
  CheckCuda(__LINE__);

/*************************************************************************/

  // start time
  printf("running algorithm\n");  fflush(stdout);
  GPUTimer timer;
  timer.start();

  // global initialization
  int wl1size;
  globalInit<<<blocks, ThreadsPerBlock>>>(d_g, d_wl1, d_wl2size, d_iomax);
  cudaMemcpy(&wl1size, d_wl2size, sizeof(int), cudaMemcpyDeviceToHost);

  bool goagain;
  do {
    // propagate max values
    do {
      cudaMemsetAsync(d_goagain, 0, sizeof(bool));
      propagateMax<<<blocks, ThreadsPerBlock>>>(d_wl1, wl1size, d_iomax, d_goagain);
      cudaMemcpy(&goagain, d_goagain, sizeof(bool), cudaMemcpyDeviceToHost);
    } while (goagain);

    // remove edges that cannot be part of an SCC
    cudaMemsetAsync(d_wl2size, 0, sizeof(int));
    removeEdges<<<blocks, ThreadsPerBlock>>>(d_wl1, wl1size, d_wl2, d_wl2size, d_iomax);
    std::swap(d_wl1, d_wl2);
    cudaMemcpyAsync(&wl1size, d_wl2size, sizeof(int), cudaMemcpyDeviceToHost);

    // local re-initialization
    cudaMemsetAsync(d_goagain, 0, sizeof(bool));
    localInit<<<blocks, ThreadsPerBlock>>>(g.nodes, d_iomax, d_goagain);
    cudaMemcpy(&goagain, d_goagain, sizeof(bool), cudaMemcpyDeviceToHost);
  } while (goagain);

  // end time
  const double runtime = timer.stop();
  printf("compute time: %.6f s\n\n", runtime);
  CheckCuda(__LINE__);

/*************************************************************************/

  // copy result to host
  const int n = g.nodes;
  int2* iomax = new int2 [n];
  cudaMemcpy(iomax, d_iomax, n * sizeof(int2), cudaMemcpyDeviceToHost);
  CheckCuda(__LINE__);

  // output SCC sizes and frequency
  printf("result:\n");
  int* count = new int [n];
  for (int v = 0; v < n; v++) count[v] = 0;
  for (int v = 0; v < n; v++) count[iomax[v].x]++;
  std::sort(count, count + n, std::greater<int>());
  int cnt = 1;
  int SCC_cnt = 0;
  for (int v = 1; v < n; v++) {
    if (count[v] != count[v - 1]) {
      printf("%d SCCs of size %d\n", cnt, count[v - 1]);
      SCC_cnt += cnt;
      cnt = 1;
    } else {
      cnt++;
    }
  }
  if (count[n - 1] > 0) {
    printf("%d SCCs of size %d\n", cnt, count[n - 1]);
    SCC_cnt += cnt;
  }
  printf("number of SCCs: %d\n", SCC_cnt);

  // clean up
  cudaFree(d_g.nindex);  cudaFree(d_g.nlist);  cudaFree(d_iomax);  cudaFree(d_wl1);  cudaFree(d_wl2);  cudaFree(d_wl2size);  cudaFree(d_goagain);
  delete [] iomax;
  delete [] count;
  freeECLgraph(g);
  return 0;
}
