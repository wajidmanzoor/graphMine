#pragma once
#include "common.cuh"

class BufferManager
{
private:
  void *buffer_;
  size_t num_elements_;
  size_t element_size_;

public:
  BufferManager() : buffer_(nullptr), num_elements_(0), element_size_(0) {}
  ~BufferManager() {}
  __host__ void Allocate(size_t num_elements, size_t element_size_);
  __host__ void AllocateManaged(size_t num_elements, size_t element_size_);
  __host__ void Free();

  __forceinline__ __device__ void *GetElement(size_t idx)
  {
    assert(idx < num_elements_);
    return (char *)buffer_ + idx * element_size_;
  }

  __forceinline__ __device__ void *GetElementRearPtr(size_t idx, int size){
    assert(idx < num_elements_);
    assert(size <= element_size_);
    return (char *)buffer_ + (idx + 1) * element_size_ - size;
  } 

  __forceinline__ __device__ size_t GetElementSize() { return element_size_; }
  __forceinline__ __device__ size_t GetElementNums() { return num_elements_; }
};

class ContextManager
{
public:
  acc_t* mc_num_;
  __host__ acc_t GetMcNum();

  // BufferManager RPX_bm_;
  // BufferManager Pivot_bm_;
  // BufferManager Queue_bm_;
  // size_t* counter_;  
  
  // __host__ void Allocate(size_t num_rpx = 0, size_t size_rpx = 0,
  //                        size_t num_pivot = 0, size_t size_pivot = 0,
  //                        size_t num_queue = 0, size_t size_queue = 0);
  // __host__ void Free();
};

