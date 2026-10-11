#include <algorithm>
#include <boost/graph/adjacency_list.hpp>
#include <boost/graph/maximum_weighted_matching.hpp>
#include <map>
#include <numeric>
#include <queue>
#include <set>

#include "exact_number.hpp"
#include "internal.hpp"

namespace graphmine::runtime {
namespace {
struct Edge {
  VertexIndex u, v;
  std::size_t original;
  Exact value;
};
using Edges = std::vector<Edge>;
std::string quality(const json::object& args) {
  const auto value = args.contains("solution_quality")
                         ? string(args.at("solution_quality"), "solution_quality")
                         : "exact";
  require(value == "exact" || value == "approximate", "Unknown solution_quality");
  return value;
}
std::vector<bool> sides(const Graph& graph, Work& work) {
  std::vector<bool> left;
  for (const auto& vertex : graph.canonical().vertices) {
    work.tick();
    const auto found = vertex.attributes.find("side");
    require(found != vertex.attributes.end() &&
                std::holds_alternative<std::string>(found->second.value()),
            "Every vertex requires attributes.side = left or right");
    const auto& label = std::get<std::string>(found->second.value());
    require(label == "left" || label == "right", "Invalid bipartite side label");
    left.push_back(label == "left");
  }
  return left;
}
Edges normalized(const Graph& graph, const std::vector<bool>* left, const std::string& objective,
                 Work& work) {
  require(!graph.directed(), "Matching requires an undirected graph");
  std::map<std::pair<VertexIndex, VertexIndex>, Edge> unique;
  for (std::size_t i = 0; i < graph.edge_count(); ++i) {
    work.tick();
    const auto& edge = graph.canonical().edges[i];
    auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (left) {
      require((*left)[u] != (*left)[v], "An edge joins vertices on the same bipartite side");
      if (!(*left)[u]) std::swap(u, v);
    } else if (v < u)
      std::swap(u, v);
    const bool weighted = objective != "maximum_cardinality";
    require(!weighted || edge.weight.has_value(), "Weighted matching requires every edge weight");
    const Exact value = weighted ? Exact(*edge.weight) : Exact(1);
    require(left || value >= 0, "General weighted matching requires nonnegative weights");
    if (u == v) continue;
    const auto pair = std::make_pair(u, v);
    auto found = unique.find(pair);
    const bool better =
        found != unique.end() &&
        (objective == "minimum_cost" ? value < found->second.value : value > found->second.value);
    if (found == unique.end() || better) unique[pair] = {u, v, i, value};
  }
  Edges output;
  for (auto& [key, edge] : unique) output.push_back(std::move(edge));
  return output;
}
json::object selected_output(const Graph& graph, const Edges& edges,
                             const std::vector<std::size_t>& chosen, json::object parameters,
                             const std::vector<bool>* left, Work& work) {
  work.output(chosen.size() + (left ? graph.vertex_count() - 2 * chosen.size() : 0));
  json::array ids, rows, unmatched_left, unmatched_right;
  std::vector<bool> used(graph.vertex_count(), false);
  Exact total = 0;
  for (const auto index : chosen) {
    work.tick();
    const auto& edge = edges.at(index);
    const auto& original = graph.canonical().edges[edge.original];
    require(!used[edge.u] && !used[edge.v], "Native matching repeats an endpoint");
    used[edge.u] = used[edge.v] = true;
    json::object row{{"id", id_json(original.id)},
                     {"source", id_json(graph.external_id(edge.u))},
                     {"target", id_json(graph.external_id(edge.v))}};
    exact_field(row, "weight", edge.value);
    ids.push_back(id_json(original.id));
    rows.push_back(row);
    total += edge.value;
  }
  json::object result{{"matching_edges", ids},
                      {"edges", rows},
                      {"matching_size", chosen.size()},
                      {"optimal", true},
                      {"feasible", true}};
  exact_field(result, "objective_value", total);
  exact_field(result, "total_weight", total);
  if (left) {
    for (VertexIndex v = 0; v < graph.vertex_count(); ++v)
      if (!used[v])
        ((*left)[v] ? unmatched_left : unmatched_right).push_back(id_json(graph.external_id(v)));
    result["unmatched_left_vertices"] = unmatched_left;
    result["unmatched_right_vertices"] = unmatched_right;
  }
  return {
      {"parameters", parameters},
      {"result", result},
      {"ports", {{"edges", result_port("edge_set", rows)}}},
      {"complete", true},
      {"quality", "exact"},
      {"diagnostics",
       {{"arithmetic", "exact over admitted binary64 weights"}, {"approximation_used", false}}}};
}

// Binary64 weights multiplied by 2^1074 are integers of at most 2098 bits.
// The bounded graph has at most 2^32 vertices; 4096 signed magnitude bits leave
// ample room for Blossom's sums and dual arithmetic, with checked overflow.
using Weight = boost::multiprecision::number<
    boost::multiprecision::cpp_int_backend<4096, 4096, boost::multiprecision::signed_magnitude,
                                           boost::multiprecision::checked, void>,
    boost::multiprecision::et_off>;
using BlossomGraph =
    boost::adjacency_list<boost::vecS, boost::vecS, boost::undirectedS, boost::no_property,
                          boost::property<boost::edge_weight_t, Weight>>;
std::vector<std::size_t> blossom(std::size_t n, const Edges& edges, Work& work) {
  std::vector<std::vector<std::size_t>> adjacency(n);
  for (std::size_t i = 0; i < edges.size(); ++i)
    if (edges[i].value > 0) {
      adjacency[edges[i].u].push_back(i);
      adjacency[edges[i].v].push_back(i);
    }
  std::vector<bool> seen(n, false);
  std::vector<std::size_t> dense(n);
  std::vector<std::size_t> chosen;
  for (VertexIndex root = 0; root < n; ++root) {
    work.tick();
    if (seen[root] || adjacency[root].empty()) continue;
    std::vector<VertexIndex> vertices{root};
    std::set<std::size_t> component_edges;
    seen[root] = true;
    for (std::size_t next = 0; next < vertices.size(); ++next) {
      const auto u = vertices[next];
      dense[u] = next;
      for (const auto index : adjacency[u]) {
        work.tick();
        component_edges.insert(index);
        const auto& edge = edges[index];
        const auto v = u == edge.u ? edge.v : edge.u;
        if (!seen[v]) {
          seen[v] = true;
          vertices.push_back(v);
        }
      }
    }
    // Charge the cubic work bound before an upstream solver whose internal
    // loops cannot consult Work; the worker boundary supplies hard cancellation.
    const auto count = vertices.size();
    const auto remaining = work.max_candidates - std::min(work.candidates, work.max_candidates);
    if (count > 0 && count > remaining / count / count)
      throw Failure("resource_limit", "Exact general matching exceeds its cubic work budget");
    work.tick(count * count * count);
    Integer scale = 1;
    for (const auto index : component_edges)
      scale = std::max(scale, denominator(edges[index].value));
    BlossomGraph input(count);
    std::map<std::pair<std::size_t, std::size_t>, std::size_t> original;
    for (const auto index : component_edges) {
      const auto& edge = edges[index];
      const auto u = dense[edge.u], v = dense[edge.v];
      const Integer integer = numerator(edge.value) * (scale / denominator(edge.value));
      boost::add_edge(u, v, Weight(integer), input);
      original[std::minmax(u, v)] = index;
    }
    using Vertex = boost::graph_traits<BlossomGraph>::vertex_descriptor;
    std::vector<Vertex> mate(count, boost::graph_traits<BlossomGraph>::null_vertex());
    boost::maximum_weighted_matching(
        input,
        boost::make_iterator_property_map(mate.begin(), boost::get(boost::vertex_index, input)));
    work.tick(0);
    for (std::size_t u = 0; u < count; ++u)
      if (mate[u] != boost::graph_traits<BlossomGraph>::null_vertex()) {
        require(mate[u] < count && mate[mate[u]] == u, "Blossom returned an invalid mate map");
        if (u < mate[u]) chosen.push_back(original.at({u, mate[u]}));
      }
  }
  std::sort(chosen.begin(), chosen.end());
  return chosen;
}

struct ResidualEdge {
  std::size_t to, reverse;
  int capacity;
  Exact cost;
};
struct Assignment {
  std::vector<std::size_t> chosen;
  bool feasible;
};
Assignment assign(std::size_t n, const std::vector<bool>& left, const Edges& edges,
                  const std::string& objective, bool perfect, Work& work) {
  const auto source = n, sink = n + 1, size = n + 2;
  std::vector<std::vector<ResidualEdge>> residual(size);
  auto add = [&](std::size_t u, std::size_t v, Exact cost) {
    const auto index = residual[u].size();
    residual[u].push_back({v, residual[v].size(), 1, cost});
    residual[v].push_back({u, index, 0, -cost});
    return index;
  };
  for (VertexIndex v = 0; v < n; ++v) {
    work.tick();
    if (left[v])
      add(source, v, 0);
    else
      add(v, sink, 0);
  }
  std::vector<std::size_t> positions;
  for (const auto& edge : edges) {
    work.tick();
    positions.push_back(add(edge.u, edge.v,
                            objective == "maximum_cardinality" ? Exact(0)
                            : objective == "maximum_weight"    ? -edge.value
                                                               : edge.value));
  }
  std::size_t cardinality = 0;
  const auto left_size = std::count(left.begin(), left.end(), true);
  const auto required = std::min<std::size_t>(left_size, n - left_size);
  while (cardinality < required) {
    work.tick(size);
    std::vector<std::optional<Exact>> distance(size);
    distance[source] = 0;
    std::vector<std::pair<std::size_t, std::size_t>> parent(size, {size, 0});
    // Exact Bellman-Ford allows negative costs. Each shortest augmentation
    // preserves optimality at that cardinality and absence of negative cycles.
    for (std::size_t iteration = 0; iteration < size; ++iteration) {
      bool changed = false;
      for (std::size_t u = 0; u < size; ++u)
        if (distance[u])
          for (std::size_t i = 0; i < residual[u].size(); ++i) {
            work.tick();
            const auto& edge = residual[u][i];
            if (!edge.capacity) continue;
            const Exact candidate = *distance[u] + edge.cost;
            if (!distance[edge.to] || candidate < *distance[edge.to]) {
              distance[edge.to] = candidate;
              parent[edge.to] = {u, i};
              changed = true;
            }
          }
      if (!changed) break;
      if (iteration + 1 == size)
        throw Failure("correctness_mismatch", "Assignment residual contains a negative cycle");
    }
    if (!distance[sink] || (!perfect && objective != "maximum_cardinality" && *distance[sink] >= 0))
      break;
    std::size_t current = sink, steps = 0;
    while (current != source) {
      work.tick();
      require(++steps < size && parent[current].first != size,
              "Invalid assignment augmenting path");
      const auto [u, index] = parent[current];
      auto& edge = residual[u][index];
      --edge.capacity;
      ++residual[edge.to][edge.reverse].capacity;
      current = u;
    }
    ++cardinality;
  }
  std::vector<std::size_t> chosen;
  for (std::size_t i = 0; i < edges.size(); ++i)
    if (!residual[edges[i].u][positions[i]].capacity) chosen.push_back(i);
  require(chosen.size() == cardinality, "Assignment flow and matching size disagree");
  return {std::move(chosen), !perfect || cardinality == required};
}
}  // namespace

json::object weighted_matching(const Graph& graph, const json::object& args, const std::string&,
                               int, Work& work) {
  fields(args, {"solution_quality"});
  const auto requested = quality(args);
  const auto edges = normalized(graph, nullptr, "maximum_weight", work);
  return selected_output(graph, edges, blossom(graph.vertex_count(), edges, work),
                         {{"solution_quality", requested}}, nullptr, work);
}
json::object bipartite_matching(const Graph& graph, const json::object& args,
                                const std::string& backend, int device, Work& work) {
  fields(args, {"objective", "weight_mode", "perfect_matching_required", "solution_quality"},
         {"objective"});
  const auto objective = string(args.at("objective"), "objective");
  require(objective == "maximum_cardinality" || objective == "maximum_weight" ||
              objective == "minimum_cost",
          "Unknown matching objective");
  const auto mode =
      args.contains("weight_mode") ? string(args.at("weight_mode"), "weight_mode") : "unweighted";
  require(mode == "unweighted" || mode == "edge_weight", "Unknown weight_mode");
  require(objective == "maximum_cardinality" || mode == "edge_weight",
          "Weighted matching objectives require weight_mode=edge_weight");
  const auto requested = quality(args);
  const bool perfect = boolean(args, "perfect_matching_required", false);
  const json::object parameters{{"objective", objective},
                                {"weight_mode", mode},
                                {"perfect_matching_required", perfect},
                                {"solution_quality", requested}};
  const auto left = sides(graph, work);
  const auto edges = normalized(graph, &left, objective, work);
  const auto result = assign(graph.vertex_count(), left, edges, objective, perfect, work);
  if (!result.feasible)
    return {{"parameters", parameters},
            {"result",
             {{"matching_edges", json::array{}},
              {"matching_size", 0},
              {"objective_value", nullptr},
              {"optimal", false},
              {"feasible", false},
              {"infeasibility_certified", true},
              {"maximum_matching_size", result.chosen.size()}}},
            {"ports", json::object{}},
            {"complete", true},
            {"quality", "exact"}};
  if (backend != "cpp") {
    std::vector<std::size_t> row(graph.vertex_count());
    std::size_t left_count = 0, right_count = 0;
    for (VertexIndex v = 0; v < graph.vertex_count(); ++v)
      row[v] = left[v] ? left_count++ : right_count++;
    std::vector<std::vector<int>> costs(left_count, std::vector<int>(right_count, 1000));
    std::vector<std::vector<std::size_t>> index(
        left_count, std::vector<std::size_t>(right_count, edges.size()));
    for (std::size_t i = 0; i < edges.size(); ++i) {
      work.tick();
      const auto& edge = edges[i];
      costs[row[edge.u]][row[edge.v]] = edge.value.convert_to<int>();
      index[row[edge.u]][row[edge.v]] = i;
    }
    const auto columns = original_assignment(costs, device, work);
    std::vector<std::size_t> chosen;
    Exact actual = 0, expected = 0;
    for (std::size_t r = 0; r < columns.size(); ++r) {
      const auto i = index[r][columns[r]];
      chosen.push_back(i);
      actual += edges.at(i).value;
    }
    for (const auto i : result.chosen) expected += edges[i].value;
    if (actual != expected || chosen.size() != result.chosen.size())
      throw Failure("correctness_mismatch",
                    "CUDA assignment failed native exact optimality verification");
    std::sort(chosen.begin(), chosen.end());
    auto output = selected_output(graph, edges, chosen, parameters, &left, work);
    output.at("diagnostics").as_object()["optimality_verification"] =
        "exact native minimum-cost matching";
    return output;
  }
  return selected_output(graph, edges, result.chosen, parameters, &left, work);
}
}  // namespace graphmine::runtime
