#pragma once
#include "family_util.hpp"

namespace graphmine::runtime {
struct MatchingEdge { VertexIndex u, v; std::size_t original; Exact value; };
using MatchingEdges = std::vector<MatchingEdge>;
MatchingEdges general_matching_edges(const Graph&, Work&);
}
