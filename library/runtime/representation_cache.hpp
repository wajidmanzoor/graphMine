#pragma once

#include <memory>

#include "graphmine/views.hpp"
#include "internal.hpp"

namespace graphmine::runtime {
std::shared_ptr<const Graph> cached_graph(const json::value&, Work&);
json::object representation_cache_request(const json::object&);
}  // namespace graphmine::runtime
