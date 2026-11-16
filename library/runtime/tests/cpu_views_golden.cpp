#include "legacy_normalizers.hpp"
#include "../view_profiles.hpp"
#include "../family_util.hpp"
#include "../record_query.hpp"
#include "../force_layout.hpp"
#include "../structure_input.hpp"
#include "../influence_input.hpp"
#include "../steiner_input.hpp"
#include "../walk_input.hpp"
#include "../edge_set_input.hpp"
#include "../filtration_input.hpp"
#include "../signed_input.hpp"
#include "../matching_input.hpp"
#include "../vertex_records_input.hpp"
#include "../path_input.hpp"
#include "../graph_output_view.hpp"
#include "../enumeration_input.hpp"
#include "../learning.hpp"
#include "../feature_input.hpp"
#include "../hypergraph_input.hpp"
#include "../dynamic_input.hpp"
#include "../embedding_input.hpp"
#include "../sparsification_input.hpp"
#include "../flow_input.hpp"
#include "../anomaly_input.hpp"
#include "graphmine/runtime.hpp"
#include <cstring>
#include <iostream>

namespace gm = graphmine;
namespace rt = graphmine::runtime;
rt::Work unlimited() {
  rt::Work work;
  work.max_candidates = work.max_output_items = UINT64_MAX;
  work.timeout_seconds = std::numeric_limits<double>::infinity();
  return work;
}
void clear_views() {
  const auto response = rt::strict_json(rt::request(R"({"command":"representation_cache","action":"clear"})")).as_object();
  if (response.contains("error")) throw std::runtime_error(rt::json::serialize(response));
}
void cache_pass(const rt::Work& work, int repeat, std::size_t position = 0) {
  const auto& used = work.representations.at(position).as_object();
  if (!used.at("retained").as_bool() || used.at("hit").as_bool() != (repeat != 0))
    throw std::runtime_error("Golden did not exercise a fresh build followed by a cache hit");
}
template<class T> void equal(const std::vector<T>& a, const std::vector<T>& b) {
  if (a.size() != b.size() || (!a.empty() && std::memcmp(a.data(), b.data(), a.size()*sizeof(T))))
    throw std::runtime_error("CPU view array bytes differ");
}
void traversal(const gm::Graph& graph, const char* id = "breadth-first-search:cpp:default",
               const char* simrank_direction = nullptr) {
  const auto& profile = rt::cpu_view_profile(id);
  auto old_work = unlimited();
  const auto expected = simrank_direction
    ? gm::legacy_test::simrank(graph,std::string(simrank_direction)=="undirected_projection",old_work)
    : gm::legacy_test::adjacency(graph, old_work);
  clear_views();
  std::vector<std::uint64_t> offsets{0}; std::vector<gm::VertexIndex> indices;
  for (const auto& row : expected) {
    indices.insert(indices.end(), row.begin(), row.end()); offsets.push_back(indices.size());
  }
  for (int repeat = 0; repeat < 2; ++repeat) {
    auto work = unlimited();
    const auto input = rt::consume_view(graph, profile, work, rt::ViewBudget::original_edges);
    cache_pass(work,repeat);
    const auto& view = std::get<gm::CsrView>(input->view);
    equal(offsets, view.offsets); equal(indices, view.indices);
    const auto repacked = rt::adjacency_layout(view);
    if (repacked.size() != expected.size()) throw std::runtime_error("CPU row layout size differs");
    for (std::size_t v=0; v<repacked.size(); ++v) equal(expected[v],repacked[v]);
    if (view.in_offsets) {
      rt::MiningGraph reverse(expected.size()), old_weak=expected, new_weak=repacked;
      for (gm::VertexIndex u=0; u<expected.size(); ++u)
        for (const auto v : expected[u]) {
          reverse[v].push_back(u);
          if (graph.directed()) old_weak[v].push_back(u);
        }
      std::vector<std::uint64_t> incoming_offsets{0}; std::vector<gm::VertexIndex> incoming_indices;
      for (gm::VertexIndex v=0; v<expected.size(); ++v) {
        const auto row = rt::CsrRows{view,true}[v];
        incoming_indices.insert(incoming_indices.end(),reverse[v].begin(),reverse[v].end());
        incoming_offsets.push_back(incoming_indices.size());
        if (graph.directed()) new_weak[v].insert(new_weak[v].end(),row.begin(),row.end());
        equal(old_weak[v],new_weak[v]);
      }
      equal(incoming_offsets,*view.in_offsets); equal(incoming_indices,*view.in_indices);
    }
    if (work.candidates != old_work.candidates) throw std::runtime_error("CPU view candidate cost differs");
  }
}
const char* clique_profiles[] = {
  "maximal-cliques:cpp:default", "maximum-clique:cpp:default", "k-cliques:cpp:default",
  "k-core:cpp:default", "maximum-independent-set:cpp:default", "minimum-vertex-cover:cpp:default"
};
const char* reachability_profiles[] = {"transitive-closure:cpp:default", "overlapping-communities:cpp:default"};
const char* density_profiles[] = {"densest-subgraph:cpp:clique_terms", "quasi-cliques:cpp:default"};
const char* coloring_profiles[] = {"maximal-independent-set:cpp:default", "vertex-coloring:cpp:default"};
const char* pattern_profiles[] = {"triangle-counting:cpp:default", "graphlet-counting:cpp:default",
                                 "motif-counting:cpp:input", "motif-counting:cpp:motif"};
const char* record_profiles[] = {"node-lookup:cpp:records", "edge-filter:cpp:records", "neighbors:cpp:records",
  "common-neighbors:cpp:records", "query-paths:cpp:records", "graph-aggregate:cpp:records", "query-subgraph:cpp:records"};
