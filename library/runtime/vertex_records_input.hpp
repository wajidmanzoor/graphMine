#pragma once
#include "pattern_match.hpp"

namespace graphmine::runtime {
inline std::vector<json::object> vertex_records_input(const Graph& graph,
    const ViewProfile& profile, Work& work) {
  const auto input = consume_view(graph,profile,work,ViewBudget::algorithm_owned);
  const auto& view = std::get<CooView>(input->view);
  std::vector<json::object> records;
  for (const auto original : view.vertices.to_original)
    records.push_back(vertex_record_json(graph.canonical().vertices.at(original),work));
  return records;
}
}
