#include "catalog_data.hpp"
#include "pattern_match.hpp"

namespace graphmine::runtime {
json::object graphlet_counting(const Graph& graph, const json::object& args, const std::string&,
                               int, Work& work) {
  using namespace family_util;
  fields(args,
         {"graphlet_sizes", "include_orbit_counts", "list_instances", "result_limit_per_graphlet"},
         {"graphlet_sizes"});
  require(!graph.directed(), "Graphlets require undirected input");
  require(args.at("graphlet_sizes").is_array() && !args.at("graphlet_sizes").as_array().empty(),
          "graphlet_sizes must be a nonempty array");
  std::set<std::uint64_t> sizes;
  for (const auto& value : args.at("graphlet_sizes").as_array()) {
    const auto size = uint(value, "graphlet size");
    require(size >= 2 && size <= 7 && sizes.insert(size).second,
            "graphlet_sizes must be distinct integers from two through seven");
  }
  const bool orbit_counts = boolean(args, "include_orbit_counts", false),
             listing = boolean(args, "list_instances", false);
  const auto cap = limit(args, "result_limit_per_graphlet");
  require(!cap || listing, "result_limit_per_graphlet applies only when listing instances");
  struct Pattern {
    std::string id;
    MiningGraph adj;
    std::vector<std::size_t> orbits;
    std::uint64_t count = 0;
    json::array instances;
  };
  std::vector<Pattern> patterns;
  json::object dictionary, orbit_dictionary;
  std::uint64_t output_items = 0;
  const auto atlas = json::parse(native_atlas_json).as_object();
  using Signature = std::vector<std::size_t>;
  const auto signature = [](const MiningGraph& adj) {
    Signature result;
    for (const auto& row : adj) result.push_back(row.size());
    std::sort(result.begin(), result.end());
    return result;
  };
  std::map<Signature, std::vector<std::size_t>> lookup;
  for (const auto& value : atlas.at("patterns").as_array()) {
    const auto& entry = value.as_object();
    const auto n = uint(entry.at("vertices"), "atlas size");
    if (!sizes.count(n)) continue;
    work.tick(n + entry.at("edges").as_array().size());
    Pattern pattern{
        string(entry.at("id"), "atlas id"), MiningGraph(n), std::vector<std::size_t>(n), 0, {}};
    json::array vertices, edges;
    for (std::size_t v = 0; v < n; ++v) vertices.push_back(json::object{{"id", v}});
    for (const auto& edge : entry.at("edges").as_array()) {
      const auto u = uint(edge.as_array()[0], "atlas endpoint"),
                 v = uint(edge.as_array()[1], "atlas endpoint");
      require(u < n && v < n, "Invalid embedded atlas endpoint");
      pattern.adj[u].push_back(v);
      pattern.adj[v].push_back(u);
      edges.push_back(json::object{{"id", edges.size()}, {"source", u}, {"target", v}});
    }
    for (auto& row : pattern.adj) std::sort(row.begin(), row.end());
    dictionary[pattern.id] = json::object{{"graph",
                                           {{"id", pattern.id},
                                            {"directed", false},
                                            {"allows_self_loops", false},
                                            {"allows_parallel_edges", false}}},
                                          {"vertices", vertices},
                                          {"edges", edges}};
    std::size_t orbit_index = 0;
    for (const auto& orbit : entry.at("orbits").as_array()) {
      for (const auto& v : orbit.as_array())
        pattern.orbits.at(uint(v, "atlas orbit")) = orbit_index;
      if (orbit_counts)
        orbit_dictionary[pattern.id + ":orbit-" + std::to_string(orbit_index)] =
            json::object{{"graphlet", pattern.id}, {"pattern_vertices", orbit}};
      ++orbit_index;
    }
    output_items += 1 + n + edges.size();
    if (orbit_counts) output_items += orbit_index;
    work.output(output_items);
    lookup[signature(pattern.adj)].push_back(patterns.size());
    patterns.push_back(std::move(pattern));
  }
  const auto adj = adjacency(graph, work);
  std::vector<std::map<std::string, std::uint64_t>> roles(graph.vertex_count());
  for (const auto size : sizes)
    combinations(graph.vertex_count(), size, work, [&](const Vertices& selected) {
      MiningGraph subgraph(size);
      for (std::size_t i = 0; i < size; ++i)
        for (std::size_t j = i + 1; j < size; ++j) {
          work.tick();
          if (adjacent(adj, selected[i], selected[j])) {
            subgraph[i].push_back(j);
            subgraph[j].push_back(i);
          }
        }
      const auto reach = cpu_bfs(subgraph, 0, {}, work);
      if (std::any_of(reach.distances.begin(), reach.distances.end(), [](auto d) { return d < 0; }))
        return true;
      bool classified = false;
      const auto candidates = lookup.find(signature(subgraph));
      require(candidates != lookup.end(), "Embedded atlas is missing a degree class");
      for (const auto index : candidates->second) {
        auto& pattern = patterns[index];
        Vertices match;
        simple_mappings(
            subgraph, pattern.adj, false, true,
            [&](const Vertices& mapping) {
              match = mapping;
              return false;
            },
            work);
        if (match.empty()) continue;
        classified = true;
        if (pattern.count == UINT64_MAX)
          throw Failure("resource_limit", "Graphlet count exceeds uint64");
        ++pattern.count;
        if (orbit_counts)
          for (std::size_t q = 0; q < size; ++q) {
            auto& role = roles[selected[match[q]]];
            const auto key = pattern.id + ":orbit-" + std::to_string(pattern.orbits[q]);
            auto [it, inserted] = role.emplace(key, 0);
            ++it->second;
            if (inserted) ++output_items;
          }
        if (listing && (!cap || pattern.instances.size() < *cap)) {
          pattern.instances.push_back(ids(graph, selected));
          output_items += size;
        }
        work.output(output_items);
        break;
      }
      require(classified, "Connected graphlet is absent from the complete embedded atlas");
      return true;
    });
  json::object counts, instances, completeness;
  json::array count_rows, role_rows;
  bool complete = true;
  for (const auto& pattern : patterns) {
    counts[pattern.id] = pattern.count;
    count_rows.push_back(json::object{{"graphlet", pattern.id}, {"count", pattern.count}});
    if (listing) {
      instances[pattern.id] = pattern.instances;
      completeness[pattern.id] = pattern.instances.size() == pattern.count;
      complete = complete && pattern.instances.size() == pattern.count;
    }
  }
  json::object data{{"count_by_graphlet", counts}, {"graphlet_dictionary", dictionary}},
      ports{{"counts", result_port("table", count_rows)}};
  if (orbit_counts) {
    for (VertexIndex v = 0; v < graph.vertex_count(); ++v) {
      json::object values;
      for (const auto& [key, value] : roles[v]) values[key] = value;
      role_rows.push_back(
          json::object{{"vertex", id_json(graph.external_id(v))}, {"counts", values}});
    }
    data["orbit_dictionary"] = orbit_dictionary;
    data["orbit_counts_by_vertex"] = role_rows;
  }
  if (listing) {
    data["instances_by_graphlet"] = instances;
    data["instances_complete_by_graphlet"] = completeness;
    ports["instances"] = result_port("graphlet_instances", instances, complete);
  }
  work.output(output_items + (orbit_counts ? graph.vertex_count() : 0));
  auto result =
      output({{"graphlet_sizes", args.at("graphlet_sizes")},
              {"include_orbit_counts", orbit_counts},
              {"list_instances", listing},
              {"result_limit_per_graphlet", cap ? json::value(*cap) : json::value(nullptr)}},
             data, ports);
  result["diagnostics"] = json::object{
      {"classification", "native_induced_isomorphism"},
      {"atlas_source", atlas.at("source")},
      {"atlas_networkx_version", atlas.at("networkx_version")},
      {"atlas_role", "static graph and automorphism-orbit dictionary; no Python runtime"}};
  return result;
}
}  // namespace graphmine::runtime
