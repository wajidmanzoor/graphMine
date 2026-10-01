#pragma once
#include <cstdint>
#include <cstdio>
#include <cuda_runtime_api.h>
#include <stdexcept>
#include <string>

#define CUDA_RUNTIME(ans)                 \
  {                                       \
    gpuAssert((ans), __FILE__, __LINE__); \
  }

inline void gpuAssert(cudaError_t code, const char *file, int line, bool abort = true)
{
  if (code != cudaSuccess)
  {
#ifdef GRAPHMINE_LIBRARY
    throw std::runtime_error(std::string("Maximum-Clique-on-GPU CUDA failure at ") +
                             file + ":" + std::to_string(line) + ": " +
                             cudaGetErrorString(code));
#else
    fprintf(stderr, "GPUassert: %s %s %d\n", cudaGetErrorString(code), file, line);
    if (abort)
      exit(1);
#endif
  }
}

#define execKernel(kernel, gridSize, blockSize, deviceId, verbose, ...) \
  {                                                                     \
    dim3 grid(gridSize);                                                \
    dim3 block(blockSize);                                              \
    CUDA_RUNTIME(cudaSetDevice(deviceId));                              \
    kernel<<<grid, block>>>(__VA_ARGS__);                               \
    CUDA_RUNTIME(cudaDeviceSynchronize());                              \
  }

#define execKernelAsync(kernel, gridSize, blockSize, deviceId, streamId, verbose, ...) \
  {                                                                                    \
    dim3 grid(gridSize);                                                               \
    dim3 block(blockSize);                                                             \
    CUDA_RUNTIME(cudaSetDevice(deviceId));                                             \
    kernel<<<grid, block, 0, streamId>>>(__VA_ARGS__);                                 \
  }

struct CUDAContext
{
  uint32_t max_threads_per_SM;
  uint32_t num_SMs;
  uint32_t shared_mem_size_per_block;
  uint32_t shared_mem_size_per_sm;
  uint32_t max_grid_size;
  uint32_t max_blocks_per_sm;

  CUDAContext()
  {
    /*get the maximal number of threads in an SM*/
    cudaDeviceProp prop;
    int current_device = 0;
    cudaGetDevice(&current_device);
    cudaGetDeviceProperties(&prop, current_device);
    max_grid_size = prop.maxGridSize[0];
    max_threads_per_SM = prop.maxThreadsPerMultiProcessor;
    shared_mem_size_per_block = prop.sharedMemPerBlock;
    max_blocks_per_sm = prop.maxBlocksPerMultiProcessor;
    shared_mem_size_per_sm = prop.sharedMemPerMultiprocessor;
    num_SMs = prop.multiProcessorCount;
  }

  uint32_t GetConCBlocks(uint32_t block_size)
  {
    auto conc_blocks_per_SM = min(max_blocks_per_sm, min(max_threads_per_SM / block_size, max_grid_size)); /*assume regs are not limited*/
    return conc_blocks_per_SM;
  }
};

__device__ __inline__ uint32_t __mysmid()
{
  unsigned int r;
  asm("mov.u32 %0, %%smid;"
      : "=r"(r));
  return r;
}

static __inline__ __device__ bool atomicCASBool(bool *address, bool compare, bool val)
{
  unsigned long long addr = (unsigned long long)address;
  unsigned pos = addr & 3;             // byte position within the int
  int *int_addr = (int *)(addr - pos); // int-aligned address
  int old = *int_addr, assumed, ival;

  do
  {
    assumed = old;
    if (val)
      ival = old | (1 << (8 * pos));
    else
      ival = old & (~((0xFFU) << (8 * pos)));
    old = atomicCAS(int_addr, assumed, ival);
  } while (assumed != old);

  return (bool)(old & ((0xFFU) << (8 * pos)));
}

static __inline__ __device__ float atomicMax(float* address, float val)
{
    int* address_as_i = (int*) address;
    int old = *address_as_i, assumed;
    do {
        assumed = old;
        old = ::atomicCAS(address_as_i, assumed,
            __float_as_int(::fmaxf(val, __int_as_float(assumed))));
    } while (assumed != old);
    return __int_as_float(old);
}

template <typename T>
T getVal(T *arr, T index, AllocationTypeEnum at)
{
  if (at == AllocationTypeEnum::unified)
    return (arr[index]);

  T val = 0;
  CUDA_RUNTIME(cudaMemcpy(&val, &(arr[index]), sizeof(T), cudaMemcpyKind::cudaMemcpyDeviceToHost));
  return val;
}
