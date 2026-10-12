/*
MG-MIS: This code computes a maximal independent set using multiple GPUs.

Copyright (c) 2025, Anju Mongandampulath Akathoott and Martin Burtscher

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

URL: The latest version of this code is available at https://cs.txstate.edu/~burtscher/research/MG-MIS/ and at https://github.com/burtscher/MG-MIS.

Publication: This work is described in detail in the following paper.
Anju Mongandampulath Akathoott, Benila Jerald, and Martin Burtscher. "A Multi-GPU Algorithm for Computing Maximal Independent Sets in Large Graphs." Proceedings of the 2025 ACM International Conference on Supercomputing. June 2025.
*/


#define NDEBUG

#include <cstdlib>
#include <cstdio>
#include <iostream>
#include <utility>
#include <sys/time.h>
#include <cuda.h>
#include <omp.h>
#include <unistd.h>
#include <cassert>
#include "ECLgraph.h"

static const int ThreadsPerBlock = 512;
static const int WS = 32;  // warp size
static const long PageSize = 512;
typedef unsigned char stattype;
static const stattype in = 0xfe;
static const stattype out = 0;
static const stattype undecided = 1;
static __device__ long BUF_SIZE = 16384000;
static long h_BUF_SIZE = 16384000;
static bool p2pEnabled;


// https://stackoverflow.com/questions/664014/what-integer-hash-function-are-good-that-accepts-an-integer-hash-key
static __device__ unsigned int hash(unsigned int val)
{
  val = ((val >> 16) ^ val) * 0x45d9f3b;
  val = ((val >> 16) ^ val) * 0x45d9f3b;
  return (val >> 16) ^ val;
}


static __global__ void init(stattype* const __restrict__ nstat, const long size)
{
  const long from = threadIdx.x + (long)blockIdx.x * ThreadsPerBlock;
  const long incr = (long)gridDim.x * ThreadsPerBlock;

  for (long i = from; i < size; i += incr) {
    nstat[i] = undecided;
  }
}


static __device__ bool iamhigher(const long me, const long nbr, const unsigned int hash_me)
{
  unsigned int hash_nbr = hash(nbr);
  return (hash_me > hash_nbr) || ((hash_me == hash_nbr) && (me > nbr));
}


static __host__ __device__ bool islocal(const long v, const long beg, const long end)
{
  return ((v >= beg) && (v < end));
}


static inline __device__ int getOwningGpuId(const long* const __restrict__ beg, const long* const __restrict__ end, const long v, const int devices)
{
  for (int i = 0; i < devices; i++) {
    if ((v >= beg[i]) && (v < end[i]))
      return i;
  }
  assert(false);
  return -1;  // control should not reach here
}


static __global__ void readBufferAndSetToOut(const long* const __restrict__ buffer, const long* const size, volatile stattype* const __restrict__ nstat, const long beg)
{
  const long thread = threadIdx.x + (long)blockIdx.x * ThreadsPerBlock;
  if (thread < *(size)) {
    const long v = buffer[thread];
    nstat[v - beg] = out;
  }
}


static __global__ void readPairBuffersAndProcess(const long* const __restrict__ buf1, const long* const pairBufferSize, long* const __restrict__ responseBuffer, long* respBufSize, const stattype* const __restrict__ nstat, const long beg)  // read the buffer written to by d, for id, and write in the buffer of id to d
{
  const long thread = threadIdx.x + (long)blockIdx.x * ThreadsPerBlock;
  if (thread < (*(pairBufferSize) / 2)) {
    const long u = buf1[2 * thread];
    const long v = buf1[2 * thread + 1];
    if (nstat[v - beg] == out) {
      const long index = atomicAdd((unsigned long long*)respBufSize, 1);
      if (index < BUF_SIZE) {
        responseBuffer[index] = u;
      }
    }
  }
}


static __global__ void readResponseAndProcess(long* buffer, const long* const size, long* remoteNbrIndex, const long beg)
{
  const long thread = threadIdx.x + (long)blockIdx.x * ThreadsPerBlock;
  if (thread < *(size)) {
    const long v = buffer[thread];
    remoteNbrIndex[v - beg]++;
  }
}


