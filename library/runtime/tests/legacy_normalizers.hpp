#pragma once
// Frozen from a38d1dcb for equivalence tests only. Never linked into production.
#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include "../internal.hpp"
#include "../exact_number.hpp"
#include "../pattern_match.hpp"
#include "../numeric.hpp"
#include "../native_time.hpp"
namespace graphmine::legacy_test {
using namespace graphmine::runtime;
// Frozen feature common front; independent of the dense view and its repacker.
struct FeatureInput {
  std::vector<ExternalId> ids;
  std::map<ExternalId,VertexIndex> indices;
  std::string dataset_id;
  numeric::Matrix vectors;
  FeatureInput(const json::value& input, Work& work) {
    const auto data = object(input,"feature_vectors");
    fields(data,{"dataset_id","dimension","vectors"},{"dataset_id","dimension","vectors"});
    dataset_id = string(data.at("dataset_id"),"dataset_id");
    require(!dataset_id.empty(),"dataset_id must not be empty");
    const auto dimension = uint(data.at("dimension"),"dimension");
    require(dimension > 0,"Feature dimension must be positive");
    require(data.at("vectors").is_array(),"vectors must be an array");
    const auto& records = data.at("vectors").as_array();
    vectors = numeric::Matrix(records.size(),dimension,work);
    for (std::size_t i=0; i<records.size(); ++i) {
      const auto row = object(records[i],"vector");
      fields(row,{"id","values"},{"id","values"});
      require(ids.size() < UINT32_MAX,"Too many structured-input vertices");
      const auto id = external_id(row.at("id"));
      require(indices.emplace(id,ids.size()).second,"Duplicate structured-input vertex ID");
      ids.push_back(id);
      require(row.at("values").is_array() && row.at("values").as_array().size() == dimension,"Feature width must match dimension");
      for (std::size_t j=0; j<dimension; ++j) vectors(i,j) = numeric::float64(row.at("values").as_array()[j],"feature");
    }
  }
};
struct HypergraphInput {
  struct Edge { ExternalId id; std::vector<VertexIndex> vertices; Exact weight; };
  std::vector<ExternalId> ids;
  std::map<ExternalId,VertexIndex> indices;
  std::vector<Exact> weights;
  std::vector<Edge> edges;
  json::array vertex_records;
  HypergraphInput(const json::value& input, Work& work) {
    const auto data = object(input,"hypergraph");
    fields(data,{"graph","vertices","hyperedges"},{"graph","vertices","hyperedges"});
    const auto meta = object(data.at("graph"),"hypergraph metadata");
    fields(meta,{"id","attributes"},{"id"});
    require(!string(meta.at("id"),"graph.id").empty(),"Hypergraph ID must not be empty");
    if (meta.contains("attributes")) require(meta.at("attributes").is_object(),"Graph attributes must be an object");
    require(data.at("vertices").is_array() && data.at("hyperedges").is_array(),"Hypergraph vertices and hyperedges must be arrays");
    vertex_records = data.at("vertices").as_array();
    for (const auto& value : vertex_records) {
      work.tick();
      const auto row = object(value,"hypergraph vertex");
      fields(row,{"id","weight","attributes"},{"id"});
      require(ids.size() < UINT32_MAX,"Too many structured-input vertices");
      const auto id = external_id(row.at("id"));
      require(indices.emplace(id,ids.size()).second,"Duplicate structured-input vertex ID");
      ids.push_back(id);
      const auto weight = row.contains("weight") ? exact_number(row.at("weight"),"vertex weight") : Exact(1);
      require(weight >= 0,"Vertex weights must be nonnegative");
      weights.push_back(weight);
      if (row.contains("attributes")) require(row.at("attributes").is_object(),"Vertex attributes must be an object");
    }
    std::set<ExternalId> seen;
    for (const auto& value : data.at("hyperedges").as_array()) {
      work.tick();
      const auto row = object(value,"hyperedge");
      fields(row,{"id","vertices","weight","attributes"},{"id","vertices"});
      const auto id = external_id(row.at("id"));
      require(seen.insert(id).second,"Duplicate hyperedge ID");
      require(row.at("vertices").is_array() && !row.at("vertices").as_array().empty(),"Hyperedges need a nonempty vertex array");
      Edge edge{id,{},row.contains("weight") ? exact_number(row.at("weight"),"hyperedge weight") : Exact(1)};
      require(edge.weight >= 0,"Hyperedge weights must be nonnegative");
      std::set<VertexIndex> members;
      for (const auto& vertex : row.at("vertices").as_array()) {
        work.tick();
        const auto found = indices.find(external_id(vertex));
        require(found != indices.end(),"Unknown structured-input vertex ID");
        require(members.insert(found->second).second,"Hyperedge repeats a vertex");
        edge.vertices.push_back(found->second);
      }
      if (row.contains("attributes")) require(row.at("attributes").is_object(),"Hyperedge attributes must be an object");
      edges.push_back(std::move(edge));
    }
  }
};
inline std::set<std::pair<ExternalId,ExternalId>> dynamic_triangle_edges(const Graph& graph, Work& work) {
  require(!graph.directed(),"Dynamic triangles require an undirected graph");
  auto input = graph.canonical(); input.edges.clear();
  std::set<std::pair<ExternalId,ExternalId>> seen;
  for (auto edge : graph.canonical().edges) {
    work.tick();
    if (edge.source == edge.target) continue;
    auto a=edge.source,b=edge.target;
    if (!graph.directed() && b<a) std::swap(a,b);
    if (!seen.emplace(a,b).second) continue;
    edge.weight.reset(); edge.original_weight.reset();
    input.edges.push_back(std::move(edge));
  }
  const Graph normalized(std::move(input));
  std::set<std::pair<ExternalId,ExternalId>> result;
  for (const auto& edge : normalized.canonical().edges) result.emplace(std::minmax(edge.source,edge.target));
  return result;
}
inline UndirectedGraphView simple(const Graph& graph, UndirectedProjectionOptions options = {}) {
  if (graph.canonical().graph.directed && !options.allow_directed_projection) {
    throw std::invalid_argument(
        "undirected algorithm received directed input without an explicit projection");
  }

  UndirectedGraphView view;
  view.normalization.directed_projection_applied = graph.canonical().graph.directed;

  std::set<std::pair<VertexIndex, VertexIndex>> unique_edges;
  for (const auto& edge : graph.canonical().edges) {
    auto source = graph.dense_index(edge.source);
    auto target = graph.dense_index(edge.target);
    if (source == target) {
      ++view.normalization.self_loops_removed;
      continue;
    }
    if (target < source) {
      std::swap(source, target);
    }
    if (!unique_edges.emplace(source, target).second) {
      ++view.normalization.parallel_edges_collapsed;
    }
  }

  std::vector<std::vector<VertexIndex>> adjacency(graph.vertex_count());
  for (const auto& [source, target] : unique_edges) {
    adjacency[source].push_back(target);
    adjacency[target].push_back(source);
  }

  view.csr.offsets.resize(graph.vertex_count() + 1, 0);
  for (std::size_t vertex = 0; vertex < adjacency.size(); ++vertex) {
    std::sort(adjacency[vertex].begin(), adjacency[vertex].end());
    view.csr.offsets[vertex + 1] =
        view.csr.offsets[vertex] + adjacency[vertex].size();
    view.csr.neighbors.insert(view.csr.neighbors.end(),
                              adjacency[vertex].begin(),
                              adjacency[vertex].end());
  }
  return view;
}

inline WeightedGraph weighted(const Graph& graph, bool weighted, bool nonnegative,
                                          const std::string& aggregation,
                                          const std::string& direction, Work& work) {
  work.tick(graph.vertex_count());
  std::vector<std::map<VertexIndex, double>> rows(graph.vertex_count());
  const bool directed = graph.directed() && direction != "undirected_projection";
  auto add = [&](VertexIndex u, VertexIndex v, double weight) {
    work.tick();
    const auto found = rows[u].emplace(v, weight);
    if (found.second) return;
    auto& previous = found.first->second;
    if (aggregation == "min")
      previous = std::min(previous, weight);
    else if (aggregation == "max")
      previous = std::max(previous, weight);
    else if (aggregation == "sum")
      previous += weight;
    require(std::isfinite(previous), "Aggregated edge weight overflowed");
  };
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    const double weight = weighted ? edge.weight.value_or(1) : 1;
    require(!nonnegative || weight >= 0, "This operation requires nonnegative edge weights");
    auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    if (direction == "incoming" && directed) std::swap(u, v);
    add(u, v, weight);
    if (!directed) add(v, u, weight);
  }
  WeightedGraph result{std::vector<std::vector<Arc>>(rows.size()), directed};
  for (VertexIndex u = 0; u < rows.size(); ++u)
    for (const auto& [v, weight] : rows[u]) result.rows[u].push_back({v, weight});
  return result;
}

