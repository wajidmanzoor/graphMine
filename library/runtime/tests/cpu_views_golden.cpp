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
void traversal(const gm::Graph& graph) {
  const auto& profile = rt::cpu_view_profile("breadth-first-search:cpp:default");
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
void contracts() {
  const auto raw = rt::strict_json(R"({"graph":{"id":"profile","directed":true,"allows_self_loops":true,"allows_parallel_edges":true},
    "vertices":[{"id":0},{"id":1},{"id":2}],"edges":[
      {"id":0,"source":0,"target":1,"weight":-3},
      {"id":1,"source":0,"target":1,"weight":5},
      {"id":2,"source":1,"target":2,"weight":1},
      {"id":3,"source":2,"target":2,"weight":-1}]})");
  const auto graph = rt::parse_graph(raw);
  traversal(graph);
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
int main(int argc, char**) {
  try {
    if (argc > 1) { contracts(); return 0; }
    std::string line; std::size_t count=0;
    while (std::getline(std::cin,line)) {
      const auto input=rt::strict_json(line).as_object();
      try { traversal(rt::parse_graph(input.at("graph"))); }
      catch (const std::exception& e) { throw std::runtime_error(rt::string(input.at("dataset"),"dataset")+": "+e.what()); }
      std::cout << rt::json::serialize(rt::json::object{{"dataset",input.at("dataset")},{"profile","breadth-first-search:cpp:default"},{"equal",true}}) << '\n';
      ++count;
    }
    std::cerr << count << " datasets passed CPU traversal array goldens (cold/warm)\n";
    return count ? 0 : 2;
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
