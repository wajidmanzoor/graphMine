#pragma once
#include "edge_set_input.hpp"

namespace graphmine::runtime {
std::set<std::pair<ExternalId,ExternalId>> dynamic_triangle_edges(const Graph&, Work&);
}
