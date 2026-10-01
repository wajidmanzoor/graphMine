#pragma once
#include "context_gpu.cuh"
#include "graph_gpu.cuh"
#include "mce_gpu.cuh"

#ifndef TASK_SHARE_BOUND
  #define TASK_SHARE_BOUND 24
#endif

// 1. User defined vertex
#define bitvec_t uint64_t


// 2. User defined enumeration tree node
struct MetadataMultiGPU
{
  bitvec_t* bitmap_base;
  size_t p_size, x_size;
  bitvec_t* rpv_base;
  int32_t task_count;
  int32_t pending_count;
};

// 3. User defined context manager
class ContextManagerBkpbMultiGPU : public ContextManager
{
public:
  // BufferManager bitmaps_;
  // BufferManager rpxv_;
  BufferManager buffers_;
  BufferManager metas_;

  vid_t *current_id;
  vid_t *active_warps_;
  // vid_t *debug_val;
};

// 4. User defined kernel function


__device__ void SetTaskByIdMultiGPU(bitvec_t *bitmap_base, size_t p_size, bitvec_t* rpv_src, bitvec_t* rpv_dst, int remain_bits){
    
  size_t sizeOfItem = round_up(p_size, sizeof(bitvec_t) * 8) / sizeof(bitvec_t) / 8;

  size_t p_id;
  for(int i = 0; i < sizeOfItem; i++){
    rpv_dst[i] = rpv_src[i];
    rpv_dst[i + sizeOfItem] = rpv_src[i + sizeOfItem] & ~rpv_src[i + 2 * sizeOfItem];
  }
  
  for(int i = sizeOfItem - 1; i >= 0 && remain_bits > 0; i--){
    bitvec_t vec = rpv_src[i + 2 * sizeOfItem];
    if(__popcll(vec) < remain_bits){
      remain_bits -= __popcll(vec);
      rpv_dst[i + sizeOfItem] |= vec;
    }
    else {
      while(__popcll(vec) > remain_bits){
        vec = vec - (vec & -vec);
      }
      remain_bits = 0;
      rpv_dst[i] |= (vec & -vec);
      rpv_dst[i + sizeOfItem] |= vec;
      p_id = __ffsll(vec) - 1 + i * sizeof(bitvec_t) * 8;    
    }
  }
  
  for(int i = 0; i < sizeOfItem; i++){
    rpv_dst[i + sizeOfItem] = rpv_dst[i + sizeOfItem] & bitmap_base[p_id * sizeOfItem + i];
  }
}

