#include "graphmine/graph.hpp"

#include <algorithm>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_set>

namespace graphmine {

std::string ExternalId::to_string() const {
  if (std::holds_alternative<std::int64_t>(value_)) {
    return std::to_string(std::get<std::int64_t>(value_));
  }
  return std::get<std::string>(value_);
}

std::size_t ExternalIdHash::operator()(const ExternalId& id) const noexcept {
  if (std::holds_alternative<std::int64_t>(id.value())) {
    const auto value = std::get<std::int64_t>(id.value());
    return std::hash<std::int64_t>{}(value) ^ 0x9e3779b97f4a7c15ULL;
  }
  return std::hash<std::string>{}(std::get<std::string>(id.value())) ^
         0x85ebca6bU;
}

namespace {

std::uint64_t edge_key(VertexIndex source, VertexIndex target) {
  return (static_cast<std::uint64_t>(source) << 32U) |
         static_cast<std::uint64_t>(target);
}

}  // namespace

Graph::Graph(CanonicalGraphInput input) : input_(std::move(input)) {
  if (input_.graph.id.empty()) {
    throw std::invalid_argument("canonical graph id must not be empty");
  }
  if (input_.vertices.size() >
      static_cast<std::size_t>(std::numeric_limits<VertexIndex>::max())) {
    throw std::invalid_argument("graph has more vertices than the dense ID type supports");
  }

  dense_ids_.reserve(input_.vertices.size());
  for (std::size_t i = 0; i < input_.vertices.size(); ++i) {
    const auto inserted = dense_ids_.emplace(
        input_.vertices[i].id, static_cast<VertexIndex>(i));
    if (!inserted.second) {
      throw std::invalid_argument("duplicate vertex id: " +
                                  input_.vertices[i].id.to_string());
    }
  }

  std::unordered_set<ExternalId, ExternalIdHash> edge_ids;
  edge_ids.reserve(input_.edges.size());
  std::unordered_set<std::uint64_t> logical_edges;
  logical_edges.reserve(input_.edges.size());

  for (const auto& edge : input_.edges) {
    if (!edge_ids.emplace(edge.id).second) {
      throw std::invalid_argument("duplicate edge id: " + edge.id.to_string());
    }
    const auto source_it = dense_ids_.find(edge.source);
    const auto target_it = dense_ids_.find(edge.target);
    if (source_it == dense_ids_.end() || target_it == dense_ids_.end()) {
      throw std::invalid_argument("edge " + edge.id.to_string() +
                                  " references an unknown vertex");
    }

    auto source = source_it->second;
    auto target = target_it->second;
    if (source == target && !input_.graph.allows_self_loops) {
      throw std::invalid_argument("self-loop is present but graph disallows self-loops");
    }
    if (!input_.graph.directed && target < source) {
      std::swap(source, target);
    }
    if (!input_.graph.allows_parallel_edges &&
        !logical_edges.emplace(edge_key(source, target)).second) {
      throw std::invalid_argument(
          "parallel edge is present but graph disallows parallel edges");
    }
  }
}

Graph Graph::from_edges(
    std::string graph_id, std::vector<ExternalId> vertices,
    const std::vector<std::pair<ExternalId, ExternalId>>& edges,
    bool directed) {
  CanonicalGraphInput input;
  input.graph.id = std::move(graph_id);
  input.graph.directed = directed;
  input.graph.allows_self_loops = false;
  input.graph.allows_parallel_edges = false;
  input.vertices.reserve(vertices.size());
  for (auto& id : vertices) {
    input.vertices.push_back(VertexRecord{std::move(id), std::nullopt,
                                          std::nullopt, {}});
  }
  input.edges.reserve(edges.size());
  for (std::size_t i = 0; i < edges.size(); ++i) {
    input.edges.push_back(EdgeRecord{ExternalId{static_cast<std::int64_t>(i)},
                                     edges[i].first, edges[i].second,
                                     std::nullopt, std::nullopt, std::nullopt,
                                     {}});
  }
  return Graph(std::move(input));
}

VertexIndex Graph::dense_index(const ExternalId& id) const {
  const auto it = dense_ids_.find(id);
  if (it == dense_ids_.end()) {
    throw std::out_of_range("unknown external vertex id: " + id.to_string());
  }
  return it->second;
}

const ExternalId& Graph::external_id(VertexIndex index) const {
  if (index >= input_.vertices.size()) {
    throw std::out_of_range("dense vertex index is out of range");
  }
  return input_.vertices[index].id;
}

UndirectedGraphView Graph::simple_undirected(
    UndirectedProjectionOptions options) const {
  if (input_.graph.directed && !options.allow_directed_projection) {
    throw std::invalid_argument(
        "undirected algorithm received directed input without an explicit projection");
  }

  UndirectedGraphView view;
  view.normalization.directed_projection_applied = input_.graph.directed;

  std::set<std::pair<VertexIndex, VertexIndex>> unique_edges;
  for (const auto& edge : input_.edges) {
    auto source = dense_index(edge.source);
    auto target = dense_index(edge.target);
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

  std::vector<std::vector<VertexIndex>> adjacency(vertex_count());
  for (const auto& [source, target] : unique_edges) {
    adjacency[source].push_back(target);
    adjacency[target].push_back(source);
  }

  view.csr.offsets.resize(vertex_count() + 1, 0);
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

}  // namespace graphmine
