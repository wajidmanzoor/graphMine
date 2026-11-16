#pragma once

#include "family_util.hpp"

namespace graphmine::runtime {
const json::value* record_field(const json::object&, const std::string&);
bool typed_equal(const json::value&, const json::value&, Work&);
json::object vertex_record_json(const VertexRecord&, Work&);
json::object edge_record_json(const EdgeRecord&, Work&);
struct AttributePredicates {
  json::array specifications;
  bool edges;
  AttributePredicates(const json::value&, const Graph&, bool);
  bool match(const json::object&, const json::object&, Work&) const;
};
struct PatternRecords {
  std::vector<json::object> vertices, edges;
  std::map<std::pair<VertexIndex,VertexIndex>,std::vector<std::size_t>> bundles;
  PatternRecords(const Graph&, Work&, const ViewProfile&);
};
bool pattern_mappings(const Graph&, const Graph&, bool, const json::array&, const json::array&,
                      const std::function<bool(const std::vector<VertexIndex>&)>&, Work&,
                      const ViewProfile&);
bool simple_mappings(const MiningGraph&, const MiningGraph&, bool, bool,
                     const std::function<bool(const std::vector<VertexIndex>&)>&, Work&);
json::array mapping_rows(const Graph&, const Graph&, const std::vector<VertexIndex>&);
}  // namespace graphmine::runtime
