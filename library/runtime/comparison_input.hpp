#pragma once
#include "family_util.hpp"

namespace graphmine::runtime {
using ComparisonPair = std::pair<VertexIndex,VertexIndex>;
struct ComparisonGraph {
  bool directed;
  json::object graph;
  std::vector<std::string> labels;
  struct Edge {
    VertexIndex u, v;
    json::object record;
    std::string label;
  };
  std::vector<Edge> edges;
  std::map<ComparisonPair, std::size_t> indices;
  ComparisonPair key(VertexIndex u, VertexIndex v) const {
    if (!directed && u > v) std::swap(u, v);
    return {u, v};
  }
  std::optional<std::size_t> edge(VertexIndex u, VertexIndex v) const {
    const auto it = indices.find(key(u, v));
    if (it == indices.end()) return {};
    return it->second;
  }
};
ComparisonGraph comparison_input(const Graph&, const std::vector<std::string>& vertex_fields,
    const std::vector<std::string>& edge_fields, bool ignore_labels, const std::string& loops,
    const std::string& parallel, bool edit, Work&);
}
