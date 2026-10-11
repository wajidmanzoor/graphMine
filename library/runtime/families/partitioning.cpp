#include <queue>

#include "family_util.hpp"
#include "native_random.hpp"

namespace graphmine::runtime {
namespace {
using namespace family_util;
json::object assignment_output(const Graph& graph, const std::vector<std::size_t>& assignment,
                               json::object args, json::object data, Work& work,
                               const char* quality = "exact") {
  require(assignment.size() == graph.vertex_count(), "Partition did not cover every vertex");
  std::map<std::size_t, std::size_t> labels;
  std::vector<Vertices> groups;
  json::array rows, group_rows;
  for (VertexIndex v = 0; v < graph.vertex_count(); ++v) {
    auto [it, inserted] = labels.emplace(assignment[v], labels.size());
    if (inserted) groups.emplace_back();
    groups[it->second].push_back(v);
    rows.push_back(json::object{{"vertex", id_json(graph.external_id(v))}, {"part", it->second}});
  }
  for (const auto& group : groups)
    group_rows.push_back(
        json::object{{"group", group_rows.size()}, {"vertices", ids(graph, group)}});
  work.output(2 * graph.vertex_count() + groups.size());
  data["partition_assignment"] = rows;
  data["groups"] = group_rows;
  return output(args, data,
                {{"partition", result_port("vertex_partition", rows)},
                 {"groups", result_port("vertex_groups", group_rows)}},
                true, quality);
}
}  // namespace
json::object community_detection(const Graph& graph, const json::object& args, const std::string&,
                                 int, Work& work) {
  using namespace family_util;
  fields(args, {"quality_function", "resolution", "weight_mode", "solution_quality", "seed"});
  require(!graph.directed(), "Community detection requires undirected input");
  const auto objective =
      choice(args, "quality_function", "modularity", {"modularity", "constant_potts_model"});
  const auto weight_mode = choice(args, "weight_mode", "unweighted", {"unweighted", "edge_weight"});
  const auto requested = choice(args, "solution_quality", "heuristic", {"exact", "heuristic"});
  const Exact resolution =
      args.contains("resolution") ? exact_number(args.at("resolution"), "resolution") : Exact(1);
  require(resolution > 0, "resolution must be positive");
  const auto seed = natural(args, "seed", 0);
  const auto n = graph.vertex_count();
  const auto normalized = edges(graph, weight_mode == "edge_weight", work);
  std::vector<Exact> degrees(n, 0);
  Exact total = 0;
  for (const auto& edge : normalized) {
    degrees[edge.u] += edge.weight;
    degrees[edge.v] += edge.weight;
    total += edge.weight;
  }
  std::vector<std::size_t> selected(n);
  std::iota(selected.begin(), selected.end(), 0);
  Exact best = 0;
  bool optimal = n == 0 || total == 0;
  if (total > 0) {
    work.tick(n * n);
    std::vector<std::vector<Exact>> pair(n, std::vector<Exact>(n, 0));
    for (const auto& edge : normalized) pair[edge.u][edge.v] = edge.weight;
    Exact offset = 0;
    for (VertexIndex u = 0; u < n; ++u) {
      if (objective == "modularity")
        offset -= resolution * degrees[u] * degrees[u] / (4 * total * total);
      for (VertexIndex v = u + 1; v < n; ++v) {
        if (objective == "modularity")
          pair[u][v] =
              pair[u][v] / total - resolution * degrees[u] * degrees[v] / (2 * total * total);
        else
          pair[u][v] -= resolution;
        pair[v][u] = pair[u][v];
      }
    }
    auto score = [&](const std::vector<std::size_t>& parts) {
      Exact value = offset;
      for (VertexIndex u = 0; u < n; ++u)
        for (VertexIndex v = u + 1; v < n; ++v) {
          work.tick();
          if (parts[u] == parts[v]) value += pair[u][v];
        }
      return value;
    };
    best = score(selected);
    if (requested == "exact") {
      partitions(n, 1, n, work, [&](const auto& parts) {
        const auto value = score(parts);
        if (value > best) {
          best = value;
          selected = parts;
        }
      });
      optimal = true;
    } else {
      NativeRandom random(json::object{{"random_seed", seed}});
      auto order = all_vertices(graph);
      random.shuffle(order, work);
      // Positive-gain single-vertex moves terminate because the exact objective
      // strictly increases over a finite set of partitions. No optimality claim.
      for (;;) {
        bool changed = false;
        for (const auto u : order) {
          work.tick(n);
          std::vector<Exact> gain(n, 0);
          std::vector<bool> occupied(n, false);
          for (VertexIndex v = 0; v < n; ++v) {
            occupied[selected[v]] = true;
            if (u != v) gain[selected[v]] += pair[u][v];
          }
          auto target = selected[u];
          const auto current = gain[target];
          Exact improvement = 0;
          for (std::size_t p = 0; p < n; ++p) {
            work.tick();
            const Exact delta = (occupied[p] ? gain[p] : Exact(0)) - current;
            if (delta > improvement) {
              improvement = delta;
              target = p;
            }
          }
          if (improvement > 0) {
            selected[u] = target;
            best += improvement;
            changed = true;
          }
        }
        if (!changed) break;
      }
      if (score(selected) != best)
        throw Failure("correctness_mismatch", "Community objective failed recomputation");
    }
  }
  json::object data{
      {"community_count", std::set<std::size_t>(selected.begin(), selected.end()).size()},
      {"quality_function", objective},
      {"optimal", optimal}};
  exact_field(data, "quality_score", best);
  auto result = assignment_output(graph, selected,
                                  {{"quality_function", objective},
                                   {"resolution", display_number(resolution)},
                                   {"weight_mode", weight_mode},
                                   {"solution_quality", requested},
                                   {"seed", seed}},
                                  data, work, optimal ? "exact" : "heuristic");
  json::array communities;
  for (const auto& row : result.at("result").as_object().at("partition_assignment").as_array())
    communities.push_back(json::object{{"vertex", row.as_object().at("vertex")},
                                       {"community", row.as_object().at("part")}});
  result.at("result").as_object()["community_by_vertex"] = communities;
  result["diagnostics"] = json::object{
      {"solver", optimal ? "native_exact_partition_search" : "native_positive_gain_vertex_moves"},
      {"arithmetic", "exact rational"}};
  return result;
}
json::object balanced_partitioning(const Graph& graph, const json::object& args, const std::string&,
                                   int, Work& work) {
  using namespace family_util;
  fields(args,
         {"num_parts", "balance_mode", "vertex_weights", "imbalance_tolerance", "edge_weight_mode",
          "objective", "solution_quality"},
         {"num_parts"});
  require(!graph.directed(), "Balanced partitioning requires undirected input");
  const auto k = natural(args, "num_parts", 2, 2), n = graph.vertex_count();
  require(k <= n, "num_parts exceeds vertex count");
  const auto balance_mode =
      choice(args, "balance_mode", "vertex_count", {"vertex_count", "vertex_weight"});
  const auto edge_mode =
      choice(args, "edge_weight_mode", "unweighted", {"unweighted", "edge_weight"});
  const auto objective = choice(args, "objective", "edge_cut", {"edge_cut", "normalized_cut"});
  const auto quality = choice(args, "solution_quality", "exact", {"exact", "approximate"});
  const Exact tolerance = decimal_number(
      args.contains("imbalance_tolerance") ? args.at("imbalance_tolerance") : json::value(0.03),
      "imbalance_tolerance");
  require(tolerance >= 0, "imbalance_tolerance must be nonnegative");
  std::vector<Exact> weights(n, 1);
  if (balance_mode == "vertex_count")
    require(!args.contains("vertex_weights") || args.at("vertex_weights").is_null(),
            "vertex_weights requires vertex_weight balance mode");
  else {
    require(args.contains("vertex_weights"), "vertex_weights is required");
    const auto values = vertex_values(graph, args.at("vertex_weights"), "vertex_weights");
    for (VertexIndex v = 0; v < n; ++v) {
      weights[v] = exact_number(values[v], "vertex weight");
      require(weights[v] >= 0, "Vertex weights must be nonnegative");
    }
  }
  Exact total = 0;
  for (const auto& weight : weights) total += weight;
  const Exact ideal = total / k;
  const Exact lower = std::max(Exact(0), Exact((1 - tolerance) * ideal)),
              upper = (1 + tolerance) * ideal;
  const auto normalized = edges(graph, edge_mode == "edge_weight", work);
  std::optional<Exact> best;
  std::vector<std::size_t> selected;
  std::vector<Exact> best_sizes;
  Exact best_cut = 0;
  partitions(n, k, k, work, [&](const auto& parts) {
    work.tick(n);
    std::vector<Exact> sizes(k, 0), boundary(k, 0);
    for (VertexIndex v = 0; v < n; ++v) sizes[parts[v]] += weights[v];
    for (const auto& size : sizes)
      if (size < lower || size > upper || (objective == "normalized_cut" && size <= 0)) return;
    Exact cut = 0, value = 0;
    for (const auto& edge : normalized) {
      work.tick();
      if (parts[edge.u] != parts[edge.v]) {
        cut += edge.weight;
        boundary[parts[edge.u]] += edge.weight;
        boundary[parts[edge.v]] += edge.weight;
      }
    }
    if (objective == "edge_cut")
      value = cut;
    else
      for (std::size_t p = 0; p < k; ++p) value += boundary[p] / sizes[p];
    if (!best || value < *best) {
      best = value;
      selected = parts;
      best_sizes = sizes;
      best_cut = cut;
    }
  });
  json::object resolved{
      {"num_parts", k},
      {"balance_mode", balance_mode},
      {"vertex_weights",
       args.contains("vertex_weights") ? args.at("vertex_weights") : json::value(nullptr)},
      {"imbalance_tolerance",
       args.contains("imbalance_tolerance") ? args.at("imbalance_tolerance") : json::value(0.03)},
      {"edge_weight_mode", edge_mode},
      {"objective", objective},
      {"solution_quality", quality}};
  if (!best)
    return output(resolved,
                  {{"feasible", false},
                   {"balanced", false},
                   {"infeasibility_certified", true},
                   {"partition_assignment", json::array{}},
                   {"part_sizes", json::array{}},
                   {"objective_value", nullptr},
                   {"optimal", false}},
                  {});
  json::array sizes, sizes_exact;
  Exact deviation = 0;
  for (const auto& size : best_sizes) {
    sizes.push_back(display_number(size));
    sizes_exact.push_back(fraction_json(size));
    if (ideal > 0) deviation = std::max(deviation, Exact(abs(size - ideal) / ideal));
  }
  json::object data{{"feasible", true},
                    {"balanced", true},
                    {"part_sizes", sizes},
                    {"part_sizes_exact", sizes_exact},
                    {"optimal", true}};
  exact_field(data, "objective_value", *best);
  exact_field(data, "edge_cut", best_cut);
  exact_field(data, "imbalance_ratio", deviation);
  return assignment_output(graph, selected, resolved, data, work);
}
json::object signed_balance(const Graph& graph, const json::object& args, const std::string&, int,
                            Work& work) {
  using namespace family_util;
  fields(args, {"task", "weight_mode", "solution_quality"}, {"task"});
  require(!graph.directed(), "Signed balance requires undirected input");
  const auto task =
      choice(args, "task", "balance_check", {"balance_check", "frustration_minimization"});
  const auto weight_mode = choice(args, "weight_mode", "unweighted", {"unweighted", "edge_weight"});
  const auto quality = choice(args, "solution_quality", "exact", {"exact", "approximate"});
  struct SignedEdge {
    VertexIndex u, v;
    bool negative;
    Exact weight;
  };
  std::map<std::pair<VertexIndex, VertexIndex>, SignedEdge> edges;
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    require(edge.type && (*edge.type == "positive" || *edge.type == "negative"),
            "Every edge requires type positive or negative");
    auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    const Exact weight = weight_mode == "unweighted" ? Exact(1) : Exact(edge.weight.value_or(1));
    require(weight >= 0, "Frustration costs must be nonnegative");
    if (u == v) continue;
    if (u > v) std::swap(u, v);
    auto [it, inserted] =
        edges.emplace(std::make_pair(u, v), SignedEdge{u, v, *edge.type == "negative", weight});
    if (!inserted) {
      require(it->second.negative == (*edge.type == "negative"),
              "Contradictory parallel signed edges require a resolution policy");
      if (weight_mode == "edge_weight") it->second.weight += weight;
    }
  }
  const auto n = graph.vertex_count();
  std::vector<std::vector<std::pair<VertexIndex, bool>>> adj(n);
  for (const auto& [_, edge] : edges) {
    adj[edge.u].emplace_back(edge.v, edge.negative);
    adj[edge.v].emplace_back(edge.u, edge.negative);
  }
  std::vector<int> parity(n, -1);
  Vertices roots;
  for (VertexIndex start = 0; start < n; ++start)
    if (parity[start] == -1) {
      roots.push_back(start);
      parity[start] = 0;
      std::queue<VertexIndex> queue;
      queue.push(start);
      while (!queue.empty()) {
        auto u = queue.front();
        queue.pop();
        for (const auto& [v, negative] : adj[u]) {
          work.tick();
          if (parity[v] < 0) {
            parity[v] = parity[u] ^ negative;
            queue.push(v);
          }
        }
      }
    }
  auto score = [&](const auto& values) {
    Exact value = 0;
    for (const auto& [_, edge] : edges) {
      work.tick();
      if ((values[edge.u] != values[edge.v]) != edge.negative) value += edge.weight;
    }
    return value;
  };
  bool balanced = true;
  for (const auto& [_, edge] : edges)
    if ((parity[edge.u] != parity[edge.v]) != edge.negative) balanced = false;
  Exact best = score(parity);
  if (!balanced && task == "frustration_minimization") {
    Vertices free;
    for (VertexIndex v = 0; v < n; ++v)
      if (!std::binary_search(roots.begin(), roots.end(), v)) free.push_back(v);
    std::vector<int> trial(n, 0);
    std::vector<bool> bits(free.size(), false);
    for (;;) {
      work.tick();
      const auto value = score(trial);
      if (value < best) {
        best = value;
        parity = trial;
      }
      if (best == 0)
        break;  // Nonnegative costs certify this optimum, even when structurally unbalanced.
      std::size_t pos = 0;
      while (pos < free.size() && bits[pos]) {
        bits[pos] = false;
        trial[free[pos]] = 0;
        ++pos;
      }
      if (pos == free.size()) break;
      bits[pos] = true;
      trial[free[pos]] = 1;
    }
  }
  json::array rows, partition_rows, frustrated;
  for (VertexIndex v = 0; v < n; ++v) {
    const char* label = parity[v] ? "B" : "A";
    rows.push_back(json::object{{"vertex", id_json(graph.external_id(v))}, {"faction", label}});
    partition_rows.push_back(
        json::object{{"vertex", id_json(graph.external_id(v))}, {"part", label}});
  }
  for (const auto& [_, edge] : edges)
    if ((parity[edge.u] != parity[edge.v]) != edge.negative) {
      json::object row{{"source", id_json(graph.external_id(edge.u))},
                       {"target", id_json(graph.external_id(edge.v))}};
      exact_field(row, "weight", edge.weight);
      frustrated.push_back(row);
    }
  work.output(rows.size() + frustrated.size());
  json::object data{{"balanced", balanced},
                    {"faction_assignment", rows},
                    {"frustrated_edges", frustrated},
                    {"optimal", true},
                    {"frustration_optimal", balanced || task == "frustration_minimization"}};
  exact_field(data, "frustrated_weight", best);
  return output({{"task", task}, {"weight_mode", weight_mode}, {"solution_quality", quality}}, data,
                {{"partition", result_port("vertex_partition", partition_rows)}});
}
}  // namespace graphmine::runtime