inline std::vector<std::vector<VertexIndex>> adjacency(const Graph& graph, Work& work) {
  std::vector<std::vector<VertexIndex>> result(graph.vertex_count());
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u != v) {
      result[u].push_back(v);
      if (!graph.directed()) result[v].push_back(u);
    }
  }
  for (auto& row : result) {
    std::sort(row.begin(), row.end());
    row.erase(std::unique(row.begin(), row.end()), row.end());
  }
  return result;
}
// Frozen exact edge-list normalizer from 0d4986de. Keep independent of the new
// factory and layout decoder so a policy/rounding change cannot bless itself.
inline MiningGraph propagation_neighbors(const Graph& graph, const std::string& direction, Work& work) {
  require(direction == "incoming" || direction == "outgoing" || direction == "undirected_projection",
          "Invalid propagation direction");
  MiningGraph neighbors(graph.vertex_count());
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    if (!graph.directed() || direction == "undirected_projection") {
      neighbors[u].push_back(v);
      neighbors[v].push_back(u);
    } else if (direction == "incoming") neighbors[v].push_back(u);
    else neighbors[u].push_back(v);
  }
  for (VertexIndex v = 0; v < neighbors.size(); ++v) {
    neighbors[v].push_back(v);
    std::sort(neighbors[v].begin(), neighbors[v].end());
    neighbors[v].erase(std::unique(neighbors[v].begin(), neighbors[v].end()), neighbors[v].end());
  }
  return neighbors;
}
inline numeric::Matrix propagate(const MiningGraph& neighbors, numeric::Matrix features, std::size_t layers, Work& work) {
  for (std::size_t layer = 0; layer < layers; ++layer) {
    numeric::Matrix next(features.rows, features.cols, work);
    for (std::size_t v = 0; v < features.rows; ++v)
      for (std::size_t c = 0; c < features.cols; ++c) {
        long double sum = 0;
        for (const auto u : neighbors[v]) { work.tick(); sum += features(u, c); }
        next(v, c) = numeric::finite(sum / neighbors[v].size());
      }
    features = std::move(next);
  }
  return features;
}
struct ExactEdge { VertexIndex u, v; Exact weight; std::size_t original; };
inline std::vector<ExactEdge> exact_edges(const Graph& graph, bool weighted, Work& work,
                                         bool nonnegative = true, bool loops = false) {
  std::map<std::pair<VertexIndex, VertexIndex>, ExactEdge> normalized;
  for (std::size_t i = 0; i < graph.edge_count(); ++i) {
    work.tick();
    const auto& raw = graph.canonical().edges[i];
    auto u = graph.dense_index(raw.source), v = graph.dense_index(raw.target);
    Exact weight = weighted ? Exact(raw.weight.value_or(1)) : Exact(1);
    require(!nonnegative || weight >= 0, "Weights must be nonnegative");
    if (u == v && !loops) continue;
    if (!graph.directed() && u > v) std::swap(u, v);
    auto [it, inserted] = normalized.emplace(std::make_pair(u, v), ExactEdge{u, v, weight, i});
    if (!inserted && weighted) it->second.weight += weight;
  }
  std::vector<ExactEdge> output;
  for (auto& entry : normalized) output.push_back(std::move(entry.second));
  return output;
}
inline numeric::Matrix structural_features(const Graph& graph, Work& work) {
  numeric::Matrix features(graph.vertex_count(),3,work);
  for (std::size_t v=0; v<features.rows; ++v) features(v,0) = 1;
  for (const auto& edge : exact_edges(graph,false,work,false,false)) {
    ++features(edge.u,2); ++features(edge.v,1);
    if (!graph.directed()) { ++features(edge.v,2); ++features(edge.u,1); }
  }
  return features;
}
// Frozen SimRank incoming-neighbor builder from 0d4986de.
inline MiningGraph simrank(const Graph& graph, bool project, Work& work) {
  MiningGraph neighbors(graph.vertex_count());
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    neighbors[v].push_back(u);
    if (!graph.directed() || project) neighbors[u].push_back(v);
  }
  for (auto& row : neighbors) {
    std::sort(row.begin(), row.end());
    row.erase(std::unique(row.begin(), row.end()), row.end());
  }
  return neighbors;
}
// Frozen record-query Index constructor from b80b1071. Record JSON conversion
// is part of the unchanged common front, not view normalization.
struct RecordIndex {
  const Graph& graph;
  std::vector<json::object> vertices, edges;
  std::vector<std::vector<std::size_t>> outgoing, incoming;
  std::vector<std::pair<VertexIndex, VertexIndex>> endpoints;
  std::map<ExternalId, std::size_t> edge_indices;
  RecordIndex(const Graph& input, Work& work)
      : graph(input), outgoing(input.vertex_count()), incoming(input.vertex_count()) {
    for (const auto& row : graph.canonical().vertices)
      vertices.push_back(vertex_record_json(row, work));
    for (const auto& row : graph.canonical().edges) {
      work.tick();
      const auto i = edges.size();
      const auto u = graph.dense_index(row.source), v = graph.dense_index(row.target);
      edges.push_back(edge_record_json(row, work));
      outgoing[u].push_back(i);
      incoming[v].push_back(i);
      endpoints.emplace_back(u, v);
      edge_indices[row.id] = i;
    }
  }
};
// Frozen force-layout input preparation from 06dc4cf3. In particular, every
// addition uses a long-double intermediate and rounds back to double at once.
struct ForceLayoutInput { numeric::Matrix weights, positions; };
inline ForceLayoutInput force_layout_input(const Graph& graph, bool weighted,
                                           std::size_t dimensions, Work& work) {
  const auto n = graph.vertex_count();
  ForceLayoutInput input{numeric::Matrix(n,n,work),numeric::Matrix(n,dimensions,work)};
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    require(!weighted || edge.weight.has_value(), "Weighted layout requires every edge weight");
    const double value = weighted ? *edge.weight : 1;
    require(value >= 0, "Layout weights must be nonnegative");
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    input.weights(u,v) = input.weights(v,u) = weighted
      ? numeric::finite(static_cast<long double>(input.weights(u,v)) + value) : 1;
  }
  return input;
}
// Frozen pattern_mappings::collect from ed2fcfb8. Arbitrary property conversion
// stays in the unchanged common front; endpoint grouping is frozen here.
struct PatternRecords {
  std::vector<json::object> vertices, edges;
  std::map<std::pair<VertexIndex,VertexIndex>,std::vector<std::size_t>> bundles;
  PatternRecords(const Graph& graph, Work& work) {
    for (const auto& v : graph.canonical().vertices)
      vertices.push_back(vertex_record_json(v,work));
    for (const auto& edge : graph.canonical().edges) {
      work.tick();
      auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
      if (!graph.directed() && u > v) std::swap(u,v);
      bundles[{u,v}].push_back(edges.size());
      edges.push_back(edge_record_json(edge,work));
    }
  }
};
// Frozen structure.cpp::SimpleEdges input construction from ed2fcfb8.
struct StructureInput {
  std::vector<std::pair<VertexIndex,VertexIndex>> pairs;
  std::vector<json::array> source_ids;
  std::vector<std::vector<std::pair<VertexIndex,std::size_t>>> adjacency;
  StructureInput(const Graph& graph, Work& work) : adjacency(graph.vertex_count()) {
    work.tick(graph.vertex_count());
    std::map<std::pair<VertexIndex,VertexIndex>,json::array> records;
    for (const auto& edge : graph.canonical().edges) {
      work.tick();
      const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
      if (u != v) records[std::minmax(u,v)].push_back(id_json(edge.id));
    }
    for (auto& [edge,ids] : records) {
      work.tick();
      const auto position = pairs.size();
      pairs.push_back(edge); source_ids.push_back(std::move(ids));
      adjacency[edge.first].emplace_back(edge.second,position);
      adjacency[edge.second].emplace_back(edge.first,position);
    }
    for (auto& row : adjacency) std::sort(row.begin(),row.end());
  }
};
// Frozen influence-maximization input preparation before its view migration.
struct InfluenceInput {
  std::map<std::pair<VertexIndex,VertexIndex>,Exact> weights;
  std::vector<std::vector<std::pair<VertexIndex,Exact>>> incoming;
  InfluenceInput(const Graph& graph, bool cascade, Work& work) : incoming(graph.vertex_count()) {
    for (const auto& edge : graph.canonical().edges) {
      work.tick();
      require(edge.weight && *edge.weight >= 0 && *edge.weight <= 1,
              "Every diffusion edge needs an explicit weight in [0,1]");
      const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
      if (u == v) continue;
      auto& weight = weights[{u,v}];
      const Exact probability(*edge.weight);
      if (cascade) weight = 1 - (1 - weight) * (1 - probability);
      else weight += probability;
    }
    for (const auto& [ends,weight] : weights)
      if (weight > 0) incoming[ends.second].emplace_back(ends.first,weight);
  }
};
// Frozen group-Steiner minimum-edge preparation and cost/index solver order.
inline std::vector<ExactEdge> steiner_edges(const Graph& graph, Work& work) {
  std::map<std::pair<VertexIndex,VertexIndex>,ExactEdge> normalized;
  for (std::size_t i=0; i<graph.edge_count(); ++i) {
    work.tick();
    const auto& edge = graph.canonical().edges[i];
    require(edge.weight && *edge.weight >= 0,"Every group-Steiner edge needs nonnegative weight");
    auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    if (u > v) std::swap(u,v);
    auto [it,inserted] = normalized.emplace(std::make_pair(u,v),ExactEdge{u,v,Exact(*edge.weight),i});
    if (!inserted && Exact(*edge.weight) < it->second.weight)
      it->second = {u,v,Exact(*edge.weight),i};
  }
  std::vector<ExactEdge> result;
  for (const auto& [_,edge] : normalized) result.push_back(edge);
  std::sort(result.begin(),result.end(),[](const auto& a,const auto& b) {
    return a.weight != b.weight ? a.weight < b.weight : a.original < b.original;
  });
  return result;
}
// Frozen per-original-edge inputs to graph coarsening's quotient computation.
// Cluster aggregation is the algorithm itself; these records are not merged.
inline std::vector<ExactEdge> exact_records(const Graph& graph, Work& work) {
  std::vector<ExactEdge> result;
  for (std::size_t i=0; i<graph.edge_count(); ++i) {
    work.tick();
    const auto& edge = graph.canonical().edges[i];
    result.push_back({graph.dense_index(edge.source),graph.dense_index(edge.target),
                       Exact(edge.weight.value_or(1)),i});
  }
  return result;
}
// Frozen random_walks adjacency construction, including zero-mass entries and
// self-loops, before its CPU input migration.
inline std::vector<std::map<VertexIndex,Exact>> walk_adjacency(const Graph& graph, bool uniform, Work& work) {
  work.tick(graph.vertex_count());
  std::vector<std::map<VertexIndex,Exact>> adj(graph.vertex_count());
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    const Exact weight = uniform ? Exact(1) : Exact(edge.weight.value_or(1));
    require(weight >= 0,"Walk weights must be nonnegative");
    auto add = [&](VertexIndex from,VertexIndex to) {
      if (uniform) adj[from][to] = 1;
      else adj[from][to] += weight;
    };
    add(u,v);
    if (!graph.directed() && u != v) add(v,u);
  }
  return adj;
}
// Frozen original-edge set used by null-model significance before randomizing.
inline std::set<std::pair<VertexIndex,VertexIndex>> edge_set_input(const Graph& graph, Work& work) {
  std::set<std::pair<VertexIndex,VertexIndex>> result;
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    if (!graph.directed() && u > v) std::swap(u,v);
    result.emplace(u,v);
  }
  return result;
}
// Frozen persistent-homology validation and minimum filtration edge map.
inline std::map<std::pair<VertexIndex,VertexIndex>,Exact> filtration_input(const Graph& graph, Work& work) {
  std::map<std::pair<VertexIndex,VertexIndex>,Exact> weights;
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    require(edge.source != edge.target,"Persistence rejects self-loops");
    require(edge.weight && *edge.weight >= 0,"Every edge needs nonnegative filtration weight");
    auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u > v) std::swap(u,v);
    const Exact value(*edge.weight);
    auto [it,inserted] = weights.emplace(std::make_pair(u,v),value);
    if (!inserted && value < it->second) it->second = value;
  }
  return weights;
}
// Frozen signed-balance normalization, including contradictory parallel signs.
struct SignedEdge { VertexIndex u, v; bool negative; Exact weight; };
inline std::map<std::pair<VertexIndex,VertexIndex>,SignedEdge> signed_input(const Graph& graph, bool weighted, Work& work) {
  std::map<std::pair<VertexIndex,VertexIndex>,SignedEdge> result;
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    require(edge.type && (*edge.type == "positive" || *edge.type == "negative"),
            "Every edge requires type positive or negative");
    auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    const Exact weight = weighted ? Exact(edge.weight.value_or(1)) : Exact(1);
    require(weight >= 0,"Frustration costs must be nonnegative");
    if (u == v) continue;
    if (u > v) std::swap(u,v);
    auto [it,inserted] = result.emplace(std::make_pair(u,v),SignedEdge{u,v,*edge.type == "negative",weight});
    if (!inserted) {
      require(it->second.negative == (*edge.type == "negative"),
              "Contradictory parallel signed edges require a resolution policy");
      if (weighted) it->second.weight += weight;
    }
  }
  return result;
}
// Frozen normalized(graph, nullptr, "maximum_weight", work) for general matching.
struct MatchingEdge { VertexIndex u, v; std::size_t original; Exact value; };
inline std::vector<MatchingEdge> general_matching_edges(const Graph& graph, Work& work) {
  require(!graph.directed(),"Matching requires an undirected graph");
  std::map<std::pair<VertexIndex,VertexIndex>,MatchingEdge> unique;
  for (std::size_t i=0; i<graph.edge_count(); ++i) {
    work.tick();
    const auto& edge = graph.canonical().edges[i];
    auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (v < u) std::swap(u,v);
    require(edge.weight.has_value(),"Weighted matching requires every edge weight");
    const Exact value(*edge.weight);
    require(value >= 0,"General weighted matching requires nonnegative weights");
    if (u == v) continue;
    const auto pair = std::make_pair(u,v);
    const auto found = unique.find(pair);
    if (found == unique.end() || value > found->second.value) unique[pair] = {u,v,i,value};
  }
  std::vector<MatchingEdge> result;
  for (auto& [_,edge] : unique) result.push_back(std::move(edge));
  return result;
}
// Frozen entity-resolution vertex input; edge hints are not algorithm inputs.
inline std::vector<json::object> vertex_records_input(const Graph& graph, Work& work) {
  std::vector<json::object> records;
  for (const auto& v : graph.canonical().vertices) records.push_back(vertex_record_json(v,work));
  return records;
}
// Frozen widest-path row builder; undirected rows interleave original edge IDs.
inline std::vector<std::vector<std::pair<VertexIndex,double>>> widest_path_input(const Graph& graph, Work& work) {
  std::vector<std::vector<std::pair<VertexIndex,double>>> rows(graph.vertex_count());
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    require(edge.weight && *edge.weight >= 0,"Every widest-path edge requires a nonnegative capacity");
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    rows[u].emplace_back(v,*edge.weight);
    if (!graph.directed()) rows[v].emplace_back(u,*edge.weight);
  }
  return rows;
}
// Frozen critical-path adjacency plus the raw endpoints/weights read by its DP.
struct CriticalPathInput {
  std::vector<std::vector<std::size_t>> adjacency;
  std::vector<std::size_t> indegree;
  std::vector<VertexIndex> ends;
  std::vector<Exact> weights;
  CriticalPathInput(const Graph& graph, Work& work) : adjacency(graph.vertex_count()),indegree(graph.vertex_count()) {
    for (std::size_t i=0; i<graph.edge_count(); ++i) {
      work.tick();
      const auto& edge = graph.canonical().edges[i];
      require(edge.weight.has_value(),"Critical paths require every edge weight");
      const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
      adjacency[u].push_back(i); ++indegree[v];
      ends.push_back(v); weights.emplace_back(*edge.weight);
    }
  }
};
// Frozen graph_output.cpp selection/serialization before adding view inputs.
inline json::object selected_graph(const Graph& graph, const std::vector<bool>& selected, Work& work) {
  auto properties = [&](json::object& output,const Attributes& attrs,bool present) {
    if (present || !attrs.empty()) output["attributes"] = property_json(PropertyValue(attrs),work);
  };
  const auto& data = graph.canonical();
  json::array vertices,edges;
  for (VertexIndex v=0; v<selected.size(); ++v) if (selected[v]) {
    work.tick();
    const auto& record = data.vertices[v];
    json::object row{{"id",id_json(record.id)}};
    if (record.label) row["label"] = *record.label;
    if (record.type) row["type"] = *record.type;
    properties(row,record.attributes,record.attributes_present);
    vertices.push_back(row);
  }
  for (const auto& edge : data.edges) {
    work.tick();
    if (!selected[graph.dense_index(edge.source)] || !selected[graph.dense_index(edge.target)]) continue;
    json::object row{{"id",id_json(edge.id)},{"source",id_json(edge.source)},{"target",id_json(edge.target)}};
    if (edge.original_weight)
      row["weight"] = std::visit([](const auto& value) { return json::value(value); },*edge.original_weight);
    else if (edge.weight) row["weight"] = display_number(Exact(*edge.weight));
    if (edge.timestamp)
      row["timestamp"] = std::visit([](const auto& value) { return json::value(value); },*edge.timestamp);
    if (edge.type) row["type"] = *edge.type;
    properties(row,edge.attributes,edge.attributes_present);
    edges.push_back(row);
    work.output(vertices.size()+edges.size());
  }
  work.output(vertices.size()+edges.size());
  json::object metadata{{"id",data.graph.id},{"directed",data.graph.directed},
    {"allows_self_loops",data.graph.allows_self_loops},{"allows_parallel_edges",data.graph.allows_parallel_edges}};
  properties(metadata,data.graph.attributes,data.graph.attributes_present);
  return {{"graph",metadata},{"vertices",vertices},{"edges",edges}};
}
// Frozen bounded-path input construction, with its directed-operation guard.
struct EnumerationInput {
  std::vector<std::vector<std::size_t>> adjacency;
  std::vector<Exact> times;
  std::vector<VertexIndex> ends;
  EnumerationInput(const Graph& graph, bool preserve, bool chronological,
                     std::optional<std::size_t> anchor, Work& work) {
    require(graph.directed(),"Bounded path and cycle enumeration requires directed input");
    const auto& raw = graph.canonical().edges;
    adjacency.resize(graph.vertex_count()); times.resize(raw.size()); ends.resize(raw.size());
    std::set<std::pair<VertexIndex,VertexIndex>> seen;
    for (std::size_t i=0; i<raw.size(); ++i) {
      work.tick();
      const auto u = graph.dense_index(raw[i].source), v = graph.dense_index(raw[i].target);
      ends[i] = v;
      if (u == v) {
        require(!anchor || *anchor != i,"anchor_edge is a discarded self-loop");
        continue;
      }
      if (!seen.emplace(u,v).second && !preserve) {
        require(!anchor || *anchor != i,"anchor_edge was collapsed; select preserve parallel edges");
        continue;
      }
      adjacency[u].push_back(i);
      if (chronological) times[i] = timestamp_seconds(raw[i].timestamp,work);
    }
  }
};
}  // namespace graphmine::legacy_test
