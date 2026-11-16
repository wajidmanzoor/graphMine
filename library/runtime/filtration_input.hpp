#pragma once
#include "family_util.hpp"

namespace graphmine::runtime {
using FiltrationWeights = std::map<std::pair<VertexIndex,VertexIndex>,Exact>;
FiltrationWeights filtration_input(const Graph&, Work&);
}