static __global__ void askRemoteNbrStatus(const long* const __restrict__ beg, const long* const __restrict__ end, const long* const __restrict__ nidx, const long* const __restrict__ nlist, const stattype* const __restrict__ nstat, const int gpuId, const int devices, long** buf1Ptrs, long* curBufferSizeArr, long* remoteNbrIndex, const long nidx_0, const long my_beg, const long my_end)
{
  const long thread = threadIdx.x + (long)blockIdx.x * ThreadsPerBlock;
  const long threads = (long)gridDim.x * ThreadsPerBlock;
  const long size = my_end - my_beg;

  for (long v = thread; v < size; v += threads) {
    const stattype nv = nstat[v];
    const long stop_local = nidx[v + 1] - nidx_0;
    if (nv & 1) {
      long remoteIndex = remoteNbrIndex[v];
      if (remoteIndex < stop_local) {  // implies v is waiting for some nbr's status
        long nbr = nlist[remoteIndex];  // Note: Need local index to nlist
        bool localNbr;
        while ((localNbr = islocal(nbr, my_beg, my_end)) && (remoteIndex < (stop_local - 1))) {
          nbr = nlist[(++remoteIndex)];
        }
        remoteNbrIndex[v] = remoteIndex;
        if (!localNbr) {
          const long targetGpuId = getOwningGpuId(beg, end, nbr, devices);
          long* buf1 = buf1Ptrs[targetGpuId];
          long index = atomicAdd((unsigned long long*)&curBufferSizeArr[targetGpuId], 2);
          if (index < BUF_SIZE) {
            buf1[index] = v + my_beg;  // converting to global id
            buf1[index + 1] = nbr;
          }
        }
      }
    }
  }
}


static __device__ void pushRemoteNbrsToBuffer(const long* const __restrict__ beg, const long* const __restrict__ end, const long* const __restrict__ nidx, const long* const __restrict__ nlist, volatile bool* const go_again, const int gpuId, const int devices, long** bufferPtrs, long* curBufferSizeArr, long* const __restrict__ remoteNbrIndex, const long my_beg, const long my_end, const long v, const long nidx_0)
{
  bool addedAllRemoteNbrs = true;
  const long stop_local = nidx[v + 1] - nidx_0;
  long minRemoteIndex = stop_local;
  for (long i = remoteNbrIndex[v]; i < stop_local; i++) {
    const long nbr = nlist[i];
    if (!(islocal(nbr, my_beg, my_end))) {
      const long targetGpuId = getOwningGpuId(beg, end, nbr, devices);
      long* B = bufferPtrs[targetGpuId];
      long index = atomicAdd((unsigned long long*)&curBufferSizeArr[targetGpuId], 1ULL);
      if (index < BUF_SIZE) {
        B[index] = nbr;
      } else {
        addedAllRemoteNbrs = false;
        minRemoteIndex = min(minRemoteIndex, i);
        break;
      }
    }
  }
  remoteNbrIndex[v] = minRemoteIndex;
  if (!addedAllRemoteNbrs) {
    *go_again = true;  //  All remote nbrs could not be set to out due to buffer size limitation
  }
}


// set local nbrs to out and add remote nbrs to the corresponding buffers
static __device__ void processAllNbrs(const long* const __restrict__ beg, const long* const __restrict__ end, const long* const __restrict__ nidx, const long* const __restrict__ nlist, volatile bool* const go_again, const int gpuId, const int devices, long** bufferPtrs, long* curBufferSizeArr, long* const __restrict__ remoteNbrIndex, const long my_beg, const long my_end, const long stop_local, const long v, volatile stattype* const __restrict__ nstat, const long nidx_0)
{
  bool addedAllRemoteNbrs = true;
  long minRemoteIndex = stop_local;  // local index
  for (long i = (nidx[v] - nidx_0); i < stop_local; i++) {
    const long nbr = nlist[i];
    if (islocal(nbr, my_beg, my_end)) {
      nstat[nbr - my_beg] = out;
    } else {
      const long targetGpuId = getOwningGpuId(beg, end, nbr, devices);  // ID of the GPU to which nbr belongs
      long* B = bufferPtrs[targetGpuId];  // pointer to the beginning of the data-buffer for target within my buffers.
      long index = atomicAdd((unsigned long long*)&curBufferSizeArr[targetGpuId], 1);
      if (index < BUF_SIZE) {
        B[index] = nbr;
      } else {
        addedAllRemoteNbrs = false;
        minRemoteIndex = min(minRemoteIndex, i);
      }
    }
  }
  remoteNbrIndex[v] = minRemoteIndex;
  if (!addedAllRemoteNbrs) {
    *go_again = true;  //  All remote nbrs could not be set to out due to buffer size limitation
  }
}


