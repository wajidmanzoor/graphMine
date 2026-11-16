#pragma once
#include "family_util.hpp"

namespace graphmine::runtime {
struct EnumerationInput {
  std::vector<std::vector<std::size_t>> adjacency;
  std::vector<Exact> times;
  std::vector<VertexIndex> ends;
};
EnumerationInput enumeration_input(const Graph&, bool preserve_parallel, bool chronological,
                                   std::optional<std::size_t> anchor, Work&);
}