__device__ acc_t IterKernelAutoMultiGPU(ContextManagerBkpbMultiGPU& context, bitvec_t* bitmap_base, size_t p_size, size_t x_size){
  const size_t warp_id = (blockIdx.x * blockDim.x + threadIdx.x) / warpSize;
  bitvec_t* rpv = (bitvec_t *)context.buffers_.GetElement(warp_id);
  MetadataMultiGPU* meta = (MetadataMultiGPU *)context.metas_.GetElement(warp_id);
  acc_t mc_local = 0;
  int level = 0, level_sharing = -1, level_to_share = -1;
  size_t sizeOfItem = round_up(p_size, sizeof(bitvec_t) * 8) / sizeof(bitvec_t) / 8;
  const size_t itemPerVec = sizeof(bitvec_t) * 8;
  if(get_lane_id() == 0){
    meta->task_count = 0;
    meta->pending_count = 0;
  }
  bool has_task = true;
  while (true)
  {
    if(level_sharing < level_to_share) {
      if(get_lane_id() == 0){ // share workload
        auto pending_count = meta->pending_count;
        if(pending_count == 0){
          level_sharing ++;
          bitvec_t* pp_base = rpv + (3 * level_sharing + 1) * sizeOfItem;
          bitvec_t* vpp_base = rpv + (3 * level_sharing + 2) * sizeOfItem;
          int task_count = 0;
          for(int i = 0; i < sizeOfItem; i++)
            task_count += __popcll(pp_base[i] & vpp_base[i]);
          if(task_count > 0){
            meta->bitmap_base = bitmap_base;
            meta->p_size = p_size;
            meta->x_size = x_size;
            meta->rpv_base = rpv + (3 * level_sharing) * sizeOfItem;
            meta->pending_count = task_count;
            __threadfence();
            meta->task_count = task_count;
            // atomicAdd(context.debug_val, task_count);
            // printf("Set: %d %d\n", task_count, task_count);
          }  
        }
      }
      level_sharing = __shfl_sync(FULL_MASK, level_sharing, 0);
    }

    if(!has_task){
      if(meta->pending_count == 0)
        break;
      else { 
        if(get_lane_id() == 0){
          auto task_count = meta->task_count;
          if(task_count > 0){
            auto old_value = atomicCAS(&meta->task_count, task_count, task_count - 1);
            if(old_value == task_count){
              SetTaskByIdMultiGPU(meta->bitmap_base, meta->p_size, meta->rpv_base, rpv + 3 * sizeOfItem * (level_sharing + 1), task_count); 
              __threadfence();
              auto pending_count = atomicSub(&meta->pending_count, 1);
              //  printf("Acquire: %d %d\n", task_count - 1, pending_count - 1);
              level = level_sharing + 1;
              has_task = true;
            }
          }
        } 
          
        has_task = __shfl_sync(FULL_MASK, has_task, 0);
        if(!has_task){
          cuda_sleep();
          continue;
        }
      }
    }

    // find p
    // bitvec_t *rr_base = rpv + (3 * level) * sizeOfItem;
    // bitvec_t *pp_base = rpv + (3 * level + 1) * sizeOfItem;

    // vid_t pivot_id = 0;
    // size_t pid = INF;

    // size_t min_non_neighbor_p = INF;


    // for(int i = get_lane_id(); i < p_size + x_size; i += warpSize){
    //   size_t non_neighbor_p = 0;
    //   bool is_p_or_x = true;
    //   for(int j = 0; j < sizeOfItem && is_p_or_x; j++){
    //     if(rr_base[j] & ~bitmap_base[i * sizeOfItem + j])
    //       is_p_or_x = false;
    //     non_neighbor_p += __popcll(pp_base[j] & ~bitmap_base[i * sizeOfItem + j]);
    //   }
    //   if(is_p_or_x && non_neighbor_p < min_non_neighbor_p){
    //     min_non_neighbor_p = non_neighbor_p;
    //     pivot_id = i;
    //   }
    // }
    // size_t mnnp = warp_min(min_non_neighbor_p);
    // mnnp = __shfl_sync(FULL_MASK, mnnp, 0);
    
    // if(mnnp == INF) // is maximal 
    //   mc_local ++;
    // else if(mnnp > 0){
    //   size_t cur_p_size = 0;
    //   unsigned match_mask = __ballot_sync(FULL_MASK, mnnp == min_non_neighbor_p);
    //   pivot_id = __shfl_sync(FULL_MASK, pivot_id, __ffs(match_mask) - 1);
    //   if (get_lane_id() == 0)
    //   {
    //     bitvec_t *vpp_base = rpv + (3 * level + 2) * sizeOfItem;
    //     for (size_t i = 0; i < sizeOfItem; i++)
    //     {
    //       bitvec_t res = ~bitmap_base[pivot_id * sizeOfItem + i] & pp_base[i];
    //       if (pid == INF && res != (bitvec_t)0ULL)
    //         pid = i * itemPerVec + __ffsll(res) - 1;
    //       vpp_base[i] = res;
    //       cur_p_size += __popcll(pp_base[i]);
    //     }
    //   }
    //   pid = __shfl_sync(FULL_MASK, pid, 0);
    //   cur_p_size = __shfl_sync(FULL_MASK, cur_p_size, 0);

    //   if(pid != INF && cur_p_size >= TASK_SHARE_BOUND){
    //     level_to_share = level;
    //   }
    // }    
    
    bitvec_t *rr_base = rpv + (3 * level) * sizeOfItem;
    bitvec_t *pp_base = rpv + (3 * level + 1) * sizeOfItem;
    
    vid_t pivot_id = 0;
    size_t pid = INF;

    size_t cur_p_size = 0;
    if (get_lane_id() == 0)
    {
      for (size_t i = 0; i < sizeOfItem; i++)
        cur_p_size += __popcll(pp_base[i]);
    }
    cur_p_size = __shfl_sync(FULL_MASK, cur_p_size, 0);
    size_t min_non_neighbor_p = INF;


    // if (cur_p_size != 0){
    //   for(int i = get_lane_id(); i < p_size; i += warpSize){
    //     int pos = i / sizeof(bitvec_t) / 8;
    //     int offset = i % (sizeof(bitvec_t) * 8);
    //     bool is_p = i < p_size && ((pp_base[pos] & ((bitvec_t)1ULL << offset)) != 0ULL);

    //     size_t non_neighbor_p = 0;
    //     for (int j=0; is_p && j<sizeOfItem; j++)
    //       non_neighbor_p += __popcll(pp_base[j] & ~bitmap_base[i * sizeOfItem + j]);
    //     unsigned mask = __ballot_sync(__activemask(), non_neighbor_p == 1);
    //     if(get_lane_id() == 0 && mask != 0){
    //       bitvec_t new_r = (bitvec_t)mask << (i % (sizeof(bitvec_t) * 8));
    //       rr_base[i / sizeof(bitvec_t) / 8] |= new_r;
    //       pp_base[i / sizeof(bitvec_t) / 8] &= ~new_r;
    //       cur_p_size -= __popcll(new_r);
    //     }
    //   }
    //   cur_p_size = __shfl_sync(FULL_MASK, cur_p_size, 0);
    // }


    if (cur_p_size != 0)
    {
      for (int i = get_lane_id(); i < p_size + x_size && min_non_neighbor_p != 0; i += warpSize)
      {
        size_t non_neighbor_p = 0;
        bool is_p_or_x = true;
        for (int j = 0; j < sizeOfItem; j++)
        {
          if (rr_base[j] & ~bitmap_base[i * sizeOfItem + j])
          {
            is_p_or_x = false;
            break;
          }
          non_neighbor_p += __popcll(pp_base[j] & ~bitmap_base[i * sizeOfItem + j]);
        }
        if (is_p_or_x && non_neighbor_p < min_non_neighbor_p)
        {
          min_non_neighbor_p = non_neighbor_p;
          pivot_id = i;
        }
      }

      size_t mnnp = warp_min(min_non_neighbor_p);
      mnnp = __shfl_sync(FULL_MASK, mnnp, 0);

      if (mnnp > 0)
      {
        unsigned match_mask = __ballot_sync(FULL_MASK, mnnp == min_non_neighbor_p);
        pivot_id = __shfl_sync(FULL_MASK, pivot_id, __ffs(match_mask) - 1);
        if (get_lane_id() == 0)
        {
          bitvec_t *vpp_base = rpv + (3 * level + 2) * sizeOfItem;
          for (size_t i = 0; i < sizeOfItem; i++)
          {
            bitvec_t res = ~bitmap_base[pivot_id * sizeOfItem + i] & pp_base[i];
            if (pid == INF && res != (bitvec_t)0ULL)
              pid = i * itemPerVec + __ffsll(res) - 1;
            vpp_base[i] = res;
          }
        }
        pid = __shfl_sync(FULL_MASK, pid, 0);

        if(pid != INF && cur_p_size >= TASK_SHARE_BOUND){
          level_to_share = level;
        }
      }
    } 
    else
    {
      for(int i = get_lane_id(); i < p_size + x_size && min_non_neighbor_p != 0; i += warpSize){
        bool is_p_or_x = true;
        for (int j = 0; j < sizeOfItem; j++)
        {
          if (rr_base[j] & ~bitmap_base[i * sizeOfItem + j])
          {
            is_p_or_x = false;
            break;
          }
        }
        if(is_p_or_x)
          min_non_neighbor_p = 0;
      }
      bool is_maximal = __all_sync(FULL_MASK, min_non_neighbor_p == INF);
      if(get_lane_id() == 0 && is_maximal)
        mc_local ++;


      // bool is_maximal = true;
      // for (int i = get_lane_id(); i < p_size + x_size && is_maximal; i += warpSize)
      // {
      //   bitvec_t vec = (bitvec_t)0ULL;
      //   for (int j = 0; j < sizeOfItem && vec == (bitvec_t)0ULL; j++)
      //   {
      //     vec |= (~bitmap_base[i * sizeOfItem + j] & rr_base[j]);
      //   }

      //   if (vec == (bitvec_t)0ULL)
      //   {
      //     is_maximal = false;
      //   }
      // }
      // is_maximal = __all_sync(FULL_MASK, is_maximal);
      // if (get_lane_id() == 0 && is_maximal)
      // {
      //   mc_local++;
      // }
    }
    
    
    if (pid == INF)
    {
      // find next node
      if (get_lane_id() == 0)
      {             
        while (level > (level_sharing + 1) && pid == INF)
        {
          level--;
          bitvec_t *pp_base = rpv + (3 * level + 1) * sizeOfItem;
          bitvec_t *vpp_base = rpv + (3 * level + 2) * sizeOfItem;
          for (size_t i = 0; i < sizeOfItem && pid == INF; i++)
          {
            bitvec_t res = vpp_base[i] & pp_base[i];
            if (res != (bitvec_t)0ULL)
              pid = i * itemPerVec + __ffsll(res) - 1;
          }
        }
      }

      pid = __shfl_sync(FULL_MASK, pid, 0);
      level = __shfl_sync(FULL_MASK, level, 0);
      level_to_share = min(level_to_share, level - 1);


      if (pid == INF)
      {
        has_task = false;
        continue;
      }
    }

    // generate new node
    level++;
#ifdef EXPAND_R
    rr_base = rpv + (3 * level - 3) * sizeOfItem;
    pp_base = rpv + (3 * level - 2) * sizeOfItem;
    bitvec_t *rr_next_base = rr_base + 3 * sizeOfItem;
    bitvec_t *pp_next_base = pp_base + 3 * sizeOfItem;
    if(get_lane_id() == 0){
      cur_p_size = 0;
      pp_base[pid / itemPerVec] &= ~((bitvec_t)1ULL << (pid % itemPerVec));
      for (int i = 0; i < sizeOfItem; i++){
        rr_next_base[i] = rr_base[i];
        pp_next_base[i] = pp_base[i] & bitmap_base[pid * sizeOfItem + i];
        cur_p_size += __popcll(pp_next_base[i]);
      }
      rr_next_base[pid / itemPerVec] |= (bitvec_t)1ULL << (pid % itemPerVec);
     
    }
    cur_p_size = __shfl_sync(FULL_MASK, cur_p_size, 0);
    for(int i = get_lane_id(); i < p_size && cur_p_size > 1; i += warpSize){
      int pos = i / sizeof(bitvec_t) / 8;
      int offset = i % (sizeof(bitvec_t) * 8);
      bool is_p = (pp_next_base[pos] & ((bitvec_t)1ULL << offset)) != 0ULL;

      size_t non_neighbor_p = 0;
      for (int j=0; is_p && j<sizeOfItem; j++)
        non_neighbor_p += __popcll(pp_next_base[j] & ~bitmap_base[i * sizeOfItem + j]);
      unsigned mask = __ballot_sync(__activemask(), non_neighbor_p == 1);
      if(get_lane_id() == 0 && mask != 0){
        bitvec_t new_r = (bitvec_t)mask << (i % (sizeof(bitvec_t) * 8));
        rr_next_base[i / sizeof(bitvec_t) / 8] |= new_r;
        pp_next_base[i / sizeof(bitvec_t) / 8] &= ~new_r;
      }
    }
#else
    // no prune
    if (get_lane_id() == 0)
    {
      bitvec_t *rr_base = rpv + (3 * level - 3) * sizeOfItem;
      bitvec_t *pp_base = rpv + (3 * level - 2) * sizeOfItem;
      bitvec_t *rr_next_base = rr_base + 3 * sizeOfItem;
      bitvec_t *pp_next_base = pp_base + 3 * sizeOfItem;

      pp_base[pid / itemPerVec] &= ~((bitvec_t)1ULL << (pid % itemPerVec));
      for (int i = 0; i < sizeOfItem; i++)
      {
        rr_next_base[i] = rr_base[i];
        pp_next_base[i] = pp_base[i] & bitmap_base[pid * sizeOfItem + i];
      }
      rr_next_base[pid / itemPerVec] |= (bitvec_t)1ULL << (pid % itemPerVec);
    }
#endif  
  }
  return mc_local;
}

