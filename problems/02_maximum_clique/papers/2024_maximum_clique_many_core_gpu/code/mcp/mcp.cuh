#pragma once

#include <cstdio>
#include <cub/cub.cuh>
#include <cuda/atomic>
#include <cuda_runtime.h>
#include "../include/cgarray.cuh"
#include "../include/config.h"
#include "../include/defs.h"
#include "../include/logger.h"
#include "../include/queue.cuh"
#include "mcp_kernel_wl_donor.cuh"
#include "mcp_kernel_wl_donor_warp.cuh"
#include "parameter.cuh"
#include "mcp_utils.cuh"

using namespace std;



namespace graph
{

  template <typename T, int BLOCK_DIM_X>
  __global__ void getNodeDegree_kernel(T *node_degree, graph::COOCSRGraph_d<T> g, T *max_degree)
  {
    T gtid = threadIdx.x + blockIdx.x * blockDim.x;
    typedef cub::BlockReduce<T, BLOCK_DIM_X> BlockReduce;
    __shared__ typename BlockReduce::TempStorage temp_storage;
    T degree = 0;
    if (gtid < g.numNodes)
    {
      degree = g.rowPtr[gtid + 1] - g.rowPtr[gtid];
      node_degree[gtid] = degree;
    }

    T aggregate = BlockReduce(temp_storage).Reduce(degree, cub::Max());
    if (threadIdx.x == 0)
      atomicMax(max_degree, aggregate);
  }

  template <typename T, int BLOCK_DIM_X>
  __global__ void getSplitDegree_kernel(T *node_degree, graph::COOCSRGraph_d<T> g, T *max_degree)
  {
    T gtid = threadIdx.x + blockIdx.x * blockDim.x;
    typedef cub::BlockReduce<T, BLOCK_DIM_X> BlockReduce;
    __shared__ typename BlockReduce::TempStorage temp_storage;
    T degree = 0;
    if (gtid < g.numNodes)
    {
      degree = g.rowPtr[gtid + 1] - g.splitPtr[gtid];
      node_degree[gtid] = degree;
    }

    T aggregate = BlockReduce(temp_storage).Reduce(degree, cub::Max());
    if (threadIdx.x == 0)
      atomicMax(max_degree, aggregate);
  }

  template <typename T, int BLOCK_DIM_X>
  __global__ void getPreSplitDegree_kernel(T *node_degree, graph::COOCSRGraph_d<T> g, T *max_degree)
  {
    T gtid = threadIdx.x + blockIdx.x * blockDim.x;
    typedef cub::BlockReduce<T, BLOCK_DIM_X> BlockReduce;
    __shared__ typename BlockReduce::TempStorage temp_storage;
    T degree = 0;
    if (gtid < g.numNodes)
    {
      degree = g.splitPtr[gtid] - g.rowPtr[gtid];
      node_degree[gtid] = degree;
    }

    T aggregate = BlockReduce(temp_storage).Reduce(degree, cub::Max());
    if (threadIdx.x == 0)
      atomicMax(max_degree, aggregate);
  }

  template <typename T>
  class MultiGPU_MCP
  {
  private:
    int dev_, global_id_, total_instance_;
    cudaStream_t stream_;

