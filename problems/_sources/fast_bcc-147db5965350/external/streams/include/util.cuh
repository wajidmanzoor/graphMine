#ifndef UTIL_H
#define UTIL_H

inline void CudaAssert(cudaError_t code, const char* expr, const char* file, int line) {
    if (code != cudaSuccess) {
        std::cerr << "CUDA Error: " << cudaGetErrorString(code) << " in " << file << " at line " << line << " during " << expr << std::endl;
        exit(code);
    }
}

// Define the CUCHECK macro
#define CUCHECK(x) CudaAssert(x, #x, __FILE__, __LINE__)

typedef long long ll;
typedef unsigned long long ull;

#endif // UTIL_H