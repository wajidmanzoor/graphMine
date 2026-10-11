#include <algorithm>
#include <functional>
#include <numeric>
#include <queue>
#include <set>

#include "internal.hpp"

namespace graphmine::runtime {
namespace {
using Vertices = std::vector<VertexIndex>;
using Groups = std::vector<Vertices>;
Vertices intersect(const Vertices& a, const Vertices& b, Work& work) {
  work.tick(a.size() + b.size());
  Vertices output;
  std::set_intersection(a.begin(), a.end(), b.begin(), b.end(), std::back_inserter(output));
  return output;
}
// Iterative Bron-Kerbosch avoids a process-stack limit on clique size. The
// callback can stop after witnessing that a requested output cap is exceeded.
bool maximal(const MiningGraph& adj, const std::function<bool(const Vertices&)>& emit,
             const std::function<std::size_t()>& lower, Work& work) {
  if (adj.empty()) return true;
  struct Frame {
    Vertices possible, excluded, candidates;
    std::size_t next = 0;
  };
  auto frame = [&](Vertices possible, Vertices excluded) {
    work.tick(possible.size() + excluded.size());
    VertexIndex pivot = adj.size();
    std::size_t score = 0;
    for (const auto* values : {&possible, &excluded})
      for (const auto v : *values) {
        const auto size = intersect(possible, adj[v], work).size();
        if (pivot == adj.size() || size > score) {
          pivot = v;
          score = size;
        }
      }
    Vertices candidates;
    if (pivot != adj.size()) {
      work.tick(possible.size() + adj[pivot].size());
      std::set_difference(possible.begin(), possible.end(), adj[pivot].begin(), adj[pivot].end(),
                          std::back_inserter(candidates));
    }
    return Frame{std::move(possible), std::move(excluded), std::move(candidates), 0};
  };
  Vertices all(adj.size()), current;
  std::iota(all.begin(), all.end(), 0);
  std::vector<Frame> stack;
  stack.push_back(frame(std::move(all), {}));
  while (!stack.empty()) {
    work.tick();
    auto& top = stack.back();
    if (top.possible.empty() && top.excluded.empty()) {
      auto clique = current;
      std::sort(clique.begin(), clique.end());
      if (!emit(clique)) return false;
      stack.pop_back();
      if (!current.empty()) current.pop_back();
      continue;
    }
    if (top.next == top.candidates.size() || current.size() + top.possible.size() < lower()) {
      stack.pop_back();
      if (!current.empty()) current.pop_back();
      continue;
    }
    const auto v = top.candidates[top.next++];
    auto possible = intersect(top.possible, adj[v], work),
         excluded = intersect(top.excluded, adj[v], work);
    top.possible.erase(std::lower_bound(top.possible.begin(), top.possible.end(), v));
    top.excluded.insert(std::lower_bound(top.excluded.begin(), top.excluded.end(), v), v);
    current.push_back(v);
    stack.push_back(frame(std::move(possible), std::move(excluded)));
  }
  return true;
}
json::array external(const Graph& graph, const Vertices& vertices) {
  json::array values;
  for (const auto v : vertices) values.push_back(id_json(graph.external_id(v)));
  return values;
}
json::object group_output(const Graph& graph, Groups values, json::object parameters,
                          bool complete = true) {
  for (auto& group : values) std::sort(group.begin(), group.end());
  std::sort(values.begin(), values.end(), [](const auto& a, const auto& b) {
    return a.size() != b.size() ? a.size() > b.size() : a < b;
  });
  json::array rows;
  for (const auto& group : values)
    rows.push_back(json::object{
        {"group", rows.size()}, {"vertices", external(graph, group)}, {"size", group.size()}});
  return {{"parameters", parameters},
          {"result", {{"groups", rows}, {"count", rows.size()}}},
          {"ports", {{"groups", result_port("vertex_groups", rows, complete)}}},
          {"complete", complete},
          {"quality", "exact"}};
}
std::optional<std::uint64_t> result_limit(const json::object& args) {
  if (!args.contains("result_limit") || args.at("result_limit").is_null()) return {};
  const auto limit = uint(args.at("result_limit"), "result_limit");
  require(limit > 0, "result_limit must be positive");
  return limit;
}
void clique_witness(const MiningGraph& adj, Vertices& vertices, Work& work) {
  std::sort(vertices.begin(), vertices.end());
  require(std::adjacent_find(vertices.begin(), vertices.end()) == vertices.end(),
          "GPU clique repeats a vertex");
  for (const auto v : vertices) require(v < adj.size(), "GPU clique has an unknown vertex");
  for (std::size_t i = 0; i < vertices.size(); ++i)
    for (std::size_t j = i + 1; j < vertices.size(); ++j) {
      work.tick();
      require(std::binary_search(adj[vertices[i]].begin(), adj[vertices[i]].end(), vertices[j]),
              "GPU clique has a missing edge");
    }
}
std::size_t color_bound(const MiningGraph& adj, Work& work) {
  std::vector<std::size_t> colors(adj.size(), 0);
  std::size_t maximum = 0;
  for (VertexIndex v = 0; v < adj.size(); ++v) {
    work.tick(adj[v].size());
    std::set<std::size_t> used;
    for (const auto u : adj[v])
      if (colors[u]) used.insert(colors[u]);
    std::size_t color = 1;
    while (used.count(color)) ++color;
    colors[v] = color;
    maximum = std::max(maximum, color);
  }
  return maximum;
}
Groups maximum(const MiningGraph& adj, bool ties, const std::string& backend, int device,
               Work& work) {
  Groups result;
  std::size_t best = 0;
  Vertices witness;
  if (backend != "cpp") {
    witness = original_maximum_clique(adj, backend, device, work);
    clique_witness(adj, witness, work);
    best = witness.size();
    if (best) result.push_back(witness);
    if (!ties && color_bound(adj, work) == best) return result;
  }
  if (ties) result.clear();
  maximal(
      adj,
      [&](const Vertices& clique) {
        if (clique.size() > best) {
          best = clique.size();
          result.clear();
        }
        if (clique.size() == best && (ties || result.empty())) {
          work.output(result.size() + 1);
          result.push_back(clique);
        }
        return true;
      },
      [&] { return best; }, work);
  if (backend != "cpp" && best != witness.size())
    throw Failure("correctness_mismatch",
                  "Original GPU maximum disagrees with the bounded native proof");
  return result;
}
MiningGraph complement(const MiningGraph& adj, Work& work) {
  work.tick(static_cast<std::uint64_t>(adj.size()) * adj.size());
  MiningGraph output(adj.size());
  for (VertexIndex u = 0; u < adj.size(); ++u)
    for (VertexIndex v = 0; v < adj.size(); ++v)
      if (u != v && !std::binary_search(adj[u].begin(), adj[u].end(), v)) output[u].push_back(v);
  return output;
}
}  // namespace

bool enumerate_maximal_cliques(const MiningGraph& adj,
                               const std::function<bool(const std::vector<VertexIndex>&)>& emit,
                               Work& work) {
  return maximal(adj, emit, [] { return 0; }, work);
}

json::object maximal_cliques(const Graph& graph, const json::object& args,
                             const std::string& backend, int device, Work& work) {
  fields(args, {"minimum_clique_size", "result_limit"});
  require(!graph.directed(), "Maximal cliques require an undirected graph");
  const auto minimum = args.contains("minimum_clique_size")
                           ? uint(args.at("minimum_clique_size"), "minimum_clique_size")
                           : 1;
  require(minimum > 0, "minimum_clique_size must be positive");
  const auto limit = result_limit(args);
  const auto adj = adjacency(graph, work);
  Groups values;
  std::uint64_t unfiltered = 0;
  std::optional<std::uint64_t> gpu_count;
  if (backend != "cpp") gpu_count = original_maximal_count(adj, backend, device, work);
  const bool complete = maximal(
      adj,
      [&](const Vertices& clique) {
        if (unfiltered == UINT64_MAX)
          throw Failure("resource_limit", "Maximal clique count exceeds uint64");
        ++unfiltered;
        if (clique.size() < minimum) return true;
        if (limit && values.size() == *limit) return false;
        work.output(values.size() + 1);
        values.push_back(clique);
        return true;
      },
      [] { return 0; }, work);
  if (gpu_count && ((complete && *gpu_count != unfiltered) || *gpu_count < unfiltered))
    throw Failure("correctness_mismatch",
                  "Original GPU maximal count disagrees with native materialization");
  auto output = group_output(graph, std::move(values),
                             {{"minimum_clique_size", minimum},
                              {"result_limit", limit ? json::value(*limit) : json::value(nullptr)}},
                             complete);
  output.at("result").as_object()["count_is_exhaustive"] = complete;
  if (gpu_count)
    output["diagnostics"] = json::object{{"unfiltered_gpu_total", *gpu_count},
                                         {"materialization", "bounded_native_bron_kerbosch"}};
  return output;
}

json::object maximum_clique(const Graph& graph, const json::object& args,
                            const std::string& backend, int device, Work& work) {
  fields(args, {"return_all_ties"});
  require(!graph.directed(), "Maximum clique requires an undirected graph");
  const auto ties = boolean(args, "return_all_ties", false);
  const auto adj = adjacency(graph, work);
  auto values = maximum(adj, ties, backend, device, work);
  auto output = group_output(graph, values, {{"return_all_ties", ties}});
  output.at("result").as_object()["maximum_size"] = values.empty() ? 0 : values.front().size();
  output.at("ports").as_object()["vertices"] =
      result_port("vertex_set", values.empty() ? json::array{} : external(graph, values.front()));
  if (backend != "cpp")
    output["diagnostics"] = json::object{
        {"optimality", "GPU witness checked by native coloring bound or bounded exact search"},
        {"all_ties", ties ? "native materialization" : "not requested"}};
  return output;
}

json::object k_cliques(const Graph& graph, const json::object& args, const std::string& backend,
                       int device, Work& work) {
  fields(args, {"k", "mode", "result_limit"}, {"k"});
  require(!graph.directed(), "k-cliques requires an undirected graph");
  const auto k = uint(args.at("k"), "k");
  require(k >= 2, "k must be at least two");
  const auto mode = args.contains("mode") ? string(args.at("mode"), "mode") : "count";
  require(mode == "count" || mode == "enumerate", "mode must be count or enumerate");
  const auto limit = result_limit(args);
  const auto adj = adjacency(graph, work);
  std::uint64_t count = 0;
  Groups values;
  std::optional<std::uint64_t> gpu_count;
  if (backend != "cpp" && k <= adj.size())
    gpu_count = original_k_clique_count(adj, static_cast<std::uint32_t>(k), backend, device, work);
  if (k <= adj.size() && (!gpu_count || mode == "enumerate")) {
    struct Frame {
      Vertices possible;
      std::size_t next = 0;
    };
    Vertices all(adj.size()), current;
    std::iota(all.begin(), all.end(), 0);
    std::vector<Frame> stack{{std::move(all), 0}};
    while (!stack.empty()) {
      work.tick();
      auto& top = stack.back();
      if (current.size() == k) {
        if (count == UINT64_MAX)
          throw Failure("resource_limit", "Fixed-size clique count exceeds uint64");
        ++count;
        if (mode == "enumerate" && (!limit || values.size() < *limit)) {
          work.output(values.size() + 1);
          values.push_back(current);
        }
        stack.pop_back();
        current.pop_back();
        continue;
      }
      if (top.possible.size() - top.next + current.size() < k) {
        stack.pop_back();
        if (!current.empty()) current.pop_back();
        continue;
      }
      const auto v = top.possible[top.next++];
      Vertices remaining(top.possible.begin() + top.next, top.possible.end());
      auto next = intersect(remaining, adj[v], work);
      current.push_back(v);
      stack.push_back({std::move(next), 0});
    }
    if (gpu_count && *gpu_count != count)
      throw Failure("correctness_mismatch",
                    "Original GPU k-clique count disagrees with native materialization");
  } else if (gpu_count)
    count = *gpu_count;
  const bool listed_complete = mode == "enumerate" && values.size() == count;
  auto output = group_output(graph, values,
                             {{"k", k},
                              {"mode", mode},
                              {"result_limit", limit ? json::value(*limit) : json::value(nullptr)}},
                             listed_complete);
  auto& result = output.at("result").as_object();
  result["count"] = count;
  result["k"] = k;
  result["listed_count"] = values.size();
  result["count_is_exhaustive"] = true;
  output.at("ports").as_object()["count"] = result_port("scalar", count);
  output["complete"] = mode == "count" || listed_complete;
  if (backend != "cpp")
    output["diagnostics"] = json::object{
        {"materialization", mode == "enumerate"
                                ? "bounded native enumeration verified against original GPU count"
                                : "original GPU count"}};
  return output;
}

json::object core_numbers(const Graph& graph, const json::object& args, const std::string& backend,
                          int device, Work& work) {
  fields(args, {"requested_k"});
  require(!graph.directed(), "k-core requires an undirected graph");
  std::optional<std::uint64_t> k;
  if (args.contains("requested_k") && !args.at("requested_k").is_null())
    k = uint(args.at("requested_k"), "requested_k");
  work.output(graph.vertex_count());
  const auto adj = adjacency(graph, work);
  std::vector<std::uint32_t> values(adj.size(), 0);
  if (backend == "cpp") {
    using Item = std::pair<std::uint32_t, VertexIndex>;
    std::priority_queue<Item, std::vector<Item>, std::greater<Item>> queue;
    for (VertexIndex v = 0; v < adj.size(); ++v) {
      values[v] = adj[v].size();
      queue.emplace(values[v], v);
    }
    std::vector<bool> removed(adj.size(), false);
    while (!queue.empty()) {
      work.tick();
      const auto [degree, u] = queue.top();
      queue.pop();
      if (removed[u] || values[u] != degree) continue;
      removed[u] = true;
      for (const auto v : adj[u]) {
        work.tick();
        if (!removed[v] && values[v] > degree) {
          --values[v];
          queue.emplace(values[v], v);
        }
      }
    }
  } else if (backend == "libcugraph")
    values = cugraph_core_numbers(weighted_graph(graph, false, false, "collapse", "outgoing", work),
                                  device, work);
  else
    values = original_core_numbers(adj, device, work);
  require(values.size() == graph.vertex_count(), "GPU core numbers lost vertices");
  json::array rows, selected;
  for (VertexIndex v = 0; v < values.size(); ++v) {
    require(values[v] <= adj[v].size(), "Core number exceeds vertex degree");
    rows.push_back(
        json::object{{"vertex", id_json(graph.external_id(v))}, {"core_number", values[v]}});
    if (k && values[v] >= *k) selected.push_back(id_json(graph.external_id(v)));
  }
  auto port = result_port("vertex_scores", rows);
  port["score_field"] = "core_number";
  json::object output{{"parameters", {{"requested_k", k ? json::value(*k) : json::value(nullptr)}}},
                      {"result", {{"vertices", rows}}},
                      {"ports", {{"scores", port}}},
                      {"complete", true},
                      {"quality", "exact"}};
  if (k) {
    output.at("result").as_object()["selected_vertices"] = selected;
    output.at("ports").as_object()["vertices"] = result_port("vertex_set", selected);
  }
  return output;
}

json::object maximum_independent_set(const Graph& graph, const json::object& args,
                                     const std::string& backend, int device, Work& work) {
  fields(args, {"mode"});
  require(!graph.directed(), "Maximum independent set requires an undirected graph");
  require(!args.contains("mode") || args.at("mode") == "exact", "Only exact mode is supported");
  const auto sets = maximum(complement(adjacency(graph, work), work), false, backend, device, work);
  const auto vertices = sets.empty() ? json::array{} : external(graph, sets.front());
  work.output(vertices.size());
  return {
      {"parameters", {{"mode", "exact"}}},
      {"result", {{"vertices", vertices}, {"size", vertices.size()}, {"maximum_certified", true}}},
      {"ports", {{"vertices", result_port("vertex_set", vertices)}}},
      {"complete", true},
      {"quality", "exact"}};
}

json::object minimum_vertex_cover(const Graph& graph, const json::object& args,
                                  const std::string& backend, int device, Work& work) {
  fields(args, {"mode", "k"});
  require(!graph.directed(), "Minimum vertex cover requires an undirected graph");
  const auto mode = args.contains("mode") ? string(args.at("mode"), "mode") : "exact";
  require(mode == "exact" || mode == "decision", "Unknown vertex-cover mode");
  std::optional<std::uint64_t> k;
  if (args.contains("k") && !args.at("k").is_null()) k = uint(args.at("k"), "k");
  require(mode != "decision" || k, "Decision mode requires k");
  const auto sets = maximum(complement(adjacency(graph, work), work), false, backend, device, work);
  Vertices independent = sets.empty() ? Vertices{} : sets.front();
  std::sort(independent.begin(), independent.end());
  json::array vertices;
  for (VertexIndex v = 0; v < graph.vertex_count(); ++v)
    if (!std::binary_search(independent.begin(), independent.end(), v))
      vertices.push_back(id_json(graph.external_id(v)));
  work.output(vertices.size());
  json::object result{
      {"vertices", vertices}, {"size", vertices.size()}, {"minimum_certified", true}};
  if (mode == "decision") result["exists"] = vertices.size() <= *k;
  return {{"parameters", {{"mode", mode}, {"k", k ? json::value(*k) : json::value(nullptr)}}},
          {"result", result},
          {"ports", {{"vertices", result_port("vertex_set", vertices)}}},
          {"complete", true},
          {"quality", "exact"}};
}
}  // namespace graphmine::runtime
