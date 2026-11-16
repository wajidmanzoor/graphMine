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
void traversal(const gm::Graph& graph, const char* id = "breadth-first-search:cpp:default") {
  const auto& profile = rt::cpu_view_profile(id);
  auto old_work = unlimited();
  const auto expected = gm::legacy_test::adjacency(graph, old_work);
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
    if (work.candidates != old_work.candidates) throw std::runtime_error("CPU view candidate cost differs");
  }
}
const char* clique_profiles[] = {
  "maximal-cliques:cpp:default", "maximum-clique:cpp:default", "k-cliques:cpp:default",
  "k-core:cpp:default", "maximum-independent-set:cpp:default", "minimum-vertex-cover:cpp:default"
};
const char* reachability_profiles[] = {"transitive-closure:cpp:default", "overlapping-communities:cpp:default"};
const char* density_profiles[] = {"densest-subgraph:cpp:clique_terms", "quasi-cliques:cpp:default"};
struct ExactCase { const char* profile; bool weighted, nonnegative = true, loops = false; };
const ExactCase density_exact_cases[] = {
  {"densest-subgraph:cpp:edge_weight",true}, {"densest-subgraph:cpp:unweighted",false},
  {"densest-k-subgraph:cpp:edge_weight",true}, {"densest-k-subgraph:cpp:unweighted",false}
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
  const auto& used = response.at("representations").as_array().back().as_object();
  if (rt::string(used.at("view_profile"),"view_profile") != profile.id ||
      used.at("view") != rt::json::parse(profile.spec.canonical_json()))
    throw std::runtime_error(profile.id + ": consumed a different declared spec");
}
struct WeightedCase {
  const char* profile; const char* aggregation; bool nonnegative, unit;
  bool weighted = true;
  const char* direction = "outgoing";
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
bool weighted_path(const gm::Graph& graph, const WeightedCase& test) {
  auto reference_work = unlimited(); std::optional<rt::WeightedGraph> expected; std::string failure;
  try { expected = gm::legacy_test::weighted(graph, test.weighted, test.nonnegative, test.aggregation, test.direction, reference_work); }
  catch (const std::exception& e) { failure = e.what(); }
  // Frozen many-source unweighted conversion from 201b2367; validates stored
  // lengths before using unit distances, including discarded self-loops.
  if (expected && test.unit) for (auto& row : expected->rows) for (auto& arc : row) arc.weight = 1;
  for (int repeat=0; repeat<2; ++repeat) {
    auto work = unlimited(); std::shared_ptr<const gm::ViewResult> input; std::string actual_failure;
    try { input = rt::consume_view(graph, rt::cpu_view_profile(test.profile), work, rt::ViewBudget::weighted_adjacency); }
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
  density_input.as_object().at("edges").as_array()[0].as_object()["weight"] = 1e16;
  density_input.as_object().at("edges").as_array()[1].as_object()["weight"] = 1;
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
    const bool density = argc > 1 && std::string(argv[1]) == "--density";
    std::vector<const char*> simple_profiles;
    if (cliques) simple_profiles.assign(std::begin(clique_profiles),std::end(clique_profiles));
    if (reachability) simple_profiles.assign(std::begin(reachability_profiles),std::end(reachability_profiles));
    if (density) simple_profiles.assign(std::begin(density_profiles),std::end(density_profiles));
    std::vector<WeightedCase> selected_weighted;
    if (weighted) selected_weighted.assign(std::begin(weighted_cases),std::end(weighted_cases));
    if (connectivity) selected_weighted.assign(std::begin(connectivity_cases),std::end(connectivity_cases));
    if (centrality) selected_weighted.assign(std::begin(centrality_cases),std::end(centrality_cases));
    std::string line; std::size_t count=0;
    while (std::getline(std::cin,line)) {
      const auto input=rt::strict_json(line).as_object();
      try {
        const auto graph = rt::parse_graph(input.at("graph"));
        if (density) for (const auto& test : density_exact_cases) {
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
        } else if (selected_weighted.empty()) traversal(graph);
      }
      catch (const std::exception& e) { throw std::runtime_error(rt::string(input.at("dataset"),"dataset")+": "+e.what()); }
      if (selected_weighted.empty() && simple_profiles.empty()) std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},{"profile","breadth-first-search:cpp:default"},{"equal",true}}) << '\n';
      ++count;
    }
    std::cerr << count << " datasets passed CPU " << (weighted ? "weighted-path" : connectivity ? "connectivity" : cliques ? "clique/core" : reachability ? "reachability" : density ? "density" : centrality ? "centrality" : "traversal") << " array goldens (cold/warm)\n";
    return count ? 0 : 2;
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
