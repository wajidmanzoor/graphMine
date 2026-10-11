#pragma once
#include "numeric.hpp"

namespace graphmine::runtime {
struct StructuredVertices {
  std::vector<ExternalId> ids;
  std::map<ExternalId, VertexIndex> indices;
  void add(const json::value& value) {
    require(ids.size() < UINT32_MAX, "Too many structured-input vertices");
    const auto id = external_id(value);
    require(indices.emplace(id, ids.size()).second, "Duplicate structured-input vertex ID");
    ids.push_back(id);
  }
  VertexIndex index(const json::value& value) const {
    const auto found = indices.find(external_id(value));
    require(found != indices.end(), "Unknown structured-input vertex ID");
    return found->second;
  }
};
struct FeatureInput : StructuredVertices {
  std::string dataset_id;
  numeric::Matrix vectors;
  FeatureInput(const json::value& input, Work& work) {
    const auto data = object(input, "feature_vectors");
    fields(data, {"dataset_id", "dimension", "vectors"}, {"dataset_id", "dimension", "vectors"});
    dataset_id = string(data.at("dataset_id"), "dataset_id");
    require(!dataset_id.empty(), "dataset_id must not be empty");
    const auto dimension = uint(data.at("dimension"), "dimension");
    require(dimension > 0, "Feature dimension must be positive");
    require(data.at("vectors").is_array(), "vectors must be an array");
    const auto& records = data.at("vectors").as_array();
    vectors = numeric::Matrix(records.size(), dimension, work);
    for (std::size_t i = 0; i < records.size(); ++i) {
      const auto row = object(records[i], "vector");
      fields(row, {"id", "values"}, {"id", "values"});
      add(row.at("id"));
      require(row.at("values").is_array() && row.at("values").as_array().size() == dimension,
              "Feature width must match dimension");
      for (std::size_t j = 0; j < dimension; ++j)
        vectors(i, j) = numeric::float64(row.at("values").as_array()[j], "feature");
    }
  }
};
struct HypergraphInput : StructuredVertices {
  struct Edge {
    ExternalId id;
    family_util::Vertices vertices;
    Exact weight;
  };
  std::vector<Exact> weights;
  std::vector<Edge> edges;
  json::array vertex_records;
  HypergraphInput(const json::value& input, Work& work) {
    const auto data = object(input, "hypergraph");
    fields(data, {"graph", "vertices", "hyperedges"}, {"graph", "vertices", "hyperedges"});
    const auto meta = object(data.at("graph"), "hypergraph metadata");
    fields(meta, {"id", "attributes"}, {"id"});
    require(!string(meta.at("id"), "graph.id").empty(), "Hypergraph ID must not be empty");
    if (meta.contains("attributes"))
      require(meta.at("attributes").is_object(), "Graph attributes must be an object");
    require(data.at("vertices").is_array() && data.at("hyperedges").is_array(),
            "Hypergraph vertices and hyperedges must be arrays");
    vertex_records = data.at("vertices").as_array();
    for (const auto& value : vertex_records) {
      work.tick();
      const auto row = object(value, "hypergraph vertex");
      fields(row, {"id", "weight", "attributes"}, {"id"});
      add(row.at("id"));
      const auto weight =
          row.contains("weight") ? exact_number(row.at("weight"), "vertex weight") : Exact(1);
      require(weight >= 0, "Vertex weights must be nonnegative");
      weights.push_back(weight);
      if (row.contains("attributes"))
        require(row.at("attributes").is_object(), "Vertex attributes must be an object");
    }
    std::set<ExternalId> seen;
    for (const auto& value : data.at("hyperedges").as_array()) {
      work.tick();
      const auto row = object(value, "hyperedge");
      fields(row, {"id", "vertices", "weight", "attributes"}, {"id", "vertices"});
      const auto id = external_id(row.at("id"));
      require(seen.insert(id).second, "Duplicate hyperedge ID");
      require(row.at("vertices").is_array() && !row.at("vertices").as_array().empty(),
              "Hyperedges need a nonempty vertex array");
      Edge edge{
          id,
          {},
          row.contains("weight") ? exact_number(row.at("weight"), "hyperedge weight") : Exact(1)};
      require(edge.weight >= 0, "Hyperedge weights must be nonnegative");
      std::set<VertexIndex> members;
      for (const auto& vertex : row.at("vertices").as_array()) {
        work.tick();
        const auto v = index(vertex);
        require(members.insert(v).second, "Hyperedge repeats a vertex");
        edge.vertices.push_back(v);
      }
      if (row.contains("attributes"))
        require(row.at("attributes").is_object(), "Hyperedge attributes must be an object");
      edges.push_back(std::move(edge));
    }
  }
};
inline std::vector<Graph> graph_collection(const json::value& input, Work& work) {
  const auto data = object(input, "graph_collection");
  fields(data, {"dataset_id", "graphs"}, {"dataset_id", "graphs"});
  require(!string(data.at("dataset_id"), "dataset_id").empty(), "dataset_id must not be empty");
  require(data.at("graphs").is_array(), "graphs must be an array");
  std::vector<Graph> graphs;
  std::set<std::string> ids;
  for (const auto& raw : data.at("graphs").as_array()) {
    graphs.push_back(parse_graph(raw));
    const auto& graph = graphs.back();
    work.tick(graph.vertex_count() + graph.edge_count() + 1);
    require(ids.insert(graph.canonical().graph.id).second, "Collection graph IDs must be unique");
    require(graph.directed() == graphs.front().directed(),
            "Collection graphs must have consistent direction");
  }
  return graphs;
}
}  // namespace graphmine::runtime
