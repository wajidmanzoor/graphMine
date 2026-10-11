#include <queue>

#include "family_util.hpp"
#include "native_time.hpp"

namespace graphmine::runtime {
json::object widest_paths(const Graph& graph, const json::object& args, const std::string&, int,
                          Work& work) {
  using namespace family_util;
  fields(args, {"source_vertex"}, {"source_vertex"});
  const auto source = graph.dense_index(external_id(args.at("source_vertex")));
  const auto n = graph.vertex_count();
  std::vector<std::vector<std::pair<VertexIndex, double>>> adj(n);
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    require(edge.weight && *edge.weight >= 0,
            "Every widest-path edge requires a nonnegative capacity");
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    adj[u].emplace_back(v, *edge.weight);
    if (!graph.directed()) adj[v].emplace_back(u, *edge.weight);
  }
  std::vector<std::optional<double>> capacity(n);
  std::vector<std::optional<VertexIndex>> parent(n);
  capacity[source] = std::numeric_limits<double>::infinity();
  std::priority_queue<std::pair<double, VertexIndex>> queue;
  queue.emplace(*capacity[source], source);
  while (!queue.empty()) {
    work.tick();
    const auto [value, u] = queue.top();
    queue.pop();
    if (value != *capacity[u]) continue;
    for (const auto& [v, weight] : adj[u]) {
      work.tick();
      const auto candidate = std::min(value, weight);
      if (!capacity[v] || candidate > *capacity[v]) {
        capacity[v] = candidate;
        parent[v] = u;
        queue.emplace(candidate, v);
      }
    }
  }
  work.output(n);
  json::array rows;
  for (VertexIndex v = 0; v < n; ++v) {
    json::object row{
        {"vertex", id_json(graph.external_id(v))},
        {"reachable", capacity[v].has_value()},
        {"is_source", v == source},
        {"predecessor", parent[v] ? id_json(graph.external_id(*parent[v])) : json::value(nullptr)},
        {"bottleneck_capacity", nullptr}};
    if (v != source && capacity[v]) exact_field(row, "bottleneck_capacity", Exact(*capacity[v]));
    rows.push_back(row);
  }
  return output({{"source_vertex", id_json(graph.external_id(source))}}, {{"vertices", rows}},
                {{"paths", result_port("widest_path_tree", rows)}});
}

