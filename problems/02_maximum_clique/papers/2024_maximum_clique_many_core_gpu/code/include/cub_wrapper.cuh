#pragma once

#include <cub/cub.cuh>
#include <cuda_runtime.h>
#include "defs.h"
#include "utils.cuh"

template <typename InputType, typename OutputType, typename CountType, typename FlagIterator>
uint32_t CUBSelect(
    InputType input, OutputType output,
    FlagIterator flags,
    const CountType countInput,
    int devId)
{
  CUDA_RUNTIME(cudaSetDevice(devId));
  uint32_t *countOutput = nullptr;
  CUDA_RUNTIME(cudaMallocManaged(&countOutput, sizeof(uint32_t)));

  void *d_temp_storage = nullptr;
  size_t temp_storage_bytes = 0;

  cub::DeviceSelect::Flagged(d_temp_storage, temp_storage_bytes, input, flags, output, countOutput, countInput);
  CUDA_RUNTIME(cudaDeviceSynchronize());
  CUDA_RUNTIME(cudaMallocManaged(&d_temp_storage, temp_storage_bytes));
  cub::DeviceSelect::Flagged(d_temp_storage, temp_storage_bytes, input, flags, output, countOutput, countInput);
  CUDA_RUNTIME(cudaDeviceSynchronize());
  uint32_t res = *countOutput;
  CUDA_RUNTIME(cudaFree(d_temp_storage));
  CUDA_RUNTIME(cudaFree(countOutput));
  return res;
}

template <typename InputType, typename OutputType>
OutputType CUBScanExclusive(
    InputType *input, OutputType *output,
    const int count, int devId,
    cudaStream_t stream = 0, AllocationTypeEnum at = unified)
{
  CUDA_RUNTIME(cudaSetDevice(devId));

  void *d_temp_storage = nullptr;
  size_t temp_storage_bytes = 0;

  /*record the last input item in case it is an in-place scan*/
  auto last_input = getVal<InputType>(input, count - 1, at); // input[count - 1];
  cub::DeviceScan::ExclusiveSum(d_temp_storage, temp_storage_bytes, input, output, count);
  CUDA_RUNTIME(cudaMalloc(&d_temp_storage, temp_storage_bytes));
  cub::DeviceScan::ExclusiveSum(d_temp_storage, temp_storage_bytes, input, output, count);
  CUDA_RUNTIME(cudaFree(d_temp_storage));
  
  return getVal<OutputType>(output, count - 1, at) + (OutputType)last_input;
}


template <typename InputType, typename OutputType>
OutputType CUBSum(
    InputType *input,
    const int count, int devId,
    cudaStream_t stream = 0, AllocationTypeEnum at = gpu)
{
  CUDA_RUNTIME(cudaSetDevice(devId));

  void *d_temp_storage = nullptr;
  size_t temp_storage_bytes = 0;
  OutputType *d_sum;
  CUDA_RUNTIME(cudaMalloc((void**)&d_sum, sizeof(OutputType)));

  /*record the last input item in case it is an in-place scan*/
  cub::DeviceReduce::Sum(d_temp_storage, temp_storage_bytes, input, d_sum, count);
  CUDA_RUNTIME(cudaMalloc(&d_temp_storage, temp_storage_bytes));
  cub::DeviceReduce::Sum(d_temp_storage, temp_storage_bytes, input, d_sum, count);
  CUDA_RUNTIME(cudaFree(d_temp_storage));
  OutputType sum = getVal<OutputType>(d_sum, 0, at);
  CUDA_RUNTIME(cudaFree(d_sum));
  return sum;
}

template <typename InputType, typename OutputType>
OutputType CUBMax(
    InputType *input,
    const int count, int devId,
    cudaStream_t stream = 0, AllocationTypeEnum at = gpu)
{
  CUDA_RUNTIME(cudaSetDevice(devId));

  void *d_temp_storage = nullptr;
  size_t temp_storage_bytes = 0;
  OutputType *d_sum;
  CUDA_RUNTIME(cudaMalloc((void**)&d_sum, sizeof(OutputType)));

  /*record the last input item in case it is an in-place scan*/
  cub::DeviceReduce::Max(d_temp_storage, temp_storage_bytes, input, d_sum, count);
  CUDA_RUNTIME(cudaMalloc(&d_temp_storage, temp_storage_bytes));
  cub::DeviceReduce::Max(d_temp_storage, temp_storage_bytes, input, d_sum, count);
  CUDA_RUNTIME(cudaFree(d_temp_storage));
  OutputType sum = getVal<OutputType>(d_sum, 0, at);
  CUDA_RUNTIME(cudaFree(d_sum));
  return sum;
}

template <typename InputType, typename OutputType>
OutputType CUBMin(
    InputType *input,
    const int count, int devId,
    cudaStream_t stream = 0, AllocationTypeEnum at = unified)
{
  CUDA_RUNTIME(cudaSetDevice(devId));

  void *d_temp_storage = nullptr;
  size_t temp_storage_bytes = 0;
  OutputType *d_sum;
  CUDA_RUNTIME(cudaMalloc((void**)&d_sum, sizeof(OutputType)));

  /*record the last input item in case it is an in-place scan*/
  cub::DeviceReduce::Min(d_temp_storage, temp_storage_bytes, input, d_sum, count);
  CUDA_RUNTIME(cudaMalloc(&d_temp_storage, temp_storage_bytes));
  cub::DeviceReduce::Min(d_temp_storage, temp_storage_bytes, input, d_sum, count);
  CUDA_RUNTIME(cudaFree(d_temp_storage));
  OutputType sum = getVal<OutputType>(d_sum, 0, at);
  CUDA_RUNTIME(cudaFree(d_sum));
  return sum;
}


template <typename InputType, typename OutputType>
OutputType CUBArgMin(
    InputType *input,
    const int count, int devId,
    cudaStream_t stream = 0, AllocationTypeEnum at = unified)
{
  CUDA_RUNTIME(cudaSetDevice(devId));

  void *d_temp_storage = nullptr;
  size_t temp_storage_bytes = 0;
  OutputType *d_sum;
  cub::KeyValuePair<int, int>   *d_out;
  CUDA_RUNTIME(cudaMalloc((void**)&d_sum, sizeof(OutputType)));

  /*record the last input item in case it is an in-place scan*/
  cub::DeviceReduce::ArgMin(d_temp_storage, temp_storage_bytes, input, d_out, count);
  CUDA_RUNTIME(cudaMalloc(&d_temp_storage, temp_storage_bytes));
  cub::DeviceReduce::ArgMin(d_temp_storage, temp_storage_bytes, input, d_out, count);
  CUDA_RUNTIME(cudaFree(d_temp_storage));
  OutputType sum = getVal<OutputType>(d_out->key, 0, at);
  CUDA_RUNTIME(cudaFree(d_sum));
  return sum;
}
