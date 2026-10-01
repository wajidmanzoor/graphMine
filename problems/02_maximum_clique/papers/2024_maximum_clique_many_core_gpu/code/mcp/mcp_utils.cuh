#pragma once
#include "../include/csrcoo.cuh"
#include "../include/defs.h"
#include "../include/queue.cuh"
#include "parameter.cuh"
#include <cuda/semaphore>

#define current_level (sh.l - 2)
#define next_level (sh.l - 1)
#define warp_current_level (wsh[lh.wx].l - 3)
#define warp_next_level (wsh[lh.wx].l - 2)
#define warpIdx (lh.wx)
#define laneIdx (lh.lx)
#define degree Xx_aux_shared
#define min_bounds(i) current_bucket[i]
#define max_bounds(i) next_bucket[i]
#define first_thread_block if (threadIdx.x == 0)
#define fetch(shared, global) if (threadIdx.x == 0) shared = global
#define fetch_both(shared1, global1, shared2, global2) if (threadIdx.x == 0) {shared1 = global1; shared2 = global2;}
#define fetch_warp(shared, global, warp_id) if (laneIdx == 0) shared[warp_id] = global

namespace mcp 
{

template <typename T>
struct GLOBAL_HANDLE {
  graph::COOCSRGraph_d<T> gsplit;
  T iteration_limit;
  T *level_candidate;
  T *encoded_induced_subgraph;

  T *P;
  T *B;
  T *A;
  T *C;
  T *Cmax;
  T *level_pointer;
  T *Xx_aux;
  T *current, *next;
  T *ordering;
  T *core;
  T *Iset, *Iset_count;

  bool *colored;

  volatile uint32_t *Cmax_size;
  volatile T *cut_by_kcore_l1;
  volatile T *cut_by_color;
  volatile T *cut_by_color_l1;
  volatile T *cut_by_renumber_l1;
  volatile float *avg_subgraph_density;
  volatile float *max_subgraph_density;
  volatile uint32_t *avg_subgraph_width;
  volatile uint32_t *max_subgraph_width;
  volatile uint32_t *total_subgraph;
  volatile unsigned long long *branches;
  
  cuda::atomic<uint32_t, cuda::thread_scope_device> *work_ready;
  cuda::binary_semaphore<cuda::thread_scope_device> *max_clique_sem;
  uint32_t *global_message;
  volatile T *work_stealing;

  T stride;
  bool verbose;
  bool eval;
};

template<typename T>
struct LOCAL_HANDLE {
  uint numPartitions, gwx, wx, lx, partMask;
  int maskBlock, maskIndex, newIndex, sameBlockMask;
  int colMaskBlock, colMaskIndex, colNewIndex;
};

#define __warp__(x) x[BLOCK_DIM_X / CPARTSIZE]
template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
struct SHARED_HANDLE {
 
  T l, base_l, sm_block_id, root_sm_block_id;
  uint32_t state, worker_pos, shared_other_sm_block_id;
  T i, src, srcStart, srcLen, usrcStart, usrcLen;

  T num_divs_local;
  T *encode;
  T *pl, *bl, *al;
  T *c;
  T *level_pointer_index;
  T *Xx_aux_shared, Xx_aux_sz;
  T *current_bucket, *next_bucket, current_bucket_sz, next_bucket_sz;
  T *cores, *ordering;
  T *Iset, *Iset_count;

  bool *colored;
  T max_core_l1;

  T lastMask_i, lastMask_ii;
  T to_col[MAX_DEGEN / 32];
  T to_bl[MAX_DEGEN / 32];

  uint32_t __warp__(queue);
  cuda::atomic<uint32_t, cuda::thread_scope_block> __warp__(tickets), head, tail;
  bool fork;
};

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
struct WARP_SHARED_HANDLE {
 
  T l, base_l, sm_warp_id, root_sm_warp_id, root_sm_block_id;
  uint32_t state, worker_pos, shared_other_sm_warp_id;
  T i, usrcLen;

  T num_divs_local;
  T *encode;
  T *pl, *bl, *al;
  T *level_pointer_index;
  T *Xx_aux_shared, Xx_aux_sz;

  bool *colored;

  T lastMask_i, lastMask_ii;
  T to_col[MAX_DEGEN / 32];
    
  bool fork;
};

// Taken from the previous work
namespace graph
{

  template <typename T>
  __host__ __device__ T binary_search(const T *arr, const T lt, const T rt, const T searchVal, bool &found)
  {
    T left = lt, right = rt;
    found = false;
    while (left < right)
    {
      const T mid = (left + right) / 2;
      T val = arr[mid];
      if (val == searchVal)
      {
        found = true;
        return mid;
      }
      bool pred = val < searchVal;
      if (pred)
      {
        left = mid + 1;
      }
      else
      {
        right = mid;
      }
    }
    return left;
  }


    template <typename T, uint CPARTSIZE = 32>
  __device__ __forceinline__ uint64 warp_sorted_count_and_encode_full(
      const T *const A, const size_t aSz, T *B,
      T bSz, T j, T num_divs_local, T *encode)
  {
    const int _warpIdx = threadIdx.x / CPARTSIZE; // which warp in thread block
    const int _laneIdx = threadIdx.x % CPARTSIZE; // which thread in warp
    // cover entirety of A with warp
    for (T i = _laneIdx; i < aSz; i += CPARTSIZE)
    {
      const T searchVal = A[i];
      bool found = false;
      const T lb = graph::binary_search<T>(B, 0, bSz, searchVal, found);
      if (found)
      {
        ////////////////////////////// Device function ///////////////////////
        T chunk_index = i / 32; // 32 here is the division size of the encode
        T inChunkIndex = i % 32;
        atomicOr(&encode[j * num_divs_local + chunk_index], 1 << inChunkIndex);

        T chunk_index1 = j / 32; // 32 here is the division size of the encode
        T inChunkIndex1 = j % 32;
        atomicOr(&encode[i * num_divs_local + chunk_index1], 1 << inChunkIndex1);
        /////////////////////////////////////////////////////////////////////
      }
    }
    return 0;
  }