json::object critical_paths(const Graph& graph, const json::object& args, const std::string&, int,
                            Work& work) {
  using namespace family_util;
  fields(args, {"k", "sources", "sinks"}, {"k"});
  require(graph.directed(), "Critical paths require a directed acyclic graph");
  const auto k = natural(args, "k", 1, 1);
  require(k < UINT64_MAX, "k exceeds native indexing capacity");
  const auto n = graph.vertex_count();
  const auto& raw = graph.canonical().edges;
  std::vector<std::vector<std::size_t>> adj(n);
  std::vector<std::size_t> indegree(n, 0);
  for (std::size_t i = 0; i < raw.size(); ++i) {
    work.tick();
    require(raw[i].weight.has_value(), "Critical paths require every edge weight");
    const auto u = graph.dense_index(raw[i].source), v = graph.dense_index(raw[i].target);
    adj[u].push_back(i);
    ++indegree[v];
  }
  Vertices sources, sinks;
  if (args.contains("sources") && !args.at("sources").is_null())
    sources = vertices(graph, args.at("sources"), "sources");
  else
    for (VertexIndex v = 0; v < n; ++v)
      if (!indegree[v]) sources.push_back(v);
  if (args.contains("sinks") && !args.at("sinks").is_null())
    sinks = vertices(graph, args.at("sinks"), "sinks");
  else
    for (VertexIndex v = 0; v < n; ++v)
      if (adj[v].empty()) sinks.push_back(v);
  std::queue<VertexIndex> queue;
  for (VertexIndex v = 0; v < n; ++v)
    if (!indegree[v]) queue.push(v);
  Vertices order;
  while (!queue.empty()) {
    work.tick();
    const auto u = queue.front();
    queue.pop();
    order.push_back(u);
    for (const auto e : adj[u]) {
      work.tick();
      const auto v = graph.dense_index(raw[e].target);
      if (--indegree[v] == 0) queue.push(v);
    }
  }
  require(order.size() == n, "Critical paths require acyclic input, including no self-loops");
  struct Path {
    Exact weight;
    VertexIndex start;
    std::vector<std::size_t> edges;
  };
  const auto less = [&](const Path& a, const Path& b) {
    work.tick();
    if (a.weight != b.weight) return a.weight > b.weight;
    if (a.edges != b.edges) return a.edges < b.edges;
    return a.start < b.start;
  };
  std::vector<std::vector<Path>> suffixes(n);
  std::vector<bool> is_sink(n, false);
  for (const auto v : sinks) is_sink[v] = true;
  for (auto it = order.rbegin(); it != order.rend(); ++it) {
    const auto u = *it;
    auto& current = suffixes[u];
    if (is_sink[u]) current.push_back({0, u, {}});
    for (const auto e : adj[u]) {
      const auto v = graph.dense_index(raw[e].target);
      for (const auto& suffix : suffixes[v]) {
        work.tick(suffix.edges.size() + 1);
        Path path{Exact(*raw[e].weight) + suffix.weight, u, {e}};
        path.edges.insert(path.edges.end(), suffix.edges.begin(), suffix.edges.end());
        current.push_back(std::move(path));
      }
      std::sort(current.begin(), current.end(), less);
      if (current.size() > k + 1) current.resize(k + 1);
    }
  }
  std::vector<Path> paths;
  for (const auto v : sources) {
    for (const auto& path : suffixes[v]) {
      work.tick(path.edges.size() + 1);
      paths.push_back(path);
    }
    std::sort(paths.begin(), paths.end(), less);
    if (paths.size() > k + 1) paths.resize(k + 1);
  }
  const bool complete = paths.size() <= k;
  if (!complete) paths.resize(k);
  json::array rows;
  std::uint64_t output_items = 0;
  for (const auto& path : paths) {
    json::array edge_ids, vertex_ids{id_json(graph.external_id(path.start))};
    output_items += 1 + 2 * path.edges.size();
    work.output(output_items);
    for (const auto i : path.edges) {
      edge_ids.push_back(id_json(raw[i].id));
      vertex_ids.push_back(id_json(raw[i].target));
    }
    json::object row{{"edges", edge_ids},
                     {"vertices", vertex_ids},
                     {"weight_fraction", fraction_json(path.weight)}};
    exact_field(row, "total_weight", path.weight);
    rows.push_back(row);
  }
  auto result =
      output({{"k", k},
              {"sources", args.contains("sources") ? args.at("sources") : json::value(nullptr)},
              {"sinks", args.contains("sinks") ? args.at("sinks") : json::value(nullptr)}},
             {{"paths", rows}, {"complete", true}, {"all_paths_returned", complete}},
             {{"paths", result_port("path_set", rows, complete)}});
  result["diagnostics"] =
      json::object{{"ranking_arithmetic", "exact_rational"},
                   {"solver", "native_DAG_k_best_suffixes"},
                   {"zero_edge_paths", "included when a source is also a sink"}};
  return result;
}

