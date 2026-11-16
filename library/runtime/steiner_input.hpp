#pragma once
#include "family_util.hpp"

namespace graphmine::runtime {
std::vector<family_util::Edge> group_steiner_edges(const Graph&, Work&);
}