  template <typename T, uint CPARTSIZE = 32>
  __device__ __forceinline__ uint64 warp_sorted_count_and_encode_full_stats(
      const T *const A, const size_t aSz, T *B,
      T bSz, T j, T num_divs_local, T *encode, uint32_t &edges)
  {
    const int _warpIdx = threadIdx.x / CPARTSIZE; // which warp in thread block
    const int _laneIdx = threadIdx.x % CPARTSIZE; // which thread in warp
    // cover entirety of A with warp
    for (T i = _laneIdx; i < aSz; i += CPARTSIZE)
    {
      const T searchVal = A[i];
      bool found = false;
      const T lb = graph::binary_search<T>(B, 0, bSz, searchVal, found);
      if (found)
      {
        ////////////////////////////// Device function ///////////////////////
        T chunk_index = i / 32; // 32 here is the division size of the encode
        T inChunkIndex = i % 32;
        atomicOr(&encode[j * num_divs_local + chunk_index], 1 << inChunkIndex);

        T chunk_index1 = j / 32; // 32 here is the division size of the encode
        T inChunkIndex1 = j % 32;
        atomicOr(&encode[i * num_divs_local + chunk_index1], 1 << inChunkIndex1);
        /////////////////////////////////////////////////////////////////////
        atomicAdd(&edges, 2);
      }
    }
    return 0;
  }

};

template <typename T, uint CPARTSIZE>
__device__ __forceinline__ void reduce_part(T partMask, uint64 &warpCount)
{
  for (int i = CPARTSIZE / 2; i >= 1; i /= 2)
    warpCount += __shfl_down_sync(partMask, warpCount, i);
}

template <typename T, uint CPARTSIZE>
__device__ __forceinline__ void reduce_part(T partMask, T &warpCount)
{
  for (int i = CPARTSIZE / 2; i >= 1; i /= 2)
    warpCount += __shfl_down_sync(partMask, warpCount, i);
}

template <typename T, uint CPARTSIZE>
__device__ __forceinline__ void reduce_part_min(T partMask, T &warpMin)
{ 
  warpMin = __reduce_min_sync(__activemask(), warpMin);
}

template <typename T, uint CPARTSIZE>
__device__ __forceinline__ void reduce_part_max(T partMask, T &warpMin)
{ 
  warpMin = __reduce_max_sync(partMask, warpMin);
}

__device__ __forceinline__ void wait_for_donor(
    cuda::atomic<uint32_t, cuda::thread_scope_device> &work_ready, uint32_t &shared_state,
    queue_callee(queue, tickets, head, tail))
{
  uint32_t ns = 8;
  do
  {
    if (work_ready.load(cuda::memory_order_relaxed))
    {
      
      if (work_ready.load(cuda::memory_order_acquire))
      {
        shared_state = 2;
        work_ready.store(0, cuda::memory_order_relaxed);
        break;
      }
    }
    else if (queue_full(queue, tickets, head, tail, CB))
    {
      shared_state = 100;
      break;
    }
  } while (ns = my_sleep(ns));
}

__device__ __forceinline__ void wait_for_donor_warp(
    cuda::atomic<uint32_t, cuda::thread_scope_device> &work_ready, uint32_t &shared_state,
    queue_callee(queue, tickets, head, tail))
{
  uint32_t ns = 8;
  do
  {
    if (work_ready.load(cuda::memory_order_relaxed))
    {
      
      if (work_ready.load(cuda::memory_order_acquire))
      {
        shared_state = 2;
        work_ready.store(0, cuda::memory_order_relaxed);
        break;
      }
    }
    else if (queue_full(queue, tickets, head, tail, WARPS))
    {
      shared_state = 100;
      break;
    }
  } while (ns = my_sleep(ns));
}

__device__ __forceinline__ void wait_for_donor_warp_(
    cuda::atomic<uint32_t, cuda::thread_scope_device> &work_ready, uint32_t &block_shared_state, uint32_t &warp_shared_state,
    queue_callee(queue, tickets, head, tail))
{
  uint32_t ns = 8;
  do
  {
    if (work_ready.load(cuda::memory_order_relaxed))
    {
      
      if (work_ready.load(cuda::memory_order_acquire))
      {
        warp_shared_state = 2;
        work_ready.store(0, cuda::memory_order_relaxed);
        break;
      }
    }
    else if (queue_full(queue, tickets, head, tail, WARPS))
    {
      warp_shared_state = 100;
      block_shared_state = 100;
      break;
    }
  } while (ns = my_sleep(ns));
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void setup_stack_first_level_psanse(
    GLOBAL_HANDLE<T> &gh, SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  if (threadIdx.x == 0)
  {
    sh.src = sh.i; // Gets the vertex
    sh.srcStart = gh.gsplit.splitPtr[sh.src]; // Gets the start index of the second part on the column index array
    sh.srcLen = gh.gsplit.rowPtr[sh.src + 1] - sh.srcStart; // Gets the length of the second part of the neighbourhood
    sh.usrcStart = gh.gsplit.rowPtr[sh.src]; // Gets the start index on the first part of the column index array
    sh.usrcLen = gh.gsplit.splitPtr[sh.src] - sh.usrcStart; // Get the length of the first part of the neighbourhood

    sh.num_divs_local = ((sh.usrcLen) + 32 - 1) / 32; // For excess the numbers of register to contein the neighbourhood of the chosen vertex
    auto encode_offset = sh.sm_block_id * (MAXDEG * NUMDIVS);
    sh.encode = &gh.encoded_induced_subgraph[encode_offset];

    auto level_offset = sh.sm_block_id * NUMDIVS * (MAXLEVEL);
    sh.pl = &gh.P[level_offset];
    sh.bl = &gh.B[level_offset];
    sh.al = &gh.A[level_offset];
    
    size_t Xx_offset = sh.sm_block_id * MAXDEG;
    sh.Xx_aux_shared = &gh.Xx_aux[Xx_offset];
    sh.current_bucket = &gh.current[Xx_offset];
    sh.next_bucket = &gh.next[Xx_offset];
    sh.ordering = &gh.ordering[Xx_offset];

    size_t clique_offset = sh.sm_block_id * MAXLEVEL;
    if (gh.eval) sh.c = &gh.C[clique_offset];
    
    auto level_item_offset = sh.sm_block_id * (MAXLEVEL);
    sh.level_pointer_index = &gh.level_pointer[level_item_offset];
    sh.colored = &gh.colored[level_item_offset];
    
    sh.level_pointer_index[0] = 0;
    sh.l = sh.base_l = 2;

    sh.colored[current_level] = false;

    sh.lastMask_i = (sh.usrcLen) >> 5;
    sh.lastMask_ii = (1 << ((sh.usrcLen) & 0x1F)) - 1; // Takes the last 5 bit so multiple of 32
  }
  __syncthreads();

}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void setup_stack_first_level_psanse_(
    GLOBAL_HANDLE<T> &gh, SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  if (threadIdx.x == 0)
  {
    sh.src = sh.i; // Gets the vertex
    sh.srcStart = gh.gsplit.splitPtr[sh.src]; // Gets the start index of the second part on the column index array
    sh.srcLen = gh.gsplit.rowPtr[sh.src + 1] - sh.srcStart; // Gets the length of the second part of the neighbourhood
    sh.usrcStart = gh.gsplit.rowPtr[sh.src]; // Gets the start index on the first part of the column index array
    sh.usrcLen = gh.gsplit.splitPtr[sh.src] - sh.usrcStart; // Get the length of the first part of the neighbourhood

    sh.num_divs_local = ((sh.usrcLen) + 32 - 1) / 32; // For excess the numbers of register to contein the neighbourhood of the chosen vertex
    auto encode_offset = sh.sm_block_id * (MAXDEG * NUMDIVS);
    sh.encode = &gh.encoded_induced_subgraph[encode_offset];
    
    size_t bucket_offset = sh.sm_block_id * MAXDEG;
    size_t Xx_offset = sh.sm_block_id * MAXDEG * NUMPART;
    sh.Xx_aux_shared = &gh.Xx_aux[Xx_offset];
    sh.current_bucket = &gh.current[bucket_offset];
    sh.next_bucket = &gh.next[bucket_offset];
    sh.ordering = &gh.ordering[bucket_offset];

    sh.l = 2;

    sh.lastMask_i = (sh.usrcLen) >> 5;
    sh.lastMask_ii = (1 << ((sh.usrcLen) & 0x1F)) - 1; // Takes the last 5 bit so multiple of 32
  }
  __syncthreads();

}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void setup_warp_stack_second_level(
    GLOBAL_HANDLE<T> &gh, LOCAL_HANDLE<T> &lh, SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
    WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh)
{
  if (lh.lx == 0)
  {
    wsh.usrcLen = sh.usrcLen;
    wsh.num_divs_local = sh.num_divs_local;
    wsh.encode = sh.encode;
    wsh.state = 0;
		

    auto level_offset = wsh.sm_warp_id * NUMDIVS * MAXLEVEL;
    wsh.pl = &gh.P[level_offset];
    wsh.bl = &gh.B[level_offset];
    wsh.al = &gh.A[level_offset];
    
    size_t Xx_offset = wsh.sm_warp_id * MAXDEG;
    wsh.Xx_aux_shared = &gh.Xx_aux[Xx_offset];
    
    auto level_item_offset = wsh.sm_warp_id * MAXLEVEL;
    wsh.level_pointer_index = &gh.level_pointer[level_item_offset];
    wsh.colored = &gh.colored[level_item_offset];
    wsh.l = wsh.base_l = 3;

    wsh.lastMask_i = (wsh.usrcLen) >> 5;
    wsh.lastMask_ii = (1 << ((wsh.usrcLen) & 0x1F)) - 1; // Takes the last 5 bit so multiple of 32
  }
  __syncwarp();

}



template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void setup_stack_first_level_psanse_recolor(
    GLOBAL_HANDLE<T> &gh, SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  if (threadIdx.x == 0)
  {
    sh.src = sh.i; // Gets the vertex
    sh.srcStart = gh.gsplit.splitPtr[sh.src]; // Gets the start index of the second part on the column index array
    sh.srcLen = gh.gsplit.rowPtr[sh.src + 1] - sh.srcStart; // Gets the length of the second part of the neighbourhood
    sh.usrcStart = gh.gsplit.rowPtr[sh.src]; // Gets the start index on the first part of the column index array
    sh.usrcLen = gh.gsplit.splitPtr[sh.src] - sh.usrcStart; // Get the length of the first part of the neighbourhood

    sh.num_divs_local = ((sh.usrcLen) + 32 - 1) / 32; // For excess the numbers of register to contein the neighbourhood of the chosen vertex
    auto encode_offset = sh.sm_block_id * (MAXDEG * NUMDIVS);
    sh.encode = &gh.encoded_induced_subgraph[encode_offset];

    auto level_offset = sh.sm_block_id * NUMDIVS * (MAXLEVEL);
    sh.pl = &gh.P[level_offset];
    sh.bl = &gh.B[level_offset];
    sh.al = &gh.A[level_offset];
    sh.Iset = &gh.Iset[level_offset];
    
    size_t Xx_offset = sh.sm_block_id * MAXDEG;
    sh.Xx_aux_shared = &gh.Xx_aux[Xx_offset];
    sh.current_bucket = &gh.current[Xx_offset];
    sh.next_bucket = &gh.next[Xx_offset];
    sh.ordering = &gh.ordering[Xx_offset];
    
    auto level_item_offset = sh.sm_block_id * (MAXLEVEL);
    sh.level_pointer_index = &gh.level_pointer[level_item_offset];
    sh.colored = &gh.colored[level_item_offset];
    
    sh.level_pointer_index[0] = 0;
    sh.l = sh.base_l = 2;

    sh.colored[current_level] = false;

    sh.lastMask_i = (sh.usrcLen) >> 5;
    sh.lastMask_ii = (1 << ((sh.usrcLen) & 0x1F)) - 1; // Takes the last 5 bit so multiple of 32
  }
  __syncthreads();

}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void setup_stack_first_level_tomita(
    GLOBAL_HANDLE<T> &gh, SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  if (threadIdx.x == 0)
  {
    sh.src = sh.i; // Gets the vertex
    sh.srcStart = gh.gsplit.splitPtr[sh.src]; // Gets the start index of the second part on the column index array
    sh.srcLen = gh.gsplit.rowPtr[sh.src + 1] - sh.srcStart; // Gets the length of the second part of the neighbourhood
    sh.usrcStart = gh.gsplit.rowPtr[sh.src]; // Gets the start index on the first part of the column index array
    sh.usrcLen = gh.gsplit.splitPtr[sh.src] - sh.usrcStart; // Get the length of the first part of the neighbourhood

    sh.num_divs_local = ((sh.usrcLen) + 32 - 1) / 32; // For excess the numbers of register to contein the neighbourhood of the chosen vertex
    auto encode_offset = sh.sm_block_id * (MAXDEG * NUMDIVS);
    sh.encode = &gh.encoded_induced_subgraph[encode_offset];

    auto level_offset = sh.sm_block_id * NUMDIVS * (MAXLEVEL);
    sh.pl = &gh.P[level_offset];
    sh.bl = &gh.B[level_offset];
    sh.al = &gh.A[level_offset];

    auto iset_offset = sh.sm_block_id * (MAXDEG) * MAXLEVEL;
    sh.Iset = &gh.Iset[iset_offset];

    size_t Xx_offset = sh.sm_block_id * MAXDEG;
    sh.Xx_aux_shared = &gh.Xx_aux[Xx_offset];
    sh.current_bucket = &gh.current[Xx_offset];
    sh.next_bucket = &gh.next[Xx_offset];
    sh.ordering = &gh.ordering[Xx_offset];

    auto level_item_offset = sh.sm_block_id * (MAXLEVEL);
    sh.level_pointer_index = &gh.level_pointer[level_item_offset];
    sh.colored = &gh.colored[level_item_offset];
    sh.Iset_count = &gh.Iset_count[level_item_offset];

    sh.level_pointer_index[0] = 0;
    sh.l = sh.base_l = 2;

    sh.colored[current_level] = false;

    sh.lastMask_i = (sh.usrcLen) >> 5;
    sh.lastMask_ii = (1 << ((sh.usrcLen) & 0x1F)) - 1; // Takes the last 5 bit so multiple of 32
  }
  __syncthreads();

}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void reduce_stack_first_level(
    GLOBAL_HANDLE<T> &gh, SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  if (threadIdx.x == 0)
  {
    sh.num_divs_local = (sh.usrcLen + 32 - 1) / 32;
		sh.lastMask_i = sh.usrcLen >> 5;
		sh.lastMask_ii = (1 << (sh.usrcLen & 0x1F)) - 1;
  }
  __syncthreads();
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_kcore_first_level(
  LOCAL_HANDLE<T> &lh,
  SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
  GLOBAL_HANDLE<T> &gh, const T& num_divs_local, const T const* encode, const T& max_clq)
{

  __shared__ int cur_core, min_degree, todos, ordering_sz;
  __shared__ int currents;
  auto &g = gh.gsplit;
  
  first_thread_block
  {
    min_degree = sh.usrcLen;
    todos = sh.usrcLen;
    sh.current_bucket_sz = 0;
    sh.next_bucket_sz = 0;
    ordering_sz = 0;
  }
  __syncthreads();

  // Computes the degrees and get the min
  for (T j = lh.wx; j < sh.usrcLen; j += lh.numPartitions)
  {
    T _degree = 0;
    for (T k = lh.lx; k < num_divs_local; k += CPARTSIZE)
    {
      _degree += __popc(encode[j * num_divs_local + k]);
    }

    __syncwarp();

    reduce_part<T, CPARTSIZE>(lh.partMask, _degree);

    __syncwarp();

    if (lh.lx == 0)
    {
      sh.degree[j] = _degree;
      atomicMin(&min_degree, _degree);
    }

    __syncwarp();
  }

  __syncthreads();

  fetch(cur_core, min_degree);

  __syncthreads();


  while (todos > 0)
  {

    fetch_both(sh.current_bucket_sz, 0, sh.next_bucket_sz, 0);

    __syncthreads();
      
    // Filter the min degrees vertices
    for (T j = threadIdx.x; j < sh.usrcLen; j += BLOCK_DIM_X)
      if (sh.degree[j] == cur_core)
        sh.current_bucket[atomicAdd(&sh.current_bucket_sz, 1)] = j;

    __syncthreads();

    fetch(currents, sh.current_bucket_sz);

    __syncthreads();

    while (currents > 0)
    {
      
      first_thread_block
      {
        todos -= currents;
        sh.next_bucket_sz = 0;
      }

      __syncthreads();

      // For each candidate inside the bucket
      for (T j = lh.wx; j < sh.current_bucket_sz; j += lh.numPartitions)
      {
        const T node = sh.current_bucket[j];

        if (lh.lx == 0 && cur_core + 1 >= max_clq) {
          sh.ordering[atomicAdd(&ordering_sz, 1)] = g.colInd[sh.usrcStart + node];
        }
        __syncwarp();

        for (T k = lh.lx; k < sh.usrcLen; k += CPARTSIZE)
        {
          if (encode[node * num_divs_local + (k >> 5)] & (1 << (k & 0x1F)))
          {
            const T neighbour = k;
            if (sh.degree[neighbour] > cur_core) 
            {
              T old = atomicSub(&sh.degree[neighbour], 1);
              if (old - 1 == cur_core)
                sh.next_bucket[atomicAdd(&sh.next_bucket_sz, 1)] = neighbour;
            }
          }
        }
        __syncwarp();
      }

      __syncthreads();

      // Swap current with next
      first_thread_block
      { 
        T* tmp_ptr = sh.current_bucket;
        sh.current_bucket = sh.next_bucket;
        sh.next_bucket = tmp_ptr;

        T tmp = sh.current_bucket_sz;
        sh.current_bucket_sz = sh.next_bucket_sz;
        sh.next_bucket_sz = tmp;

        currents = sh.current_bucket_sz;
      }

      __syncthreads();

    }

    first_thread_block
      cur_core++;

    __syncthreads();

  }

  fetch_both(sh.usrcLen, ordering_sz, sh.max_core_l1, cur_core - 1);
  __syncthreads();

}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void reverse_degeneracy_ordering_first_level(
  LOCAL_HANDLE<T> &lh,
  SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
  GLOBAL_HANDLE<T> &gh)
{
  for (T j = threadIdx.x; j < sh.usrcLen / 2; j += BLOCK_DIM_X)
  {
    T tmp = sh.ordering[j];
    sh.ordering[j] = sh.ordering[sh.usrcLen - j - 1];
    sh.ordering[sh.usrcLen - j - 1] = tmp;

    // tmp = sh.cores[j];
    // sh.cores[j] = sh.cores[sh.usrcLen - j - 1];
    // sh.cores[sh.usrcLen - j - 1] = tmp;
  }

  __syncthreads();
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void encode_clear(
    LOCAL_HANDLE<T> &lh, SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> & sh, const T &lim)
{
  for (T j = lh.wx; j < lim; j += lh.numPartitions)
    for (T k = lh.lx; k < sh.num_divs_local; k += CPARTSIZE)
      sh.encode[j * sh.num_divs_local + k] = 0x00;
  __syncthreads();
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void iset_clear(
    LOCAL_HANDLE<T> &lh, SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> & sh, const T &lim)
{
  for (T j = lh.wx; j < lim; j += lh.numPartitions)
    for (T k = lh.lx; k < sh.num_divs_local; k += CPARTSIZE)
      sh.Iset[j * sh.num_divs_local + k] = 0x00;
  __syncthreads();
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_P_intersection_to_first_level(
  SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
  const T& usrcLen, const T num_divs_local, T* cur_pl)
{

  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
  {
    const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;
    cur_pl[j] = m;
  }
 
  __syncthreads();

}


template <typename T>
__device__ __forceinline__ void reduce_or(LOCAL_HANDLE<T>& lh, unsigned* sh_ptr, const unsigned val)
{
  const unsigned any = __any_sync(lh.partMask, val);

  if (lh.lx == 0)
    atomicOr(sh_ptr, any);

}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_P_intersection_for_next_level(
    LOCAL_HANDLE<T> &lh,
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, const T& num_divs_local,
    const T const* cur_bl, const T const* cur_al, T* cur_pl)
{
  
  const T prevCand = lh.newIndex;
  const T prevCandBlock = prevCand >> 5;
  for (T j = threadIdx.x; j < num_divs_local; j += blockDim.x)
  {
    const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;
    const T t = sh.encode[lh.newIndex * num_divs_local + j];
    const T prevCandMask = (j > prevCandBlock) ? 0x00000000 : 
      ((j < prevCandBlock) ? 0xFFFFFFFF : ((1 << (prevCand & 0x1F)) - 1));
    const T bua = (cur_bl[j] & prevCandMask) | cur_al[j];
    const T tbua = bua & m & t;
    cur_pl[j] = tbua;
  }

  __syncthreads();
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_warp_P_intersection_second_level(
    LOCAL_HANDLE<T> &lh,
    WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh, const T& num_divs_local,
    const T const* cur_bl, const T const* cur_al, T* cur_pl)
{
  
  const T prevCand = wsh.i;
  const T prevCandBlock = prevCand >> 5;
  for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
  {
    const T m = (j == wsh.lastMask_i) ? wsh.lastMask_ii : 0xFFFFFFFF;
    const T t = wsh.encode[wsh.i * num_divs_local + j];
    const T prevCandMask = (j > prevCandBlock) ? 0x00000000 : 
      ((j < prevCandBlock) ? 0xFFFFFFFF : ((1 << (prevCand & 0x1F)) - 1));
    const T bua = (cur_bl[j] & prevCandMask) | cur_al[j];
    const T tbua = bua & m & t;
    cur_pl[j] = tbua;
  }

  __syncwarp();
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_warp_P_intersection_for_next_level_(
    LOCAL_HANDLE<T> &lh,
   WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh, const T& num_divs_local,
    const T const* cur_bl, const T const* cur_al, T* cur_pl)
{
  
  const T prevCand = lh.newIndex;
  const T prevCandBlock = prevCand >> 5;
  for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
  {
    const T m = (j == wsh.lastMask_i) ? wsh.lastMask_ii : 0xFFFFFFFF;
    const T t = wsh.encode[lh.newIndex * num_divs_local + j];
    const T prevCandMask = (j > prevCandBlock) ? 0x00000000 : 
      ((j < prevCandBlock) ? 0xFFFFFFFF : ((1 << (prevCand & 0x1F)) - 1));
    const T bua = (cur_bl[j] & prevCandMask) | cur_al[j];
    const T tbua = bua & m & t;
    cur_pl[j] = tbua;
  }

  __syncwarp();
}



template <bool WL, typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void get_candidates_for_next_level(
    LOCAL_HANDLE<T> &lh,
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, const T &level,
    const T const* cur_bl)
{

  __syncthreads();
  const T nextCand = sh.level_pointer_index[level];
  const T nextCandBlock = nextCand >> 5;
  for (T j = threadIdx.x + nextCandBlock; j < sh.num_divs_local; j += blockDim.x)
  {
    const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;  
    const T nextCandMask = (j > nextCandBlock) ? 0xFFFFFFFF : (~((1 << (nextCand & 0x1F)) - 1));
    T nodes = cur_bl[j] & nextCandMask & m;
    if (WL)
    {
      T idx = 0;
      while ((idx = __ffs(nodes)))
      {
        --idx;
        // Conversion from bitset to Vertex Ivdex
        const T donate_index = j * 32 + idx;
        sh.Xx_aux_shared[atomicAdd(&sh.Xx_aux_sz, 1)] = donate_index;
        nodes ^= 1u << idx;
      }
    }

  }

  __syncthreads();
}



template <bool WL, typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void get_warp_candidates_for_next_level_(
    LOCAL_HANDLE<T> &lh,
    WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh, const T &level,
    const T const* cur_bl)
{

  const T nextCand = wsh.level_pointer_index[level];
  const T nextCandBlock = nextCand >> 5;
  for (T j = laneIdx + nextCandBlock; j < wsh.num_divs_local; j += CPARTSIZE)
  {
    const T m = (j == wsh.lastMask_i) ? wsh.lastMask_ii : 0xFFFFFFFF;  
    const T nextCandMask = (j > nextCandBlock) ? 0xFFFFFFFF : (~((1 << (nextCand & 0x1F)) - 1));
    T nodes = cur_bl[j] & nextCandMask & m;
    if (WL)
    {
      T idx = 0;
      while ((idx = __ffs(nodes)))
      {
        --idx;
        // Conversion from bitset to Vertex Ivdex
        const T donate_index = j * 32 + idx;
        wsh.Xx_aux_shared[atomicAdd(&(wsh.Xx_aux_sz), 1)] = donate_index;
        nodes ^= 1u << idx;
      }
    }

  }

  __syncwarp();
}

template <bool WL, typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void get_warp_candidates_for_next_level_local(
    LOCAL_HANDLE<T> &lh,
    WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh, const T &level,
    const T const* cur_bl)
{

  if (laneIdx == 0)
  {
    const T nextCand = wsh.level_pointer_index[level];
    const T nextCandBlock = nextCand >> 5;
    for (T j = nextCandBlock; j < wsh.num_divs_local && wsh.Xx_aux_sz < NUMPART - 1; j++)
    {
      const T m = (j == wsh.lastMask_i) ? wsh.lastMask_ii : 0xFFFFFFFF; 
      const T nextCandMask = (j > nextCandBlock) ? 0xFFFFFFFF : (~((1 << (nextCand & 0x1F)) - 1));
      T nodes = cur_bl[j] & nextCandMask & m;
      if (WL)
      {
        T idx = 0;
        while ((idx = __ffs(nodes)) && wsh.Xx_aux_sz < NUMPART - 1)
        {
          --idx;
          // Conversion from bitset to Vertex Ivdex
          const T donate_index = j * 32 + idx;
          wsh.Xx_aux_shared[wsh.Xx_aux_sz++] = donate_index;
          nodes ^= 1u << idx;
        }
      } 
    }
  }

  __syncwarp();
}



template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void do_fork(
    GLOBAL_HANDLE<T> &gh, SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
    const T & num_divs_local,
    const T const* cur_bl, const T const* cur_al,    
    queue_callee(queue, tickets, head, tail))
{
  // Donated vertex stays un Xx_aux_shared
  for (T j = 0; j < sh.Xx_aux_sz; j++)
  {
    if (threadIdx.x == 0)
      queue_wait_ticket(queue, tickets, head, tail, CB, sh.worker_pos, sh.shared_other_sm_block_id);
    __syncthreads();

    const uint32_t other_sm_block_id = sh.shared_other_sm_block_id;
    const auto other_level_offset = other_sm_block_id * NUMDIVS * (MAXLEVEL);
    const auto other_clique_offset = other_sm_block_id * (MAXLEVEL);
    T *other_pl = &gh.P[other_level_offset];

    if (gh.eval)
    {
      T *other_c = &gh.C[other_clique_offset];

      for (T k = threadIdx.x; k < sh.l - 1; k += blockDim.x)
        other_c[k] = sh.c[k];

      __syncthreads();

      if (threadIdx.x == 0)
        other_c[sh.l - 1] = sh.ordering[sh.Xx_aux_shared[j]];
    }

    __syncthreads();

    const T prevCand = sh.Xx_aux_shared[j];
    const T prevCandBlock = prevCand >> 5;
    for (T k = threadIdx.x; k < num_divs_local; k += blockDim.x)
    {
      const T m = (k == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;
      const T t = sh.encode[sh.Xx_aux_shared[j] * sh.num_divs_local + k];
      const T prevCandMask = (k > prevCandBlock) ? 0x00000000 : (k < prevCandBlock ? 0xFFFFFFFF : ((1 << (prevCand & 0x1F)) - 1));
      const T bua = (cur_bl[k] & prevCandMask) | cur_al[k];
      const T tbua = bua & t & m;
      other_pl[(next_level) * num_divs_local + k] = tbua;
    }

    __syncthreads();

    if (threadIdx.x == 0)
    {
      uint32_t *message = &gh.global_message[other_sm_block_id * MSGCNT];
      sh.level_pointer_index[current_level] = max(sh.level_pointer_index[current_level], sh.Xx_aux_shared[j] + 1);
      message[0] = sh.root_sm_block_id;
      message[1] = sh.l + 1;
      message[2] = sh.srcLen;
      message[3] = sh.usrcLen;
      message[4] = sh.i;
      gh.work_ready[other_sm_block_id].store(1, cuda::memory_order_release);
      sh.worker_pos++;
    }
    __syncthreads();
  }

  __syncthreads();
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void do_warp_fork_global(
  LOCAL_HANDLE<T> &lh,
    GLOBAL_HANDLE<T> &gh, WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh,
    const T & num_divs_local,
    const T const* cur_bl, const T const* cur_al,
    queue_callee(queue, tickets, head, tail))
{
  // Donated vertex stays un Xx_aux_shared
  for (T j = 0; j < wsh.Xx_aux_sz; j++)
  {
    if (laneIdx == 0)
      queue_wait_ticket(queue, tickets, head, tail, WARPS, wsh.worker_pos, wsh.shared_other_sm_warp_id);
    __syncwarp();

    const uint32_t other_sm_warp_id = wsh.shared_other_sm_warp_id;
    const auto other_level_offset = other_sm_warp_id * NUMDIVS * (MAXLEVEL);
    T *other_pl = &gh.P[other_level_offset];

    //if (laneIdx == 0) printf("warp: %u donate to %u\n", lh.gwx, other_sm_warp_id);

    const T prevCand = wsh.Xx_aux_shared[j];
    const T prevCandBlock = prevCand >> 5;
    for (T k = laneIdx; k < num_divs_local; k += CPARTSIZE)
    {
      const T m = (k == wsh.lastMask_i) ? wsh.lastMask_ii : 0xFFFFFFFF;
      const T t = wsh.encode[wsh.Xx_aux_shared[j] * num_divs_local + k];
      const T prevCandMask = (k > prevCandBlock) ? 0x00000000 : (k < prevCandBlock ? 0xFFFFFFFF : ((1 << (prevCand & 0x1F)) - 1));
      const T bua = (cur_bl[k] & prevCandMask) | cur_al[k];
      const T tbua = bua & t & m;
      other_pl[(wsh.l - 2) * num_divs_local + k] = tbua;
    }

    __syncwarp();
    

    if (laneIdx == 0)
    {
      uint32_t *message = &gh.global_message[other_sm_warp_id * MSGCNT];
      wsh.level_pointer_index[wsh.l - 3] = max(wsh.level_pointer_index[wsh.l - 3], wsh.Xx_aux_shared[j] + 1);
      message[0] = wsh.root_sm_warp_id;
      message[1] = wsh.l + 1;
      message[2] = wsh.root_sm_block_id;
      message[3] = wsh.usrcLen;
      message[4] = wsh.i;
      gh.work_ready[other_sm_warp_id].store(1, cuda::memory_order_release);
      wsh.worker_pos++;
    }
    __syncwarp();

  }
}



template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void do_warp_fork_local(
  LOCAL_HANDLE<T> &lh,
    GLOBAL_HANDLE<T> &gh, WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh,
    const T & num_divs_local,
    const T const* cur_bl, const T const* cur_al,    
    queue_callee(queue, tickets, head, tail))
{
  // Donated vertex stays un Xx_aux_shared
  for (T j = 0; j < wsh.Xx_aux_sz; j++)
  {
    if (laneIdx == 0)
      queue_wait_ticket_local(queue, tickets, head, tail, NUMPART, wsh.worker_pos, wsh.shared_other_sm_warp_id);
    __syncwarp();


    const uint32_t other_sm_warp_id = wsh.shared_other_sm_warp_id;
    const auto other_level_offset = other_sm_warp_id * NUMDIVS * (MAXLEVEL);
    T *other_pl = &gh.P[other_level_offset];

    const T prevCand = wsh.Xx_aux_shared[j];
    const T prevCandBlock = prevCand >> 5;
    for (T k = laneIdx; k < num_divs_local; k += CPARTSIZE)
    {
      const T m = (k == wsh.lastMask_i) ? wsh.lastMask_ii : 0xFFFFFFFF;
      const T t = wsh.encode[wsh.Xx_aux_shared[j] * num_divs_local + k];
      const T prevCandMask = (k > prevCandBlock) ? 0x00000000 : (k < prevCandBlock ? 0xFFFFFFFF : ((1 << (prevCand & 0x1F)) - 1));
      const T bua = (cur_bl[k] & prevCandMask) | cur_al[k];
      const T tbua = bua & t & m;
      other_pl[(wsh.l - 2) * num_divs_local + k] = tbua;
    }

    __syncwarp();
    

    if (laneIdx == 0)
    {
      uint32_t *message = &gh.global_message[other_sm_warp_id * MSGCNT];
      wsh.level_pointer_index[wsh.l - 3] = max(wsh.level_pointer_index[wsh.l - 3], wsh.Xx_aux_shared[j] + 1);
      message[0] = wsh.root_sm_warp_id;
      message[1] = wsh.l + 1;
      message[2] = wsh.root_sm_block_id;
      message[3] = wsh.usrcLen;
      message[4] = wsh.i;
      gh.work_ready[other_sm_warp_id].store(1, cuda::memory_order_release);
      wsh.worker_pos++;
    }
    __syncwarp();

  }
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void do_warp_fork_shared(
  LOCAL_HANDLE<T> &lh,
    GLOBAL_HANDLE<T> &gh, WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh,
    const T & num_divs_local,
    const T const* cur_bl, const T const* cur_al,    
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  // Donated vertex stays un Xx_aux_shared
  for (T j = 0; j < wsh.Xx_aux_sz; j++)
  {
    if (laneIdx == 0)
      queue_wait_ticket(sh.queue, sh.tickets, sh.head, sh.tail, NUMPART, wsh.worker_pos, wsh.shared_other_sm_warp_id);
    __syncwarp();


    const uint32_t other_sm_warp_id = wsh.shared_other_sm_warp_id;
    const auto other_level_offset = other_sm_warp_id * NUMDIVS * (MAXLEVEL);
    T *other_pl = &gh.P[other_level_offset];

    const T prevCand = wsh.Xx_aux_shared[j];
    const T prevCandBlock = prevCand >> 5;
    for (T k = laneIdx; k < num_divs_local; k += CPARTSIZE)
    {
      const T m = (k == wsh.lastMask_i) ? wsh.lastMask_ii : 0xFFFFFFFF;
      const T t = wsh.encode[wsh.Xx_aux_shared[j] * num_divs_local + k];
      const T prevCandMask = (k > prevCandBlock) ? 0x00000000 : (k < prevCandBlock ? 0xFFFFFFFF : ((1 << (prevCand & 0x1F)) - 1));
      const T bua = (cur_bl[k] & prevCandMask) | cur_al[k];
      const T tbua = bua & t & m;
      other_pl[(wsh.l - 2) * num_divs_local + k] = tbua;
    }

    __syncwarp();
    

    if (laneIdx == 0)
    {
      uint32_t *message = &gh.global_message[other_sm_warp_id * MSGCNT];
      wsh.level_pointer_index[wsh.l - 3] = max(wsh.level_pointer_index[wsh.l - 3], wsh.Xx_aux_shared[j] + 1);
      message[0] = wsh.root_sm_warp_id;
      message[1] = wsh.l + 1;
      message[2] = wsh.root_sm_block_id;
      message[3] = wsh.usrcLen;
      message[4] = wsh.i;
      gh.work_ready[other_sm_warp_id].store(1, cuda::memory_order_release);
      wsh.worker_pos++;
    }
    __syncwarp();

  }
}

template<typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void shared_wait_for_donor_warp_local(
    cuda::atomic<uint32_t, cuda::thread_scope_device> &work_ready, uint32_t &warp_shared_state,
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  uint32_t ns = 8;
  do
  {
    if (work_ready.load(cuda::memory_order_relaxed))
    {
      
      if (work_ready.load(cuda::memory_order_acquire))
      {
        warp_shared_state = 2;
        work_ready.store(0, cuda::memory_order_relaxed);
        break;
      }
    }
    else if (shared_queue_full(sh.queue, sh.tickets, sh.head, sh.tail, NUMPART))
    {
      warp_shared_state = 100;
      break;
    }
  } while (ns = my_sleep(ns));
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void setup_stack_donor_psanse(
    GLOBAL_HANDLE<T> &gh, SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  if (threadIdx.x == 0)
  {
    size_t Xx_offset = sh.sm_block_id * MAXDEG;
    sh.Xx_aux_shared = &gh.Xx_aux[Xx_offset];

    size_t clique_offset = sh.sm_block_id * MAXLEVEL;
    if (gh.eval) sh.c = &gh.C[clique_offset];

    uint32_t *message = &gh.global_message[sh.sm_block_id * MSGCNT];
    sh.root_sm_block_id = message[0];
    sh.l = sh.base_l = message[1];
    sh.srcLen = message[2];
    sh.usrcLen = message[3];
    sh.i = message[4];
    sh.src = sh.i;

    auto encode_offset = sh.root_sm_block_id * (MAXDEG * NUMDIVS);
    sh.encode = &gh.encoded_induced_subgraph[encode_offset];

    size_t ordering_offset = sh.root_sm_block_id * MAXDEG;
    if (gh.eval) sh.ordering = &gh.ordering[ordering_offset];

    auto level_offset = sh.sm_block_id * NUMDIVS * MAXLEVEL;
    sh.pl = &gh.P[level_offset];
    sh.bl = &gh.B[level_offset];
    sh.al = &gh.A[level_offset];  
    //sh.Iset = &gh.Iset[level_offset];
  
    auto level_item_offset = sh.sm_block_id * MAXLEVEL;
    sh.level_pointer_index = &gh.level_pointer[level_item_offset];
    sh.level_pointer_index[current_level] = 0;
    
    sh.colored = &gh.colored[level_item_offset];
    sh.colored[current_level] = false;

    sh.num_divs_local = (sh.usrcLen + 32 - 1) / 32;
    sh.lastMask_i = sh.usrcLen >> 5;
    sh.lastMask_ii = (1 << (sh.usrcLen & 0x1F)) - 1;

  }
  __syncthreads();
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void setup_warp_stack_donor_psanse_(
    GLOBAL_HANDLE<T> &gh, LOCAL_HANDLE<T> &lh, WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh)
{
  if (laneIdx == 0)
  {
    size_t Xx_offset = wsh.sm_warp_id * MAXDEG;
    wsh.Xx_aux_shared = &gh.Xx_aux[Xx_offset];
    
    uint32_t *message = &gh.global_message[wsh.sm_warp_id * MSGCNT];
    wsh.root_sm_warp_id = message[0];
    wsh.l = wsh.base_l = message[1];
    wsh.root_sm_block_id = message[2];
    wsh.usrcLen = message[3];
    wsh.i = message[4];

    auto encode_offset = wsh.root_sm_block_id * MAXDEG * NUMDIVS;
    wsh.encode = &gh.encoded_induced_subgraph[encode_offset];

    auto level_offset = wsh.sm_warp_id * NUMDIVS * MAXLEVEL;
    wsh.pl = &gh.P[level_offset];
    wsh.bl = &gh.B[level_offset];
    wsh.al = &gh.A[level_offset];
    //sh.Iset = &gh.Iset[level_offset];
    

    auto level_item_offset = wsh.sm_warp_id * MAXLEVEL;
    wsh.level_pointer_index = &gh.level_pointer[level_item_offset];
    wsh.level_pointer_index[wsh.l - 3] = 0;
    wsh.colored = &gh.colored[level_item_offset];
    wsh.colored[wsh.l - 3] = false;

    wsh.num_divs_local = (wsh.usrcLen + 32 - 1) / 32;
    wsh.lastMask_i = wsh.usrcLen >> 5;
    wsh.lastMask_ii = (1 << (wsh.usrcLen & 0x1F)) - 1;

  }
  __syncwarp();
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void setup_warp_stack_donor_psanse_global(
    GLOBAL_HANDLE<T> &gh, LOCAL_HANDLE<T> &lh, WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh)
{
  if (laneIdx == 0)
  {
    size_t Xx_offset = wsh.sm_warp_id * MAXDEG;
    wsh.Xx_aux_shared = &gh.Xx_aux[Xx_offset];
    
    uint32_t *message = &gh.global_message[wsh.sm_warp_id * MSGCNT];
    wsh.root_sm_warp_id = message[0];
    wsh.l = wsh.base_l = message[1];
    uint32_t root_sm_block_id = message[2];
    wsh.usrcLen = message[3];
    wsh.i = message[4];

    auto encode_offset = (root_sm_block_id) * (MAXDEG * NUMDIVS);
    wsh.encode = &gh.encoded_induced_subgraph[encode_offset];

    auto level_offset = wsh.sm_warp_id * NUMDIVS * MAXLEVEL;
    wsh.pl = &gh.P[level_offset];
    wsh.bl = &gh.B[level_offset];
    wsh.al = &gh.A[level_offset];
    //sh.Iset = &gh.Iset[level_offset];
    

    auto level_item_offset = wsh.sm_warp_id * MAXLEVEL;
    wsh.level_pointer_index = &gh.level_pointer[level_item_offset];
    wsh.level_pointer_index[wsh.l - 3] = 0;
    wsh.colored = &gh.colored[level_item_offset];
    wsh.colored[wsh.l - 3] = false;

    wsh.num_divs_local = (wsh.usrcLen + 32 - 1) / 32;
    wsh.lastMask_i = wsh.usrcLen >> 5;
    wsh.lastMask_ii = (1 << (wsh.usrcLen & 0x1F)) - 1;

  }
  __syncwarp();
}




template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void setup_stack_donor_psanse_recolor(
    GLOBAL_HANDLE<T> &gh, SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  if (threadIdx.x == 0)
  {
    size_t Xx_offset = sh.sm_block_id * MAXDEG;
    sh.Xx_aux_shared = &gh.Xx_aux[Xx_offset];
    sh.current_bucket = &gh.current[Xx_offset];
    sh.next_bucket = &gh.next[Xx_offset];
    
    uint32_t *message = &gh.global_message[sh.sm_block_id * MSGCNT];
    sh.root_sm_block_id = message[0];
    sh.l = sh.base_l = message[1];
    sh.srcLen = message[2];
    sh.usrcLen = message[3];
    sh.i = message[4];
    sh.src = sh.i;

    auto encode_offset = sh.root_sm_block_id * (MAXDEG * NUMDIVS);
    sh.encode = &gh.encoded_induced_subgraph[encode_offset];

    auto level_offset = sh.sm_block_id * NUMDIVS * MAXLEVEL;
    sh.pl = &gh.P[level_offset];
    sh.bl = &gh.B[level_offset];
    sh.al = &gh.A[level_offset];
    sh.Iset = &gh.Iset[level_offset];
    

    auto level_item_offset = sh.sm_block_id * MAXLEVEL;
    sh.level_pointer_index = &gh.level_pointer[level_item_offset];
    sh.level_pointer_index[current_level] = 0;
    
    sh.colored = &gh.colored[level_item_offset];
    sh.colored[current_level] = false;

    sh.num_divs_local = (sh.usrcLen + 32 - 1) / 32;
    sh.lastMask_i = sh.usrcLen >> 5;
    sh.lastMask_ii = (1 << (sh.usrcLen & 0x1F)) - 1;

  }
  __syncthreads();
}



template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void setup_stack_donor_tomita(
    GLOBAL_HANDLE<T> &gh, SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  if (threadIdx.x == 0)
  {
    size_t Xx_offset = sh.sm_block_id * MAXDEG;
    sh.Xx_aux_shared = &gh.Xx_aux[Xx_offset];
    
    uint32_t *message = &gh.global_message[sh.sm_block_id * MSGCNT];
    sh.root_sm_block_id = message[0];
    sh.l = sh.base_l = message[1];
    sh.srcLen = message[2];
    sh.usrcLen = message[3];
    sh.i = message[4];
    sh.src = sh.i;

    auto encode_offset = sh.root_sm_block_id * (MAXDEG * NUMDIVS);
    sh.encode = &gh.encoded_induced_subgraph[encode_offset];

    auto level_offset = sh.sm_block_id * NUMDIVS * MAXLEVEL;
    sh.pl = &gh.P[level_offset];
    sh.bl = &gh.B[level_offset];
    sh.al = &gh.A[level_offset];

    auto iset_offset = sh.sm_block_id * ((MAXDEG) * MAXLEVEL);
    sh.Iset = &gh.Iset[iset_offset];
    

    auto level_item_offset = sh.sm_block_id * MAXLEVEL;
    sh.level_pointer_index = &gh.level_pointer[level_item_offset];
    sh.level_pointer_index[current_level] = 0;
    
    sh.colored = &gh.colored[level_item_offset];
    sh.colored[current_level] = false;

    sh.Iset_count = &gh.Iset_count[level_item_offset];

    sh.num_divs_local = (sh.usrcLen + 32 - 1) / 32;
    sh.lastMask_i = sh.usrcLen >> 5;
    sh.lastMask_ii = (1 << (sh.usrcLen & 0x1F)) - 1;

  }
  __syncthreads();
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void try_dequeue(
    GLOBAL_HANDLE<T> &gh, SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
    queue_callee(queue, tickets, head, tail))
{
  if (threadIdx.x == 0 && sh.Xx_aux_sz >= 4)
    queue_dequeue(queue, tickets, head, tail, CB, sh.fork, sh.worker_pos, sh.Xx_aux_sz);
  __syncthreads();
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void try_dequeue_warp_global(LOCAL_HANDLE<T> &lh,
    GLOBAL_HANDLE<T> &gh, WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh,
    queue_callee(queue, tickets, head, tail))
{
  if (laneIdx == 0 && wsh.Xx_aux_sz >= 4)
    queue_dequeue(queue, tickets, head, tail, WARPS, wsh.fork, wsh.worker_pos, wsh.Xx_aux_sz);
  __syncwarp();
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void try_dequeue_warp_local(LOCAL_HANDLE<T> &lh,
    GLOBAL_HANDLE<T> &gh, WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh,
    queue_callee(queue, tickets, head, tail))
{
  if (laneIdx == 0 && wsh.Xx_aux_sz >= 1)
    queue_dequeue_local(queue, tickets, head, tail, NUMPART, wsh.fork, wsh.worker_pos, wsh.Xx_aux_sz);
  __syncwarp();
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void try_dequeue_warp_shared(LOCAL_HANDLE<T> &lh,
    GLOBAL_HANDLE<T> &gh, WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh,
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  if (laneIdx == 0 && wsh.Xx_aux_sz >= 1)
    shared_queue_dequeue(sh.queue, sh.tickets, sh.head, sh.tail, NUMPART, wsh.fork, wsh.worker_pos, wsh.Xx_aux_sz);
  __syncwarp();
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void prepare_fork(SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  if (threadIdx.x == 0)
  {
    sh.Xx_aux_sz = 0;
    sh.fork = false;
  }
  __syncthreads();
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void prepare_warp_fork_(LOCAL_HANDLE<T> &lh, WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh)
{
  if (laneIdx == 0)
  {
    wsh.Xx_aux_sz = 0;
    wsh.fork = false;
  }
  __syncwarp();
}

template <typename T>
__device__ __forceinline__ void next_pointer(
    LOCAL_HANDLE<T> &lh, 
    T &level_pointer_index)
{
  if (threadIdx.x == 0)
    level_pointer_index = lh.newIndex + 1;
  __syncthreads();
}

template <typename T>
__device__ __forceinline__ void next_warp_pointer(
    LOCAL_HANDLE<T> &lh, 
    T &level_pointer_index)
{
  if (lh.lx == 0)
    level_pointer_index = lh.newIndex + 1;
  __syncwarp();
}

template <typename T>
__device__ __forceinline__ void go_to_next_level(T &l, T &level_pointer_index, bool &colored)
{
  if (threadIdx.x == 0)
  {
    ++l;
    level_pointer_index = 0;
    colored = false;
  }

  __syncthreads();
}

template <typename T>
__device__ __forceinline__ void go_to_next_level_warp(LOCAL_HANDLE<T> &lh, T &l, T &level_pointer_index, bool &colored)
{
  if (lh.lx == 0)
  {
    ++l;
    level_pointer_index = 0;
    colored = false;
  }

  __syncwarp();
}

template <typename T, uint BLOCK_DIM_X>
__device__ __forceinline__ bool empty(LOCAL_HANDLE<T> &lh, const T const* set, const T size)
{
  unsigned _not_empty = 0;
  __shared__ unsigned not_empty;
  
  if (threadIdx.x == 0)
    not_empty = 0;

  __syncthreads();

  for (T j = threadIdx.x; j < size; j += BLOCK_DIM_X)
      _not_empty |= bool(set[j] != 0);

  __syncthreads();

  const unsigned not_empty_reduced = __any_sync(lh.partMask, _not_empty);

  if (lh.lx == 0) atomicOr(&not_empty, not_empty_reduced);
  
  __syncthreads();
  return !not_empty;
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool empty_w(LOCAL_HANDLE<T> &lh, const T const* set, const T size)
{
  unsigned not_empty = 0;

  for (T j = laneIdx; j < size; j += CPARTSIZE)
      not_empty |= bool(set[j] != 0);

  return !__any_sync(lh.partMask, not_empty);
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ T popc(LOCAL_HANDLE<T> &lh, const T const* set, const T size)
{
  T thread_count = 0;
  __shared__ T total_count;

  if (threadIdx.x == 0)
    total_count = 0;

  __syncthreads();

  for (T j = threadIdx.x; j < size; j += BLOCK_DIM_X)
    thread_count += __popc(set[j]);

  __syncthreads();

  reduce_part<T, CPARTSIZE>(lh.partMask, thread_count);

  __syncthreads();

  if (lh.lx == 0 && thread_count > 0)
    atomicAdd(&total_count, thread_count);

  __syncthreads();
  return total_count;
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool get_next_candidate_to_color(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
    const T &lim, const int& last_choosen_index, const T const*col)
{
  if (last_choosen_index >= lim)
  {
    __syncthreads();
    return false;
  }
  // Starts from maskblock based on previous vertex index
  lh.colMaskBlock = last_choosen_index >> 5;
  lh.colMaskIndex = ~((1 << (last_choosen_index & 0x1F)) - 1);
  lh.colNewIndex = __ffs(col[lh.colMaskBlock] & lh.colMaskIndex);
  // while there are no bits set to 1
  while (lh.colNewIndex == 0)
  {
    lh.colMaskIndex = 0xFFFFFFFF;
    ++lh.colMaskBlock;
    if ((lh.colMaskBlock << 5) >= lim)
      break;
    lh.colNewIndex = __ffs(col[lh.colMaskBlock] & lh.colMaskIndex);
  } // Counts in maskBlock the number of blocks set to 0
  // If there are no other candidates
  if ((lh.colMaskBlock << 5) >= lim)
  {
    __syncthreads();
    return false;
  }
  // newIndex contains the actual candidate
  lh.colNewIndex = (lh.colMaskBlock << 5) + lh.colNewIndex - 1;
  __syncthreads();
  return true;
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool get_next_warp_candidate_to_color_(
    LOCAL_HANDLE<T> &lh, 
    const T &lim, const int& last_choosen_index, const T const*col)
{
  if (last_choosen_index >= lim)
  {
    __syncwarp();
    return false;
  }
  // Starts from maskblock based on previous vertex index
  lh.colMaskBlock = last_choosen_index >> 5;
  lh.colMaskIndex = ~((1 << (last_choosen_index & 0x1F)) - 1);
  lh.colNewIndex = __ffs(col[lh.colMaskBlock] & lh.colMaskIndex);
  // while there are no bits set to 1
  while (lh.colNewIndex == 0)
  {
    lh.colMaskIndex = 0xFFFFFFFF;
    ++lh.colMaskBlock;
    if ((lh.colMaskBlock << 5) >= lim)
      break;
    lh.colNewIndex = __ffs(col[lh.colMaskBlock] & lh.colMaskIndex);
  } // Counts in maskBlock the number of blocks set to 0
  // If there are no other candidates
  if ((lh.colMaskBlock << 5) >= lim)
  {
    __syncwarp();
    return false;
  }
  // newIndex contains the actual candidate
  lh.colNewIndex = (lh.colMaskBlock << 5) + lh.colNewIndex - 1;
  __syncwarp();
  return true;
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool get_next_candidate_to_color_reverse(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
    const int &lim, const int& last_choosen_index, const T const*col)
{
  if (last_choosen_index < 0)
  {
    __syncthreads();
    return false;
  }
  // Starts from maskblock based on previous vertex index
  lh.colMaskBlock = last_choosen_index >> 5;
  lh.colMaskIndex = ((1 << ((last_choosen_index + 1) & 0x1F)) - 1);
  lh.colNewIndex = __clz(col[lh.colMaskBlock] & lh.colMaskIndex);
  // while there are no bits set to 1
  while (lh.colNewIndex == 32)
  {
    lh.colMaskIndex = 0xFFFFFFFF;
    --lh.colMaskBlock;
    if ((lh.colMaskBlock) < 0)
      break;
    lh.colNewIndex = __clz(col[lh.colMaskBlock] & lh.colMaskIndex);
  } // Counts in maskBlock the number of blocks set to 0
  // If there are no other candidates
  if ((lh.colMaskBlock) < 0)
  {
    __syncthreads();
    return false;
  }
  // newIndex contains the actual candidate
  lh.colNewIndex = (lh.colMaskBlock << 5) + (32 - lh.colNewIndex) - 1;
  __syncthreads();
  return true;
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool get_next_candidate(
    GLOBAL_HANDLE<T> &gh, LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
    const T &lim, const T &level_pointer_index, T *cur_pl)
{
  if (level_pointer_index >= lim)
  {
    __syncthreads();
    if (threadIdx.x == 0)
      --sh.l;
    __syncthreads();
    return false;
  }
  // Starts from maskblock based on previous vertex index
  lh.maskBlock = level_pointer_index >> 5;
  lh.maskIndex = ~((1 << (level_pointer_index & 0x1F)) - 1);
  lh.newIndex = __ffs(cur_pl[lh.maskBlock] & lh.maskIndex);
  // while there are no bits set to 1
  while (lh.newIndex == 0)
  {
    lh.maskIndex = 0xFFFFFFFF;
    ++lh.maskBlock;
    if ((lh.maskBlock << 5) >= lim)
      break;
    lh.newIndex = __ffs(cur_pl[lh.maskBlock] & lh.maskIndex);
  } // Counts in maskBlock the number of blocks set to 0
  // If there are no other candidates
  if ((lh.maskBlock << 5) >= lim)
  {
    __syncthreads();
    if (threadIdx.x == 0)
      --sh.l; // Back to the previous level
    __syncthreads();
    return false;
  }
  // newIndex contains the actual candidate
  lh.newIndex = (lh.maskBlock << 5) + lh.newIndex - 1;
  lh.sameBlockMask = (~((1 << (lh.newIndex & 0x1F)) - 1)) | ~cur_pl[lh.maskBlock];
  __syncthreads();
  return true;
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool p_maximality(
    GLOBAL_HANDLE<T> &gh,
    LOCAL_HANDLE<T> &lh,
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  // if P == 0
  if (mcp::empty<T, BLOCK_DIM_X>(lh, sh.pl + current_level * sh.num_divs_local, sh.num_divs_local)) {
    
    __syncthreads();
    if (threadIdx.x == 0) {

      int old = atomicMax((int*)gh.Cmax_size, sh.l - 1);
      if (sh.l - 1 == (*gh.Cmax_size) && sh.l - 1 > old)
        printf("Found clique of size %d.\n", sh.l - 1);
      --sh.l;
    }
    __syncthreads();
    return true;
  }
  __syncthreads();
  return false;
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool p_maximality_eval(
    GLOBAL_HANDLE<T> &gh,
    LOCAL_HANDLE<T> &lh,
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh)
{
  // if P == 0
  if (mcp::empty<T, BLOCK_DIM_X>(lh, sh.pl + current_level * sh.num_divs_local, sh.num_divs_local)) {
    
    if (threadIdx.x == 0) {

      // to avoid acquiring the semaphore repeatly
      if ((*gh.Cmax_size) < sh.l - 1)
      {
        gh.max_clique_sem->acquire();

        // once acquired check if actually bigger
        if ((*gh.Cmax_size) < sh.l - 1) 
        {
          printf("Found clique of size %d.\n", sh.l - 1);
          (*gh.Cmax_size) = sh.l - 1;
          
          // save clique
          for (T j = 0; j < sh.l - 1; j++)
            gh.Cmax[j] = sh.c[j];
        }
        gh.max_clique_sem->release();
      }

      --sh.l;
    }
    __syncthreads();
    return true;
  }
  __syncthreads();
  return false;
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool p_warp_maximality_(
    GLOBAL_HANDLE<T> &gh,
    LOCAL_HANDLE<T> &lh,
    WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh)
{
  // if P == 0
  if (mcp::empty_w<T, BLOCK_DIM_X, CPARTSIZE>(lh, wsh.pl + (wsh.l - 3) * wsh.num_divs_local, wsh.num_divs_local)) {
    
    if (laneIdx == 0) {

      int old = atomicMax((int*)gh.Cmax_size, wsh.l - 1);
      if (wsh.l - 1 == (*gh.Cmax_size) && wsh.l - 1 > old)
        printf("Found clique of size %d.\n", wsh.l - 1);
      --wsh.l;
    }
    __syncwarp();
    return true;
  }
  __syncwarp();
  return false;
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool b_maximality(
    GLOBAL_HANDLE<T> &gh,
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
    LOCAL_HANDLE<T> &lh)
{
  if (empty<T, BLOCK_DIM_X>(lh, sh.to_bl, sh.num_divs_local)) {

    __syncthreads();
    if (threadIdx.x == 0) {
    
      // int old = atomicMax((int*)gh.Cmax_size, sh.l - 1);
      // if (sh.l - 1 == (*gh.Cmax_size) && sh.l - 1 > old)
      //   printf("Found clique of size %d.\n", sh.l - 1);
      --sh.l;
    }
    __syncthreads();
    return true;
  }

  __syncthreads();
  return false;
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool b_warp_maximality_(
    GLOBAL_HANDLE<T> &gh,
    WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh,
    LOCAL_HANDLE<T> &lh)
{
  if (empty_w<T, BLOCK_DIM_X, CPARTSIZE>(lh, wsh.bl + (wsh.l - 3) * wsh.num_divs_local, wsh.num_divs_local)) {

    if (laneIdx == 0) {
    
      // int old = atomicMax((int*)gh.Cmax_size, sh.l - 1);
      // if (sh.l - 1 == (*gh.Cmax_size) && sh.l - 1 > old)
      //   printf("Found clique of size %d.\n", sh.l - 1);
      --wsh.l;
    }
    __syncwarp();
    return true;
  }

  __syncwarp();
  return false;
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_branching_aux_set(
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
    const  T const* cur_pl, T* cur_al, T* cur_bl)
{
  for (T j = threadIdx.x; j < sh.num_divs_local; j += BLOCK_DIM_X)
  {
    const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;
    cur_bl[j] = sh.to_bl[j] & m;
    cur_al[j] = (cur_pl[j] & ~(sh.to_bl[j])) & m;
  }
  __syncthreads();
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_branching_aux_set_second_level(
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, T* cur_al)
{
  for (T j = threadIdx.x; j < sh.num_divs_local; j += BLOCK_DIM_X)
  {
    const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;
    cur_al[j] = (m & ~(sh.to_bl[j])) & m;
  }
  __syncthreads();
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_warp_branching_aux_set_(
    LOCAL_HANDLE<T> &lh,
    WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh, const T& num_divs_local,
    const  T const* cur_pl, T* cur_al, const T const* cur_bl)
{
  for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
  {
    const T m = (j == wsh.lastMask_i) ? wsh.lastMask_ii : 0xFFFFFFFF;
    cur_al[j] = (cur_pl[j] & ~(cur_bl[j])) & m;
  }
  __syncwarp();
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool bitset_scan(
    GLOBAL_HANDLE<T> &gh, LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
    const T& level_pointer_index, const T &lim, const T const* cur_bl)
{
  // in case not work reverse
  // REDO
  if (level_pointer_index >= lim)
  {
    lh.newIndex = lim;
    __syncthreads();
    return false;
  }
  // Starts from maskblock based on previous vertex index
  lh.maskBlock = level_pointer_index >> 5;
  lh.maskIndex = ~((1 << (level_pointer_index & 0x1F)) - 1);
  lh.newIndex = __ffs(cur_bl[lh.maskBlock] & lh.maskIndex);

  // while there are no bits set to 1
  while (lh.newIndex == 0)
  {
    lh.maskIndex = 0xFFFFFFFF;
    ++lh.maskBlock;
    if ((lh.maskBlock << 5) >= lim)
      break;
    lh.newIndex = __ffs(cur_bl[lh.maskBlock] & lh.maskIndex);
  } // Counts in maskBlock the number of blocks set to 0
  // If there are no other candidates
  if ((lh.maskBlock << 5) >= lim)
  {
    lh.newIndex = lim;
    __syncthreads();
    return false;
  }
  // newIndex contains the actual candidate
  lh.newIndex = (lh.maskBlock << 5) + lh.newIndex - 1;

  __syncthreads();
  return true;
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool bitset_scan_reverse(
    GLOBAL_HANDLE<T> &gh, LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
    const int& level_pointer_index, const T &lim, const T const* cur_bl)
{
  // in case not work reverse
  // REDO
  if (level_pointer_index <= lim)
  {
    lh.newIndex = lim;
    __syncthreads();
    return false;
  }
  // Starts from maskblock based on previous vertex index
  lh.maskBlock = level_pointer_index >> 5;
  lh.maskIndex = ((1 << ((level_pointer_index + 1) & 0x1F)) - 1);
  lh.newIndex = __clz(cur_bl[lh.maskBlock] & lh.maskIndex);

  // while there are no bits set to 1
  while (lh.newIndex == 32)
  {
    lh.maskIndex = 0xFFFFFFFF;
    --lh.maskBlock;
    if ((lh.maskBlock << 5) <= lim)
      break;
    lh.newIndex = __clz(cur_bl[lh.maskBlock] & lh.maskIndex);
  } // Counts in maskBlock the number of blocks set to 0
  // If there are no other candidates
  if ((lh.maskBlock << 5) <= lim)
  {
    lh.newIndex = lim;
    __syncthreads();
    return false;
  }
  // newIndex contains the actual candidate
  lh.newIndex = (lh.maskBlock << 5) + (32 - lh.newIndex) - 1;

  __syncthreads();
  return true;
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool get_next_branching_index(
    GLOBAL_HANDLE<T> &gh, LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
    const T& level_pointer_index, const T &lim, const T const* cur_bl)
{
  // in case not work reverse
  // REDO
  if (level_pointer_index >= lim)
  {
    __syncthreads();
    if (threadIdx.x == 0)
      --sh.l;
    __syncthreads();
    return false;
  }
  // Starts from maskblock based on previous vertex index
  lh.maskBlock = level_pointer_index >> 5;
  lh.maskIndex = ~((1 << (level_pointer_index & 0x1F)) - 1);
  lh.newIndex = __ffs(cur_bl[lh.maskBlock] & lh.maskIndex);

  // while there are no bits set to 1
  while (lh.newIndex == 0)
  {
    lh.maskIndex = 0xFFFFFFFF;
    ++lh.maskBlock;
    if ((lh.maskBlock << 5) >= lim)
      break;
    lh.newIndex = __ffs(cur_bl[lh.maskBlock] & lh.maskIndex);
  } // Counts in maskBlock the number of blocks set to 0
  // If there are no other candidates
  if ((lh.maskBlock << 5) >= lim)
  {
    __syncthreads();
    if (threadIdx.x == 0)
      --sh.l; // Back to the previous level
    __syncthreads();
    return false;
  }
  // newIndex contains the actual candidate
  lh.newIndex = (lh.maskBlock << 5) + lh.newIndex - 1;

  __syncthreads();
  return true;
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool get_next_warp_branching_index_(
    GLOBAL_HANDLE<T> &gh, LOCAL_HANDLE<T> &lh, 
    WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh,
    const T& level_pointer_index, const T &lim, const T const* cur_bl)
{
  // in case not work reverse
  // REDO
  if (level_pointer_index >= lim)
  {
    __syncwarp();
    if (laneIdx == 0)
      --wsh.l;
    __syncwarp();
    return false;
  }
  // Starts from maskblock based on previous vertex index
  lh.maskBlock = level_pointer_index >> 5;
  lh.maskIndex = ~((1 << (level_pointer_index & 0x1F)) - 1);
  lh.newIndex = __ffs(cur_bl[lh.maskBlock] & lh.maskIndex);

  // while there are no bits set to 1
  while (lh.newIndex == 0)
  {
    lh.maskIndex = 0xFFFFFFFF;
    ++lh.maskBlock;
    if ((lh.maskBlock << 5) >= lim)
      break;
    lh.newIndex = __ffs(cur_bl[lh.maskBlock] & lh.maskIndex);
  } // Counts in maskBlock the number of blocks set to 0
  // If there are no other candidates
  if ((lh.maskBlock << 5) >= lim)
  {
    __syncwarp();
    if (laneIdx == 0)
      --wsh.l; // Back to the previous level
    __syncwarp();
    return false;
  }
  // newIndex contains the actual candidate
  lh.newIndex = (lh.maskBlock << 5) + lh.newIndex - 1;

  __syncwarp();
  return true;
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool reduce(
    GLOBAL_HANDLE<T> &gh, LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
    const T& num_divs_local, const int level,
    T * cur_pl
    )
{
  // Compute degrees
  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
  {
    sh.to_bl[j] = cur_pl[j]; 
  }

  __shared__ int mod_R;
  __shared__ T min_degree;
  __shared__ T k;

  if (threadIdx.x == 0)
  {
    mod_R = 0;
    min_degree = sh.usrcLen;
    k = (T)(*gh.Cmax_size) >= level ? (T)(*gh.Cmax_size) - level : 0;
  }

  __syncthreads();

  if (k <= 2) return false;

  __syncthreads();

  //////////////// Compute degrees /////////////////////////////////////////////////////////

  for (T block_idx = lh.wx; block_idx < num_divs_local; block_idx += lh.numPartitions)
  { 
    T idx_block = 0;
    T block = sh.to_bl[block_idx];
    while ((idx_block = __ffs(block)) != 0)
    {
      T idx_degree = 0;
      const T idx = (block_idx << 5) + idx_block - 1;
     
      for (T j = lh.lx; j < num_divs_local; j += CPARTSIZE)
        if (sh.to_bl[j] != 0) idx_degree += __popc(sh.to_bl[j] & sh.encode[idx * num_divs_local + j]);

      __syncwarp();

      reduce_part<T, CPARTSIZE>(lh.partMask, idx_degree);
      
      __syncwarp();

      if (lh.lx == 0) 
      {
        sh.degree[idx] = idx_degree;
        atomicAdd(&mod_R, 1);
        atomicMin(&min_degree, idx_degree);
      }
     
      __syncwarp();

      block ^= 1 << (idx_block - 1);

      __syncwarp();
    }
    __syncwarp();
  }

  __syncthreads();



  if (min_degree == mod_R - 1)
  {
    if (threadIdx.x == 0)
    {
      const T old = atomicMax((uint32_t*)gh.Cmax_size, sh.l + mod_R - 1);
      if (old < sh.l + mod_R - 1)
        printf("Reduce finds clique of size %u.\n", *(gh.Cmax_size));
      sh.l--;
    }
    __syncthreads();
    return true;
  }
  
  ////////////////////////////////////////////////////////////////////////////////////////////
 
  __syncthreads();

  for (T idx = threadIdx.x; idx < sh.usrcLen; idx += BLOCK_DIM_X)
  {
    const T li = idx >> 5;
    const T ri = 1 << (idx & 0x1F);
    if ((sh.to_bl[li] & ri) > 0)
    {
      if (sh.degree[idx] == 0)
      {
        atomicXor(&sh.to_bl[li], ri);
        atomicSub(&mod_R, 1);
      } 
    }
  }

  __syncthreads(); 

  // Reduce
  while (true)
  {
    __shared__ int preSize;

    if (threadIdx.x == 0)
      preSize = mod_R;

    __syncthreads();

    // for each index of R
    for (T idx = 0; idx < sh.usrcLen; idx++)
    { 
      
      const T block_idx = idx >> 5;
      const T ri_idx = 1 << (idx & 0x1F);
      if ((sh.to_bl[block_idx] & ri_idx) > 0)
      {

        if (sh.degree[idx] < k - 1 || sh.degree[idx] >= mod_R - 4)
        {
          bool rule_1 = sh.degree[idx] < k - 1;
          if (rule_1)
          {
            // remove u from G
            if (threadIdx.x == 0)
            {
              //printf ("Rule 1 applyied\n");
              sh.to_bl[block_idx] ^= ri_idx;
              mod_R--;
            }

            __syncthreads();

            for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
            {
              T neighbour_block = sh.to_bl[j] & sh.encode[idx * num_divs_local + j];
              T neighbour_block_idx = 0;
              while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
              {
                const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                sh.degree[neighbour_idx]--;
                const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                if (sh.degree[neighbour_idx] == 0) {
                  sh.to_bl[j] ^= neighbour_block_bit;
                  atomicSub(&mod_R, 1);
                }
                neighbour_block ^= neighbour_block_bit;
              }
            }

            __syncthreads();
            continue;
      
          }

          bool rule_2 = sh.degree[idx] == mod_R - 2;
          if (!rule_1 && rule_2)
          {
            __shared__ T u;
            __shared__ T not_neighbours;
            __shared__ T not_neighbours_count;

            if (threadIdx.x == 0)
            {
              u = sh.usrcLen;
              not_neighbours_count = 0;
            }
            
            __syncthreads();

            for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
            { 
              T block_of_idx = block_idx == j ? ri_idx : 0x00000000;
              T last_mask = j == sh.lastMask_i ? sh.lastMask_ii : 0xFFFFFFFF;
              T lone_vertex_block = (sh.to_bl[j] & ~(sh.encode[idx * num_divs_local + j] | block_of_idx)) & last_mask;
              T lone_vertex_idx_block = 0;
              while((lone_vertex_idx_block = __ffs(lone_vertex_block)) != 0)
              {
                const T count = atomicAdd(&not_neighbours_count, 1);
                if (count == 0) not_neighbours = (j << 5) + lone_vertex_idx_block - 1;
                lone_vertex_block ^= 1 << (lone_vertex_idx_block - 1);
              }
            }

            __syncthreads();

            if (not_neighbours_count == 1) {

              if (threadIdx.x == 0) 
              { 
                //printf("Rule 2 applyied\n");
                u = not_neighbours;
              }
              __syncthreads();

              // Remove u from R
              if (threadIdx.x == 0)
              {
                const T li_u = u >> 5;
                const T ri_u = 1 << (u & 0x1F);
                sh.to_bl[li_u] ^= ri_u;
                mod_R--;
              }

              __syncthreads();

              for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
              {
                T neighbour_block = sh.to_bl[j] & sh.encode[u * num_divs_local + j];
                T neighbour_block_idx = 0;
                while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                {
                  const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                  sh.degree[neighbour_idx]--;
                  const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                  if (sh.degree[neighbour_idx] == 0) {
                    sh.to_bl[j] ^= neighbour_block_bit;
                    atomicSub(&mod_R, 1);
                  }
                  neighbour_block ^= neighbour_block_bit;
                }
              }

            }

            __syncthreads();
            continue;
          }

          bool rule_3 = sh.degree[idx] == mod_R - 3;
          if (!rule_1 && rule_3)
          {
            __shared__ T u1, u2;
            __shared__ T not_neighbours[2];
            __shared__ T not_neighbours_count;

            if (threadIdx.x == 0)
            {
              u1 = sh.usrcLen;
              u2 = sh.usrcLen;
              not_neighbours_count = 0;
            }
            
            __syncthreads();

            for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
            { 
              const T block_of_idx = block_idx == j ? ri_idx : 0x00000000;
              const T last_mask = j == sh.lastMask_i ? sh.lastMask_ii : 0xFFFFFFFF;
              T lone_vertex_block = (sh.to_bl[j] & ~(sh.encode[idx * num_divs_local + j] | block_of_idx)) & last_mask;
              T lone_vertex_idx_block = 0;
              while ((lone_vertex_idx_block = __ffs(lone_vertex_block)) != 0)
              {
                const T count = atomicAdd(&not_neighbours_count, 1);
                if (count < 2)
                  not_neighbours[count] = (j << 5) + lone_vertex_idx_block - 1;
                
                lone_vertex_block ^= 1 << (lone_vertex_idx_block - 1);
              }
            }

            __syncthreads();

            if (not_neighbours_count == 2) {

              if (threadIdx.x == 0)
              { 
                u1 = not_neighbours[0];
                u2 = not_neighbours[1];
              }

              __syncthreads();

              // Remove u from g
              const T li_u1 = u1 >> 5;
              const T ri_u1 = 1 << (u1 & 0x1F);
              const T li_u2 = u2 >> 5;
              const T ri_u2 = 1 << (u2 & 0x1F);
              
              const bool u1_u2 = (sh.encode[u1 * num_divs_local + li_u2] & ri_u2) > 0;

              if (!u1_u2)
              {
                //if (threadIdx.x == 0) printf("Rule 3 applyied.\n");
  
                if (threadIdx.x == 0)
                {
                  sh.to_bl[li_u1] ^= ri_u1;
                  sh.to_bl[li_u2] ^= ri_u2;
                  mod_R -= 2;
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.to_bl[j] &sh.encode[u1 * num_divs_local + j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) {
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.to_bl[j] & sh.encode[u2 * num_divs_local + j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) {
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();
              }
              // } else {

              //   for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
              //     sh.to_col[j] = sh.to_bl[j] & sh.encode[u1 * num_divs_local + j] & sh.encode[u2 * num_divs_local + j];

              //   __syncthreads();

              //   __shared__ T common_indices;
              //   if ((common_indices = popc<T, BLOCK_DIM_X, CPARTSIZE>(lh, sh.to_col, num_divs_local)) + 2 < k)
              //   {
              //     if (threadIdx.x == 0)
              //     {
              //       sh.to_bl[li_u1] ^= ri_u1;
              //       sh.to_bl[li_u2] ^= ri_u2;
              //       mod_R -= 2;
              //     }

              //     __syncthreads();

              //     for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
              //     {
              //       T neighbour_block = sh.encode[u1 * num_divs_local + j] & sh.to_bl[j];
              //       T neighbour_block_idx = 0;
              //       while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
              //       {
              //         const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
              //         sh.degree[neighbour_idx]--;
              //         const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
              //         if (sh.degree[neighbour_idx] == 0) {
              //           sh.to_bl[j] ^= neighbour_block_bit;
              //           atomicSub(&mod_R, 1);
              //         }
              //         neighbour_block ^= neighbour_block_bit;
              //       }
              //     }

              //     __syncthreads();

              //     for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
              //     {
              //       T neighbour_block = sh.encode[u2 * num_divs_local + j] & sh.to_bl[j];
              //       T neighbour_block_idx = 0;
              //       while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
              //       {
              //         const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
              //         sh.degree[neighbour_idx]--;
              //         const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
              //         if (sh.degree[neighbour_idx] == 0) {
              //           sh.to_bl[j] ^= neighbour_block_bit;
              //           atomicSub(&mod_R, 1);
              //         }
              //         neighbour_block ^= neighbour_block_bit;
              //       }
              //     }

              //     __syncthreads();
              //   } else if (common_indices + 2 >= sh.degree[idx] + 1) {

              //     // remove u from G
              //     if (threadIdx.x == 0)
              //     {
              //       //printf ("Rule 1 applyied\n");
              //       sh.to_bl[block_idx] ^= ri_idx;
              //       mod_R--;
              //     }

              //     __syncthreads();

              //     for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
              //     {
              //       T neighbour_block = sh.encode[idx * num_divs_local + j] & sh.to_bl[j];
              //       T neighbour_block_idx = 0;
              //       while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
              //       {
              //         const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
              //         sh.degree[neighbour_idx]--;
              //         const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
              //         if (sh.degree[neighbour_idx] == 0) {
              //           sh.to_bl[j] ^= neighbour_block_bit;
              //           atomicSub(&mod_R, 1);
              //         }
              //         neighbour_block ^= neighbour_block_bit;
              //       }
              //     }

              //     __syncthreads();
              //   }

              //   __syncthreads();
              // }
            
            }

            __syncthreads();
            continue;
          }
       
          bool rule_4 = sh.degree[idx] == mod_R - 4;
          if (!rule_1 && rule_4)
          {
            __shared__ T u1, u2, u3;
            __shared__ T not_neighbours[3];
            __shared__ T not_neighbours_count;

            if (threadIdx.x == 0)
            {
              u1 = sh.usrcLen;
              u2 = sh.usrcLen;
              u3 = sh.usrcLen;
              not_neighbours_count = 0;
            }
            
            __syncthreads();

            for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
            { 
              const T block_of_idx = block_idx == j ? ri_idx : 0x00000000;
              const T last_mask = j == sh.lastMask_i ? sh.lastMask_ii : 0xFFFFFFFF;
              T lone_vertex_block = (sh.to_bl[j] & ~(sh.encode[idx * num_divs_local + j] | block_of_idx)) & last_mask;
              T lone_vertex_idx_block = 0;
              while((lone_vertex_idx_block = __ffs(lone_vertex_block)) != 0)
              {
                const T count = atomicAdd(&not_neighbours_count, 1);
                if (count < 3) not_neighbours[count] = (j << 5) + lone_vertex_idx_block - 1;
                lone_vertex_block ^= 1 << (lone_vertex_idx_block - 1);
              }
            }

            __syncthreads();

            if (not_neighbours_count == 3) {

              if (threadIdx.x == 0) 
              {
                u1 = not_neighbours[0];
                u2 = not_neighbours[1];
                u3 = not_neighbours[2];
              }

              __syncthreads();

              // Remove u from g
              const T li_u1 = u1 >> 5;
              const T ri_u1 = 1 << (u1 & 0x1F);
              const T li_u2 = u2 >> 5;
              const T ri_u2 = 1 << (u2 & 0x1F);
              const T li_u3 = u3 >> 5;
              const T ri_u3 = 1 << (u3 & 0x1F);
              
              bool u1_u2 = (sh.encode[u1 * num_divs_local + li_u2] & ri_u2) > 0;
              bool u1_u3 = (sh.encode[u1 * num_divs_local + li_u3] & ri_u3) > 0;
              bool u2_u3 = (sh.encode[u2 * num_divs_local + li_u3] & ri_u3) > 0;

              __syncthreads();

              if (!u1_u2 && !u1_u3 && !u2_u3) // |E(G)| = 0
              {
  
                if (threadIdx.x == 0)
                {
                  sh.to_bl[li_u1] ^= ri_u1;
                  sh.to_bl[li_u2] ^= ri_u2;
                  sh.to_bl[li_u3] ^= ri_u3;
                  mod_R -= 3;
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.to_bl[j] & sh.encode[u1 * num_divs_local + j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) {
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.to_bl[j] & sh.encode[u2 * num_divs_local + j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) {
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.to_bl[j] & sh.encode[u3 * num_divs_local + j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) {
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();
              }
              else if (!u1_u2 && !u1_u3 && u2_u3)
              {
  
                if (threadIdx.x == 0)
                {
                  sh.to_bl[li_u1] ^= ri_u1;
                  mod_R--;
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.to_bl[j] & sh.encode[u1 * num_divs_local + j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) {
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();

              }
              else if (!u1_u2 && !u2_u3 && u1_u3)
              {
  
                if (threadIdx.x == 0)
                {
                  sh.to_bl[li_u2] ^= ri_u2;
                  mod_R--;
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.to_bl[j] & sh.encode[u2 * num_divs_local + j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) {
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();

              }
              else if (!u1_u3 && !u2_u3 && u1_u2)
              {
              
                if (threadIdx.x == 0)
                {
                  sh.to_bl[li_u3] ^= ri_u3;
                  mod_R--;
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.to_bl[j] & sh.encode[u3 * num_divs_local + j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) {
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();

              }
              /*else {
                
                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                  sh.to_col[j] = sh.to_bl[j] & sh.encode[u1 * num_divs_local + j] & sh.encode[u2 * num_divs_local + j] & sh.encode[u3 * num_divs_local + j];

                __syncthreads();

                const T deg_u1u2u3 = popc<T, BLOCK_DIM_X, CPARTSIZE>(lh, sh.to_col, num_divs_local);

                __syncthreads();

                if (deg_u1u2u3 + 3 < k)
                {
                  if (threadIdx.x == 0)
                  {
                    sh.to_bl[li_u1] ^= ri_u1;
                    sh.to_bl[li_u2] ^= ri_u2;
                    sh.to_bl[li_u3] ^= ri_u3;
                    mod_R -= 3;
                  }

                  __syncthreads();

                  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                  {
                    T neighbour_block = sh.encode[u1 * num_divs_local + j] & sh.to_bl[j];
                    T neighbour_block_idx = 0;
                    while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                    {
                      const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                      sh.degree[neighbour_idx]--;
                      const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                      if (sh.degree[neighbour_idx] == 0) {
                        sh.to_bl[j] ^= neighbour_block_bit;
                        atomicSub(&mod_R, 1);
                      }
                      neighbour_block ^= neighbour_block_bit;
                    }
                  }

                  __syncthreads();

                  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                  {
                    T neighbour_block = sh.encode[u2 * num_divs_local + j] & sh.to_bl[j];
                    T neighbour_block_idx = 0;
                    while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                    {
                      const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                      sh.degree[neighbour_idx]--;
                      const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                      if (sh.degree[neighbour_idx] == 0) {
                        sh.to_bl[j] ^= neighbour_block_bit;
                        atomicSub(&mod_R, 1);
                      }
                      neighbour_block ^= neighbour_block_bit;
                    }
                  }

                  __syncthreads();

                  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                  {
                    T neighbour_block = sh.encode[u3 * num_divs_local + j] & sh.to_bl[j];
                    T neighbour_block_idx = 0;
                    while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                    {
                      const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                      sh.degree[neighbour_idx]--;
                      const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                      if (sh.degree[neighbour_idx] == 0) {
                        sh.to_bl[j] ^= neighbour_block_bit;
                        atomicSub(&mod_R, 1);
                      }
                      neighbour_block ^= neighbour_block_bit;
                    }
                  }

                  __syncthreads();
                }
              }*/
            }

            __syncthreads();
            continue;
          }
        
          bool rule_5 = sh.degree[idx] >= k - 1 && sh.degree[idx] >= mod_R - 50 && sh.degree[idx] < mod_R - 4;
          if (false && !rule_1 && rule_5)
          {
            __shared__ T not_neighbours[50];
            __shared__ T not_neighbours_count;

            if (threadIdx.x == 0)
            {
              not_neighbours_count = 0;
            }
            
            __syncthreads();

            for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
            { 
              const T block_of_idx = block_idx == j ? ri_idx : 0x00000000;
              const T last_mask = j == sh.lastMask_i ? sh.lastMask_ii : 0xFFFFFFFF;
              sh.to_col[j] = (sh.to_bl[j] & ~(sh.encode[idx * num_divs_local + j] | block_of_idx)) & last_mask;
              T lone_vertex_block = sh.to_col[j];
              T lone_vertex_idx_block = 0;
              while((lone_vertex_idx_block = __ffs(lone_vertex_block)) != 0)
              {
                const T count = atomicAdd(&not_neighbours_count, 1);
                if (count < 50) not_neighbours[count] = (j << 5) + lone_vertex_idx_block - 1;
                lone_vertex_block ^= 1 << (lone_vertex_idx_block - 1);
              }
            }

            __syncthreads();

            if (not_neighbours_count >= 5 && not_neighbours_count <= 50)
            {
              
              for (T not_neighbour_idx = 0; not_neighbour_idx < not_neighbours_count; not_neighbour_idx++)
              { 

                __shared__ T mod_N;
                T local_mod_N = 0;
                const T not_neighbour = not_neighbours[not_neighbour_idx];

                if (threadIdx.x == 0) mod_N = 0;

                __syncthreads();
                
                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  local_mod_N += __popc(sh.to_col[j] & sh.encode[not_neighbour * num_divs_local + j]);
                }

                __syncthreads();
                
                reduce_part<T, CPARTSIZE>(lh.partMask, local_mod_N);

                __syncthreads();

                if (lh.lx == 0)
                {
                  atomicAdd(&mod_N, local_mod_N);
                }

                __syncthreads();

                if (mod_N == 0)
                {

                  if (threadIdx.x == 0)
                  {
                    const T nn_li = not_neighbour >> 5;
                    const T nn_ri = 1 << (not_neighbour & 0x1F);
                    sh.to_bl[nn_li] ^= nn_ri;
                    mod_R--;
                  }

                  __syncthreads();

                  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                  {
                    T neighbour_block = sh.encode[not_neighbour * num_divs_local + j] & sh.to_bl[j];
                    T neighbour_block_idx = 0;
                    while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                    {
                      const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                      sh.degree[neighbour_idx]--;
                      const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                      if (sh.degree[neighbour_idx] == 0) {
                        sh.to_bl[j] ^= neighbour_block_bit;
                        atomicSub(&mod_R, 1);
                      }
                      neighbour_block ^= neighbour_block_bit;
                    }
                  }

                __syncthreads();
                }

                __syncthreads();
              }
            }

            __syncthreads();
            continue;

          }
        }

        __syncthreads();
      }
      
      __syncthreads();

    }
    
    __syncthreads();
    if (mod_R == preSize || mod_R < k) break;
    __syncthreads();

  }

  __syncthreads();

  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
  {
    cur_pl[j] = sh.to_bl[j];
  } 

  __syncthreads();
  if (mod_R < k) { if (threadIdx.x == 0) sh.l--; __syncthreads(); return true;}

  __syncthreads();
  return false;

}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool reduce_second_level(
    GLOBAL_HANDLE<T> &gh, LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh,
    const T& num_divs_local, const int level
    )
{
  __shared__ T mod_R;
  __shared__ T min_degree;
  __shared__ T k;

  if (threadIdx.x == 0)
  {
    mod_R = 0;
    min_degree = sh.usrcLen;
    k = (T)(*gh.Cmax_size) >= level ? (T)(*gh.Cmax_size) - level : 0;
  }

  __syncthreads();

  if (k <= 2) return false;

  __syncthreads();

  //////////////// Compute degrees /////////////////////////////////////////////////////////

  for (T block_idx = lh.wx; block_idx < num_divs_local; block_idx += lh.numPartitions)
  { 
    T idx_block = 0;
    T block = sh.to_bl[block_idx];
    while ((idx_block = __ffs(block)) != 0)
    {
      T idx_degree = 0;
      T idx = (block_idx << 5) + idx_block - 1;
      for (T j = lh.lx; j < num_divs_local; j += CPARTSIZE)
        if (sh.to_bl[j] != 0)
          idx_degree += __popc(sh.to_bl[j] & sh.encode[idx * num_divs_local + j]);

      __syncwarp();

      reduce_part<T, CPARTSIZE>(lh.partMask, idx_degree);
      
      __syncwarp();

      if (lh.lx == 0) 
      {
        sh.degree[idx] = idx_degree;
        atomicAdd(&mod_R, 1);
        atomicMin(&min_degree, idx_degree);
      }
      __syncwarp();

      block ^= 1 << (idx_block - 1);

      __syncwarp();
    }
    __syncwarp();
  }

  __syncthreads();

  if (min_degree == mod_R - 1)
  {
    if (threadIdx.x == 0)
    {
      const T old = atomicMax((uint32_t*)gh.Cmax_size, sh.l + mod_R - 1);
      if (old < sh.l + mod_R - 1)
      {
        printf("Reduce finds clique of size %u.\n", *(gh.Cmax_size));
      }
    }
    __syncthreads();
    return true;
  }
  
  ////////////////////////////////////////////////////////////////////////////////////////////
 
  __syncthreads();

  for (T idx = threadIdx.x; idx < sh.usrcLen; idx += BLOCK_DIM_X)
  {
    const T li = idx >> 5;
    const T ri = 1 << (idx & 0x1F);
    if ((sh.to_bl[li] & ri) > 0)
    {
      if (sh.degree[idx] == 0)
      {
        atomicXor(&sh.to_bl[li], ri);
        atomicSub(&mod_R, 1);
      } 
    }
  }

  __syncthreads(); 

  // mod_R = popc<T, BLOCK_DIM_X, CPARTSIZE>(lh, sh.to_bl, num_divs_local);

  // __syncthreads();

  // Reduce
  while (true)
  {
    __shared__ T preSize;

    if (threadIdx.x == 0)
      preSize = mod_R;

    __syncthreads();

    // for each index of R
    for (T idx = 0; idx < sh.usrcLen; idx++)
    { 
      
      const T block_idx = idx >> 5;
      const T ri_idx = 1 << (idx & 0x1F);
      if ((sh.to_bl[block_idx] & ri_idx) > 0)
      {

        if (sh.degree[idx] < k - 1 || sh.degree[idx] >= mod_R - 4)
        {
          bool rule_1 = sh.degree[idx] < k - 1;
          if (rule_1)
          {
            // remove u from G
            if (threadIdx.x == 0)
            {
              //printf ("Rule 1 applyied\n");
              sh.to_bl[block_idx] ^= ri_idx;
              mod_R--;
            }

            __syncthreads();

            for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
            {
              T neighbour_block = sh.encode[idx * num_divs_local + j] & sh.to_bl[j];
              T neighbour_block_idx = 0;
              while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
              {
                const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                sh.degree[neighbour_idx]--;
                const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                if (sh.degree[neighbour_idx] == 0) {
                  sh.to_bl[j] ^= neighbour_block_bit;
                  atomicSub(&mod_R, 1);
                }
                neighbour_block ^= neighbour_block_bit;
              }
            }

            __syncthreads();
            continue;
      
          }

          bool rule_2 = sh.degree[idx] == mod_R - 2;
          if (!rule_1 && rule_2)
          {
            __shared__ T u;
            __shared__ T not_neighbours;
            __shared__ T not_neighbours_count;

            if (threadIdx.x == 0)
            {
              u = sh.usrcLen;
              not_neighbours_count = 0;
            }
            
            __syncthreads();

            for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
            { 
              T block_of_idx = block_idx == j ? ri_idx : 0x00000000;
              T last_mask = j == sh.lastMask_i ? sh.lastMask_ii : 0xFFFFFFFF;
              T lone_vertex_block = (sh.to_bl[j] & ~(sh.encode[idx * num_divs_local + j] | block_of_idx)) & last_mask;
              T lone_vertex_idx_block = 0;
              while((lone_vertex_idx_block = __ffs(lone_vertex_block)) != 0)
              {
                const T count = atomicAdd(&not_neighbours_count, 1);
                if (count == 0) not_neighbours = (j << 5) + lone_vertex_idx_block - 1;
                lone_vertex_block ^= 1 << (lone_vertex_idx_block - 1);
              }
            }

            __syncthreads();

            if (not_neighbours_count == 1) {

              if (threadIdx.x == 0) 
              { 
                //printf("Rule 2 applyied\n");
                u = not_neighbours;
              }
              __syncthreads();

              // Remove u from R
              if (threadIdx.x == 0)
              {
                const T li_u = u >> 5;
                const T ri_u = 1 << (u & 0x1F);
                sh.to_bl[li_u] ^= ri_u;
                mod_R--;
              }

              __syncthreads();

              for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
              {
                T neighbour_block = sh.encode[u * num_divs_local + j] & sh.to_bl[j];
                T neighbour_block_idx = 0;
                while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                {
                  const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                  sh.degree[neighbour_idx]--;
                  const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                  if (sh.degree[neighbour_idx] == 0) 
                  {
                    sh.to_bl[j] ^= neighbour_block_bit;
                    atomicSub(&mod_R, 1);
                  }
                  neighbour_block ^= neighbour_block_bit;
                }
              }

            }

            __syncthreads();
            continue;
          }

          bool rule_3 = sh.degree[idx] == mod_R - 3;
          if (!rule_1 && rule_3)
          {
            __shared__ T u1, u2;
            __shared__ T not_neighbours[2];
            __shared__ T not_neighbours_count;

            if (threadIdx.x == 0)
            {
              u1 = sh.usrcLen;
              u2 = sh.usrcLen;
              not_neighbours_count = 0;
            }
            
            __syncthreads();

            for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
            { 
              const T block_of_idx = block_idx == j ? ri_idx : 0x00000000;
              const T last_mask = j == sh.lastMask_i ? sh.lastMask_ii : 0xFFFFFFFF;
              T lone_vertex_block = (sh.to_bl[j] & ~(sh.encode[idx * num_divs_local + j] | block_of_idx)) & last_mask;
              T lone_vertex_idx_block = 0;
              while ((lone_vertex_idx_block = __ffs(lone_vertex_block)) != 0)
              {
                const T count = atomicAdd(&not_neighbours_count, 1);
                if (count < 2) {
                  not_neighbours[count] = (j << 5) + lone_vertex_idx_block - 1;
                  atomicSub(&mod_R, 1);
                }
                
                lone_vertex_block ^= 1 << (lone_vertex_idx_block - 1);
              }
            }

            __syncthreads();

            if (not_neighbours_count == 2) {

              if (threadIdx.x == 0)
              { 
                u1 = not_neighbours[0];
                u2 = not_neighbours[1];
              }

              __syncthreads();

              // Remove u from g
              const T li_u1 = u1 >> 5;
              const T ri_u1 = 1 << (u1 & 0x1F);
              const T li_u2 = u2 >> 5;
              const T ri_u2 = 1 << (u2 & 0x1F);
              
              const bool u1_u2 = (sh.encode[u1 * num_divs_local + li_u2] & ri_u2) > 0;

              if (!u1_u2)
              {
                //if (threadIdx.x == 0) printf("Rule 3 applyied.\n");
  
                if (threadIdx.x == 0)
                {
                  sh.to_bl[li_u1] ^= ri_u1;
                  sh.to_bl[li_u2] ^= ri_u2;
                  mod_R -= 2;
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.encode[u1 * num_divs_local + j] & sh.to_bl[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) 
                    { 
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.encode[u2 * num_divs_local + j] & sh.to_bl[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) 
                    {
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();

              } 
            }
            

            __syncthreads();
            continue;
          }
       
          bool rule_4 = sh.degree[idx] == mod_R - 4;
          if (!rule_1 && rule_4)
          {
            __shared__ T u1, u2, u3;
            __shared__ T not_neighbours[3];
            __shared__ T not_neighbours_count;

            if (threadIdx.x == 0)
            {
              u1 = sh.usrcLen;
              u2 = sh.usrcLen;
              u3 = sh.usrcLen;
              not_neighbours_count = 0;
            }
            
            __syncthreads();

            for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
            { 
              const T block_of_idx = block_idx == j ? ri_idx : 0x00000000;
              const T last_mask = j == sh.lastMask_i ? sh.lastMask_ii : 0xFFFFFFFF;
              T lone_vertex_block = (sh.to_bl[j] & ~(sh.encode[idx * num_divs_local + j] | block_of_idx)) & last_mask;
              T lone_vertex_idx_block = 0;
              while((lone_vertex_idx_block = __ffs(lone_vertex_block)) != 0)
              {
                const T count = atomicAdd(&not_neighbours_count, 1);
                if (count < 3) not_neighbours[count] = (j << 5) + lone_vertex_idx_block - 1;
                lone_vertex_block ^= 1 << (lone_vertex_idx_block - 1);
              }
            }

            __syncthreads();

            if (not_neighbours_count == 3) {

              if (threadIdx.x == 0) 
              {
                u1 = not_neighbours[0];
                u2 = not_neighbours[1];
                u3 = not_neighbours[2];
              }

              __syncthreads();

              // Remove u from g
              const T li_u1 = u1 >> 5;
              const T ri_u1 = 1 << (u1 & 0x1F);
              const T li_u2 = u2 >> 5;
              const T ri_u2 = 1 << (u2 & 0x1F);
              const T li_u3 = u3 >> 5;
              const T ri_u3 = 1 << (u3 & 0x1F);
              
              bool u1_u2 = (sh.encode[u1 * num_divs_local + li_u2] & ri_u2) > 0;
              bool u1_u3 = (sh.encode[u1 * num_divs_local + li_u3] & ri_u3) > 0;
              bool u2_u3 = (sh.encode[u2 * num_divs_local + li_u3] & ri_u3) > 0;

              __syncthreads();

              if (!u1_u2 && !u1_u3 && !u2_u3) // |E(G)| = 0
              {
  
                if (threadIdx.x == 0)
                {
                  sh.to_bl[li_u1] ^= ri_u1;
                  sh.to_bl[li_u2] ^= ri_u2;
                  sh.to_bl[li_u3] ^= ri_u3;
                  mod_R -= 3;
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.encode[u1 * num_divs_local + j] & sh.to_bl[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) {
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.encode[u2 * num_divs_local + j] & sh.to_bl[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) 
                    {
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.encode[u3 * num_divs_local + j] & sh.to_bl[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) 
                    { 
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();
              }
              else if (!u1_u2 && !u1_u3 && u2_u3)
              {
  
                if (threadIdx.x == 0)
                {
                  sh.to_bl[li_u1] ^= ri_u1;
                  mod_R--;
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.encode[u1 * num_divs_local + j] & sh.to_bl[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) {
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();

              }
              else if (!u1_u2 && !u2_u3 && u1_u3)
              {
  
                if (threadIdx.x == 0)
                {
                  sh.to_bl[li_u2] ^= ri_u2;
                  mod_R--;
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.encode[u2 * num_divs_local + j] & sh.to_bl[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) 
                    { 
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();

              }
              else if (!u1_u3 && !u2_u3 && u1_u2)
              {
              
                if (threadIdx.x == 0)
                {
                  sh.to_bl[li_u3] ^= ri_u3;
                  mod_R--;
                }

                __syncthreads();

                for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
                {
                  T neighbour_block = sh.encode[u3 * num_divs_local + j] & sh.to_bl[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    sh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (sh.degree[neighbour_idx] == 0) {
                      sh.to_bl[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R, 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncthreads();

              }

            }

            __syncthreads();
            continue;
          }
        }

        __syncthreads();
      }
      
      __syncthreads();
    }
    
    __syncthreads();
    if (mod_R == preSize || mod_R < k) break;
    __syncthreads();

  }

  __syncthreads();

  if (mod_R < k) {__syncthreads(); return true;}
  return false;

}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ bool warp_reduce(
    GLOBAL_HANDLE<T> &gh, LOCAL_HANDLE<T> &lh, 
    WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh,
    const T& num_divs_local, const int level,
    T * cur_pl
    )
{
  // Compute degrees
  for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
  {
    wsh.to_col[j] = cur_pl[j]; 
  }

  __shared__ T __warp__(mod_R);
  __shared__ T __warp__(min_degree);
  __shared__ T __warp__(k);

  if (laneIdx == 0)
  {
    mod_R[warpIdx] = 0;
    min_degree[warpIdx] = wsh.usrcLen;
    k[warpIdx] = (T)(*gh.Cmax_size) >= level ? (T)(*gh.Cmax_size) - level : 0;
  }

  __syncwarp();

  if (k[warpIdx] <= 2) return false;

  __syncwarp();

  //////////////// Compute degrees /////////////////////////////////////////////////////////

  for (T block_idx = 0; block_idx < num_divs_local; block_idx++)
  { 
    T idx_block = 0;
    T block = wsh.to_col[block_idx];
    while ((idx_block = __ffs(block)) != 0)
    {
      T idx_degree = 0;
      T idx = (block_idx << 5) + idx_block - 1;
      for (T j = lh.lx; j < num_divs_local; j += CPARTSIZE)
          idx_degree += __popc(wsh.to_col[j] & wsh.encode[idx * num_divs_local + j]);

      __syncwarp();

      reduce_part<T, CPARTSIZE>(lh.partMask, idx_degree);
      
      __syncwarp();

      if (lh.lx == 0) 
      {
        wsh.degree[idx] = idx_degree;
        mod_R[warpIdx]++;
        min_degree[warpIdx] = min(min_degree[warpIdx], idx_degree);
      }
      __syncwarp();

      block ^= 1 << (idx_block - 1);

      __syncwarp();
    }
    __syncwarp();
  }

  __syncwarp();
  if (min_degree[warpIdx] == mod_R[warpIdx] - 1)
  {
    if (laneIdx == 0)
    {
      const T old = atomicMax((uint32_t*)gh.Cmax_size, wsh.l + mod_R[warpIdx] - 1);
      if (old < wsh.l + mod_R[warpIdx] - 1)
        printf("Reduce finds clique of size %u.\n", *(gh.Cmax_size));
      wsh.l--;
    }
    __syncwarp();
    return true;
  }
  
  ////////////////////////////////////////////////////////////////////////////////////////////
 
  __syncwarp();

  for (T idx = laneIdx; idx < wsh.usrcLen; idx += CPARTSIZE)
  {
    const T li = idx >> 5;
    const T ri = 1 << (idx & 0x1F);
    if ((wsh.to_col[li] & ri) > 0)
    {
      if (wsh.degree[idx] == 0)
      {
        atomicXor(&wsh.to_col[li], ri);
        atomicSub(&mod_R[warpIdx], 1);
      } 
    }
  }

  __syncwarp(); 

  // mod_R = popc<T, BLOCK_DIM_X, CPARTSIZE>(lh, sh.to_bl, num_divs_local);

  // __syncthreads();

  // Reduce
  while (true)
  {
    __shared__ T __warp__(preSize);

    if (laneIdx == 0)
      preSize[warpIdx] = mod_R[warpIdx];

    __syncwarp();

    // for each index of R
    for (T idx = 0; idx < wsh.usrcLen; idx++)
    { 
      
      const T block_idx = idx >> 5;
      const T ri_idx = 1 << (idx & 0x1F);
      if ((wsh.to_col[block_idx] & ri_idx) > 0)
      {

        if (wsh.degree[idx] < k[warpIdx] - 1 || wsh.degree[idx] >= mod_R[warpIdx] - 4)
        {
          const bool rule_1 = wsh.degree[idx] < k[warpIdx] - 1;
          if (rule_1)
          {
            // remove u from G
            if (laneIdx == 0)
            {
              //printf ("Rule 1 applyied\n");
              wsh.to_col[block_idx] ^= ri_idx;
              mod_R[warpIdx]--;
            }

            __syncwarp();

            for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
            {
              T neighbour_block = wsh.encode[idx * num_divs_local + j] & wsh.to_col[j];
              T neighbour_block_idx = 0;
              while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
              {
                const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                wsh.degree[neighbour_idx]--;
                const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                if (wsh.degree[neighbour_idx] == 0) {
                  wsh.to_col[j] ^= neighbour_block_bit;
                  atomicSub(&mod_R[warpIdx], 1);
                }
                neighbour_block ^= neighbour_block_bit;
              }
            }

            __syncwarp();
            continue;
      
          }

          const bool rule_2 = wsh.degree[idx] == mod_R[warpIdx] - 2;
          if (!rule_1 && rule_2)
          {
            __shared__ T __warp__(u);
            __shared__ T __warp__(not_neighbours);
            __shared__ T __warp__(not_neighbours_count);

            if (laneIdx == 0)
            {
              u[warpIdx] = wsh.usrcLen;
              not_neighbours_count[warpIdx] = 0;
            }
            
            __syncwarp();

            for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
            { 
              T block_of_idx = block_idx == j ? ri_idx : 0x00000000;
              T last_mask = j == wsh.lastMask_i ? wsh.lastMask_ii : 0xFFFFFFFF;
              T lone_vertex_block = (wsh.to_col[j] & ~(wsh.encode[idx * num_divs_local + j] | block_of_idx)) & last_mask;
              T lone_vertex_idx_block = 0;
              while((lone_vertex_idx_block = __ffs(lone_vertex_block)) != 0)
              {
                const T count = atomicAdd(&not_neighbours_count[warpIdx], 1);
                if (count == 0) not_neighbours[warpIdx] = (j << 5) + lone_vertex_idx_block - 1;
                lone_vertex_block ^= 1 << (lone_vertex_idx_block - 1);
              }
            }

            __syncwarp();

            if (not_neighbours_count[warpIdx] == 1) {

              if (laneIdx == 0) 
              { 
                //printf("Rule 2 applyied\n");
                u[warpIdx] = not_neighbours[warpIdx];
              }
              __syncwarp();

              // Remove u from R
              if (laneIdx == 0)
              {
                const T li_u = u[warpIdx] >> 5;
                const T ri_u = 1 << (u[warpIdx] & 0x1F);
                wsh.to_col[li_u] ^= ri_u;
                mod_R[warpIdx]--;
              }

              __syncwarp();

              for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
              {
                T neighbour_block = wsh.encode[u[warpIdx] * num_divs_local + j] & wsh.to_col[j];
                T neighbour_block_idx = 0;
                while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                {
                  const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                  wsh.degree[neighbour_idx]--;
                  const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                  if (wsh.degree[neighbour_idx] == 0) {
                    wsh.to_col[j] ^= neighbour_block_bit;
                    atomicSub(&mod_R[warpIdx], 1);
                  }
                  neighbour_block ^= neighbour_block_bit;
                }
              }

            }

            __syncwarp();
            continue;
          }

          const bool rule_3 = wsh.degree[idx] == mod_R[warpIdx] - 3;
          if (!rule_1 && rule_3)
          {
            __shared__ T __warp__(u1), __warp__(u2);
            __shared__ T __warp__(not_neighbours)[2];
            __shared__ T __warp__(not_neighbours_count);

            if (laneIdx == 0)
            {
              u1[warpIdx] = wsh.usrcLen;
              u2[warpIdx] = wsh.usrcLen;
              not_neighbours_count[warpIdx] = 0;
            }
            
            __syncwarp();

            for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
            { 
              const T block_of_idx = block_idx == j ? ri_idx : 0x00000000;
              const T last_mask = j == wsh.lastMask_i ? wsh.lastMask_ii : 0xFFFFFFFF;
              T lone_vertex_block = (wsh.to_col[j] & ~(wsh.encode[idx * num_divs_local + j] | block_of_idx)) & last_mask;
              T lone_vertex_idx_block = 0;
              while ((lone_vertex_idx_block = __ffs(lone_vertex_block)) != 0)
              {
                const T count = atomicAdd(&not_neighbours_count[warpIdx], 1);
                if (count < 2)
                  not_neighbours[warpIdx][count] = (j << 5) + lone_vertex_idx_block - 1;
                
                lone_vertex_block ^= 1 << (lone_vertex_idx_block - 1);
              }
            }

            __syncwarp();

            if (not_neighbours_count[warpIdx] == 2) {

              if (laneIdx == 0)
              { 
                u1[warpIdx] = not_neighbours[warpIdx][0];
                u2[warpIdx] = not_neighbours[warpIdx][1];
              }

              __syncwarp();

              // Remove u from g
              const T li_u1 = u1[warpIdx] >> 5;
              const T ri_u1 = 1 << (u1[warpIdx] & 0x1F);
              const T li_u2 = u2[warpIdx] >> 5;
              const T ri_u2 = 1 << (u2[warpIdx] & 0x1F);
              
              const bool u1_u2 = (wsh.encode[u1[warpIdx] * num_divs_local + li_u2] & ri_u2) > 0;

              if (!u1_u2)
              {
                //if (threadIdx.x == 0) printf("Rule 3 applyied.\n");
  
                if (laneIdx == 0)
                {
                  wsh.to_col[li_u1] ^= ri_u1;
                  wsh.to_col[li_u2] ^= ri_u2;
                  mod_R[warpIdx] -= 2;
                }

                __syncwarp();

                for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
                {
                  T neighbour_block = wsh.encode[u1[warpIdx] * num_divs_local + j] & wsh.to_col[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    wsh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (wsh.degree[neighbour_idx] == 0) {
                      wsh.to_col[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R[warpIdx], 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncwarp();

                for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
                {
                  T neighbour_block = wsh.encode[u2[warpIdx] * num_divs_local + j] & wsh.to_col[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    wsh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (wsh.degree[neighbour_idx] == 0) {
                      wsh.to_col[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R[warpIdx], 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncwarp();

              } 
            
            }

            __syncwarp();
            continue;
          }
       
          const bool rule_4 = wsh.degree[idx] == mod_R[warpIdx] - 4;
          if (!rule_1 && rule_4)
          {
            __shared__ T __warp__(u1), __warp__(u2), __warp__(u3);
            __shared__ T __warp__(not_neighbours)[3];
            __shared__ T __warp__(not_neighbours_count);

            if (laneIdx == 0)
            {
              u1[warpIdx] = wsh.usrcLen;
              u2[warpIdx] = wsh.usrcLen;
              u3[warpIdx] = wsh.usrcLen;
              not_neighbours_count[warpIdx] = 0;
            }
            
            __syncwarp();

            for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
            { 
              const T block_of_idx = block_idx == j ? ri_idx : 0x00000000;
              const T last_mask = j == wsh.lastMask_i ? wsh.lastMask_ii : 0xFFFFFFFF;
              T lone_vertex_block = (wsh.to_col[j] & ~(wsh.encode[idx * num_divs_local + j] | block_of_idx)) & last_mask;
              T lone_vertex_idx_block = 0;
              while((lone_vertex_idx_block = __ffs(lone_vertex_block)) != 0)
              {
                const T count = atomicAdd(&not_neighbours_count[warpIdx], 1);
                if (count < 3) not_neighbours[warpIdx][count] = (j << 5) + lone_vertex_idx_block - 1;
                lone_vertex_block ^= 1 << (lone_vertex_idx_block - 1);
              }
            }

            __syncwarp();

            if (not_neighbours_count[warpIdx] == 3) {

              if (laneIdx == 0) 
              {
                u1[warpIdx] = not_neighbours[warpIdx][0];
                u2[warpIdx] = not_neighbours[warpIdx][1];
                u3[warpIdx] = not_neighbours[warpIdx][2];
              }

              __syncwarp();

              // Remove u from g
              const T li_u1 = u1[warpIdx] >> 5;
              const T ri_u1 = 1 << (u1[warpIdx] & 0x1F);
              const T li_u2 = u2[warpIdx] >> 5;
              const T ri_u2 = 1 << (u2[warpIdx] & 0x1F);
              const T li_u3 = u3[warpIdx] >> 5;
              const T ri_u3 = 1 << (u3[warpIdx] & 0x1F);
              
              bool u1_u2 = (wsh.encode[u1[warpIdx] * num_divs_local + li_u2] & ri_u2) > 0;
              bool u1_u3 = (wsh.encode[u1[warpIdx] * num_divs_local + li_u3] & ri_u3) > 0;
              bool u2_u3 = (wsh.encode[u2[warpIdx] * num_divs_local + li_u3] & ri_u3) > 0;

              __syncwarp();

              if (!u1_u2 && !u1_u3 && !u2_u3) // |E(G)| = 0
              {
  
                if (laneIdx == 0)
                {
                  wsh.to_col[li_u1] ^= ri_u1;
                  wsh.to_col[li_u2] ^= ri_u2;
                  wsh.to_col[li_u3] ^= ri_u3;
                  mod_R[warpIdx] -= 3;
                }

                __syncwarp();

                for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
                {
                  T neighbour_block = wsh.encode[u1[warpIdx] * num_divs_local + j] & wsh.to_col[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    wsh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (wsh.degree[neighbour_idx] == 0) {
                      wsh.to_col[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R[warpIdx], 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncwarp();

                for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
                {
                  T neighbour_block = wsh.encode[u2[warpIdx] * num_divs_local + j] & wsh.to_col[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    wsh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (wsh.degree[neighbour_idx] == 0) {
                      wsh.to_col[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R[warpIdx], 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncwarp();

                for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
                {
                  T neighbour_block = wsh.encode[u3[warpIdx] * num_divs_local + j] & wsh.to_col[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    wsh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (wsh.degree[neighbour_idx] == 0) {
                      wsh.to_col[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R[warpIdx], 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncwarp();
              }
              else if (!u1_u2 && !u1_u3 && u2_u3)
              {
  
                if (laneIdx == 0)
                {
                  wsh.to_col[li_u1] ^= ri_u1;
                  mod_R[warpIdx]--;
                }

                __syncwarp();

                for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
                {
                  T neighbour_block = wsh.encode[u1[warpIdx] * num_divs_local + j] & wsh.to_col[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    wsh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (wsh.degree[neighbour_idx] == 0) {
                      wsh.to_col[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R[warpIdx], 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncwarp();

              }
              else if (!u1_u2 && !u2_u3 && u1_u3)
              {
  
                if (laneIdx == 0)
                {
                  wsh.to_col[li_u2] ^= ri_u2;
                  mod_R[warpIdx]--;
                }

                __syncwarp();

                for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
                {
                  T neighbour_block = wsh.encode[u2[warpIdx] * num_divs_local + j] & wsh.to_col[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    wsh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (wsh.degree[neighbour_idx] == 0) {
                      wsh.to_col[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R[warpIdx], 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncwarp();

              }
              else if (!u1_u3 && !u2_u3 && u1_u2)
              {
              
                if (laneIdx == 0)
                {
                  wsh.to_col[li_u3] ^= ri_u3;
                  mod_R[warpIdx]--;
                }

                __syncwarp();

                for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
                {
                  T neighbour_block = wsh.encode[u3[warpIdx] * num_divs_local + j] & wsh.to_col[j];
                  T neighbour_block_idx = 0;
                  while ((neighbour_block_idx = __ffs(neighbour_block)) != 0)
                  {
                    const T neighbour_idx = (j << 5) + neighbour_block_idx - 1;
                    wsh.degree[neighbour_idx]--;
                    const T neighbour_block_bit = 1 << (neighbour_block_idx - 1);
                    if (wsh.degree[neighbour_idx] == 0) {
                      wsh.to_col[j] ^= neighbour_block_bit;
                      atomicSub(&mod_R[warpIdx], 1);
                    }
                    neighbour_block ^= neighbour_block_bit;
                  }
                }

                __syncwarp();

              }

            }

            __syncwarp();
            continue;
          }
        }

        __syncwarp();
      }
      
      __syncwarp();

    }
    
    __syncwarp();
    if (mod_R[warpIdx] == preSize[warpIdx] || mod_R[warpIdx] < k[warpIdx]) break;
    __syncwarp();

  }

  __syncwarp();

  for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
  {
    cur_pl[j] = wsh.to_col[j];
  } 

  __syncwarp();
  assert(mod_R >= 0);
  if (mod_R[warpIdx] < k[warpIdx]) { if (laneIdx == 0) wsh.l--; __syncwarp(); return true;}
  return false;

}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ int compute_upperbound_chromatic_number_psanse(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, const int ub,
    const T& num_divs_local
    )
{
  __shared__ int color;
  __shared__ T pointer;

  fetch(color, 1);

  __syncthreads();

  // UNCOL = P
  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
  {
    const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;
    sh.to_bl[j] = m;
  }

  __syncthreads();

  while(color <= ub && !mcp::empty<T, BLOCK_DIM_X>(lh, sh.to_bl, num_divs_local))
  {

    for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
      sh.to_col[j] = sh.to_bl[j];

    __syncthreads();
    
    fetch(pointer, 0);

    __syncthreads();
    
    // get one vertex
    while (mcp::get_next_candidate_to_color(lh, sh, sh.usrcLen, pointer, sh.to_col))
    {
      // remove adjacet from color
      // if (threadIdx.x == 0 && sh.i == 0) 
      // printf("cand :%u\n", lh.colNewIndex);

      for (T j = threadIdx.x + (lh.colNewIndex >> 5); j < num_divs_local; j += BLOCK_DIM_X)
      {
        const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;        
        sh.to_col[j] &= ~(sh.encode[lh.colNewIndex * num_divs_local + j]) & m;
      }

      __syncthreads();

      if (threadIdx.x == 0)
      {
        pointer = lh.colNewIndex + 1;
        const T li = lh.colNewIndex >> 5;
        const T ri = 1 << (lh.colNewIndex & 0x1F);
        sh.to_bl[li] ^= ri;
        //sh.Iset[color * num_divs_local + li] |= ri;
      }
      
      __syncthreads();
    }

    if (threadIdx.x == 0) 
      color++;

    __syncthreads();

  }

  __syncthreads();

  if (mcp::empty<T, BLOCK_DIM_X>(lh, sh.to_bl, num_divs_local))
  {
    __syncthreads();
    return ub;
  }

  __syncthreads();
  return color;
  
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ int add_to_iset_tomita(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, 
    const int& index, int& k, const int& ub,
    const T& num_divs_local)
{

  __shared__ bool inserted;

  if (threadIdx.x == 0) inserted = false;

  __syncthreads();

  // If is it possible to insert into an existing iset

  for (T k_j = 0; k_j < k; k_j++)
  {
    __shared__ unsigned not_empty_intersect;
    if (threadIdx.x == 0) not_empty_intersect = 0;
    __syncthreads();

    unsigned local_not_empty_intersect = 0;
    for (T j = threadIdx.x; j < sh.Iset_count[k_j]; j += BLOCK_DIM_X)
    {
      const T index_of_iset = sh.Iset[k_j * MAXDEG + j];
      const T index_li = index_of_iset >> 5;
      const T index_ri = 1 << (index_of_iset & 0x1F);
      local_not_empty_intersect += (sh.encode[index * num_divs_local + index_li] & index_ri) > 0 ? 1 : 0;
    }

    __syncthreads();

    const unsigned local_not_empty_intersect_mask = __any_sync(lh.partMask, local_not_empty_intersect);

    __syncthreads();

    if (lh.lx == 0 && local_not_empty_intersect_mask != 0)
    {
      atomicOr(&not_empty_intersect, local_not_empty_intersect_mask);
    }

    __syncthreads();

    if (!not_empty_intersect)
    {
      if (threadIdx.x == 0)
      {
        const T li = index >> 5;
        const T ri = 1 << (index & 0x1F);
        sh.to_bl[li] ^= ri;
        sh.Iset[k_j * MAXDEG + sh.Iset_count[k_j]++] = index;
        inserted = true;
      }

      __syncthreads();
      break;
    }

    __syncthreads();
  }

  __syncthreads();

  if (threadIdx.x == 0 && !inserted && k < ub) // Create a new Iset
  {
    const T li = index >> 5;
    const T ri = 1 << (index & 0x1F);
    sh.to_bl[li] ^= ri;
    sh.Iset_count[k] = 0;
    sh.Iset[k * MAXDEG + sh.Iset_count[k]++] = index;
    inserted = true;
    k++;
  }

  __syncthreads();
  return inserted;
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ int compute_upperbound_chromatic_number_tomita(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, const int ub,
    const T& num_divs_local
    )
{
  __shared__ int k;
  __shared__ int index;

  if (threadIdx.x == 0)
  {
    k = 0;
    index = 0;
  }

  __syncthreads();

  // Reset
  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
  {
    const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;
    sh.to_bl[j] = m;
  }

  __syncthreads();

  while(index < sh.usrcLen && add_to_iset_tomita(lh, sh, index, k, ub, sh.num_divs_local))
  {
    if (threadIdx.x == 0) index++;
    __syncthreads();
  }

  __syncthreads();

  if (mcp::empty<T, BLOCK_DIM_X>(lh, sh.to_bl, num_divs_local))
  {
    __syncthreads();
    return ub;
  }

  __syncthreads();
  return k + 1;
  
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ int try_to_renumber(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, 
    const int& index, const int k, const int& ub,
    const T& num_divs_local
    )
{
  __shared__ int total_neighbours;
  __shared__ bool inserted;

  if (threadIdx.x == 0) inserted = false;

  __syncthreads();

  for (T iset_i = 0; iset_i < (ub - 1) && !inserted; iset_i++)
  {
    // Intersect
    if (threadIdx.x == 0) total_neighbours = 0;
    __syncthreads();

    unsigned neighbours = 0;
    for (T j = threadIdx.x; j < sh.Iset_count[iset_i]; j += BLOCK_DIM_X)
    {
      const T index_of_iset = sh.Iset[iset_i * MAXDEG + j];
      const T index_li = index_of_iset >> 5;
      const T index_ri = 1 << (index_of_iset & 0x1F);
      neighbours += (sh.encode[index * num_divs_local + index_li] & index_ri) > 0 ? 1 : 0;
    }

    __syncthreads();

    reduce_part<T, CPARTSIZE>(lh.partMask, neighbours);

    __syncthreads();

    if (lh.lx == 0 && neighbours > 0)
    {
      atomicAdd(&total_neighbours, neighbours);
    }

    __syncthreads();

    if (total_neighbours == 1)
    {
      
      __shared__ T one_neighbour;
      __shared__ T one_neighbour_pos;

      // Get one neighbour
      for (T j = threadIdx.x; j < sh.Iset_count[iset_i]; j += BLOCK_DIM_X)
      {
        const T index_of_iset = sh.Iset[iset_i * MAXDEG + j];
        const T index_li = index_of_iset >> 5;
        const T index_ri = 1 << (index_of_iset & 0x1F);
        if ((sh.encode[index * num_divs_local + index_li] & index_ri) > 0) 
          {one_neighbour = index_of_iset; one_neighbour_pos = j;}
      }
      
      for (T iset_j = iset_i + 1; iset_j < ub && !inserted; iset_j++)
      {
        __shared__ unsigned not_empty_intersect_;
        if (threadIdx.x == 0) not_empty_intersect_ = 0;
        __syncthreads();

        unsigned local_not_empty_intersect_ = 0;
        for (T j = threadIdx.x; j < sh.Iset_count[iset_j]; j += BLOCK_DIM_X)
        {
          const T index_of_iset = sh.Iset[iset_j * MAXDEG + j];
          const T index_li = index_of_iset >> 5;
          const T index_ri = 1 << (index_of_iset & 0x1F);
          local_not_empty_intersect_ += (sh.encode[one_neighbour * num_divs_local + index_li] & index_ri) > 0 ? 1 : 0;
        }

        __syncthreads();

        const unsigned local_not_empty_intersect_mask_ = __any_sync(lh.partMask, local_not_empty_intersect_);

        __syncthreads();

        if (lh.lx == 0 && local_not_empty_intersect_mask_ != 0)
        {
          atomicOr(&not_empty_intersect_, local_not_empty_intersect_mask_);
        }

        __syncthreads();

        // iset found
        if (!not_empty_intersect_)
        {
          if (threadIdx.x == 0)
          {
            const T li_i = index >> 5;
            const T ri_i = 1 << (index & 0x1F);
            // const T li_j = one_neighbour >> 5;
            // const T ri_j = 1 << (one_neighbour & 0x1F);
            sh.Iset[iset_i * MAXDEG + one_neighbour_pos] = index;
            sh.Iset[iset_j * MAXDEG + sh.Iset_count[iset_j]++] = one_neighbour;
            sh.to_bl[li_i] ^= ri_i;
            inserted = true;
          }
          __syncthreads();
        }
      
        __syncthreads();
      }
    }
  }

  __syncthreads();
  return inserted;
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ int compute_upperbound_chromatic_number_tomita_renumber(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, const int ub,
    const T& num_divs_local
    )
{
  __shared__ int k;
  __shared__ int index;
  __shared__ bool inserted;

  if (threadIdx.x == 0)
  {
    k = 0;
    index = 0;
  }

  __syncthreads();

  // Reset
  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
  {
    const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;
    sh.to_bl[j] = m;
  }

  __syncthreads();

  while(index < sh.usrcLen)
  {
    inserted = add_to_iset_tomita(lh, sh, index, k, ub, sh.num_divs_local);
    
    if (!inserted)
    {
      inserted = try_to_renumber(lh, sh, index, k, ub, num_divs_local);

      if (!inserted)
      {
        __syncthreads();
        break;
      }
    }

    __syncthreads();

    if (threadIdx.x == 0)
      index++;

    __syncthreads();
  }

  __syncthreads();

  if (mcp::empty<T, BLOCK_DIM_X>(lh, sh.to_bl, num_divs_local))
  {
    __syncthreads();
    return ub;
  }

  __syncthreads();
  return k + 1;
  
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_branches_fast_recolor(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, const int ub,
    const T& num_divs_local, const T *const cur_pl
    )
{
  __shared__ int color;
  __shared__ T pointer;
  //__shared__ T to_uncol[MAX_DEGEN / 32];
  //__shared__ T to_iset[MAX_DEGEN / 32];

  if (threadIdx.x == 0)
  { 
    color = 0;
  }
  __syncthreads();

  // UNCOL = P
  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
  {
    const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;
    sh.to_bl[j] = cur_pl[j] & m;
    //to_uncol[j] = sh.to_bl[j];
  }

  __syncthreads();

  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
      sh.to_col[j] = sh.to_bl[j];

  __syncthreads();

  while(ub > 0 && color <= ub /* && !mcp::empty<T, BLOCK_DIM_X>(lh, sh.to_bl, num_divs_local)*/)
  {
    
    if (threadIdx.x == 0) 
      pointer = 0;

    __syncthreads();

    for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
    {
      sh.Iset[color * num_divs_local + j] = 0x00;
    }

    __syncthreads();

    if (threadIdx.x == 0)
    {
      sh.min_bounds(color) = sh.usrcLen;
      sh.max_bounds(color) = 0;
    }

    __syncthreads();
    
    // get one vertex
  
    while (mcp::get_next_candidate_to_color(lh, sh, sh.usrcLen, pointer, sh.to_col))
    {

      __shared__ bool recolored;
    
      if (threadIdx.x == 0) recolored = false;    
      
      __syncthreads();

      if (color >= ub && ub >= 3 /*&& popc<T, BLOCK_DIM_X, CPARTSIZE>(lh, sh.to_col, num_divs_local) == 1*/)
      {
        ////////////// Re-Color ///////////////////////////////////////////////////////////////////

        // Save in shared
        __shared__ T to_color_idx_neighbourhood[MAX_DEGEN / 32];

        for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
        {
          to_color_idx_neighbourhood[j] = sh.encode[lh.colNewIndex * num_divs_local + j];
        }

        for (T iset_i = 0; iset_i < ub - 1 && !recolored; iset_i++)
        {
          
          __shared__ T total_neighbours;
          T neighbours = 0;
          if (threadIdx.x == 0) total_neighbours = 0;

          __syncthreads();

          __shared__ T one_neighbour;
          for (T j = threadIdx.x + (sh.min_bounds(iset_i) >> 5); j < min((sh.max_bounds(iset_i) >> 5) + 1, num_divs_local); j += BLOCK_DIM_X) {
            neighbours += __popc(sh.Iset[iset_i * num_divs_local + j] & to_color_idx_neighbourhood[j]);
          }

          __syncthreads();

          reduce_part<T, CPARTSIZE>(lh.partMask, neighbours);

          __syncthreads();

          if (lh.lx == 0 && neighbours > 0);
            atomicAdd(&total_neighbours, neighbours);

          __syncthreads();

          if (total_neighbours == 0)
          {
            if (threadIdx.x == 0)
            {
              const T li = lh.colNewIndex >> 5;
              const T ri = 1 << (lh.colNewIndex & 0x1F);
              sh.min_bounds(iset_i) = min(sh.min_bounds(iset_i), lh.colNewIndex);
              sh.max_bounds(iset_i) = max(sh.max_bounds(iset_i), lh.colNewIndex);
              sh.Iset[iset_i * num_divs_local + li] |= ri;
              sh.to_bl[li] ^= ri;
              sh.to_col[li] ^= ri;
              recolored = true;
            }

            __syncthreads();
          }
          else
          if (total_neighbours == 1)
          {
            
            // Save in shared
            __shared__ T one_neighbour_neighbourhood[MAX_DEGEN / 32];

            __shared__ T one_neighbour;
            for (T j = threadIdx.x + (sh.min_bounds(iset_i) >> 5); j < min((sh.max_bounds(iset_i) >> 5) + 1, num_divs_local); j += BLOCK_DIM_X) {
              const T neigh_block = sh.Iset[iset_i * num_divs_local + j] & to_color_idx_neighbourhood[j];
              if (__popc(neigh_block) == 1) one_neighbour = (j << 5) + __ffs(neigh_block) - 1;
            }

            __syncthreads();

            for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
              one_neighbour_neighbourhood[j] = sh.encode[one_neighbour * num_divs_local + j];

            __syncthreads();

            for (T iset_j = iset_i + 1; iset_j < ub && !recolored; iset_j++)
            {

              T neighbours_ = 0;
              __shared__ T any_neighbours;
              if (threadIdx.x == 0) any_neighbours = 0;

              __syncthreads();

              for (T j = threadIdx.x + (sh.min_bounds(iset_j) >> 5); j < min((sh.max_bounds(iset_j) >> 5) + 1, num_divs_local); j += BLOCK_DIM_X)
              {
                neighbours_ |= sh.Iset[iset_j * num_divs_local + j] & one_neighbour_neighbourhood[j];
              }
                
              __syncthreads();

              const T any_neighbours_warp = __any_sync(lh.partMask, neighbours_);

              __syncthreads();

              if (lh.lx == 0 && any_neighbours_warp)
                atomicOr(&any_neighbours, any_neighbours_warp);

              __syncthreads();

              // iset found
              if (!any_neighbours)
              {
                if (threadIdx.x == 0)
                {
                  const T li_i = lh.colNewIndex >> 5;
                  const T ri_i = 1 << (lh.colNewIndex & 0x1F);
                  const T li_j = one_neighbour >> 5;
                  const T ri_j = 1 << (one_neighbour & 0x1F);
                  sh.Iset[iset_i * num_divs_local + li_j] ^= ri_j;
                  sh.Iset[iset_i * num_divs_local + li_i] |= ri_i;
                  sh.Iset[iset_j * num_divs_local + li_j] |= ri_j;
                  sh.min_bounds(iset_i) = min(sh.min_bounds(iset_i), lh.colNewIndex);
                  sh.max_bounds(iset_i) = max(sh.max_bounds(iset_i), lh.colNewIndex);
                  sh.min_bounds(iset_j) = min(sh.min_bounds(iset_j), one_neighbour);
                  sh.max_bounds(iset_j) = max(sh.max_bounds(iset_j), one_neighbour);                  
                  sh.to_bl[li_i] ^= ri_i;
                  sh.to_col[li_i] ^= ri_i;
                  recolored = true;
                }

                __syncthreads();
              }

              __syncthreads();
            }

            __syncthreads();
          }

          __syncthreads();
        }
        //////////////////////////////////////////////////////////////////////////////////////////

      } else if (threadIdx.x == 0 && !recolored && color < ub)
      {
        const T li = lh.colNewIndex >> 5;
        const T ri = 1 << (lh.colNewIndex & 0x1F);
        sh.min_bounds(color) = min(sh.min_bounds(color), lh.colNewIndex);
        sh.max_bounds(color) = max(sh.max_bounds(color), lh.colNewIndex);
        sh.Iset[color * num_divs_local + li] |= ri;
      }
      
      __syncthreads();

      if (!recolored && color < ub) 
      {

        // if (color == ub)
        // {
        //   __syncthreads();
        //   break;
        // }

        __syncthreads();

        for (T j = threadIdx.x + (lh.colNewIndex >> 5); j < num_divs_local; j += BLOCK_DIM_X)
        {
          const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;        
          sh.to_col[j] &= ~(sh.encode[lh.colNewIndex * num_divs_local + j]) & m;
        }

        __syncthreads();

        if (threadIdx.x == 0)
        {
          const T li = lh.colNewIndex >> 5;
          const T ri = 1 << (lh.colNewIndex & 0x1F);
          sh.to_bl[li] ^= ri;
          sh.to_col[li] ^= ri;
        }

        __syncthreads();
        
      }

      __syncthreads();

      if (threadIdx.x == 0) pointer = lh.colNewIndex + 1;

      __syncthreads();
    }

    for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
      sh.to_col[j] = sh.to_bl[j];

    __syncthreads();

    if (threadIdx.x == 0) color++;

    __syncthreads();

  }

  if (threadIdx.x == 0) sh.colored[current_level] = true;
  __syncthreads();
  return;
  
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_branches_fast_recolor_parallel_search(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, const int ub,
    const T& num_divs_local, const T *const cur_pl
    )
{
  __shared__ int color;
  __shared__ T pointer;
  //__shared__ T to_uncol[MAX_DEGEN / 32];
  //__shared__ T to_iset[MAX_DEGEN / 32];

  if (threadIdx.x == 0)
  { 
    color = 0;
  }
  __syncthreads();

  // UNCOL = P
  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
  {
    const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;
    sh.to_bl[j] = cur_pl[j] & m;
    //to_uncol[j] = sh.to_bl[j];
  }

  __syncthreads();

  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
      sh.to_col[j] = sh.to_bl[j];

  __syncthreads();

  while(ub > 0 && color <= ub /* && !mcp::empty<T, BLOCK_DIM_X>(lh, sh.to_bl, num_divs_local)*/)
  {
    
    if (threadIdx.x == 0) 
      pointer = 0;

    __syncthreads();

    for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
    {
      sh.Iset[color * num_divs_local + j] = 0x00;
    }

    __syncthreads();

    if (threadIdx.x == 0)
    {
      sh.min_bounds(color) = sh.usrcLen;
      sh.max_bounds(color) = 0;
    }

    __syncthreads();
    
    // get one vertex
  
    while (mcp::get_next_candidate_to_color(lh, sh, sh.usrcLen, pointer, sh.to_col))
    {

      __shared__ bool recolored;
    
      if (threadIdx.x == 0) recolored = false;    
      
      __syncthreads();

      if (color >= ub && ub >= 3 /*&& popc<T, BLOCK_DIM_X, CPARTSIZE>(lh, sh.to_col, num_divs_local) == 1*/)
      {
        ////////////// Re-Color ///////////////////////////////////////////////////////////////////

        // Save in shared
        __shared__ T to_color_idx_neighbourhood[MAX_DEGEN / 32];

        for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
        {
          to_color_idx_neighbourhood[j] = sh.encode[lh.colNewIndex * num_divs_local + j];
        }

        __shared__ bool found;
        __shared__ unsigned n, iset;

        if (threadIdx.x == 0) found = false;

        __syncthreads();

        for (T iset_i = lh.wx; iset_i < ub - 1 && !found; iset_i+= lh.numPartitions)
        {
          __shared__ T __warp__(total_neighbours);
          T neighbours = 0;
          if (laneIdx == 0) total_neighbours[warpIdx] = 0;

          __syncwarp();

          __shared__ T one_neighbour;
          for (T j = laneIdx + (sh.min_bounds(iset_i) >> 5); j < min((sh.max_bounds(iset_i) >> 5) + 1, num_divs_local); j += CPARTSIZE) {
            neighbours += __popc(sh.Iset[iset_i * num_divs_local + j] & to_color_idx_neighbourhood[j]);
          }

          __syncwarp();

          reduce_part<T, CPARTSIZE>(lh.partMask, neighbours);

          __syncwarp();

          if (lh.lx == 0 && neighbours > 0);
            atomicAdd(&total_neighbours[warpIdx], neighbours);

          __syncwarp();

          if (total_neighbours[warpIdx] == 0)
          {
            if (laneIdx == 0)
            {
              found = true;
              n = 0;
              iset = iset_i;
            }
            __syncwarp();
          }
          else
          if (false && total_neighbours[warpIdx] == 1)
          {
            if(laneIdx == 0)
            {
              found = true;
              n = 1;
              iset = iset_i;
            }
            __syncwarp();
          }

          __syncwarp();
        }

        __syncthreads();

        if (found && n == 0)
        {
          if (threadIdx.x == 0)
          {
            const T li = lh.colNewIndex >> 5;
            const T ri = 1 << (lh.colNewIndex & 0x1F);
            sh.min_bounds(iset) = min(sh.min_bounds(iset), lh.colNewIndex);
            sh.max_bounds(iset) = max(sh.max_bounds(iset), lh.colNewIndex);
            sh.Iset[iset * num_divs_local + li] |= ri;
            sh.to_bl[li] ^= ri;
            sh.to_col[li] ^= ri;
            recolored = true;
          }

          __syncthreads();

        }
        else if (false && found && n == 1)
        {
          // Save in shared
          __shared__ T one_neighbour_neighbourhood[MAX_DEGEN / 32];
          __shared__ bool found2;
          __shared__ T one_neighbour;
          __shared__ T iset2;

          if (threadIdx.x == 0) found2 = false;

          __syncthreads();

          for (T j = threadIdx.x + (sh.min_bounds(iset) >> 5); j < min((sh.max_bounds(iset) >> 5) + 1, num_divs_local); j += BLOCK_DIM_X) {
            const T neigh_block = sh.Iset[iset * num_divs_local + j] & to_color_idx_neighbourhood[j];
            if (__popc(neigh_block) == 1) one_neighbour = (j << 5) + __ffs(neigh_block) - 1;
          }

          __syncthreads();

          for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
            one_neighbour_neighbourhood[j] = sh.encode[one_neighbour * num_divs_local + j];

          __syncthreads();

          for (T iset_j = iset + 1 + lh.wx; iset_j < ub && !found2; iset_j += lh.numPartitions)
          {

            T neighbours_ = 0;
            __shared__ T __warp__(any_neighbours);
            if (laneIdx == 0) any_neighbours[warpIdx] = 0;

            __syncwarp();

            for (T j = laneIdx + (sh.min_bounds(iset_j) >> 5); j < min((sh.max_bounds(iset_j) >> 5) + 1, num_divs_local); j += CPARTSIZE)
            {
              neighbours_ |= sh.Iset[iset_j * num_divs_local + j] & one_neighbour_neighbourhood[j];
            }
              
            __syncwarp();

            const T any_neighbours_warp = __any_sync(lh.partMask, neighbours_);

            __syncwarp();

            if (lh.lx == 0 && any_neighbours_warp)
              atomicOr(&any_neighbours[warpIdx], any_neighbours_warp);

            __syncwarp();

            // iset found
            if (!any_neighbours[warpIdx])
            {
              if (laneIdx == 0)
              {
                found2 = true;
                iset2 = iset_j;
              }

              __syncwarp();
            }

            __syncwarp();
          }

          __syncthreads();

          if (found2)
          {
            if (threadIdx.x == 0)
            {
              const T li_i = lh.colNewIndex >> 5;
              const T ri_i = 1 << (lh.colNewIndex & 0x1F);
              const T li_j = one_neighbour >> 5;
              const T ri_j = 1 << (one_neighbour & 0x1F);
              sh.Iset[iset * num_divs_local + li_j] ^= ri_j;
              sh.Iset[iset * num_divs_local + li_i] |= ri_i;
              sh.Iset[iset2 * num_divs_local + li_j] |= ri_j;
              sh.min_bounds(iset) = min(sh.min_bounds(iset), lh.colNewIndex);
              sh.max_bounds(iset) = max(sh.max_bounds(iset), lh.colNewIndex);
              sh.min_bounds(iset2) = min(sh.min_bounds(iset2), one_neighbour);
              sh.max_bounds(iset2) = max(sh.max_bounds(iset2), one_neighbour);                  
              sh.to_bl[li_i] ^= ri_i;
              sh.to_col[li_i] ^= ri_i;
              recolored = true;
            }

            __syncthreads();
          }

          __syncthreads();
        }

        __syncthreads();

        //////////////////////////////////////////////////////////////////////////////////////////

      } else if (threadIdx.x == 0 && !recolored && color < ub)
      {
        const T li = lh.colNewIndex >> 5;
        const T ri = 1 << (lh.colNewIndex & 0x1F);
        sh.min_bounds(color) = min(sh.min_bounds(color), lh.colNewIndex);
        sh.max_bounds(color) = max(sh.max_bounds(color), lh.colNewIndex);
        sh.Iset[color * num_divs_local + li] |= ri;
      }
      
      __syncthreads();

      if (!recolored && color < ub) 
      {

        // if (color == ub)
        // {
        //   __syncthreads();
        //   break;
        // }

        __syncthreads();

        for (T j = threadIdx.x + (lh.colNewIndex >> 5); j < num_divs_local; j += BLOCK_DIM_X)
        {
          const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;        
          sh.to_col[j] &= ~(sh.encode[lh.colNewIndex * num_divs_local + j]) & m;
        }

        __syncthreads();

        if (threadIdx.x == 0)
        {
          const T li = lh.colNewIndex >> 5;
          const T ri = 1 << (lh.colNewIndex & 0x1F);
          sh.to_bl[li] ^= ri;
          sh.to_col[li] ^= ri;
        }

        __syncthreads();
        
      }

      __syncthreads();

      if (threadIdx.x == 0) pointer = lh.colNewIndex + 1;

      __syncthreads();
    }

    for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
      sh.to_col[j] = sh.to_bl[j];

    __syncthreads();

    if (threadIdx.x == 0) color++;

    __syncthreads();

  }

  if (threadIdx.x == 0) sh.colored[current_level] = true;
  __syncthreads();
  return;
  
}

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_branches_fast(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, const int r,
    const T& num_divs_local, const int level, const T const* cur_pl)
{
  __shared__ int color;
  __shared__ int pointer;

  fetch(color, 1);

  __syncthreads();

  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
    sh.to_bl[j] = cur_pl[j];

  __syncthreads();

  while(color <= r && !mcp::empty<T, BLOCK_DIM_X>(lh, sh.to_bl,  num_divs_local))
  {

    for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
      sh.to_col[j] = sh.to_bl[j];

    __syncthreads();
    
    fetch(pointer, 0);

    __syncthreads();
    
    // get one vertex
    while (mcp::get_next_candidate_to_color(lh, sh, sh.usrcLen, pointer, sh.to_col))
    {

      for (T j = threadIdx.x + (lh.colNewIndex >> 5); j < num_divs_local; j += BLOCK_DIM_X)
      {
        const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;        
        sh.to_col[j] &= ~(sh.encode[lh.colNewIndex * num_divs_local + j]) & m;
      }

      __syncthreads();

      if (threadIdx.x == 0)
      {
        pointer = lh.colNewIndex + 1;
        const T li = lh.colNewIndex >> 5;
        const T ri = 1 << (lh.colNewIndex & 0x1F);
        sh.to_bl[li] ^= ri;
      }
      
      __syncthreads();
    }

    if (threadIdx.x == 0) color++;
    __syncthreads();

  }

  fetch(sh.colored[level], true);
  
  __syncthreads();
  return;
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_branches_fast_second_level(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, const int r,
    const T& num_divs_local)
{
  __shared__ int color;
  __shared__ int pointer;

  if (threadIdx.x == 0)
    color = 1;

  __syncthreads();

  while(color <= r && !mcp::empty<T, BLOCK_DIM_X>(lh, sh.to_bl,  num_divs_local))
  {

    for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
      sh.to_col[j] = sh.to_bl[j];

    __syncthreads();
    
    if (threadIdx.x == 0) 
      pointer = 0;

    __syncthreads();
    
    // get one vertex
    while (mcp::get_next_candidate_to_color(lh, sh, sh.usrcLen, pointer, sh.to_col))
    {

      for (T j = threadIdx.x + (lh.colNewIndex >> 5); j < num_divs_local; j += BLOCK_DIM_X)
      {
        const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;        
        sh.to_col[j] &= ~(sh.encode[lh.colNewIndex * num_divs_local + j]) & m;
      }

      __syncthreads();

      if (threadIdx.x == 0)
      {
        pointer = lh.colNewIndex + 1;
        const T li = lh.colNewIndex >> 5;
        const T ri = 1 << (lh.colNewIndex & 0x1F);
        sh.to_bl[li] ^= ri;
      }
      
      __syncthreads();
    }

    if (threadIdx.x == 0) 
      color++;

    __syncthreads();

  }

  __syncthreads();
  return;
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_warp_branches_fast_(
    LOCAL_HANDLE<T> &lh, 
    WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &wsh, const int r,
    const T& num_divs_local, const int level, const T const* cur_pl, T * cur_bl)
{
  __shared__ int __warp__(color);
  __shared__ int __warp__(pointer);

  if (laneIdx == 0)
    color[warpIdx] = 1;

  __syncwarp();

  for (T j = laneIdx; j < num_divs_local; j += CPARTSIZE)
    cur_bl[j] = cur_pl[j];

  __syncwarp();

  while(color[warpIdx] <= r && !mcp::empty_w<T, BLOCK_DIM_X, CPARTSIZE>(lh, cur_bl,  num_divs_local))
  {

    for (T j = lh.lx; j < num_divs_local; j += CPARTSIZE)
      wsh.to_col[j] = cur_bl[j];

    __syncwarp();
    
    if (laneIdx == 0) 
      pointer[warpIdx] = 0;

    __syncwarp();
    
    // get one vertex
    while (mcp::get_next_warp_candidate_to_color_<T, BLOCK_DIM_X, CPARTSIZE>(lh, wsh.usrcLen, pointer[warpIdx], wsh.to_col))
    {
      // remove adjacet from color
      for (T j = laneIdx + (lh.colNewIndex >> 5); j < num_divs_local; j += CPARTSIZE)
      {
        const T m = (j == wsh.lastMask_i) ? wsh.lastMask_ii : 0xFFFFFFFF;        
        wsh.to_col[j] &= ~(wsh.encode[lh.colNewIndex * num_divs_local + j]) & m;
      }

      __syncwarp();

      if (laneIdx == 0)
      {
        pointer[warpIdx] = lh.colNewIndex + 1;
        const T li = lh.colNewIndex >> 5;
        const T ri = 1 << (lh.colNewIndex & 0x1F);
        cur_bl[li] ^= ri;
      }
      
      __syncwarp();
    }

    if (laneIdx == 0) 
      color[warpIdx]++;

    __syncwarp();

  }

  if (laneIdx == 0)
  {
    wsh.colored[level] = true;
  }

  __syncwarp();
  return;
}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_branches_number(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, const int r,
    const T& num_divs_local, const int level, const T const* cur_pl
    )
{
  
  __shared__ int k;
  __shared__ bool inserted;
  __shared__ T pointer;

  if (threadIdx.x == 0)
  {
    k = 0;
    pointer = 0;
  }

  __syncthreads();

  // Reset
  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
  {
    const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;
    sh.to_bl[j] = cur_pl[j];
  }

  __syncthreads();

  while(r > 0 && mcp::get_next_candidate_to_color(lh, sh, sh.usrcLen, pointer, sh.to_bl))
  {
    add_to_iset_tomita(lh, sh, lh.colNewIndex, k, r, sh.num_divs_local);
    if (threadIdx.x == 0) pointer = lh.colNewIndex + 1;
    __syncthreads();
  }

  if (threadIdx.x == 0)
    sh.colored[level] = true;

  __syncthreads();
  return;

}


template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_branches_renumber(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, const int r,
    const T& num_divs_local, const int level, const T const* cur_pl
    )
{
  
  __shared__ int k;
  __shared__ bool inserted;
  __shared__ T pointer;

  if (threadIdx.x == 0)
  {
    k = 0;
    pointer = 0;
    sh.Iset_count[0] = 0;
  }

  __syncthreads();

  // Reset
  for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
  {
    const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;
    sh.to_bl[j] = cur_pl[j];
  }

  __syncthreads();

  while(r > 0 && mcp::get_next_candidate_to_color(lh, sh, sh.usrcLen, pointer, sh.to_bl))
  {
    
    inserted = add_to_iset_tomita(lh, sh, lh.colNewIndex, k, r, sh.num_divs_local);

    if (!inserted) try_to_renumber(lh, sh, lh.colNewIndex, k, r, sh.num_divs_local);

    if (threadIdx.x == 0) pointer = lh.colNewIndex + 1;

    __syncthreads();
  }

  if (threadIdx.x == 0)
    sh.colored[level] = true;

  __syncthreads();
  return;

}



template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__device__ __forceinline__ void compute_branches_fast_from_reduce(
    LOCAL_HANDLE<T> &lh, 
    SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> &sh, const int r,
    const T& num_divs_local, const int level, bool &b_is_not_0,
    const T const* cur_pl
    )
{
  __shared__ int color;
  __shared__ T col_pointer;

  for (T j = 0; j < num_divs_local; j += BLOCK_DIM_X)
  {
    sh.to_cl[j] = sh.to_bl[j];
  }

  if (threadIdx.x == 0)
    color = 1;

  __syncthreads();

  while(color <= r && !mcp::empty<T, BLOCK_DIM_X>(lh, sh.to_bl, num_divs_local))
  {

    for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
      sh.to_col[j] = sh.to_bl[j];

    __syncthreads();
    
    if (threadIdx.x == 0) 
      col_pointer = 0;

    __syncthreads();
    
    // get one vertex
    while (mcp::get_next_candidate_to_color(lh, sh, sh.usrcLen, col_pointer, sh.to_col))
    {
      // remove adjacet from color
      // if (threadIdx.x == 0 && sh.i == 0) 
      // printf("cand :%u\n", lh.colNewIndex);

      for (T j = threadIdx.x; j < num_divs_local; j += BLOCK_DIM_X)
      {
        const T m = (j == sh.lastMask_i) ? sh.lastMask_ii : 0xFFFFFFFF;        
        sh.to_col[j] &= ~(sh.encode[lh.colNewIndex * num_divs_local + j]) & m;
      }

      __syncthreads();

      if (threadIdx.x == 0)
      {
        col_pointer = lh.colNewIndex + 1;
        const T li = lh.colNewIndex >> 5;
        const T ri = 1 << (lh.colNewIndex & 0x1F);
        sh.to_bl[li] ^= ri; 
      }
      
      __syncthreads();
    }

    if (threadIdx.x == 0) 
      color++;

    __syncthreads();

  }

  if (threadIdx.x == 0)
    sh.colored[level] = true;

  __syncthreads();

  b_is_not_0 = !empty<T, BLOCK_DIM_X>(lh, sh.to_bl, num_divs_local);

  __syncthreads();

}

};