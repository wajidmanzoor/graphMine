#include "graph_gpu.cuh"

__host__ void GraphGpu::LoadFromCpu(Graph &graph, bool print)
{

  assert(rowoffset_ == nullptr && colidx_ == nullptr);
  vid_t *rowoffset_cpu;
  vid_t *colidx_cpu;


  if(graph.GetRowOffset() == nullptr || graph.GetColIdx() == nullptr){
    rowoffset_cpu = new vid_t[graph.GetNumVertices() + 1];
    colidx_cpu = new vid_t[graph.GetNumEdges() * 2];
    // vid_t *rowidx_cpu = new vid_t[graph.GetNumEdges() * 2];
    vid_t edge_cpu = 0;

    for (vid_t i = 0; i < graph.GetNumVertices(); i++)
    {
      rowoffset_cpu[i] = edge_cpu;
      for (vid_t j = 0; j < graph.N(i).size(); j++)
      {
        // rowidx_cpu[edge_cpu] = i;
        colidx_cpu[edge_cpu] = graph.N(i)[j];
        edge_cpu++;
      }
    }
    rowoffset_cpu[graph.GetNumVertices()] = edge_cpu;
    assert(edge_cpu == graph.GetNumEdges() * 2);
  } else {
    rowoffset_cpu = graph.GetRowOffset();
    colidx_cpu = graph.GetColIdx();
  }
  
  // In CSR format, the number of elements in colidx and rowidx should be twice the number of edges
  // because in an undirected graph, each edge is represented twice (from vertex A to vertex B and from vertex B to vertex A).


  CUDA_CHECK(cudaMalloc(&rowoffset_, sizeof(vid_t) * (graph.GetNumVertices() + 1)));
  CUDA_CHECK(cudaMalloc(&colidx_, sizeof(vid_t) * graph.GetNumEdges() * 2));
  // CUDA_CHECK(cudaMalloc(&rowidx_, sizeof(vid_t) * graph.GetNumEdges() * 2));
  CUDA_CHECK(cudaMemcpy(rowoffset_, rowoffset_cpu, sizeof(vid_t) * (graph.GetNumVertices() + 1), cudaMemcpyHostToDevice));
  CUDA_CHECK(cudaMemcpy(colidx_, colidx_cpu, sizeof(vid_t) * graph.GetNumEdges() * 2, cudaMemcpyHostToDevice));
  // CUDA_CHECK(cudaMemcpy(rowidx_, rowidx_cpu, sizeof(vid_t) * graph.GetNumEdges() * 2, cudaMemcpyHostToDevice));

  size_t total_mem = sizeof(vid_t) * (graph.GetNumVertices() + 1) + sizeof(vid_t) * graph.GetNumEdges() * 2;
  if(print)
    std::cout <<"\033[90m" << "[GPU] Graph memory usage: " << total_mem / 1024.0 / 1024.0 << " MB" << "\033[0m" << std::endl;

  num_vertices_ = graph.GetNumVertices();
  num_edges_ = graph.GetNumEdges();
  max_degree_ = graph.GetMaxDegree();

  if(graph.GetRowOffset() == nullptr || graph.GetColIdx() == nullptr){
    delete[] rowoffset_cpu;
    delete[] colidx_cpu;
  }
  // delete[] rowidx_cpu;
}

__host__ void GraphGpu::Free()
{
  if (rowoffset_ != nullptr)
    CUDA_CHECK(cudaFree(rowoffset_));
  if (colidx_ != nullptr)
    CUDA_CHECK(cudaFree(colidx_));
  // if (rowidx_ != nullptr)
  //   CUDA_CHECK(cudaFree(rowidx_));
  rowoffset_ = nullptr;
  colidx_ = nullptr;
  // rowidx_ = nullptr;
}
