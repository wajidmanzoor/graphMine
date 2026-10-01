#pragma once
#include <cstdint>
#include <iostream>
#include <vector>
#include <memory>
#include <string>
#include <sstream>
#include <fstream>
#include <cassert>
#include <unordered_map>
#include <algorithm>
#include <queue>
#include "timer.h"

using vid_t = uint32_t;
using attr_t = uint32_t;
using eid_t = uint64_t;
using acc_t = uint64_t;
using byte_t = uint8_t;
using vlist_t = std::vector<vid_t>;
#define INF 0x7fffffff
#define FULL_MASK 0xffffffff

/////////////////////////////////////////////////////////////////////
// 1. Global definitions
/////////////////////////////////////////////////////////////////////

enum VertexState : uint8_t
{
  STATE_R,
  STATE_P,
  STATE_X,
  STATE_P2R,
  STATE_P2X,
  STATE_P2X2E,
  STATE_P2E,
  STATE_X2E
};

enum VertexEvent : uint8_t
{
  EVENT_SET_R,
  EVENT_SET_E,
  EVENT_RESTORE_AUTO,
};

#ifdef __CUDACC__ // for cuda
#include <cuda_runtime.h>
#define INLINE __forceinline__
#define HOST_DEVICE __host__ __device__
#define HOST __host__

#else
#define INLINE inline
#define HOST_DEVICE
#define HOST
#endif

/////////////////////////////////////////////////////////////////////
// 2. Host utility functions
/////////////////////////////////////////////////////////////////////

HOST std::string ExtractName(const std::string &path);
HOST size_t SetIntersectionCount(const vlist_t &a, const vlist_t &b);
HOST size_t CountBit(uint64_t x);

/////////////////////////////////////////////////////////////////////
// 3. Device utility functions
/////////////////////////////////////////////////////////////////////

INLINE HOST_DEVICE static int round_up(int a, int r)
{
  return ((a + r - 1) / r) * r;
}

#ifdef __CUDACC__

/**
 * @brief Macro to check CUDA errors and call the cudaHandleError function.
 *
 * This macro simplifies the process of checking CUDA function return values.
 * It calls the cudaHandleError function with the result of the CUDA operation,
 * the current file name, and the line number.
 *
 * @param ans The result of a CUDA function call.
 */
#define CUDA_CHECK(ans) \
  cudaHandleError((ans), __FILE__, __LINE__)

/**
 * @brief Function to assert CUDA errors and handle them appropriately.
 *
 * This function checks if the given CUDA error code indicates an error.
 * If an error is detected, it prints an error message to stderr and optionally
 * aborts the program.
 *
 * @param code The CUDA error code to check.
 * @param file The name of the file where the error occurred.
 * @param line The line number in the file where the error occurred.
 * @param abort If true, the program will be aborted on error. Default is true.
 */
inline void cudaHandleError(cudaError_t code, const char *file, int line, bool abort = true)
{
  if (code != cudaSuccess)
  {
    // Print error message with error string, file name, and line number
    fprintf(stderr, "GPUassert: %s %s %d\n", cudaGetErrorString(code), file, line);
    if (abort)
    {
      // Abort the program if abort is true
      exit(code);
    }
  }
}

__device__ __forceinline__ unsigned get_lane_id()
{
  unsigned ret;
  asm volatile("mov.u32 %0, %laneid;" : "=r"(ret));
  return ret;
}

__device__ __forceinline__ unsigned count_bit(unsigned bit_mask)
{
  unsigned ret_val;
  asm volatile("popc.b32 %0, %1;" : "=r"(ret_val) : "r"(bit_mask));
  return ret_val;
}

__device__ __forceinline__ unsigned extract_bits(uint bit_mask, uint start_pos,
                                                 uint len)
{
  uint ret_val;
  asm volatile(
      "bfe.u32 %0, %1, %2, %3;"
      : "=r"(ret_val) : "r"(bit_mask), "r"(start_pos), "r"(len));
  return ret_val;
}

__device__ __forceinline__ uint64_t set_high_bits(uint64_t dst, uint32_t src)
{
  uint64_t ret_val;
  asm volatile(
      "bfi.b64 %0, %1, %2, %3, 32;"
      : "=l"(ret_val)
      : "r"(src), "l"(dst), "r"(32));
  return ret_val;
}

__device__ __forceinline__ uint64_t set_low_bits(uint64_t dst, uint32_t src)
{
  uint64_t ret_val;
  asm volatile(
      "bfi.b64 %0, %1, %2, %3, 32;"
      : "=l"(ret_val)
      : "r"(src), "l"(dst), "r"(0));
  return ret_val;
}

__device__ __forceinline__ unsigned set_bits(uint bit_mask, uint val,
                                             uint start_pos, uint len)
{
  uint ret_val;
  asm volatile(
      "bfi.b32 %0, %1, %2, %3, %4;"
      : "=r"(ret_val) : "r"(val), "r"(bit_mask), "r"(start_pos), "r"(len));
  return ret_val;
}

__device__ __forceinline__ void cuda_sleep(){
  clock_t t0 = clock64();
  clock_t t1 = t0;
  while ((t1 - t0 < 10000000))
      t1 = clock64();
}



template <typename T = int>
__device__ __forceinline__ T warp_max(T value){
  for (int offset = warpSize/2; offset > 0; offset /= 2){
    T other = __shfl_down_sync(FULL_MASK, value, offset);
    value = max(value, other);
  }
  return value;
}

template <typename T = int>
__device__ __forceinline__ T warp_min(T value){
  for (int offset = warpSize/2; offset > 0; offset /= 2){
    T other = __shfl_down_sync(FULL_MASK, value, offset);
    value = min(value, other);
  }
  return value;
}


