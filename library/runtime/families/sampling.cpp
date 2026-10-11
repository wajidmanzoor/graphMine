#include "internal.hpp"
#include "native_random.hpp"
#include "native_time.hpp"

#include <algorithm>
#include <map>
#include <numeric>
#include <set>

namespace graphmine::runtime {
namespace {
std::vector<VertexIndex> selected_ids(const Graph& graph, const json::value& value, Work& work) {
  require(value.is_array(), "Seeds must be an array"); std::vector<VertexIndex> output;
  for (const auto& id : value.as_array()) { work.tick(); output.push_back(graph.dense_index(external_id(id))); }
  return output;
}
json::array external_ids(const Graph& graph, const std::vector<VertexIndex>& vertices) {
  json::array result; for (const auto v : vertices) result.push_back(id_json(graph.external_id(v))); return result;
}
std::int64_t fanout(const json::value& value) {
  require(value.is_int64() || (value.is_uint64() && value.as_uint64() <= INT64_MAX), "Fanouts must be signed 64-bit integers");
  const auto count = value.to_number<std::int64_t>(); require(count >= -1, "Fanouts must be -1 or nonnegative"); return count;
}
struct Neighbor { VertexIndex vertex; std::size_t edge; Exact weight; };
}
json::object random_walks(const Graph& graph, const json::object& args, const std::string& backend, int device, Work& work) {
  fields(args, {"start_vertices","length","walk_model","p","q","random_seed"}, {"start_vertices","length"});
  const auto starts = selected_ids(graph,args.at("start_vertices"),work); const auto length = uint(args.at("length"),"length");
  const auto model = args.contains("walk_model") ? string(args.at("walk_model"),"walk_model") : "uniform";
  require(model == "uniform" || model == "weighted" || model == "node2vec", "Unknown walk_model");
  const Exact p = args.contains("p") ? exact_number(args.at("p"),"p") : Exact(1), q = args.contains("q") ? exact_number(args.at("q"),"q") : Exact(1);
  require(p > 0 && q > 0, "Node2vec p and q must be positive"); require(model == "node2vec" || (p == 1 && q == 1), "p and q apply only to node2vec");
  NativeRandom rng(args); work.tick(graph.vertex_count());
  std::vector<std::map<VertexIndex,Exact>> adj(graph.vertex_count());
  for (const auto& edge : graph.canonical().edges) {
    work.tick(); const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target); const Exact weight = model == "uniform" ? Exact(1) : Exact(edge.weight.value_or(1));
    require(weight >= 0, "Walk weights must be nonnegative");
    auto add = [&](VertexIndex from, VertexIndex to) { if (model == "uniform") adj[from][to] = 1; else adj[from][to] += weight; };
    add(u,v); if (!graph.directed() && u != v) add(v,u);
  }
  std::vector<std::vector<VertexIndex>> paths;
  if (backend == "cpp") {
    std::size_t used = 0;
    for (const auto source : starts) {
      std::vector<VertexIndex> path{source}; work.output(used+1);
      for (std::uint64_t step = 0; step < length; ++step) {
        work.tick(); const auto current = path.back(); if (adj[current].empty()) break;
        std::vector<VertexIndex> candidates; std::vector<Exact> weights;
        for (const auto& [v,weight] : adj[current]) {
          work.tick(); candidates.push_back(v); Exact value = weight;
          if (model == "node2vec" && path.size() > 1) { const auto previous = path[path.size()-2]; if (v == previous) value /= p; else if (!adj[previous].count(v)) value /= q; }
          weights.push_back(value);
        }
        const auto chosen = model == "uniform" ? std::optional<std::size_t>(rng.uniform(candidates.size(),work)) : rng.weighted(weights,work);
        if (!chosen) break;
        work.output(used+path.size()+1); path.push_back(candidates[*chosen]);
      }
      used += path.size(); paths.push_back(std::move(path));
    }
  } else {
    WeightedGraph input{std::vector<std::vector<Arc>>(adj.size()),true};
    for (VertexIndex u = 0; u < adj.size(); ++u) {
      Exact maximum = 0; for (const auto& [v,w] : adj[u]) maximum = std::max(maximum,w);
      for (const auto& [v,w] : adj[u]) if (w > 0) {
        work.tick(); const auto weight = (w/maximum).convert_to<double>();
        if (weight == 0) throw Failure("unsupported_input", "A positive GPU walk probability underflows float64; use native CPU");
        input.rows[u].push_back({v,weight});
      }
    }
    paths = cugraph_walks(input,starts,length,model,p.convert_to<double>(),q.convert_to<double>(),rng.seed,device,work);
  }
  if (paths.size() != starts.size()) throw Failure("correctness_mismatch", "Walk output has the wrong start count");
  json::array result, lengths; std::size_t used = 0;
  for (std::size_t i = 0; i < paths.size(); ++i) {
    const auto& path = paths[i];
    if (path.empty() || path.front() != starts[i] || path.size()-1 > length) throw Failure("correctness_mismatch", "Walk length or start is invalid");
    for (std::size_t j = 1; j < path.size(); ++j) { work.tick(); const auto found = adj.at(path[j-1]).find(path[j]); if (found == adj.at(path[j-1]).end() || (model != "uniform" && found->second == 0)) throw Failure("correctness_mismatch", "Walk uses an ineligible transition"); }
    if (path.size()-1 < length) for (const auto& [v,w] : adj.at(path.back())) { work.tick(); if (w > 0) throw Failure("correctness_mismatch", "Walk stopped before a genuine dead end"); }
    used += path.size(); work.output(used); result.push_back(external_ids(graph,path)); lengths.push_back(path.size()-1);
  }
  return {{"parameters",{{"start_vertices",external_ids(graph,starts)},{"length",length},{"walk_model",model},{"p",display_number(p)},{"q",display_number(q)},{"random_seed",rng.seed}}},
          {"result",{{"walks",result},{"lengths",lengths}}},{"ports",{{"walks",result_port("walk_sample",result)}}},{"complete",true},{"quality","stochastic"},
          {"diagnostics",{{"random_seed",rng.seed},{"generator",backend=="cpp"?"mt19937_64 with integer rejection sampling":"native libcugraph RNG"},
                          {"probability_arithmetic",backend=="cpp"?"exact rational weights":"float64"},{"node2vec_adjacency","previous_to_candidate_arc"},
                          {"parallel_edges",model=="uniform"?"collapse neighbors":"sum weights exactly"},{"self_loops","retained"}}}};
}
json::object neighborhood_sampling(const Graph& graph, const json::object& args, const std::string& backend, int device, Work& work) {
  fields(args, {"seeds","fanouts","replacement","sampling_model","edge_type_fanouts","time_cutoff","random_seed"}, {"seeds","fanouts"});
  const auto seeds = selected_ids(graph,args.at("seeds"),work); require(args.at("fanouts").is_array(), "fanouts must be an array");
  std::vector<std::int64_t> fanouts; for (const auto& value : args.at("fanouts").as_array()) { work.tick(); fanouts.push_back(fanout(value)); }
  const bool replacement = boolean(args,"replacement",false);
  const auto model = args.contains("sampling_model") ? string(args.at("sampling_model"),"sampling_model") : "uniform";
  require(model == "uniform" || model == "weighted", "Unknown sampling_model"); const bool weighted = model == "weighted";
  const bool typed = args.contains("edge_type_fanouts") && !args.at("edge_type_fanouts").is_null();
  std::map<std::string,std::vector<std::int64_t>> overrides;
  if (typed) for (const auto& entry : object(args.at("edge_type_fanouts"),"edge_type_fanouts")) {
    require(!entry.key().empty() && entry.value().is_array() && entry.value().as_array().size() == fanouts.size(), "Typed fanouts require a nonempty type and one fanout per hop");
    auto& values = overrides[std::string(entry.key())]; for (const auto& value : entry.value().as_array()) { work.tick(); values.push_back(fanout(value)); }
  }
  const auto cutoff = args.contains("time_cutoff") && !args.at("time_cutoff").is_null() ? std::optional<Exact>(exact_number(args.at("time_cutoff"),"time_cutoff")) : std::nullopt;
  NativeRandom rng(args); work.tick(graph.vertex_count()); std::vector<std::vector<Neighbor>> adj(graph.vertex_count());
  for (std::size_t i = 0; i < graph.edge_count(); ++i) {
    work.tick(); const auto& edge = graph.canonical().edges[i]; require(!typed || (edge.type && !edge.type->empty()), "Typed sampling requires every edge to have a nonempty type");
    const Exact weight = weighted ? Exact(edge.weight.value_or(1)) : Exact(1); require(weight >= 0, "Sampling weights must be nonnegative");
    if (cutoff && timestamp_seconds(edge.timestamp,work) > *cutoff) continue;
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target); adj[u].push_back({v,i,weight}); if (!graph.directed() && u != v) adj[v].push_back({u,i,weight});
  }
  require(backend == "cpp", "GPU neighborhood sampling adapter is not available");
  std::vector<bool> selected(graph.vertex_count(),false); for (const auto v : seeds) selected[v] = true;
  json::array rows;
  for (std::size_t batch = 0; batch < seeds.size(); ++batch) {
    std::vector<VertexIndex> frontier{seeds[batch]};
    for (std::size_t hop = 0; hop < fanouts.size(); ++hop) {
      std::set<VertexIndex> following;
      for (const auto u : frontier) {
        std::map<std::string,std::vector<Neighbor>> grouped;
        for (const auto& neighbor : adj[u]) { work.tick(); grouped[typed ? *graph.canonical().edges[neighbor.edge].type : ""].push_back(neighbor); }
        for (const auto& [kind,candidates] : grouped) {
          const auto count = overrides.count(kind) ? overrides.at(kind)[hop] : fanouts[hop]; std::vector<std::size_t> chosen;
          if (count == -1) { chosen.resize(candidates.size()); std::iota(chosen.begin(),chosen.end(),0); }
          else {
            std::vector<Exact> weights; std::vector<std::size_t> eligible;
            for (std::size_t i = 0; i < candidates.size(); ++i) { work.tick(); weights.push_back(candidates[i].weight); if (!weighted || candidates[i].weight > 0) eligible.push_back(i); }
            const auto size = eligible.empty() ? 0 : replacement ? static_cast<std::uint64_t>(count) : std::min<std::uint64_t>(count,eligible.size());
            work.tick(size); work.output(rows.size()+size);
            for (std::size_t j = 0; j < size; ++j) {
              if (weighted) { const auto index = rng.weighted(weights,work); if (!index) throw Failure("correctness_mismatch", "Weighted sampler exhausted eligible mass"); chosen.push_back(*index); if (!replacement) weights[*index] = 0; }
              else { const auto offset = rng.uniform(eligible.size(),work); chosen.push_back(eligible[offset]); if (!replacement) { eligible[offset] = eligible.back(); eligible.pop_back(); } }
            }
          }
          for (const auto i : chosen) {
            work.tick(); const auto& neighbor = candidates[i]; const auto& edge = graph.canonical().edges[neighbor.edge];
            rows.push_back(json::object{{"edge_id",id_json(edge.id)},{"source",id_json(graph.external_id(u))},{"target",id_json(graph.external_id(neighbor.vertex))},
                                       {"hop",hop+1},{"batch",batch},{"seed",id_json(graph.external_id(seeds[batch]))}});
            selected[neighbor.vertex] = true; following.insert(neighbor.vertex); work.output(rows.size());
          }
        }
      }
      frontier.assign(following.begin(),following.end());
    }
  }
  json::array vertices; for (VertexIndex v = 0; v < selected.size(); ++v) if (selected[v]) vertices.push_back(id_json(graph.external_id(v)));
  work.output(rows.size()+vertices.size()); auto vertex_port = result_port("vertex_set",vertices); vertex_port["scope"] = "requested_random_sample";
  return {{"parameters",{{"seeds",external_ids(graph,seeds)},{"fanouts",args.at("fanouts")},{"replacement",replacement},{"sampling_model",model},
                         {"edge_type_fanouts",typed?args.at("edge_type_fanouts"):json::value(nullptr)},{"time_cutoff",cutoff?display_number(*cutoff):json::value(nullptr)},{"random_seed",rng.seed}}},
          {"result",{{"sampled_edges",rows},{"sampled_vertices",vertices}}},{"ports",{{"edges",result_port("edge_sample",rows)},{"vertices",vertex_port}}},{"complete",true},{"quality","stochastic"},
          {"diagnostics",{{"random_seed",rng.seed},{"generator","mt19937_64 with integer rejection sampling"},{"probability_arithmetic","exact rational weights"},
                          {"sample_unit","edge_instance"},{"frontier_multiplicity","distinct vertices per hop and seed batch"},{"all_neighbors_includes_zero_weight_edges",true},
                          {"time_convention","integer epoch seconds or timezone-aware RFC 3339; exact fractional comparison; leap seconds rejected"}}}};
}
}  // namespace graphmine::runtime