static __global__ void computeMIS1(const long* const __restrict__ beg, const long* const __restrict__ end, const long* const __restrict__ nidx, const long* const __restrict__ nlist, volatile stattype* const __restrict__ nstat, volatile bool* const go_again, const int gpuId, const int devices, long** bufferPtrs, long* curBufferSizeArr, long* const __restrict__ remoteNbrIndex, const long nidx_0, const long my_beg, const long my_end)
{  
  const long thread = threadIdx.x + (long)blockIdx.x * ThreadsPerBlock;
  const long threads = (long)gridDim.x * ThreadsPerBlock;
  const long size = my_end - my_beg; 

  for (long v = thread; v < size; v += threads) {
    const long global_id_v = my_beg + v;
    const stattype nv = nstat[v];
    const long stop_local = nidx[v + 1] - nidx_0;
    if (nv & 1) {
      unsigned int hash_v = hash(global_id_v);
      long i;
      for (i = (nidx[v] - nidx_0); i < stop_local; i++) {
        const long nbr = nlist[i];
        bool localNbr;
        if ((localNbr = islocal(nbr, my_beg, my_end)) && (nstat[nbr - my_beg]) == out)
          continue;
        if (!(iamhigher(global_id_v, nbr, hash_v))) {
          if (!localNbr) {  // remote nbr with higher priority
            if (i < remoteNbrIndex[v])
              continue;  // Reason: This remote nbr is known to be out
            else
              remoteNbrIndex[v] = i;
          }
          break;  // breaking since my priority is low
        }
      }

      if (i < stop_local) {
        *go_again = true;  // v cannot be decided now since there is a higher priority nbr with undecided status
      } else {
        nstat[v] = in;
        processAllNbrs(beg, end, nidx, nlist, go_again, gpuId, devices, bufferPtrs, curBufferSizeArr, remoteNbrIndex, my_beg, my_end, stop_local, v, nstat, nidx_0);
      }
    } else if ((nv == in) && (remoteNbrIndex[v] < stop_local)) {
      // Add the remaining remote nbrs to the buffer
      pushRemoteNbrsToBuffer(beg, end, nidx, nlist, go_again, gpuId, devices, bufferPtrs, curBufferSizeArr, remoteNbrIndex, my_beg, my_end, v, nidx_0);
    }
  }
}


struct CPUTimer
{
  timeval beg, end;
  CPUTimer() {}
  ~CPUTimer() {}
  void start() {gettimeofday(&beg, NULL);}
  double elapsed() {gettimeofday(&end, NULL); return end.tv_sec - beg.tv_sec + (end.tv_usec - beg.tv_usec) / 1000000.0;}
};


static void CheckCuda(const int line)
{
  cudaError_t e;
  cudaDeviceSynchronize();
  if (cudaSuccess != (e = cudaGetLastError())) {
    fprintf(stderr, "CUDA error %d on line %d: %s\n\n", e, line, cudaGetErrorString(e));
    exit(-1);
  }
}


static bool checkIfWorkLeft(const bool* const __restrict__ flag, const int devices)
{
  for (int i = 0; i < devices; i++) {
    if (flag[i]) return true;
  }
  return false;
}


static void resetBufferSize(long* const __restrict__ bufSizeArr, const int devices)
{
  cudaMemsetAsync(bufSizeArr, 0, devices * sizeof(long));
}


static __global__ void saturateSize_kernel(const int id, long* bufferSizeArr, const int devices)
{
  for (int d = 0; d < devices; d++) {
    if ((id != d) && (bufferSizeArr[d] > BUF_SIZE)) {
      bufferSizeArr[d] = BUF_SIZE;
    }
  }
}


static void sendDataToReceivers(const int sender, const int devices, long*** s_buf, long** s_bufSize, long*** r_buf, long** r_bufSize, const bool p2pEnabled, long* const host_buffer)
{
  if (p2pEnabled) {
    for (int r = 0; r < devices; r++) {
      if (r != sender) {
        long n;
        cudaMemcpy(&n, (s_bufSize[sender] + r), sizeof(long), cudaMemcpyDeviceToHost);
        if (n > 0) {
          cudaMemcpyPeerAsync(r_buf[r][sender], sender, s_buf[sender][r], r, n * sizeof(long));
        }
        cudaMemcpyAsync((r_bufSize[r] + sender), &n, sizeof(long), cudaMemcpyHostToDevice);
      }
    }
  } else {
    for (int r = 0; r < devices; r++) {
      if (r != sender) {
        long n;
        // Note: By default the device is set to the sender
        cudaMemcpy(&n, (s_bufSize[sender] + r), sizeof(long), cudaMemcpyDeviceToHost);
        if (n > 0) {
          cudaMemcpyAsync(host_buffer, s_buf[sender][r], n * sizeof(long), cudaMemcpyDeviceToHost);
        }

        cudaSetDevice(r);
        if (n > 0) {
          cudaMemcpyAsync(r_buf[r][sender], host_buffer, n * sizeof(long), cudaMemcpyHostToDevice);
        }
        cudaMemcpyAsync((r_bufSize[r] + sender), &n, sizeof(long), cudaMemcpyHostToDevice);

        cudaSetDevice(sender);  // Setting the device back to the sender. Required for next itr, and also needed before exiting the loop
      }
    }
  }
  cudaDeviceSynchronize();
}