__device__ bool GetTaskFromGlobalIdMultiGPU(GraphGpu& graph, ContextManagerBkpbMultiGPU& context, size_t &p_size, size_t &x_size, bitvec_t*& bitmap_base){
  const size_t warp_id = (blockIdx.x * blockDim.x + threadIdx.x) / warpSize;

  size_t lane_id = get_lane_id();
  vid_t cur_id;
  if(lane_id == 0)
    cur_id = atomicAdd_system(context.current_id, 1);
  cur_id = __shfl_sync(FULL_MASK, cur_id, 0);
  vid_t *p_base, *x_base;
#ifndef LEVEL_2
  if(cur_id >= graph.GetNumVertices())
    return false;

  cur_id = graph.GetNumVertices() - cur_id - 1;
  vid_t *Nv;
  size_t Nv_size;
  graph.GetNeighbors(cur_id, Nv, Nv_size);
  if(lane_id == 0)
    x_size = binary_search_first_greater(cur_id, Nv, Nv_size);
  x_size = __shfl_sync(FULL_MASK, x_size, 0);
  x_base = Nv;
  p_size = Nv_size - x_size;
  p_base = Nv + x_size;
#else
  if(cur_id >= graph.GetNumEdges() * 2)
    return false;
  cur_id = graph.GetNumEdges() * 2 - cur_id - 1;
  // if(lane_id == 0 && cur_id % 100000000 == 0)
  //   printf("cur_id: %d\n", cur_id);
  vid_t *Nv0, *Nv1;
  vid_t v0, v1;
  size_t Nv0_size, Nv1_size;
  size_t Nv_size = 0;
  graph.GetEdge(cur_id, v0, v1);
  if(v0 > v1){
    p_size = 0;
    x_size = 1;
    return true;
  }
  graph.GetNeighbors(v0, Nv0, Nv0_size);
  graph.GetNeighbors(v1, Nv1, Nv1_size);

  vid_t *rpx_base = (vid_t *)context.buffers_.GetElement(warp_id);

  for (size_t v0_idx = lane_id; v0_idx < Nv0_size; v0_idx += warpSize){
    vid_t nv0 = Nv0[v0_idx];
    size_t pos = binary_search(nv0, Nv1, Nv1_size);
    size_t match_mask = __ballot_sync(__activemask(), pos!= INF);
    if (pos!= INF){
      size_t offset = count_bit(match_mask) - 1 - count_bit((match_mask >> lane_id) - 1);
      size_t pos = Nv_size + offset;
      rpx_base[pos] = nv0;
    }
    Nv_size += __popc(match_mask);
  }
  Nv_size = __shfl_sync(FULL_MASK, Nv_size, 0);

  if (lane_id == 0)
  {
    x_size = binary_search_first_greater(v1, rpx_base, Nv_size);
  }
  x_size = __shfl_sync(FULL_MASK, x_size, 0);
  x_base = rpx_base;
  p_size = Nv_size - x_size;
  p_base = rpx_base + x_size;
#endif



if (p_size > 0){
    size_t sizeOfItem = round_up(p_size, sizeof(bitvec_t) * 8) / sizeof(bitvec_t) / 8;
    size_t bitmap_size = (p_size + x_size) * round_up(p_size, sizeof(bitvec_t) * 8) / 8;

    // assert((x_size + p_size) * sizeof(vid_t) + bitmap_size < context.buffers_.GetElementSize());

    if((x_size + p_size) * sizeof(vid_t) + bitmap_size >= context.buffers_.GetElementSize()){      
      if(get_lane_id() == 0){
        printf("x_size: %lu, p_size: %lu\n", x_size, p_size);
      }
      
      x_size = 1;
      p_size = 0;
      return true;
    } else
      bitmap_base = (bitvec_t *)context.buffers_.GetElementRearPtr(warp_id, bitmap_size);    

    BuildBitmap(graph, bitmap_base, p_base, p_size, x_base, x_size);

    if(get_lane_id() == 0){
      bitvec_t *rpv_vec_base = (bitvec_t *)context.buffers_.GetElement(warp_id);
      const size_t itemPerVec = sizeof(bitvec_t) * 8;
      for (int i = 0; i < sizeOfItem; i++)
      {
        rpv_vec_base[i] = (bitvec_t)0ULL;
        if (i != sizeOfItem - 1 || p_size % itemPerVec == 0)
          rpv_vec_base[sizeOfItem + i] = rpv_vec_base[sizeOfItem * 2 + i] = (bitvec_t)~0ULL;
        else
          rpv_vec_base[sizeOfItem + i] = rpv_vec_base[sizeOfItem * 2 + i] = (bitvec_t)~0ULL >> (itemPerVec - p_size % itemPerVec);
      }
    }
  }

  return true; 
}

