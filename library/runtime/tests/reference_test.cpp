#include "graphmine/runtime.hpp"
#include <boost/json.hpp>
#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace json = boost::json;
namespace {
std::size_t cases = 0;
std::string device = "cpu";
int ordinal = 0;
using Matrix = std::vector<std::vector<long double>>;
constexpr long double infinity = 1e30L;
void check(bool condition, const std::string& message) { if (!condition) throw std::runtime_error(message); }
json::value id(int v) { return v == 0 ? json::value(0) : v == 1 ? json::value("0") : json::value(INT64_C(9007199254740991) + v); }
int index(const json::value& value, int n) { for (int v = 0; v < n; ++v) if (value == id(v)) return v; throw std::runtime_error("Lost typed vertex ID"); }
json::object fixture(int n, bool directed, unsigned code, bool weighted = false, double a = 0, double b = 1.5) {
  json::array nodes, edges;
  for (int v = 0; v < n; ++v) nodes.push_back(json::object{{"id", id(v)}});
  for (int u = 0; u < n; ++u) for (int v = directed ? 0 : u + 1; v < n; ++v) {
    if (u == v) continue;
    const auto state = code % (weighted ? 3 : 2); code /= weighted ? 3 : 2;
    if (state) edges.push_back(json::object{{"id", edges.size()}, {"source", id(u)}, {"target", id(v)}, {"weight", weighted ? (state == 1 ? a : b) : 1.0}});
  }
  return {{"graph", {{"id", "reference-oracle"}, {"directed", directed}, {"allows_self_loops", true}, {"allows_parallel_edges", true}}}, {"vertices", nodes}, {"edges", edges}};
}
json::object request(const char* operation, const json::object& graph, json::object parameters = {}) {
  return {{"command", "run"}, {"operation", operation}, {"graph", graph}, {"parameters", parameters}, {"device", device}, {"gpu_device", ordinal}};
}
json::object invoke(const json::object& input, const std::string& error = "") {
  const auto output = json::parse(graphmine::runtime::request(json::serialize(input))).as_object();
  ++cases;
  if (cases % 500 == 0) std::cerr << "Validated " << cases << " native requests on " << device << ' ' << ordinal << '\n';
  if (!error.empty()) { check(output.contains("error") && output.at("error").as_object().at("code").as_string() == error, "Wrong error: " + json::serialize(output)); return output; }
  check(!output.contains("error"), "Native operation failed: " + json::serialize(input) + " => " + json::serialize(output));
  if (input.at("device") != "auto") check(output.at("backend").as_object().at("device") == input.at("device"), "Wrong device");
  return output;
}
Matrix lengths(const json::object& graph, int n, bool unweighted = false, bool weak = false) {
  Matrix d(n, std::vector<long double>(n, infinity));
  for (int v = 0; v < n; ++v) d[v][v] = 0;
  for (const auto& raw : graph.at("edges").as_array()) {
    const auto& e = raw.as_object(); const auto u = index(e.at("source"), n), v = index(e.at("target"), n);
    const long double w = unweighted ? 1 : e.at("weight").to_number<double>();
    d[u][v] = std::min(d[u][v], w);
    if (weak || !graph.at("graph").as_object().at("directed").as_bool()) d[v][u] = std::min(d[v][u], w);
  }
  return d;
}
Matrix floyd(Matrix d) {
  for (std::size_t k = 0; k < d.size(); ++k) for (std::size_t u = 0; u < d.size(); ++u) for (std::size_t v = 0; v < d.size(); ++v)
    if (d[u][k] < infinity && d[k][v] < infinity) d[u][v] = std::min(d[u][v], d[u][k] + d[k][v]);
  return d;
}
void distance(const json::object& row, long double expected) {
  check(row.at("distance").is_null() == (expected >= infinity), "Incorrect unreachable distance");
  if (expected < infinity) {
    check(row.at("distance").to_number<double>() == expected, "Weighted distance disagrees with Floyd oracle");
    if (device == "cpu") {
      const auto& exact = row.at("distance_exact").as_object();
      check(std::stold(std::string(exact.at("numerator").as_string())) / std::stold(std::string(exact.at("denominator").as_string())) == expected, "Incorrect exact distance");
    }
  }
}
void paths() {
  for (unsigned mask = 0; mask < 729; ++mask) {
    auto graph = fixture(3, true, mask, true);
    if (mask % 11 == 0 && !graph.at("edges").as_array().empty()) {
      auto extra = graph.at("edges").as_array().front().as_object(); extra["id"] = "parallel"; extra["weight"] = 7;
      graph.at("edges").as_array().push_back(extra);
    }
    const auto direct = lengths(graph, 3), expected = floyd(direct);
    for (int source = 0; source < 3; ++source) {
      json::object params{{"source", id(source)}, {"cutoff", source == 1 ? json::value(1.5) : json::value(nullptr)}};
      const auto output = invoke(request("single-source-shortest-paths", graph, params));
      const auto& rows = output.at("result").as_object().at("distances").as_array();
      check(rows.size() == 3, "Missing shortest path rows");
      for (const auto& value : rows) {
        const auto& row = value.as_object(); const auto v = index(row.at("vertex"), 3);
        const auto want = source == 1 && expected[source][v] > 1.5 ? infinity : expected[source][v];
        distance(row, want);
        if (want < infinity && v != source) {
          int current = v; std::set<int> seen;
          while (current != source) {
            check(seen.insert(current).second, "Cyclic shortest path witness");
            const auto& predecessor = rows[current].as_object().at("predecessor");
            check(!predecessor.is_null(), "Missing predecessor"); const auto parent = index(predecessor, 3);
            check(expected[source][parent] + direct[parent][current] == expected[source][current], "Non-tight predecessor edge"); current = parent;
          }
        } else check(row.at("predecessor").is_null(), "Source or unreachable vertex has predecessor");
      }
    }
    for (const bool unweighted : {false, true}) {
      const auto output = invoke(request("many-source-shortest-paths", graph, {{"weight_mode", unweighted ? "unweighted" : "edge_weight"}}));
      const auto want = unweighted ? floyd(lengths(graph, 3, true)) : expected;
      const auto& rows = output.at("result").as_object().at("distances").as_array(); check(rows.size() == 9, "Missing many-source rows");
      for (const auto& value : rows) { const auto& row = value.as_object(); distance(row, want[index(row.at("source"), 3)][index(row.at("target"), 3)]); }
    }
  }
}
void forests() {
  for (unsigned mask = 0; mask < 729; ++mask) {
    const auto graph = fixture(4, false, mask, true, -2, 3);
    const auto reach = floyd(lengths(graph, 4, true));
    int components = 0;
    for (int u = 0; u < 4; ++u) { bool earlier = false; for (int v = 0; v < u; ++v) earlier |= reach[u][v] < infinity; if (!earlier) ++components; }
    long double minimum = infinity, maximum = -infinity;
    const auto& edges = graph.at("edges").as_array();
    // Enumerate every edge subset and accept only spanning acyclic forests.
    for (unsigned bits = 0; bits < (1U << edges.size()); ++bits) {
      if (__builtin_popcount(bits) != 4 - components) continue;
      auto subset = fixture(4, false, 0); long double weight = 0;
      for (std::size_t e = 0; e < edges.size(); ++e) if (bits & (1U << e)) { subset.at("edges").as_array().push_back(edges[e]); weight += edges[e].as_object().at("weight").to_number<double>(); }
      const auto connected = floyd(lengths(subset, 4, true)); bool spans = true;
      for (int u = 0; u < 4; ++u) for (int v = 0; v < 4; ++v) spans &= (reach[u][v] < infinity) == (connected[u][v] < infinity);
      if (spans) { minimum = std::min(minimum, weight); maximum = std::max(maximum, weight); }
    }
    for (const bool maximize : {false, true}) {
      const auto output = invoke(request("spanning-tree-forest", graph, {{"objective", maximize ? "maximum" : "minimum"}}));
      const auto& result = output.at("result").as_object();
      check(result.at("total_weight").to_number<double>() == (maximize ? maximum : minimum), "Forest disagrees with exhaustive subset oracle");
      check(result.at("vertices").as_array().size() == 4 && result.at("edges").as_array().size() == static_cast<unsigned>(4 - components), "Forest lost isolates or has a cycle");
      auto selected = fixture(4, false, 0); std::set<std::pair<int,int>> seen; long double total = 0;
      for (const auto& raw : result.at("edges").as_array()) {
        auto edge = raw.as_object(); const auto u = index(edge.at("source"), 4), v = index(edge.at("target"), 4);
        check(u < v && seen.emplace(u, v).second, "Invalid forest edge");
        bool exists = false; for (const auto& candidate : edges) { const auto& c = candidate.as_object(); exists |= edge.at("source") == c.at("source") && edge.at("target") == c.at("target") && edge.at("weight") == c.at("weight"); }
        check(exists, "Unknown forest edge"); total += edge.at("weight").to_number<double>(); edge["id"] = seen.size(); selected.at("edges").as_array().push_back(edge);
      }
      check(total == (maximize ? maximum : minimum), "Forest total differs from returned witness");
      const auto actual = floyd(lengths(selected, 4, true));
      for (int u = 0; u < 4; ++u) for (int v = 0; v < 4; ++v) check((reach[u][v] < infinity) == (actual[u][v] < infinity), "Forest does not span a component");
    }
  }
}
void connectivity() {
  for (bool directed : {false, true}) for (unsigned mask = 0; mask < 64; ++mask) {
    const int n = directed ? 3 : 4; const auto graph = fixture(n, directed, mask);
    for (const bool strong : {false, true}) {
      const auto output = invoke(request("connected-components", graph, {{"connectivity_mode", strong ? "strongly_connected" : "weakly_connected"}}));
      const auto expected = floyd(lengths(graph, n, true, !strong));
      std::vector<int> labels(n, -1); int label = 0;
      for (const auto& raw : output.at("result").as_object().at("groups").as_array()) {
        const auto& row = raw.as_object(); check(row.at("size").to_number<std::size_t>() == row.at("vertices").as_array().size(), "Incorrect group size");
        for (const auto& vertex : row.at("vertices").as_array()) { const auto v = index(vertex, n); check(labels[v] < 0, "Duplicate group member"); labels[v] = label; } ++label;
      }
      for (int u = 0; u < n; ++u) { check(labels[u] >= 0, "Missing group member"); for (int v = 0; v < n; ++v) check((labels[u] == labels[v]) == (expected[u][v] < infinity && expected[v][u] < infinity), "Connectivity disagrees with reachability oracle"); }
    }
    if (directed && device == "cpu") {
      const auto reach = floyd(lengths(graph, n, true)); bool cycle = false;
      for (int u = 0; u < n; ++u) for (int v = u + 1; v < n; ++v) cycle |= reach[u][v] < infinity && reach[v][u] < infinity;
      const auto result = invoke(request("topological-sort", graph), cycle ? "invalid_input" : "");
      if (!cycle) {
        const auto& order = result.at("result").as_object().at("order").as_array(); check(order.size() == static_cast<unsigned>(n), "Incomplete topological order");
        std::vector<int> positions(n, -1);
        for (int i = 0; i < n; ++i) { const auto v = index(order[i], n); check(positions[v] < 0, "Duplicate topological vertex"); positions[v] = i; }
        for (const auto& e : graph.at("edges").as_array()) check(positions[index(e.as_object().at("source"), n)] < positions[index(e.as_object().at("target"), n)], "Topological order violates an arc");
      }
    }
  }
}
std::vector<long double> rank_oracle(const json::object& graph, bool weighted, int direction, int dangling, bool personalized, double alpha) {
  const int n = graph.at("vertices").as_array().size(); Matrix weights(n, std::vector<long double>(n, 0));
  for (const auto& raw : graph.at("edges").as_array()) {
    const auto& edge = raw.as_object(); auto u = index(edge.at("source"), n), v = index(edge.at("target"), n); if (u == v) continue;
    if (direction == 1) std::swap(u, v);
    const long double w = weighted ? edge.at("weight").to_number<double>() : 1;
    weights[u][v] += w; if (direction == 2) weights[v][u] += w;
  }
  std::vector<long double> seeds(n, personalized ? 0 : 1.0L / n); if (personalized) seeds[0] = 1;
  Matrix system(n, std::vector<long double>(n + 1, 0));
  for (int v = 0; v < n; ++v) { system[v][v] = 1; system[v][n] = (1 - alpha) * seeds[v]; }
  for (int u = 0; u < n; ++u) {
    long double total = 0; for (const auto weight : weights[u]) total += weight;
    for (int v = 0; v < n; ++v) {
      const long double probability = total ? weights[u][v] / total : dangling == 2 ? (u == v ? 1 : 0) : dangling == 1 ? 1.0L / n : seeds[v];
      system[v][u] -= alpha * probability;
    }
  }
  // Solve (I - alpha P^T)x = (1-alpha)p by pivoted elimination,
  // independently of the implementation's iterative solver.
  for (int k = 0; k < n; ++k) {
    int pivot = k; for (int u = k + 1; u < n; ++u) if (std::abs(system[u][k]) > std::abs(system[pivot][k])) pivot = u;
    std::swap(system[pivot], system[k]); const auto scale = system[k][k]; check(std::abs(scale) > 1e-15L, "Singular oracle matrix");
    for (int j = k; j <= n; ++j) system[k][j] /= scale;
    for (int u = 0; u < n; ++u) if (u != k) { const auto factor = system[u][k]; for (int j = k; j <= n; ++j) system[u][j] -= factor * system[k][j]; }
  }
  std::vector<long double> result; for (const auto& row : system) result.push_back(row[n]); return result;
}
void rank_check(const json::object& output, const std::vector<long double>& expected) {
  const auto& rows = output.at("ports").as_object().at("scores").as_object().at("value").as_array(); check(rows.size() == expected.size(), "Incomplete PageRank score port");
  check(output.at("ports").as_object().at("scores").as_object().at("complete").as_bool(), "Full PageRank scores marked incomplete");
  long double error = 0; for (const auto& raw : rows) { const auto& row = raw.as_object(); error += std::abs(row.at("score").to_number<double>() - expected[index(row.at("vertex"), expected.size())]); }
  check(error < 1e-8L, "PageRank disagrees with linear-system oracle");
  const auto& diag = output.at("diagnostics").as_object(); check(diag.at("fixed_point_residual_l1").to_number<double>() <= diag.at("accepted_residual").to_number<double>(), "PageRank claims an excessive residual");
}
void ranks() {
  for (unsigned mask = 0; mask < 64; ++mask) {
    auto graph = fixture(3, true, mask);
    auto& edges = graph.at("edges").as_array(); for (std::size_t e = 0; e < edges.size(); ++e) edges[e].as_object()["weight"] = (e % 3) * 0.5;
    if (!edges.empty() && mask % 7 == 0) { auto copy = edges.front().as_object(); copy["id"] = "parallel"; edges.push_back(copy); }
    for (const bool weighted : {false, true}) {
      const auto result = invoke(request("pagerank", graph, {{"weight_mode", weighted ? "edge_weight" : "unweighted"}})); rank_check(result, rank_oracle(graph, weighted, 0, 0, false, 0.85));
    }
    for (int direction = 0; direction < 3; ++direction) for (int policy = 0; policy < 3; ++policy) {
      if (device == "gpu" && policy == 1) continue;  // Explicitly CPU-only native capability.
      const auto result = invoke(request("personalized-pagerank", graph, {{"seed_vertices", {id(0), id(0)}}, {"weight_mode", "edge_weight"},
          {"direction_mode", direction == 0 ? "outgoing" : direction == 1 ? "incoming" : "undirected_projection"},
          {"dangling_policy", policy == 0 ? "redistribute_to_seeds" : policy == 1 ? "redistribute_uniformly" : "self_loop"}, {"exclude_seeds_from_output", true}, {"top_k", 1}}));
      rank_check(result, rank_oracle(graph, true, direction, policy, true, 0.85));
      const auto& ranking = result.at("result").as_object().at("ranking").as_array(); check(ranking.size() == 1 && ranking.front().as_object().at("vertex") != id(0), "Seed exclusion/top_k failed");
    }
  }
  auto graph = fixture(12, true, 0);
  for (int u = 0; u < 12; ++u) for (int delta : {1, 3})
    graph.at("edges").as_array().push_back(json::object{{"id", graph.at("edges").as_array().size()}, {"source", id(u)}, {"target", id((u + delta) % 12)}, {"weight", 0.5 + (u % 3)}});
  const auto result = invoke(request("pagerank", graph, {{"weight_mode", "edge_weight"}, {"tolerance", 1e-11}}));
  rank_check(result, rank_oracle(graph, true, 0, 0, false, 0.85));
  auto bounded = request("personalized-pagerank", graph, {{"seed_vertices", {id(0)}}, {"weight_mode", "edge_weight"}});
  bounded["budget"] = json::object{{"max_candidates", 10000}};
  rank_check(invoke(bounded), rank_oracle(graph, true, 0, 0, true, 0.85));
}
void similarity() {
  const std::vector<std::string> measures = device == "gpu" ? std::vector<std::string>{"jaccard"} : std::vector<std::string>{"jaccard", "common_neighbors", "adamic_adar", "resource_allocation", "preferential_attachment", "sorensen", "overlap", "cosine"};
  for (unsigned mask = 0; mask < 64; ++mask) {
    const auto graph = fixture(4, false, mask); const auto adjacent = lengths(graph, 4, true);
    int degree[4]{}; for (int u = 0; u < 4; ++u) for (int v = 0; v < 4; ++v) if (u != v && adjacent[u][v] < infinity) ++degree[u];
    for (const auto& measure : measures) for (const bool exclude : {false, true}) {
      const auto output = invoke(request("link-prediction", graph, {{"scoring_measure", measure}, {"exclude_existing_edges", exclude}, {"top_k", 2}}));
      struct Pair { int u, v; double score; }; std::vector<Pair> expected;
      for (int u = 0; u < 4; ++u) for (int v = u + 1; v < 4; ++v) {
        if (exclude && adjacent[u][v] < infinity) continue;
        int common = 0; double aa = 0, ra = 0;
        for (int k = 0; k < 4; ++k) if (k != u && k != v && adjacent[u][k] < infinity && adjacent[v][k] < infinity) { ++common; aa += 1.0 / std::log(degree[k]); ra += 1.0 / degree[k]; }
        double score = 0;
        if (measure == "common_neighbors") score = common;
        else if (measure == "adamic_adar") score = aa;
        else if (measure == "resource_allocation") score = ra;
        else if (measure == "preferential_attachment") score = degree[u] * degree[v];
        else { const double denominator = measure == "jaccard" ? degree[u] + degree[v] - common : measure == "sorensen" ? (degree[u] + degree[v]) / 2.0 : measure == "overlap" ? std::min(degree[u], degree[v]) : std::sqrt(degree[u] * degree[v]); score = denominator ? common / denominator : 0; }
        expected.push_back({u, v, score});
      }
      std::sort(expected.begin(), expected.end(), [](auto a, auto b) { if (a.score != b.score) return a.score > b.score; return a.u != b.u ? a.u < b.u : a.v < b.v; });
      const auto& result = output.at("result").as_object(); const auto& rows = result.at("pairs").as_array();
      check(result.at("candidate_count").to_number<std::size_t>() == expected.size() && rows.size() == std::min<std::size_t>(2, expected.size()), "Wrong link candidate count");
      check(output.at("complete").as_bool() == (rows.size() == expected.size()), "Capped links incorrectly marked complete");
      for (std::size_t i = 0; i < rows.size(); ++i) { const auto& row = rows[i].as_object(); check(index(row.at("source"), 4) == expected[i].u && index(row.at("target"), 4) == expected[i].v && std::abs(row.at("score").to_number<double>() - expected[i].score) < 1e-12, "Local score or ranking disagrees with matrix oracle"); }
    }
  }
}
void contracts() {
  auto graph = fixture(3, true, 0);
  graph.at("edges").as_array() = {json::object{{"id", 0}, {"source", id(0)}, {"target", id(1)}, {"weight", 9007199254740992.0}}, json::object{{"id", 1}, {"source", id(1)}, {"target", id(2)}, {"weight", 1}}};
  if (device == "cpu") {
    const auto output = invoke(request("single-source-shortest-paths", graph, {{"source", id(0)}, {"cutoff", INT64_C(9007199254740993)}}));
    const auto& row = output.at("result").as_object().at("distances").as_array()[2].as_object(); check(row.at("distance").as_int64() == INT64_C(9007199254740993), "Large integral path rounded or cutoff changed");
    for (auto& edge : graph.at("edges").as_array()) edge.as_object()["weight"] = 1e308;
    const auto large = invoke(request("single-source-shortest-paths", graph, {{"source", id(0)}}));
    check(large.at("result").as_object().at("distances").as_array()[2].as_object().at("distance").is_object(), "Reachable overflow was not represented exactly");
  } else invoke(request("single-source-shortest-paths", graph, {{"source", id(0)}}), "unsupported_input");
  graph = fixture(3, true, 1);
  for (const auto& params : {json::object{{"alpha", 1}}, json::object{{"tolerance", 0}}, json::object{{"max_iterations", 0}}, json::object{{"weight_mode", "invented"}}}) invoke(request("pagerank", graph, params), "invalid_input");
  invoke(request("pagerank", graph, {{"max_iterations", 1}, {"tolerance", 1e-14}}), "convergence_failure");
  invoke(request("personalized-pagerank", graph, {{"seed_vertices", json::array{} }}), "invalid_input");
  for (const auto restart : {0.0, -1.0, 1.1}) invoke(request("personalized-pagerank", graph, {{"seed_vertices", {id(0)}}, {"restart_probability", restart}}), "invalid_input");
  const auto direct = invoke(request("pagerank", graph, {{"alpha", 0}})); rank_check(direct, std::vector<long double>(3, 1.0L / 3));
  auto limited = request("pagerank", graph); limited["budget"] = json::object{{"max_candidates", 2}}; invoke(limited, "resource_limit");
  for (const auto op : {"single-source-shortest-paths", "many-source-shortest-paths"}) {
    auto negative = graph; negative.at("edges").as_array()[0].as_object()["weight"] = -1;
    invoke(request(op, negative, std::string(op) == "single-source-shortest-paths" ? json::object{{"source", id(0)}} : json::object{{"weight_mode", "unweighted"}}), "invalid_input");
  }
  invoke(request("spanning-tree-forest", graph), "invalid_input");
  auto empty = fixture(0, false, 0);
  invoke(request("spanning-tree-forest", empty)); invoke(request("connected-components", empty)); invoke(request("pagerank", empty)); invoke(request("link-prediction", empty));
  invoke(request("spanning-tree-forest", empty, {{"require_connected", true}}), "invalid_input");
  auto extremes = fixture(3, false, 0);
  extremes.at("edges").as_array() = {
    json::object{{"id", 0}, {"source", id(0)}, {"target", id(1)}, {"weight", -1e308}},
    json::object{{"id", 1}, {"source", id(1)}, {"target", id(2)}, {"weight", 1e308}},
    json::object{{"id", 2}, {"source", id(0)}, {"target", id(2)}, {"weight", 1e308}},
    json::object{{"id", 3}, {"source", id(0)}, {"target", id(1)}, {"weight", 2.0}}};
  const auto low = invoke(request("spanning-tree-forest", extremes));
  check(low.at("result").as_object().at("total_weight").to_number<int>() == 0, "Minimum forest lost extreme weights");
  const auto high = invoke(request("spanning-tree-forest", extremes, {{"objective", "maximum"}}));
  check(high.at("result").as_object().at("total_weight").is_object(), "Maximum forest total overflowed instead of returning a rational");
  graph = fixture(4, false, 0);
  invoke(request("link-prediction", graph, {{"candidate_pairs", {{id(0), id(0)}}}}), "invalid_input");
  limited = request("link-prediction", graph, {{"top_k", 1}}); limited["budget"] = json::object{{"max_output_items", 2}}; invoke(limited, "resource_limit");
  const auto pairs = invoke(request("link-prediction", graph, {{"candidate_pairs", {{id(0), id(1)}, {id(1), id(0)}}}})); check(pairs.at("result").as_object().at("candidate_count").to_number<int>() == 1, "Pair deduplication failed");
  invoke(request("many-source-shortest-paths", graph, {{"origins", json::array{}}}));
  invoke(request("many-source-shortest-paths", graph, {{"destinations", json::array{}}}));
  if (device == "gpu") {
    invoke(request("link-prediction", graph, {{"scoring_measure", "common_neighbors"}}), "unsupported_input");
    invoke(request("personalized-pagerank", graph, {{"seed_vertices", {id(0)}}, {"dangling_policy", "redistribute_uniformly"}}), "unsupported_input");
    auto auto_request = request("link-prediction", graph, {{"scoring_measure", "common_neighbors"}}); auto_request["device"] = "auto";
    check(invoke(auto_request).at("backend").as_object().at("id") == "cpp", "Unsupported GPU parameters were not routed to C++");
  }
}
}
int main(int argc, char** argv) {
  try {
    const std::string suite = argc > 1 ? argv[1] : "contracts";
    if (argc > 2) device = argv[2]; if (argc > 3) ordinal = std::stoi(argv[3]);
    if (suite == "paths") paths(); else if (suite == "forests") forests(); else if (suite == "connectivity") connectivity();
    else if (suite == "rank") ranks(); else if (suite == "similarity") similarity(); else if (suite == "contracts") contracts(); else throw std::runtime_error("Unknown suite");
    const auto catalog = json::parse(graphmine::runtime::request("{\"command\":\"catalog\"}")).as_object();
    std::cout << json::serialize(json::object{{"suite", suite}, {"backend", device}, {"gpu_device", ordinal}, {"passed_requests", cases}, {"failed", 0}, {"implementation_sha256", catalog.at("implementation_sha256")}}) << '\n';
    return 0;
  } catch (const std::exception& failure) { std::cerr << "Native reference oracle failure after " << cases << " requests: " << failure.what() << '\n'; return 1; }
}