  public:
    GPUArray<T> node_degree, max_degree, max_undirected_degree;
    GPUArray<T> encoded_induced_subgraph, current, next, ordering;
    GPUArray<T> P, A, B, Iset, Iset_count, Xx_aux, level_pointer, work_stealing, C, Cmax;
    GPUArray<bool> colored; 
    GPUArray<uint32_t> global_message;
    cuda::atomic<uint32_t, cuda::thread_scope_device> *work_ready = nullptr;
    cuda::binary_semaphore<cuda::thread_scope_device> *max_clique_sem = nullptr;
    uint32_t * d_core_numbers;
    queue_declare(queue, tickets, head, tail);
    uint32_t Cmax_size, *d_Cmax_size = nullptr;
    T * d_cut_by_kcore_l1 = nullptr, max_core, *cut_by_kcore_l1 = nullptr;
    T * d_cut_by_color = nullptr, *d_cut_by_color_l1 = nullptr, cut_by_color, cut_by_color_l1;
    float* d_max_subgraph_density = nullptr, max_subgraph_density, avg_subgraph_density, *d_avg_subgraph_density = nullptr;
    uint32_t *d_number_of_subgraphs = nullptr, number_of_subgraphs;
    uint32_t *d_max_subgraph_width = nullptr, *d_avg_subgraph_width = nullptr;
    uint32_t max_subgraph_width, avg_subgraph_width;
    unsigned long long *d_branches = nullptr, branches;

    MultiGPU_MCP(int dev, int global_id, int total_instance, uint32_t *core_numbers, T max_core) 
      : dev_(dev), global_id_(global_id), total_instance_(total_instance), d_core_numbers(core_numbers), max_core(max_core)
    {
      CUDA_RUNTIME(cudaSetDevice(dev_));
      CUDA_RUNTIME(cudaStreamCreate(&stream_));
      CUDA_RUNTIME(cudaStreamSynchronize(stream_));
    }

    MultiGPU_MCP() : MultiGPU_MCP(0, 0, 0, 0) {}

    void getNodeDegree(COOCSRGraph_d<T> &g, T *maxD)
    {
      const int dimBlock = 128;
      node_degree.initialize("Edge Support", unified, g.numNodes, dev_);
      uint dimGridNodes = (g.numNodes + dimBlock - 1) / dimBlock;
      execKernel((getNodeDegree_kernel<T, dimBlock>),
                 dimGridNodes, dimBlock, dev_, false, 
                 node_degree.gdata(), g, maxD);
      node_degree.freeGPU();
    }

    void getSplitDegree(COOCSRGraph_d<T> &g, T *maxD)
    {
      const int dimBlock = 128;
      node_degree.initialize("Edge Support", unified, g.numNodes, dev_);
      uint dimGridNodes = (g.numNodes + dimBlock - 1) / dimBlock;
      execKernel((getPreSplitDegree_kernel<T, dimBlock>),
                 dimGridNodes, dimBlock, dev_, false,
                 node_degree.gdata(), g, maxD);
      node_degree.freeGPU();
    }

