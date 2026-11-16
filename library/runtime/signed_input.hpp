#pragma once
#include "family_util.hpp"

namespace graphmine::runtime {
struct SignedInputEdge { VertexIndex u, v; bool negative; Exact weight; };
using SignedInput = std::map<std::pair<VertexIndex,VertexIndex>,SignedInputEdge>;
SignedInput signed_input(const Graph&, bool weighted, Work&);
}
