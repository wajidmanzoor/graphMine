#pragma once

#include <memory>

#include "graphmine/views.hpp"
#include "internal.hpp"

namespace graphmine::runtime {
std::shared_ptr<const Graph> cached_graph(const json::value&, Work&);
WeightedGraph cached_weighted_graph(const std::string&, Work&,
                                    const std::function<WeightedGraph()>&);
std::shared_ptr<const ViewResult> cached_standard_view(
    const std::string& snapshot, const std::string& canonical_spec,
    const std::function<ViewResult()>& build);
json::object representation_cache_request(const json::object&);
}  // namespace graphmine::runtime
