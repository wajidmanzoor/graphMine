#include "legacy_normalizers.hpp"
#include "../view_profiles.hpp"
#include "../family_util.hpp"
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
  std::vector<std::uint64_t> offsets{0}; std::vector<gm::VertexIndex> indices;
  for (const auto& row : expected) {
    indices.insert(indices.end(), row.begin(), row.end()); offsets.push_back(indices.size());
  }
  for (int repeat = 0; repeat < 2; ++repeat) {
    auto work = unlimited();
    const auto input = rt::consume_view(graph, profile, work, rt::ViewBudget::original_edges);
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
struct ExactCase { const char* profile; bool weighted, nonnegative = true, loops = false; };
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
bool exact_edges(const gm::Graph& graph, const ExactCase& test, std::uint64_t budget = UINT64_MAX) {
  auto old_work = unlimited(); old_work.max_candidates = budget;
  std::optional<std::vector<gm::legacy_test::ExactEdge>> expected;
  std::string expected_failure;
  try { expected = gm::legacy_test::exact_edges(graph,test.weighted,old_work,test.nonnegative,test.loops); }
  catch (const std::exception& e) { expected_failure = e.what(); }
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); work.max_candidates = budget;
    std::optional<std::vector<rt::family_util::Edge>> actual;
    std::string actual_failure;
    try { actual = rt::family_util::edges(graph,rt::cpu_view_profile(test.profile),work); }
    catch (const std::exception& e) { actual_failure = e.what(); }
    if (expected_failure != actual_failure) throw std::runtime_error(std::string(test.profile)+": exact edge rejection differs");
    if (!expected) continue;
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
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); std::shared_ptr<const gm::ViewResult> input; std::string actual_failure;
    try {
      input = rt::consume_view(graph, rt::cpu_view_profile(test.profile), work, rt::ViewBudget::weighted_adjacency);
      if (test.extra_adjacency) work.tick(graph.edge_count());
    }
    catch (const std::exception& e) { actual_failure = e.what(); }
    if (failure != actual_failure) throw std::runtime_error(std::string(test.profile)+": rejection differs");
    if (!expected) continue;
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
  traversal(graph);
  for (const auto& test : weighted_cases) weighted_path(graph,test);
  for (const auto& test : connectivity_cases) weighted_path(graph,test);
  traversal(graph,"topological-sort:cpp:default");
  auto undirected = raw;
  undirected.as_object().at("graph").as_object()["directed"] = false;
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
  auto spectral_input = density_input;
  spectral_input.as_object().at("edges").as_array().pop_back();
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
    std::vector<ExactCase> selected_exact;
    if (density) selected_exact.assign(std::begin(density_exact_cases),std::end(density_exact_cases));
    if (partitioning) selected_exact.assign(std::begin(partition_exact_cases),std::end(partition_exact_cases));
    if (spectral) selected_exact.assign(std::begin(spectral_exact_cases),std::end(spectral_exact_cases));
    if (alignment) selected_exact.assign(std::begin(alignment_exact_cases),std::end(alignment_exact_cases));
    std::string line; std::size_t count=0;
    while (std::getline(std::cin,line)) {
      const auto input=rt::strict_json(line).as_object();
      try {
        const auto graph = rt::parse_graph(input.at("graph"));
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
        } else if (selected_weighted.empty() && selected_exact.empty()) traversal(graph);
      }
      catch (const std::exception& e) { throw std::runtime_error(rt::string(input.at("dataset"),"dataset")+": "+e.what()); }
      if (selected_weighted.empty() && selected_exact.empty() && simple_profiles.empty()) std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},{"profile","breadth-first-search:cpp:default"},{"equal",true}}) << '\n';
      ++count;
    }
    std::cerr << count << " datasets passed CPU " << (weighted ? "weighted-path" : connectivity ? "connectivity" : cliques ? "clique/core" : reachability ? "reachability" : density ? "density" : centrality ? "centrality" : coloring ? "coloring" : similarity ? "similarity" : patterns ? "patterns" : partitioning ? "partitioning" : spectral ? "spectral" : alignment ? "alignment" : "traversal") << " array goldens (cold/warm)\n";
    return count ? 0 : 2;
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