static void runLocalRound(const int id, const int devices, const int repeats, long* bufSizeArr, int blocks, long* beg, long* end, const long* const __restrict__ nidx, const long* const __restrict__ nlist, volatile stattype* const __restrict__ nstat, bool* go_again, long** bufferAddress, long* remoteNbrIndex, const long nidx_0, const long my_beg, const long my_end)
{
  resetBufferSize(bufSizeArr, devices);
  // local computation
  for (int j = 0; j < repeats; j++) {
    if (j == repeats - 1) {
      cudaMemsetAsync(go_again, false, sizeof(bool));
    }
    computeMIS1<<<blocks, ThreadsPerBlock>>>(beg, end, nidx, nlist, nstat, go_again, id, devices, bufferAddress, bufSizeArr, remoteNbrIndex, nidx_0, my_beg, my_end);
  }
  saturateSize_kernel<<<1,1>>>(id, bufSizeArr, devices);
}


static __global__ void initRemoteNbrIndxArr(long* const __restrict__ remoteNbrIndex, const long size, const long* const __restrict__ nidx, const long nidx_0)
{
  const long thread = threadIdx.x + (long)blockIdx.x * ThreadsPerBlock;
  const long threads = (long)gridDim.x * ThreadsPerBlock;

  for (long v = thread; v < size; v += threads) {
    remoteNbrIndex[v] = nidx[v] - nidx_0;
  }
}


static void setToOut(const int id, long*** bufferAddress, long** bufferSize, volatile stattype* const __restrict__ nstatus, const int devices, const long beg)
{
  // The GPU 'id' reads the buffers received from all the other GPUs, and for each vertex u in the buffer, set nstatus[u] = out;
  for (int d = 0; d < devices; d++) {
    if (id != d) {
      int n;
      cudaMemcpy(&n, (bufferSize[id] + d), sizeof(long), cudaMemcpyDeviceToHost);
      readBufferAndSetToOut<<<(n + ThreadsPerBlock - 1) / ThreadsPerBlock, ThreadsPerBlock>>>(bufferAddress[id][d], (bufferSize[id] + d), nstatus, beg);  // read the buffer received by id from d
    }
  }
  cudaDeviceSynchronize();
}