__launch_bounds__(32 * WARP_PER_BLOCK, 1)
    __global__ void BkpbKernelM(GraphGpu graph, ContextManagerBkpbMultiGPU context)
{
  acc_t mc_local = 0;
  const size_t warp_id = (blockIdx.x * blockDim.x + threadIdx.x) / warpSize;
  const size_t num_warps = gridDim.x * blockDim.x / warpSize;
  size_t lane_id = get_lane_id();

  vid_t *rpx_base = (vid_t *)context.buffers_.GetElement(warp_id);
  MetadataMultiGPU *meta_base = (MetadataMultiGPU *)context.metas_.GetElement(warp_id);
  bitvec_t *bitmap_base; // = (bitvec_t *)context.bitmaps_.GetElement(warp_id);
  bitvec_t *rpv_vec_base = (bitvec_t *)context.buffers_.GetElement(warp_id);
  size_t p_size, x_size;

  uint64_t start_time = clock64();
  if (lane_id == 0){
    atomicAdd(context.active_warps_, 1);
    meta_base->pending_count = 0;
    __threadfence();
  }
  // stage 1
  while (true)
  {
    if(!GetTaskFromGlobalIdMultiGPU(graph, context, p_size, x_size, bitmap_base))
      break;
    if (p_size == 0)
    {
      if (x_size == 0 && lane_id == 0)
        mc_local++;
    }
    else
      mc_local += IterKernelAutoMultiGPU(context, bitmap_base, p_size, x_size);
  } 

  if (lane_id == 0){
    auto num = atomicSub(context.active_warps_, 1);
    //printf("active warp rate: %lf | active warps: %lu\n", (double)num / num_warps, num);
  }

  // stage 2
  vid_t cur_warp_id = warp_id;

  while (true){
    cur_warp_id = (cur_warp_id + 1) % num_warps;
    MetadataMultiGPU* meta = (MetadataMultiGPU*)context.metas_.GetElement(cur_warp_id);
    bool has_task = false;
    if(lane_id == 0){
      auto task_count = meta->task_count;
      if(task_count != 0){
        auto old_value = atomicCAS(&meta->task_count, task_count, task_count - 1);
        if(old_value == task_count){ // get a task
          has_task = true;
          SetTaskByIdMultiGPU(meta->bitmap_base, meta->p_size, meta->rpv_base, rpv_vec_base, task_count);
          bitmap_base = meta->bitmap_base;
          p_size = meta->p_size;
          x_size = meta->x_size;        
          __threadfence();
          atomicSub(&meta->pending_count, 1);
          atomicAdd(context.active_warps_, 1);
        }
      }
    }
    has_task = __shfl_sync(FULL_MASK, has_task, 0);
    if(has_task){
      p_size = __shfl_sync(FULL_MASK, p_size, 0);
      x_size = __shfl_sync(FULL_MASK, x_size, 0);
      bitmap_base = (bitvec_t *) __shfl_sync(FULL_MASK, (uint64_t)bitmap_base, 0);
      mc_local += IterKernelAutoMultiGPU(context, bitmap_base, p_size, x_size);
      if(lane_id == 0){
        auto num = atomicSub(context.active_warps_, 1);
        // cuda_sleep();
        // printf("active warp rate: %lf | active warps: %lu\n", (double)num / num_warps, num);
      }
      cur_warp_id--;
    }
    else
      cuda_sleep();
    
    bool exit_flag;
    if(lane_id == 0){
      
      __threadfence();
      // printf("%d " ,*context.active_warps_);
      exit_flag = *context.active_warps_ == 0;
    }
    exit_flag = __shfl_sync(FULL_MASK, exit_flag, 0);
    if(exit_flag)
      break;
  }


  if (lane_id == 0 && mc_local != 0)
  {
    acc_t res = atomicAdd_system((unsigned long long *)context.mc_num_, mc_local);
    // printf("mc_num: %llu\n", res);
  }
  // if(threadIdx.x == 0 && blockIdx.x == 0)
  //   printf("total shared tasks size: %d\n", *context.debug_val);
}

