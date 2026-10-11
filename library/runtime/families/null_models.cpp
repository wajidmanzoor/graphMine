#include "family_util.hpp"
#include "native_random.hpp"
#include "numeric.hpp"

namespace graphmine::runtime {
json::object null_significance(const Graph& graph, const json::object& args, const std::string&,
                               int, Work& work) {
  using namespace family_util;
  fields(args,
         {"null_model", "statistic_definition", "observed_value", "sample_count", "random_seed",
          "tail", "max_randomization_attempts", "return_randomized_edges"},
         {"statistic_definition", "sample_count"});
  const auto model = choice(args, "null_model", "degree_preserving_configuration",
                            {"degree_preserving_configuration", "erdos_renyi"});
  const auto tail =
      choice(args, "tail", "greater", {"greater", "less", "two_sided_about_null_mean"});
  const auto count = natural(args, "sample_count", 1, 1),
             maximum_attempts = natural(args, "max_randomization_attempts", 100000, 1);
  require(maximum_attempts >= count, "max_randomization_attempts must be at least sample_count");
  const auto return_edges = boolean(args, "return_randomized_edges", false);
  if (args.contains("random_seed") && !args.at("random_seed").is_null())
    uint(args.at("random_seed"), "random_seed");
  NativeRandom random(args);
  const auto n = graph.vertex_count();
  using Pair = std::pair<VertexIndex, VertexIndex>;
  using EdgeSet = std::set<Pair>;
  EdgeSet original;
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    if (!graph.directed() && u > v) std::swap(u, v);
    original.emplace(u, v);
  }
  const auto definition = object(args.at("statistic_definition"), "statistic_definition");
  require(definition.contains("name"), "statistic_definition needs name");
  const auto name = string(definition.at("name"), "statistic name");
  require(name == "triangles" || name == "directed_triangles" || name == "k_cliques" ||
              name == "density" || name == "modularity",
          "Unsupported null statistic");
  if (name == "k_cliques")
    fields(definition, {"name", "k"}, {"k"});
  else if (name == "modularity")
    fields(definition, {"name", "partition", "resolution"}, {"partition"});
  else
    fields(definition, {"name"});
  require((name != "triangles" && name != "k_cliques") || !graph.directed(),
          "Clique statistics require undirected input");
  require(name != "directed_triangles" || graph.directed(),
          "directed_triangles requires directed input");
  const auto k = name == "k_cliques" ? natural(definition, "k", 3, 1) : 3;
  std::vector<std::size_t> partition(n, 0);
  std::size_t parts = 0;
  Exact resolution = 1;
  if (name == "modularity") {
    require(definition.at("partition").is_array(), "modularity partition must be an array");
    std::vector<bool> seen(n, false);
    for (const auto& group : definition.at("partition").as_array()) {
      const auto selected = vertices(graph, group, "partition group");
      require(!selected.empty(), "Partition groups must be nonempty");
      for (const auto v : selected) {
        require(!seen[v], "Partition repeats a vertex");
        seen[v] = true;
        partition[v] = parts;
      }
      ++parts;
    }
    require(std::all_of(seen.begin(), seen.end(), [](bool v) { return v; }),
            "Partition must cover every vertex");
    if (definition.contains("resolution"))
      resolution = exact_number(definition.at("resolution"), "resolution");
    require(resolution >= 0, "resolution must be nonnegative");
  }
  const std::uint64_t possible = n * (n ? n - 1 : 0) / (graph.directed() ? 1 : 2),
                      m = original.size();
  auto degrees = [&](const EdgeSet& edges) {
    std::pair<std::vector<std::uint64_t>, std::vector<std::uint64_t>> result{{}, {}};
    result.first.resize(n, 0);
    result.second.resize(n, 0);
    for (const auto& [u, v] : edges) {
      work.tick();
      ++result.first[u];
      ++result.second[v];
      if (!graph.directed()) {
        ++result.first[v];
        ++result.second[u];
      }
    }
    return result;
  };
  const auto original_degrees = degrees(original);
  auto evaluate = [&](const EdgeSet& edges) -> Exact {
    work.tick(n + edges.size());
    if (name == "density") return possible ? Exact(edges.size()) / possible : Exact(0);
    if (name == "modularity") {
      require(!edges.empty(), "Modularity is undefined for an edgeless graph");
      const auto deg = degrees(edges);
      std::vector<Exact> outgoing(parts, 0), incoming(parts, 0);
      Exact inside = 0;
      for (const auto& [u, v] : edges)
        if (partition[u] == partition[v]) ++inside;
      for (VertexIndex v = 0; v < n; ++v) {
        outgoing[partition[v]] += deg.first[v];
        incoming[partition[v]] += deg.second[v];
      }
      Exact value = inside / edges.size();
      const Exact denominator = Exact(edges.size()) * edges.size() * (graph.directed() ? 1 : 4);
      for (std::size_t p = 0; p < parts; ++p)
        value -= resolution * outgoing[p] * incoming[p] / denominator;
      return value;
    }
    MiningGraph adj(n);
    for (const auto& [u, v] : edges) {
      adj[u].push_back(v);
      if (!graph.directed()) adj[v].push_back(u);
    }
    for (auto& row : adj) std::sort(row.begin(), row.end());
    Integer value = 0;
    if (name == "directed_triangles") {
      for (VertexIndex u = 0; u < n; ++u)
        for (const auto v : adj[u])
          if (v > u)
            for (const auto w : adj[v]) {
              work.tick();
              if (w > u && w != v && adjacent(adj, w, u)) ++value;
            }
    } else if (k <= n)
      each_clique(adj, k, k, work, [&](const Vertices&) {
        ++value;
        return true;
      });
    return Exact(value);
  };
  const auto observed = args.contains("observed_value") && !args.at("observed_value").is_null()
                            ? exact_number(args.at("observed_value"), "observed_value")
                            : evaluate(original);
  const auto observed_float = numeric::finite(observed.convert_to<long double>());
  const bool fixed = model == "degree_preserving_configuration",
             complement = fixed && m > possible / 2;
  std::vector<Pair> complete;
  if (!fixed || complement) {
    work.tick(possible);
    complete.reserve(possible);
    for (VertexIndex u = 0; u < n; ++u)
      for (VertexIndex v = graph.directed() ? 0 : u + 1; v < n; ++v)
        if (u != v) complete.emplace_back(u, v);
  }
  EdgeSet base = original;
  if (complement) {
    base.clear();
    for (const auto& edge : complete)
      if (!original.count(edge)) base.insert(edge);
  }
  const auto base_degrees = degrees(base);
  Vertices outgoing, incoming;
  if (fixed)
    for (VertexIndex v = 0; v < n; ++v) {
      work.tick(base_degrees.first[v] + (graph.directed() ? base_degrees.second[v] : 0));
      outgoing.insert(outgoing.end(), base_degrees.first[v], v);
      if (graph.directed()) incoming.insert(incoming.end(), base_degrees.second[v], v);
    }
  if (return_edges && m > (work.max_output_items / count ? work.max_output_items / count - 1 : 0))
    throw Failure("resource_limit", "Randomized edge output exceeds budget");
  work.output(count * (1 + (return_edges ? m : 0)));
  json::array values, random_edges;
  std::vector<Exact> samples;
  std::uint64_t attempts = 0;
  for (std::uint64_t sample_index = 0; sample_index < count; ++sample_index) {
    EdgeSet sample;
    if (fixed) {
      bool accepted = false;
      while (attempts < maximum_attempts) {
        ++attempts;
        work.tick(n + outgoing.size() + incoming.size());
        auto stubs = graph.directed() ? incoming : outgoing;
        random.shuffle(stubs, work);
        sample.clear();
        bool simple = true;
        const auto size = graph.directed() ? outgoing.size() : stubs.size() / 2;
        for (std::size_t i = 0; i < size; ++i) {
          auto u = graph.directed() ? outgoing[i] : stubs[2 * i],
               v = graph.directed() ? stubs[i] : stubs[2 * i + 1];
          if (!graph.directed() && u > v) std::swap(u, v);
          if (u == v || !sample.emplace(u, v).second) {
            simple = false;
            break;
          }
        }
        if (simple) {
          accepted = true;
          break;
        }
      }
      if (!accepted)
        throw Failure("resource_limit",
                      "Simple configuration sampling exhausted max_randomization_attempts");
      if (complement) {
        EdgeSet transformed;
        work.tick(complete.size());
        for (const auto& edge : complete)
          if (!sample.count(edge)) transformed.insert(edge);
        sample = std::move(transformed);
      }
      if (degrees(sample) != original_degrees)
        throw Failure("correctness_mismatch", "Null randomization changed a degree invariant");
    } else {
      ++attempts;
      work.tick(complete.size());
      auto available = complete;
      for (std::size_t i = 0; i < m; ++i) {
        const auto next = i + random.uniform(available.size() - i, work);
        std::swap(available[i], available[next]);
        sample.insert(available[i]);
      }
    }
    if (sample.size() != m)
      throw Failure("correctness_mismatch", "Null randomization changed edge count");
    const auto value = evaluate(sample);
    samples.push_back(value);
    values.push_back(display_number(value));
    if (return_edges) {
      json::array rows;
      for (const auto& [u, v] : sample)
        rows.push_back(json::array{id_json(graph.external_id(u)), id_json(graph.external_id(v))});
      random_edges.push_back(rows);
    }
  }
  Exact exact_mean = 0;
  for (const auto& value : samples) exact_mean += value;
  exact_mean /= count;
  long double variance = 0;
  for (const auto& value : samples) {
    const auto delta = Exact(value - exact_mean).convert_to<long double>();
    variance += delta * delta;
  }
  const auto mean = numeric::finite(exact_mean.convert_to<long double>()),
             standard_deviation = numeric::finite(std::sqrt(variance / count));
  std::uint64_t extreme = 0;
  for (const auto& value : samples) {
    if (tail == "greater")
      extreme += value >= observed;
    else if (tail == "less")
      extreme += value <= observed;
    else
      extreme += abs(value - exact_mean) >= abs(observed - exact_mean);
  }
  json::object summary{
      {"mean", mean},
      {"standard_deviation", standard_deviation},
      {"minimum", display_number(*std::min_element(samples.begin(), samples.end()))},
      {"maximum", display_number(*std::max_element(samples.begin(), samples.end()))},
      {"standard_deviation_ddof", 0}};
  json::object diagnostics{
      {"random_seed", random.seed},
      {"generator", "native_mt19937_64_with_unbiased_integer_rejection"},
      {"attempts", attempts},
      {"accepted", count},
      {"acceptance_rate", static_cast<double>(count) / attempts},
      {"complement_sampling", complement},
      {"sampler", fixed ? "uniform_stub_pairing_conditioned_on_simplicity" : "uniform_G_n_m"},
      {"invariants_checked", true},
      {"tail", tail},
      {"two_sided_center", "exact rational null mean"}};
  json::object data{
      {"observed_value", display_number(observed)},
      {"null_distribution_summary", summary},
      {"z_score", standard_deviation
                      ? json::value(numeric::finite(
                            (static_cast<long double>(observed_float) - mean) / standard_deviation))
                      : json::value(nullptr)},
      {"empirical_p_value", static_cast<double>(extreme) / count},
      {"null_distribution_samples", values},
      {"randomization_diagnostics", diagnostics},
      {"complete", true}};
  if (return_edges) data["randomized_edges"] = random_edges;
  json::object resolved{
      {"null_model", model},
      {"statistic_definition", definition},
      {"observed_value",
       args.contains("observed_value") ? args.at("observed_value") : json::value(nullptr)},
      {"sample_count", count},
      {"random_seed", random.seed},
      {"tail", tail},
      {"max_randomization_attempts", maximum_attempts},
      {"return_randomized_edges", return_edges}};
  auto result = output(resolved, data, {{"samples", result_port("numeric_sample", values)}}, true,
                       "statistical_estimate");
  result["diagnostics"] = diagnostics;
  return result;
}
}  // namespace graphmine::runtime