int main(int argc, char* argv [])
{
  printf("Multi-GPU MIS using buffers for data exchange (%s)\n", __FILE__);
  int deviceCount;

  cudaGetDeviceCount(&deviceCount);
  if (deviceCount < 2) {
    printf("The system has only a single GPU\n");
  }
  // check command line
  if (argc != 3) {fprintf(stderr, "USAGE: %s input_file devices\n", argv[0]);  exit(-1);}
  if ((ThreadsPerBlock < WS) || ((ThreadsPerBlock % WS) != 0)) {printf("ERROR: threads per block must be a multiple of the warp size\n\n");  exit(-1);}
  if ((ThreadsPerBlock & (ThreadsPerBlock - 1)) != 0) {printf("ERROR: threads per block must be a power of two\n\n");  exit(-1);}
  if ((PageSize & (PageSize - 1)) != 0) {printf("ERROR: page size must be a power of two\n\n");  exit(-1);}

  const int devices = atoi(argv[2]);
  const int repeats = 2;
  CPUTimer prepTimer;
  prepTimer.start();

  // read input
  ECLgraph g = readECLgraph(argv[1]);
  printf("input: %s\n", argv[1]);
  printf("nodes: %ld\n", g.nodes);
  printf("edges: %ld\n", g.edges);
  printf("devices: %d\n", devices);
  printf("PageSize = %ld\n", PageSize);
  if (devices == 1) printf("*** Note: This code is not optimized for use with a single GPU. ***\n");

  stattype* h_nstatus = new stattype [g.nodes];  // 0: out, 0xFE: in, and LSB = 1 implies undecided
  stattype** d_nstatus_ptrs = new stattype* [devices];
  long** d_nidx_ptrs = new long* [devices];
  long** d_nlist_ptrs = new long* [devices];
  long** d_remoteNbrIndx_ptrs = new long* [devices];

  long** s_bufSize = new long* [devices];
  long** r_bufSize = new long* [devices];
  long*** s_buf1 = new long** [devices];
  long*** r_buf1 = new long** [devices];
  long*** d_s_buf1 = new long** [devices];
  long*** d_r_buf1 = new long** [devices];

  for (int i = 0; i < devices; i++) {
    s_buf1[i] = new long* [devices];
    r_buf1[i] = new long* [devices];
  }

  bool* go_again_d [devices];
  long beg [devices];  // first vertex (inclusive)
  long end [devices];  // last vertex (exclusive)
  bool flag [devices];
  int blocks [devices];
  long* d_beg [devices];
  long* d_end [devices];

  long** h_tmp_buffer = new long* [devices];

#pragma omp parallel num_threads(devices) default(none) shared(g, beg, end, d_nstatus_ptrs, go_again_d, blocks, d_beg, d_end, d_nidx_ptrs, d_nlist_ptrs, d_remoteNbrIndx_ptrs, s_buf1, s_bufSize, r_buf1, r_bufSize, d_s_buf1, d_r_buf1, p2pEnabled, h_tmp_buffer, stderr, h_BUF_SIZE, devices)
  {
    int i = omp_get_thread_num();
    cudaSetDevice(i);
    int canAccessPeer = 0;
    for (int d = 0; d < devices; d++) {
      if (d != i) {
        cudaDeviceCanAccessPeer(&canAccessPeer, i, d);
        if (!canAccessPeer) {
          printf("Device %d cannot access device %d via P2P\n", i, d);
        } else {
#pragma omp atomic write
          p2pEnabled = (cudaDeviceEnablePeerAccess(d, 0) == cudaSuccess);
        }
      }
    }

    // compute ranges
    beg[i] = ((i * g.nodes / devices) / PageSize) * PageSize;
    end[i] = (i == devices - 1) ? g.nodes : ((((i + 1) * (g.nodes / devices)) / PageSize) * PageSize);
    printf("Vertex ID range of device %d: [%ld, %ld)\n", i, beg[i], end[i]);

    const long from = g.nindex[beg[i]];
    const long to = g.nindex[end[i]];
    const long numEdges = to - from;
    long numLocalNodes = end[i] - beg[i];
    float dataSize;
    long giga = 1 << 30;
    float dataSizeNoBuf = float(numLocalNodes * sizeof(stattype) + 2 * numLocalNodes * sizeof(g.nindex[0]) + numEdges * sizeof(g.nlist[0])) / giga;  // 2 * used for counting remoteNbrIndx array

    cudaDeviceProp deviceProp;
    cudaGetDeviceProperties(&deviceProp, i);
    float availableGlobalMem = deviceProp.totalGlobalMem / (float)((1 << 30));
    printf("Global memory size = %.2f GB\n", availableGlobalMem);
    if (dataSizeNoBuf >= availableGlobalMem) {
      fprintf(stderr, "ERROR: Input requires more global memory than available.\n\n");  exit(-1);
    }

    long suggestedBufSize;
    if (devices == 1) {
      suggestedBufSize = 0;  // No inter-GPU communication buffers needed in a single-GPU system
    } else {
      suggestedBufSize = ((availableGlobalMem - dataSizeNoBuf - 1) * 1024 * 1024 * 1024) / (2 * (devices - 1) * sizeof(long));  // Each GPU needs two buffers (one to send and one to receive) per other GPU
      if (suggestedBufSize < 0) {
        suggestedBufSize = ((availableGlobalMem - dataSizeNoBuf - 0.5) * 1024 * 1024 * 1024) / (2 * (devices - 1) * sizeof(long));  // Can't leave 1GB, not enough space.
        assert(suggestedBufSize > 0);
      }
    }

#pragma omp critical
    {
      if (h_BUF_SIZE == 16384000 || h_BUF_SIZE > suggestedBufSize) {
        h_BUF_SIZE = suggestedBufSize;
        assert(h_BUF_SIZE % 2 == 0);
      }
    }

#pragma omp barrier
    if (devices == 1) {
      h_BUF_SIZE = 16384000;  // Default size retained. Note that no inter-GPU communication is involved when devices = 1
    } else if (h_BUF_SIZE < 16384000) {
      printf("Suggested new h_BUF_SIZE is %d, which is < 16384000. Exiting...\n", h_BUF_SIZE);
      exit(-1);
    }

    long bufMemSize = (devices > 1) ? (2 * (devices - 1) * h_BUF_SIZE * sizeof(long)) : 0;
#pragma omp single
    {
      printf("h_BUF_SIZE of one buffer = %ld words (%.2f GB)\n", h_BUF_SIZE, (float(h_BUF_SIZE * sizeof(long)) / giga));
      if (devices > 1) {
        printf("GPU #%d - Total buffer size of all %d buffers in this GPU: %.2f GB\n", i, 2 * (devices - 1), float(2 * (devices - 1) * h_BUF_SIZE * sizeof(long)) / giga);  // One for sending one for receiving, for each other GPU
      } else {
        printf("No inter-GPU buffers used since it is single GPU mode.\n");
      }
    }

    dataSize = float(numLocalNodes * sizeof(stattype) + 2 * numLocalNodes * sizeof(g.nindex[0]) + numEdges * sizeof(g.nlist[0]) + bufMemSize) / giga;  // 2 * used for counting remoteNbrIndx array
    printf("GPU #%d - Total memory usage: %.2f GB\n", i, dataSize);

    if (numLocalNodes > 0) {
      cudaMalloc((void **)&d_nstatus_ptrs[i], numLocalNodes * sizeof(stattype));
      CheckCuda(__LINE__);
      cudaMalloc((void**)&d_nidx_ptrs[i], (numLocalNodes + 1) * sizeof(g.nindex[0]));
      CheckCuda(__LINE__);
      cudaMemcpy(d_nidx_ptrs[i], g.nindex + beg[i], (numLocalNodes + 1) * sizeof(g.nindex[0]), cudaMemcpyHostToDevice);
      CheckCuda(__LINE__);
      cudaMalloc((void**)&d_remoteNbrIndx_ptrs[i], numLocalNodes * sizeof(g.nindex[0]));
      CheckCuda(__LINE__);
    }

    if (numEdges > 0) {
      cudaMalloc((void**)&d_nlist_ptrs[i], numEdges * sizeof(g.nlist[0]));
      CheckCuda(__LINE__);
      cudaMemcpy(d_nlist_ptrs[i], g.nlist + from, numEdges * sizeof(g.nlist[0]), cudaMemcpyHostToDevice);
      CheckCuda(__LINE__);
    }

    cudaMalloc((void**)&go_again_d[i], sizeof(bool));
    cudaMalloc((void**)&d_beg[i], devices * sizeof(long));
    cudaMalloc((void**)&d_end[i], devices * sizeof(long));
    CheckCuda(__LINE__);

    cudaFuncSetCacheConfig(init, cudaFuncCachePreferL1);
    cudaFuncSetCacheConfig(computeMIS1, cudaFuncCachePreferL1);

    blocks[i] = (numLocalNodes + ThreadsPerBlock - 1) / ThreadsPerBlock;

    for (int j = 0; j < devices; j++) {
      if (i == j) {
        s_buf1[i][j] = NULL; // Since a GPU does not send data to itself
        r_buf1[i][j] = NULL;
      } else {
        // allocate buffers for sending data from GPU i to GPU j
        cudaMalloc(&s_buf1[i][j], h_BUF_SIZE * sizeof(long));
        cudaMalloc(&r_buf1[i][j], h_BUF_SIZE * sizeof(long));
      } 
    }
    CheckCuda(__LINE__);

    cudaMalloc(&d_s_buf1[i], devices * sizeof(long*));
    cudaMemcpy(d_s_buf1[i], &(s_buf1[i][0]), devices * sizeof(long*), cudaMemcpyHostToDevice);
    cudaMalloc(&d_r_buf1[i], devices * sizeof(long*));
    cudaMemcpy(d_r_buf1[i], &(r_buf1[i][0]), devices * sizeof(long*), cudaMemcpyHostToDevice);

    CheckCuda(__LINE__);

    cudaMalloc(&s_bufSize[i], devices * sizeof(long));
    cudaMalloc(&r_bufSize[i], devices * sizeof(long));
    CheckCuda(__LINE__);

    h_tmp_buffer[i] = new long [h_BUF_SIZE];

#pragma omp barrier
    // Prepare copies of beg and end arrays in each GPU
    cudaMemcpyAsync(d_beg[i], beg, devices * sizeof(long), cudaMemcpyHostToDevice);
    cudaMemcpyAsync(d_end[i], end, devices * sizeof(long), cudaMemcpyHostToDevice);
    cudaDeviceSynchronize();
  }

  for (int i = 0; i < devices; i++) {
    cudaSetDevice(i);
    cudaMemcpyToSymbol(BUF_SIZE, &h_BUF_SIZE, sizeof(long));
  }

  double prepTime = prepTimer.elapsed();
  printf("preparation time: %.6f s\n", prepTime);
  printf("p2pEnabled = %s\n", p2pEnabled ? "true" : "false");
  printf("----------------------\n\n");

  int itr = 0;
  CPUTimer timer;
  timer.start();

#pragma omp parallel num_threads(devices) default(none) shared(g, beg, end, go_again_d, d_nstatus_ptrs, itr, flag, blocks, d_beg, d_end, d_nidx_ptrs, d_nlist_ptrs, d_remoteNbrIndx_ptrs, s_buf1, d_s_buf1, s_bufSize, r_buf1, d_r_buf1, r_bufSize, p2pEnabled, h_tmp_buffer, h_BUF_SIZE, devices, repeats)
  {
    int id = omp_get_thread_num();
    cudaSetDevice(id);
    const long nidx_0 = g.nindex[beg[id]];
    stattype* d_nstatus = d_nstatus_ptrs[id];
    long* d_nindx = d_nidx_ptrs[id];
    long* d_nlist = d_nlist_ptrs[id];
    long* d_remoteNbrIndex = d_remoteNbrIndx_ptrs[id];
    long* host_buffer = h_tmp_buffer[id];
    const long numLocalNodes = end[id] - beg[id];
    init<<<blocks[id], ThreadsPerBlock>>>(d_nstatus, numLocalNodes);
    initRemoteNbrIndxArr<<<blocks[id], ThreadsPerBlock>>>(d_remoteNbrIndex, numLocalNodes, d_nindx, nidx_0);
    cudaDeviceSynchronize();
#pragma omp barrier

    bool anyFlag;
    do {
      if (id == 0) {
        itr++;
      }
#pragma omp barrier

      runLocalRound(id, devices, repeats, s_bufSize[id], blocks[id], d_beg[id], d_end[id], d_nindx, d_nlist, d_nstatus, go_again_d[id], d_s_buf1[id], d_remoteNbrIndex, nidx_0, beg[id], end[id]);
      sendDataToReceivers(id, devices, s_buf1, s_bufSize, r_buf1, r_bufSize, p2pEnabled, host_buffer);
      cudaMemcpy(&flag[id], go_again_d[id], sizeof(bool), cudaMemcpyDeviceToHost);  // Implied CDS(); required.
#pragma omp barrier

      setToOut(id, r_buf1, r_bufSize, d_nstatus, devices, beg[id]);
#pragma omp barrier

      anyFlag = checkIfWorkLeft(flag, devices);
      if (!anyFlag) break;  

      if (flag[id]) {
        resetBufferSize(s_bufSize[id], devices);
        askRemoteNbrStatus<<<blocks[id], ThreadsPerBlock>>>(d_beg[id], d_end[id], d_nindx, d_nlist, d_nstatus, id, devices, d_s_buf1[id], s_bufSize[id], d_remoteNbrIndex, nidx_0, beg[id], end[id]);
        cudaDeviceSynchronize();
        saturateSize_kernel<<<1,1>>>(id, s_bufSize[id], devices);
        // send the prepared pair data to the target GPUs' receive-buffers
        sendDataToReceivers(id, devices, s_buf1, s_bufSize, r_buf1, r_bufSize, p2pEnabled, host_buffer);
      }
#pragma omp barrier

      // Go over the buffers, examine the status of the second element v of each pair (u,v). If v is out, insert u to another buffer for sending back. If v is not out, no need to send any info back.
      resetBufferSize(s_bufSize[id], devices);  // Reset indices before writing response
      for (int sender = 0; sender < devices; sender++) {
        if (id != sender) {
          // read the pairBuffer written to by sender, for id, and write the response in the buffer of id to sender
          int n;
          cudaMemcpy(&n, (r_bufSize[id] + sender), sizeof(long), cudaMemcpyDeviceToHost);
          readPairBuffersAndProcess<<<(n + ThreadsPerBlock - 1) / ThreadsPerBlock, ThreadsPerBlock>>>(r_buf1[id][sender], (r_bufSize[id] + sender), s_buf1[id][sender], (s_bufSize[id] + sender), d_nstatus, beg[id]);  
        }
      }
      saturateSize_kernel<<<1,1>>>(id, s_bufSize[id], devices);
#pragma omp barrier
      sendDataToReceivers(id, devices, s_buf1, s_bufSize, r_buf1, r_bufSize, p2pEnabled, host_buffer);
#pragma omp barrier

      // Each GPU goes over the response data for it. If a local vertex u is in the response, it means that the remote nbr u was checking is out. Increment the remote nbr index of u
      for (int sender = 0; sender < devices; sender++) {
        if (id != sender) {
          int n;
          cudaMemcpy(&n, (r_bufSize[id] + sender), sizeof(long), cudaMemcpyDeviceToHost);
          readResponseAndProcess<<<(n + ThreadsPerBlock - 1) / ThreadsPerBlock, ThreadsPerBlock>>>(r_buf1[id][sender], (r_bufSize[id] + sender), d_remoteNbrIndex, beg[id]);
        }
      }
      cudaDeviceSynchronize();
#pragma omp barrier

      // run local MIS round again
      runLocalRound(id, devices, repeats, s_bufSize[id], blocks[id], d_beg[id], d_end[id], d_nindx, d_nlist, d_nstatus, go_again_d[id], d_s_buf1[id], d_remoteNbrIndex, nidx_0, beg[id], end[id]);
      sendDataToReceivers(id, devices, s_buf1, s_bufSize, r_buf1, r_bufSize, p2pEnabled, host_buffer);
      cudaMemcpy(&flag[id], go_again_d[id], sizeof(bool), cudaMemcpyDeviceToHost);
#pragma omp barrier

      setToOut(id, r_buf1, r_bufSize, d_nstatus, devices, beg[id]);
#pragma omp barrier

      anyFlag = checkIfWorkLeft(flag, devices);
    } while (anyFlag);
  }


  double runtime = timer.elapsed();
  printf("runtime: %.6f s\n", runtime);
  printf("iterations: %d\n", itr);
  printf("throughput: %.6f Mnodes/s\n", g.nodes * 0.000001 / runtime);
  printf("throughput: %.6f Medges/s\n", g.edges * 0.000001 / runtime);


  CPUTimer verifyTimer;
  verifyTimer.start();

#pragma omp parallel num_threads(devices) default(none) shared(beg, end, d_nstatus_ptrs, h_nstatus)
  {
    int id = omp_get_thread_num();
    cudaSetDevice(id);
    stattype* d_nstatus = d_nstatus_ptrs[id];
    const long numLocalNodes = end[id] - beg[id];
    cudaMemcpy(h_nstatus + beg[id], d_nstatus, numLocalNodes * sizeof(stattype), cudaMemcpyDeviceToHost);
  }
  // determine and print set size
  long count = 0;
  for (long v = 0; v < g.nodes; v++) {
    if (h_nstatus[v] == in) {
      count++;
    }
  }
  printf("elements in set: %d (%.1f%%)\n", count, 100.0 * count / g.nodes);  fflush(stdout);

  // verify result
  for (long v = 0; v < g.nodes; v++) {
    if ((h_nstatus[v] != in) && (h_nstatus[v] != out)) {fprintf(stderr, "ERROR: found undecided node %d\n", v);  exit(-1);}
    if (h_nstatus[v] == in) {
      for (long i = g.nindex[v]; i < g.nindex[v + 1]; i++) {
        if (h_nstatus[g.nlist[i]] == in) {fprintf(stderr, "ERROR: found adjacent nodes in MIS\n");  exit(-1);}
      }
    } else {
      int flag = 0;
      for (long i = g.nindex[v]; i < g.nindex[v + 1]; i++) {
        if (h_nstatus[g.nlist[i]] == in) {
          flag = 1;
          break;
        }
      }
      if (flag == 0) {fprintf(stderr, "ERROR: set is not maximal\n");  exit(-1);}
    }
  }
  printf("verification passed\n");  fflush(stdout);
  double verify_time = verifyTimer.elapsed();
  printf("Time to copy result to host and verify: %.6f s\n", verify_time);
  printf("--------------------\n\n");

  // clean up
  freeECLgraph(g);
  for (int i = 0; i < devices; i++) {
    cudaSetDevice(i);
    cudaFree(go_again_d[i]);
  }
  for (int i = 0; i < devices; i++) {
    for (int j = 0; j < devices; j++) {
      if (i != j)
        cudaFree(s_buf1[i][j]);
      cudaFree(r_buf1[i][j]);
    }
    cudaFree(d_s_buf1[i]);
    cudaFree(d_r_buf1[i]);
    cudaFree(s_bufSize[i]);
    cudaFree(r_bufSize[i]);

    cudaFree(d_nstatus_ptrs[i]);
    cudaFree(d_nidx_ptrs[i]);
    cudaFree(d_nlist_ptrs[i]);
    cudaFree(d_remoteNbrIndx_ptrs[i]);

    delete [] s_buf1[i];
    delete [] r_buf1[i];
    delete [] h_tmp_buffer[i];
  }

  delete [] s_bufSize;
  delete [] r_bufSize;
  delete [] d_s_buf1;
  delete [] d_r_buf1;
  delete [] s_buf1;
  delete [] r_buf1;
  delete [] h_nstatus;
  delete [] d_nstatus_ptrs;
  delete [] d_nidx_ptrs;
  delete [] d_nlist_ptrs;
  delete [] d_remoteNbrIndx_ptrs;
  delete [] h_tmp_buffer;

  return 0;
}
