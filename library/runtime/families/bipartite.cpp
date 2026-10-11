#include <array>

#include "family_util.hpp"

namespace graphmine::runtime {
namespace {
using namespace family_util;
std::vector<bool> partition(const Graph& graph, const json::object& args, bool explicit_sides) {
  require(!graph.directed(), "Bipartite operations require undirected input");
  std::vector<bool> left(graph.vertex_count(), false), seen(graph.vertex_count(), false);
  if (explicit_sides) {
    for (const auto key : {"left_partition", "right_partition"}) {
      for (const auto v : vertices(graph, args.at(key), key)) {
        require(!seen[v], "Partitions overlap");
        seen[v] = true;
        left[v] = std::string_view(key) == "left_partition";
      }
    }
    require(std::all_of(seen.begin(), seen.end(), [](bool v) { return v; }),
            "Partitions must cover every vertex, including isolates");
  } else
    for (VertexIndex v = 0; v < graph.vertex_count(); ++v) {
      const auto& attrs = graph.canonical().vertices[v].attributes;
      const auto it = attrs.find("side");
      require(it != attrs.end() && std::holds_alternative<std::string>(it->second.value()),
              "Every vertex requires attributes.side=left|right");
      const auto& side = std::get<std::string>(it->second.value());
      require(side == "left" || side == "right", "Invalid bipartite side");
      left[v] = side == "left";
    }
  return left;
}
MiningGraph bipartite_graph(const Graph& graph, const std::vector<bool>& left, bool drop_loops,
                            Work& work) {
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v && drop_loops) continue;
    require(left[u] != left[v], "Edge joins vertices on the same bipartite side");
  }
  return adjacency(graph, work);
}
}  // namespace
json::object maximal_bicliques(const Graph& graph, const json::object& args, const std::string&,
                               int, Work& work) {
  using namespace family_util;
  fields(args,
         {"left_partition", "right_partition", "minimum_left_size", "minimum_right_size",
          "result_limit"},
         {"left_partition", "right_partition"});
  const auto left = partition(graph, args, true);
  auto adj = bipartite_graph(graph, left, true, work);
  const auto minimum_left = natural(args, "minimum_left_size", 1, 1),
             minimum_right = natural(args, "minimum_right_size", 1, 1);
  const auto cap = limit(args);
  const auto n = graph.vertex_count();
  // Completing the two sides preserves maximal bicliques as maximal cliques.
  work.tick(n * (n ? n - 1 : 0) / 2);
  for (VertexIndex u = 0; u < n; ++u) {
    for (VertexIndex v = 0; v < n; ++v)
      if (u != v && left[u] == left[v]) adj[u].push_back(v);
    std::sort(adj[u].begin(), adj[u].end());
  }
  json::array rows;
  std::uint64_t output_items = 0;
  const auto complete = enumerate_maximal_cliques(
      adj,
      [&](const Vertices& clique) {
        Vertices l, r;
        for (auto v : clique) (left[v] ? l : r).push_back(v);
        if (l.size() < minimum_left || r.size() < minimum_right) return true;
        if (cap && rows.size() == *cap) return false;
        output_items += 1 + clique.size();
        work.output(output_items);
        rows.push_back(
            json::object{{"left_vertices", ids(graph, l)}, {"right_vertices", ids(graph, r)}});
        return true;
      },
      work);
  json::object data{{"bicliques", rows}, {"returned_count", rows.size()}, {"complete", complete}};
  if (complete) data["total_count"] = rows.size();
  return output({{"left_partition", args.at("left_partition")},
                 {"right_partition", args.at("right_partition")},
                 {"minimum_left_size", minimum_left},
                 {"minimum_right_size", minimum_right},
                 {"result_limit", cap ? json::value(*cap) : json::value(nullptr)}},
                data, {{"bicliques", result_port("bipartite_groups", rows, complete)}}, complete);
}
json::object butterflies(const Graph& graph, const json::object& args, const std::string&, int,
                         Work& work) {
  using namespace family_util;
  fields(args, {"mode", "alpha", "beta", "core_measure", "solution_quality"});
  const auto mode =
      choice(args, "mode", "count", {"count", "per_vertex", "per_edge", "alpha_beta_core"});
  const auto measure = choice(args, "core_measure", "butterfly_participation",
                              {"butterfly_participation", "degree"});
  const auto quality = choice(args, "solution_quality", "exact", {"exact", "approximate"});
  const auto alpha = limit(args, "alpha"), beta = limit(args, "beta");
  require(mode == "alpha_beta_core" || (!alpha && !beta && measure == "butterfly_participation"),
          "alpha, beta and core_measure apply only to alpha_beta_core");
  const auto left = partition(graph, args, false);
  const auto adj = bipartite_graph(graph, left, false, work);
  const auto n = graph.vertex_count();
  std::vector<std::uint64_t> per_vertex(n, 0);
  std::map<std::pair<VertexIndex, VertexIndex>, std::uint64_t> per_edge;
  for (VertexIndex u = 0; u < n; ++u)
    for (const auto v : adj[u])
      if (u < v) per_edge[{u, v}] = 0;
  std::vector<std::array<VertexIndex, 4>> instances;
  std::uint64_t count = 0;
  for (VertexIndex u = 0; u < n; ++u)
    if (left[u])
      for (VertexIndex v = u + 1; v < n; ++v)
        if (left[v]) {
          work.tick(adj[u].size() + adj[v].size());
          Vertices common;
          std::set_intersection(adj[u].begin(), adj[u].end(), adj[v].begin(), adj[v].end(),
                                std::back_inserter(common));
          for (std::size_t a = 0; a < common.size(); ++a)
            for (std::size_t b = a + 1; b < common.size(); ++b) {
              work.tick();
              if (count == UINT64_MAX)
                throw Failure("resource_limit", "Butterfly count exceeds uint64");
              ++count;
              const std::array<VertexIndex, 4> instance{u, v, common[a], common[b]};
              for (const auto vertex : instance) ++per_vertex[vertex];
              for (const auto x : {u, v})
                for (const auto y : {common[a], common[b]}) ++per_edge[std::minmax(x, y)];
              if (mode == "alpha_beta_core" && measure == "butterfly_participation")
                instances.push_back(instance);
            }
        }
  json::object data{{"butterfly_count", count}, {"complete", true}},
      ports{{"count", result_port("scalar", count)}};
  if (mode == "per_vertex") {
    work.output(n);
    json::array rows;
    for (VertexIndex v = 0; v < n; ++v)
      rows.push_back(
          json::object{{"vertex", id_json(graph.external_id(v))}, {"count", per_vertex[v]}});
    data["vertices"] = rows;
    auto p = result_port("vertex_scores", rows);
    p["score_field"] = "count";
    ports["scores"] = p;
  } else if (mode == "per_edge") {
    work.output(per_edge.size());
    json::array rows;
    for (const auto& [ends, value] : per_edge)
      rows.push_back(json::object{{"source", id_json(graph.external_id(ends.first))},
                                  {"target", id_json(graph.external_id(ends.second))},
                                  {"count", value}});
    data["edges"] = rows;
    auto p = result_port("edge_scores", rows);
    p["score_field"] = "count";
    ports["edges"] = p;
  } else if (mode == "alpha_beta_core") {
    std::uint64_t maximum_left = 0, maximum_right = 0;
    for (VertexIndex v = 0; v < n; ++v) {
      auto& maximum = left[v] ? maximum_left : maximum_right;
      maximum =
          std::max<std::uint64_t>(maximum, measure == "degree" ? adj[v].size() : per_vertex[v]);
    }
    json::array rows;
    std::uint64_t output_items = 0;
    for (std::uint64_t a = alpha.value_or(1); a <= alpha.value_or(maximum_left); ++a) {
      for (std::uint64_t b = beta.value_or(1); b <= beta.value_or(maximum_right); ++b) {
        work.tick(n);
        std::vector<bool> remaining(n, true);
        for (;;) {
          work.tick(n);
          std::vector<std::uint64_t> values(n, 0);
          if (measure == "degree") {
            for (VertexIndex u = 0; u < n; ++u)
              if (remaining[u])
                for (const auto v : adj[u]) {
                  work.tick();
                  values[u] += remaining[v];
                }
          } else
            for (const auto& instance : instances) {
              work.tick();
              if (std::all_of(instance.begin(), instance.end(),
                              [&](auto v) { return remaining[v]; }))
                for (const auto v : instance) ++values[v];
            }
          bool changed = false;
          for (VertexIndex v = 0; v < n; ++v)
            if (remaining[v] && values[v] < (left[v] ? a : b)) {
              remaining[v] = false;
              changed = true;
            }
          if (!changed) break;
        }
        Vertices selected;
        for (VertexIndex v = 0; v < n; ++v)
          if (remaining[v]) selected.push_back(v);
        output_items += 1 + selected.size();
        work.output(output_items);
        rows.push_back(json::object{{"alpha", a}, {"beta", b}, {"vertices", ids(graph, selected)}});
        if (b == UINT64_MAX) break;
      }
      if (a == UINT64_MAX) break;
    }
    data["cores"] = rows;
    data["core_measure"] = measure;
    ports["cores"] = result_port("vertex_groups", rows);
  }
  return output({{"mode", mode},
                 {"alpha", alpha ? json::value(*alpha) : json::value(nullptr)},
                 {"beta", beta ? json::value(*beta) : json::value(nullptr)},
                 {"core_measure", measure},
                 {"solution_quality", quality}},
                data, ports);
}
}  // namespace graphmine::runtime
