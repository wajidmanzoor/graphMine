#include "graphmine/runtime.hpp"
#include <boost/json.hpp>
#include <algorithm>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace json = boost::json;
namespace {
std::size_t calls = 0;
std::string backend = "cpp";
int device = 0;
void check(bool value, const std::string& message) { if (!value) throw std::runtime_error(message); }
json::value vid(int v) { return v == 0 ? json::value(0) : v == 1 ? json::value("0") : json::value(INT64_C(9007199254740991) + v); }
json::value eid(int e) { return e == 0 ? json::value(0) : e == 1 ? json::value("0") : json::value("edge-" + std::to_string(e)); }
struct Fixture {
  int n;
  std::vector<std::pair<int, int>> edges;
  json::object graph;
  Fixture(int count, unsigned bits) : n(count) {
    json::array vertices, records;
    for (int v = 0; v < n; ++v) vertices.push_back(json::object{{"id", vid(v)}});
    unsigned bit = 0;
    for (int u = 0; u < n; ++u) for (int v = u + 1; v < n; ++v, ++bit) if (bits & (1U << bit)) {
      records.push_back(json::object{{"id", eid(edges.size())}, {"source", vid(u)}, {"target", vid(v)}, {"weight", -2.5}});
      edges.emplace_back(u, v);
    }
    if (!records.empty() && bits % 7 == 0) {
      auto extra = records.front().as_object(); extra["id"] = "parallel";
      std::swap(extra.at("source"), extra.at("target")); records.push_back(extra);
    }
    if (n && bits % 11 == 0) records.push_back(json::object{{"id", "loop"}, {"source", vid(0)}, {"target", vid(0)}});
    graph = {{"graph", {{"id", "structure-oracle"}, {"directed", false}, {"allows_self_loops", true}, {"allows_parallel_edges", true}}},
             {"vertices", vertices}, {"edges", records}};
  }
  int vertex(const json::value& value) const { for (int v = 0; v < n; ++v) if (vid(v) == value) return v; throw std::runtime_error("Lost typed vertex ID"); }
  int edge(const json::value& value) const { for (unsigned e = 0; e < edges.size(); ++e) if (eid(e) == value) return e; throw std::runtime_error("Lost normalized edge ID"); }
  unsigned vertex_mask(const json::array& values) const {
    unsigned output = 0; for (const auto& v : values) { const auto bit = 1U << vertex(v); check(!(output & bit), "Repeated vertex"); output |= bit; } return output;
  }
  unsigned all_edges() const { return (1U << edges.size()) - 1; }
  unsigned neighbors(int u, unsigned selected) const {
    unsigned result = 0;
    for (unsigned e = 0; e < edges.size(); ++e) if (selected & (1U << e)) {
      const auto [a,b] = edges[e]; if (u == a) result |= 1U << b; if (u == b) result |= 1U << a;
    }
    return result;
  }
  unsigned endpoints(unsigned selected) const {
    unsigned result = 0; for (unsigned e = 0; e < edges.size(); ++e) if (selected & (1U << e)) result |= (1U << edges[e].first) | (1U << edges[e].second); return result;
  }
  int components(unsigned selected, unsigned vertices) const {
    int count = 0; unsigned remaining = vertices;
    while (remaining) {
      ++count; unsigned frontier = remaining & -remaining; remaining ^= frontier;
      while (frontier) {
        const auto v = __builtin_ctz(frontier); frontier &= frontier - 1;
        const auto next = neighbors(v, selected) & remaining; remaining &= ~next; frontier |= next;
      }
    }
    return count;
  }
};
json::object request(const char* operation, const Fixture& f, json::object args = {}) {
  return {{"command", "run"}, {"operation", operation}, {"graph", f.graph}, {"parameters", args}, {"backend", backend},
          {"device", backend == "cpp" ? "cpu" : "gpu"}, {"gpu_device", device}};
}
json::object invoke(json::object input, const char* error = nullptr) {
  const auto output = json::parse(graphmine::runtime::request(json::serialize(input))).as_object(); ++calls;
  if (calls % 500 == 0) std::cerr << "Validated " << calls << " structure requests\n";
  if (error) { check(output.contains("error") && output.at("error").as_object().at("code") == error, "Wrong error: " + json::serialize(output)); return output; }
  check(!output.contains("error"), "Native failure: " + json::serialize(output));
  check(output.at("backend").as_object().at("id").as_string() == backend && output.at("complete").as_bool(), "Wrong backend or incomplete result");
  return output;
}
void edge_rows(const Fixture& f, const json::array& rows) {
  for (const auto& item : rows) {
    const auto& row = item.as_object(); const auto e = f.edge(row.at("id")); const auto [u, v] = f.edges[e];
    const auto a = f.vertex(row.at("source")), b = f.vertex(row.at("target"));
    check(std::minmax(a, b) == std::minmax(u, v), "Edge identity/endpoints disagree");
    json::array expected;
    for (const auto& raw : f.graph.at("edges").as_array()) {
      const auto& source = raw.as_object(); const auto a = f.vertex(source.at("source")), b = f.vertex(source.at("target"));
      if (std::minmax(a, b) == std::minmax(u, v)) expected.push_back(source.at("id"));
    }
    check(row.at("source_edge_ids") == expected, "Collapsed original edge identities lost");
  }
}
void truss(const Fixture& f) {
  std::vector<int> expected(f.edges.size(), 2);
  // Enumerate every edge subset, independently of the peeling implementation.
  // Its minimum triangle support makes it a (minimum+2)-truss witness.
  for (unsigned subset = 1; subset <= f.all_edges(); ++subset) {
    int minimum = f.n;
    for (unsigned e = 0; e < f.edges.size(); ++e) if (subset & (1U << e)) {
      const auto [u,v] = f.edges[e]; minimum = std::min(minimum, __builtin_popcount(f.neighbors(u, subset) & f.neighbors(v, subset)));
    }
    for (unsigned e = 0; e < f.edges.size(); ++e) if (subset & (1U << e)) expected[e] = std::max(expected[e], minimum + 2);
  }
  for (const auto k : {json::value(nullptr), json::value(2), json::value(3), json::value(6), json::value(UINT64_MAX)}) {
    const auto output = invoke(request("k-truss", f, {{"requested_k", k}})); const auto& result = output.at("result").as_object();
    const auto& rows = result.at("edges").as_array(); edge_rows(f, rows);
    check(rows.size() == f.edges.size(), "Truss decomposition omitted an edge"); unsigned seen = 0, chosen = 0;
    int maximum = 0;
    for (const auto& raw : rows) {
      const auto& row = raw.as_object(); const auto e = f.edge(row.at("id")); check(!(seen & (1U << e)), "Repeated truss edge"); seen |= 1U << e;
      check(row.at("truss_number").to_number<int>() == expected[e], "Truss number disagrees with subset oracle"); maximum = std::max(maximum, expected[e]);
      if (k.is_null() || static_cast<std::uint64_t>(expected[e]) >= k.to_number<std::uint64_t>()) chosen |= 1U << e;
    }
    check(result.at("maximum_truss_number").to_number<int>() == maximum, "Incorrect maximum truss number");
    unsigned selected = 0; for (const auto& raw : result.at("selected_edges").as_array()) selected |= 1U << f.edge(raw.as_object().at("id"));
    check(selected == chosen && f.vertex_mask(result.at("selected_vertices").as_array()) == f.endpoints(chosen), "Wrong requested truss");
    check(output.at("ports").as_object().at("edges").as_object().at("value") == result.at("selected_edges"), "Truss port differs from selected result");
    const auto& mapping = result.at("truss_number_by_edge").as_array(); unsigned mapped = 0;
    check(mapping.size() == f.edges.size(), "Missing formal edge map");
    for (const auto& raw : mapping) {
      const auto& row = raw.as_object(); const auto e = f.edge(row.at("edge"));
      check(!(mapped & (1U << e)) && row.at("truss_number").to_number<int>() == expected[e], "Incorrect formal edge map"); mapped |= 1U << e;
    }
  }
}
void blocks(const Fixture& f) {
  std::vector<unsigned> connected;
  for (unsigned subset = 1; subset <= f.all_edges(); ++subset) {
    const auto vertices = f.endpoints(subset); bool valid = f.components(subset, vertices) == 1;
    for (int v = 0; v < f.n && valid; ++v) if (vertices & (1U << v)) valid = f.components(subset, vertices & ~(1U << v)) <= 1;
    if (valid) connected.push_back(subset);
  }
  std::set<unsigned> expected;
  for (const auto subset : connected) {
    bool maximal = true; for (const auto other : connected) if (other != subset && (other & subset) == subset) { maximal = false; break; }
    if (maximal) expected.insert(subset);
  }
  const auto all_vertices = (1U << f.n) - 1; const auto base = f.components(f.all_edges(), all_vertices);
  unsigned bridges = 0, articulation = 0, isolated = 0;
  for (unsigned e = 0; e < f.edges.size(); ++e) if (f.components(f.all_edges() & ~(1U << e), all_vertices) > base) bridges |= 1U << e;
  for (int v = 0; v < f.n; ++v) {
    if (f.components(f.all_edges(), all_vertices & ~(1U << v)) > base) articulation |= 1U << v;
    if (!f.neighbors(v, f.all_edges())) isolated |= 1U << v;
  }
  const auto output = invoke(request("biconnected-components", f)); const auto& result = output.at("result").as_object();
  std::set<unsigned> actual; unsigned used = 0;
  for (const auto& row : result.at("blocks").as_array()) {
    unsigned mask = 0; for (const auto& value : row.as_array()) mask |= 1U << f.edge(value);
    check(mask && !(used & mask) && actual.insert(mask).second, "Repeated or empty block edge"); used |= mask;
  }
  check(actual == expected && used == f.all_edges(), "Edge blocks disagree with independent subset oracle");
  check(f.vertex_mask(result.at("articulation_vertices").as_array()) == articulation, "Incorrect articulation set");
  check(f.vertex_mask(result.at("isolated_vertices").as_array()) == isolated, "Missing isolated vertices");
  unsigned found = 0; edge_rows(f, result.at("bridges").as_array());
  for (const auto& row : result.at("bridges").as_array()) found |= 1U << f.edge(row.as_object().at("id")); check(found == bridges, "Incorrect bridge set");
  edge_rows(f, result.at("normalized_edges").as_array());
  for (const auto& row : result.at("groups").as_array()) {
    unsigned edges = 0; for (const auto& e : row.as_object().at("edge_ids").as_array()) edges |= 1U << f.edge(e);
    check(expected.count(edges) && f.vertex_mask(row.as_object().at("vertices").as_array()) == f.endpoints(edges), "Wrong block vertex membership");
  }
}
void contracts() {
  const Fixture f(5, 0x3ff);
  const auto operations = backend == "cpp" ? std::vector<const char*>{"biconnected-components", "k-truss"} : std::vector<const char*>{"k-truss"};
  for (const auto operation : operations) {
    auto directed = request(operation, f); directed.at("graph").as_object().at("graph").as_object()["directed"] = true; invoke(directed, "invalid_input");
    auto unknown = request(operation, f, {{"unknown", 1}}); invoke(unknown, "invalid_input");
    for (const auto key : {"max_output_items", "max_candidates"}) { auto limited = request(operation, f); limited["budget"] = json::object{{key, 1}}; invoke(limited, "resource_limit"); }
    auto expired = request(operation, f); expired["budget"] = {{"timeout_seconds", 1e-12}}; invoke(expired, "resource_limit");
  }
  for (const auto k : {json::value(1), json::value(-1), json::value(true), json::value(3.0)}) invoke(request("k-truss", f, {{"requested_k", k}}), "invalid_input");
}
void boundaries() {
  for (const bool clique : {false, true}) {
    const unsigned n = clique ? 64 : 20000; json::array vertices, edges;
    for (unsigned v = 0; v < n; ++v) vertices.push_back(json::object{{"id", vid(v)}});
    for (unsigned u = 0; u < n; ++u) for (unsigned v = u + 1; v < (clique ? n : std::min(n, u + 2)); ++v)
      edges.push_back(json::object{{"id", edges.size()}, {"source", vid(u)}, {"target", vid(v)}});
    json::object graph{{"graph", {{"id", "deep-structure"}, {"directed", false}, {"allows_self_loops", false}, {"allows_parallel_edges", false}}}, {"vertices", vertices}, {"edges", edges}};
    auto input = request("k-truss", Fixture(0, 0)); input["graph"] = graph;
    input["budget"] = json::object{{"max_candidates", 20000000}, {"max_output_items", 200000}};
    for (const unsigned k : {2U, clique ? n : 3U, clique ? n + 1 : 4U}) {
      input["parameters"] = json::object{{"requested_k", k}}; const auto output = invoke(input); const auto& result = output.at("result").as_object();
      const auto expected = clique ? n : 2U;
      check(result.at("maximum_truss_number").to_number<unsigned>() == expected, "Wrong deep-graph truss number");
      check(result.at("edges").as_array().size() == edges.size(), "Lost deep-graph edges");
      for (const auto& row : result.at("edges").as_array()) check(row.as_object().at("truss_number").to_number<unsigned>() == expected, "Wrong edge truss number");
      check(result.at("selected_edges").as_array().size() == (k <= expected ? edges.size() : 0), "Incorrect deep-graph k selection");
    }
    if (!clique && backend == "cpp") {
      input["operation"] = "biconnected-components"; input["parameters"] = json::object{};
      const auto output = invoke(input); const auto& result = output.at("result").as_object();
      check(result.at("blocks").as_array().size() == n - 1 && result.at("bridges").as_array().size() == n - 1, "Deep path blocks/bridges incomplete");
      check(result.at("articulation_vertices").as_array().size() == n - 2 && result.at("isolated_vertices").as_array().empty(), "Deep path articulation set incorrect");
    }
  }
  for (unsigned bits : {0U, 7U, 127U, 513U, 1023U}) {
    Fixture f(5, bits); auto& vertices = f.graph.at("vertices").as_array(); std::reverse(vertices.begin(), vertices.end());
    truss(f); if (backend == "cpp") blocks(f);
  }
}
}
int main(int argc, char** argv) {
  try {
    const std::string suite = argc > 1 ? argv[1] : "truss"; if (argc > 2) backend = argv[2]; if (argc > 3) device = std::stoi(argv[3]);
    check(suite == "truss" || suite == "blocks" || suite == "contracts" || suite == "boundaries", "Unknown suite");
    if (suite == "contracts") contracts();
    else if (suite == "boundaries") boundaries();
    else {
      for (unsigned mask = 0; mask < 1024; ++mask) { const Fixture f(5, mask); if (suite == "truss") truss(f); else blocks(f); }
      for (int n : {0, 1, 2}) { const Fixture f(n, 0); if (suite == "truss") truss(f); else blocks(f); }
    }
    const auto catalog = json::parse(graphmine::runtime::request("{\"command\":\"catalog\"}")).as_object();
    std::cout << json::serialize(json::object{{"suite", suite}, {"backend", backend}, {"gpu_device", device}, {"passed_requests", calls}, {"failed", 0}, {"implementation_sha256", catalog.at("implementation_sha256")}}) << '\n'; return 0;
  } catch (const std::exception& error) { std::cerr << "Structure oracle failed after " << calls << " requests: " << error.what() << '\n'; return 1; }
}