json::object temporal_paths(const Graph& graph, const json::object& args, const std::string&, int,
                            Work& work) {
  using namespace family_util;
  fields(args, {"source", "ready_time", "deadline", "objective", "duration_attribute"},
         {"source", "ready_time"});
  require(graph.directed(), "Temporal paths require directed input");
  const auto source = graph.dense_index(external_id(args.at("source")));
  const auto ready = exact_number(args.at("ready_time"), "ready_time");
  std::optional<Exact> deadline;
  if (args.contains("deadline") && !args.at("deadline").is_null()) {
    deadline = exact_number(args.at("deadline"), "deadline");
    require(*deadline >= ready, "deadline precedes ready_time");
  }
  const auto objective =
      choice(args, "objective", "fastest_duration", {"fastest_duration", "earliest_arrival"});
  const auto attribute = args.contains("duration_attribute")
                             ? string(args.at("duration_attribute"), "duration_attribute")
                             : "duration";
  require(!attribute.empty(), "duration_attribute must be nonempty");
  struct Event {
    VertexIndex u, v;
    Exact departure, arrival;
    std::size_t edge;
  };
  const auto n = graph.vertex_count();
  std::vector<Event> events;
  std::vector<std::set<Exact>> times(n);
  times[source].insert(ready);
  const auto& raw = graph.canonical().edges;
  for (std::size_t i = 0; i < raw.size(); ++i) {
    work.tick();
    const auto& edge = raw[i];
    const auto departure = timestamp_seconds(edge.timestamp, work);
    const auto it = edge.attributes.find(attribute);
    require(it != edge.attributes.end(), "Every event needs the requested duration attribute");
    const auto& value = it->second.value();
    Exact duration;
    if (std::holds_alternative<std::int64_t>(value))
      duration = std::get<std::int64_t>(value);
    else {
      require(std::holds_alternative<double>(value), "Event duration must be numeric");
      duration = std::get<double>(value);
    }
    require(duration >= 0, "Event duration must be nonnegative");
    const Exact arrival = departure + duration;
    if (departure < ready || (deadline && arrival > *deadline)) continue;
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    events.push_back({u, v, departure, arrival, i});
    times[u].insert(departure);
    times[v].insert(arrival);
  }
  struct State {
    VertexIndex vertex;
    Exact time;
  };
  struct Arc {
    std::size_t target;
    Exact cost;
    std::optional<std::size_t> edge;
  };
  std::vector<State> states;
  std::vector<std::map<Exact, std::size_t>> indexes(n);
  for (VertexIndex v = 0; v < n; ++v)
    for (const auto& time : times[v]) {
      work.tick();
      indexes[v][time] = states.size();
      states.push_back({v, time});
    }
  std::vector<std::vector<Arc>> adj(states.size() + 1);
  for (VertexIndex v = 0; v < n; ++v) {
    std::optional<std::pair<Exact, std::size_t>> before;
    for (const auto& item : indexes[v]) {
      work.tick();
      if (before) adj[before->second].push_back({item.second, item.first - before->first, {}});
      before = item;
    }
  }
  for (const auto& event : events) {
    work.tick();
    adj[indexes[event.u].at(event.departure)].push_back(
        {indexes[event.v].at(event.arrival), event.arrival - event.departure, event.edge});
  }
  const auto start = objective == "fastest_duration" ? states.size() : indexes[source].at(ready);
  if (objective == "fastest_duration")
    for (const auto& item : indexes[source]) adj[start].push_back({item.second, 0, {}});
  std::vector<std::optional<Exact>> distances(adj.size());
  std::vector<std::optional<std::pair<std::size_t, std::size_t>>> predecessors(adj.size());
  using Item = std::pair<Exact, std::size_t>;
  std::priority_queue<Item, std::vector<Item>, std::greater<Item>> queue;
  distances[start] = 0;
  queue.emplace(0, start);
  while (!queue.empty()) {
    work.tick();
    const auto [distance, u] = queue.top();
    queue.pop();
    if (distance != *distances[u]) continue;
    for (std::size_t i = 0; i < adj[u].size(); ++i) {
      work.tick();
      const auto& arc = adj[u][i];
      const Exact candidate = distance + arc.cost;
      if (!distances[arc.target] || candidate < *distances[arc.target]) {
        distances[arc.target] = candidate;
        predecessors[arc.target] = {u, i};
        queue.emplace(candidate, arc.target);
      }
    }
  }
  std::vector<std::optional<std::size_t>> best(n);
  auto value_at = [&](std::size_t i) -> Exact {
    return objective == "earliest_arrival" ? states[i].time : *distances[i];
  };
  for (std::size_t i = 0; i < states.size(); ++i)
    if (distances[i]) {
      const auto v = states[i].vertex;
      if (!best[v] || std::make_pair(value_at(i), states[i].time) <
                          std::make_pair(value_at(*best[v]), states[*best[v]].time))
        best[v] = i;
    }
  json::array rows;
  std::uint64_t output_items = n;
  for (VertexIndex v = 0; v < n; ++v) {
    json::object row{{"vertex", id_json(graph.external_id(v))},
                     {"reachable", best[v].has_value()},
                     {"value", nullptr},
                     {"value_fraction", nullptr},
                     {"edges", json::array{}},
                     {"departure", nullptr},
                     {"arrival", nullptr}};
    if (best[v]) {
      std::size_t current = *best[v];
      std::vector<std::size_t> path;
      while (predecessors[current]) {
        work.tick();
        const auto [u, i] = *predecessors[current];
        if (adj[u][i].edge) path.push_back(*adj[u][i].edge);
        current = u;
        require(path.size() <= adj.size(), "Temporal predecessor witness contains a cycle");
      }
      std::reverse(path.begin(), path.end());
      json::array edge_ids;
      for (const auto i : path) edge_ids.push_back(id_json(raw[i].id));
      const Exact value = value_at(*best[v]);
      exact_field(row, "value", value);
      row["value_fraction"] = value.str();
      row["edges"] = edge_ids;
      exact_field(row, "departure",
                  path.empty() ? ready : timestamp_seconds(raw[path.front()].timestamp, work));
      exact_field(row, "arrival", path.empty() ? ready : states[*best[v]].time);
      output_items += path.size();
    }
    work.output(output_items);
    rows.push_back(row);
  }
  auto result =
      output({{"source", id_json(graph.external_id(source))},
              {"ready_time", args.at("ready_time")},
              {"deadline", args.contains("deadline") ? args.at("deadline") : json::value(nullptr)},
              {"objective", objective},
              {"duration_attribute", attribute}},
             {{"values", rows}, {"complete", true}},
             {{"paths", result_port("temporal_path_table", rows)}});
  result["diagnostics"] =
      json::object{{"arithmetic", "exact_rational"},
                   {"waiting_before_first_departure", "excluded_from_fastest_duration"}};
  return result;
}
}  // namespace graphmine::runtime
