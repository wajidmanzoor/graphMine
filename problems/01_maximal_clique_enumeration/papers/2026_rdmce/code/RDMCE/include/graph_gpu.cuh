#pragma once
#include "common.cuh"
#include "graph.h"

class GraphGpu
{
protected:
  vid_t *rowoffset_;
  vid_t *colidx_;
  // vid_t *rowidx_; // only used for COO format
  size_t num_vertices_;
  size_t num_edges_;
  size_t max_degree_;
  int device_id_;

public:
  GraphGpu() : rowoffset_(nullptr), colidx_(nullptr),
               num_vertices_(0), num_edges_(0), max_degree_(0), device_id_(0) {}
  ~GraphGpu() {}

  __forceinline__ __device__ size_t GetNumVertices() const { return num_vertices_; }

  __forceinline__ __device__ size_t GetNumEdges() const { return num_edges_; }

  __forceinline__ __device__ size_t GetMaxDegree() const { return max_degree_; }

  __forceinline__ __device__ int GetDeviceId() const { return device_id_; }

  __forceinline__ __device__ vid_t *GetColIdx() const { return colidx_; }

  // __forceinline__ __device__ vid_t* GetRowIdx() const { return rowidx_; }

  __forceinline__ __device__ vid_t *GetRowOffset() const { return rowoffset_; }

  __forceinline__ __device__ size_t VertexDegree(vid_t v) const { return rowoffset_[v + 1] - rowoffset_[v]; }

  __forceinline__ __device__ size_t VertexOffset(vid_t v) const { return rowoffset_[v]; }

  __forceinline__ __device__ void GetNeighbors(vid_t v_id, vid_t *&neighbors_ptr, size_t &neighbors_size) const
  {
    neighbors_ptr = colidx_ + rowoffset_[v_id];
    neighbors_size = rowoffset_[v_id + 1] - rowoffset_[v_id];
  }

  __forceinline__ __device__ void GetEdge(vid_t e_id, vid_t &v0, vid_t &v1) const
  {
    v0 = binary_search_last_not_greater(e_id, rowoffset_, num_vertices_);
    v1 = colidx_[e_id];
  }

  __host__ void SortByDegeneracy();

  __host__ void LoadFromCpu(Graph &graph, bool print = true);

  __host__ void Free();

};

template <typename T = uint64_t>
__forceinline__ __device__ void BuildBitmap(GraphGpu &graph, T *bitmap_base, vid_t *p_base, size_t& p_size, vid_t *x_base, size_t& x_size)
{
  assert(bitmap_base != nullptr && p_base != nullptr && x_base != nullptr && p_size != 0);
  size_t sizeOfItem = (p_size + sizeof(T) * 8 - 1) / sizeof(T) / 8;

  // initialize
  for(size_t i = get_lane_id(); i < (p_size + x_size) * sizeOfItem; i += warpSize)
    bitmap_base[i] = 0ULL;  

  vid_t p0 = p_base[0];
  for(size_t idx = 0; idx < p_size; idx ++){
    vid_t vp = p_base[idx];
    vid_t *Nvp;
    size_t Nvp_size;
    graph.GetNeighbors(vp, Nvp, Nvp_size);
    
    bool cond = p_size + x_size < Nvp_size + 32;
    int bound = cond ? p_size + x_size : Nvp_size;
    for(size_t i = get_lane_id(); i < bound; i += warpSize){
      vid_t v = cond ? (i < p_size ? p_base[i] : x_base[i - p_size]) : Nvp[i];
      vid_t* Nv = cond ? Nvp : (Nvp[i] < p0 ? x_base : p_base);
      size_t Nv_size = cond ? Nvp_size : (Nvp[i] < p0 ? x_size : p_size);
      vid_t pos = binary_search(v, Nv, Nv_size);
      if(pos != INF){
        pos = cond? i : (Nvp[i] < p0 ? pos + p_size: pos);
        bitmap_base[pos * sizeOfItem + idx / (8 * sizeof(T))] |= 1ULL << (idx % (8 * sizeof(T)));
      }
    }
  }

  size_t new_x_size = 0;
  bitmap_base += p_size * sizeOfItem;
  for(size_t i = get_lane_id(); i < x_size; i += warpSize){
    bool valid = false;
    for(size_t j = 0; j < sizeOfItem && !valid; j++)
      if(bitmap_base[i * sizeOfItem + j]!= 0ULL)
        valid = true;
    uint32_t match_mask = __ballot_sync(__activemask(), valid);
    if(valid) {
      size_t offset = count_bit(match_mask) - 1 - count_bit((match_mask >> get_lane_id()) - 1);
      size_t pos = new_x_size + offset;
      for(size_t j = 0; j < sizeOfItem; j++)
        bitmap_base[pos * sizeOfItem + j] = bitmap_base[i * sizeOfItem + j];
    }
    new_x_size += count_bit(match_mask);
  }
  x_size = __shfl_sync(FULL_MASK, new_x_size, 0);
}


template <typename T = uint64_t>
__forceinline__ __device__ void BuildBitmapOld(GraphGpu &graph, T *bitmap_base, vid_t *p_base, size_t& p_size, vid_t *x_base, size_t& x_size)
{
  assert(bitmap_base != nullptr && p_base != nullptr && x_base != nullptr && p_size != 0);
  size_t sizeOfItem = (p_size + sizeof(T) * 8 - 1) / sizeof(T) / 8;

  for(size_t idx = 0; idx < p_size; idx ++){
    vid_t vp = p_base[idx];
    vid_t *Nvp;
    size_t Nvp_size;
    graph.GetNeighbors(vp, Nvp, Nvp_size);
    for(size_t i = get_lane_id(); i < p_size + x_size; i += warpSize){
      if(idx % (8 * sizeof(T)) == 0)
        bitmap_base[i * sizeOfItem + idx / (8 * sizeof(T))] = 0ULL;
      vid_t v = i < p_size? p_base[i] : x_base[i - p_size];
      if(binary_search(v, Nvp, Nvp_size) != INF)
        bitmap_base[i * sizeOfItem + idx / (8 * sizeof(T))] |= 1ULL << (idx % (8 * sizeof(T)));
    }
  }
  size_t new_x_size = 0;
  bitmap_base += p_size * sizeOfItem;
  for(size_t i = get_lane_id(); i < x_size; i += warpSize){
    bool valid = false;
    for(size_t j = 0; j < sizeOfItem && !valid; j++)
      if(bitmap_base[i * sizeOfItem + j]!= 0ULL)
        valid = true;
    uint32_t match_mask = __ballot_sync(__activemask(), valid);
    if(valid) {
      size_t offset = count_bit(match_mask) - 1 - count_bit((match_mask >> get_lane_id()) - 1);
      size_t pos = new_x_size + offset;
      for(size_t j = 0; j < sizeOfItem; j++)
        bitmap_base[pos * sizeOfItem + j] = bitmap_base[i * sizeOfItem + j];
    }
    new_x_size += count_bit(match_mask);
  }
  x_size = __shfl_sync(FULL_MASK, new_x_size, 0);
}
