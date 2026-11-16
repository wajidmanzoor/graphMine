#include "legacy_normalizers.hpp"
#include "../view_profiles.hpp"
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
    if (work.candidates != old_work.candidates) throw std::runtime_error("CPU view candidate cost differs");
  }
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
    std::string line; std::size_t count=0;
    while (std::getline(std::cin,line)) {
      const auto input=rt::strict_json(line).as_object();
      try {
        const auto graph = rt::parse_graph(input.at("graph"));
        if (weighted) {
          for (const auto& test : weighted_cases) {
            const bool rejected = weighted_path(graph,test);
            std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
              {"profile",test.profile},{"equal",true},{"rejected",rejected}}) << '\n';
          }
        } else if (connectivity) {
          for (const auto& test : connectivity_cases) {
            const bool rejected = weighted_path(graph,test);
            std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
              {"profile",test.profile},{"equal",true},{"rejected",rejected}}) << '\n';
          }
          traversal(graph,"topological-sort:cpp:default");
          std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},
            {"profile","topological-sort:cpp:default"},{"equal",true},{"rejected",false}}) << '\n';
        } else traversal(graph);
      }
      catch (const std::exception& e) { throw std::runtime_error(rt::string(input.at("dataset"),"dataset")+": "+e.what()); }
      if (!weighted && !connectivity) std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},{"profile","breadth-first-search:cpp:default"},{"equal",true}}) << '\n';
      ++count;
    }
    std::cerr << count << " datasets passed CPU " << (weighted ? "weighted-path" : connectivity ? "connectivity" : "traversal") << " array goldens (cold/warm)\n";
    return count ? 0 : 2;
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
