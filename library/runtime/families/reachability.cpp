#include "family_util.hpp"

namespace graphmine::runtime {
json::object transitive_closure(const Graph& graph, const json::object& args, const std::string&,
                                int, Work& work) {
  using namespace family_util;
  fields(args, {"query_mode", "query_pairs", "enumerate_closure_edges"});
  const auto mode = choice(args, "query_mode", "full_transitive_closure",
                           {"single_pair", "batch_pairs", "full_transitive_closure"});
  const bool enumerate = boolean(args, "enumerate_closure_edges", true);
  const auto adj = adjacency(graph, work);
  json::array rows;
  std::uint64_t count = 0;
  if (mode == "full_transitive_closure") {
    require(!args.contains("query_pairs") || args.at("query_pairs").is_null(),
            "query_pairs is not accepted for full closure");
    for (VertexIndex source = 0; source < graph.vertex_count(); ++source) {
      const auto search = cpu_bfs(adj, source, {}, work);
      for (VertexIndex target = 0; target < graph.vertex_count(); ++target) {
        work.tick();
        if (search.distances[target] < 0) continue;
        ++count;
        if (enumerate) {
          work.output(count);
          rows.push_back(json::object{{"source", id_json(graph.external_id(source))},
                                      {"target", id_json(graph.external_id(target))}});
        }
      }
    }
  } else {
    require(args.contains("query_pairs") && args.at("query_pairs").is_array() &&
                !args.at("query_pairs").as_array().empty(),
            "Supply nonempty query_pairs");
    const auto& pairs = args.at("query_pairs").as_array();
    require(mode != "single_pair" || pairs.size() == 1, "single_pair requires exactly one pair");
    work.output(pairs.size());
    std::map<VertexIndex, Search> searches;
    for (const auto& pair : pairs) {
      const auto endpoints = vertices(graph, pair, "query pair", true);
      require(endpoints.size() == 2, "Query pairs require two IDs");
      const auto [it, inserted] = searches.try_emplace(endpoints[0]);
      if (inserted) it->second = cpu_bfs(adj, endpoints[0], {}, work);
      const bool reachable = it->second.distances[endpoints[1]] >= 0;
      count += reachable;
      rows.push_back(json::object{{"source", pair.as_array()[0]},
                                  {"target", pair.as_array()[1]},
                                  {"reachable", reachable}});
    }
  }
  const bool pairs_complete = mode != "full_transitive_closure" || enumerate;
  return output(
      {{"query_mode", mode},
       {"query_pairs",
        args.contains("query_pairs") ? args.at("query_pairs") : json::value(nullptr)},
       {"enumerate_closure_edges", enumerate}},
      {{"count", count}, {"pairs", pairs_complete ? json::value(rows) : json::value(nullptr)}},
      {{"count", result_port("scalar", count)},
       {"pairs", result_port("table", rows, pairs_complete)}});
}
json::object overlapping_communities(const Graph& graph, const json::object& args,
                                     const std::string&, int, Work& work) {
  using namespace family_util;
  fields(args, {"k", "minimum_community_size", "include_unassigned_vertices"}, {"k"});
  require(!graph.directed(), "Clique percolation requires undirected input");
  const auto k = natural(args, "k", 2, 2), minimum = natural(args, "minimum_community_size", 1, 1);
  const bool unassigned = boolean(args, "include_unassigned_vertices", true);
  const auto adj = adjacency(graph, work);
  std::vector<Vertices> cliques;
  if (k <= graph.vertex_count())
    enumerate_maximal_cliques(
        adj,
        [&](const Vertices& clique) {
          if (clique.size() >= k) {
            work.tick(clique.size());
            cliques.push_back(clique);
          }
          return true;
        },
        work);
  std::vector<std::size_t> parent(cliques.size());
  std::iota(parent.begin(), parent.end(), 0);
  auto root = [&](std::size_t v) {
    while (parent[v] != v) {
      work.tick();
      parent[v] = parent[parent[v]];
      v = parent[v];
    }
    return v;
  };
  for (std::size_t i = 0; i < cliques.size(); ++i)
    for (std::size_t j = i + 1; j < cliques.size(); ++j) {
      work.tick(cliques[i].size() + cliques[j].size());
      Vertices common;
      std::set_intersection(cliques[i].begin(), cliques[i].end(), cliques[j].begin(),
                            cliques[j].end(), std::back_inserter(common));
      if (common.size() >= k - 1) parent[root(j)] = root(i);
    }
  std::map<std::size_t, std::set<VertexIndex>> communities;
  std::vector<bool> assigned(graph.vertex_count(), false);
  for (std::size_t i = 0; i < cliques.size(); ++i) {
    auto& group = communities[root(i)];
    for (const auto v : cliques[i]) {
      work.tick();
      group.insert(v);
      assigned[v] = true;
    }
  }
  json::array rows;
  std::uint64_t output_items = 0;
  for (const auto& [_, group] : communities)
    if (group.size() >= minimum) {
      output_items += 1 + group.size();
      work.output(output_items);
      rows.push_back(json::object{{"group", rows.size()},
                                  {"vertices", ids(graph, Vertices(group.begin(), group.end()))},
                                  {"size", group.size()}});
    }
  json::object data{{"groups", rows}, {"count", rows.size()}};
  if (unassigned) {
    Vertices others;
    for (VertexIndex v = 0; v < graph.vertex_count(); ++v)
      if (!assigned[v]) others.push_back(v);
    work.output(output_items + others.size());
    data["unassigned_vertices"] = ids(graph, others);
  }
  return output(
      {{"k", k}, {"minimum_community_size", minimum}, {"include_unassigned_vertices", unassigned}},
      data, {{"groups", result_port("vertex_groups", rows)}});
}
}  // namespace graphmine::runtime
