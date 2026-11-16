#pragma once
#include "view_profiles.hpp"

namespace graphmine::runtime {
json::object selected_graph(const Graph&, const ViewProfile&, const std::vector<bool>&, Work&);
}
