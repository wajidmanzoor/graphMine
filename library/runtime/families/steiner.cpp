#include "family_util.hpp"

namespace graphmine::runtime {
json::object group_steiner(const Graph& graph, const json::object& args, const std::string&, int,
                           Work& work) {
  using namespace family_util;
  fields(args, {"groups", "required_vertices", "solution_quality"}, {"groups"});
  require(!graph.directed(), "Group Steiner requires undirected input");
  const auto quality = choice(args, "solution_quality", "exact", {"exact", "approximate"});
  require(args.at("groups").is_array() && !args.at("groups").as_array().empty(),
          "groups must contain nonempty vertex arrays");
  std::vector<Vertices> groups;
  for (const auto& raw : args.at("groups").as_array()) {
    auto group = vertices(graph, raw, "group", true);
    require(!group.empty(), "Group must be nonempty");
    groups.push_back(std::move(group));
  }
  Vertices required;
  if (args.contains("required_vertices") && !args.at("required_vertices").is_null())
    required = vertices(graph, args.at("required_vertices"), "required_vertices", true);
  struct Edge {
    VertexIndex u, v;
    Exact weight;
    std::size_t index;
  };
  std::map<std::pair<VertexIndex, VertexIndex>, Edge> normalized;
  for (std::size_t i = 0; i < graph.edge_count(); ++i) {
    work.tick();
    const auto& edge = graph.canonical().edges[i];
    require(edge.weight && *edge.weight >= 0, "Every group-Steiner edge needs nonnegative weight");
    auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    if (u > v) std::swap(u, v);
    auto [it, inserted] =
        normalized.emplace(std::make_pair(u, v), Edge{u, v, Exact(*edge.weight), i});
    if (!inserted && Exact(*edge.weight) < it->second.weight)
      it->second = {u, v, Exact(*edge.weight), i};
  }
  std::vector<Edge> edges;
  for (const auto& [_, edge] : normalized) edges.push_back(edge);
  std::sort(edges.begin(), edges.end(), [](const auto& a, const auto& b) {
    return a.weight != b.weight ? a.weight < b.weight : a.index < b.index;
  });
  std::optional<Exact> best;
  Vertices selected;
  std::vector<std::size_t> chosen;
  const auto n = graph.vertex_count();
  for (std::size_t size = 1; size <= n; ++size) {
    combinations(n, size, work, [&](const Vertices& candidate) {
      work.tick(n);
      std::vector<bool> mask(n, false);
      for (const auto v : candidate) mask[v] = true;
      for (const auto v : required)
        if (!mask[v]) return true;
      for (const auto& group : groups) {
        work.tick(group.size());
        if (std::none_of(group.begin(), group.end(), [&](auto v) { return mask[v]; })) return true;
      }
      Vertices parent(n);
      std::iota(parent.begin(), parent.end(), 0);
      auto root = [&](VertexIndex v) {
        while (parent[v] != v) {
          work.tick();
          parent[v] = parent[parent[v]];
          v = parent[v];
        }
        return v;
      };
      Exact cost = 0;
      std::vector<std::size_t> tree;
      for (const auto& edge : edges) {
        work.tick();
        if (!mask[edge.u] || !mask[edge.v]) continue;
        const auto u = root(edge.u), v = root(edge.v);
        if (u == v) continue;
        parent[u] = v;
        cost += edge.weight;
        tree.push_back(edge.index);
        if (best && cost >= *best) break;
        if (tree.size() + 1 == size) break;
      }
      if (tree.size() + 1 == size && (!best || cost < *best)) {
        best = cost;
        selected = candidate;
        chosen = tree;
      }
      return true;
    });
    if (best && *best == 0) break;
  }
  const json::object resolved{
      {"groups", args.at("groups")},
      {"required_vertices",
       args.contains("required_vertices") ? args.at("required_vertices") : json::value(nullptr)},
      {"solution_quality", quality}};
  if (!best)
    return output(resolved,
                  {{"feasible", false},
                   {"infeasibility_certified", true},
                   {"tree_edges", json::array{}},
                   {"tree_weight", nullptr},
                   {"selected_vertices", json::array{}},
                   {"optimal", false}},
                  {});
  json::array tree_edges, representatives;
  for (const auto i : chosen) tree_edges.push_back(id_json(graph.canonical().edges[i].id));
  for (std::size_t i = 0; i < groups.size(); ++i) {
    VertexIndex representative = n;
    for (const auto v : groups[i])
      if (std::binary_search(selected.begin(), selected.end(), v))
        representative = std::min(representative, v);
    require(representative < n, "Group coverage certificate failed");
    representatives.push_back(
        json::object{{"group", i}, {"vertex", id_json(graph.external_id(representative))}});
  }
  work.output(selected.size() + chosen.size() + groups.size());
  const auto vertex_ids = ids(graph, selected);
  json::object data{{"feasible", true},
                    {"tree_edges", tree_edges},
                    {"selected_vertices", vertex_ids},
                    {"group_representatives", representatives},
                    {"optimal", true},
                    {"tree_weight_fraction", best->str()}};
  exact_field(data, "tree_weight", *best);
  auto result = output(resolved, data,
                       {{"vertices", result_port("vertex_set", vertex_ids)},
                        {"edges", result_port("edge_set", tree_edges)}});
  result["diagnostics"] = json::object{{"solver", "native_vertex_subset_MST_optimization"},
                                       {"arithmetic", "exact rational"},
                                       {"tree_and_group_coverage_checked", true}};
  return result;
}
}  // namespace graphmine::runtime
