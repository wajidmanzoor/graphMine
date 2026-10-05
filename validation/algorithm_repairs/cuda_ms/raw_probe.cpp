#include <cuda_runtime.h>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
extern "C" {
#include "cudams.h"
#include "motzkin_cuda.h"
}

// id n m mode allowed_count, edges, then optional allowed vertex IDs.
int main(int argc, char** argv) {
  if (argc != 3) return 2;
  std::ifstream input(argv[1]);
  std::ofstream output(argv[2]);
  if (!input || !output) return 2;
  init_cuda();
  quiet = 1;
  std::string id;
  int n, m, mode, count;
  while (input >> id >> n >> m >> mode >> count) {
    std::vector<std::vector<char>> rows(n, std::vector<char>(n, 0));
    std::vector<char*> pointers;
    for (auto& row : rows) pointers.push_back(row.data());
    for (int e = 0, u, v; e < m; ++e) {
      if (!(input >> u >> v) || u < 0 || v < 0 || u >= n || v >= n) return 2;
      rows[u][v] = rows[v][u] = 1;
    }
    t_bitmask allowed = count >= 0 ? mask_alloc(n) : nullptr;
    for (int i = 0, v; i < count; ++i) {
      if (!(input >> v) || v < 0 || v >= n) return 2;
      allowed[v / 64] |= 1ULL << (v % 64);
    }
    t_bitmask result = nullptr, upper = nullptr;
    const float value = graph_clique_cuda(&result, &upper, pointers.data(), n,
                                         allowed, 5, .001F, .5F, 3, mode);
    if (!result || value < 0 || cudaDeviceSynchronize() != cudaSuccess) {
      output << id << " ERROR" << std::endl;
    } else {
      output << id << " OK " << mask_size(result, n) << ' ' << value << ' '
             << (upper ? mask_size(upper, n) : -1);
      for (int v = 0; v < n; ++v) if (result[v / 64] & (1ULL << (v % 64))) output << ' ' << v;
      output << std::endl;
    }
    mask_free(result);
    mask_free(upper);
    mask_free(allowed);
  }
  return input.eof() ? 0 : 2;
}
