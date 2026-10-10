#include "internal.hpp"

#include <algorithm>
#include <map>
#include <numeric>
#include <queue>
#include <set>

namespace graphmine::runtime {
namespace {
using Pair = std::pair<VertexIndex, VertexIndex>;
Pair ordered(VertexIndex u, VertexIndex v) { return std::minmax(u, v); }
struct SimpleEdges {
  std::vector<Pair> pairs;
  std::vector<json::array> source_ids;
  std::vector<std::vector<std::pair<VertexIndex, std::size_t>>> adjacency;
  explicit SimpleEdges(const Graph& graph, Work& work) : adjacency(graph.vertex_count()) {
    work.tick(graph.vertex_count());
    std::map<Pair, json::array> records;
    for (const auto& edge : graph.canonical().edges) {
      work.tick(); const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
      if (u != v) records[ordered(u, v)].push_back(id_json(edge.id));
    }
    for (auto& [edge, ids] : records) {
      work.tick(); const auto position = pairs.size();
      pairs.push_back(edge); source_ids.push_back(std::move(ids));
      adjacency[edge.first].emplace_back(edge.second, position);
      adjacency[edge.second].emplace_back(edge.first, position);
    }
    for (auto& row : adjacency) std::sort(row.begin(), row.end());
  }
  json::object row(const Graph& graph, std::size_t e) const {
    return {{"id", source_ids[e].front()}, {"source", id_json(graph.external_id(pairs[e].first))},
            {"target", id_json(graph.external_id(pairs[e].second))}, {"source_edge_ids", source_ids[e]}};
  }
  template<class Emit> void triangles(std::size_t e, Work& work, Emit emit) const {
    const auto& a = adjacency[pairs[e].first]; const auto& b = adjacency[pairs[e].second];
    std::size_t i = 0, j = 0;
    while (i < a.size() && j < b.size()) {
      work.tick();
      if (a[i].first < b[j].first) ++i;
      else if (b[j].first < a[i].first) ++j;
      else { emit(a[i].second, b[j].second); ++i; ++j; }
    }
  }
};
json::array external(const Graph& graph, const std::vector<VertexIndex>& vertices) {
  json::array output; for (const auto v : vertices) output.push_back(id_json(graph.external_id(v))); return output;
}
}

json::object biconnected(const Graph& graph, const json::object& args, const std::string&, int, Work& work) {
  fields(args, {}); require(!graph.directed(), "Biconnected blocks require an undirected graph");
  const SimpleEdges input(graph, work); const auto n = graph.vertex_count();
  const auto missing = input.pairs.size();
  std::vector<std::size_t> discovered(n, 0), low(n, 0), parent_edge(n, missing), children(n, 0), edge_stack;
  std::vector<bool> cut(n, false); std::size_t clock = 0;
  std::vector<std::vector<std::size_t>> blocks;
  std::vector<std::size_t> bridges;
  std::vector<VertexIndex> isolated;
  // Iterative Tarjan traversal has no host recursion-depth dependence.
  for (VertexIndex root = 0; root < n; ++root) {
    work.tick(); if (discovered[root]) continue;
    if (input.adjacency[root].empty()) { isolated.push_back(root); discovered[root] = ++clock; continue; }
    std::vector<std::pair<VertexIndex, std::size_t>> stack{{root, 0}};
    discovered[root] = low[root] = ++clock;
    while (!stack.empty()) {
      work.tick(); auto& [u, next] = stack.back();
      if (next < input.adjacency[u].size()) {
        const auto [v, edge] = input.adjacency[u][next++];
        if (edge == parent_edge[u]) continue;
        if (!discovered[v]) {
          parent_edge[v] = edge; ++children[u]; edge_stack.push_back(edge);
          discovered[v] = low[v] = ++clock; stack.emplace_back(v, 0);
        } else if (discovered[v] < discovered[u]) {
          low[u] = std::min(low[u], discovered[v]); edge_stack.push_back(edge);
        }
        continue;
      }
      const auto child = u; stack.pop_back();
      if (stack.empty()) { cut[child] = children[child] > 1; continue; }
      const auto parent = stack.back().first;
      low[parent] = std::min(low[parent], low[child]);
      if (low[child] > discovered[parent]) bridges.push_back(parent_edge[child]);
      if (low[child] >= discovered[parent]) {
        if (parent_edge[parent] != missing) cut[parent] = true;
        std::vector<std::size_t> block;
        while (true) {
          work.tick(); require(!edge_stack.empty(), "Native block stack lost its parent edge");
          const auto edge = edge_stack.back(); edge_stack.pop_back(); block.push_back(edge);
          if (edge == parent_edge[child]) break;
        }
        std::sort(block.begin(), block.end()); blocks.push_back(std::move(block));
      }
    }
    require(edge_stack.empty(), "Native block decomposition left unassigned edges");
  }
  std::vector<VertexIndex> articulation;
  for (VertexIndex v = 0; v < n; ++v) if (cut[v]) articulation.push_back(v);
  std::sort(bridges.begin(), bridges.end());
  struct Block { std::vector<VertexIndex> vertices; std::vector<std::size_t> edges; };
  std::vector<Block> ordered_blocks;
  std::uint64_t output_size = bridges.size() + articulation.size() + isolated.size();
  for (auto& block : blocks) {
    std::set<VertexIndex> vertices;
    for (const auto e : block) { work.tick(); vertices.insert(input.pairs[e].first); vertices.insert(input.pairs[e].second); }
    output_size += block.size() + vertices.size(); work.output(output_size);
    ordered_blocks.push_back({{vertices.begin(), vertices.end()}, std::move(block)});
  }
  work.output(output_size);
  std::sort(ordered_blocks.begin(), ordered_blocks.end(), [](const auto& a, const auto& b) {
    return a.vertices.size() != b.vertices.size() ? a.vertices.size() > b.vertices.size() : a.vertices < b.vertices;
  });
  json::array groups, edge_blocks, bridge_rows, normalized_edges;
  for (const auto& block : ordered_blocks) {
    json::array ids; for (const auto e : block.edges) ids.push_back(input.source_ids[e].front());
    groups.push_back(json::object{{"group", groups.size()}, {"vertices", external(graph, block.vertices)}, {"size", block.vertices.size()}, {"edge_ids", ids}});
    edge_blocks.push_back(std::move(ids));
  }
  for (const auto e : bridges) bridge_rows.push_back(input.row(graph, e));
  for (std::size_t e = 0; e < input.pairs.size(); ++e) normalized_edges.push_back(input.row(graph, e));
  const auto points = external(graph, articulation);
  return {{"parameters", json::object{}},
          {"result", {{"groups", groups}, {"count", groups.size()}, {"blocks", edge_blocks}, {"normalized_edges", normalized_edges},
                      {"bridges", bridge_rows}, {"articulation_vertices", points}, {"articulation_points", points}, {"isolated_vertices", external(graph, isolated)}}},
          {"ports", {{"groups", result_port("vertex_groups", groups)}, {"vertices", result_port("vertex_set", points)}, {"edges", result_port("edge_set", bridge_rows)}}},
          {"complete", true}, {"quality", "exact"}};
}

json::object truss(const Graph& graph, const json::object& args, const std::string& backend, int device, Work& work) {
  fields(args, {"requested_k"}); require(!graph.directed(), "Truss decomposition requires an undirected graph");
  std::optional<std::uint64_t> requested;
  if (args.contains("requested_k") && !args.at("requested_k").is_null()) {
    requested = uint(args.at("requested_k"), "requested_k"); require(*requested >= 2, "requested_k must be at least two");
  }
  const SimpleEdges input(graph, work); work.output(input.pairs.size());
  std::vector<std::uint32_t> values(input.pairs.size(), 2);
  if (backend == "cpp") {
    std::vector<std::uint32_t> support(input.pairs.size(), 0);
    std::vector<bool> removed(input.pairs.size(), false);
    using Item = std::pair<std::uint32_t, std::size_t>;
    std::priority_queue<Item, std::vector<Item>, std::greater<Item>> queue;
    for (std::size_t e = 0; e < input.pairs.size(); ++e) {
      input.triangles(e, work, [&](auto, auto) { ++support[e]; }); queue.emplace(support[e], e);
    }
    while (!queue.empty()) {
      work.tick(); const auto [level, e] = queue.top(); queue.pop();
      if (removed[e] || support[e] != level) continue;
      removed[e] = true; values[e] = level + 2;
      input.triangles(e, work, [&](auto a, auto b) {
        if (removed[a] || removed[b]) return;
        for (const auto other : {a, b}) if (support[other] > level) { --support[other]; queue.emplace(support[other], other); }
      });
    }
  } else {
    values = cugraph_truss_numbers(weighted_graph(graph, false, false, "collapse", "outgoing", work), input.pairs, device, work);
    require(values.size() == input.pairs.size(), "GPU truss decomposition lost normalized edges");
  }
  json::array rows, selected, by_edge; std::set<VertexIndex> endpoints; std::uint32_t maximum = 0;
  for (std::size_t e = 0; e < input.pairs.size(); ++e) {
    work.tick(); require(values[e] >= 2 && values[e] <= std::max<std::size_t>(2, graph.vertex_count()), "Invalid GPU truss number");
    auto row = input.row(graph, e); row["truss_number"] = values[e]; rows.push_back(row);
    by_edge.push_back(json::object{{"edge", input.source_ids[e].front()}, {"truss_number", values[e]}});
    maximum = std::max(maximum, values[e]);
    if (!requested || values[e] >= *requested) { selected.push_back(row); endpoints.insert(input.pairs[e].first); endpoints.insert(input.pairs[e].second); }
  }
  work.output(input.pairs.size() + endpoints.size());
  return {{"parameters", {{"requested_k", requested ? json::value(*requested) : json::value(nullptr)}}},
          {"result", {{"edges", rows}, {"truss_number_by_edge", by_edge}, {"maximum_truss_number", maximum}, {"selected_edges", selected},
                      {"selected_vertices", external(graph, {endpoints.begin(), endpoints.end()})}}},
          {"ports", {{"edges", result_port("edge_set", selected)}}}, {"complete", true}, {"quality", "exact"}};
}
}  // namespace graphmine::runtime
