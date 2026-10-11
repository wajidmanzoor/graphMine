#include "record_query.hpp"

namespace graphmine::runtime {
namespace {
using namespace family_util;
namespace query = record_query;
struct Collection {
  Work& work;
  std::optional<std::uint64_t> cap;
  json::array rows;
  std::uint64_t count = 0, items = 0;
  Collection(Work& work, const json::object& args) : work(work), cap(limit(args)) {}
  bool add(json::object row, std::size_t cost = 1) {
    work.tick();
    ++count;
    if (cap && rows.size() >= *cap) return false;
    items += cost;
    work.output(items);
    rows.push_back(std::move(row));
    return true;
  }
  bool complete() const { return count == rows.size(); }
};
json::object defaults(json::object args, std::initializer_list<const char*> filters,
                      bool capped = true) {
  for (const auto* name : filters)
    if (!args.contains(name)) args[name] = json::array{};
  if (capped && !args.contains("result_limit")) args["result_limit"] = nullptr;
  return args;
}
json::array vertex_ids(const Graph& graph, const std::set<std::size_t>& values) {
  json::array result;
  for (const auto v : values) result.push_back(id_json(graph.external_id(v)));
  return result;
}
json::array edge_ids(const query::Index& index, const std::set<std::size_t>& values) {
  json::array result;
  for (const auto e : values) result.push_back(index.edges[e].at("id"));
  return result;
}
}  // namespace
json::object node_lookup(const Graph& graph, const json::object& args, const std::string&, int,
                         Work& work) {
  fields(args, {"vertices", "vertex_filters", "result_limit"});
  const query::Index index(graph, work);
  const auto selected = index.selected(args, "vertices", false);
  const auto filters = index.filters(args, "vertex_filters", false);
  Collection output(work, args);
  json::array vertices;
  for (std::size_t v = 0; v < index.vertices.size(); ++v) {
    work.tick();
    if ((!selected || selected->count(v)) && filters.match(index.vertices[v], work) &&
        output.add(index.vertices[v]))
      vertices.push_back(index.vertices[v].at("id"));
  }
  auto parameters = defaults(args, {"vertex_filters"});
  if (!parameters.contains("vertices")) parameters["vertices"] = nullptr;
  auto rows = result_port("table", output.rows, output.complete());
  rows["vertex_field"] = "id";
  return query::result(
      parameters, output.rows, output.count,
      {{"rows", rows}, {"vertices", result_port("vertex_set", vertices, output.complete())}});
}
json::object edge_filter(const Graph& graph, const json::object& args, const std::string&, int,
                         Work& work) {
  fields(args, {"edge_ids", "edge_filters", "source_filters", "target_filters", "result_limit"});
  const query::Index index(graph, work);
  const auto selected = index.selected(args, "edge_ids", true);
  const auto edge_filters = index.filters(args, "edge_filters", true),
             source_filters = index.filters(args, "source_filters", false),
             target_filters = index.filters(args, "target_filters", false);
  Collection output(work, args);
  std::set<std::size_t> vertices, edges;
  for (std::size_t e = 0; e < index.edges.size(); ++e) {
    work.tick();
    const auto [u, v] = index.endpoints[e];
    if ((!selected || selected->count(e)) && edge_filters.match(index.edges[e], work) &&
        source_filters.match(index.vertices[u], work) &&
        target_filters.match(index.vertices[v], work) && output.add(index.edges[e])) {
      vertices.insert(u);
      vertices.insert(v);
      edges.insert(e);
    }
  }
  auto parameters = defaults(args, {"edge_filters", "source_filters", "target_filters"});
  if (!parameters.contains("edge_ids")) parameters["edge_ids"] = nullptr;
  return query::result(
      parameters, output.rows, output.count,
      {{"vertices", result_port("vertex_set", vertex_ids(graph, vertices), output.complete())},
       {"edges", result_port("edge_ids", edge_ids(index, edges), output.complete())}});
}
json::object query_neighbors(const Graph& graph, const json::object& args, const std::string&, int,
                             Work& work) {
  fields(args, {"entity", "hops", "direction", "edge_filters", "include_seed", "result_limit"},
         {"entity"});
  const query::Index index(graph, work);
  const auto adj = query::adjacency(index, args, work);
  const auto entity = graph.dense_index(external_id(args.at("entity")));
  const auto hops = natural(args, "hops", 1);
  const bool include = boolean(args, "include_seed", false);
  const auto distances = query::distances(adj, entity, hops, work);
  Collection output(work, args);
  json::array vertices;
  for (VertexIndex v = 0; v < graph.vertex_count(); ++v)
    if (distances[v] >= 0 && (include || v != entity) &&
        output.add({{"vertex", id_json(graph.external_id(v))}, {"distance", distances[v]}}))
      vertices.push_back(id_json(graph.external_id(v)));
  auto parameters = defaults(args, {"edge_filters"});
  parameters["hops"] = hops;
  parameters["include_seed"] = include;
  parameters["direction"] = choice(args, "direction", "out", {"out", "in", "both"});
  return query::result(parameters, output.rows, output.count,
                       {{"vertices", result_port("vertex_set", vertices, output.complete())}});
}
json::object query_common_neighbors(const Graph& graph, const json::object& args,
                                    const std::string&, int, Work& work) {
  fields(args, {"source", "target", "direction", "edge_filters", "result_limit"},
         {"source", "target"});
  const query::Index index(graph, work);
  const auto adj = query::adjacency(index, args, work);
  const auto source = graph.dense_index(external_id(args.at("source"))),
             target = graph.dense_index(external_id(args.at("target")));
  std::set<VertexIndex> left, right;
  for (const auto& [v, e] : adj[source]) left.insert(v);
  for (const auto& [v, e] : adj[target]) right.insert(v);
  Collection output(work, args);
  json::array vertices;
  for (VertexIndex v = 0; v < graph.vertex_count(); ++v)
    if (left.count(v) && right.count(v) && output.add({{"vertex", id_json(graph.external_id(v))}}))
      vertices.push_back(id_json(graph.external_id(v)));
  auto parameters = defaults(args, {"edge_filters"});
  parameters["direction"] = choice(args, "direction", "out", {"out", "in", "both"});
  return query::result(parameters, output.rows, output.count,
                       {{"vertices", result_port("vertex_set", vertices, output.complete())}});
}
json::object query_paths(const Graph& graph, const json::object& args, const std::string&, int,
                         Work& work) {
  fields(args,
         {"source", "target", "mode", "max_hops", "direction", "edge_filters", "result_limit"},
         {"source", "target"});
  const query::Index index(graph, work);
  const auto adj = query::adjacency(index, args, work);
  const auto source = graph.dense_index(external_id(args.at("source"))),
             target = graph.dense_index(external_id(args.at("target")));
  const auto mode = choice(args, "mode", "shortest", {"shortest", "all_simple"}),
             direction = choice(args, "direction", "out", {"out", "in", "both"});
  const auto requested = natural(args, "max_hops", 3),
             hops = std::min<std::uint64_t>(requested, graph.vertex_count() - 1);
  const auto distances = query::distances(adj, source, hops, work);
  Collection output(work, args);
  std::set<std::size_t> selected_vertices, selected_edges;
  auto emit = [&](const Vertices& vertices, const std::vector<std::size_t>& edges) {
    json::array eid;
    for (const auto e : edges) eid.push_back(index.edges[e].at("id"));
    if (output.add({{"vertices", ids(graph, vertices)}, {"edges", eid}, {"hops", edges.size()}},
                   1 + vertices.size() + edges.size())) {
      selected_vertices.insert(vertices.begin(), vertices.end());
      selected_edges.insert(edges.begin(), edges.end());
    }
  };
  if (source == target)
    emit({source}, {});
  else if (distances[target] >= 0) {
    const auto bound = mode == "shortest" ? static_cast<std::uint64_t>(distances[target]) : hops;
    Vertices vertices{source};
    std::vector<std::size_t> edges, next{0};
    std::vector<bool> visited(graph.vertex_count(), false);
    visited[source] = true;
    while (!vertices.empty()) {
      const auto u = vertices.back();
      if (next.back() == adj[u].size()) {
        visited[u] = false;
        vertices.pop_back();
        next.pop_back();
        if (!edges.empty()) edges.pop_back();
        continue;
      }
      work.tick();
      const auto [v, e] = adj[u][next.back()++];
      if (visited[v] || edges.size() >= bound) continue;
      if (mode == "shortest" && distances[v] != static_cast<std::int64_t>(edges.size() + 1))
        continue;
      if (v == target) {
        auto path_vertices = vertices;
        path_vertices.push_back(v);
        auto path_edges = edges;
        path_edges.push_back(e);
        emit(path_vertices, path_edges);
      } else if (edges.size() + 1 < bound) {
        visited[v] = true;
        vertices.push_back(v);
        edges.push_back(e);
        next.push_back(0);
      }
    }
  }
  auto parameters = defaults(args, {"edge_filters"});
  parameters["mode"] = mode;
  parameters["direction"] = direction;
  parameters["max_hops"] = requested;
  return query::result(
      parameters, output.rows, output.count,
      {{"vertices",
        result_port("vertex_set", vertex_ids(graph, selected_vertices), output.complete())},
       {"edges", result_port("edge_ids", edge_ids(index, selected_edges), output.complete())}});
}

json::object graph_aggregate(const Graph& graph, const json::object& args, const std::string&, int,
                             Work& work) {
  fields(args,
         {"scope", "filters", "metric", "field", "group_by", "direction", "order", "result_limit"});
  const query::Index index(graph, work);
  const auto scope = choice(args, "scope", "edges", {"vertices", "edges"}),
             metric = choice(args, "metric", "count", {"count", "sum", "avg", "min", "max"}),
             direction = choice(args, "direction", "out", {"out", "in", "both"}),
             order = choice(args, "order", "input", {"input", "ascending", "descending"});
  const auto raw_field = args.contains("field") ? args.at("field") : json::value(nullptr),
             raw_group = args.contains("group_by") ? args.at("group_by") : json::value(nullptr);
  const auto field = raw_field.is_null() ? "" : string(raw_field, "field"),
             group = raw_group.is_null() ? "" : string(raw_group, "group_by");
  require(metric == "count" ? raw_field.is_null() : !raw_field.is_null(),
          "Numeric aggregation needs an explicit field; count must omit field");
  const bool vertex_groups = group == "vertex", edge_scope = scope == "edges";
  require(direction == "out" || (vertex_groups && edge_scope),
          "direction applies only to per-vertex edge aggregation");
  const auto& records = edge_scope ? index.edges : index.vertices;
  const query::Filters filters(
      args.contains("filters") ? args.at("filters") : json::value(json::array{}), records,
      edge_scope);
  if (!raw_field.is_null()) query::check_field(records, field, edge_scope);
  if (!raw_group.is_null() && !vertex_groups) query::check_field(records, group, edge_scope);
  struct Bucket {
    json::value group;
    std::uint64_t count = 0;
    Exact sum = 0;
    std::optional<Exact> minimum, maximum;
  };
  std::vector<Bucket> buckets;
  std::map<std::string, std::size_t> bucket_indices;
  auto bucket = [&](const json::value& group) -> Bucket& {
    const auto key = query::scalar_key(group);
    const auto [it, inserted] = bucket_indices.emplace(key, buckets.size());
    if (inserted) buckets.push_back({group});
    return buckets[it->second];
  };
  if (vertex_groups && edge_scope)
    for (const auto& vertex : index.vertices) bucket(vertex.at("id"));
  else if (raw_group.is_null())
    bucket(nullptr);
  for (std::size_t i = 0; i < records.size(); ++i) {
    work.tick();
    const auto& record = records[i];
    if (!filters.match(record, work)) continue;
    Exact value = 1;
    if (metric != "count") {
      const auto* raw = record_field(record, field);
      require(raw && raw->is_number(),
              "Every matched record needs a finite numeric aggregate field");
      value = decimal_number(*raw, "aggregate");
    }
    json::array groups;
    if (vertex_groups) {
      if (!edge_scope)
        groups.push_back(record.at("id"));
      else {
        const auto [u, v] = index.endpoints[i];
        if (!graph.directed() || direction == "out" || direction == "both")
          groups.push_back(record.at("source"));
        if ((!graph.directed() || direction == "in" || direction == "both") &&
            (groups.empty() || u != v))
          groups.push_back(record.at("target"));
      }
    } else if (raw_group.is_null())
      groups.push_back(nullptr);
    else {
      const auto* value = record_field(record, group);
      require(value && query::scalar(*value), "Every matched record needs a scalar group_by field");
      groups.push_back(*value);
    }
    for (const auto& name : groups) {
      auto& row = bucket(name);
      ++row.count;
      row.sum += value;
      row.minimum = row.minimum ? std::min(*row.minimum, value) : value;
      row.maximum = row.maximum ? std::max(*row.maximum, value) : value;
    }
  }
  struct Row {
    json::object data;
    std::optional<Exact> value;
  };
  std::vector<Row> rows;
  for (const auto& bucket : buckets) {
    work.tick();
    std::optional<Exact> value;
    if (metric == "count")
      value = Exact(bucket.count);
    else if (metric == "sum")
      value = bucket.sum;
    else if (metric == "avg") {
      if (bucket.count) value = bucket.sum / bucket.count;
    } else
      value = metric == "min" ? bucket.minimum : bucket.maximum;
    json::value display = nullptr, exact = nullptr;
    bool rounded = false;
    if (value) {
      display = display_number(*value);
      require(display.is_number(), "Aggregate cannot be displayed as a finite JSON number");
      exact = fraction_json(*value);
      rounded = display.is_double() && Exact(display.as_double()) != *value;
    }
    rows.push_back({{{vertex_groups ? "vertex" : "group", bucket.group},
                     {"value", display},
                     {"exact_value", exact},
                     {"rounded", rounded},
                     {"record_count", bucket.count}},
                    value});
  }
  if (order != "input")
    std::stable_sort(rows.begin(), rows.end(), [&](const Row& a, const Row& b) {
      work.tick();
      if (!a.value || !b.value) return a.value.has_value() && !b.value.has_value();
      return order == "ascending" ? (*a.value < *b.value) : (*a.value > *b.value);
    });
  Collection output(work, args);
  for (auto& row : rows) output.add(std::move(row.data));
  json::object ports;
  if (vertex_groups) {
    auto scores = result_port("vertex_scores", output.rows, output.complete());
    scores["score_field"] = "value";
    scores["exact_score_field"] = "exact_value";
    ports["scores"] = scores;
  }
  auto parameters = defaults(args, {"filters"});
  parameters["scope"] = scope;
  parameters["metric"] = metric;
  parameters["field"] = raw_field;
  parameters["group_by"] = raw_group;
  parameters["direction"] = direction;
  parameters["order"] = order;
  return query::result(parameters, output.rows, output.count, ports);
}

json::object query_subgraph(const Graph& graph, const json::object& args, const std::string&, int,
                            Work& work) {
  fields(args, {"mode", "vertices", "edge_ids", "entity", "hops", "direction", "vertex_filters",
                "edge_filters"});
  const query::Index index(graph, work);
  const auto mode = choice(args, "mode", "vertices", {"vertices", "edges", "neighborhood"}),
             direction = choice(args, "direction", "out", {"out", "in", "both"});
  const auto hops = natural(args, "hops", 1);
  const auto vertices = index.selected(args, "vertices", false),
             edges = index.selected(args, "edge_ids", true);
  const auto vertex_filters = index.filters(args, "vertex_filters", false),
             edge_filters = index.filters(args, "edge_filters", true);
  const bool entity = args.contains("entity") && !args.at("entity").is_null();
  require(mode != "vertices" || vertices.has_value(),
          "Vertex extraction needs an explicit vertices array");
  require(mode == "neighborhood" || (!entity && hops == 1 && direction == "out"),
          "entity, hops and direction apply only to neighborhood mode");
  require(mode != "neighborhood" || (entity && !vertices),
          "Neighborhood mode needs entity and cannot accept vertices");
  std::vector<bool> selected(graph.vertex_count(), mode != "vertices");
  if (mode == "neighborhood") {
    const auto seed = graph.dense_index(external_id(args.at("entity")));
    const auto distances = query::distances(query::adjacency(index, args, work), seed, hops, work);
    for (std::size_t v = 0; v < selected.size(); ++v) selected[v] = distances[v] >= 0;
  }
  for (std::size_t v = 0; v < selected.size(); ++v) {
    if (mode == "vertices")
      selected[v] = vertices->count(v);
    else if (vertices && !vertices->count(v))
      selected[v] = false;
    if (!vertex_filters.match(index.vertices[v], work)) selected[v] = false;
  }
  json::array edge_records;
  std::set<std::size_t> used_edges, endpoints;
  for (std::size_t e = 0; e < index.edges.size(); ++e) {
    work.tick();
    const auto [u, v] = index.endpoints[e];
    if (selected[u] && selected[v] && (!edges || edges->count(e)) &&
        edge_filters.match(index.edges[e], work)) {
      edge_records.push_back(index.edges[e]);
      used_edges.insert(e);
      endpoints.insert(u);
      endpoints.insert(v);
    }
  }
  if (mode == "edges")
    for (std::size_t v = 0; v < selected.size(); ++v)
      selected[v] = selected[v] && endpoints.count(v);
  // Build only selected records; the original fingerprint is supplied by the
  // request boundary, so hashing a large input consumes no output allowance.
  auto derived = selected_graph(graph, std::vector<bool>(graph.vertex_count(), false), work);
  json::array vertex_records;
  std::set<std::size_t> used_vertices;
  for (std::size_t v = 0; v < selected.size(); ++v)
    if (selected[v]) {
      vertex_records.push_back(index.vertices[v]);
      used_vertices.insert(v);
    }
  derived["vertices"] = vertex_records;
  derived["edges"] = edge_records;
  derived.at("graph").as_object()["id"] = "query:" + work.input_fingerprint;
  work.output(vertex_records.size() + edge_records.size());
  auto parameters = defaults(args, {"vertex_filters", "edge_filters"}, false);
  parameters["mode"] = mode;
  parameters["hops"] = hops;
  parameters["direction"] = direction;
  for (const auto* key : {"vertices", "edge_ids", "entity"})
    if (!parameters.contains(key)) parameters[key] = nullptr;
  return output(parameters,
                {{"graph", derived},
                 {"vertex_count", vertex_records.size()},
                 {"edge_count", edge_records.size()}},
                {{"graph", result_port("graph", derived)},
                 {"vertices", result_port("vertex_set", vertex_ids(graph, used_vertices))},
                 {"edges", result_port("edge_ids", edge_ids(index, used_edges))}});
}
}  // namespace graphmine::runtime
