#include <queue>

#include "native_time.hpp"
#include "pattern_match.hpp"
#include "temporal_motif_input.hpp"

namespace graphmine::runtime {
namespace {
const ViewProfile query_profile{"temporal-motifs:cpp:query_records", {"temporal-motifs"},
  R"({"kind":"coo","coo_layout":"records","weights":"none","edge_ids":true,"sorted_neighbors":false})"};
const ViewProfile event_profile{"temporal-motifs:cpp:events", {"temporal-motifs"},
  R"({"kind":"coo","weights":"none","edge_ids":true,"sorted_neighbors":false})"};
const ViewProfile bundle_profile{"temporal-motifs:cpp:bundles", {"temporal-motifs"},
  R"({"kind":"coo","weights":"none","edge_ids":true,"sorted_neighbors":false})"};
}
TemporalQueryInput temporal_motif_query_input(const Graph& graph, Work& work) {
  const auto built=consume_view(graph,query_profile,work,ViewBudget::algorithm_owned);
  const auto& view=std::get<CooView>(built->view);
  TemporalQueryInput result;
  for (std::size_t i=0; i<view.src.size(); ++i) {
    const auto original=view.edge_ids->at(i);
    const auto u=view.vertices.to_original[view.src[i]], v=view.vertices.to_original[view.dst[i]];
    result.indices.emplace(graph.canonical().edges[original].id,original);
    result.incident.insert(u); result.incident.insert(v);
    result.sources.push_back(u); result.targets.push_back(v); result.originals.push_back(original);
  }
  return result;
}
TemporalEventInput temporal_motif_event_input(const Graph& graph, Work& work) {
  const auto built=consume_view(graph,event_profile,work,ViewBudget::algorithm_owned);
  const auto& view=std::get<CooView>(built->view);
  TemporalEventInput result;
  result.endpoints.resize(graph.edge_count());
  for (std::size_t i=0; i<view.src.size(); ++i) {
    if (view.symmetric && view.src[i]>view.dst[i]) continue;
    result.endpoints[view.edge_ids->at(i)] = {view.vertices.to_original[view.src[i]],view.vertices.to_original[view.dst[i]]};
  }
  // The view supplies canonical endpoints. Exact temporal/property decoding
  // remains in the common front, in original event order.
  for (std::size_t i=0; i<result.endpoints.size(); ++i) {
    work.tick();
    const auto& edge=graph.canonical().edges[i];
    result.times.push_back(timestamp_seconds(edge.timestamp,work));
    result.by_pair[result.endpoints[i]].push_back(i);
    result.records.push_back(edge_record_json(edge,work));
  }
  return result;
}
json::object temporal_motifs(const Graph& graph, const json::object& args, const std::string&, int,
                             Work& work) {
  using namespace family_util;
  fields(args,
         {"temporal_motif", "maximum_duration_seconds", "allow_equal_timestamps",
          "temporal_induced", "list_instances", "result_limit"},
         {"temporal_motif", "maximum_duration_seconds"});
  const auto spec = object(args.at("temporal_motif"), "temporal_motif");
  fields(spec, {"graph", "order", "vertex_predicates", "edge_predicates"}, {"graph"});
  const auto query = parse_graph(spec.at("graph"));
  require(query.directed() == graph.directed(), "Data and temporal motif direction must match");
  const auto& qe = query.canonical().edges;
  const auto& events = graph.canonical().edges;
  require(!qe.empty(), "Temporal motif needs an edge event");
  const auto query_input=temporal_motif_query_input(query,work);
  const auto& indices=query_input.indices;
  require(query_input.incident.size() == query.vertex_count(),
          "Temporal motifs cannot contain isolated vertices");
  const auto maximum =
      exact_number(args.at("maximum_duration_seconds"), "maximum_duration_seconds");
  require(maximum >= 0, "Duration must be nonnegative");
  const bool equal = boolean(args, "allow_equal_timestamps", false),
             induced = boolean(args, "temporal_induced", false),
             listing = boolean(args, "list_instances", false);
  const auto cap = limit(args);
  require(!cap || listing, "result_limit requires list_instances");
  json::array vp, ep;
  for (const auto* name : {"vertex_predicates", "edge_predicates"})
    if (spec.contains(name)) {
      require(spec.at(name).is_array(), std::string(name) + " must be an array");
      (std::string(name) == "vertex_predicates" ? vp : ep) = spec.at(name).as_array();
    }
  AttributePredicates edge_match(ep, query, true);
  std::vector<std::pair<std::size_t, std::size_t>> order;
  if (spec.contains("order")) {
    require(spec.at("order").is_array(), "Temporal order must be an array");
    for (const auto& pair : spec.at("order").as_array()) {
      require(pair.is_array() && pair.as_array().size() == 2, "Order needs edge-ID pairs");
      auto a = indices.find(external_id(pair.as_array()[0])),
           b = indices.find(external_id(pair.as_array()[1]));
      require(a != indices.end() && b != indices.end(), "Unknown temporal motif edge");
      order.emplace_back(a->second, b->second);
    }
  } else
    for (std::size_t i = 1; i < qe.size(); ++i) order.emplace_back(i - 1, i);
  std::vector<std::vector<std::size_t>> successors(qe.size());
  std::vector<std::size_t> indegree(qe.size());
  for (auto [a, b] : order) {
    successors[a].push_back(b);
    ++indegree[b];
  }
  std::queue<std::size_t> ready;
  for (std::size_t i = 0; i < qe.size(); ++i)
    if (!indegree[i]) ready.push(i);
  std::size_t visited = 0;
  while (!ready.empty()) {
    const auto a = ready.front();
    ready.pop();
    ++visited;
    for (auto b : successors[a])
      if (!--indegree[b]) ready.push(b);
  }
  require(visited == qe.size(), "Temporal order must be acyclic");
  const auto data_input=temporal_motif_event_input(graph,work);
  const auto& times=data_input.times;
  const auto& data_records=data_input.records;
  const auto& endpoints=data_input.endpoints;
  auto by_pair=data_input.by_pair;
  std::vector<json::object> query_records;
  using Pair = std::pair<VertexIndex, VertexIndex>;
  auto pair_key = [&](VertexIndex a, VertexIndex b) {
    if (!graph.directed() && a > b) std::swap(a, b);
    return Pair{a, b};
  };
  for (const auto i : query_input.originals) query_records.push_back(edge_record_json(qe[i], work));
  std::set<std::vector<std::size_t>> seen;
  std::vector<Integer> participation(graph.vertex_count(), 0);
  json::array instances;
  pattern_mappings(
      graph, query, false, vp, ep,
      [&](const Vertices& mapping) {
        std::vector<std::vector<std::size_t>> candidates(qe.size());
        for (std::size_t e = 0; e < qe.size(); ++e) {
          const auto key = pair_key(mapping[query_input.sources[e]],mapping[query_input.targets[e]]);
          for (const auto i : by_pair[key]) {
            work.tick();
            if (edge_match.match(data_records[i], query_records[e], work))
              candidates[e].push_back(i);
          }
          if (candidates[e].empty()) return true;
        }
        std::vector<std::size_t> chosen(qe.size()), next(qe.size());
        std::vector<bool> used(events.size(), false);
        std::size_t depth = 0;
        std::set<VertexIndex> image(mapping.begin(), mapping.end());
        for (;;) {
          work.tick();
          if (depth == qe.size()) {
            bool accept = !seen.count(chosen);
            Exact first = times[chosen[0]], last = first;
            for (const auto i : chosen) {
              first = std::min(first, times[i]);
              last = std::max(last, times[i]);
            }
            accept = accept && last - first <= maximum;
            if (accept && induced)
              for (std::size_t i = 0; i < events.size(); ++i) {
                work.tick();
                if (!used[i] && image.count(endpoints[i].first) &&
                    image.count(endpoints[i].second) && first <= times[i] && times[i] <= last) {
                  accept = false;
                  break;
                }
              }
            if (accept) {
              seen.insert(chosen);
              for (const auto v : image) ++participation[v];
              if (listing && (!cap || instances.size() < *cap)) {
                work.output(graph.vertex_count() +
                            (instances.size() + 1) * (1 + 2 * qe.size() + query.vertex_count()));
                json::array edge_ids, timestamps, exact_times;
                for (const auto i : chosen) {
                  edge_ids.push_back(id_json(events[i].id));
                  timestamps.push_back(display_number(times[i]));
                  exact_times.push_back(fraction_json(times[i]));
                }
                json::object row{{"edge_ids", edge_ids},
                                 {"timestamps", timestamps},
                                 {"timestamps_exact", exact_times},
                                 {"vertices", mapping_rows(graph, query, mapping)}};
                exact_field(row, "duration", last - first);
                instances.push_back(row);
              }
            }
            --depth;
            used[chosen[depth]] = false;
            continue;
          }
          if (next[depth] == candidates[depth].size()) {
            next[depth] = 0;
            if (!depth) break;
            --depth;
            used[chosen[depth]] = false;
            continue;
          }
          const auto candidate = candidates[depth][next[depth]++];
          if (used[candidate]) continue;
          chosen[depth] = candidate;
          bool valid = true;
          for (auto [a, b] : order)
            if (a <= depth && b <= depth &&
                (equal ? times[chosen[a]] > times[chosen[b]]
                       : times[chosen[a]] >= times[chosen[b]])) {
              valid = false;
              break;
            }
          if (!valid) continue;
          used[candidate] = true;
          ++depth;
          if (depth < qe.size()) next[depth] = 0;
        }
        return true;
      },
      work,bundle_profile);
  json::array rows;
  for (VertexIndex v = 0; v < graph.vertex_count(); ++v)
    rows.push_back(json::object{{"vertex", id_json(graph.external_id(v))},
                                {"value", display_number(Exact(participation[v]))}});
  const bool complete = listing && instances.size() == seen.size();
  work.output(rows.size() + instances.size() * (1 + 2 * qe.size() + query.vertex_count()));
  json::object data{{"occurrence_count", seen.size()},
                    {"instances_complete", complete},
                    {"per_vertex_participation", rows}},
      ports;
  if (listing) {
    data["instances"] = instances;
    ports["instances"] = result_port("temporal_occurrence_collection", instances, complete);
  }
  auto result = output({{"temporal_motif", spec},
                        {"maximum_duration_seconds", args.at("maximum_duration_seconds")},
                        {"allow_equal_timestamps", equal},
                        {"temporal_induced", induced},
                        {"list_instances", listing},
                        {"result_limit", cap ? json::value(*cap) : json::value(nullptr)}},
                       data, ports);
  result["diagnostics"] =
      json::object{{"count_complete", true},
                   {"occurrence_identity", "edge_id_tuple_in_motif_input_order"},
                   {"arithmetic", "exact_rational"}};
  return result;
}
}  // namespace graphmine::runtime
