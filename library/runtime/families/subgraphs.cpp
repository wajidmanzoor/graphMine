#include "internal.hpp"

#include <algorithm>
#include <queue>

namespace graphmine::runtime {
json::object induced_subgraph(const Graph& graph, const json::object& args, const std::string& backend, int device, Work& work) {
  fields(args, {"mode","vertices_or_seeds","radius","direction_mode"}, {"mode","vertices_or_seeds"});
  const auto mode = string(args.at("mode"),"mode"); require(mode == "induced" || mode == "ego", "Unknown subgraph selection mode");
  require(args.at("vertices_or_seeds").is_array(), "vertices_or_seeds must be an array");
  const auto radius = args.contains("radius") ? uint(args.at("radius"),"radius") : 1;
  const auto direction = args.contains("direction_mode") ? string(args.at("direction_mode"),"direction_mode") : "outgoing";
  require(direction == "outgoing" || direction == "incoming" || direction == "undirected_projection", "Unknown direction_mode");
  work.tick(graph.vertex_count()); std::vector<bool> selected(graph.vertex_count(),false); std::vector<VertexIndex> seeds; json::array resolved;
  for (const auto& raw : args.at("vertices_or_seeds").as_array()) {
    work.tick(); const auto vertex = graph.dense_index(external_id(raw)); resolved.push_back(id_json(graph.external_id(vertex)));
    if (!selected[vertex]) { selected[vertex] = true; seeds.push_back(vertex); }
  }
  if (mode == "ego" && radius && !seeds.empty()) {
    const auto input = weighted_graph(graph, false, false, "collapse", direction, work);
    if (backend == "cpp") {
      std::queue<std::pair<VertexIndex,std::uint64_t>> queue; for (const auto v : seeds) queue.emplace(v,0);
      while (!queue.empty()) {
        work.tick(); const auto [u,depth] = queue.front(); queue.pop(); if (depth >= radius) continue;
        for (const auto& arc : input.rows[u]) { work.tick(); if (!selected[arc.target]) { selected[arc.target] = true; queue.emplace(arc.target,depth+1); } }
      }
    } else {
      CanonicalGraphInput normalized; normalized.graph = {"native-ego-discovery",true,false,false,{}};
      for (VertexIndex v = 0; v < input.rows.size(); ++v) normalized.vertices.push_back({ExternalId(static_cast<std::int64_t>(v)),{},{},{}});
      for (VertexIndex u = 0; u < input.rows.size(); ++u) for (const auto& arc : input.rows[u]) {
        work.tick(); normalized.edges.push_back({ExternalId(static_cast<std::int64_t>(normalized.edges.size())), ExternalId(static_cast<std::int64_t>(u)), ExternalId(static_cast<std::int64_t>(arc.target)), {}, {}, {}, {}});
      }
      const Graph discovery(std::move(normalized));
      const auto results = cugraph_bfs(discovery,seeds,std::min<std::uint64_t>(radius,graph.vertex_count()),device,work);
      for (const auto& search : results) for (VertexIndex v = 0; v < selected.size(); ++v) { work.tick(); if (search.distances[v] >= 0) selected[v] = true; }
    }
  }
  const auto output = selected_graph(graph,selected,work); json::array vertices, mapping;
  for (VertexIndex v = 0; v < selected.size(); ++v) if (selected[v]) {
    const auto id = id_json(graph.external_id(v)); mapping.push_back(json::object{{"vertex",id},{"local_index",vertices.size()},{"input_index",v}}); vertices.push_back(id);
  }
  return {{"parameters",{{"mode",mode},{"vertices_or_seeds",resolved},{"radius",radius},{"direction_mode",direction}}},
          {"result",{{"subgraph",output},{"graph",output},{"vertex_mapping",{{"local_to_original",vertices},{"original_to_local",mapping}}}}},
          {"ports",{{"graph",result_port("graph",output)},{"vertices",result_port("vertex_set",vertices)}}},{"complete",true},{"quality","exact"},
          {"diagnostics",{{"record_policy","Preserve typed IDs, record order, edge instances and property values; omit empty optional attribute maps"}}}};
}
}  // namespace graphmine::runtime
