#include "family_util.hpp"
#include "native_time.hpp"
#include "enumeration_input.hpp"

namespace graphmine::runtime {
namespace {
const ViewProfile enumeration_records{"bounded-paths-cycles:cpp:records", {"bounded-paths-cycles"},
  R"({"kind":"coo","coo_layout":"records","weights":"none","edge_ids":true,"sorted_neighbors":false})"};
const ViewProfile enumeration_first{"bounded-paths-cycles:cpp:collapse_first", {"bounded-paths-cycles"},
  R"({"kind":"coo","direction":"keep","self_loops":"drop","parallel_edges":"collapse:first",
       "weights":"none","edge_ids":true,"sorted_neighbors":false})"};
const ViewProfile enumeration_parallel{"bounded-paths-cycles:cpp:preserve", {"bounded-paths-cycles"},
  R"({"kind":"coo","direction":"keep","self_loops":"drop","parallel_edges":"keep",
       "weights":"none","edge_ids":true,"sorted_neighbors":false})"};
}
EnumerationInput enumeration_input(const Graph& graph, bool preserve_parallel, bool chronological,
                                   std::optional<std::size_t> anchor, Work& work) {
  require(graph.directed(),"Bounded path and cycle enumeration requires directed input");
  const auto records = consume_view(graph,enumeration_records,work,ViewBudget::algorithm_owned);
  const auto retained = consume_view(graph,preserve_parallel ? enumeration_parallel : enumeration_first,
                                     work,ViewBudget::algorithm_owned);
  const auto& raw = std::get<CooView>(records->view);
  const auto& kept = std::get<CooView>(retained->view);
  std::vector<bool> present(graph.edge_count());
  for (const auto e : *kept.edge_ids) present[e] = true;
  EnumerationInput result;
  result.adjacency.resize(graph.vertex_count());
  result.times.resize(graph.edge_count()); result.ends.resize(graph.edge_count());
  for (std::size_t i=0; i<raw.src.size(); ++i) {
    work.tick();
    const auto e = raw.edge_ids->at(i);
    const auto u = raw.src[i], v = raw.dst[i];
    result.ends[e] = v;
    if (!present[e]) {
      if (anchor && *anchor == e)
        throw Failure("invalid_input",u == v ? "anchor_edge is a discarded self-loop" :
          "anchor_edge was collapsed; select preserve parallel edges");
      continue;
    }
    result.adjacency[u].push_back(e);
    if (chronological) result.times[e] = timestamp_seconds(graph.canonical().edges[e].timestamp,work);
  }
  return result;
}
json::object bounded_paths_cycles(const Graph& graph, const json::object& args, const std::string&,
                                  int, Work& work) {
  using namespace family_util;
  fields(args,
         {"task", "source", "target", "anchor_edge", "max_hops", "result_limit",
          "chronological_order_required", "parallel_edge_policy"},
         {"task", "max_hops"});
  require(graph.directed(), "Bounded path and cycle enumeration requires directed input");
  const auto task =
      choice(args, "task", "all_cycles",
             {"s_t_path", "cycle_through_vertex", "cycle_through_edge", "all_cycles"});
  const auto parallel =
      choice(args, "parallel_edge_policy", "collapse_first", {"collapse_first", "preserve"});
  const auto hops = natural(args, "max_hops", 1, 1);
  const auto cap = limit(args);
  const bool chronological = boolean(args, "chronological_order_required", false);
  auto present = [&](const char* name) { return args.contains(name) && !args.at(name).is_null(); };
  require(present("source") == (task == "s_t_path" || task == "cycle_through_vertex"),
          "source is required only for path and cycle-through-vertex tasks");
  require(present("target") == (task == "s_t_path"), "target is required only for s_t_path");
  require(present("anchor_edge") == (task == "cycle_through_edge"),
          "anchor_edge is required only for cycle_through_edge");
  std::optional<VertexIndex> source, target;
  if (present("source")) source = graph.dense_index(external_id(args.at("source")));
  if (present("target")) {
    target = graph.dense_index(external_id(args.at("target")));
    require(source != target, "s_t_path requires distinct endpoints");
  }
  const auto& raw = graph.canonical().edges;
  const auto n = graph.vertex_count();
  std::optional<std::size_t> anchor;
  if (present("anchor_edge")) {
    const auto id = external_id(args.at("anchor_edge"));
    for (std::size_t i = 0; i < raw.size(); ++i)
      if (raw[i].id == id) anchor = i;
    require(anchor.has_value(), "Unknown anchor_edge");
  }
  const auto input = enumeration_input(graph,parallel == "preserve",chronological,anchor,work);
  const auto& adj = input.adjacency; const auto& times = input.times; const auto& ends = input.ends;
  using Sequence = std::vector<std::size_t>;
  const auto less = [](const Sequence& a, const Sequence& b) {
    return a.size() == b.size() ? a < b : a.size() < b.size();
  };
  std::set<Sequence, decltype(less)> kept(less);
  std::uint64_t count = 0, output_items = 0;
  auto emit = [&](Sequence sequence) {
    work.tick(sequence.size());
    if (anchor && std::find(sequence.begin(), sequence.end(), *anchor) == sequence.end()) return;
    if (task != "s_t_path" && task != "cycle_through_vertex") {
      auto first = std::min_element(sequence.begin(), sequence.end(), [&](auto a, auto b) {
        return chronological && times[a] != times[b] ? times[a] < times[b] : a < b;
      });
      std::rotate(sequence.begin(), first, sequence.end());
    }
    if (chronological)
      for (std::size_t i = 1; i < sequence.size(); ++i)
        if (times[sequence[i - 1]] >= times[sequence[i]]) return;
    if (count == UINT64_MAX) throw Failure("resource_limit", "Path/cycle count exceeds uint64");
    ++count;
    if (cap && kept.size() == *cap && !less(sequence, *kept.rbegin())) return;
    output_items += 1 + sequence.size();
    kept.insert(std::move(sequence));
    if (cap && kept.size() > *cap) {
      const auto last = std::prev(kept.end());
      output_items -= 1 + last->size();
      kept.erase(last);
    }
    work.output(output_items);
  };
  Vertices starts = source ? Vertices{*source} : all_vertices(graph);
  for (const auto start : starts) {
    struct Frame {
      VertexIndex vertex;
      std::size_t next;
    };
    work.tick(n);
    std::vector<bool> visited(n, false);
    std::vector<Frame> stack{{start, 0}};
    Sequence path;
    visited[start] = true;
    while (!stack.empty()) {
      work.tick();
      auto& frame = stack.back();
      if (frame.next == adj[frame.vertex].size() || path.size() == hops) {
        visited[frame.vertex] = false;
        stack.pop_back();
        if (!path.empty()) path.pop_back();
        continue;
      }
      const auto e = adj[frame.vertex][frame.next++];
      const auto v = ends[e];
      if (task != "s_t_path" && v == start && !path.empty()) {
        auto candidate = path;
        candidate.push_back(e);
        emit(std::move(candidate));
        continue;
      }
      if (visited[v] || (!source && v < start)) continue;
      if (target && v == *target) {
        auto candidate = path;
        candidate.push_back(e);
        emit(std::move(candidate));
        continue;
      }
      if (path.size() + 1 == hops) continue;
      visited[v] = true;
      path.push_back(e);
      stack.push_back({v, 0});
    }
  }
  json::array sequences, vertex_sequences;
  for (const auto& sequence : kept) {
    json::array edge_ids, vertex_ids{id_json(raw[sequence.front()].source)};
    for (const auto i : sequence) {
      edge_ids.push_back(id_json(raw[i].id));
      vertex_ids.push_back(id_json(raw[i].target));
    }
    sequences.push_back(edge_ids);
    vertex_sequences.push_back(vertex_ids);
  }
  const bool complete = count == kept.size();
  json::object resolved = args;
  for (const auto key : {"source", "target", "anchor_edge"})
    if (!resolved.contains(key)) resolved[key] = nullptr;
  resolved["result_limit"] = cap ? json::value(*cap) : json::value(nullptr);
  resolved["chronological_order_required"] = chronological;
  resolved["parallel_edge_policy"] = parallel;
  auto result = output(
      resolved,
      {{"paths_or_cycles", sequences},
       {"vertex_sequences", vertex_sequences},
       {"result_count", kept.size()},
       {"total_count", count},
       {"complete", complete},
       {"shortest_length_found",
        kept.empty() ? json::value(nullptr) : json::value(kept.begin()->size())}},
      {{"sequences", result_port("edge_sequence_collection", sequences, complete)}}, complete);
  result["diagnostics"] = json::object{
      {"count_complete", true},
      {"parallel_edge_policy", parallel},
      {"cycle_start", "source_for_vertex_task_otherwise_earliest_event_or_first_input_edge"}};
  return result;
}
}  // namespace graphmine::runtime
