#pragma once
#include "view_profiles.hpp"

namespace graphmine::runtime {
struct SparsificationInput {
  struct Edge { VertexIndex u,v; double weight; std::size_t original; };
  std::vector<Edge> edges;
  MiningGraph adjacency;
};
SparsificationInput sparsification_input(const Graph&, Work&);
}
