#include "pattern_match.hpp"

namespace graphmine::runtime {
json::object subgraph_isomorphism(const Graph& graph, const json::object& args, const std::string&,
                                  int, Work& work) {
  using namespace family_util;
  fields(args, {"query_graph", "induced", "vertex_predicates", "edge_predicates", "result_limit"},
         {"query_graph"});
  const auto query = parse_graph(args.at("query_graph"));
  const auto induced = boolean(args, "induced", false);
  const auto cap = limit(args);
  json::array vertex_specs, edge_specs;
  if (args.contains("vertex_predicates")) {
    require(args.at("vertex_predicates").is_array(), "vertex_predicates must be an array");
    vertex_specs = args.at("vertex_predicates").as_array();
  }
  if (args.contains("edge_predicates")) {
    require(args.at("edge_predicates").is_array(), "edge_predicates must be an array");
    edge_specs = args.at("edge_predicates").as_array();
  }
  json::array matches;
  const bool complete = pattern_mappings(
      graph, query, induced, vertex_specs, edge_specs,
      [&](const Vertices& mapping) {
        if (cap && matches.size() == *cap) return false;
        work.output((matches.size() + 1) * std::max<std::size_t>(1, query.vertex_count()));
        matches.push_back(mapping_rows(graph, query, mapping));
        return true;
      },
      work);
  auto port = result_port("vertex_mappings", matches, complete);
  port["query_graph_fingerprint"] = input_fingerprint(args.at("query_graph"));
  return output({{"query_graph", args.at("query_graph")},
                 {"induced", induced},
                 {"vertex_predicates", vertex_specs},
                 {"edge_predicates", edge_specs},
                 {"result_limit", cap ? json::value(*cap) : json::value(nullptr)}},
                {{"matches", matches}, {"returned_count", matches.size()}, {"complete", complete}},
                {{"matches", port}}, complete);
}

json::object motif_counting(const Graph& graph, const json::object& args, const std::string&, int,
                            Work& work) {
  using namespace family_util;
  fields(args,
         {"motifs", "induced", "occurrence_identity", "list_instances", "result_limit_per_motif"},
         {"motifs"});
  require(args.at("motifs").is_array() && !args.at("motifs").as_array().empty(),
          "motifs must contain connected canonical graphs");
  const bool induced = boolean(args, "induced", false),
             listing = boolean(args, "list_instances", false);
  const auto identity = choice(args, "occurrence_identity", "unique_vertex_set_and_mapping_class",
                               {"unique_vertex_set_and_mapping_class", "all_embeddings"});
  const auto cap = limit(args, "result_limit_per_motif");
  require(!cap || listing, "result_limit_per_motif applies only when listing instances");
  const auto adj = adjacency(graph, work);
  json::object counts, completeness, instances;
  json::array rows;
  std::uint64_t materialized = 0;
  for (const auto& record : args.at("motifs").as_array()) {
    const auto query = parse_graph(record);
    const auto name = query.canonical().graph.id;
    require(!counts.contains(name), "Motif graph IDs must be unique");
    require(query.directed() == graph.directed(), "Motif direction must match input");
    require(query.vertex_count() > 0, "Motif must be nonempty");
    auto qadj = adjacency(query, work), weak = qadj;
    if (query.directed())
      for (VertexIndex u = 0; u < qadj.size(); ++u)
        for (const auto v : qadj[u]) weak[v].push_back(u);
    const auto reached = cpu_bfs(weak, 0, {}, work);
    require(std::all_of(reached.distances.begin(), reached.distances.end(),
                        [](auto d) { return d >= 0; }),
            "Every motif must be connected");
    using Pair = std::pair<VertexIndex, VertexIndex>;
    std::set<std::pair<Vertices, std::vector<Pair>>> seen;
    Integer count = 0;
    json::array matches;
    simple_mappings(
        adj, qadj, graph.directed(), induced,
        [&](const Vertices& mapping) {
          if (identity != "all_embeddings") {
            auto chosen = mapping;
            std::sort(chosen.begin(), chosen.end());
            std::vector<Pair> image_edges;
            for (VertexIndex u = 0; u < qadj.size(); ++u)
              for (const auto v : qadj[u])
                if (graph.directed() || u < v) {
                  work.tick();
                  auto a = mapping[u], b = mapping[v];
                  if (!graph.directed() && a > b) std::swap(a, b);
                  image_edges.emplace_back(a, b);
                }
            std::sort(image_edges.begin(), image_edges.end());
            if (!seen.emplace(std::move(chosen), std::move(image_edges)).second) return true;
          }
          ++count;
          if (listing && (!cap || matches.size() < *cap)) {
            materialized += query.vertex_count();
            work.output(materialized);
            matches.push_back(mapping_rows(graph, query, mapping));
          }
          return true;
        },
        work);
    const auto value = display_number(Exact(count));
    counts[name] = value;
    completeness[name] = Integer(matches.size()) == count;
    if (listing) instances[name] = matches;
    rows.push_back(json::object{{"motif", name}, {"count", value}});
  }
  json::object data{{"count_by_motif", counts}, {"instances_complete_by_motif", completeness}},
      ports{{"counts", result_port("table", rows)}};
  if (listing) {
    bool complete = true;
    for (const auto& entry : completeness) complete = complete && entry.value().as_bool();
    data["instances_by_motif"] = instances;
    ports["instances"] = result_port("motif_instances", instances, complete);
  }
  return output({{"motifs", args.at("motifs")},
                 {"induced", induced},
                 {"occurrence_identity", identity},
                 {"list_instances", listing},
                 {"result_limit_per_motif", cap ? json::value(*cap) : json::value(nullptr)}},
                data, ports);
}
}  // namespace graphmine::runtime
