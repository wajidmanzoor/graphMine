#pragma once
#include "family_util.hpp"

namespace graphmine::runtime {
struct FrequentInput {
  bool directed;
  std::string vertex_field, edge_field;
  std::vector<json::value> labels;
  struct Edge {
    VertexIndex u, v;
    json::value label;
  };
  std::vector<Edge> edges;
};
std::shared_ptr<const ViewResult> frequent_collection_view(const json::value&, Work&);
FrequentInput frequent_member_input(const Graph&, const CsrView&, const std::string& vertex_field,
    const std::string& edge_field, const std::string& loops, const std::string& parallel, Work&);
FrequentInput single_frequent_input(const Graph&, const std::string& vertex_field,
    const std::string& parallel, Work&);
}
