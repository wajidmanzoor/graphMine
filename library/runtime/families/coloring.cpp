#include <algorithm>
#include <numeric>
#include <set>

#include "internal.hpp"
#include "native_random.hpp"
#include "view_profiles.hpp"

namespace graphmine::runtime {
namespace {
constexpr const char* adjacency_spec = R"({"kind":"csr","direction":"keep","self_loops":"drop",
  "parallel_edges":"collapse:first","weights":"none","sorted_neighbors":true})";
const ViewProfile independent_profile{"maximal-independent-set:cpp:default", {"maximal-independent-set"}, adjacency_spec};
const ViewProfile coloring_profile{"vertex-coloring:cpp:default", {"vertex-coloring"}, adjacency_spec};
MiningGraph conflicts(const Graph& graph, unsigned distance, const ViewProfile& profile,
                       const std::string& backend, Work& work) {
  require(!graph.directed(), "Independent sets and coloring require undirected input");
  work.tick(graph.vertex_count());
  MiningGraph adj;
  if (backend == "cpp") {
    const auto input = consume_view(graph, profile, work, ViewBudget::original_edges);
    adj = adjacency_layout(std::get<CsrView>(input->view));
  } else adj = adjacency(graph, work);
  if (distance == 1) return adj;
  MiningGraph output(adj.size());
  for (VertexIndex u = 0; u < adj.size(); ++u) {
    std::set<VertexIndex> row;
    for (const auto v : adj[u]) {
      work.tick();
      row.insert(v);
      for (const auto w : adj[v]) {
        work.tick();
        if (w != u) row.insert(w);
      }
    }
    output[u].assign(row.begin(), row.end());
  }
  return output;
}
std::vector<VertexIndex> order(const MiningGraph& adj, NativeRandom& rng, Work& work) {
  work.tick(adj.size());
  std::vector<VertexIndex> result(adj.size());
  std::iota(result.begin(), result.end(), 0);
  rng.shuffle(result, work);
  return result;
}
}  // namespace
json::object maximal_independent(const Graph& graph, const json::object& args,
                                 const std::string& backend, int device, Work& work) {
  fields(args, {"random_seed"});
  NativeRandom rng(args);
  const auto adj = conflicts(graph, 1, independent_profile, backend, work);
  std::vector<VertexIndex> chosen;
  if (backend == "cpp") {
    std::vector<bool> blocked(adj.size(), false);
    for (const auto u : order(adj, rng, work))
      if (!blocked[u]) {
        work.tick();
        chosen.push_back(u);
        blocked[u] = true;
        for (const auto v : adj[u]) {
          work.tick();
          blocked[v] = true;
        }
      }
  } else
    chosen = cugraph_maximal_independent(adj, rng.seed, device, work);
  std::vector<bool> selected(adj.size(), false), covered(adj.size(), false);
  for (const auto u : chosen) {
    if (u >= adj.size() || selected[u])
      throw Failure("correctness_mismatch", "Independent set has an invalid or duplicate vertex");
    selected[u] = covered[u] = true;
  }
  for (const auto u : chosen)
    for (const auto v : adj[u]) {
      work.tick();
      if (selected[v]) throw Failure("correctness_mismatch", "Selected vertices are adjacent");
      covered[v] = true;
    }
  if (!std::all_of(covered.begin(), covered.end(), [](bool value) { return value; }))
    throw Failure("correctness_mismatch", "Independent set is not maximal");
  work.output(chosen.size());
  std::sort(chosen.begin(), chosen.end());
  json::array ids;
  for (const auto u : chosen) ids.push_back(id_json(graph.external_id(u)));
  return {{"parameters", {{"random_seed", rng.seed}}},
          {"result", {{"vertices", ids}, {"size", ids.size()}, {"maximal", true}}},
          {"ports", {{"vertices", result_port("vertex_set", ids)}}},
          {"complete", true},
          {"quality", "exact"},
          {"diagnostics",
           {{"random_seed", rng.seed},
            {"maximum_cardinality_claimed", false},
            {"verified", "independence and maximality"}}}};
}
json::object vertex_coloring(const Graph& graph, const json::object& args,
                             const std::string& backend, int device, Work& work) {
  fields(args, {"distance", "random_seed"});
  const auto distance = args.contains("distance") ? uint(args.at("distance"), "distance") : 1;
  require(distance == 1 || distance == 2, "Coloring distance must be 1 or 2");
  NativeRandom rng(args);
  const auto adj = conflicts(graph, distance, coloring_profile, backend, work);
  work.output(adj.size());
  std::vector<std::uint32_t> colors;
  if (backend == "cpp") {
    colors.assign(adj.size(), UINT32_MAX);
    for (const auto u : order(adj, rng, work)) {
      std::set<std::uint32_t> used;
      for (const auto v : adj[u]) {
        work.tick();
        if (colors[v] != UINT32_MAX) used.insert(colors[v]);
      }
      std::uint32_t color = 0;
      while (used.count(color)) {
        work.tick();
        ++color;
      }
      colors[u] = color;
    }
  } else
    colors = cugraph_vertex_coloring(adj, rng.seed, device, work);
  if (colors.size() != adj.size()) throw Failure("correctness_mismatch", "Coloring omits vertices");
  std::map<std::uint32_t, std::uint32_t> labels;
  json::array rows;
  for (VertexIndex u = 0; u < adj.size(); ++u) {
    for (const auto v : adj[u]) {
      work.tick();
      if (colors[u] == colors[v])
        throw Failure("correctness_mismatch", "Coloring conflicts at the requested distance");
    }
    const auto label = labels.emplace(colors[u], labels.size()).first->second;
    rows.push_back(json::object{{"vertex", id_json(graph.external_id(u))}, {"color", label}});
  }
  return {{"parameters", {{"distance", distance}, {"random_seed", rng.seed}}},
          {"result", {{"colors", rows}, {"color_count", labels.size()}, {"proper", true}}},
          {"ports", {{"colors", result_port("table", rows)}}},
          {"complete", true},
          {"quality", "heuristic"},
          {"diagnostics",
           {{"random_seed", rng.seed},
            {"minimum_color_count_claimed", false},
            {"verified", "proper coloring on the distance conflict graph"}}}};
}
}  // namespace graphmine::runtime
