#pragma once
#include "pattern_match.hpp"

namespace graphmine::runtime::record_query {
bool scalar(const json::value&);
std::string scalar_key(const json::value&);
int compare(const json::value&, const json::value&);
void check_field(const std::vector<json::object>&, const std::string&, bool,
                 bool allow_absent = false);
struct Filters {
  json::array rules;
  Filters(const json::value&, const std::vector<json::object>&, bool);
  bool match(const json::object&, Work&) const;
};
struct Index {
  const Graph& graph;
  std::vector<json::object> vertices, edges;
  std::vector<std::vector<std::size_t>> outgoing, incoming;
  std::vector<std::pair<VertexIndex, VertexIndex>> endpoints;
  std::map<ExternalId, std::size_t> edge_indices;
  explicit Index(const Graph&, Work&);
  std::optional<std::set<std::size_t>> selected(const json::object&, const char*, bool) const;
  Filters filters(const json::object&, const char*, bool) const;
};
using Adjacency = std::vector<std::vector<std::pair<VertexIndex, std::size_t>>>;
Adjacency adjacency(const Index&, const json::object&, Work&);
std::vector<std::int64_t> distances(const Adjacency&, VertexIndex, std::uint64_t, Work&);
json::object result(const json::object&, const json::array&, std::uint64_t, json::object);
}  // namespace graphmine::runtime::record_query
