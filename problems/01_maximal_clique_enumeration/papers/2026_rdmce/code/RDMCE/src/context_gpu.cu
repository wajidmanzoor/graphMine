#include "context_gpu.cuh"

__host__ void BufferManager::Allocate(size_t num_elements, size_t element_size)
{
  num_elements_ = num_elements;
  element_size_ = element_size;
  if (num_elements != 0 && element_size != 0)
    CUDA_CHECK(cudaMalloc(&buffer_, num_elements * element_size));
  else
    buffer_ = nullptr;
}

__host__ void BufferManager::AllocateManaged(size_t num_elements, size_t element_size)
{
  num_elements_ = num_elements;
  element_size_ = element_size;
  if (num_elements != 0 && element_size != 0)
    CUDA_CHECK(cudaMallocManaged(&buffer_, num_elements * element_size));
  else
    buffer_ = nullptr;
}

__host__ void BufferManager::Free()
{
  if (buffer_ != nullptr)
  {
    CUDA_CHECK(cudaFree(buffer_));
    buffer_ = nullptr;
  }
}

__host__ acc_t ContextManager::GetMcNum()
{
  acc_t res;
  CUDA_CHECK(cudaMemcpy(&res, mc_num_, sizeof(acc_t), cudaMemcpyDeviceToHost));
  return res;
}