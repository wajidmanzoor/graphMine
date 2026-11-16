#pragma once
#include "family_util.hpp"

namespace graphmine::runtime {
using WalkAdjacency = std::vector<std::map<VertexIndex,Exact>>;
WalkAdjacency walk_adjacency(const Graph&, bool uniform, Work&);
}