template <typename T = int>
__device__ __forceinline__ T linear_search(T key, T *list, unsigned left, unsigned right)
{
  for (unsigned i = left; i <= right; i++)
  {
    if (list[i] == key)
      return i;
  }
  return -1;
}

template <typename T = int>
__device__ __forceinline__ T binary_search(T key, const T *list, unsigned int left, unsigned int right)
{
  while (left <= right)
  {
    unsigned int mid = (left + right) / 2;
    T value = list[mid];
    if (value == key)
      return mid;
    if (value > key && mid > 0)
      right = mid - 1;
    else
      left = mid + 1;
  }
  return INF;
}

template <typename T = int>
__device__ __forceinline__ T binary_search(T key, const T *list, size_t size)
{
  if(size == 0)
    return INF;
  return binary_search(key, list, 0, size - 1);
}

template <typename T = int>
__host__ __device__ __forceinline__ T binary_search_last_not_greater(T key, const T *list, unsigned int left, unsigned int right)
{
  T pos = 0; 
  while (left <= right)
  {
    unsigned int mid = (left + right) / 2;
    T value = list[mid];
    if (value == key)
      return mid;
    else if (value < key)
    {
      pos = mid;
      left = mid + 1;
    }
    else
    {
      right = mid - 1;
    }
  }
  return pos;
}

// __host__ __device__ __forceinline__ T binary_search_last_not_greater(T key, const T *list, unsigned int left, unsigned int right)
// {
//   T pos = 0;
//   while (left <= right)
//   {
//     unsigned int mid = (left + right) / 2;
//     T value = list[mid];
//     if (value == key)
//       return mid;
//     else if(value < key && mid > 0)
//       right = mid - 1;
//     else{
//       pos = mid;
//       left = mid + 1;
//     }
//   }
//   return pos;
// }

template <typename T = int>
__host__ __device__ __forceinline__ T binary_search_first_greater(T key, const T *list, unsigned int left, unsigned int right)
{
  T pos = right + 1;
  while (left <= right)
  {
    unsigned int mid = (left + right) / 2;
    T value = list[mid];
    if (value == key)
      return mid + 1;
    else if (value > key)
    {
      if(mid == 0)
        return 0;
      pos = mid;
      right = mid - 1;
    }
    else
    {
      left = mid + 1;
    }
  }
  return pos;
}

template <typename T = int>
__host__ __device__ __forceinline__ T binary_search_first_greater(T key, const T *list, size_t size)
{

  return (size == 0)? (T) 0 : binary_search_first_greater(key, list, 0, size - 1);
}

template <typename T = int>
__device__ __forceinline__ T binary_search_last_not_greater(T key, const T *list, size_t size)
{
  return binary_search_last_not_greater(key, list, 0, size - 1);
}

#endif

/////////////////////////////////////////////////////////////////////
// 4. MCE utility functions
/////////////////////////////////////////////////////////////////////

class VertexMce
{
protected:
  VertexState state_;
  size_t level_1_, level_2_;

public:
  vid_t v_;
  VertexMce(vid_t v = 0, VertexState state = STATE_R) : v_(v), state_(state), level_1_(0), level_2_(0) {}
  INLINE HOST_DEVICE void Init(vid_t v, VertexState state)
  {
    v_ = v;
    state_ = state;
  }
  INLINE HOST_DEVICE void Update(VertexEvent event, size_t level)
  {
    if (event == EVENT_SET_R)
    {
      assert(state_ == STATE_P);
      state_ = STATE_P2R;
      level_1_ = level;
      // printf("set %d to R\n", v_);
    }
    else if (event == EVENT_SET_E)
    {
      if (state_ == STATE_P)
      {
        state_ = STATE_P2E;
        level_1_ = level;
        // printf("set %d to E\n", v_);
      }
      else if (state_ == STATE_X)
      {
        state_ = STATE_X2E;
        level_1_ = level;
        // printf("set %d to E\n", v_);
      }
      else if (state_ == STATE_P2X)
      {
        state_ = STATE_P2X2E;
        level_2_ = level;
        // printf("set %d to E\n", v_);
      }
    }
    else if (event == EVENT_RESTORE_AUTO)
    {
      if (state_ == STATE_P2X2E && level_2_ == level)
        state_ = STATE_P2X;
      else if (state_ == STATE_X2E && level_1_ == level)
        state_ = STATE_X;
      else if (state_ == STATE_P2E && level_1_ == level)
        state_ = STATE_P;
      else if (state_ == STATE_P2X && level_1_ == level)
        state_ = STATE_P;
      else if (state_ == STATE_P2R && level_1_ == level)
      {
        state_ = STATE_P2X; // set traversed R to X
        level_1_ = level - 1;
      }
      // printf("restore %d\n", v_);
    }
  }
  INLINE HOST_DEVICE bool IsP() const { return state_ == STATE_P; }
  INLINE HOST_DEVICE bool IsR() const { return state_ == STATE_R || state_ == STATE_P2R; }
  INLINE HOST_DEVICE bool IsX() const { return state_ == STATE_X || state_ == STATE_P2X; }
  INLINE HOST_DEVICE bool operator<(const VertexMce &other) const { return v_ < other.v_; }
};

template <typename T = VertexMce>
class NodeMce
{
private:
  T *vertices_;
  size_t capacity_;

public:
  INLINE HOST_DEVICE T *GetVertex(size_t pos) { return vertices_ + pos; }
  INLINE HOST_DEVICE void SetVertex(size_t pos, vid_t v_id, VertexState state)
  {
    assert(pos < capacity_);
    vertices_[pos].Init(v_id, state);
  }

  INLINE HOST_DEVICE void Init(void *ptr, size_t size)
  {
    vertices_ = (T *)ptr;
    capacity_ = size / sizeof(T);
  }
};
