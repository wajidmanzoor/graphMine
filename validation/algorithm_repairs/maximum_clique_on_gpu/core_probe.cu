#include <fstream>
#include <vector>
#include "kcore.cuh"

int main(int argc, char** argv) {
  if (argc != 3) return 2;
  std::ifstream input(argv[1]);
  std::ofstream output(argv[2]);
  std::string id;
  unsigned n, m;
  int bound;
  while (input >> id >> n >> m >> bound) {
    std::vector<std::vector<unsigned>> adjacency(n + 1);
    for (unsigned e = 0, u, v; e < m; ++e) {
      if (!(input >> u >> v)) return 2;
      adjacency[u + 1].push_back(v + 1);
      adjacency[v + 1].push_back(u + 1);
    }
    output << id;
    if (m == 0) {
      for (unsigned v = 0; v < n; ++v) output << " 0";
      output << std::endl;
      continue;
    }
    graph::COOCSRGraph_d<unsigned> g{};
    g.numNodes = n + 1;
    g.numEdges = 2 * m;
    CUDA_RUNTIME(cudaMallocManaged(&g.rowPtr, (n + 2ULL) * sizeof(unsigned)));
    CUDA_RUNTIME(cudaMallocManaged(&g.colInd, 2ULL * m * sizeof(unsigned)));
    unsigned index = 0;
    for (unsigned v = 0; v <= n; ++v) {
      g.rowPtr[v] = index;
      std::sort(adjacency[v].begin(), adjacency[v].end());
      for (auto neighbor : adjacency[v]) g.colInd[index++] = neighbor;
    }
    g.rowPtr[n + 1] = index;
    {
      graph::SingleGPU_Kcore<unsigned, int> solver(0);
      solver.findKcoreIncremental_async(g);
      auto* core = solver.coreNumber.copytocpu(0, n + 1, true);
      for (unsigned v = 1; v <= n; ++v) output << ' ' << core[v];
      std::free(core);
      output << std::endl;
    }
    CUDA_RUNTIME(cudaFree(g.rowPtr));
    CUDA_RUNTIME(cudaFree(g.colInd));
  }
  return input.eof() ? 0 : 2;
}
