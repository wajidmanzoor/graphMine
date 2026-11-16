#include <algorithm>
#include <map>
#include <set>

#include "exact_flow.hpp"
#include "internal.hpp"
#include "flow_input.hpp"

namespace graphmine::runtime {
namespace {
const ViewProfile flow_weight_records{"max-flow-min-cut:cpp:weight_records", {"max-flow-min-cut"},
  R"({"kind":"coo","self_loops":"keep","parallel_edges":"keep","weights":"rational_exact",
       "require_edge_weights":true,"nonnegative_weights":true,"edge_ids":true,"sorted_neighbors":false})"};
const ViewProfile flow_unit_records{"max-flow-min-cut:cpp:unit_records", {"max-flow-min-cut"},
  R"({"kind":"coo","self_loops":"keep","parallel_edges":"keep","weights":"rational_exact",
       "weight_source":"unit","edge_ids":true,"sorted_neighbors":false})"};
const ViewProfile flow_weight_sum{"max-flow-min-cut:cpp:weight_sum", {"max-flow-min-cut"},
  R"({"kind":"coo","self_loops":"drop","parallel_edges":"collapse:sum","weights":"rational_exact",
       "require_edge_weights":true,"nonnegative_weights":true})"};
const ViewProfile flow_unit_sum{"max-flow-min-cut:cpp:unit_sum", {"max-flow-min-cut"},
  R"({"kind":"coo","self_loops":"drop","parallel_edges":"collapse:sum","weights":"rational_exact","weight_source":"unit"})"};
}
FlowInput flow_input(const Graph& graph, bool unit, Work& work) {
  std::shared_ptr<const ViewResult> records;
  try {
    records = consume_view(graph,unit ? flow_unit_records : flow_weight_records,work,ViewBudget::record_edges);
  } catch (const Failure& error) {
    if (std::string(error.what()) == "This operation requires nonnegative edge weights")
      throw Failure("invalid_input","Edge capacities must be nonnegative");
    throw;
  } catch (const std::invalid_argument& error) {
    if (std::string(error.what()) == "Graph view: This view requires explicit edge weights")
      throw Failure("invalid_input","Edge-weight capacity mode requires every edge weight");
    throw;
  }
  const auto summed = consume_view(graph,unit ? flow_unit_sum : flow_weight_sum,work,ViewBudget::algorithm_owned);
  const auto& normalized = std::get<CooView>(summed->view);
  const auto& weights = std::get<std::vector<RationalWeight>>(normalized.weights);
  auto exact = [](const RationalWeight& weight) -> Exact { return Exact(Integer(weight.numerator))/Integer(weight.denominator); };
  FlowInput result;
  for (std::size_t i=0; i<normalized.src.size(); ++i) {
    const auto capacity = exact(weights[i]);
    result.arcs[{normalized.vertices.to_original[normalized.src[i]],normalized.vertices.to_original[normalized.dst[i]]}].capacity = capacity;
    result.capacity_sum += capacity;
  }
  const auto& original = std::get<CooView>(records->view);
  const auto& capacities = std::get<std::vector<RationalWeight>>(original.weights);
  for (std::size_t i=0; i<original.src.size(); ++i) {
    const auto u=original.vertices.to_original[original.src[i]],v=original.vertices.to_original[original.dst[i]];
    const auto capacity = exact(capacities[i]);
    const auto edge = original.edge_ids->at(i);
    if (u==v) result.loops.push_back({edge,u,capacity});
    else result.arcs.at({u,v}).originals.push_back({edge,capacity});
  }
  return result;
}
json::object max_flow(const Graph& graph, const json::object& args, const std::string& backend,
                      int device, Work& work) {
  fields(args,
         {"source", "sink", "capacity_mode", "return_cut_side", "vertex_capacities",
          "solution_quality"},
         {"source", "sink"});
  const auto source = graph.dense_index(external_id(args.at("source"))),
             sink = graph.dense_index(external_id(args.at("sink")));
  require(source != sink, "Source and sink must be distinct");
  const auto mode = args.contains("capacity_mode")
                        ? string(args.at("capacity_mode"), "capacity_mode")
                        : "edge_weight";
  require(mode == "unit_capacity" || mode == "edge_weight", "Unknown capacity_mode");
  const bool cut_side = boolean(args, "return_cut_side", true);
  const auto quality = args.contains("solution_quality")
                           ? string(args.at("solution_quality"), "solution_quality")
                           : "exact";
  require(quality == "exact" || quality == "approximate", "Unknown solution_quality");
  const auto n = graph.vertex_count();
  work.tick(n + graph.edge_count());
  work.output(graph.edge_count() * (graph.directed() ? 1 : 2) + (cut_side ? n : 0));
  std::vector<std::optional<Exact>> vertex_capacities(n);
  json::array resolved_capacities;
  if (args.contains("vertex_capacities") && !args.at("vertex_capacities").is_null()) {
    require(args.at("vertex_capacities").is_array(),
            "vertex_capacities is an array of {vertex, capacity} records to preserve typed IDs");
    for (const auto& raw : args.at("vertex_capacities").as_array()) {
      work.tick();
      const auto row = object(raw, "vertex capacity");
      fields(row, {"vertex", "capacity"}, {"vertex", "capacity"});
      const auto v = graph.dense_index(external_id(row.at("vertex")));
      require(!vertex_capacities[v], "Duplicate vertex capacity");
      const auto capacity = exact_number(row.at("capacity"), "vertex capacity");
      require(capacity >= 0, "Vertex capacities must be nonnegative");
      vertex_capacities[v] = capacity;
      resolved_capacities.push_back(row);
    }
  }
  std::map<std::pair<VertexIndex, VertexIndex>, FlowInput::Arc> arcs;
  Exact capacity_sum = 0;
  json::array flows;
  auto add = [&](VertexIndex u, VertexIndex v, std::size_t edge, const Exact& capacity) {
    auto& arc = arcs[{u, v}];
    arc.capacity += capacity;
    arc.originals.push_back({edge, capacity});
    capacity_sum += capacity;
  };
  auto flow_row = [&](std::size_t index, VertexIndex u, VertexIndex v, const Exact& capacity,
                      const Exact& amount) {
    json::object row{{"edge", id_json(graph.canonical().edges[index].id)},
                     {"source", id_json(graph.external_id(u))},
                     {"target", id_json(graph.external_id(v))}};
    exact_field(row, "capacity", capacity);
    exact_field(row, "flow", amount);
    return row;
  };
  if (backend == "cpp") {
    auto prepared = flow_input(graph,mode == "unit_capacity",work);
    arcs = std::move(prepared.arcs); capacity_sum = std::move(prepared.capacity_sum);
    for (const auto& loop : prepared.loops) flows.push_back(flow_row(loop.edge,loop.vertex,loop.vertex,loop.capacity,0));
  } else for (std::size_t i = 0; i < graph.edge_count(); ++i) {
    work.tick();
    const auto& edge = graph.canonical().edges[i];
    require(mode == "unit_capacity" || edge.weight.has_value(),
            "Edge-weight capacity mode requires every edge weight");
    const Exact capacity = mode == "unit_capacity" ? Exact(1) : Exact(*edge.weight);
    require(capacity >= 0, "Edge capacities must be nonnegative");
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) {
      flows.push_back(flow_row(i, u, v, capacity, 0));
      continue;
    }
    add(u, v, i, capacity);
    if (!graph.directed()) add(v, u, i, capacity);
  }
  // Splitting every vertex makes optional vertex capacities precise, including
  // explicitly supplied source/sink limits. Unspecified limits exceed every
  // possible edge-only flow and cannot appear in an optimal cut.
  ExactFlow network(2 * n);
  std::vector<std::size_t> internal(n);
  for (VertexIndex v = 0; v < n; ++v) {
    work.tick();
    internal[v] = network.add(2 * std::size_t(v), 2 * std::size_t(v) + 1,
                              vertex_capacities[v].value_or(capacity_sum + 1));
  }
  for (auto& [ends, arc] : arcs) {
    work.tick();
    arc.position =
        network.add(2 * std::size_t(ends.first) + 1, 2 * std::size_t(ends.second), arc.capacity);
  }
  Exact value = 0;
  if (backend == "cpp")
    value = network.solve(2 * std::size_t(source), 2 * std::size_t(sink) + 1, work);
  else {
    std::vector<IntegerFlowArc> input;
    for (const auto& [ends, arc] : arcs)
      input.push_back({ends.first, ends.second, arc.capacity.convert_to<std::int64_t>()});
    const auto result = original_flow(n, input, source, sink, device, work);
    std::vector<Exact> incoming(n, 0), outgoing(n, 0);
    std::size_t i = 0;
    for (const auto& [ends, arc] : arcs) {
      work.tick();
      const Exact amount = result.at(i++);
      const auto [u, v] = ends;
      network.set_flow(2 * std::size_t(u) + 1, arc.position, amount);
      incoming[v] += amount;
      outgoing[u] += amount;
    }
    value = incoming[sink] - outgoing[sink];
    if (value < 0) throw Failure("correctness_mismatch", "CUDA flow has negative terminal value");
    for (VertexIndex v = 0; v < n; ++v)
      network.set_flow(2 * std::size_t(v), internal[v], v == source ? outgoing[v] : incoming[v]);
  }
  const auto reachable = network.reachable(2 * std::size_t(source), work);
  if (reachable[2 * std::size_t(sink) + 1])
    throw Failure("correctness_mismatch", "Residual flow still reaches the sink");
  Exact cut = 0;
  std::set<std::size_t> cut_originals;
  json::array cut_edges, cut_vertices, normalized, vertex_flows, source_side, sink_side,
      split_sides;
  std::vector<Exact> balance(n, 0);
  for (const auto& [ends, arc] : arcs) {
    work.tick();
    const auto [u, v] = ends;
    const Exact amount = network.flow(2 * std::size_t(u) + 1, arc.position);
    if (amount < 0 || amount > arc.capacity)
      throw Failure("correctness_mismatch", "Flow exceeds an edge capacity");
    balance[u] -= amount;
    balance[v] += amount;
    Exact remaining = amount;
    json::array ids;
    for (const auto& original : arc.originals) {
      work.tick();
      const Exact part = std::min(remaining, original.capacity);
      remaining -= part;
      flows.push_back(flow_row(original.edge, u, v, original.capacity, part));
      ids.push_back(id_json(graph.canonical().edges[original.edge].id));
      if (reachable[2 * std::size_t(u) + 1] && !reachable[2 * std::size_t(v)])
        cut_originals.insert(original.edge);
    }
    if (remaining != 0)
      throw Failure("correctness_mismatch", "Parallel flow allocation lost capacity");
    json::object row{{"source", id_json(graph.external_id(u))},
                     {"target", id_json(graph.external_id(v))},
                     {"source_edge_ids", ids}};
    exact_field(row, "capacity", arc.capacity);
    exact_field(row, "flow", amount);
    normalized.push_back(row);
    if (reachable[2 * std::size_t(u) + 1] && !reachable[2 * std::size_t(v)]) cut += arc.capacity;
  }
  for (VertexIndex v = 0; v < n; ++v) {
    work.tick();
    const auto id = id_json(graph.external_id(v));
    const Exact expected = v == source ? -value : v == sink ? value : Exact(0);
    if (balance[v] != expected)
      throw Failure("correctness_mismatch", "Flow conservation or terminal value is incorrect");
    const auto amount = network.flow(2 * std::size_t(v), internal[v]);
    if (amount < 0 || (vertex_capacities[v] && amount > *vertex_capacities[v]))
      throw Failure("correctness_mismatch", "Flow violates a vertex capacity");
    if (vertex_capacities[v]) {
      json::object row{{"vertex", id}};
      exact_field(row, "capacity", *vertex_capacities[v]);
      exact_field(row, "flow", amount);
      vertex_flows.push_back(row);
    }
    if (reachable[2 * std::size_t(v)] && !reachable[2 * std::size_t(v) + 1]) {
      if (!vertex_capacities[v])
        throw Failure("correctness_mismatch", "Unbounded vertex appears in minimum cut");
      cut_vertices.push_back(id);
      cut += *vertex_capacities[v];
    }
    if (cut_side) {
      (reachable[2 * std::size_t(v)] ? source_side : sink_side).push_back(id);
      split_sides.push_back(json::object{{"vertex", id},
                                         {"input_reachable", reachable[2 * std::size_t(v)]},
                                         {"output_reachable", reachable[2 * std::size_t(v) + 1]}});
    }
  }
  if (cut != value)
    throw Failure("correctness_mismatch", "Flow value and exact cut capacity differ");
  for (const auto index : cut_originals)
    cut_edges.push_back(id_json(graph.canonical().edges[index].id));
  work.output(flows.size() + normalized.size() + vertex_flows.size() + cut_edges.size() +
              cut_vertices.size() + (cut_side ? n : 0));
  json::object result{{"optimal", true},
                      {"min_cut_edges", cut_edges},
                      {"min_cut_vertices", cut_vertices},
                      {"flow_assignment", flows},
                      {"flows", flows},
                      {"normalized_arcs", normalized},
                      {"vertex_flows", vertex_flows}};
  for (const auto key : {"max_flow_value", "flow_value", "min_cut_value", "cut_capacity"})
    exact_field(result, key, value);
  json::object ports{{"value", result_port("scalar", display_number(value))}};
  if (cut_side) {
    result["source_side_vertices"] = source_side;
    result["source_side"] = source_side;
    result["sink_side"] = sink_side;
    result["split_source_side"] = split_sides;
    ports["vertices"] = result_port("vertex_set", source_side);
  }
  const json::object parameters{
      {"source", id_json(graph.external_id(source))},
      {"sink", id_json(graph.external_id(sink))},
      {"capacity_mode", mode},
      {"return_cut_side", cut_side},
      {"vertex_capacities",
       resolved_capacities.empty() ? json::value(nullptr) : json::value(resolved_capacities)},
      {"solution_quality", quality}};
  return {
      {"parameters", parameters},
      {"result", result},
      {"ports", ports},
      {"complete", true},
      {"quality", "exact"},
      {"diagnostics",
       {{"arithmetic", "exact rational capacities; sums do not overflow binary64"},
        {"cut_convention",
         "edge capacities plus explicitly limited split vertices; terminal limits are respected"},
        {"undirected_flow_convention", "two directed assignments per non-loop input edge"}}}};
}
}  // namespace graphmine::runtime
