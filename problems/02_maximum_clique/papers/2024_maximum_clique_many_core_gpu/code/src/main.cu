#include <cuda_runtime.h>
#include <iostream>
#include <omp.h>
#include <vector>

#include "../include/cgarray.cuh"
#include "../include/config.h"
#include "../include/csrcoo.cuh"
#include "../include/fileop.h"
#include "../include/kcore.cuh"
#include "../include/main_support.cuh"
#include "../include/timer.h"
#include "../include/utils.cuh"
#include "../mcp/mcp.cuh"

using namespace std;

int main(int argc, char **argv)
{
  Config config = parseArgs(argc, argv);

  printf("\033[0m");
  printf("Welcome ---------------------\n");
  printConfig(config);

  if (config.mt == MAINTASK::CONVERT)
  {
    graph::convert_to_bel<DataType>(config.srcGraph, config.dstGraph);
    return 0;
  }

  Timer read_graph_timer;
  Timer total_timer;
  vector<EdgeTy<DataType>> edges;
  graph::read_bel(config.srcGraph, edges);

  auto full = [](const EdgeTy<DataType> &e)
  { return false; };
  graph::CSRCOO<DataType> csrcoo = graph::CSRCOO<DataType>::from_edgelist(edges, full);
  vector<EdgeTy<DataType>>().swap(edges);

  DataType n = csrcoo.num_rows();
  DataType m = csrcoo.nnz();

  graph::COOCSRGraph<DataType> g;
  graph::COOCSRGraph_d<DataType> *gd = (graph::COOCSRGraph_d<DataType> *)malloc(sizeof(graph::COOCSRGraph_d<DataType>));
  g.numNodes = n;
  g.capacity = m;
  g.numEdges = m;
  gd->numNodes = g.numNodes;
  gd->numEdges = g.numEdges;
  gd->capacity = g.capacity;

  // No Allocation
  g.rowPtr = new graph::GPUArray<DataType>("Row pointer", AllocationTypeEnum::noalloc, n + 1, config.deviceId);
  g.rowInd = new graph::GPUArray<DataType>("Src Index", AllocationTypeEnum::noalloc, m, config.deviceId);
  g.colInd = new graph::GPUArray<DataType>("Dst Index", AllocationTypeEnum::noalloc, m, config.deviceId);

  DataType *rp, *ri, *ci;
  CUDA_RUNTIME(cudaMallocManaged((void **)&(rp), (n + 1) * (uint64) sizeof(DataType)));
  CUDA_RUNTIME(cudaMallocManaged((void **)&(ri), (m) * (uint64) sizeof(DataType)));
  CUDA_RUNTIME(cudaMallocManaged((void **)&(ci), (m) * (uint64) sizeof(DataType)));
  CUDA_RUNTIME(cudaMemcpy(rp, csrcoo.row_ptr(), (n + 1) * (uint64) sizeof(DataType), cudaMemcpyDefault));
  CUDA_RUNTIME(cudaMemcpy(ri, csrcoo.row_ind(), (m) * (uint64) sizeof(DataType), cudaMemcpyDefault));
  CUDA_RUNTIME(cudaMemcpy(ci, csrcoo.col_ind(), (m) * (uint64) sizeof(DataType), cudaMemcpyDefault));
  cudaMemAdvise(rp, (n + 1) * (uint64) sizeof(DataType), cudaMemAdviseSetReadMostly, config.deviceId /*ignored*/);
  cudaMemAdvise(ri, (m) * (uint64) sizeof(DataType), cudaMemAdviseSetReadMostly, config.deviceId /*ignored*/);
  cudaMemAdvise(ci, (m) * (uint64) sizeof(DataType), cudaMemAdviseSetReadMostly, config.deviceId /*ignored*/);
  g.rowPtr->cdata() = rp;
  g.rowPtr->setAlloc(cpuonly);
  g.rowInd->cdata() = ri;
  g.rowInd->setAlloc(cpuonly);
  g.colInd->cdata() = ci;
  g.colInd->setAlloc(cpuonly);

  Log(info, "Read graph time: %f s", read_graph_timer.elapsed());
  Log(info, "n = %u and m = %u", n, m);
  Timer transfer_timer;

  g.rowPtr->switch_to_gpu(config.deviceId);
  gd->rowPtr = g.rowPtr->gdata();

  if (g.numEdges > 1500000000)
  {
    gd->rowInd = g.rowInd->cdata();
    gd->colInd = g.colInd->cdata();
  }
  else
  {
    g.rowInd->switch_to_gpu(config.deviceId);
    g.colInd->switch_to_gpu(config.deviceId);
    gd->rowInd = g.rowInd->gdata();
    gd->colInd = g.colInd->gdata();
  }
  double transfer = transfer_timer.elapsed();
  Log(info, "Transfer Time: %f s", transfer);

  Timer degeneracy_time;
  graph::SingleGPU_Kcore<DataType, PeelType> kcore(config.deviceId);
  kcore.findKcoreIncremental_async(*gd);
  Log(info, "Degeneracy ordering time: %f s", degeneracy_time.elapsed());
  Log(info, "Heuristic clique size: %d", kcore.heurCliqueSize.getSingle(0));

  if (config.mt == MAINTASK::MCP && kcore.heurCliqueSize.getSingle(0) == kcore.count() + 1
    || config.mt == MAINTASK::MCP_EVAL && kcore.heurCliqueSize.getSingle(0) == kcore.count() + 1)
  {
    Log(info, "Maximum clique found in preprocessing time, size: %u", kcore.heurCliqueSize.getSingle(0));
    g.rowInd->freeGPU();
    g.colInd->freeGPU();
    g.rowPtr->freeGPU();
    free(gd);
    Log(info, "Total Time: %f", total_timer.elapsed());
    Log(info, "Done...");
    return 0;
  }

  if (kcore.heurCliqueSize.getSingle(0) > config.lb)
  {
    config.lb = kcore.heurCliqueSize.getSingle(0);
  }

  // If main task is MCP Reduce the graph:
  Timer csr_recreation_time;
  CUDAContext context;
  const size_t block_size = 256;
  graph::COOCSRGraph_d<DataType> *red_gd = (graph::COOCSRGraph_d<DataType> *)malloc(sizeof(graph::COOCSRGraph_d<DataType>));
  graph::GPUArray<DataType> core_numbers_red;
  DataType n_red = 0;
  DataType* n_red_d = nullptr;
  DataType m_red = 0;
  DataType* m_red_d = nullptr;
  graph::GPUArray<DataType> d_oldName, d_newName;
  DataType maxCore;

  if (config.mt == MAINTASK::MCP || config.mt == MAINTASK::MCP_EVAL)
  {

    Log(info, "Reducing the graph and reversing the degeneracy order..");
    kcore.nodePriority.freeGPU();

    const uint conc_blocks_per_SM = context.GetConCBlocks(block_size);
    const uint blocks = conc_blocks_per_SM * context.num_SMs;
    maxCore = kcore.count();
    // Count the number of vertex:
    CUDA_RUNTIME(cudaMalloc((void**)&n_red_d, sizeof(DataType)));
    CUDA_RUNTIME(cudaMemset((void*)n_red_d, 0, sizeof(DataType)));
    execKernel((getNodeNumberReducedByLB_kernel<DataType>), blocks, block_size, config.deviceId, false, *gd, kcore.coreNumber.gdata(), config.lb, n_red_d);
    CUDA_RUNTIME(cudaMemcpy(&n_red, n_red_d, sizeof(DataType), ::cudaMemcpyDeviceToHost));

    if(n_red == 0) {
      Log(info, "Search space is over: No solution bigger than the lower bound.");
      return 0;
    }

    // Count the number of edges
    graph::GPUArray<DataType> red_degrees, red_degrees_flagged;
    graph::GPUArray<char> d_flags;
    graph::GPUArray<DataType> indices;

    d_flags.initialize("Flags", AllocationTypeEnum::unified, n, config.deviceId);
    d_flags.setAll(0, true);
    red_degrees.initialize("Degrees of the reduced graph", AllocationTypeEnum::unified, n, config.deviceId);
    red_degrees.setAll(0, true);

    execKernel((computeFlags_kernel<DataType>), blocks, block_size, config.deviceId, false, *gd, kcore.coreNumber.gdata(), config.lb, d_flags.gdata());
  
    CUDA_RUNTIME(cudaMalloc((void**)&m_red_d, sizeof(DataType)));
    CUDA_RUNTIME(cudaMemset((void*)m_red_d, 0, sizeof(DataType)));
    execKernel((getEdgeNumberAndDegreesReducedByLB_kernel<DataType>), blocks, block_size, config.deviceId, false, *gd, kcore.coreNumber.gdata(), config.lb, m_red_d, red_degrees.gdata());
    CUDA_RUNTIME(cudaMemcpy(&m_red, m_red_d, sizeof(DataType), ::cudaMemcpyDeviceToHost));

    cudaFree(n_red_d);
    cudaFree(m_red_d);
  
    d_oldName.initialize("Old Names", AllocationTypeEnum::unified, n_red, config.deviceId);
    
    red_degrees_flagged.initialize("Degrees of reduced graph flagged", AllocationTypeEnum::unified, n_red, config.deviceId);
    indices.initialize("Indices from 0 to n", AllocationTypeEnum::unified, n, config.deviceId);
    

    CUBSelect(red_degrees.gdata(), red_degrees_flagged.gdata(), d_flags.gdata(), n, config.deviceId);
    red_degrees.freeGPU();

    // Array of inidces generate
    execKernel((generateIndices_kernel<DataType>), blocks, block_size, config.deviceId, false, indices.gdata(), n);

    // Compute old names
    graph::GPUArray<DataType> d_temp_old_name;
    d_temp_old_name.initialize("Temporary old name", AllocationTypeEnum::unified, n_red, config.deviceId);

    CUBSelect(indices.gdata(), d_temp_old_name.gdata(), d_flags.gdata(), n, config.deviceId);
    indices.freeGPU();
    
    core_numbers_red.initialize("Core Numbers Reduced", AllocationTypeEnum::gpu, n_red, config.deviceId);

    CUBSelect(kcore.coreNumber.gdata(), core_numbers_red.gdata(), d_flags.gdata(), n, config.deviceId);

    // Sort Indeces
    void *d_temp_storage = nullptr;
    size_t temp_storage_bytes = 0;
    cub::DeviceRadixSort::SortPairsDescending(
              d_temp_storage, temp_storage_bytes,
               core_numbers_red.gdata(), core_numbers_red.gdata(),
                d_temp_old_name.gdata(), d_oldName.gdata(), n_red);
    // Allocate temporary storage
    CUDA_RUNTIME(cudaMalloc(&d_temp_storage, temp_storage_bytes));
   
    // Run sorting operation
    cub::DeviceRadixSort::SortPairsDescending(
              d_temp_storage, temp_storage_bytes,
               core_numbers_red.gdata(), core_numbers_red.gdata(),
                d_temp_old_name.gdata(), d_oldName.gdata(), n_red);
    cudaFree(d_temp_storage);

    cudaDeviceSynchronize();
    d_temp_old_name.freeGPU();

    CUBSelect(kcore.coreNumber.gdata(), core_numbers_red.gdata(), d_flags.gdata(), n, config.deviceId);
    d_flags.freeGPU();

    d_temp_storage = nullptr;
    temp_storage_bytes = 0;
    cub::DeviceRadixSort::SortPairsDescending(
              d_temp_storage, temp_storage_bytes,
               core_numbers_red.gdata(), core_numbers_red.gdata(),
                red_degrees_flagged.gdata(), red_degrees_flagged.gdata(), n_red);
    // Allocate temporary storage
    CUDA_RUNTIME(cudaMalloc(&d_temp_storage, temp_storage_bytes));
   
    // Run sorting operation
    cub::DeviceRadixSort::SortPairsDescending(
              d_temp_storage, temp_storage_bytes,
               core_numbers_red.gdata(), core_numbers_red.gdata(),
                red_degrees_flagged.gdata(), red_degrees_flagged.gdata(), n_red);
    cudaFree(d_temp_storage);

    cudaDeviceSynchronize();

    // Graph allocation
    red_gd->numNodes = n_red;
    red_gd->numEdges = m_red;
    red_gd->capacity = m_red;
    CUDA_RUNTIME(cudaMallocManaged((void **)&(red_gd->colInd), (m_red) * (uint64) sizeof(DataType)));
    CUDA_RUNTIME(cudaMallocManaged((void **)&(red_gd->rowInd), (m_red) * (uint64) sizeof(DataType)));
    CUDA_RUNTIME(cudaMallocManaged((void **)&(red_gd->rowPtr), (n_red + 1) * (uint64) sizeof(DataType)));

    CUBScanExclusive<DataType, DataType>(red_degrees_flagged.gdata(), red_gd->rowPtr, n_red, config.deviceId);
    cudaMemcpy(&red_gd->rowPtr[n_red], &m_red, sizeof(DataType), ::cudaMemcpyHostToDevice);
    red_degrees_flagged.freeGPU();
    
    // Compute new names
    d_newName.initialize("New Names", AllocationTypeEnum::unified, n, config.deviceId);
    execKernel((computeNewName_kernel<DataType>), blocks, block_size, config.deviceId, false, d_oldName.gdata(), d_newName.gdata(), n_red, n);
    execKernel((buildReducedByLBB_kernel<DataType, PeelType>), 
      (n_red + block_size - 1) / block_size, block_size, config.deviceId, false, *gd, *red_gd, kcore.coreNumber.gdata(), d_oldName.gdata(), d_newName.gdata(), config.lb);
    d_newName.freeGPU();
    kcore.coreNumber.freeGPU();
   

    Log(info, "Reduced to n = %u and m = %u", n_red, m_red);

    d_temp_storage = NULL;
    temp_storage_bytes = 0;
    cub::DeviceSegmentedRadixSort::SortKeys(d_temp_storage, temp_storage_bytes, red_gd->colInd, red_gd->colInd, m_red, n_red, red_gd->rowPtr, red_gd->rowPtr + 1);
    // Allocate temporary storage
    cudaMalloc(&d_temp_storage, temp_storage_bytes);
    cub::DeviceSegmentedRadixSort::SortKeys(d_temp_storage, temp_storage_bytes, red_gd->colInd, red_gd->colInd, m_red, n_red, red_gd->rowPtr, red_gd->rowPtr + 1);
    cudaFree(d_temp_storage);
    
    cudaDeviceSynchronize();

  }

  graph::COOCSRGraph_d<DataType> *gsplit = (graph::COOCSRGraph_d<DataType> *)malloc(sizeof(graph::COOCSRGraph_d<DataType>));

  if (config.mt == MAINTASK::MCP || config.mt == MAINTASK::MCP_EVAL)
  {
    
    gsplit->numNodes = n_red;
    gsplit->numEdges = m_red;
    gsplit->capacity = m_red;

    CUDA_RUNTIME(cudaMallocManaged((void **)&(gsplit->colInd), (m_red) * (uint64) sizeof(DataType)));
    CUDA_RUNTIME(cudaMallocManaged((void **)&(gsplit->splitPtr), (n_red + 1) * (uint64) sizeof(DataType)));
    CUDA_RUNTIME(cudaMemcpy(gsplit->colInd, red_gd->colInd, m_red * (uint64) sizeof(DataType), ::cudaMemcpyDeviceToDevice));

    CUDA_RUNTIME(cudaMallocManaged((void **)&(gsplit->rowPtr), (n_red + 1) * (uint64) sizeof(DataType)));
    CUDA_RUNTIME(cudaMemcpy(gsplit->rowPtr, red_gd->rowPtr, (n_red + 1) * (uint64) sizeof(DataType), cudaMemcpyDefault));

    CUDA_RUNTIME(cudaMallocManaged((void **)&(gsplit->rowInd), (m_red) * (uint64) sizeof(DataType)));
    CUDA_RUNTIME(cudaMemcpy(gsplit->rowInd, red_gd->rowInd, (m_red) * (uint64) sizeof(DataType), cudaMemcpyDefault));

    d_oldName.freeGPU();
    cudaFree(red_gd->colInd);
    cudaFree(red_gd->rowInd);
    cudaFree(red_gd->rowPtr);
    free(red_gd);

    graph::GPUArray<DataType> split_ptr("Split Ptr", AllocationTypeEnum::unified, n_red + 1, config.deviceId);
    split_ptr.setAll(0, true);
    execKernel(set_priority_2<DataType>, (m_red + block_size - 1) / block_size, block_size, config.deviceId, false, *gsplit, m_red, split_ptr.gdata());
    CUDA_RUNTIME(cudaMemcpy(gsplit->splitPtr, split_ptr.gdata(), (n_red + 1) * (uint64) sizeof(DataType), cudaMemcpyDefault));
    execKernel(split_pointer<DataType>, (n_red + 1 + block_size - 1) / block_size, block_size, config.deviceId, false, *gsplit, gsplit->splitPtr);
    split_ptr.freeGPU();

    cudaMemAdvise(gsplit->colInd, (m_red) * (uint64) sizeof(DataType), cudaMemAdviseSetReadMostly, config.deviceId /*ignored*/);
    cudaMemAdvise(gsplit->splitPtr, (n_red + 1) * (uint64) sizeof(DataType), cudaMemAdviseSetReadMostly, config.deviceId /*ignored*/);
    cudaMemAdvise(gsplit->rowPtr, (n_red + 1) * (uint64) sizeof(DataType), cudaMemAdviseSetReadMostly, config.deviceId /*ignored*/);
    cudaMemAdvise(gsplit->rowInd, (m_red) * (uint64) sizeof(DataType), cudaMemAdviseSetReadMostly, config.deviceId /*ignored*/);

  }

  g.rowPtr->freeGPU();
  g.rowInd->freeGPU();
  g.colInd->freeGPU();
  CUDA_RUNTIME(cudaFree(rp));
  CUDA_RUNTIME(cudaFree(ri));
  CUDA_RUNTIME(cudaFree(ci));
  free(gd);
  
  Log(info, "CSR Recreation time: %f s", csr_recreation_time.elapsed());

  if(config.mt == MAINTASK::MCP || config.mt == MAINTASK::MCP_EVAL) {

    vector<graph::MultiGPU_MCP<DataType>> mcp;

    for (int i = 0; i < config.gpus.size(); i++)
      mcp.push_back(graph::MultiGPU_MCP<DataType>(config.gpus[i], i, config.gpus.size(), core_numbers_red.gdata(), maxCore));

    Timer mcp_timer;

    #pragma omp parallel for
    for (int i = 0; i < config.gpus.size(); i++)
    {
      mcp[i].mcp_search<32>(*gsplit, config);
      printf("Finished Launching Instance %d.\n", i);
    }
    for (int i = 0; i < config.gpus.size(); i++)
      mcp[i].sync();

    double time = mcp_timer.elapsed();
    Log(info, "search time %f s", time);

    uint64 max_clique = 0;
    for (int i = 0; i < config.gpus.size(); i++){
      mcp[i].get_results(config, *gsplit);
      auto clique_size = mcp[i].show();
      if (max_clique < clique_size)
        max_clique = clique_size;
    }
    cout << "Found a maximum clique of size " << max_clique << "." << '\n';
    
  }

  CUDA_RUNTIME(cudaFree(gsplit->colInd));
  CUDA_RUNTIME(cudaFree(gsplit->splitPtr));
  CUDA_RUNTIME(cudaFree(gsplit->rowPtr));
  CUDA_RUNTIME(cudaFree(gsplit->rowInd));
  core_numbers_red.freeGPU();
  free(gsplit);
  double total_time = total_timer.elapsed();
  Log(info, "Total time: %f s", total_time);
  printf("Done ...\n");
  return 0;
}
