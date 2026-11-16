#pragma once
#include "structured_input.hpp"

namespace graphmine::runtime {
inline HypergraphInput hypergraph_view_input(const json::value& input, const ViewProfile& profile, Work& work) {
  // Structured validation, budgets and typed vertex attributes are common front.
  HypergraphInput result(input,work);
  const auto built = consume_view(input,profile,work);
  const auto& view = std::get<HypergraphView>(built->view);
  result.ids = view.vertices.external_ids;
  result.indices.clear();
  for (VertexIndex v=0; v<result.ids.size(); ++v) result.indices.emplace(result.ids[v],v);
  auto exact = [](const RationalWeight& value) -> Exact { return Exact(Integer(value.numerator))/Integer(value.denominator); };
  result.weights.clear();
  for (const auto& value : std::get<std::vector<RationalWeight>>(view.vertex_weights)) result.weights.push_back(exact(value));
  result.edges.clear();
  const auto& weights = std::get<std::vector<RationalWeight>>(view.hyperedge_weights);
  for (std::size_t e=0; e<view.hyperedge_ids.size(); ++e)
    result.edges.push_back({view.hyperedge_ids[e],
      {view.he_vertices.begin()+view.he_offsets[e],view.he_vertices.begin()+view.he_offsets[e+1]},exact(weights[e])});
  return result;
}
}
