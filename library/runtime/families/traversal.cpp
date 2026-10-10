#include "internal.hpp"

#include <algorithm>
#include <deque>
#include <set>

namespace graphmine::runtime {
Search cpu_bfs(const std::vector<std::vector<VertexIndex>>& graph, VertexIndex source,
               std::optional<std::uint64_t> depth, Work& work) {
  Search result{std::vector<std::int64_t>(graph.size(), -1),
                std::vector<std::int64_t>(graph.size(), -1)};
  std::deque<VertexIndex> queue{source};
  result.distances[source] = 0;
  while (!queue.empty()) {
    const auto u = queue.front();
    queue.pop_front();
    work.tick();
    if (depth && static_cast<std::uint64_t>(result.distances[u]) >= *depth) continue;
    for (const auto v : graph[u]) {
      work.tick();
      if (result.distances[v] < 0) {
        result.distances[v] = result.distances[u] + 1;
        result.predecessors[v] = u;
        queue.push_back(v);
      }
    }
  }
  return result;
}

json::object bfs(const Graph& graph, const json::object& args,
                 const std::string& backend, int device, Work& work) {
  fields(args, {"sources", "source_mode", "depth_limit", "return_predecessors"}, {"sources"});
  require(args.at("sources").is_array() && !args.at("sources").as_array().empty(), "sources must be a nonempty array");
  std::vector<VertexIndex> sources;
  std::set<VertexIndex> unique;
  for (const auto& value : args.at("sources").as_array()) {
    const auto source = graph.dense_index(external_id(value));
    require(unique.insert(source).second, "sources must be distinct");
    sources.push_back(source);
  }
  const auto mode = args.contains("source_mode") ? string(args.at("source_mode"), "source_mode") : "independent";
  require(mode == "independent" || mode == "nearest_source", "Unknown source_mode");
  std::optional<std::uint64_t> depth;
  if (args.contains("depth_limit") && !args.at("depth_limit").is_null()) depth = uint(args.at("depth_limit"), "depth_limit");
  if (depth) require(*depth <= UINT32_MAX, "depth_limit must fit an unsigned 32-bit integer");
  const bool predecessors = args.contains("return_predecessors") ? (require(args.at("return_predecessors").is_bool(), "return_predecessors must be boolean"), args.at("return_predecessors").as_bool()) : true;
  const auto row_count = static_cast<std::uint64_t>(graph.vertex_count()) * (mode == "independent" ? sources.size() : 1);
  work.output(row_count);
  // Both backends retain per-source distances until nearest-source merging.
  // Admit that memory before allocating even when the final table is small.
  work.tick(static_cast<std::uint64_t>(graph.vertex_count()) * sources.size());
  std::vector<Search> found;
  if (backend == "libcugraph") {
    found = cugraph_bfs(graph, sources, depth, device, work);
  } else {
    const auto adj = adjacency(graph, work);
    for (auto source : sources) found.push_back(cpu_bfs(adj, source, depth, work));
  }
  json::array rows, reached;
  std::set<VertexIndex> reached_ids;
  auto append = [&](VertexIndex vertex, std::size_t search, bool independent) {
    work.tick();
    const auto& values = found[search];
    const auto distance = values.distances[vertex];
    json::object row{{"vertex", id_json(graph.external_id(vertex))},
                     {"distance", distance < 0 ? json::value(nullptr) : json::value(distance)},
                     {"source", distance < 0 && !independent ? json::value(nullptr) : id_json(graph.external_id(sources[search]))}};
    if (predecessors) row["predecessor"] = values.predecessors[vertex] < 0 || distance <= 0 ? json::value(nullptr) : id_json(graph.external_id(static_cast<VertexIndex>(values.predecessors[vertex])));
    if (distance >= 0) reached_ids.insert(vertex);
    rows.push_back(row);
  };
  if (mode == "independent") {
    for (std::size_t s = 0; s < sources.size(); ++s)
      for (VertexIndex v = 0; v < graph.vertex_count(); ++v) append(v, s, true);
  } else {
    for (VertexIndex v = 0; v < graph.vertex_count(); ++v) {
      std::size_t best = 0;
      for (std::size_t s = 1; s < sources.size(); ++s) {
        work.tick();
        if (found[s].distances[v] >= 0 && (found[best].distances[v] < 0 || found[s].distances[v] < found[best].distances[v])) best = s;
      }
      append(v, best, false);
    }
  }
  for (auto v : reached_ids) reached.push_back(id_json(graph.external_id(v)));
  return {{"parameters", {{"sources", args.at("sources")}, {"source_mode", mode},
                            {"depth_limit", depth ? json::value(*depth) : json::value(nullptr)},
                            {"return_predecessors", predecessors}}},
          {"result", {{"distances", rows}}},
          {"ports", {{"vertices", {{"type", "vertex_set"}, {"value", reached}, {"complete", true}}},
                     {"distances", {{"type", "table"}, {"value", rows}, {"complete", true}}}}},
          {"complete", true}, {"quality", "exact"}};
}
}  // namespace graphmine::runtime
