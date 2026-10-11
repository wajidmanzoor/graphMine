#include "pattern_match.hpp"
#include "structured_input.hpp"

namespace graphmine::runtime {
namespace {
using namespace family_util;
struct Labeled {
  bool directed;
  std::string vertex_field, edge_field;
  std::vector<json::value> labels;
  struct Edge {
    VertexIndex u, v;
    json::value label;
  };
  std::vector<Edge> edges;
};
Labeled normalize(const Graph& graph, const std::string& vf, const std::string& ef,
                  const std::string& loops, const std::string& parallel, Work& work) {
  Labeled out{graph.directed(), vf, ef, {}, {}};
  std::map<std::pair<VertexIndex, VertexIndex>, json::value> edges;
  for (const auto& v : graph.canonical().vertices) {
    work.tick();
    const auto record = vertex_record_json(v, work);
    out.labels.push_back(!vf.empty() && record.contains(vf) ? record.at(vf) : json::value(nullptr));
  }
  for (const auto& e : graph.canonical().edges) {
    work.tick();
    auto u = graph.dense_index(e.source), v = graph.dense_index(e.target);
    if (u == v) {
      require(loops == "drop", "Frequent patterns reject self-loops");
      continue;
    }
    if (!out.directed && u > v) std::swap(u, v);
    const json::value label = !ef.empty() && e.type ? json::value(*e.type) : json::value(nullptr);
    const auto [it, inserted] = edges.emplace(std::make_pair(u, v), label);
    if (!inserted) {
      require(parallel == "collapse", "Parallel edges require explicit collapse");
      require(typed_equal(it->second, label, work),
              "Cannot collapse different selected edge types");
    }
  }
  for (const auto& [pair, label] : edges) out.edges.push_back({pair.first, pair.second, label});
  return out;
}
struct CanonicalPattern {
  std::string key;
  json::object graph;
};
CanonicalPattern canonical_pattern(const Labeled& host, const Vertices& vertices,
                                   const Vertices& chosen, Work& work) {
  std::vector<std::size_t> inverse(host.labels.size(), 0);
  std::optional<std::string> best;
  json::array best_vertices, best_edges;
  // Label-sorted permutations omit no isomorphism class. The minimum complete
  // serialization, rather than a hash, is the actual deduplication key.
  injective_assignments(
      vertices.size(), vertices.size(), work,
      [&](const Vertices& order) {
        json::array labels, records, edges;
        for (std::size_t i = 0; i < order.size(); ++i) {
          const auto v = vertices[order[i]];
          inverse[v] = i;
          labels.push_back(host.labels[v]);
          json::object row{{"id", i}};
          if (!host.vertex_field.empty() && !host.labels[v].is_null())
            row[host.vertex_field] = host.labels[v];
          records.push_back(row);
        }
        std::vector<std::tuple<std::size_t, std::size_t, json::value>> sorted;
        for (const auto i : chosen) {
          work.tick();
          const auto& e = host.edges[i];
          auto u = inverse[e.u], v = inverse[e.v];
          if (!host.directed && u > v) std::swap(u, v);
          sorted.emplace_back(u, v, e.label);
        }
        std::sort(sorted.begin(), sorted.end(), [](const auto& a, const auto& b) {
          return std::make_pair(std::get<0>(a), std::get<1>(a)) <
                 std::make_pair(std::get<0>(b), std::get<1>(b));
        });
        json::array edge_key;
        for (const auto& [u, v, label] : sorted) {
          edge_key.push_back(json::array{u, v, label});
          json::object row{{"id", edges.size()}, {"source", u}, {"target", v}};
          if (!host.edge_field.empty() && !label.is_null()) row[host.edge_field] = label;
          edges.push_back(row);
        }
        const auto key =
            json::serialize(json::array{"native-lexicographic-v1", host.directed, host.vertex_field,
                                        host.edge_field, labels, edge_key});
        work.tick(key.size());
        if (!best || key < *best) {
          best = key;
          best_vertices = records;
          best_edges = edges;
        }
        return true;
      },
      [&](const Vertices& order, VertexIndex v) {
        return order.empty() || json::serialize(host.labels[vertices[order.back()]]) <=
                                    json::serialize(host.labels[vertices[v]]);
      });
  require(best.has_value(), "Canonical pattern enumeration failed");
  const auto id = "pattern-" + input_fingerprint(json::value(*best));
  return {*best,
          {{"graph",
            {{"id", id},
             {"directed", host.directed},
             {"allows_self_loops", false},
             {"allows_parallel_edges", false}}},
           {"vertices", best_vertices},
           {"edges", best_edges}}};
}
bool connected(const Labeled& host, const Vertices& vertices, const Vertices& edges, Work& work) {
  if (vertices.empty()) return false;
  std::map<VertexIndex, Vertices> adj;
  for (const auto i : edges) {
    const auto& e = host.edges[i];
    adj[e.u].push_back(e.v);
    adj[e.v].push_back(e.u);
  }
  std::set<VertexIndex> visited{vertices[0]};
  Vertices queue{vertices[0]};
  for (std::size_t at = 0; at < queue.size(); ++at)
    for (const auto v : adj[queue[at]]) {
      work.tick();
      if (visited.insert(v).second) queue.push_back(v);
    }
  return visited.size() == vertices.size();
}
}  // namespace

json::object frequent_subgraphs(const json::value& input, const json::object& args, Work& work) {
  using namespace family_util;
  fields(args,
         {"minimum_support_fraction", "minimum_edges", "maximum_edges", "minimum_vertices",
          "maximum_vertices", "induced", "label_semantics", "self_loops", "parallel_edges",
          "include_supporting_graph_ids"},
         {"minimum_support_fraction", "maximum_edges"});
  const auto collection = graph_collection(input, work);
  const auto support =
      decimal_number(args.at("minimum_support_fraction"), "minimum_support_fraction");
  require(support > 0 && support <= 1, "Support fraction must be in (0,1]");
  const auto minimum_edges = natural(args, "minimum_edges", 1),
             maximum_edges = natural(args, "maximum_edges", 0),
             minimum_vertices = natural(args, "minimum_vertices", 1);
  const auto maximum_vertices = limit(args, "maximum_vertices", 0);
  require(minimum_edges <= maximum_edges &&
              (!maximum_vertices || minimum_vertices <= *maximum_vertices),
          "Minimum pattern bounds must not exceed maximum bounds");
  const auto semantics = choice(args, "label_semantics", "vertex_and_edge_type",
                                {"unlabeled", "vertex_type", "edge_type", "vertex_and_edge_type"}),
             loops = choice(args, "self_loops", "reject", {"reject", "drop"}),
             parallel = choice(args, "parallel_edges", "reject", {"reject", "collapse"});
  const std::string vf = (semantics == "vertex_type" || semantics == "vertex_and_edge_type")
                             ? "type"
                             : "",
                    ef = (semantics == "edge_type" || semantics == "vertex_and_edge_type") ? "type"
                                                                                           : "";
  const bool induced = boolean(args, "induced", false),
             include_ids = boolean(args, "include_supporting_graph_ids", false);
  struct Record {
    json::object graph;
    std::vector<std::string> ids;
  };
  std::map<std::string, Record> records;
  for (const auto& graph : collection) {
    const auto host = normalize(graph, vf, ef, loops, parallel, work);
    std::set<std::string> seen;
    const auto maximum =
        std::min<std::uint64_t>(host.labels.size(), maximum_vertices.value_or(host.labels.size()));
    for (std::size_t size = minimum_vertices; size <= maximum; ++size)
      combinations(host.labels.size(), size, work, [&](const Vertices& vertices) {
        const std::set<VertexIndex> members(vertices.begin(), vertices.end());
        Vertices inside;
        for (std::size_t i = 0; i < host.edges.size(); ++i) {
          work.tick();
          if (members.count(host.edges[i].u) && members.count(host.edges[i].v)) inside.push_back(i);
        }
        auto save = [&](const Vertices& chosen) {
          const auto pattern = canonical_pattern(host, vertices, chosen, work);
          if (seen.insert(pattern.key).second) {
            auto [it, inserted] = records.emplace(pattern.key, Record{pattern.graph, {}});
            it->second.ids.push_back(graph.canonical().graph.id);
          }
          return true;
        };
        if (induced) {
          if (inside.size() >= minimum_edges && inside.size() <= maximum_edges) save(inside);
        } else
          for (std::size_t count = minimum_edges;
               count <= std::min<std::uint64_t>(maximum_edges, inside.size()); ++count)
            combinations(inside.size(), count, work, [&](const Vertices& selection) {
              Vertices chosen;
              for (const auto i : selection) chosen.push_back(inside[i]);
              return save(chosen);
            });
        return true;
      });
  }
  json::array patterns;
  std::uint64_t materialized = 0;
  for (auto& [key, record] : records) {
    if (Exact(record.ids.size()) < support * collection.size()) continue;
    const auto n = record.graph.at("vertices").as_array().size(),
               m = record.graph.at("edges").as_array().size();
    json::object row{
        {"pattern_id", record.graph.at("graph").as_object().at("id")},
        {"pattern", record.graph},
        {"vertex_count", n},
        {"edge_count", m},
        {"support_graph_count", record.ids.size()},
        {"support_fraction", display_number(Exact(record.ids.size()) / collection.size())}};
    if (include_ids) {
      std::sort(record.ids.begin(), record.ids.end());
      json::array ids;
      for (const auto& id : record.ids) ids.push_back(json::value(id));
      row["supporting_graph_ids"] = ids;
      materialized += ids.size();
    }
    materialized += 1 + n + m;
    work.output(materialized);
    patterns.push_back(row);
  }
  json::object parameters{{"minimum_support_fraction", args.at("minimum_support_fraction")},
                          {"minimum_edges", minimum_edges},
                          {"maximum_edges", maximum_edges},
                          {"minimum_vertices", minimum_vertices},
                          {"maximum_vertices", maximum_vertices ? json::value(*maximum_vertices)
                                                                : json::value(nullptr)},
                          {"induced", induced},
                          {"label_semantics", semantics},
                          {"self_loops", loops},
                          {"parallel_edges", parallel},
                          {"include_supporting_graph_ids", include_ids}};
  auto result = output(parameters,
                       {{"patterns", patterns},
                        {"complete", true},
                        {"frequent_pattern_count", patterns.size()},
                        {"transaction_count", collection.size()}},
                       {{"patterns", result_port("pattern_collection", patterns)},
                        {"count", result_port("scalar", patterns.size())}});
  result["diagnostics"] =
      json::object{{"support", "transaction_presence"},
                   {"canonicalization", "native-lexicographic-v1"},
                   {"pattern_vertex_namespace", "local to each canonical pattern"},
                   {"threshold_comparison", "exact decimal rational"}};
  return result;
}

json::object single_graph_frequent(const Graph& graph, const json::object& args, const std::string&,
                                   int, Work& work) {
  using namespace family_util;
  fields(args,
         {"minimum_image_support", "max_pattern_edges", "match_mode", "output_mode",
          "vertex_label_field", "parallel_edges", "include_images"},
         {"minimum_image_support", "max_pattern_edges"});
  require(!graph.directed(), "Single-graph frequent mining requires undirected input");
  const auto support = natural(args, "minimum_image_support", 1, 1),
             maximum = natural(args, "max_pattern_edges", 1, 1);
  const auto match = choice(args, "match_mode", "non_induced", {"non_induced", "induced"}),
             mode = choice(args, "output_mode", "count", {"count", "patterns"}),
             field = choice(args, "vertex_label_field", "label", {"label", "type"}),
             parallel = choice(args, "parallel_edges", "reject", {"reject", "collapse"});
  const bool include = boolean(args, "include_images", false), induced = match == "induced";
  require(!include || mode == "patterns", "include_images requires patterns output");
  const auto host = normalize(graph, field, "", "reject", parallel, work);
  for (const auto& label : host.labels)
    require(label.is_string(), "Every vertex needs the selected label/type");
  // Match against the normalized simple host, retaining its original IDs.
  json::array normalized_vertices, normalized_edges;
  for (std::size_t v = 0; v < host.labels.size(); ++v)
    normalized_vertices.push_back(
        json::object{{"id", id_json(graph.external_id(v))}, {field, host.labels[v]}});
  for (const auto& e : host.edges)
    normalized_edges.push_back(json::object{{"id", normalized_edges.size()},
                                            {"source", id_json(graph.external_id(e.u))},
                                            {"target", id_json(graph.external_id(e.v))}});
  const auto normalized = parse_graph(json::object{{"graph",
                                                    {{"id", "normalized"},
                                                     {"directed", false},
                                                     {"allows_self_loops", false},
                                                     {"allows_parallel_edges", false}}},
                                                   {"vertices", normalized_vertices},
                                                   {"edges", normalized_edges}});
  std::set<std::string> seen;
  json::array patterns;
  std::uint64_t count = 0, materialized = 0;
  auto candidate = [&](const Vertices& vertices, const Vertices& edges) {
    const auto pattern = canonical_pattern(host, vertices, edges, work);
    if (!seen.insert(pattern.key).second) return;
    const auto query = parse_graph(pattern.graph);
    std::vector<std::set<VertexIndex>> images(vertices.size());
    pattern_mappings(
        normalized, query, induced,
        json::array{json::object{{"field", field}, {"operator", "eq_query"}}}, {},
        [&](const Vertices& mapping) {
          for (std::size_t v = 0; v < mapping.size(); ++v) images[v].insert(mapping[v]);
          return true;
        },
        work);
    std::size_t value = graph.vertex_count();
    for (const auto& image : images) value = std::min(value, image.size());
    if (value < support) return;
    ++count;
    if (mode == "count") return;
    json::array image_counts, image_rows;
    for (std::size_t v = 0; v < images.size(); ++v) {
      image_counts.push_back(json::object{{"pattern_vertex", v}, {"count", images[v].size()}});
      if (include) {
        image_rows.push_back(json::object{
            {"pattern_vertex", v},
            {"host_vertices", ids(graph, Vertices(images[v].begin(), images[v].end()))}});
        materialized += images[v].size();
      }
    }
    json::object row{{"pattern_id", pattern.graph.at("graph").as_object().at("id")},
                     {"pattern", pattern.graph},
                     {"vertex_count", vertices.size()},
                     {"edge_count", edges.size()},
                     {"minimum_image_support", value},
                     {"image_counts", image_counts}};
    if (include) row["images"] = image_rows;
    materialized += 1 + 2 * vertices.size() + edges.size();
    work.output(materialized);
    patterns.push_back(row);
  };
  if (support <= host.labels.size()) {
    for (VertexIndex v = 0; v < host.labels.size(); ++v) candidate({v}, {});
    for (std::size_t size = 1; size <= std::min<std::uint64_t>(maximum, host.edges.size()); ++size)
      combinations(host.edges.size(), size, work, [&](const Vertices& chosen) {
        std::set<VertexIndex> members;
        for (const auto e : chosen) {
          members.insert(host.edges[e].u);
          members.insert(host.edges[e].v);
        }
        const Vertices vertices(members.begin(), members.end());
        if (vertices.size() > size + 1 || !connected(host, vertices, chosen, work)) return true;
        if (induced) {
          std::size_t inside = 0;
          for (const auto& e : host.edges) {
            work.tick();
            if (members.count(e.u) && members.count(e.v)) ++inside;
          }
          if (inside != size) return true;
        }
        candidate(vertices, chosen);
        return true;
      });
  }
  std::sort(patterns.begin(), patterns.end(), [](const auto& a, const auto& b) {
    return a.as_object().at("pattern_id").as_string() < b.as_object().at("pattern_id").as_string();
  });
  json::object ports{{"count", result_port("scalar", count)}};
  if (mode == "patterns") ports["patterns"] = result_port("pattern_collection", patterns);
  auto result =
      output({{"minimum_image_support", support},
              {"max_pattern_edges", maximum},
              {"match_mode", match},
              {"output_mode", mode},
              {"vertex_label_field", field},
              {"parallel_edges", parallel},
              {"include_images", include}},
             {{"frequent_pattern_count", count},
              {"patterns", mode == "patterns" ? json::value(patterns) : json::value(nullptr)},
              {"completed", true}},
             ports);
  result["diagnostics"] =
      json::object{{"support", "minimum_image_support"},
                   {"canonicalization", "native-lexicographic-v1"},
                   {"pattern_vertex_namespace", "local to each canonical pattern"}};
  return result;
}
}  // namespace graphmine::runtime
