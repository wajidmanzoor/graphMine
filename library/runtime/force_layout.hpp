#pragma once
#include "numeric.hpp"

namespace graphmine::runtime {
struct ForceLayoutInput {
  numeric::Matrix weights, positions;
};
// Dense allocation guards precede input validation, as in the original adapter.
ForceLayoutInput force_layout_input(const Graph&, bool weighted, std::size_t dimensions, Work&);
}
