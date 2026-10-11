#include <type_traits>

#include "exact_number.hpp"
#include "internal.hpp"

namespace graphmine::runtime {
json::value property_json(const PropertyValue& value, Work& work) {
  work.tick();
  return std::visit(
      [&](const auto& raw) -> json::value {
        using T = std::decay_t<decltype(raw)>;
        if constexpr (std::is_same_v<T, PropertyValue::Array>) {
          json::array result;
          for (const auto& item : raw) result.push_back(property_json(item, work));
          return result;
        } else if constexpr (std::is_same_v<T, PropertyValue::Object>) {
          json::object result;
          for (const auto& [key, item] : raw) result[key] = property_json(item, work);
          return result;
        } else
          return json::value(raw);
      },
      value.value());
}
namespace {
void properties(json::object& output, const Attributes& attributes, Work& work,
                bool present = false) {
  if (present || !attributes.empty())
    output["attributes"] = property_json(PropertyValue(attributes), work);
}
}  // namespace
json::object selected_graph(const Graph& graph, const std::vector<bool>& selected, Work& work) {
  const auto& data = graph.canonical();
  json::array vertices, edges;
  for (VertexIndex v = 0; v < selected.size(); ++v)
    if (selected[v]) {
      work.tick();
      const auto& record = data.vertices[v];
      json::object row{{"id", id_json(record.id)}};
      if (record.label) row["label"] = *record.label;
      if (record.type) row["type"] = *record.type;
      properties(row, record.attributes, work, record.attributes_present);
      vertices.push_back(row);
    }
  for (const auto& edge : data.edges) {
    work.tick();
    if (!selected[graph.dense_index(edge.source)] || !selected[graph.dense_index(edge.target)])
      continue;
    json::object row{{"id", id_json(edge.id)},
                     {"source", id_json(edge.source)},
                     {"target", id_json(edge.target)}};
    if (edge.original_weight)
      row["weight"] =
          std::visit([](const auto& value) { return json::value(value); }, *edge.original_weight);
    else if (edge.weight)
      row["weight"] = display_number(Exact(*edge.weight));
    if (edge.timestamp)
      row["timestamp"] =
          std::visit([](const auto& value) { return json::value(value); }, *edge.timestamp);
    if (edge.type) row["type"] = *edge.type;
    properties(row, edge.attributes, work, edge.attributes_present);
    edges.push_back(row);
    work.output(vertices.size() + edges.size());
  }
  work.output(vertices.size() + edges.size());
  json::object metadata{{"id", data.graph.id},
                        {"directed", data.graph.directed},
                        {"allows_self_loops", data.graph.allows_self_loops},
                        {"allows_parallel_edges", data.graph.allows_parallel_edges}};
  properties(metadata, data.graph.attributes, work, data.graph.attributes_present);
  return {{"graph", metadata}, {"vertices", vertices}, {"edges", edges}};
}
}  // namespace graphmine::runtime
