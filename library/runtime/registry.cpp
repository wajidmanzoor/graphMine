#include "internal.hpp"
#include "catalog_data.hpp"

namespace graphmine::runtime {
namespace {
json::object parameter(std::string kind, json::value initial, bool required = false,
                       bool nullable = false) {
  json::object result{{"kind", kind}, {"required", required}, {"nullable", nullable}};
  if (!required) result["default"] = std::move(initial);
  return result;
}
json::object card(const char* id, const char* problem, const char* title,
                  const char* description, json::object parameters,
                  json::object ports, json::array gpu_backends) {
  json::array backends{json::object{{"id", "cpp"}, {"device", "cpu"}, {"compiled", true}}};
  for (const auto& backend : gpu_backends) backends.push_back(backend);
  auto taxonomy = json::parse(taxonomy_json).as_object();
  std::string family;
  for (const auto& row : taxonomy.at("problems").as_array())
    if (row.as_object().at("id").as_string() == problem) family = string(row.as_object().at("family"), "family");
  require(!family.empty(), "Native operation has no declared problem family");
  return {{"id", id}, {"problem_id", problem}, {"family", family},
          {"title", title}, {"description", description}, {"input_kind", "graph"},
          {"parameters", parameters}, {"output_ports", ports}, {"backends", backends},
          {"quality", "exact"}, {"implementation_language", "c++/cuda"},
          {"evidence_status", "requires_matching_validation_report"}};
}
}

json::array operation_cards() {
  auto source_mode = parameter("string", "independent");
  source_mode["choices"] = json::array{"independent", "nearest_source"};
  auto depth = parameter("integer", nullptr, false, true);
  depth["minimum"] = 0; depth["maximum"] = UINT32_MAX;
  auto mode = parameter("string", "count");
  mode["choices"] = json::array{"count", "enumerate"};
  auto limit = parameter("integer", nullptr, false, true);
  limit["minimum"] = 1;
  auto port = [](const char* kind) { return json::object{{"type", kind}, {"availability", "runtime_checked"}}; };
  return {
    card("breadth-first-search", "breadth_first_search", "Connections within a number of steps",
         "Minimum hop distances with explicit independent or nearest-source searches. Preserve direction; discard loops and collapse duplicate arcs; weights are ignored. IDs are signed int64 or strings.",
         {{"sources", parameter("array", nullptr, true)}, {"source_mode", source_mode},
          {"depth_limit", depth}, {"return_predecessors", parameter("boolean", true)}},
         {{"vertices", port("vertex_set")}, {"distances", port("table")}},
         {json::object{{"id", "libcugraph"}, {"device", "gpu"}, {"compiled", cugraph_compiled()}}}),
    card("triangle-counting", "triangle_counting_listing", "Count or list triangles",
         "Count three-vertex cliques of an undirected graph. Discard loops and collapse duplicate edges; weights are ignored. GPU enumeration uses native CPU materialization with count verification.",
         {{"mode", mode}, {"result_limit", limit}},
         {{"count", port("scalar")}, {"groups", port("vertex_groups")}},
         {json::object{{"id", "tot"}, {"device", "gpu"}, {"compiled", original_triangles_compiled("tot")}},
          json::object{{"id", "wetric"}, {"device", "gpu"}, {"compiled", original_triangles_compiled("wetric")}}})
  };
}

json::object catalog() {
  auto result = json::parse(taxonomy_json).as_object();
  const auto cards = operation_cards();
  for (auto& family : result.at("families").as_array()) {
    json::array operations;
    for (const auto& op : cards)
      if (op.as_object().at("family") == family.as_object().at("id")) operations.push_back(op.as_object().at("id"));
    family.as_object()["operations"] = operations;
  }
  for (auto& problem : result.at("problems").as_array()) {
    json::array operations;
    for (const auto& op : cards)
      if (op.as_object().at("problem_id") == problem.as_object().at("id")) operations.push_back(op.as_object().at("id"));
    problem.as_object()["operations"] = operations;
    problem.as_object()["runtime_integration"] = operations.empty() ? "pending" : "implemented";
  }
  result["operations"] = cards;
  result["abi_version"] = 1;
  result["implementation_sha256"] = implementation_sha256;
  result["python_runtime_required"] = false;
  result["file_readers"] = json::array{json::object{{"id", "libcudf-csv"}, {"compiled", cudf_compiled()}, {"device", "gpu"}}};
  return result;
}
}  // namespace graphmine::runtime
