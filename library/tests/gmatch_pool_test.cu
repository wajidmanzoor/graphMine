#include <cuda_runtime.h>
#include <stdexcept>
#include <string>

#include "mem_manager.h"

__global__ void exhaust_pool(MemPool* pool, int* allocated) {
  int count = 0;
  while (pool->alloc() != nullptr) ++count;
  *allocated = count;
}

int main() {
  cudaCheck(cudaSetDevice(0));
  MemPool pool;
  int* output = nullptr;
  MemPool* device_pool = nullptr;
  cudaCheck(cudaMalloc(&output, sizeof(int)));
  cudaCheck(cudaMalloc(&device_pool, sizeof(MemPool)));
  cudaCheck(cudaMemcpy(device_pool, &pool, sizeof(MemPool), cudaMemcpyHostToDevice));
  exhaust_pool<<<1, 1>>>(device_pool, output);
  cudaCheck(cudaGetLastError());
  int count = 0;
  cudaCheck(cudaMemcpy(&count, output, sizeof(int), cudaMemcpyDeviceToHost));
  // The artifact intentionally leaves its final block unused. Exhaustion must
  // return nullptr for the BFS-to-DFS fallback, without writing past the pool.
  if (count != memPoolBlockNum - 1) {
    throw std::runtime_error("gMatch pool did not stop at its allocation bound");
  }
  pool.deallocate();
  cudaCheck(cudaFree(device_pool));

  MemManager manager;
  bool rejected = false;
  try {
    const int oversized = memPoolBlockNum * (memPoolBlockIntNum / 2) + 1;
    manager.init(output, oversized, 0, oversized);
  } catch (const std::runtime_error& error) {
    rejected = std::string(error.what()).find("initial matches exceed") != std::string::npos;
  }
  manager.deallocate();
  cudaCheck(cudaFree(output));
  if (!rejected) {
    throw std::runtime_error("gMatch accepted an oversized initial property array");
  }
  return 0;
}
