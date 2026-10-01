#pragma once
#include "common.cuh"

enum class OrderType
{
  UNCHANGED,
  ASC,
  DES,
  DEG
};

class Graph
{
protected:
  std::string name_;
  std::vector<vlist_t> V_;
  std::vector<vid_t> labels_;
  size_t num_vertices_ = 0;
  size_t num_edges_ = 0;
  size_t max_degree_ = 0;
  size_t degeneracy_ = 0;
  vid_t *rowoffset_cpu_ = nullptr;
  vid_t *colidx_cpu_ = nullptr;

  inline void ApplyOrder(const vlist_t &order);
  void SortByDegreeAsc();
  void SortByDegreeDes();
  void SortByDegeneracy();

public:
  Graph() = default;
  Graph(const Graph &other);
  Graph(Graph &&other);
  ~Graph();
  void LoadFromFile(const std::string &path);
  void StoreIntoBin(const std::string &path);
  void LoadFromBin(const std::string &path);
  void ConvertToCsr();

  inline const std::string &GetName() const { return name_; }
  inline size_t GetNumVertices() const { return num_vertices_; }
  inline size_t GetNumEdges() const { return num_edges_; }
  inline size_t GetMaxDegree() const { return max_degree_; }
  inline size_t GetDegeneracy() const { return degeneracy_; }
  inline vid_t* GetRowOffset() { return rowoffset_cpu_; }
  inline vid_t* GetColIdx() { return colidx_cpu_; }
  inline const vlist_t &N(vid_t v) const { return V_[v]; }

  void SortByOrder(OrderType order);

  friend std::ostream &operator<<(std::ostream &os, const Graph &graph);
};
