#include <faiss/gpu/GpuIndexFlat.h>
#include <faiss/gpu/StandardGpuResources.h>
#include <iomanip>
#include <iostream>
#include <vector>

// Test-only stream adapter around the collected GPU FlatL2 implementation.
// Emit k+1 candidates; the Python oracle removes each query's own vertex ID.
int main() {
  faiss::gpu::StandardGpuResources resources;
  resources.setTempMemory(64 * 1024 * 1024);
  int n, dim, k;
  while (std::cin >> n >> dim >> k) {
    std::vector<float> x(n * dim);
    for (auto& value : x) std::cin >> value;
    faiss::gpu::GpuIndexFlatL2 index(&resources, dim);
    index.add(n, x.data());
    std::vector<float> distances(n * (k + 1));
    std::vector<faiss::idx_t> ids(distances.size());
    index.search(n, x.data(), k + 1, distances.data(), ids.data());
    std::cout << '[' << std::setprecision(9);
    for (int i = 0; i < n; ++i) {
      if (i) std::cout << ',';
      std::cout << '[';
      for (int j = 0; j <= k; ++j) {
        if (j) std::cout << ',';
        const auto offset = i * (k + 1) + j;
        std::cout << '[' << ids[offset] << ',' << distances[offset] << ']';
      }
      std::cout << ']';
    }
    std::cout << "]\n" << std::flush;
  }
}