    template <const int PSIZE>
    void mcp_search(COOCSRGraph_d<T> &gsplit, Config config)
    {
      CUDA_RUNTIME(cudaSetDevice(dev_));

      max_degree.initialize("degree", unified, 1, dev_);
      max_degree.setSingle(0, 0, true);
      getSplitDegree(gsplit, max_degree.gdata());

      max_undirected_degree.initialize("undirected degree", unified, 1, dev_);
      max_undirected_degree.setSingle(0, 0, true);
      getNodeDegree(gsplit, max_undirected_degree.gdata());

      Log(info, "Max directed degree: %u, max undirected degree: %u", max_degree.gdata()[0], max_undirected_degree.gdata()[0]);
      
      size_t free, total;
      CUDAContext context;
      T num_SMs = context.num_SMs;
      uint block_size = config.block_size;
      Log(info, "Max blocks per SM: %u, SMs: %u", context.max_blocks_per_sm, context.num_SMs);
      
      if (!config.warp_parallel)
      {
        if (config.block_size == 64)
        {
          if ((uint64)max_degree.gdata()[0] < 8192) 
          {
            block_size = 64;
          }
          else
          if ((uint64)max_degree.gdata()[0] < 16384) 
          {
            block_size = 128;
          }
          else
          if ((uint64)max_degree.gdata()[0] < 32768)
          {
            block_size = 256;
          }
          else
          if ((uint64)max_degree.gdata()[0] < 65546)
          {
            block_size = 512;
          }
          else
          {
            block_size = 1024;
          }
        }
      }else
      {
        if (config.block_size == 64)
        {
          if ((uint64)max_degree.gdata()[0] < 5000) 
          {
            block_size = 128;
          }
          else
          if ((uint64)max_degree.gdata()[0] < 10000) 
          {
            block_size = 256;
          }
          else
          {
            block_size = 512;
          }
        }
      }

      const uint hybrid_per_warp = config.warp_parallel ? (block_size / PSIZE) : 1;
      T conc_blocks_per_SM = context.GetConCBlocks(block_size);
      const uint partition_size = PSIZE;
      const uint dv = 32;
      const uint max_level = max_core + 2;
      const uint num_divs = (max_degree.gdata()[0] + dv - 1) / dv;
      const uint64 encode_size = (uint64)num_SMs * conc_blocks_per_SM * (max_degree.gdata()[0] * num_divs);

      encoded_induced_subgraph.initialize("induced subgraph", gpu, encode_size, dev_);

      const uint64 level_size = (uint64)num_SMs * conc_blocks_per_SM * hybrid_per_warp * max_level * num_divs;
      const uint64 iset_size = (uint64)num_SMs * conc_blocks_per_SM * hybrid_per_warp * max_level * (max_degree.gdata()[0]);
      const uint64 level_item_size = (uint64)num_SMs * conc_blocks_per_SM * hybrid_per_warp * max_level;

      P.initialize("P(possible)", gpu, level_size, dev_);
      B.initialize("B", gpu, level_size, dev_);
      A.initialize("A", gpu, level_size, dev_);
      Cmax.initialize("Cmax", gpu, max_level, dev_);
      C.initialize("C", gpu, level_item_size, dev_);
    
      if (config.colorAlg == COLORALG::NUMBER 
        || config.colorAlg == COLORALG::RENUMBER) {
        Iset.initialize("Iset", gpu, iset_size, dev_);
        Iset_count.initialize("Iset count", gpu, level_item_size, dev_);
      }
      else if (config.colorAlg == COLORALG::RECOLOR)
        Iset.initialize("Iset", gpu, level_size, dev_);
      colored.initialize("colored", gpu, num_SMs * conc_blocks_per_SM * hybrid_per_warp * max_level, dev_);
      P.setAll(0, true);

      float zero = 0.0f;
      CUDA_RUNTIME(cudaMalloc((void **)&d_Cmax_size, sizeof(uint32_t)));
      CUDA_RUNTIME(cudaMemcpy((void *)d_Cmax_size, &config.lb, sizeof(uint32_t), ::cudaMemcpyHostToDevice));

      if (config.verbose)
      {
        CUDA_RUNTIME(cudaMalloc((void **)&d_avg_subgraph_density, sizeof(float)));
        CUDA_RUNTIME(cudaMemcpy((void *)d_avg_subgraph_density, &zero, sizeof(float), ::cudaMemcpyHostToDevice));
        CUDA_RUNTIME(cudaMalloc((void **)&d_max_subgraph_density, sizeof(float)));
        CUDA_RUNTIME(cudaMemcpy((void *)d_max_subgraph_density, &zero, sizeof(float), ::cudaMemcpyHostToDevice));
        CUDA_RUNTIME(cudaMalloc((void **)&d_number_of_subgraphs, sizeof(uint32_t)));
        CUDA_RUNTIME(cudaMemset(d_number_of_subgraphs, 0, sizeof(uint32_t)));
        CUDA_RUNTIME(cudaMalloc((void **)&d_cut_by_color_l1, sizeof(T)));
        CUDA_RUNTIME(cudaMemset(d_cut_by_color_l1, 0, sizeof(T)));
        CUDA_RUNTIME(cudaMalloc((void **)&d_cut_by_color, sizeof(T)));
        CUDA_RUNTIME(cudaMemset(d_cut_by_color, 0, sizeof(T)));
        CUDA_RUNTIME(cudaMalloc((void **)&d_cut_by_kcore_l1, sizeof(T)));
        CUDA_RUNTIME(cudaMemset(d_cut_by_kcore_l1, 0, sizeof(T)));
        CUDA_RUNTIME(cudaMalloc((void **)&d_max_subgraph_width, sizeof(uint32_t)));
        CUDA_RUNTIME(cudaMemset(d_max_subgraph_width, 0, sizeof(uint32_t)));
        CUDA_RUNTIME(cudaMalloc((void **)&d_avg_subgraph_width, sizeof(uint32_t)));
        CUDA_RUNTIME(cudaMemset(d_avg_subgraph_width, 0, sizeof(uint32_t)));
        CUDA_RUNTIME(cudaMalloc((void **)&d_branches, sizeof(unsigned long long)));
        CUDA_RUNTIME(cudaMemset(d_branches, 0, sizeof(unsigned long long)));
      }
    
      level_pointer.initialize("level pointer", gpu, level_item_size, dev_);
      encoded_induced_subgraph.setAll(0, true);
      
      const uint numPartitions = block_size / partition_size;
      const uint msg_cnt = 5;
      const uint conc_blocks = num_SMs * conc_blocks_per_SM;
      const uint warps = conc_blocks * numPartitions;

      cudaMemcpyToSymbol(PARTSIZE, &partition_size, sizeof(PARTSIZE));
      cudaMemcpyToSymbol(NUMPART, &numPartitions, sizeof(NUMPART));
      cudaMemcpyToSymbol(MAXLEVEL, &max_level, sizeof(MAXLEVEL));
      cudaMemcpyToSymbol(NUMDIVS, &num_divs, sizeof(NUMDIVS));
      cudaMemcpyToSymbol(MAXDEG, &(max_degree.gdata()[0]), sizeof(MAXDEG));
      cudaMemcpyToSymbol(MAXUNDEG, &(max_undirected_degree.gdata()[0]), sizeof(MAXDEG));
      cudaMemcpyToSymbol(CBPSM, &(conc_blocks_per_SM), sizeof(CBPSM));
      cudaMemcpyToSymbol(MSGCNT, &(msg_cnt), sizeof(MSGCNT));
      cudaMemcpyToSymbol(CB, &(conc_blocks), sizeof(CB));
      cudaMemcpyToSymbol(WARPS, &(warps), sizeof(WARPS));

      CUDA_RUNTIME(cudaMalloc((void **)&work_ready, conc_blocks * hybrid_per_warp * sizeof(cuda::atomic<uint32_t, cuda::thread_scope_device>)));
      CUDA_RUNTIME(cudaMemset((void *)work_ready, 0, conc_blocks * hybrid_per_warp * sizeof(cuda::atomic<uint32_t, cuda::thread_scope_device>)));
      
      if (config.mt == MAINTASK::MCP_EVAL)
      {
        cuda::binary_semaphore<cuda::thread_scope_device> init_sem{1};
        CUDA_RUNTIME(cudaMalloc((void **)&max_clique_sem, sizeof(cuda::binary_semaphore<cuda::thread_scope_device>)));
        CUDA_RUNTIME(cudaMemcpy(max_clique_sem, &init_sem, sizeof(cuda::binary_semaphore<cuda::thread_scope_device>), ::cudaMemcpyHostToDevice));
      }

      global_message = GPUArray<uint32_t>("global message", gpu, conc_blocks * msg_cnt * hybrid_per_warp, dev_);
      const uint queue_size = conc_blocks * hybrid_per_warp;
      queue_init(queue, tickets, head, tail, queue_size, dev_);
      //if (config.hybrid) local_queue_init(local_queue, local_tickets, local_head, local_tail, queue_size, conc_blocks, dev_);
      work_stealing = GPUArray<uint32_t>("work stealing counter", gpu, 1, dev_);
      work_stealing.setAll(global_id_ + config.lb, true);
      Xx_aux = GPUArray<T>("auxiliary array for X for X ", gpu, 
                           max_degree.gdata()[0] * num_SMs * conc_blocks_per_SM * hybrid_per_warp, dev_);
      current = GPUArray<T>("Current ", gpu, 
                           max_degree.gdata()[0] * num_SMs * conc_blocks_per_SM, dev_);
      next = GPUArray<T>("Next ", gpu, 
                           max_degree.gdata()[0] * num_SMs * conc_blocks_per_SM, dev_);
      ordering = GPUArray<T>("Core numbers ", gpu, 
                           max_degree.gdata()[0] * num_SMs * conc_blocks_per_SM, dev_);
         

      cudaMemGetInfo(&free, &total);
      Log(info, "VRAM usage: %llu B", total - free);
      
      auto grid_block_size = num_SMs * conc_blocks_per_SM;
      auto kernel = mcp_kernel_l1_wl_donor_psanse<T, 128, partition_size>;

      if (!config.warp_parallel)
      {
        switch(config.colorAlg) 
        {

          case COLORALG::PSANSE:

            switch (block_size)
            {

            case 32:
              kernel = mcp_kernel_l1_wl_donor_psanse<T, 32, partition_size>;
              break;

            case 64:
              kernel = mcp_kernel_l1_wl_donor_psanse<T, 64, partition_size>;
              break;

            case 128:
              kernel = mcp_kernel_l1_wl_donor_psanse<T, 128, partition_size>;
              break;

            case 256:
              kernel = mcp_kernel_l1_wl_donor_psanse<T, 256, partition_size>;
              break;

            case 512:
              kernel = mcp_kernel_l1_wl_donor_psanse<T, 512, partition_size>;
              break;

            case 1024:
              kernel = mcp_kernel_l1_wl_donor_psanse<T, 1024, partition_size>;
              break;
            
            default:
              break;
            }
            break;

          case COLORALG::NUMBER:

            switch (block_size)
            {
            case 64:
              kernel = mcp_kernel_l1_wl_donor_tomita<T, 64, partition_size>;
              break;

            case 128:
              kernel = mcp_kernel_l1_wl_donor_tomita<T, 128, partition_size>;
              break;

            case 256:
              kernel = mcp_kernel_l1_wl_donor_tomita<T, 256, partition_size>;
              break;

            case 512:
              kernel = mcp_kernel_l1_wl_donor_tomita<T, 512, partition_size>;
              break;

            case 1024:
              kernel = mcp_kernel_l1_wl_donor_tomita<T, 1024, partition_size>;
              break;
            
            default:
              break;
            }
            break;

          case COLORALG::RECOLOR:

            switch (block_size)
            {
            
            case 64:
              kernel = mcp_kernel_l1_wl_donor_psanse_recolor<T, 64, partition_size>;
              break;

            case 128:
              kernel = mcp_kernel_l1_wl_donor_psanse_recolor<T, 128, partition_size>;
              break;

            case 256:
              kernel = mcp_kernel_l1_wl_donor_psanse_recolor<T, 256, partition_size>;
              break;

            case 512:
              kernel = mcp_kernel_l1_wl_donor_psanse_recolor<T, 512, partition_size>;
              break;

            case 1024:
              kernel = mcp_kernel_l1_wl_donor_psanse_recolor<T, 1024, partition_size>;
              break;
            
            default:
              break;
            }
            break;

          case COLORALG::RENUMBER:

            switch (block_size)
            {
            
            case 64:
              kernel = mcp_kernel_l1_wl_donor_tomita_renumber<T, 64, partition_size>;
              break;

            case 128:
              kernel = mcp_kernel_l1_wl_donor_tomita_renumber<T, 128, partition_size>;
              break;

            case 256:
              kernel = mcp_kernel_l1_wl_donor_tomita_renumber<T, 256, partition_size>;
              break;

            case 512:
              kernel = mcp_kernel_l1_wl_donor_tomita_renumber<T, 512, partition_size>;
              break;

            case 1024:
              kernel = mcp_kernel_l1_wl_donor_tomita_renumber<T, 1024, partition_size>;
              break;
            
            default:
              break;
            }
            break;

            case COLORALG::REDUCE:

            switch (block_size)
            {
            
            case 64:
              kernel = mcp_kernel_l1_wl_donor_reduce<T, 64, partition_size>;
              break;
      
            case 128:
              kernel = mcp_kernel_l1_wl_donor_reduce<T, 128, partition_size>;
              break;

            case 256:
              kernel = mcp_kernel_l1_wl_donor_reduce<T, 256, partition_size>;
              break;

            case 512:
              kernel = mcp_kernel_l1_wl_donor_reduce<T, 512, partition_size>;
              break;

            case 1024:
              kernel = mcp_kernel_l1_wl_donor_reduce<T, 1024, partition_size>;
              break;
            
            default:
              break;
            }
            break;

          default:
            break;
          
        }
      }else
      { 
        
        switch (config.colorAlg)
        {
          case COLORALG::PSANSE:
          switch (block_size)
          {
            case 128:
            kernel = mcp_kernel_l1_wl_donor_w_psanse<T, 128, partition_size>;
            break;  

            case 256:
            kernel = mcp_kernel_l1_wl_donor_w_psanse<T, 256, partition_size>;
            break;

            case 512:
            kernel = mcp_kernel_l1_wl_donor_w_psanse<T, 512, partition_size>;
            break;

            default:
            break;
          }
          break;

          case COLORALG::REDUCE:
          switch (block_size)
          {
            case 128:
            kernel = mcp_kernel_l1_wl_donor_w_reduce<T, 128, partition_size>;
            break;  

            case 256:
            kernel = mcp_kernel_l1_wl_donor_w_reduce<T, 256, partition_size>;
            break;

            case 512:
            kernel = mcp_kernel_l1_wl_donor_w_reduce<T, 512, partition_size>;
            break;

            default:
            break;
          }
          break;

          default:
          break;

        }
        
      }

      mcp::GLOBAL_HANDLE<T> gh;
      gh.gsplit = gsplit;
      gh.iteration_limit = gsplit.numNodes;
      gh.encoded_induced_subgraph = encoded_induced_subgraph.gdata();
      gh.P = P.gdata();
      gh.B = B.gdata();
      gh.A = A.gdata();
      gh.Cmax = Cmax.gdata();
      gh.C = C.gdata();
      gh.Iset = Iset.gdata();
      gh.Iset_count = Iset_count.gdata();
      
      gh.Cmax_size = d_Cmax_size;
      gh.cut_by_kcore_l1 = d_cut_by_kcore_l1;
      gh.Xx_aux = Xx_aux.gdata();
      gh.current = current.gdata();
      gh.next = next.gdata(); 
      gh.core = d_core_numbers;
      
      gh.ordering = ordering.gdata();
      gh.colored = colored.gdata();
      gh.cut_by_color = d_cut_by_color;
      gh.cut_by_color_l1 = d_cut_by_color_l1;
      gh.avg_subgraph_density = d_avg_subgraph_density;
      gh.max_subgraph_density = d_max_subgraph_density;
      gh.avg_subgraph_width = d_avg_subgraph_width;
      gh.max_subgraph_width = d_max_subgraph_width;
      gh.total_subgraph = d_number_of_subgraphs;
      gh.eval = config.mt == MAINTASK::MCP_EVAL ? true : false;
      gh.verbose = config.verbose;
      gh.branches = d_branches;
      
      gh.level_pointer = level_pointer.gdata();
      gh.work_ready = work_ready;
      gh.max_clique_sem = max_clique_sem;
      gh.global_message = global_message.gdata();
      gh.work_stealing = work_stealing.gdata();
      gh.stride = total_instance_;

      if (config.warp_parallel) Log(info, "Max external parallelism: %u", warps);
      Log(info, "Launching search kernel with grid size: %u, and block size: %u", grid_block_size, block_size);
      
      execKernelAsync((kernel),
                    grid_block_size, block_size, dev_, stream_, false,
                    gh, queue_caller(queue, tickets, head, tail));
      
      //sync();

      
    }

