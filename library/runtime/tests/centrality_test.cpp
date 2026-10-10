#include "graphmine/runtime.hpp"
#include <boost/json.hpp>
#include <boost/multiprecision/cpp_int.hpp>
#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <numeric>
#include <optional>
#include <queue>
#include <stdexcept>
#include <string>
#include <vector>

namespace json = boost::json;
using Exact = boost::multiprecision::cpp_rational;
using Integer = boost::multiprecision::cpp_int;
namespace {
std::string backend = "cpp"; int device = 0; std::size_t calls = 0;
void check(bool ok, const std::string& message) { if (!ok) throw std::runtime_error(message); }
json::value id(int v) { return v == 0 ? json::value("0") : v == 1 ? json::value(0) : json::value(INT64_C(9007199254740991) + v); }
struct Fixture {
  int n; bool directed; json::object graph;
  std::vector<std::vector<std::optional<Exact>>> weights;
  Fixture(int count, bool direction, unsigned mask, unsigned base = 2) : n(count), directed(direction), weights(n, std::vector<std::optional<Exact>>(n)) {
    json::array vertices, edges;
    for (int v = 0; v < n; ++v) vertices.push_back(json::object{{"id", id(v)}});
    for (int u = 0; u < n; ++u) for (int v = directed ? 0 : u + 1; v < n; ++v) if (u != v) {
      const auto digit = mask % base; mask /= base; if (!digit) continue;
      const double weight = digit == 1 ? 0.5 : 1;
      edges.push_back(json::object{{"id", edges.size()}, {"source", id(u)}, {"target", id(v)}, {"weight", weight}});
      weights[u][v] = Exact(weight); if (!directed) weights[v][u] = Exact(weight);
    }
    if (!edges.empty()) { auto duplicate = edges.front().as_object(); duplicate["id"] = "parallel"; duplicate["weight"] = 3; edges.push_back(duplicate); }
    if (n) edges.push_back(json::object{{"id", "loop"}, {"source", id(0)}, {"target", id(0)}, {"weight", 1}});
    graph = {{"graph", {{"id", "centrality-oracle"}, {"directed", directed}, {"allows_self_loops", true}, {"allows_parallel_edges", true}}}, {"vertices", vertices}, {"edges", edges}};
  }
  int vertex(const json::value& value) const { for (int v = 0; v < n; ++v) if (id(v) == value) return v; throw std::runtime_error("Lost typed vertex identity"); }
};
json::object request(const char* operation, const Fixture& f, json::object args = {}) {
  return {{"command", "run"}, {"operation", operation}, {"graph", f.graph}, {"parameters", args}, {"backend", backend}, {"device", backend == "cpp" ? "cpu" : "gpu"}, {"gpu_device", device}};
}
json::object invoke(json::object input, const char* error = nullptr) {
  const auto result = json::parse(graphmine::runtime::request(json::serialize(input))).as_object(); ++calls;
  if (calls % 500 == 0) std::cerr << "Validated " << calls << " centrality requests\n";
  if (error) { check(result.contains("error") && result.at("error").as_object().at("code") == error, "Unexpected error: " + json::serialize(result)); return result; }
  check(!result.contains("error"), "Native failure: " + json::serialize(result));
  check(result.at("backend").as_object().at("id").as_string() == backend, "Wrong backend"); return result;
}
Exact score(const json::object& row) {
  const auto& value = row.at("score_exact").as_object();
  return Exact(Integer(std::string(value.at("numerator").as_string()))) / Integer(std::string(value.at("denominator").as_string()));
}
void scores(const Fixture& f, const json::object& output, const std::vector<Exact>& expected) {
  const auto& result = output.at("result").as_object(); const auto& rows = result.at("vertices").as_array();
  check(output.at("complete").as_bool() && result.at("complete").as_bool() && rows.size() == static_cast<unsigned>(f.n), "Incomplete score vector");
  check(output.at("ports").as_object().at("scores").as_object().at("value") == rows, "Score port differs from full results");
  std::vector<bool> seen(f.n, false); std::vector<double> actual(f.n);
  for (const auto& raw : rows) {
    const auto& row = raw.as_object(); const auto v = f.vertex(row.at("vertex")); check(!seen[v], "Repeated score"); seen[v] = true;
    actual[v] = row.at("score").to_number<double>();
    if (backend == "cpp") check(score(row) == expected[v], "Exact score disagrees with path enumeration");
    else check(std::abs(actual[v] - expected[v].convert_to<double>()) <= (backend == "turbo-bc" ? 3e-6 : 1e-10) * std::max(1.0, std::abs(expected[v].convert_to<double>())), "GPU score disagrees with exact oracle");
  }
  const auto& ranked = result.at("ranked_vertices").as_array(); check(ranked.size() == rows.size(), "Formal ranking omitted a vertex");
  std::vector<int> order(f.n); std::iota(order.begin(), order.end(), 0);
  auto id_less = [](int a, int b) { if (a == 0 || b == 0) return a != 0; return a < b; };
  std::sort(order.begin(), order.end(), [&](int a, int b) { return actual[a] != actual[b] ? actual[a] > actual[b] : id_less(a, b); });
  for (int rank = 0; rank < f.n; ++rank) {
    const auto& row = ranked[rank].as_object(); check(f.vertex(row.at("vertex")) == order[rank] && row.at("rank").to_number<int>() == rank + 1, "Ranking or typed-ID tie break is incorrect");
  }
  check(result.at("score_definition").as_object().contains("tie_break"), "Missing score definition");
}
std::vector<Exact> path_oracle(const Fixture& f, bool weighted) {
  // Enumerate all simple source-target paths and retain every exact shortest
  // path. This oracle does not use Brandes dependencies or path-count recurrences.
  std::vector<Exact> result(f.n, 0);
  for (int source = 0; source < f.n; ++source) for (int target = 0; target < f.n; ++target) if (source != target) {
    std::optional<Exact> minimum; std::vector<std::vector<int>> optimal; std::vector<int> path{source};
    std::function<void(int, unsigned, Exact)> walk = [&](int u, unsigned seen, Exact distance) {
      if (minimum && distance > *minimum) return;
      if (u == target) {
        if (!minimum || distance < *minimum) { minimum = distance; optimal.clear(); }
        optimal.push_back(path); return;
      }
      for (int v = 0; v < f.n; ++v) if (!(seen & (1U << v)) && f.weights[u][v]) {
        path.push_back(v); walk(v, seen | (1U << v), distance + (weighted ? *f.weights[u][v] : Exact(1))); path.pop_back();
      }
    };
    walk(source, 1U << source, 0);
    for (const auto& p : optimal) for (unsigned i = 1; i + 1 < p.size(); ++i) result[p[i]] += Exact(1) / optimal.size();
  }
  return result;
}
void betweenness(const Fixture& f, bool weighted) {
  const auto raw = path_oracle(f, weighted);
  for (bool normalized : {false, true}) {
    Exact scale = f.directed ? Exact(1) : Exact(1) / 2;
    if (normalized) scale = f.n < 3 ? Exact(0) : Exact(1) / ((f.n - 1) * (f.n - 2));
    auto expected = raw; for (auto& value : expected) value *= scale;
    scores(f, invoke(request("betweenness-centrality", f, {{"normalized", normalized}, {"weight_mode", weighted ? "edge_weight" : "unweighted"}})), expected);
  }
}
void degree(const Fixture& f) {
  for (const auto direction : {"incoming", "outgoing", "both", "undirected_projection"}) for (bool normalized : {false, true}) {
    std::vector<Exact> expected(f.n, 0);
    for (int u = 0; u < f.n; ++u) for (int v = 0; v < f.n; ++v) if (u != v) {
      if (!f.directed) expected[u] += bool(f.weights[u][v]);
      else if (std::string(direction) == "both") expected[u] += bool(f.weights[u][v]) + bool(f.weights[v][u]);
      else if (std::string(direction) == "incoming") expected[u] += bool(f.weights[v][u]);
      else if (std::string(direction) == "outgoing") expected[u] += bool(f.weights[u][v]);
      else expected[u] += bool(f.weights[u][v]) || bool(f.weights[v][u]);
    }
    if (normalized && f.n > 1) for (auto& value : expected) value /= f.n - 1;
    scores(f, invoke(request("degree-centrality", f, {{"direction_mode", direction}, {"normalized", normalized}})), expected);
  }
}
void contracts() {
  const Fixture f(5, false, 0x3ff);
  const auto operations = backend == "cpp" ? std::vector<const char*>{"degree-centrality", "betweenness-centrality"} : std::vector<const char*>{"betweenness-centrality"};
  for (const auto op : operations) {
    invoke(request(op, f, {{"normalized", 1}}), "invalid_input"); invoke(request(op, f, {{"unknown", true}}), "invalid_input");
    for (const auto key : {"max_candidates", "max_output_items"}) { auto input = request(op, f); input["budget"] = json::object{{key, 1}}; invoke(input, "resource_limit"); }
    auto expired = request(op, f); expired["budget"] = json::object{{"timeout_seconds", 1e-12}}; invoke(expired, "resource_limit");
  }
  invoke(request("betweenness-centrality", f, {{"weight_mode", "invalid"}}), "invalid_input");
  if (backend == "cpp") {
    invoke(request("degree-centrality", f, {{"direction_mode", "invalid"}}), "invalid_input");
    for (double weight : {0.0, -1.0}) {
      auto bad = request("betweenness-centrality", f, {{"weight_mode", "edge_weight"}}); bad.at("graph").as_object().at("edges").as_array()[0].as_object()["weight"] = weight; invoke(bad, "invalid_input");
    }
  } else invoke(request("betweenness-centrality", f, {{"weight_mode", "edge_weight"}}), "unsupported_input");
  if (backend == "turbo-bc") invoke(request("betweenness-centrality", Fixture(3, true, 63)), "unsupported_input");
}
void boundaries() {
  // Every source-target pair contributes distance-1 to the sum of raw scores.
  // This identity and layer symmetry check exponentially many shortest paths
  // without enumerating them or duplicating the Brandes implementation.
  for (const int n : {62, 66, 264}) {
    Fixture f(n, false, 0); json::array edges; std::vector<std::vector<int>> adjacency(n);
    for (int layer = 0; layer < n / 2 - 1; ++layer) for (int a = 0; a < 2; ++a) for (int b = 0; b < 2; ++b) {
      const int u = 2 * layer + a, v = 2 * layer + 2 + b;
      edges.push_back(json::object{{"id", edges.size()}, {"source", id(u)}, {"target", id(v)}});
      adjacency[u].push_back(v); adjacency[v].push_back(u);
    }
    f.graph["edges"] = edges;
    auto input = request("betweenness-centrality", f, {{"normalized", false}});
    if (backend != "cpp" && n >= 66) { invoke(input, "unsupported_input"); continue; }
    const auto output = invoke(input); const auto& rows = output.at("result").as_object().at("vertices").as_array();
    Exact expected = 0, actual_exact = 0; double actual = 0; std::vector<double> values(n);
    for (int source = 0; source < n; ++source) {
      std::vector<int> distance(n, -1); distance[source] = 0; std::queue<int> queue; queue.push(source);
      while (!queue.empty()) { const auto u = queue.front(); queue.pop(); for (const auto v : adjacency[u]) if (distance[v] < 0) { distance[v] = distance[u] + 1; queue.push(v); } }
      for (int target = source + 1; target < n; ++target) expected += distance[target] - 1;
    }
    for (const auto& raw : rows) { const auto& row = raw.as_object(); const auto v = f.vertex(row.at("vertex")); values[v] = row.at("score").to_number<double>(); actual += values[v]; if (backend == "cpp") actual_exact += score(row); }
    if (backend == "cpp") check(actual_exact == expected, "Unbounded path-count accumulation violates pair-distance identity");
    else check(std::isfinite(actual) && std::abs(actual - expected.convert_to<double>()) <= 1e-5 * expected.convert_to<double>(), "GPU path-count accumulation violates pair-distance identity");
    for (int v = 0; v < n; v += 2) check(std::abs(values[v] - values[v + 1]) < 1e-4 * std::max(1.0, values[v]), "Layer symmetry is broken");
  }
  if (backend == "cpp") {
    // Exact distances distinguish a true tie from a binary64 rounded sum,
    // including costs larger than the largest finite floating-point number.
    for (const auto weights : {std::vector<double>{9007199254740992.0, 1, 9007199254740992.0, 2},
                               std::vector<double>{1e308, 1e308, 1e308, 5e307},
                               std::vector<double>{std::numeric_limits<double>::denorm_min(), std::numeric_limits<double>::denorm_min(), 1, 1}}) {
      Fixture f(4, true, 0); json::array edges;
      for (int i = 0; i < 4; ++i) {
        const int u = i < 2 ? i : i == 2 ? 0 : 2, v = i < 2 ? i == 0 ? 1 : 3 : i == 2 ? 2 : 3;
        f.weights[u][v] = Exact(weights[i]); edges.push_back(json::object{{"id", i}, {"source", id(u)}, {"target", id(v)}, {"weight", weights[i]}});
      }
      f.graph["edges"] = edges; betweenness(f, true);
    }
  }
  for (int n : {0, 1, 2}) { const Fixture f(n, false, 0); betweenness(f, false); if (backend == "cpp") degree(f); }
}
}
int main(int argc, char** argv) {
  try {
    const std::string suite = argc > 1 ? argv[1] : "betweenness"; if (argc > 2) backend = argv[2]; if (argc > 3) device = std::stoi(argv[3]);
    if (suite == "contracts") contracts();
    else if (suite == "boundaries") boundaries();
    else if (suite == "weighted") { check(backend == "cpp", "Only CPU supports positive weighted betweenness"); for (unsigned mask = 0; mask < 729; ++mask) { betweenness(Fixture(4, false, mask, 3), true); betweenness(Fixture(3, true, mask, 3), true); } }
    else {
      check(suite == "betweenness" || (suite == "degree" && backend == "cpp"), "Unknown suite or backend");
      auto run = [&](const Fixture& f) { if (suite == "degree") degree(f); else betweenness(f, false); };
      for (unsigned mask = 0; mask < 1024; ++mask) run(Fixture(5, false, mask));
      if (backend != "turbo-bc") {
        for (unsigned mask = 0; mask < 4096; mask += 17) run(Fixture(4, true, mask));
        for (unsigned mask = 0; mask < 64; ++mask) run(Fixture(3, true, mask));
      }
    }
    const auto catalog = json::parse(graphmine::runtime::request("{\"command\":\"catalog\"}")).as_object();
    std::cout << json::serialize(json::object{{"suite", suite}, {"backend", backend}, {"gpu_device", device}, {"passed_requests", calls}, {"failed", 0}, {"implementation_sha256", catalog.at("implementation_sha256")}}) << '\n'; return 0;
  } catch (const std::exception& error) { std::cerr << "Centrality oracle failed after " << calls << " requests: " << error.what() << '\n'; return 1; }
}
