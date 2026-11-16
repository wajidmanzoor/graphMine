#pragma once
#include <set>
#include "view_profiles.hpp"

namespace graphmine::runtime {
inline std::set<std::pair<VertexIndex,VertexIndex>> edge_set_input(
    const Graph& graph, const ViewProfile& profile, Work& work) {
  const auto input = consume_view(graph,profile,work,ViewBudget::record_edges);
  const auto& view = std::get<CooView>(input->view);
  std::set<std::pair<VertexIndex,VertexIndex>> result;
  for (std::size_t i=0; i<view.src.size(); ++i) {
    if (view.symmetric && view.src[i] > view.dst[i]) continue;
    result.emplace(view.src[i],view.dst[i]);
  }
  return result;
}
}