    void get_results(Config config, COOCSRGraph_d<T> &gsplit)
    {

      if (config.verbose)
      {
        Log(info, "Full Statistics:");
        CUDA_RUNTIME(cudaMemcpy(&cut_by_color_l1, d_cut_by_color_l1, sizeof(T), ::cudaMemcpyDeviceToHost));
        Log(info, "Cut branches by color l1: %u", cut_by_color_l1);
        // CUDA_RUNTIME(cudaMemcpy(&cut_by_renumber_l1, d_cut_by_renumber_l1, sizeof(T), ::cudaMemcpyDeviceToHost));
        // Log(info, "Cut branches by Re-NUMBER l1: %u", cut_by_renumber_l1);
        CUDA_RUNTIME(cudaMemcpy(&cut_by_kcore_l1, d_cut_by_kcore_l1, sizeof(T), ::cudaMemcpyDeviceToHost));
        Log(info, "Cut branches by kcore l1: %u", cut_by_kcore_l1);
        CUDA_RUNTIME(cudaMemcpy(&cut_by_color, d_cut_by_color, sizeof(T), ::cudaMemcpyDeviceToHost));
        Log(info, "Cut branches by color: %u", cut_by_color);
        CUDA_RUNTIME(cudaMemcpy(&number_of_subgraphs, d_number_of_subgraphs, sizeof(uint32_t), ::cudaMemcpyDeviceToHost));
        CUDA_RUNTIME(cudaMemcpy(&avg_subgraph_width, d_avg_subgraph_width, sizeof(uint32_t), ::cudaMemcpyDeviceToHost));
        if (number_of_subgraphs > 0)
        {
          Log(info, "Avarage subgraph width: %u", avg_subgraph_width / number_of_subgraphs);
          CUDA_RUNTIME(cudaMemcpy(&max_subgraph_width, d_max_subgraph_width, sizeof(uint32_t), ::cudaMemcpyDeviceToHost));
          Log(info, "Max subgraph width: %u", max_subgraph_width);
          CUDA_RUNTIME(cudaMemcpy(&avg_subgraph_density, d_avg_subgraph_density, sizeof(float), ::cudaMemcpyDeviceToHost));
          Log(info, "Avarage subgraph density: %f", avg_subgraph_density / float(number_of_subgraphs));
          CUDA_RUNTIME(cudaMemcpy(&max_subgraph_density, d_max_subgraph_density, sizeof(float), ::cudaMemcpyDeviceToHost));
          Log(info, "Max subgraph density: %f", max_subgraph_density);
          CUDA_RUNTIME(cudaMemcpy(&branches, d_branches, sizeof(unsigned long long), ::cudaMemcpyDeviceToHost));
          Log(info, "Explored branches: %llu", branches);
        }
      }

      CUDA_RUNTIME(cudaMemcpy((void *)&Cmax_size, d_Cmax_size, sizeof(uint32_t), ::cudaMemcpyDeviceToHost));
      CUDA_RUNTIME(cudaDeviceSynchronize());

      if (config.mt == MAINTASK::MCP_EVAL)
      {
        // Get solution
        T* Max_Clique = Cmax.copytocpu(0, Cmax_size, true);

        // Pay attention is w(G') not w(G), w(G') evaluated just for correctness of search procedure
        printf("w(G') = {");
        for (T i = 0; i < Cmax_size; i++) {
          if(i == Cmax_size - 1)
            printf("%u", Max_Clique[i]);
          else
            printf("%u, ", Max_Clique[i]);
          if (i % 10 == 9)
            printf("\n");
        }
        printf("}.\n");

        // Verify
        bool is_clique = true;
        for (T i = 0; i < Cmax_size && is_clique; i++)
        {
          for (T j = i + 1; j < Cmax_size && is_clique; j++)
          {
            bool connected = false;
            T src1 = Max_Clique[i], src2 = Max_Clique[j];
            for (T k = 0, index = gsplit.colInd[gsplit.rowPtr[src1]]; 
              k < gsplit.rowPtr[src1 + 1] - gsplit.rowPtr[src1];
              index = gsplit.colInd[gsplit.rowPtr[src1] + ++k])
            {
              if (index == src2)
              {
                connected = true;
                break;
              }
            }

            if (!connected)
            {
              printf("%u and %u not connected.\n", src1, src2);
              is_clique = false;
            }
           
          }
        }

        if (!is_clique)
          printf("Not a Clique.\n");

        delete[] Max_Clique;
      }
    }

