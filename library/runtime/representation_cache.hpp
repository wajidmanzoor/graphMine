#pragma once

#include <memory>

#include "internal.hpp"

namespace graphmine::runtime {
std::shared_ptr<const Graph> cached_graph(const json::value&, Work&);
WeightedGraph cached_weighted_graph(const std::string&, Work&,
                                    const std::function<WeightedGraph()>&);
json::object representation_cache_request(const json::object&);
}  // namespace graphmine::runtime