// 5. User defined solver wrapper
void BkSolverWrapperMultiGPU(Graph &graph, size_t device_id, vid_t *cur_id, acc_t *mc_num)
{
  
  cudaDeviceProp prop;
  cudaGetDeviceProperties(&prop, device_id);
  size_t sm_num = prop.multiProcessorCount;
  // printf("\033[90m[GPU] SM: %lu  \tWARP_PER_BLOCK: %d\tBLOCK_PER_SM: %d\033[0m\n", sm_num, WARP_PER_BLOCK, BLOCK_PER_SM);
  // printf("\033[90m[GPU] TASK_SHARE_BOUND: %d\033[0m\n", TASK_SHARE_BOUND);

  GraphGpu graph_gpu;
  ContextManagerBkpbMultiGPU context_gpu;

  graph_gpu.LoadFromCpu(graph, false);

  size_t num_warps = WARP_PER_SM * sm_num;
  size_t bitvec_size = round_up(graph.GetDegeneracy(), 8 * sizeof(bitvec_t)) / 8;

  size_t bitmap_size = round_up(graph.GetMaxDegree() * (bitvec_size + 2 * sizeof(vid_t)), 8);
  size_t rpxv_size = graph.GetDegeneracy() * bitvec_size * 3;

  size_t free_byte;
  size_t total_byte;
  CUDA_CHECK(cudaMemGetInfo(&free_byte, &total_byte));
  context_gpu.metas_.Allocate(num_warps, sizeof(MetadataMultiGPU));

  size_t max_available_size = round_up((size_t) (free_byte * 0.95 / num_warps), 8);
  size_t max_usage = bitmap_size + rpxv_size;
  size_t total_size = min(max_usage, max_available_size);

  // printf("\033[90m[GPU] Context memory usage: %lf MB\033[0m\n", total_size * num_warps / 1024.0 / 1024.0);
  // printf("      \033[90m- Bitmap: %lf MB\n", (total_size - rpxv_size) * num_warps / 1024.0 / 1024.0);
  // printf("      - Rpx buffer: %lf MB\033[0m\n", rpxv_size * num_warps / 1024.0 / 1024.0);

  if(max_usage < max_available_size)
    context_gpu.buffers_.Allocate(num_warps, max_usage);
  else{
    // printf("\033[90m[GPU] Context memory usage exceeds 95%% of available memory on GPUs, using unified memory instead\033[0m\n");
    context_gpu.buffers_.AllocateManaged(num_warps, max_usage);
  }

  context_gpu.mc_num_ = mc_num;
  context_gpu.current_id = cur_id;
  // CUDA_CHECK(cudaMalloc((void **)&context_gpu.mc_num_, sizeof(acc_t)));
  // CUDA_CHECK(cudaMemset(context_gpu.mc_num_, 0, sizeof(acc_t)));
  // CUDA_CHECK(cudaMalloc((void **)&context_gpu.current_id, sizeof(vid_t)));
  // CUDA_CHECK(cudaMemset(context_gpu.current_id, 0, sizeof(vid_t)));
  CUDA_CHECK(cudaMalloc((void **)&context_gpu.active_warps_, sizeof(vid_t)));
  CUDA_CHECK(cudaMemset(context_gpu.active_warps_, 0, sizeof(vid_t)));

  // CUDA_CHECK(cudaMalloc((void **)&context_gpu.debug_val, sizeof(vid_t)));
  // CUDA_CHECK(cudaMemset(context_gpu.debug_val, 0, sizeof(vid_t))); 

  BkpbKernelM<<<sm_num * BLOCK_PER_SM, 32 * WARP_PER_BLOCK>>>(graph_gpu, context_gpu);
  // BkpbKernelM<<<1, 32>>>(graph_gpu, context_gpu);

  CUDA_CHECK(cudaDeviceSynchronize());
  // auto mc_num = context_gpu.GetMcNum();
  // free memory
  graph_gpu.Free();
  // context_gpu.bitmaps_.Free();
  // context_gpu.rpxv_.Free();
  context_gpu.buffers_.Free();
  context_gpu.metas_.Free();

  // CUDA_CHECK(cudaFree(context_gpu.mc_num_));
  // CUDA_CHECK(cudaFree(context_gpu.current_id));
  CUDA_CHECK(cudaFree(context_gpu.active_warps_));
  // CUDA_CHECK(cudaFree(context_gpu.debug_val));
  // return mc_num;
}