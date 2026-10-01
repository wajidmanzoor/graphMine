#pragma once

/* Minimal compatibility shim for the single CUDA Samples helper used by
 * TurboBC.  Current CUDA toolkit packages no longer install helper_cuda.h. */
#include <cstdio>
#include <cstdlib>
#ifdef GRAPHMINE_LIBRARY
#include <stdexcept>
#include <string>
#endif
#include <cuda_runtime.h>

inline void turbo_bc_check_cuda(cudaError_t result, const char *expression,
                                const char *file, int line) {
  if (result != cudaSuccess) {
#ifdef GRAPHMINE_LIBRARY
    throw std::runtime_error(std::string("CUDA call failed at ") + file + ":" +
                             std::to_string(line) + ": " + expression + ": " +
                             cudaGetErrorString(result));
#else
    std::fprintf(stderr, "CUDA call failed at %s:%d: %s: %s\n", file, line,
                 expression, cudaGetErrorString(result));
    std::exit(EXIT_FAILURE);
#endif
  }
}

#define checkCudaErrors(call)                                                   \
  turbo_bc_check_cuda((call), #call, __FILE__, __LINE__)
