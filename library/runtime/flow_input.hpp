#pragma once
#include "family_util.hpp"

namespace graphmine::runtime {
struct FlowInput {
  struct Original { std::size_t edge; Exact capacity; };
  struct Arc { Exact capacity = 0; std::vector<Original> originals; std::size_t position = 0; };
  struct Loop { std::size_t edge; VertexIndex vertex; Exact capacity; };
  std::map<std::pair<VertexIndex,VertexIndex>,Arc> arcs;
  std::vector<Loop> loops;
  Exact capacity_sum = 0;
};
FlowInput flow_input(const Graph&, bool unit, Work&);
}