bool record_index(const gm::Graph& graph, const char* profile, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<gm::legacy_test::RecordIndex> expected;
  std::string old_failure;
  try { expected.emplace(graph,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::record_query::Index> actual;
    std::string new_failure;
    try { actual.emplace(graph,rt::cpu_view_profile(profile),work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error(std::string(profile)+": record index rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->vertices.size() != actual->vertices.size() || expected->edges.size() != actual->edges.size() ||
        expected->outgoing.size() != actual->outgoing.size() || expected->incoming.size() != actual->incoming.size() ||
        expected->endpoints.size() != actual->endpoints.size() || expected->edge_indices != actual->edge_indices ||
        old_work.candidates != work.candidates) throw std::runtime_error("Record index size, ID map or cost differs");
    for (std::size_t v=0; v<expected->vertices.size(); ++v) {
      if (rt::json::serialize(expected->vertices[v]) != rt::json::serialize(actual->vertices[v]))
        throw std::runtime_error("Vertex record bytes differ");
      equal(expected->outgoing[v],actual->outgoing[v]); equal(expected->incoming[v],actual->incoming[v]);
    }
    std::vector<gm::VertexIndex> old_endpoints, new_endpoints;
    for (std::size_t e=0; e<expected->edges.size(); ++e) {
      if (rt::json::serialize(expected->edges[e]) != rt::json::serialize(actual->edges[e]))
        throw std::runtime_error("Edge record bytes differ");
      old_endpoints.insert(old_endpoints.end(),{expected->endpoints[e].first,expected->endpoints[e].second});
      new_endpoints.insert(new_endpoints.end(),{actual->endpoints[e].first,actual->endpoints[e].second});
    }
    equal(old_endpoints,new_endpoints);
  }
  return !expected;
}
template<class Edges> std::string exact_edge_bytes(const Edges& edges) {
  rt::json::array result;
  for (const auto& edge : edges) result.push_back(rt::json::array{edge.u,edge.v,rt::fraction_json(edge.weight),edge.original});
  return rt::json::serialize(result);
}
bool anomaly_input(const gm::Graph& graph, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<gm::legacy_test::AnomalyInput> expected;
  std::string old_failure;
  try { expected.emplace(graph,old_work); } catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::AnomalyInput> actual;
    std::string new_failure;
    try { actual = rt::anomaly_input(graph,work); } catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Anomaly input rejection differs");
    if (!expected) continue;
    for (std::size_t i=0; i<4; ++i) cache_pass(work,repeat,i);
    if (exact_edge_bytes(expected->simple) != exact_edge_bytes(actual->simple) ||
        exact_edge_bytes(expected->weighted) != exact_edge_bytes(actual->weighted) ||
        exact_edge_bytes(expected->records) != exact_edge_bytes(actual->records) ||
        expected->neighbors.size() != actual->adjacency.size() || old_work.candidates != work.candidates)
      throw std::runtime_error("Anomaly exact edges/records/cost differ");
    for (std::size_t v=0; v<expected->neighbors.size(); ++v) equal(expected->neighbors[v],actual->adjacency[v]);
  }
  return !expected;
}
bool anomaly_records(const gm::Graph& graph, bool vertices, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<std::vector<rt::json::object>> expected;
  std::string old_failure;
  try { expected = gm::legacy_test::anomaly_records(graph,vertices,old_work); } catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<std::vector<rt::json::object>> actual;
    std::string new_failure;
    try { actual = rt::anomaly_records(graph,vertices,work); } catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Anomaly population rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->size() != actual->size() || old_work.candidates != work.candidates) throw std::runtime_error("Anomaly population shape/cost differs");
    for (std::size_t i=0; i<expected->size(); ++i)
      if (rt::json::serialize(expected->at(i)) != rt::json::serialize(actual->at(i))) throw std::runtime_error("Anomaly population record bytes differ");
  }
  return !expected;
}
template<class Input> rt::json::value flow_bytes(const Input& input) {
  rt::json::array arcs,loops;
  for (const auto& [ends,arc] : input.arcs) {
    rt::json::array originals;
    for (const auto& edge : arc.originals) originals.push_back(rt::json::array{edge.edge,rt::fraction_json(edge.capacity)});
    arcs.push_back(rt::json::array{ends.first,ends.second,rt::fraction_json(arc.capacity),originals,arc.position});
  }
  for (const auto& loop : input.loops) loops.push_back(rt::json::array{loop.edge,loop.vertex,rt::fraction_json(loop.capacity)});
  return rt::json::array{arcs,loops,rt::fraction_json(input.capacity_sum)};
}
bool flow_input(const gm::Graph& graph, bool unit, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<gm::legacy_test::FlowInput> expected;
  std::string old_failure;
  try { expected.emplace(graph,unit,old_work); } catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::FlowInput> actual;
    std::string new_failure;
    try { actual = rt::flow_input(graph,unit,work); } catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Flow input rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat,0); cache_pass(work,repeat,1);
    if (rt::json::serialize(flow_bytes(*expected)) != rt::json::serialize(flow_bytes(*actual)) || old_work.candidates != work.candidates)
      throw std::runtime_error("Flow exact capacity/contributor/loop bytes or cost differ");
  }
  return !expected;
}
bool sparsification_input(const gm::Graph& graph, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<gm::legacy_test::SparsificationInput> expected;
  std::string old_failure;
  try { expected.emplace(graph,old_work); } catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::SparsificationInput> actual;
    std::string new_failure;
    try { actual = rt::sparsification_input(graph,work); } catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Sparsification input rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->edges.size() != actual->edges.size() || expected->adjacency.size() != actual->adjacency.size() ||
        old_work.candidates != work.candidates) throw std::runtime_error("Sparsification input shape/cost differs");
    std::vector<gm::VertexIndex> old_ends,new_ends; std::vector<double> old_weights,new_weights;
    std::vector<std::size_t> old_ids,new_ids;
    for (const auto& edge : expected->edges) { old_ends.insert(old_ends.end(),{edge.u,edge.v}); old_weights.push_back(edge.weight); old_ids.push_back(edge.original); }
    for (const auto& edge : actual->edges) { new_ends.insert(new_ends.end(),{edge.u,edge.v}); new_weights.push_back(edge.weight); new_ids.push_back(edge.original); }
    equal(old_ends,new_ends); equal(old_weights,new_weights); equal(old_ids,new_ids);
    for (std::size_t v=0; v<expected->adjacency.size(); ++v) equal(expected->adjacency[v],actual->adjacency[v]);
  }
  return !expected;
}
gm::Graph corpus_sparsification(const gm::Graph& graph) {
  auto data = graph.canonical(); data.graph.directed = false; data.edges.clear();
  std::set<std::pair<gm::VertexIndex,gm::VertexIndex>> seen;
  for (auto edge : graph.canonical().edges) {
    const auto u=graph.dense_index(edge.source),v=graph.dense_index(edge.target);
    if (u==v || !seen.emplace(std::minmax(u,v)).second) continue;
    edge.weight = data.edges.size()%4==0 ? 0.0 : data.edges.size()%4==1 ? 1.0/11.0 : 0.5;
    edge.original_weight.reset(); data.edges.push_back(std::move(edge));
  }
  return gm::Graph(std::move(data));
}
bool embedding_input(const gm::Graph& graph, const std::string& loops, const std::string& direction, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<rt::WalkAdjacency> expected;
  std::string old_failure;
  try { expected = gm::legacy_test::embedding_adjacency(graph,loops,direction,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::WalkAdjacency> actual;
    std::string new_failure;
    try { actual = rt::embedding_adjacency(graph,loops,direction,work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Embedding adjacency rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->size() != actual->size() || old_work.candidates != work.candidates)
      throw std::runtime_error("Embedding adjacency shape/cost differs");
    for (std::size_t u=0; u<expected->size(); ++u) {
      rt::json::array old_values,new_values; std::vector<gm::VertexIndex> old_neighbors,new_neighbors;
      for (const auto& [v,w] : expected->at(u)) { old_neighbors.push_back(v); old_values.push_back(rt::fraction_json(w)); }
      for (const auto& [v,w] : actual->at(u)) { new_neighbors.push_back(v); new_values.push_back(rt::fraction_json(w)); }
      equal(old_neighbors,new_neighbors);
      if (rt::json::serialize(old_values) != rt::json::serialize(new_values)) throw std::runtime_error("Embedding exact adjacency bytes differ");
    }
  }
  return !expected;
}
bool knowledge_input(const gm::Graph& graph, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<gm::legacy_test::KnowledgeInput> expected;
  std::string old_failure;
  try { expected.emplace(graph,old_work); } catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::KnowledgeInput> actual;
    std::string new_failure;
    try { actual = rt::knowledge_input(graph,work); } catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Knowledge record rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    equal(expected->sources,actual->sources); equal(expected->targets,actual->targets);
    if (expected->edge_indices != actual->edge_indices || expected->relations != actual->relations || old_work.candidates != work.candidates)
      throw std::runtime_error("Knowledge record IDs/labels/cost differ");
  }
  return !expected;
}
rt::json::value corpus_knowledge(rt::json::value graph) {
  graph.as_object().at("graph").as_object()["directed"] = true;
  std::size_t i=0;
  for (auto& edge : graph.as_object().at("edges").as_array()) {
    edge.as_object()["type"] = "relation_"+std::to_string(i%3); ++i;
  }
  return graph;
}
bool dynamic_input(const gm::Graph& graph, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<std::set<std::pair<gm::ExternalId,gm::ExternalId>>> expected;
  std::string old_failure;
  try { expected = gm::legacy_test::dynamic_triangle_edges(graph,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<std::set<std::pair<gm::ExternalId,gm::ExternalId>>> actual;
    std::string new_failure;
    try { actual = rt::dynamic_triangle_edges(graph,work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Dynamic triangle input rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    rt::json::array old_pairs,new_pairs;
    for (const auto& [u,v] : *expected) old_pairs.push_back(rt::json::array{rt::id_json(u),rt::id_json(v)});
    for (const auto& [u,v] : *actual) new_pairs.push_back(rt::json::array{rt::id_json(u),rt::id_json(v)});
    if (rt::json::serialize(old_pairs) != rt::json::serialize(new_pairs) || old_work.candidates != work.candidates)
      throw std::runtime_error("Dynamic triangle typed endpoint bytes/cost differ");
  }
  return !expected;
}
bool hypergraph_input(const rt::json::value& input, const char* profile, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<gm::legacy_test::HypergraphInput> expected;
  std::string old_failure;
  try { expected.emplace(input,old_work); } catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::HypergraphInput> actual;
    std::string new_failure;
    try { actual = rt::hypergraph_view_input(input,rt::cpu_view_profile(profile),work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Hypergraph incidence rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->ids != actual->ids || expected->indices != actual->indices || expected->weights.size() != actual->weights.size() ||
        expected->edges.size() != actual->edges.size() || rt::json::serialize(expected->vertex_records) != rt::json::serialize(actual->vertex_records) ||
        old_work.candidates != work.candidates) throw std::runtime_error("Hypergraph maps/attributes/cost differ");
    auto compare_weight = [](const rt::Exact& a,const rt::Exact& b) {
      if (rt::json::serialize(rt::fraction_json(a)) != rt::json::serialize(rt::fraction_json(b)))
        throw std::runtime_error("Hypergraph exact weight bytes differ");
    };
    for (std::size_t v=0; v<expected->weights.size(); ++v) compare_weight(expected->weights[v],actual->weights[v]);
    for (std::size_t e=0; e<expected->edges.size(); ++e) {
      if (expected->edges[e].id != actual->edges[e].id) throw std::runtime_error("Hyperedge identity differs");
      equal(expected->edges[e].vertices,actual->edges[e].vertices);
      compare_weight(expected->edges[e].weight,actual->edges[e].weight);
    }
  }
  return !expected;
}
rt::json::object corpus_hypergraph(const gm::Graph& graph) {
  rt::json::array vertices,edges;
  for (gm::VertexIndex v=0; v<graph.vertex_count(); ++v)
    vertices.push_back(rt::json::object{{"id",rt::id_json(graph.external_id(v))},{"weight",v%5+0.25}});
  for (const auto& edge : graph.canonical().edges) {
    rt::json::array members{rt::id_json(edge.source)};
    if (edge.source != edge.target) members.push_back(rt::id_json(edge.target));
    edges.push_back(rt::json::object{{"id",edges.size()},{"vertices",members},{"weight",std::abs(edge.weight.value_or(1))}});
  }
  if (graph.vertex_count() >= 3)
    edges.push_back(rt::json::object{{"id",edges.size()},
      {"vertices",{rt::id_json(graph.external_id(2)),rt::id_json(graph.external_id(0)),rt::id_json(graph.external_id(1))}},
      {"weight",1.0/11.0}});
  return {{"graph",{{"id",graph.canonical().graph.id}}},{"vertices",vertices},{"hyperedges",edges}};
}
bool feature_input(const rt::json::value& input, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<gm::legacy_test::FeatureInput> expected;
  std::string old_failure;
  try { expected.emplace(input,old_work); } catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::FeatureInput> actual;
    std::string new_failure;
    try { actual = rt::feature_view_input(input,rt::cpu_view_profile("knn-graph:cpp:features"),work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Feature matrix rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->ids != actual->ids || expected->indices != actual->indices || expected->dataset_id != actual->dataset_id ||
        expected->vectors.rows != actual->vectors.rows || expected->vectors.cols != actual->vectors.cols ||
        old_work.candidates != work.candidates) throw std::runtime_error("Feature matrix map/shape/cost differs");
    equal(expected->vectors.values,actual->vectors.values);
  }
  return !expected;
}
rt::json::object corpus_features(const gm::Graph& graph) {
  rt::json::array rows;
  std::vector<std::uint64_t> degrees(graph.vertex_count());
  for (const auto& edge : graph.canonical().edges) { ++degrees[graph.dense_index(edge.source)]; ++degrees[graph.dense_index(edge.target)]; }
  for (gm::VertexIndex v=0; v<graph.vertex_count(); ++v)
    rows.push_back(rt::json::object{{"id",rt::id_json(graph.external_id(v))},
      {"values",{static_cast<double>(v%5)-2.0,0.25*degrees[v],v==0 ? -0.0 : 1.0/(v+1.0)}}});
  return {{"dataset_id",graph.canonical().graph.id},{"dimension",3},{"vectors",rows}};
}
bool graph_learning_input(const rt::json::value& input, const std::string& direction, std::uint64_t budget = UINT64_MAX) {
  const bool structural = direction == "structural_features";
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::vector<rt::MiningGraph> neighbors;
  std::vector<rt::numeric::Matrix> features;
  std::vector<gm::Graph> graphs;
  std::string old_failure;
  try {
    graphs = rt::graph_collection(input,old_work);
    for (const auto& graph : graphs) {
      if (structural) features.push_back(gm::legacy_test::structural_features(graph,old_work));
      else neighbors.push_back(gm::legacy_test::propagation_neighbors(graph,direction,old_work));
    }
  } catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::shared_ptr<const gm::ViewResult> actual;
    std::vector<rt::numeric::Matrix> actual_features;
    std::string new_failure;
    try {
      const auto parsed = rt::graph_collection(input,work);
      actual = structural ? rt::learning::graph_structural_view(input,work) :
                            rt::learning::graph_propagation_view(input,direction,work);
      const auto& collection = std::get<gm::CollectionView>(actual->view);
      for (std::size_t m=0; m<parsed.size(); ++m) {
        if (structural) actual_features.push_back(rt::learning::structural_features(collection.members[m],parsed[m].edge_count(),work));
        else work.tick(parsed[m].edge_count());
      }
    } catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Collection learning rejection differs");
    if (!old_failure.empty()) continue;
    cache_pass(work,repeat);
    const auto& collection = std::get<gm::CollectionView>(actual->view);
    if (collection.members.size() != graphs.size() || collection.member_indices.size() != graphs.size() ||
        collection.member_ids.size() != graphs.size() || work.candidates != old_work.candidates)
      throw std::runtime_error("Collection learning members/cost differ");
    for (std::size_t m=0; m<graphs.size(); ++m) {
      const auto& view = collection.members[m]; const auto& graph = graphs[m];
      if (collection.member_indices[m] != m || collection.member_ids[m] != graph.canonical().graph.id)
        throw std::runtime_error("Collection learning member identity differs");
      for (gm::VertexIndex v=0; v<graph.vertex_count(); ++v)
        if (view.vertices.to_original[v] != v || view.vertices.external_ids[v] != graph.external_id(v))
          throw std::runtime_error("Collection learning vertex map differs");
      if (structural) { equal(features[m].values,actual_features[m].values); continue; }
      std::vector<std::uint64_t> offsets{0}; std::vector<gm::VertexIndex> indices;
      for (const auto& row : neighbors[m]) { indices.insert(indices.end(),row.begin(),row.end()); offsets.push_back(indices.size()); }
      equal(offsets,view.offsets); equal(indices,view.indices);
      if (budget == UINT64_MAX) {
        auto previous_work = unlimited(), next_work = unlimited();
        rt::numeric::Matrix values(graph.vertex_count(),2,previous_work);
        for (std::size_t v=0; v<values.rows; ++v) { values(v,0)=v%3 ? 0x1p-53 : 1; values(v,1)=static_cast<double>(v%7)-3.25; }
        previous_work.candidates = 0;
        equal(gm::legacy_test::propagate(neighbors[m],values,2,previous_work).values,
              rt::learning::propagate(view,values,2,next_work).values);
        if (previous_work.candidates != next_work.candidates) throw std::runtime_error("Collection propagation cost differs");
      }
    }
  }
  return !old_failure.empty();
}
bool node_learning_input(const gm::Graph& graph, const std::string& direction, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<rt::MiningGraph> expected;
  std::string old_failure;
  try { expected = gm::legacy_test::propagation_neighbors(graph,direction,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::shared_ptr<const gm::ViewResult> actual;
    std::string new_failure;
    try { actual = rt::learning::node_propagation_view(graph,direction,work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Learning adjacency rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    const auto& view = std::get<gm::CsrView>(actual->view);
    std::vector<std::uint64_t> offsets{0}; std::vector<gm::VertexIndex> indices;
    for (const auto& row : *expected) { indices.insert(indices.end(),row.begin(),row.end()); offsets.push_back(indices.size()); }
    equal(offsets,view.offsets); equal(indices,view.indices);
    if (old_work.candidates != work.candidates) throw std::runtime_error("Learning adjacency cost differs");
    // Compare propagated binary64 features too, including mean order and rounding.
    if (budget == UINT64_MAX) {
      auto previous_work = unlimited(), next_work = unlimited();
      rt::numeric::Matrix features(graph.vertex_count(),2,previous_work);
      for (std::size_t v=0; v<features.rows; ++v) {
        features(v,0) = v%3 ? 0x1p-53 : 1.0;
        features(v,1) = static_cast<double>(v%7)-3.25;
      }
      previous_work.candidates = 0;
      const auto previous = gm::legacy_test::propagate(*expected,features,2,previous_work);
      const auto next = rt::learning::propagate(view,features,2,next_work);
      equal(previous.values,next.values);
      if (previous_work.candidates != next_work.candidates) throw std::runtime_error("Learning propagation cost differs");
    }
  }
  return !expected;
}
bool enumeration_input(const gm::Graph& graph, bool preserve, bool chronological,
                        std::optional<std::size_t> anchor = {}, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<gm::legacy_test::EnumerationInput> expected;
  std::string old_failure;
  try { expected.emplace(graph,preserve,chronological,anchor,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::EnumerationInput> actual;
    std::string new_failure;
    try { actual = rt::enumeration_input(graph,preserve,chronological,anchor,work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Enumeration input rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat,0); cache_pass(work,repeat,1);
    if (expected->adjacency.size() != actual->adjacency.size() || expected->times.size() != actual->times.size() ||
        old_work.candidates != work.candidates) throw std::runtime_error("Enumeration input size/cost differs");
    equal(expected->ends,actual->ends);
    for (std::size_t v=0; v<expected->adjacency.size(); ++v) equal(expected->adjacency[v],actual->adjacency[v]);
    for (std::size_t e=0; e<expected->times.size(); ++e)
      if (rt::json::serialize(rt::fraction_json(expected->times[e])) != rt::json::serialize(rt::fraction_json(actual->times[e])))
        throw std::runtime_error("Enumeration exact time bytes differ");
  }
  return !expected;
}
bool selected_graph_input(const gm::Graph& graph, int mask, std::uint64_t budget = UINT64_MAX,
                          std::uint64_t output_budget = UINT64_MAX) {
  std::vector<bool> selected(graph.vertex_count());
  for (std::size_t v=0; v<selected.size(); ++v) selected[v] = mask==1 || (mask==2 && v%2==0);
  auto old_work = unlimited(); old_work.max_candidates = budget; old_work.max_output_items = output_budget;
  std::optional<rt::json::object> expected;
  std::string old_failure;
  try { expected = gm::legacy_test::selected_graph(graph,selected,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget; work.max_output_items = output_budget;
    std::optional<rt::json::object> actual;
    std::string new_failure;
    try { actual = rt::selected_graph(graph,rt::cpu_view_profile("induced-subgraph:cpp:records"),selected,work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Selected graph rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (old_work.candidates != work.candidates || rt::json::serialize(*expected) != rt::json::serialize(*actual))
      throw std::runtime_error("Selected graph JSON bytes/cost differ");
  }
  return !expected;
}
bool widest_path_input(const gm::Graph& graph, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<rt::CapacityRows> expected;
  std::string old_failure;
  try { expected = gm::legacy_test::widest_path_input(graph,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::CapacityRows> actual;
    std::string new_failure;
    try { actual = rt::widest_path_input(graph,work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Widest-path input rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->size() != actual->size() || old_work.candidates != work.candidates)
      throw std::runtime_error("Widest-path input size/cost differs");
    for (std::size_t v=0; v<expected->size(); ++v) {
      std::vector<gm::VertexIndex> old_neighbors, new_neighbors; std::vector<double> old_weights, new_weights;
      for (const auto& [u,w] : expected->at(v)) { old_neighbors.push_back(u); old_weights.push_back(w); }
      for (const auto& [u,w] : actual->at(v)) { new_neighbors.push_back(u); new_weights.push_back(w); }
      equal(old_neighbors,new_neighbors); equal(old_weights,new_weights);
    }
  }
  return !expected;
}
bool critical_path_input(const gm::Graph& graph, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<gm::legacy_test::CriticalPathInput> expected;
  std::string old_failure;
  try { expected.emplace(graph,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::CriticalPathInput> actual;
    std::string new_failure;
    try { actual = rt::critical_path_input(graph,work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Critical-path input rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->adjacency.size() != actual->adjacency.size() || expected->weights.size() != actual->weights.size() ||
        old_work.candidates != work.candidates) throw std::runtime_error("Critical-path input size/cost differs");
    equal(expected->indegree,actual->indegree); equal(expected->ends,actual->ends);
    for (std::size_t v=0; v<expected->adjacency.size(); ++v) equal(expected->adjacency[v],actual->adjacency[v]);
    for (std::size_t e=0; e<expected->weights.size(); ++e)
      if (rt::json::serialize(rt::fraction_json(expected->weights[e])) != rt::json::serialize(rt::fraction_json(actual->weights[e])))
        throw std::runtime_error("Critical-path exact weight bytes differ");
  }
  return !expected;
}
bool vertex_records_input(const gm::Graph& graph, const char* profile, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<std::vector<rt::json::object>> expected;
  std::string old_failure;
  try { expected = gm::legacy_test::vertex_records_input(graph,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<std::vector<rt::json::object>> actual;
    std::string new_failure;
    try { actual = rt::vertex_records_input(graph,rt::cpu_view_profile(profile),work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Vertex record rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->size() != actual->size() || old_work.candidates != work.candidates)
      throw std::runtime_error("Vertex record count/cost differs");
    for (std::size_t i=0; i<expected->size(); ++i)
      if (rt::json::serialize(expected->at(i)) != rt::json::serialize(actual->at(i)))
        throw std::runtime_error("Vertex record JSON bytes differ");
  }
  return !expected;
}
bool general_matching_input(const gm::Graph& graph, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<std::vector<gm::legacy_test::MatchingEdge>> expected;
  std::string old_failure;
  try { expected = gm::legacy_test::general_matching_edges(graph,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::MatchingEdges> actual;
    std::string new_failure;
    try { actual = rt::general_matching_edges(graph,work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("General matching rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->size() != actual->size() || old_work.candidates != work.candidates)
      throw std::runtime_error("General matching input size/cost differs");
    std::vector<gm::VertexIndex> old_endpoints, new_endpoints;
    std::vector<std::size_t> old_ids, new_ids;
    for (std::size_t i=0; i<expected->size(); ++i) {
      const auto& a = expected->at(i); const auto& b = actual->at(i);
      old_endpoints.insert(old_endpoints.end(),{a.u,a.v}); new_endpoints.insert(new_endpoints.end(),{b.u,b.v});
      old_ids.push_back(a.original); new_ids.push_back(b.original);
      if (rt::json::serialize(rt::fraction_json(a.value)) != rt::json::serialize(rt::fraction_json(b.value)))
        throw std::runtime_error("General matching exact weight bytes differ");
    }
    equal(old_endpoints,new_endpoints); equal(old_ids,new_ids);
  }
  return !expected;
}
bool signed_input(const gm::Graph& graph, bool weighted, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<std::map<std::pair<gm::VertexIndex,gm::VertexIndex>,gm::legacy_test::SignedEdge>> expected;
  std::string old_failure;
  try { expected = gm::legacy_test::signed_input(graph,weighted,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::SignedInput> actual;
    std::string new_failure;
    try { actual = rt::signed_input(graph,weighted,work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Signed input rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->size() != actual->size() || old_work.candidates != work.candidates)
      throw std::runtime_error("Signed input size/cost differs");
    auto a = expected->begin(); auto b = actual->begin();
    for (; a != expected->end(); ++a,++b) {
      equal(std::vector<gm::VertexIndex>{a->first.first,a->first.second,a->second.u,a->second.v},
            std::vector<gm::VertexIndex>{b->first.first,b->first.second,b->second.u,b->second.v});
      equal(std::vector<std::uint8_t>{a->second.negative},std::vector<std::uint8_t>{b->second.negative});
      if (rt::json::serialize(rt::fraction_json(a->second.weight)) != rt::json::serialize(rt::fraction_json(b->second.weight)))
        throw std::runtime_error("Signed exact cost bytes differ");
    }
  }
  return !expected;
}
bool filtration_input(const gm::Graph& graph, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<rt::FiltrationWeights> expected;
  std::string old_failure;
  try { expected = gm::legacy_test::filtration_input(graph,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::FiltrationWeights> actual;
    std::string new_failure;
    try { actual = rt::filtration_input(graph,work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Filtration input rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->size() != actual->size() || old_work.candidates != work.candidates)
      throw std::runtime_error("Filtration input size/cost differs");
    auto a = expected->begin(); auto b = actual->begin();
    for (; a != expected->end(); ++a,++b) {
      equal(std::vector<gm::VertexIndex>{a->first.first,a->first.second},
            std::vector<gm::VertexIndex>{b->first.first,b->first.second});
      if (rt::json::serialize(rt::fraction_json(a->second)) != rt::json::serialize(rt::fraction_json(b->second)))
        throw std::runtime_error("Filtration exact weight bytes differ");
    }
  }
  return !expected;
}
bool edge_set_input(const gm::Graph& graph, const char* profile, std::uint64_t budget = UINT64_MAX) {
  using Edges = std::set<std::pair<gm::VertexIndex,gm::VertexIndex>>;
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<Edges> expected;
  std::string old_failure;
  try { expected = gm::legacy_test::edge_set_input(graph,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<Edges> actual;
    std::string new_failure;
    try { actual = rt::edge_set_input(graph,rt::cpu_view_profile(profile),work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Edge set rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (old_work.candidates != work.candidates) throw std::runtime_error("Edge set candidate cost differs");
    std::vector<gm::VertexIndex> old_endpoints, new_endpoints;
    for (const auto& [u,v] : *expected) old_endpoints.insert(old_endpoints.end(),{u,v});
    for (const auto& [u,v] : *actual) new_endpoints.insert(new_endpoints.end(),{u,v});
    equal(old_endpoints,new_endpoints);
  }
  return !expected;
}
bool walk_input(const gm::Graph& graph, bool uniform, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<std::vector<std::map<gm::VertexIndex,rt::Exact>>> expected;
  std::string old_failure;
  try { expected = gm::legacy_test::walk_adjacency(graph,uniform,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::WalkAdjacency> actual;
    std::string new_failure;
    try { actual = rt::walk_adjacency(graph,uniform,work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Walk input rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->size() != actual->size() || old_work.candidates != work.candidates)
      throw std::runtime_error("Walk input size/cost differs");
    for (std::size_t v=0; v<expected->size(); ++v) {
      std::vector<gm::VertexIndex> old_neighbors, new_neighbors;
      std::string old_weights, new_weights;
      for (const auto& [u,w] : expected->at(v)) {
        old_neighbors.push_back(u); old_weights += rt::json::serialize(rt::fraction_json(w))+'\n';
      }
      for (const auto& [u,w] : actual->at(v)) {
        new_neighbors.push_back(u); new_weights += rt::json::serialize(rt::fraction_json(w))+'\n';
      }
      equal(old_neighbors,new_neighbors);
      if (old_weights != new_weights) throw std::runtime_error("Walk transition weight bytes differ");
    }
  }
  return !expected;
}
bool influence_input(const gm::Graph& graph, bool cascade, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<gm::legacy_test::InfluenceInput> expected;
  std::string old_failure;
  try {
    // This adapter only admits directed input, before constructing any arrays.
    rt::require(graph.directed(),"Influence maximization requires directed input");
    expected.emplace(graph,cascade,old_work);
  } catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::InfluenceInput> actual;
    std::string new_failure;
    try {
      rt::require(graph.directed(),"Influence maximization requires directed input");
      actual = rt::influence_input(graph,cascade,work);
    } catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Influence input rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->weights.size() != actual->weights.size() || expected->incoming.size() != actual->incoming.size() ||
        old_work.candidates != work.candidates) throw std::runtime_error("Influence input shape/cost differs");
    auto a = expected->weights.begin(); auto b = actual->weights.begin();
    for (; a != expected->weights.end(); ++a,++b) {
      equal(std::vector<gm::VertexIndex>{a->first.first,a->first.second},
            std::vector<gm::VertexIndex>{b->first.first,b->first.second});
      if (rt::json::serialize(rt::fraction_json(a->second)) != rt::json::serialize(rt::fraction_json(b->second)))
        throw std::runtime_error("Influence probability fraction bytes differ");
    }
    for (std::size_t v=0; v<expected->incoming.size(); ++v) {
      std::vector<gm::VertexIndex> old_neighbors, new_neighbors;
      std::string old_weights, new_weights;
      for (const auto& [u,w] : expected->incoming[v]) {
        old_neighbors.push_back(u); old_weights += rt::json::serialize(rt::fraction_json(w))+'\n';
      }
      for (const auto& [u,w] : actual->incoming[v]) {
        new_neighbors.push_back(u); new_weights += rt::json::serialize(rt::fraction_json(w))+'\n';
      }
      equal(old_neighbors,new_neighbors);
      if (old_weights != new_weights) throw std::runtime_error("Influence incoming weight bytes differ");
    }
  }
  return !expected;
}
bool structure_input(const gm::Graph& graph, const std::string& operation, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<gm::legacy_test::StructureInput> expected;
  std::string old_failure;
  try { expected.emplace(graph,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::StructureInput> actual;
    std::string new_failure;
    try { actual = rt::structure_input(graph,rt::cpu_view_profile(operation+":cpp:topology"),
        rt::cpu_view_profile(operation+":cpp:records"),work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Structure input rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat,0); cache_pass(work,repeat,1);
    if (expected->pairs.size() != actual->pairs.size() || expected->source_ids.size() != actual->source_ids.size() ||
        expected->adjacency.size() != actual->adjacency.size() || old_work.candidates != work.candidates)
      throw std::runtime_error("Structure input shape/cost differs");
    std::vector<gm::VertexIndex> old_pairs, new_pairs;
    for (std::size_t i=0; i<expected->pairs.size(); ++i) {
      old_pairs.insert(old_pairs.end(),{expected->pairs[i].first,expected->pairs[i].second});
      new_pairs.insert(new_pairs.end(),{actual->pairs[i].first,actual->pairs[i].second});
      if (rt::json::serialize(expected->source_ids[i]) != rt::json::serialize(actual->source_ids[i]))
        throw std::runtime_error("Structure source edge ID bytes differ");
    }
    equal(old_pairs,new_pairs);
    for (std::size_t v=0; v<expected->adjacency.size(); ++v) {
      std::vector<gm::VertexIndex> old_neighbors, new_neighbors;
      std::vector<std::size_t> old_indices, new_indices;
      for (const auto& [u,e] : expected->adjacency[v]) { old_neighbors.push_back(u); old_indices.push_back(e); }
      for (const auto& [u,e] : actual->adjacency[v]) { new_neighbors.push_back(u); new_indices.push_back(e); }
      equal(old_neighbors,new_neighbors); equal(old_indices,new_indices);
    }
  }
  return !expected;
}
bool pattern_records(const gm::Graph& graph, const char* profile, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<gm::legacy_test::PatternRecords> expected;
  std::string old_failure;
  try { expected.emplace(graph,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::PatternRecords> actual;
    std::string new_failure;
    try { actual.emplace(graph,work,&rt::cpu_view_profile(profile)); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure) throw std::runtime_error("Pattern bundle rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->vertices.size() != actual->vertices.size() || expected->edges.size() != actual->edges.size() ||
        expected->bundles.size() != actual->bundles.size() || old_work.candidates != work.candidates)
      throw std::runtime_error("Pattern bundle shape/cost differs");
    for (std::size_t v=0; v<expected->vertices.size(); ++v)
      if (rt::json::serialize(expected->vertices[v]) != rt::json::serialize(actual->vertices[v]))
        throw std::runtime_error("Pattern vertex record bytes differ");
    for (std::size_t e=0; e<expected->edges.size(); ++e)
      if (rt::json::serialize(expected->edges[e]) != rt::json::serialize(actual->edges[e]))
        throw std::runtime_error("Pattern edge record bytes differ");
    auto old_bundle = expected->bundles.begin(); auto new_bundle = actual->bundles.begin();
    for (; old_bundle != expected->bundles.end(); ++old_bundle,++new_bundle) {
      equal(std::vector<gm::VertexIndex>{old_bundle->first.first,old_bundle->first.second},
            std::vector<gm::VertexIndex>{new_bundle->first.first,new_bundle->first.second});
      equal(old_bundle->second,new_bundle->second);
    }
  }
  return !expected;
}
bool force_layout_input(const gm::Graph& graph, bool weighted, std::size_t dimensions,
                        std::uint64_t budget = rt::Work{}.max_candidates) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<gm::legacy_test::ForceLayoutInput> expected;
  std::string old_failure;
  try { expected = gm::legacy_test::force_layout_input(graph,weighted,dimensions,old_work); }
  catch (const std::exception& e) { old_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<rt::ForceLayoutInput> actual;
    std::string new_failure;
    try { actual = rt::force_layout_input(graph,weighted,dimensions,work); }
    catch (const std::exception& e) { new_failure = e.what(); }
    if (old_failure != new_failure)
      throw std::runtime_error("Force layout rejection differs: " + old_failure + " / " + new_failure);
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->weights.rows != actual->weights.rows || expected->weights.cols != actual->weights.cols ||
        expected->positions.rows != actual->positions.rows || expected->positions.cols != actual->positions.cols ||
        old_work.candidates != work.candidates) throw std::runtime_error("Force layout shape/cost differs");
    equal(expected->weights.values,actual->weights.values);
    equal(expected->positions.values,actual->positions.values);
  }
  return !expected;
}
struct ExactCase { const char* profile; bool weighted, nonnegative = true, loops = false, steiner = false, records = false; };
const ExactCase density_exact_cases[] = {
  {"densest-subgraph:cpp:edge_weight",true}, {"densest-subgraph:cpp:unweighted",false},
  {"densest-k-subgraph:cpp:edge_weight",true}, {"densest-k-subgraph:cpp:unweighted",false}
};
const ExactCase partition_exact_cases[] = {
  {"community-detection:cpp:edge_weight",true}, {"community-detection:cpp:unweighted",false},
  {"balanced-partitioning:cpp:edge_weight",true}, {"balanced-partitioning:cpp:unweighted",false}
};
const ExactCase spectral_exact_cases[] = {
  {"laplacian-eigenpairs:cpp:default",true}, {"graph-signal-denoising:cpp:default",true}
};
const ExactCase alignment_exact_cases[] = {
  {"network-alignment:cpp:edge_weight",true}, {"network-alignment:cpp:unweighted",false}
};
const ExactCase local_community_case{"seeded-local-community:cpp:default",true};
const ExactCase geolocation_case{"graph-geolocation:cpp:default",true};
const ExactCase condensation_case{"graph-condensation:cpp:default",true};
const ExactCase steiner_case{"group-steiner-tree:cpp:default",true,true,false,true};
const ExactCase coarsening_cases[] = {
  {"graph-coarsening:cpp:matching",true}, {"graph-coarsening:cpp:records",true,false,true,false,true}
};
bool exact_edges(const gm::Graph& graph, const ExactCase& test, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<std::vector<gm::legacy_test::ExactEdge>> expected;
  std::string expected_failure;
  try { expected = test.steiner ? gm::legacy_test::steiner_edges(graph,old_work)
    : test.records ? gm::legacy_test::exact_records(graph,old_work)
    : gm::legacy_test::exact_edges(graph,test.weighted,old_work,test.nonnegative,test.loops); }
  catch (const std::exception& e) { expected_failure = e.what(); }
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<std::vector<rt::family_util::Edge>> actual;
    std::string actual_failure;
    try { actual = test.steiner ? rt::group_steiner_edges(graph,work)
      : rt::family_util::edges(graph,rt::cpu_view_profile(test.profile),work); }
    catch (const std::exception& e) { actual_failure = e.what(); }
    if (expected_failure != actual_failure) throw std::runtime_error(std::string(test.profile)+": exact edge rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    if (expected->size() != actual->size() || work.candidates != old_work.candidates)
      throw std::runtime_error(std::string(test.profile)+": exact edge count/cost differs");
    std::vector<gm::VertexIndex> old_endpoints, new_endpoints;
    std::vector<std::size_t> old_ids, new_ids;
    for (std::size_t i=0; i<expected->size(); ++i) {
      const auto& a = expected->at(i); const auto& b = actual->at(i);
      old_endpoints.insert(old_endpoints.end(),{a.u,a.v}); new_endpoints.insert(new_endpoints.end(),{b.u,b.v});
      old_ids.push_back(a.original); new_ids.push_back(b.original);
      // Compare canonical numerator/denominator bytes, never cpp_rational object
      // storage (which contains pointers), and never a rounded display value.
      if (rt::json::serialize(rt::fraction_json(a.weight)) != rt::json::serialize(rt::fraction_json(b.weight)))
        throw std::runtime_error(std::string(test.profile)+": exact rational weight bytes differ");
    }
    equal(old_endpoints,new_endpoints); equal(old_ids,new_ids);
  }
  return !expected;
}
void declared_request(const char* id, const rt::json::value& graph, const rt::json::object& parameters) {
  const auto& profile = rt::cpu_view_profile(id);
  const rt::json::object request{{"command","run"},{"operation",profile.operations.front()},
    {"device","cpu"},{"graph",graph},{"parameters",parameters}};
  const auto response = rt::strict_json(rt::request(rt::json::serialize(request))).as_object();
  if (response.contains("error")) throw std::runtime_error(rt::json::serialize(response));
  bool consumed = false;
  for (const auto& item : response.at("representations").as_array()) {
    const auto& used = item.as_object();
    if (!used.contains("view_profile") || rt::string(used.at("view_profile"),"view_profile") != profile.id) continue;
    if (used.at("view") != rt::json::parse(profile.spec.canonical_json()))
      throw std::runtime_error(profile.id + ": consumed a different declared spec");
    consumed = true;
  }
  if (!consumed) throw std::runtime_error(profile.id + ": did not consume its declared view");
}
struct WeightedCase {
  const char* profile; const char* aggregation; bool nonnegative, unit;
  bool weighted = true;
  const char* direction = "outgoing";
  bool extra_adjacency = false;
};
const WeightedCase weighted_cases[] = {
  {"single-source-shortest-paths:cpp:default", "min", true, false},
  {"many-source-shortest-paths:cpp:edge_weight", "min", true, false},
  {"many-source-shortest-paths:cpp:unweighted", "min", true, true},
  {"spanning-tree-forest:cpp:minimum", "min", false, false},
  {"spanning-tree-forest:cpp:maximum", "max", false, false}
};
const WeightedCase connectivity_cases[] = {
  {"connected-components:cpp:weak", "collapse", false, false, false, "undirected_projection"},
  {"connected-components:cpp:strong", "collapse", false, false, false, "outgoing"}
};
const WeightedCase centrality_cases[] = {
  {"pagerank:cpp:edge_weight", "sum", true, false, true, "outgoing"},
  {"pagerank:cpp:unweighted", "sum", true, false, false, "outgoing"},
  {"personalized-pagerank:cpp:outgoing:edge_weight", "sum", true, false, true, "outgoing"},
  {"personalized-pagerank:cpp:outgoing:unweighted", "sum", true, false, false, "outgoing"},
  {"personalized-pagerank:cpp:incoming:edge_weight", "sum", true, false, true, "incoming"},
  {"personalized-pagerank:cpp:incoming:unweighted", "sum", true, false, false, "incoming"},
  {"personalized-pagerank:cpp:undirected_projection:edge_weight", "sum", true, false, true, "undirected_projection"},
  {"personalized-pagerank:cpp:undirected_projection:unweighted", "sum", true, false, false, "undirected_projection"},
  {"betweenness-centrality:cpp:edge_weight", "min", true, false, true, "outgoing"},
  {"betweenness-centrality:cpp:unweighted", "min", true, false, false, "outgoing"},
  {"degree-centrality:cpp:outgoing", "collapse", false, false, false, "outgoing"},
  {"degree-centrality:cpp:incoming", "collapse", false, false, false, "incoming"},
  {"degree-centrality:cpp:both", "collapse", false, false, false, "outgoing"},
  {"degree-centrality:cpp:undirected_projection", "collapse", false, false, false, "undirected_projection"}
};
const WeightedCase similarity_case{"link-prediction:cpp:default","collapse",false,false,false,"outgoing",true};
const WeightedCase induced_cases[] = {
  {"induced-subgraph:cpp:outgoing","collapse",false,false,false,"outgoing"},
  {"induced-subgraph:cpp:incoming","collapse",false,false,false,"incoming"},
  {"induced-subgraph:cpp:undirected_projection","collapse",false,false,false,"undirected_projection"}
};
const std::pair<const char*,const char*> simrank_cases[] = {
  {"simrank:cpp:incoming","incoming"}, {"simrank:cpp:undirected_projection","undirected_projection"}
};
bool weighted_path(const gm::Graph& graph, const WeightedCase& test) {
  auto reference_work = unlimited(); std::optional<rt::WeightedGraph> expected; std::string failure;
  try { expected = gm::legacy_test::weighted(graph, test.weighted, test.nonnegative, test.aggregation, test.direction, reference_work); }
  catch (const std::exception& e) { failure = e.what(); }
  std::optional<rt::MiningGraph> expected_adjacency;
  if (expected && test.extra_adjacency) expected_adjacency = gm::legacy_test::adjacency(graph,reference_work);
  // Frozen many-source unweighted conversion from 201b2367; validates stored
  // lengths before using unit distances, including discarded self-loops.
  if (expected && test.unit) for (auto& row : expected->rows) for (auto& arc : row) arc.weight = 1;
  clear_views();
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); std::shared_ptr<const gm::ViewResult> input; std::string actual_failure;
    try {
      input = rt::consume_view(graph, rt::cpu_view_profile(test.profile), work, rt::ViewBudget::weighted_adjacency);
      if (test.extra_adjacency) work.tick(graph.edge_count());
    }
    catch (const std::exception& e) { actual_failure = e.what(); }
    if (failure != actual_failure) throw std::runtime_error(std::string(test.profile)+": rejection differs");
    if (!expected) continue;
    cache_pass(work,repeat);
    const auto& view = std::get<gm::CsrView>(input->view);
    std::vector<std::uint64_t> offsets{0}; std::vector<gm::VertexIndex> indices; std::vector<double> weights;
    for (const auto& row : expected->rows) {
      for (const auto& arc : row) { indices.push_back(arc.target); weights.push_back(arc.weight); }
      offsets.push_back(indices.size());
    }
    equal(offsets,view.offsets); equal(indices,view.indices); equal(weights,std::get<std::vector<double>>(view.weights));
    const auto packed = rt::weighted_layout(view);
    std::vector<gm::VertexIndex> packed_indices; std::vector<double> packed_weights;
    for (const auto& row : packed.rows) for (const auto& arc : row) {
      packed_indices.push_back(arc.target); packed_weights.push_back(arc.weight);
    }
    equal(indices,packed_indices); equal(weights,packed_weights);
    if (packed.directed != expected->directed) throw std::runtime_error("Weighted row layout direction differs");
    if (expected_adjacency) {
      const auto adjacency = rt::adjacency_layout(view);
      if (adjacency.size() != expected_adjacency->size()) throw std::runtime_error("Similarity adjacency size differs");
      for (std::size_t v=0; v<adjacency.size(); ++v) equal(expected_adjacency->at(v),adjacency[v]);
    }
    if (view.in_offsets) {
      std::vector<std::vector<gm::VertexIndex>> reverse(expected->rows.size());
      for (gm::VertexIndex u=0; u<expected->rows.size(); ++u)
        for (const auto& arc : expected->rows[u]) reverse[arc.target].push_back(u);
      offsets.assign(1,0); indices.clear();
      for (const auto& row : reverse) { indices.insert(indices.end(),row.begin(),row.end()); offsets.push_back(indices.size()); }
      equal(offsets,*view.in_offsets); equal(indices,*view.in_indices);
    }
    if (view.directed != expected->directed || work.candidates != reference_work.candidates)
      throw std::runtime_error(std::string(test.profile)+": direction/candidate cost differs");
  }
  return !expected;
}
void contracts() {
  const auto raw = rt::strict_json(R"({"graph":{"id":"profile","directed":true,"allows_self_loops":true,"allows_parallel_edges":true},
    "vertices":[{"id":0},{"id":1},{"id":2}],"edges":[
      {"id":0,"source":0,"target":1,"weight":-3},
      {"id":1,"source":0,"target":1,"weight":5},
      {"id":2,"source":1,"target":2,"weight":1},
      {"id":3,"source":2,"target":2,"weight":-1}]})");
  const auto graph = rt::parse_graph(raw);
  anomaly_input(graph);
  for (std::uint64_t budget=0; budget<16; ++budget) anomaly_input(graph,budget);
  for (bool vertices : {false,true}) {
    anomaly_records(graph,vertices);
    for (std::uint64_t budget=0; budget<12; ++budget) anomaly_records(graph,vertices,budget);
  }
  for (const auto* target : {"vertex","edge","subgraph"}) {
    rt::json::array definitions;
    const std::vector<const char*> measures = std::string(target)=="vertex" ? std::vector<const char*>{"degree","strength","event_count"} :
      std::string(target)=="edge" ? std::vector<const char*>{"edge_weight","source_degree"} : std::vector<const char*>{"vertex_count","edge_count","weight_sum","density"};
    for (const auto* measure : measures) definitions.push_back(rt::json::object{{"name",measure},{"measure",measure}});
    rt::json::object parameters{{"anomaly_target",target},{"feature_definitions",definitions},
      {"normality_reference",{{"kind","population"}}},{"scoring_definition",{{"method","standardized_l2"},{"minimum_scale",1}}},{"top_k",1}};
    if (std::string(target)=="subgraph") parameters["subgraphs"] = rt::json::array{
      rt::json::object{{"id","s"},{"vertices",{0,1}}},rt::json::object{{"id","t"},{"vertices",{1,2}}}};
    for (const auto* profile : {"graph-anomalies:cpp:simple","graph-anomalies:cpp:weighted","graph-anomalies:cpp:neighbors","graph-anomalies:cpp:records"})
      declared_request(profile,raw,parameters);
  }
  for (bool directed : {false,true}) for (bool unit : {false,true}) {
    auto capacity_graph = raw; capacity_graph.as_object().at("graph").as_object()["directed"] = directed;
    flow_input(rt::parse_graph(capacity_graph),unit);
    for (std::size_t e=0; e<4; ++e) capacity_graph.as_object().at("edges").as_array()[e].as_object()["weight"] = e==2 ? 0.0 : 0.1*(e+1);
    flow_input(rt::parse_graph(capacity_graph),unit);
    for (std::uint64_t budget=0; budget<7; ++budget) flow_input(rt::parse_graph(capacity_graph),unit,budget);
    for (const auto* suffix : {"records","sum"}) {
      const std::string profile = std::string("max-flow-min-cut:cpp:")+(unit ? "unit_" : "weight_")+suffix;
      declared_request(profile.c_str(),capacity_graph,{{"source",0},{"sink",2},{"capacity_mode",unit ? "unit_capacity" : "edge_weight"},
        {"vertex_capacities",{rt::json::object{{"vertex",1},{"capacity",0.25}}}}});
    }
    capacity_graph.as_object().at("edges").as_array()[3].as_object().erase("weight");
    flow_input(rt::parse_graph(capacity_graph),unit);
  }
  const auto sparse = rt::strict_json(R"({"graph":{"id":"sparse","directed":false,"allows_self_loops":true,"allows_parallel_edges":true},
    "vertices":[{"id":0},{"id":1},{"id":2},{"id":3},{"id":4}],"edges":[
    {"id":0,"source":2,"target":0,"weight":0.5},{"id":1,"source":1,"target":0,"weight":0.1},
    {"id":2,"source":2,"target":1,"weight":0.75},{"id":3,"source":3,"target":1,"weight":-0.0},
    {"id":4,"source":3,"target":2,"weight":0.25}]})");
  sparsification_input(graph); sparsification_input(rt::parse_graph(sparse));
  for (std::uint64_t budget=0; budget<8; ++budget) sparsification_input(rt::parse_graph(sparse),budget);
  for (std::uint64_t budget : {0,1,2,4,10})
    declared_request("spectral-sparsification:cpp:positive_edges",sparse,{{"edge_budget",budget},{"random_seed",7}});
  for (int change=0; change<4; ++change) {
    auto invalid = sparse; auto& first = invalid.as_object().at("edges").as_array()[0].as_object();
    if (change==0) first["source"] = 0;
    if (change==1) first["source"] = 1;
    if (change==2) first["weight"] = -1;
    if (change==3) first.erase("weight");
    sparsification_input(rt::parse_graph(invalid));
  }
  const auto knowledge = corpus_knowledge(raw);
  knowledge_input(graph); knowledge_input(rt::parse_graph(knowledge));
  knowledge_input(rt::parse_graph(knowledge),0);
  declared_request("knowledge-graph-embedding:cpp:records",knowledge,
    {{"model","distmult"},{"dimensions",2},{"training_triples",{0,2,3}},
     {"validation_triples",{rt::json::object{{"source",0},{"type","relation_0"},{"target",2}}}},
     {"training_parameters",{{"epochs",2},{"random_seed",9}}}});
  for (const auto* loops : {"reject","drop","keep"}) for (const auto* direction : {"preserve","undirected_projection"}) {
    embedding_input(graph,loops,direction);
    auto valid = raw;
    for (std::size_t e=0; e<valid.as_object().at("edges").as_array().size(); ++e)
      valid.as_object().at("edges").as_array()[e].as_object()["weight"] = e==2 ? 0.0 : 0.1*(e+1);
    if (std::string(loops)=="reject") valid.as_object().at("edges").as_array().pop_back();
    embedding_input(rt::parse_graph(valid),loops,direction);
    for (std::uint64_t budget=0; budget<6; ++budget) embedding_input(rt::parse_graph(valid),loops,direction,budget);
    const std::string profile = std::string("node-embedding:cpp:")+direction+"_"+loops;
    for (const auto* model : {"line","deepwalk","node2vec"}) {
      rt::json::object options{{"epochs",2},{"self_loops",loops},{"direction",direction}};
      if (std::string(model)!="line") { options["walk_length"]=2; options["walks_per_vertex"]=1; options["window"]=1; }
      if (std::string(model)=="node2vec") { options["p"]=0.5; options["q"]=2; }
      declared_request(profile.c_str(),valid,{{"model",model},{"dimensions",2},{"training_parameters",options},{"random_seed",19}});
    }
  }
  auto hyper = corpus_hypergraph(graph);
  for (std::size_t v=0; v<3; ++v)
    hyper.at("vertices").as_array()[v].as_object()["attributes"] =
      rt::json::object{{"features",{1.0,static_cast<double>(v)}},{"target",static_cast<std::int64_t>(v)},
        {"split",v<2 ? "train" : "test"}};
  for (const auto* profile : {"hypergraph-partitioning:cpp:incidence","hypergraph-node-learning:cpp:incidence"}) {
    hypergraph_input(hyper,profile);
    for (std::uint64_t budget=0; budget<24; ++budget) hypergraph_input(hyper,profile,budget);
    for (int change=0; change<8; ++change) {
      auto changed = hyper;
      auto& first = changed.at("hyperedges").as_array()[0].as_object();
      if (change==0) first.at("vertices").as_array().push_back(0);
      if (change==1) first.at("vertices").as_array()[0] = "unknown";
      if (change==2) first["weight"] = -1;
      if (change==3) changed.at("vertices").as_array()[0].as_object()["weight"] = -1;
      if (change==4) first["weight"] = UINT64_MAX;
      if (change==5) changed.at("vertices").as_array()[0].as_object()["weight"] = 9007199254740993LL;
      if (change==6) changed.at("hyperedges").as_array()[1].as_object()["id"] = 0;
      if (change==7) first["vertices"] = rt::json::array{};
      hypergraph_input(changed,profile);
    }
  }
  for (const auto* objective : {"cut_net","connectivity_minus_one"})
    declared_request("hypergraph-partitioning:cpp:incidence",hyper,{{"num_parts",2},{"imbalance_tolerance",1.0},{"objective",objective}});
  for (const auto* task : {"regression","classification"})
    declared_request("hypergraph-node-learning:cpp:incidence",hyper,{{"model","hgnn-linear-v1"},{"task",task},
      {"model_parameters",{{"layers",2},{"epochs",2}}}});
  const auto features = corpus_features(graph);
  feature_input(features);
  for (std::uint64_t budget=0; budget<12; ++budget) feature_input(features,budget);
  for (const auto* distance : {"squared_euclidean","euclidean","cosine"})
    for (const auto* symmetry : {"directed","union","mutual"})
      declared_request("knn-graph:cpp:features",features,{{"k",1},{"distance",distance},{"symmetrization",symmetry}});
  for (int change=0; change<6; ++change) {
    auto invalid_features = features;
    auto& first = invalid_features.at("vectors").as_array()[0].as_object();
    if (change==0) invalid_features["dimension"] = 4;
    if (change==1) invalid_features["dimension"] = 0;
    if (change==2) first["id"] = 1;
    if (change==3) first.at("values").as_array()[0] = 9007199254740993ULL;
    if (change==4) first.at("values").as_array()[0] = "bad";
    if (change==5) invalid_features["vectors"] = rt::json::array{};
    feature_input(invalid_features);
  }
  traversal(graph);
  for (const auto& test : weighted_cases) weighted_path(graph,test);
  for (const auto& test : connectivity_cases) weighted_path(graph,test);
  traversal(graph,"topological-sort:cpp:default");
  auto undirected = raw;
  undirected.as_object().at("graph").as_object()["directed"] = false;
  dynamic_input(graph); dynamic_input(rt::parse_graph(undirected));
  for (std::uint64_t budget=0; budget<8; ++budget) dynamic_input(rt::parse_graph(undirected),budget);
  auto typed_ids = undirected;
  const rt::json::array replacement_ids{"0",-7,"a"};
  for (std::size_t v=0; v<3; ++v) typed_ids.as_object().at("vertices").as_array()[v].as_object()["id"] = replacement_ids[v];
  for (auto& edge : typed_ids.as_object().at("edges").as_array()) for (const auto* field : {"source","target"})
    edge.as_object()[field] = replacement_ids[edge.as_object().at(field).to_number<std::size_t>()];
  dynamic_input(rt::parse_graph(typed_ids));
  declared_request("dynamic-triangle-counting:cpp:topology",typed_ids,{{"updates",rt::json::array{}}});
  declared_request("dynamic-triangle-counting:cpp:topology",undirected,
    {{"updates",{rt::json::object{{"kind","insert_edge"},{"source",0},{"target",2}}}},
     {"list_changed_instances",true},{"result_limit",1}});
  auto other_graph = raw; other_graph.as_object().at("graph").as_object()["id"] = "other";
  auto empty_graph = raw; empty_graph.as_object().at("graph").as_object()["id"] = "empty";
  empty_graph.as_object()["vertices"] = rt::json::array{}; empty_graph.as_object()["edges"] = rt::json::array{};
  rt::json::object learning_collection{{"dataset_id","learning"},{"graphs",{raw,other_graph,empty_graph}}};
  for (auto& member : learning_collection.at("graphs").as_array())
    for (auto& vertex : member.as_object().at("vertices").as_array())
      vertex.as_object()["attributes"] = rt::json::object{{"features",{1.0,2.5}}};
  for (const auto* direction : {"incoming","outgoing","undirected_projection","structural_features"}) {
    graph_learning_input(learning_collection,direction);
    for (std::uint64_t budget : {0,1,8,16,24,32,40,80}) graph_learning_input(learning_collection,direction,budget);
    for (const auto* source : {"structural","attributes"}) for (const auto* readout : {"mean","sum"}) {
      if (std::string(direction)=="structural_features" && std::string(source)!="structural") continue;
      const std::string profile = std::string("graph-learning:cpp:")+direction;
      declared_request(profile.c_str(),learning_collection,{{"task","regression"},
        {"graph_labels",{{"rows",{rt::json::object{{"graph","profile"},{"value",1}},rt::json::object{{"graph","other"},{"value",2}}}}}},
        {"split",{{"train",{"profile","other"}}}},
        {"model_definition",{{"architecture","mean_graph_convolution"},{"direction",std::string(direction)=="structural_features" ? "incoming" : direction},
          {"feature_source",source},{"readout",readout},{"layers",2},{"epochs",2}}}});
    }
  }
  for (const auto* direction : {"incoming","outgoing","undirected_projection"}) {
    node_learning_input(graph,direction);
    node_learning_input(rt::parse_graph(undirected),direction);
    for (std::uint64_t budget=0; budget<8; ++budget) node_learning_input(graph,direction,budget);
    const std::string profile = std::string("node-learning:cpp:")+direction;
    for (const auto* task : {"regression","classification"})
      declared_request(profile.c_str(),raw,{{"task",task},
        {"vertex_features",{{"rows",{rt::json::object{{"vertex",0},{"value",{1.0,0.5}}},
           rt::json::object{{"vertex",1},{"value",{2.0,1.5}}},rt::json::object{{"vertex",2},{"value",{-1.0,3.0}}}}}}},
        {"training_labels",{{"rows",{rt::json::object{{"vertex",0},{"value",1}},rt::json::object{{"vertex",1},{"value",0}}}}}},
        {"split",{{"train",{0,1}}}},
        {"model_definition",{{"architecture","sgc"},{"direction",direction},{"layers",2},{"epochs",2}}}});
  }
  auto event_graph = raw;
  for (std::size_t e=0; e<event_graph.as_object().at("edges").as_array().size(); ++e)
    event_graph.as_object().at("edges").as_array()[e].as_object()["timestamp"] =
      rt::json::value(e==0 ? "2020-01-01T00:00:00.01Z" : e==1 ? "2020-01-01T01:00:00.02+01:00" :
        e==2 ? "2020-01-01T00:00:01.001Z" : "ignored invalid loop timestamp");
  for (bool preserve : {false,true}) for (bool chronological : {false,true}) {
    enumeration_input(graph,preserve,chronological);
    enumeration_input(rt::parse_graph(undirected),preserve,chronological);
    enumeration_input(rt::parse_graph(event_graph),preserve,chronological);
    for (std::size_t anchor=0; anchor<4; ++anchor)
      enumeration_input(rt::parse_graph(event_graph),preserve,chronological,anchor);
    for (std::uint64_t budget : {0,1,2,3,4,20,40,80})
      enumeration_input(rt::parse_graph(event_graph),preserve,chronological,{},budget);
    const auto* profile = preserve ? "bounded-paths-cycles:cpp:preserve" : "bounded-paths-cycles:cpp:collapse_first";
    const rt::json::object params{{"task","s_t_path"},{"source",0},{"target",2},{"max_hops",3},
      {"parallel_edge_policy",preserve ? "preserve" : "collapse_first"},{"chronological_order_required",chronological}};
    declared_request(profile,event_graph,params);
    declared_request("bounded-paths-cycles:cpp:records",event_graph,params);
    for (const auto* task : {"all_cycles","cycle_through_vertex","cycle_through_edge"}) {
      auto cycle = event_graph;
      cycle.as_object().at("edges").as_array().back().as_object()["target"] = 0;
      cycle.as_object().at("edges").as_array().back().as_object()["timestamp"] = "2020-01-01T00:00:02Z";
      rt::json::object options{{"task",task},{"max_hops",3},{"parallel_edge_policy",preserve ? "preserve" : "collapse_first"},
        {"chronological_order_required",chronological},{"result_limit",1}};
      if (std::string(task)=="cycle_through_vertex") options["source"] = 0;
      if (std::string(task)=="cycle_through_edge") options["anchor_edge"] = 0;
      declared_request(profile,cycle,options);
    }
  }
  for (const auto& test : induced_cases) {
    weighted_path(graph,test);
    declared_request(test.profile,raw,{{"mode","ego"},{"vertices_or_seeds",{1}},{"radius",2},{"direction_mode",test.direction}});
  }
  for (const auto& selected_input : {raw,undirected}) {
    for (int mask : {0,1,2}) selected_graph_input(rt::parse_graph(selected_input),mask);
    declared_request("induced-subgraph:cpp:records",selected_input,{{"mode","induced"},{"vertices_or_seeds",{0,1}}});
    declared_request("induced-subgraph:cpp:records",selected_input,{{"mode","ego"},{"vertices_or_seeds",{1}},{"radius",2}});
    declared_request("induced-subgraph:cpp:records",selected_input,{{"mode","ego"},{"vertices_or_seeds",{1}},{"radius",0}});
  }
  for (std::uint64_t budget=0; budget<20; ++budget) selected_graph_input(graph,1,budget);
  for (std::uint64_t budget=0; budget<8; ++budget) selected_graph_input(graph,1,UINT64_MAX,budget);
  auto entity_graph = raw;
  for (std::size_t v=0; v<3; ++v)
    entity_graph.as_object().at("vertices").as_array()[v].as_object()["attributes"] =
      rt::json::object{{"name",v < 2 ? "Straße" : "STRASSE"},{"amount",9007199254740993ULL+v}};
  vertex_records_input(graph,"entity-resolution:cpp:vertices");
  vertex_records_input(rt::parse_graph(entity_graph),"entity-resolution:cpp:vertices");
  for (std::uint64_t budget=0; budget<15; ++budget)
    vertex_records_input(rt::parse_graph(entity_graph),"entity-resolution:cpp:vertices",budget);
  const rt::json::object predicate{{"field","name"},{"operator","eq"},{"normalization","nfkc_casefold"}};
  const rt::json::array blocking{rt::json::object{{"id","same_name"},{"all",{predicate}}}};
  declared_request("entity-resolution:cpp:vertices",entity_graph,{{"task","blocking"},{"blocking_rules",blocking}});
  for (const auto* policy : {"connected_components","correlation_clustering"})
    declared_request("entity-resolution:cpp:vertices",entity_graph,{{"task","resolution"},{"blocking_rules",blocking},
      {"match_decision_rule",{{"all",{predicate}}}},{"clustering_policy",policy}});
  for (const auto& null_graph : {raw,undirected}) {
    edge_set_input(rt::parse_graph(null_graph),"null-model-significance:cpp:default");
    for (const auto* model : {"degree_preserving_configuration","erdos_renyi"})
      for (const auto* tail : {"greater","less","two_sided_about_null_mean"})
        declared_request("null-model-significance:cpp:default",null_graph,
          {{"null_model",model},{"statistic_definition",{{"name","density"}}},{"sample_count",3},
           {"random_seed",41},{"tail",tail},{"return_randomized_edges",true}});
  }
  for (std::uint64_t budget=0; budget<7; ++budget)
    edge_set_input(graph,"null-model-significance:cpp:default",budget);
  declared_request("null-model-significance:cpp:default",undirected,
    {{"statistic_definition",{{"name","triangles"}}},{"sample_count",3},{"random_seed",42}});
  for (const auto* operation : {"biconnected-components","k-truss"}) {
    structure_input(graph,operation);
    structure_input(rt::parse_graph(undirected),operation);
    for (std::uint64_t budget=0; budget<16; ++budget) structure_input(graph,operation,budget);
    for (const auto* suffix : {":cpp:topology",":cpp:records"}) {
      const auto profile = std::string(operation)+suffix;
      declared_request(profile.c_str(),undirected,{});
      if (std::string(operation) == "k-truss")
        declared_request(profile.c_str(),undirected,{{"requested_k",3}});
    }
  }
  for (const auto& pattern_graph : {raw,undirected}) {
    const auto parsed = rt::parse_graph(pattern_graph);
    pattern_records(parsed,"subgraph-isomorphism:cpp:bundles");
    for (std::uint64_t budget=0; budget<35; ++budget)
      pattern_records(parsed,"subgraph-isomorphism:cpp:bundles",budget);
    for (bool induced : {false,true}) {
      declared_request("subgraph-isomorphism:cpp:bundles",pattern_graph,
        {{"query_graph",pattern_graph},{"induced",induced}});
      declared_request("subgraph-isomorphism:cpp:bundles",pattern_graph,
        {{"query_graph",pattern_graph},{"induced",induced},{"result_limit",1},
         {"edge_predicates",{rt::json::object{{"field","weight"},{"operator","eq_query"}}}}});
    }
  }
  for (const auto* profile : record_profiles) {
    record_index(graph,profile);
    record_index(rt::parse_graph(undirected),profile);
    const auto& operation = rt::cpu_view_profile(profile).operations.front();
    rt::json::object parameters;
    if (operation == "neighbors") parameters["entity"] = 0;
    if (operation == "common-neighbors" || operation == "query-paths") {
      parameters["source"] = 0; parameters["target"] = 2;
    }
    if (operation == "query-subgraph") parameters["vertices"] = rt::json::array{0,1};
    declared_request(profile,raw,parameters);
    declared_request(profile,undirected,parameters);
  }
  for (std::uint64_t budget=0; budget<40; ++budget) record_index(graph,record_profiles[0],budget);
  declared_request("query-paths:cpp:records",raw,{{"source",0},{"target",2},{"mode","all_simple"}});
  declared_request("neighbors:cpp:records",raw,{{"entity",1},{"direction","both"},{"hops",2}});
  declared_request("graph-aggregate:cpp:records",raw,{{"metric","sum"},{"field","weight"},{"group_by","vertex"},{"direction","both"}});
  declared_request("query-subgraph:cpp:records",undirected,{{"mode","neighborhood"},{"entity",1},{"hops",1}});
  for (const auto* profile : clique_profiles) {
    traversal(graph,profile);
    rt::json::object parameters;
    if (std::string(profile) == "k-cliques:cpp:default") parameters["k"] = 2;
    declared_request(profile,undirected,parameters);
  }
  declared_request("maximal-cliques:cpp:default",undirected,{{"minimum_clique_size",2},{"result_limit",1}});
  declared_request("maximum-clique:cpp:default",undirected,{{"return_all_ties",true}});
  declared_request("k-cliques:cpp:default",undirected,{{"k",2},{"mode","enumerate"}});
  declared_request("k-core:cpp:default",undirected,{{"requested_k",1}});
  declared_request("minimum-vertex-cover:cpp:default",undirected,{{"mode","decision"},{"k",1}});
  for (const auto* profile : coloring_profiles) {
    traversal(graph,profile);
    declared_request(profile,undirected,{{"random_seed",42}});
  }
  declared_request("vertex-coloring:cpp:default",undirected,{{"random_seed",42},{"distance",2}});
  weighted_path(graph,similarity_case);
  for (const auto* measure : {"jaccard","common_neighbors","adamic_adar","resource_allocation",
                              "preferential_attachment","sorensen","overlap","cosine"})
    declared_request(similarity_case.profile,undirected,{{"scoring_measure",measure},{"candidate_pairs",{{0,2}}}});
  for (const auto& [profile,direction] : simrank_cases) {
    traversal(graph,profile,direction);
    declared_request(profile,raw,{{"query_mode","single_pair"},{"source_vertex",0},{"target_vertex",2},{"direction_mode",direction}});
    declared_request(profile,raw,{{"query_mode","single_source_all"},{"source_vertex",0},{"direction_mode",direction}});
    declared_request(profile,raw,{{"query_mode","top_k_pairs"},{"direction_mode",direction}});
  }
  for (const auto* profile : pattern_profiles) traversal(graph,profile);
  declared_request("triangle-counting:cpp:default",undirected,{});
  declared_request("triangle-counting:cpp:default",undirected,{{"mode","enumerate"},{"result_limit",1}});
  declared_request("graphlet-counting:cpp:default",undirected,{{"graphlet_sizes",{2,3}}});
  declared_request("graphlet-counting:cpp:default",undirected,{{"graphlet_sizes",{2,3}},
    {"include_orbit_counts",true},{"list_instances",true},{"result_limit_per_graphlet",1}});
  for (const auto* profile : {"motif-counting:cpp:input","motif-counting:cpp:motif"}) {
    declared_request(profile,raw,{{"motifs",rt::json::array{raw}}});
    declared_request(profile,undirected,{{"motifs",rt::json::array{undirected}},
      {"induced",true},{"occurrence_identity","all_embeddings"},{"list_instances",true}});
  }
  for (const auto* profile : reachability_profiles) traversal(graph,profile);
  declared_request("transitive-closure:cpp:default",raw,{});
  declared_request("transitive-closure:cpp:default",raw,{{"enumerate_closure_edges",false}});
  declared_request("transitive-closure:cpp:default",raw,{{"query_mode","single_pair"},{"query_pairs",{{0,2}}}});
  declared_request("transitive-closure:cpp:default",raw,{{"query_mode","batch_pairs"},{"query_pairs",{{0,2},{2,0}}}});
  declared_request("overlapping-communities:cpp:default",undirected,{{"k",2}});
  declared_request("overlapping-communities:cpp:default",undirected,{{"k",3},{"include_unassigned_vertices",false}});
  for (const auto* profile : density_profiles) traversal(graph,profile);
  for (const auto& test : density_exact_cases)
    for (std::uint64_t budget=0; budget<7; ++budget) exact_edges(graph,test,budget);
  for (const auto* mode : {"independent", "nearest_source"}) {
    const rt::json::object request{{"command","run"},{"operation","breadth-first-search"},
      {"device","cpu"},{"graph",raw},{"parameters",{{"sources",{0,1}},{"source_mode",mode}}}};
    const auto response = rt::strict_json(rt::request(rt::json::serialize(request))).as_object();
    if (response.contains("error")) throw std::runtime_error(rt::json::serialize(response));
    const auto& used = response.at("representations").as_array().back().as_object();
    const auto& declared = rt::cpu_view_profile("breadth-first-search:cpp:default");
    if (rt::string(used.at("view_profile"), "view_profile") != declared.id ||
        used.at("view") != rt::json::parse(declared.spec.canonical_json()))
      throw std::runtime_error("BFS consumed a view different from its declaration");
  }
  auto positive = raw;
  for (auto& edge : positive.as_object().at("edges").as_array())
    edge.as_object()["weight"] = std::abs(edge.as_object().at("weight").to_number<double>());
  for (const auto& path_graph : {raw,undirected,positive}) {
    widest_path_input(rt::parse_graph(path_graph)); critical_path_input(rt::parse_graph(path_graph));
  }
  for (std::uint64_t budget=0; budget<7; ++budget) {
    widest_path_input(graph,budget); critical_path_input(graph,budget);
  }
  declared_request("widest-paths:cpp:default",positive,{{"source_vertex",0}});
  auto path_graph = positive;
  path_graph.as_object().at("graph").as_object()["directed"] = false;
  path_graph.as_object()["edges"] = rt::json::array{
    rt::json::object{{"id",0},{"source",2},{"target",1},{"weight",0.1}},
    rt::json::object{{"id",1},{"source",0},{"target",1},{"weight",0.2}},
    rt::json::object{{"id",2},{"source",1},{"target",2},{"weight",0.3}},
    rt::json::object{{"id",3},{"source",1},{"target",0},{"weight",-0.0}}};
  widest_path_input(rt::parse_graph(path_graph));
  declared_request("widest-paths:cpp:default",path_graph,{{"source_vertex",1}});
  auto critical_graph = raw;
  critical_graph.as_object().at("edges").as_array().pop_back();
  critical_graph.as_object().at("edges").as_array().back().as_object()["weight"] = -2;
  critical_path_input(rt::parse_graph(critical_graph));
  declared_request("top-k-critical-paths:cpp:default",critical_graph,{{"k",5}});
  declared_request("top-k-critical-paths:cpp:default",critical_graph,{{"k",1},{"sources",{0,2}},{"sinks",{2}}});
  critical_graph.as_object().at("edges").as_array()[0].as_object().erase("weight");
  critical_path_input(rt::parse_graph(critical_graph)); widest_path_input(rt::parse_graph(critical_graph));
  auto signed_graph = positive;
  signed_graph.as_object().at("graph").as_object()["directed"] = false;
  for (auto& edge : signed_graph.as_object().at("edges").as_array()) edge.as_object()["type"] = "positive";
  signed_graph.as_object().at("edges").as_array()[2].as_object()["type"] = "negative";
  for (bool weighted : {false,true}) {
    const auto* profile = weighted ? "signed-balance:cpp:edge_weight" : "signed-balance:cpp:unweighted";
    signed_input(graph,weighted); signed_input(rt::parse_graph(signed_graph),weighted);
    for (std::uint64_t budget=0; budget<7; ++budget) signed_input(rt::parse_graph(signed_graph),weighted,budget);
    for (const auto* task : {"balance_check","frustration_minimization"})
      for (const auto* quality : {"exact","approximate"})
        declared_request(profile,signed_graph,{{"task",task},{"weight_mode",weighted ? "edge_weight" : "unweighted"},
          {"solution_quality",quality}});
    auto contradictory = signed_graph;
    contradictory.as_object().at("edges").as_array()[1].as_object()["type"] = "negative";
    signed_input(rt::parse_graph(contradictory),weighted);
    auto costs = signed_graph;
    costs.as_object().at("edges").as_array()[0].as_object()["weight"] = 0.1;
    costs.as_object().at("edges").as_array()[1].as_object()["weight"] = 0.2;
    signed_input(rt::parse_graph(costs),weighted);
    costs.as_object().at("edges").as_array().back().as_object()["weight"] = -1;
    signed_input(rt::parse_graph(costs),weighted);
  }
  for (bool uniform : {false,true}) {
    walk_input(graph,uniform); walk_input(rt::parse_graph(undirected),uniform);
    for (std::uint64_t budget=0; budget<10; ++budget) walk_input(graph,uniform,budget);
  }
  auto walk_graph = positive;
  walk_graph.as_object().at("edges").as_array()[0].as_object()["weight"] = 0.0;
  walk_graph.as_object().at("edges").as_array()[1].as_object()["weight"] = 0.1;
  for (bool directed : {false,true}) {
    walk_graph.as_object().at("graph").as_object()["directed"] = directed;
    for (const auto* model : {"uniform","weighted","node2vec"}) {
      const bool uniform = std::string(model) == "uniform";
      walk_input(rt::parse_graph(walk_graph),uniform);
      rt::json::object parameters{{"start_vertices",{0,1,2}},{"length",8},{"walk_model",model},{"random_seed",43}};
      if (std::string(model) == "node2vec") { parameters["p"] = 0.5; parameters["q"] = 2; }
      declared_request(uniform ? "random-walks:cpp:uniform" : "random-walks:cpp:weighted",walk_graph,parameters);
    }
  }
  auto probabilities = positive;
  for (auto& edge : probabilities.as_object().at("edges").as_array()) edge.as_object()["weight"] = 0.1;
  for (bool cascade : {false,true}) {
    const auto* profile = cascade ? "influence-maximization:cpp:independent_cascade" : "influence-maximization:cpp:linear_threshold";
    influence_input(rt::parse_graph(probabilities),cascade);
    influence_input(graph,cascade);
    influence_input(rt::parse_graph(undirected),cascade);
    for (std::uint64_t budget=0; budget<7; ++budget) influence_input(graph,cascade,budget);
    declared_request(profile,probabilities,{{"diffusion_model",cascade ? "independent_cascade" : "linear_threshold"},
      {"seed_set_size",1}});
    if (!cascade) declared_request(profile,probabilities,{{"diffusion_model","linear_threshold"},{"seed_set_size",1},
      {"vertex_thresholds",{rt::json::object{{"vertex",0},{"value",0.1}},
                            rt::json::object{{"vertex",1},{"value",0.2}},
                            rt::json::object{{"vertex",2},{"value",0.3}}}}});
    for (const rt::json::value value : {rt::json::value(0),rt::json::value(1),rt::json::value(-0.1),rt::json::value(1.1),rt::json::value(nullptr)}) {
      auto boundary = probabilities;
      auto& loop = boundary.as_object().at("edges").as_array().back().as_object();
      if (value.is_null()) loop.erase("weight"); else loop["weight"] = value;
      influence_input(rt::parse_graph(boundary),cascade);
    }
  }
  for (bool weighted : {false,true}) for (std::size_t dimensions : {2,3}) {
    force_layout_input(graph,weighted,dimensions);
    force_layout_input(rt::parse_graph(undirected),weighted,dimensions);
    const auto* profile = weighted ? "force-directed-layout:cpp:edge_weight" : "force-directed-layout:cpp:unweighted";
    declared_request(profile,positive,{{"weight_mode",weighted ? "edge_weight" : "unweighted"},
      {"dimensions",dimensions},{"iterations",2}});
  }
  // Positive zero initialization, reciprocal/parallel ordering, sequential
  // extended rounding, missing/negative loops, overflow and budget precedence.
  auto layout_input = positive;
  const auto layout_cases = std::vector<rt::json::array>{
    {-0.0,0.0}, {1.0,std::ldexp(1.0,-53)+std::ldexp(1.0,-64)}, {0.1,0.2,0.3},
    {std::numeric_limits<double>::max(),std::numeric_limits<double>::max()}};
  for (const auto& weights : layout_cases) {
    rt::json::array edges;
    for (std::size_t e=0; e<weights.size(); ++e) edges.push_back(rt::json::object{
      {"id",e},{"source",e%2},{"target",1-e%2},{"weight",weights[e]}});
    layout_input.as_object()["edges"] = edges;
    for (bool directed : {false,true}) {
      layout_input.as_object().at("graph").as_object()["directed"] = directed;
      force_layout_input(rt::parse_graph(layout_input),true,2);
    }
  }
  for (const auto* failure : {"missing_loop","missing_edge","negative_loop"}) {
    layout_input = positive;
    auto& edges = layout_input.as_object().at("edges").as_array();
    if (std::string(failure) == "negative_loop") edges.back().as_object()["weight"] = -1;
    else edges[std::string(failure)=="missing_loop" ? edges.size()-1 : 0].as_object().erase("weight");
    for (std::uint64_t budget=0; budget<25; ++budget)
      force_layout_input(rt::parse_graph(layout_input),true,2,budget);
    force_layout_input(rt::parse_graph(layout_input),false,3);
  }
  for (const auto& test : centrality_cases) {
    weighted_path(graph,test);
    const auto& profile = rt::cpu_view_profile(test.profile);
    const auto& operation = profile.operations.front();
    rt::json::object parameters;
    if (operation == "degree-centrality") {
      parameters["direction_mode"] = profile.id.substr(profile.id.rfind(':')+1);
    } else parameters["weight_mode"] = test.weighted ? "edge_weight" : "unweighted";
    if (operation == "personalized-pagerank") {
      parameters["seed_vertices"] = rt::json::array{0};
      parameters["direction_mode"] = test.direction;
      for (const auto* policy : {"redistribute_to_seeds","redistribute_uniformly","self_loop"}) {
        parameters["dangling_policy"] = policy;
        declared_request(test.profile,positive,parameters);
      }
    } else declared_request(test.profile,positive,parameters);
  }
  auto density_input = positive;
  density_input.as_object().at("graph").as_object()["directed"] = false;
  general_matching_input(graph); general_matching_input(rt::parse_graph(undirected));
  general_matching_input(rt::parse_graph(density_input));
  for (std::uint64_t budget=0; budget<7; ++budget) general_matching_input(rt::parse_graph(undirected),budget);
  for (const auto* quality : {"exact","approximate"})
    declared_request("weighted-matching:cpp:default",density_input,{{"solution_quality",quality}});
  auto matching_ties = density_input;
  auto& matching_edges = matching_ties.as_object().at("edges").as_array();
  matching_edges[0].as_object()["weight"] = 0.125;
  matching_edges[1].as_object()["weight"] = 0.125;
  general_matching_input(rt::parse_graph(matching_ties));
  matching_edges[1].as_object()["weight"] = 0.25;
  general_matching_input(rt::parse_graph(matching_ties));
  matching_edges.back().as_object().erase("weight");
  general_matching_input(rt::parse_graph(matching_ties));
  auto spectral_input = density_input;
  spectral_input.as_object().at("edges").as_array().pop_back();
  filtration_input(graph);
  filtration_input(rt::parse_graph(spectral_input));
  for (std::uint64_t budget=0; budget<7; ++budget) filtration_input(graph,budget);
  for (int prime : {2,3,5}) for (int dimension : {0,1,2})
    declared_request("persistent-homology:cpp:default",spectral_input,
      {{"field_prime",prime},{"max_homology_dimension",dimension},{"max_filtration",2}});
  auto filtration_graph = spectral_input;
  auto& filtration_edges = filtration_graph.as_object().at("edges").as_array();
  filtration_edges[0].as_object()["weight"] = 0.25;
  filtration_edges[1].as_object()["weight"] = 0.125;
  filtration_input(rt::parse_graph(filtration_graph));
  filtration_edges[0].as_object().erase("weight");
  filtration_input(rt::parse_graph(filtration_graph));
  for (const auto& test : coarsening_cases) {
    exact_edges(graph,test);
    exact_edges(rt::parse_graph(spectral_input),test);
    for (std::uint64_t budget=0; budget<7; ++budget) exact_edges(graph,test,budget);
    for (const auto* policy : {"keep","drop"})
      declared_request(test.profile,spectral_input,{{"self_loop_policy",policy}});
  }
  auto coarsening_input = spectral_input;
  for (std::size_t v=0; v<3; ++v)
    coarsening_input.as_object().at("vertices").as_array()[v].as_object()["attributes"] =
      rt::json::object{{"features",rt::json::array{static_cast<double>(v),0.1}}};
  for (const auto* policy : {"keep","drop"}) for (const auto* reduction : {"sum","mean"})
    declared_request("graph-coarsening:cpp:records",coarsening_input,
      {{"cluster_assignment",{rt::json::object{{"vertex",0},{"value",7}},rt::json::object{{"vertex",1},{"value",7}},
                              rt::json::object{{"vertex",2},{"value",9}}}},
       {"self_loop_policy",policy},{"feature_reduction",reduction}});
  exact_edges(graph,steiner_case);
  exact_edges(rt::parse_graph(spectral_input),steiner_case);
  for (std::uint64_t budget=0; budget<7; ++budget) exact_edges(graph,steiner_case,budget);
  for (const auto* quality : {"exact","approximate"})
    declared_request(steiner_case.profile,density_input,{{"groups",{{0},{2}}},
      {"required_vertices",{1}},{"solution_quality",quality}});
  auto steiner_ties = density_input;
  auto& steiner_edges = steiner_ties.as_object().at("edges").as_array();
  steiner_edges[0].as_object()["weight"] = 0.25;
  steiner_edges[1].as_object()["weight"] = 0.25;
  exact_edges(rt::parse_graph(steiner_ties),steiner_case);
  steiner_edges[1].as_object()["weight"] = 0.125;
  exact_edges(rt::parse_graph(steiner_ties),steiner_case);
  steiner_edges.back().as_object().erase("weight");
  exact_edges(rt::parse_graph(steiner_ties),steiner_case);
  exact_edges(graph,local_community_case);
  exact_edges(rt::parse_graph(spectral_input),local_community_case);
  declared_request(local_community_case.profile,spectral_input,{{"seeds",{0}}});
  declared_request(local_community_case.profile,spectral_input,{{"seeds",{0,2}},{"maximum_volume",18}});
  exact_edges(graph,geolocation_case);
  exact_edges(rt::parse_graph(spectral_input),geolocation_case);
  const rt::json::array locations{rt::json::object{{"vertex",0},{"latitude",10},{"longitude",179}},
    rt::json::object{{"vertex",2},{"latitude",10},{"longitude",-179}}};
  for (bool fixed : {false,true})
    declared_request(geolocation_case.profile,spectral_input,{{"method_family","spatial_propagation"},
      {"seed_locations",{{"rows",locations}}},{"hold_seeds_fixed",fixed},
      {"method_definition",{{"objective","seed_location_medoid_energy"}}}});
  exact_edges(graph,condensation_case);
  exact_edges(rt::parse_graph(spectral_input),condensation_case);
  auto condensation_input = spectral_input;
  for (std::size_t v=0; v<3; ++v)
    condensation_input.as_object().at("vertices").as_array()[v].as_object()["attributes"] = rt::json::object{
      {"features",rt::json::array{static_cast<double>(v)}},{"label",v%2},{"split",v<2 ? "train" : "test"}};
  declared_request(condensation_case.profile,condensation_input,
    {{"synthetic_vertex_budget",2},{"method","gradient_matching_linear_sgc_v1"},{"seed",41},
     {"method_parameters",{{"epochs",5},{"downstream_epochs",5}}}});
  for (const auto& test : spectral_exact_cases) {
    exact_edges(graph,test);
    exact_edges(rt::parse_graph(spectral_input),test);
  }
  for (const auto* laplacian : {"combinatorial","symmetric_normalized"})
    for (const auto* selection : {"smallest","largest"})
      declared_request("laplacian-eigenpairs:cpp:default",spectral_input,
        {{"num_eigenpairs",2},{"laplacian",laplacian},{"selection",selection}});
  const rt::json::array signal{rt::json::object{{"vertex",0},{"value",0}},
    rt::json::object{{"vertex",1},{"value",1}},rt::json::object{{"vertex",2},{"value",0}}};
  for (const auto* regularizer : {"laplacian_quadratic","total_variation","trend_filtering"})
    declared_request("graph-signal-denoising:cpp:default",spectral_input,
      {{"observed_signal",signal},{"regularization_strength",0.1},{"regularizer",regularizer}});
  declared_request("graph-signal-denoising:cpp:default",spectral_input,
    {{"observed_signal",signal},{"regularization_strength",0}});
  density_input.as_object().at("edges").as_array()[0].as_object()["weight"] = 1e16;
  density_input.as_object().at("edges").as_array()[1].as_object()["weight"] = 1;
  for (const auto& test : alignment_exact_cases) {
    exact_edges(graph,test);
    exact_edges(rt::parse_graph(density_input),test);
    declared_request(test.profile,density_input,
      {{"other_graph",density_input},{"weight_mode",test.weighted ? "edge_weight" : "unweighted"}});
    declared_request(test.profile,positive,
      {{"other_graph",positive},{"weight_mode",test.weighted ? "edge_weight" : "unweighted"},
       {"node_similarity_prior",{rt::json::object{{"graph_a_vertex",0},{"graph_b_vertex",0},{"value",2}}}}});
  }
  for (const auto& test : partition_exact_cases) {
    exact_edges(graph,test);
    exact_edges(rt::parse_graph(density_input),test);
    const auto& operation = rt::cpu_view_profile(test.profile).operations.front();
    if (operation == "community-detection") {
      for (const auto* objective : {"modularity","constant_potts_model"})
        for (const auto* quality : {"exact","heuristic"})
          declared_request(test.profile,density_input,{{"weight_mode",test.weighted ? "edge_weight" : "unweighted"},
            {"quality_function",objective},{"solution_quality",quality}});
    } else {
      for (const auto* objective : {"edge_cut","normalized_cut"})
        declared_request(test.profile,density_input,{{"num_parts",2},{"imbalance_tolerance",0.5},
          {"edge_weight_mode",test.weighted ? "edge_weight" : "unweighted"},{"objective",objective}});
    }
  }
  for (const auto& test : density_exact_cases) {
    exact_edges(rt::parse_graph(density_input),test);
    rt::json::object parameters{{"weight_mode",test.weighted ? "edge_weight" : "unweighted"}};
    if (std::string(test.profile).find("densest-k-") == 0) parameters["k"] = 2;
    declared_request(test.profile,density_input,parameters);
  }
  declared_request("densest-subgraph:cpp:clique_terms",density_input,{{"clique_order",3}});
  declared_request("quasi-cliques:cpp:default",density_input,{{"gamma",0.5},{"minimum_size",2}});
  density_input.as_object().at("edges").as_array()[0].as_object()["weight"] = 1e308;
  density_input.as_object().at("edges").as_array()[1].as_object()["weight"] = 1e308;
  for (const auto& test : density_exact_cases) exact_edges(rt::parse_graph(density_input),test);
  std::vector<WeightedCase> operation_cases(std::begin(weighted_cases),std::end(weighted_cases));
  operation_cases.insert(operation_cases.end(),std::begin(connectivity_cases),std::end(connectivity_cases));
  operation_cases.push_back({"topological-sort:cpp:default","collapse",false,false});
  for (const auto& test : operation_cases) {
    const auto& profile = rt::cpu_view_profile(test.profile);
    auto input = positive;
    rt::json::object parameters;
    const auto& operation = profile.operations.front();
    if (operation == "single-source-shortest-paths") parameters["source"] = 0;
    if (operation == "many-source-shortest-paths") parameters["weight_mode"] = test.unit ? "unweighted" : "edge_weight";
    if (operation == "spanning-tree-forest") {
      input.as_object().at("graph").as_object()["directed"] = false;
      parameters["objective"] = std::string(test.aggregation) == "max" ? "maximum" : "minimum";
    }
    if (operation == "connected-components")
      parameters["connectivity_mode"] = profile.id.find(":strong") != std::string::npos ? "strongly_connected" : "weakly_connected";
    if (operation == "topological-sort") input.as_object().at("edges").as_array().pop_back();
    const rt::json::object request{{"command","run"},{"operation",operation},{"device","cpu"},
                                    {"graph",input},{"parameters",parameters}};
    const auto response = rt::strict_json(rt::request(rt::json::serialize(request))).as_object();
    if (response.contains("error")) throw std::runtime_error(rt::json::serialize(response));
    const auto& used = response.at("representations").as_array().back().as_object();
    if (rt::string(used.at("view_profile"),"view_profile") != profile.id ||
        used.at("view") != rt::json::parse(profile.spec.canonical_json()))
      throw std::runtime_error("Weighted path consumed a different declared spec");
  }
  for (unsigned budget = 0; budget < 10; ++budget) {
    auto a = unlimited(), b = unlimited(); a.max_candidates = b.max_candidates = budget;
    std::string expected, actual;
    try { (void)gm::legacy_test::adjacency(graph, a); } catch (const std::exception& e) { expected=e.what(); }
    try { (void)rt::consume_view(graph, rt::cpu_view_profile("breadth-first-search:cpp:default"), b, rt::ViewBudget::original_edges); }
    catch (const std::exception& e) { actual=e.what(); }
    if (expected != actual) throw std::runtime_error("BFS view budget rejection differs");
  }
  std::cout << "CPU traversal declaration, arrays and budgets passed\n";
}
int main(int argc, char** argv) {
  try {
    // Test-only capacity lets the largest corpus view exercise a real warm hit.
    // Production's cache default is unchanged.
    const auto configured = rt::strict_json(rt::request(
      R"({"command":"representation_cache","action":"configure","max_bytes":1073741824})")).as_object();
    if (configured.contains("error")) throw std::runtime_error(rt::json::serialize(configured));
    if (argc > 1 && std::string(argv[1]) == "--self-test") { contracts(); return 0; }
    const bool weighted = argc > 1 && std::string(argv[1]) == "--weighted-paths";
    const bool connectivity = argc > 1 && std::string(argv[1]) == "--connectivity";
    const bool cliques = argc > 1 && std::string(argv[1]) == "--cliques";
    const bool reachability = argc > 1 && std::string(argv[1]) == "--reachability";
    const bool centrality = argc > 1 && std::string(argv[1]) == "--centrality";
    const bool coloring = argc > 1 && std::string(argv[1]) == "--coloring";
    const bool similarity = argc > 1 && std::string(argv[1]) == "--similarity";
    const bool patterns = argc > 1 && std::string(argv[1]) == "--patterns";
    const bool partitioning = argc > 1 && std::string(argv[1]) == "--partitioning";
    const bool spectral = argc > 1 && std::string(argv[1]) == "--spectral";
    const bool alignment = argc > 1 && std::string(argv[1]) == "--alignment";
    const bool local_community = argc > 1 && std::string(argv[1]) == "--local-community";
    const bool geolocation = argc > 1 && std::string(argv[1]) == "--geolocation";
    const bool condensation = argc > 1 && std::string(argv[1]) == "--condensation";
    const bool records = argc > 1 && std::string(argv[1]) == "--records";
    const bool layout = argc > 1 && std::string(argv[1]) == "--layout";
    const bool subgraph_matching = argc > 1 && std::string(argv[1]) == "--subgraph-matching";
    const bool structure = argc > 1 && std::string(argv[1]) == "--structure";
    const bool influence = argc > 1 && std::string(argv[1]) == "--influence";
    const bool walks = argc > 1 && std::string(argv[1]) == "--walks";
    const bool null_models = argc > 1 && std::string(argv[1]) == "--null-models";
    const bool topology = argc > 1 && std::string(argv[1]) == "--topology";
    const bool signed_balance = argc > 1 && std::string(argv[1]) == "--signed-balance";
    const bool general_matching = argc > 1 && std::string(argv[1]) == "--general-matching";
    const bool entity_resolution = argc > 1 && std::string(argv[1]) == "--entity-resolution";
    const bool path_profiles = argc > 1 && std::string(argv[1]) == "--path-profiles";
    const bool induced_subgraph = argc > 1 && std::string(argv[1]) == "--induced-subgraph";
    const bool enumeration = argc > 1 && std::string(argv[1]) == "--enumeration";
    const bool node_learning = argc > 1 && std::string(argv[1]) == "--node-learning";
    const bool graph_learning = argc > 1 && std::string(argv[1]) == "--graph-learning";
    const bool knn = argc > 1 && std::string(argv[1]) == "--knn";
    const bool hypergraphs = argc > 1 && std::string(argv[1]) == "--hypergraphs";
    const bool dynamic_triangles = argc > 1 && std::string(argv[1]) == "--dynamic-triangles";
    const bool embeddings = argc > 1 && std::string(argv[1]) == "--embeddings";
    const bool sparsification = argc > 1 && std::string(argv[1]) == "--sparsification";
    const bool flow = argc > 1 && std::string(argv[1]) == "--flow";
    const bool anomalies = argc > 1 && std::string(argv[1]) == "--anomalies";
    const bool steiner = argc > 1 && std::string(argv[1]) == "--steiner";
    const bool coarsening = argc > 1 && std::string(argv[1]) == "--coarsening";
    const bool density = argc > 1 && std::string(argv[1]) == "--density";
    std::vector<const char*> simple_profiles;
    if (cliques) simple_profiles.assign(std::begin(clique_profiles),std::end(clique_profiles));
    if (reachability) simple_profiles.assign(std::begin(reachability_profiles),std::end(reachability_profiles));
    if (density) simple_profiles.assign(std::begin(density_profiles),std::end(density_profiles));
    if (coloring) simple_profiles.assign(std::begin(coloring_profiles),std::end(coloring_profiles));
    if (patterns) simple_profiles.assign(std::begin(pattern_profiles),std::end(pattern_profiles));
    std::vector<WeightedCase> selected_weighted;
    if (weighted) selected_weighted.assign(std::begin(weighted_cases),std::end(weighted_cases));
    if (connectivity) selected_weighted.assign(std::begin(connectivity_cases),std::end(connectivity_cases));
    if (centrality) selected_weighted.assign(std::begin(centrality_cases),std::end(centrality_cases));
    if (similarity) selected_weighted.push_back(similarity_case);
    if (induced_subgraph) selected_weighted.assign(std::begin(induced_cases),std::end(induced_cases));
    std::vector<ExactCase> selected_exact;
    if (density) selected_exact.assign(std::begin(density_exact_cases),std::end(density_exact_cases));
    if (partitioning) selected_exact.assign(std::begin(partition_exact_cases),std::end(partition_exact_cases));
    if (spectral) selected_exact.assign(std::begin(spectral_exact_cases),std::end(spectral_exact_cases));
    if (alignment) selected_exact.assign(std::begin(alignment_exact_cases),std::end(alignment_exact_cases));
    if (local_community) selected_exact.push_back(local_community_case);
    if (geolocation) selected_exact.push_back(geolocation_case);
    if (condensation) selected_exact.push_back(condensation_case);
    if (steiner) selected_exact.push_back(steiner_case);
    if (coarsening) selected_exact.assign(std::begin(coarsening_cases),std::end(coarsening_cases));
    const bool custom_inputs = records || layout || subgraph_matching || structure || influence || walks || null_models || topology || signed_balance || general_matching || entity_resolution || path_profiles || induced_subgraph || enumeration || node_learning || graph_learning || knn || hypergraphs || dynamic_triangles || embeddings || sparsification || flow || anomalies;
    if (argc > 1 && selected_weighted.empty() && selected_exact.empty() && simple_profiles.empty() && !custom_inputs)
      throw std::runtime_error("Unknown CPU golden suite");
    std::string line; std::size_t count=0;
    while (std::getline(std::cin,line)) {
      const auto input=rt::strict_json(line).as_object();
      try {
        const auto graph = rt::parse_graph(input.at("graph"));
        if (anomalies) {
          const bool rejected = anomaly_input(graph);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile","graph-anomalies:cpp:simple+weighted+neighbors+records"},{"equal",true},{"rejected",rejected}}) << '\n';
          for (bool vertices : {false,true}) {
            const bool rejected = anomaly_records(graph,vertices);
            std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
              {"profile","graph-anomalies:cpp:records"},{"vertices",vertices},{"equal",true},{"rejected",rejected}}) << '\n';
          }
        }
        if (flow) for (bool unit : {false,true}) {
          const bool rejected = flow_input(graph,unit);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",unit ? "max-flow-min-cut:cpp:unit_records+unit_sum" : "max-flow-min-cut:cpp:weight_records+weight_sum"},
            {"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (sparsification) for (bool fixture : {false,true}) {
          const bool rejected = sparsification_input(fixture ? corpus_sparsification(graph) : graph);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile","spectral-sparsification:cpp:positive_edges"},{"simple_weighted_fixture",fixture},
            {"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (embeddings) {
          for (const auto* loops : {"reject","drop","keep"}) for (const auto* direction : {"preserve","undirected_projection"}) {
            const bool rejected = embedding_input(graph,loops,direction);
            std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
              {"profile",std::string("node-embedding:cpp:")+direction+"_"+loops},{"equal",true},{"rejected",rejected}}) << '\n';
          }
          for (bool labelled : {false,true}) {
            const bool rejected = knowledge_input(labelled ? rt::parse_graph(corpus_knowledge(input.at("graph"))) : graph);
            std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
              {"profile","knowledge-graph-embedding:cpp:records"},{"directed_labelled_fixture",labelled},
              {"equal",true},{"rejected",rejected}}) << '\n';
          }
        }
        if (dynamic_triangles) {
          const bool rejected = dynamic_input(graph);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile","dynamic-triangle-counting:cpp:topology"},{"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (hypergraphs) for (const auto* profile : {"hypergraph-partitioning:cpp:incidence","hypergraph-node-learning:cpp:incidence"}) {
          const bool rejected = hypergraph_input(corpus_hypergraph(graph),profile);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",profile},{"input_conversion","edge_incidence_plus_ordered_three_vertex_hyperedge"},
            {"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (knn) {
          const bool rejected = feature_input(corpus_features(graph));
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile","knn-graph:cpp:features"},{"input_conversion","vertex_order_degree_features"},
            {"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (graph_learning) for (const auto* direction : {"incoming","outgoing","undirected_projection","structural_features"}) {
          const rt::json::object collection{{"dataset_id","corpus"},{"graphs",{input.at("graph")}}};
          const bool rejected = graph_learning_input(collection,direction);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",std::string("graph-learning:cpp:")+direction},{"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (node_learning) for (const auto* direction : {"incoming","outgoing","undirected_projection"}) {
          const bool rejected = node_learning_input(graph,direction);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",std::string("node-learning:cpp:")+direction},{"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (enumeration) for (bool preserve : {false,true}) for (bool chronological : {false,true}) {
          const bool rejected = enumeration_input(graph,preserve,chronological);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",preserve ? "bounded-paths-cycles:cpp:preserve+records" : "bounded-paths-cycles:cpp:collapse_first+records"},
            {"chronological",chronological},{"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (induced_subgraph) for (int mask : {0,1,2}) {
          const bool rejected = selected_graph_input(graph,mask);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile","induced-subgraph:cpp:records"},{"selection_mask",mask},
            {"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (path_profiles) for (bool critical : {false,true}) {
          const bool rejected = critical ? critical_path_input(graph) : widest_path_input(graph);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",critical ? "top-k-critical-paths:cpp:default" : "widest-paths:cpp:default"},
            {"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (entity_resolution) {
          const auto* profile = "entity-resolution:cpp:vertices";
          const bool rejected = vertex_records_input(graph,profile);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",profile},{"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (general_matching) {
          const bool rejected = general_matching_input(graph);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile","weighted-matching:cpp:default"},{"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (signed_balance) for (bool weighted : {false,true}) {
          const bool rejected = signed_input(graph,weighted);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",weighted ? "signed-balance:cpp:edge_weight" : "signed-balance:cpp:unweighted"},
            {"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (topology) {
          const bool rejected = filtration_input(graph);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile","persistent-homology:cpp:default"},{"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (null_models) {
          const auto* profile = "null-model-significance:cpp:default";
          const bool rejected = edge_set_input(graph,profile);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",profile},{"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (walks) for (bool uniform : {false,true}) {
          const bool rejected = walk_input(graph,uniform);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",uniform ? "random-walks:cpp:uniform" : "random-walks:cpp:weighted"},
            {"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (influence) for (bool cascade : {false,true}) {
          const bool rejected = influence_input(graph,cascade);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",cascade ? "influence-maximization:cpp:independent_cascade" : "influence-maximization:cpp:linear_threshold"},
            {"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (structure) for (const auto* operation : {"biconnected-components","k-truss"}) {
          const bool rejected = structure_input(graph,operation);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",std::string(operation)+":cpp:topology+records"},{"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (subgraph_matching) {
          const auto* profile = "subgraph-isomorphism:cpp:bundles";
          const bool rejected = pattern_records(graph,profile);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",profile},{"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (layout) for (bool weighted : {false,true}) for (std::size_t dimensions : {2,3}) {
          const bool rejected = force_layout_input(graph,weighted,dimensions);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",weighted ? "force-directed-layout:cpp:edge_weight" : "force-directed-layout:cpp:unweighted"},
            {"dimensions",dimensions},{"candidate_budget",rt::Work{}.max_candidates},
            {"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (records) for (const auto* profile : record_profiles) {
          const bool rejected = record_index(graph,profile);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",profile},{"equal",true},{"rejected",rejected}}) << '\n';
        }
        for (const auto& test : selected_exact) {
          const bool rejected = exact_edges(graph,test);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",test.profile},{"equal",true},{"rejected",rejected}}) << '\n';
        }
        if (!selected_weighted.empty()) {
          for (const auto& test : selected_weighted) {
            const bool rejected = weighted_path(graph,test);
            std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
              {"profile",test.profile},{"equal",true},{"rejected",rejected}}) << '\n';
          }
        }
        if (similarity) for (const auto& [profile,direction] : simrank_cases) {
          traversal(graph,profile,direction);
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile",profile},{"equal",true},{"rejected",false}}) << '\n';
        }
        if (connectivity) {
          traversal(graph,"topological-sort:cpp:default");
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile","topological-sort:cpp:default"},{"equal",true},{"rejected",false}}) << '\n';
        } else if (!simple_profiles.empty()) {
          for (const auto* profile : simple_profiles) {
            traversal(graph,profile);
            std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
              {"profile",profile},{"equal",true},{"rejected",false}}) << '\n';
          }
        } else if (selected_weighted.empty() && selected_exact.empty() && !custom_inputs) traversal(graph);
      }
      catch (const std::exception& e) { throw std::runtime_error(rt::string(input.at("dataset"),"dataset")+": "+e.what()); }
      if (selected_weighted.empty() && selected_exact.empty() && simple_profiles.empty() && !custom_inputs) std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},{"profile","breadth-first-search:cpp:default"},{"equal",true}}) << '\n';
      ++count;
    }
    std::cerr << count << " datasets passed CPU " << (argc > 1 ? argv[1] : "traversal")
              << " array goldens (cold/warm)\n";
    return count ? 0 : 2;
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