    uint32_t show()
    {
      cout.imbue(std::locale(""));
      return Cmax_size;
    }

    ~MultiGPU_MCP()
    {
      free_memory();
    }

    void free_memory()
    {
      // level_candidate.freeGPU();
      work_stealing.freeGPU();
      encoded_induced_subgraph.freeGPU();
      P.freeGPU();
      B.freeGPU();
      A.freeGPU();
      C.freeGPU();
      Cmax.freeGPU();
      Iset.freeGPU();
      Iset_count.freeGPU();
      Xx_aux.freeGPU();

      level_pointer.freeGPU();
      node_degree.freeGPU();
      max_degree.freeGPU();
      colored.freeGPU();
      ordering.freeGPU();
      next.freeGPU();
      current.freeGPU();
      max_undirected_degree.freeGPU();

      if (max_clique_sem != nullptr)
        CUDA_RUNTIME(cudaFree(max_clique_sem));

      if (d_max_subgraph_density != nullptr)
        CUDA_RUNTIME(cudaFree(d_max_subgraph_density));
      if (d_avg_subgraph_density != nullptr)
        CUDA_RUNTIME(cudaFree(d_avg_subgraph_density));
      if (d_max_subgraph_width != nullptr)
        CUDA_RUNTIME(cudaFree(d_max_subgraph_width));
      if (d_avg_subgraph_width != nullptr)
        CUDA_RUNTIME(cudaFree(d_avg_subgraph_width));
      if (d_Cmax_size != nullptr)
        CUDA_RUNTIME(cudaFree(d_Cmax_size));
      if (d_cut_by_color != nullptr)
        CUDA_RUNTIME(cudaFree(d_cut_by_color));
      if (d_cut_by_color_l1 != nullptr)
        CUDA_RUNTIME(cudaFree(d_cut_by_color_l1));
      if (d_cut_by_kcore_l1 != nullptr)
        CUDA_RUNTIME(cudaFree(d_cut_by_kcore_l1));
      if (d_number_of_subgraphs != nullptr)
        CUDA_RUNTIME(cudaFree(d_number_of_subgraphs));
      if (d_branches != nullptr)
        CUDA_RUNTIME(cudaFree(d_branches));

      if (work_ready != nullptr)
        CUDA_RUNTIME(cudaFree((void *)work_ready));
      
      global_message.freeGPU();
      queue_free(queue, tickets, head, tail);
      if (stream_ != nullptr)
      {
        CUDA_RUNTIME(cudaStreamDestroy(stream_));
        stream_ = nullptr;
      }
    }

    void sync()
    {
      CUDA_RUNTIME(cudaSetDevice(dev_));
      cudaDeviceSynchronize();
      //CUDA_RUNTIME(cudaGetLastError());
    }
    int device() const { return dev_; }
    cudaStream_t stream() const { return stream_; }
  };
}
