#include "graphmine/runtime.hpp"
#include "graphmine/runtime_c.h"
#include <boost/json.hpp>
#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace json = boost::json;
namespace {
std::size_t cases = 0;
void check(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}
json::object call(const json::object& request) {
  auto result = json::parse(graphmine::runtime::request(json::serialize(request))).as_object();
  if (result.contains("error")) throw std::runtime_error(json::serialize(result));
  ++cases;
  return result;
}
json::value id(int index) {
  if (index == 0) return 0;
  if (index == 1) return "0";
  return INT64_C(9007199254740991) + index;
}
int index(const json::value& value, int n) {
  for (int i = 0; i < n; ++i) if (value == id(i)) return i;
  throw std::runtime_error("Unknown or coerced ID in result");
}
json::object fixture(int n, bool directed, unsigned mask) {
  json::array vertices, edges;
  for (int v = 0; v < n; ++v) vertices.push_back(json::object{{"id", id(v)}});
  unsigned bit = 0;
  for (int u = 0; u < n; ++u) {
    for (int v = directed ? 0 : u + 1; v < n; ++v) {
      if (mask & (1U << bit)) edges.push_back(json::object{{"id", bit}, {"source", id(u)}, {"target", id(v)}});
      ++bit;
    }
  }
  return {{"graph", {{"id", "native-oracle"}, {"directed", directed}, {"allows_self_loops", true}, {"allows_parallel_edges", true}}},
          {"vertices", vertices}, {"edges", edges}};
}
std::vector<std::vector<int>> floyd(const json::object& graph, int n) {
  std::vector<std::vector<int>> d(n, std::vector<int>(n, 1000));
  for (int v = 0; v < n; ++v) d[v][v] = 0;
  for (const auto& edge : graph.at("edges").as_array()) {
    const int u = index(edge.as_object().at("source"), n), v = index(edge.as_object().at("target"), n);
    d[u][v] = std::min(d[u][v], 1);
    if (!graph.at("graph").as_object().at("directed").as_bool()) d[v][u] = std::min(d[v][u], 1);
  }
  for (int k = 0; k < n; ++k) for (int u = 0; u < n; ++u) for (int v = 0; v < n; ++v)
    d[u][v] = std::min(d[u][v], d[u][k] + d[k][v]);
  return d;
}
void bfs_tests(const std::string& device, int ordinal) {
  for (const bool directed : {true, false}) {
    const int n = directed ? 3 : 4;
    for (unsigned mask = 0; mask < (directed ? 512U : 64U); ++mask) {
      auto graph = fixture(n, directed, mask);
      // Parallel records must not change minimum-hop reachability.
      if (!graph.at("edges").as_array().empty() && mask % 7 == 0) {
        auto extra = graph.at("edges").as_array().front().as_object();
        extra["id"] = "parallel";
        graph.at("edges").as_array().push_back(extra);
      }
      const auto distances = floyd(graph, n);
      for (int depth : {-1, 0, 1, 2}) for (bool nearest : {false, true}) {
        json::array sources{id(0), id(n - 1)};
        json::object params{{"sources", sources}, {"source_mode", nearest ? "nearest_source" : "independent"}, {"depth_limit", depth < 0 ? json::value(nullptr) : json::value(depth)}};
        const auto result = call({{"command", "run"}, {"operation", "breadth-first-search"}, {"graph", graph},
                                  {"parameters", params}, {"device", device}, {"gpu_device", ordinal}});
        check(result.at("backend").as_object().at("device").as_string() == device, "Wrong device used");
        const auto& rows = result.at("result").as_object().at("distances").as_array();
        check(rows.size() == static_cast<std::size_t>(n * (nearest ? 1 : 2)), "Missing BFS rows");
        for (std::size_t i = 0; i < rows.size(); ++i) {
          const auto& row = rows[i].as_object();
          const int v = index(row.at("vertex"), n);
          const int source = nearest ? (distances[0][v] <= distances[n - 1][v] ? 0 : n - 1) : (i < static_cast<std::size_t>(n) ? 0 : n - 1);
          const int want = distances[source][v];
          const bool reachable = want < 1000 && (depth < 0 || want <= depth);
          check(row.at("distance").is_null() != reachable, "Wrong reachable set at mask " + std::to_string(mask));
          if (reachable) {
            check(row.at("distance").as_int64() == want, "BFS/Floyd distance mismatch at mask " + std::to_string(mask));
            check(row.at("source") == id(source), "Wrong nearest source identity");
            if (want) {
              const int parent = index(row.at("predecessor"), n);
              bool edge_exists = false;
              for (const auto& e : graph.at("edges").as_array()) {
                const auto& edge = e.as_object();
                edge_exists |= edge.at("source") == id(parent) && edge.at("target") == id(v);
                if (!directed) edge_exists |= edge.at("source") == id(v) && edge.at("target") == id(parent);
              }
              check(edge_exists && distances[source][parent] == want - 1, "Invalid predecessor witness");
            } else check(row.at("predecessor").is_null(), "A source must have no predecessor");
          } else check(row.at("predecessor").is_null(), "Unreachable vertex has predecessor");
        }
      }
    }
  }
}
void triangle_tests(const std::string& backend, int ordinal) {
  for (unsigned mask = 0; mask < 1024; ++mask) {
    const int n = 5;
    auto graph = fixture(n, false, mask);
    bool adjacent[n][n]{};
    for (const auto& e : graph.at("edges").as_array()) {
      const auto& row = e.as_object();
      const int u = index(row.at("source"), n), v = index(row.at("target"), n);
      adjacent[u][v] = adjacent[v][u] = true;
    }
    std::set<std::set<int>> expected;
    for (int a = 0; a < n; ++a) for (int b = a + 1; b < n; ++b) for (int c = b + 1; c < n; ++c)
      if (adjacent[a][b] && adjacent[a][c] && adjacent[b][c]) expected.insert({a, b, c});
    for (bool enumerate : {false, true}) {
      const auto result = call({{"command", "run"}, {"operation", "triangle-counting"}, {"graph", graph},
                               {"parameters", {{"mode", enumerate ? "enumerate" : "count"}}},
                               {"device", backend == "cpp" ? "cpu" : "gpu"}, {"backend", backend}, {"gpu_device", ordinal}});
      const auto& data = result.at("result").as_object();
      check(data.at("count").to_number<std::uint64_t>() == expected.size(), "Triangle subset-oracle count mismatch");
      if (enumerate) {
        std::set<std::set<int>> observed;
        for (const auto& group : data.at("groups").as_array()) {
          std::set<int> ids;
          for (const auto& v : group.as_object().at("vertices").as_array()) ids.insert(index(v, n));
          observed.insert(ids);
        }
        check(observed == expected && data.at("groups").as_array().size() == expected.size(), "Triangle membership mismatch");
      }
    }
  }
}
void contract_tests() {
  auto graph = fixture(3, false, 7);
  const json::object good{{"command", "run"}, {"operation", "breadth-first-search"}, {"graph", graph},
                          {"parameters", {{"sources", json::array{0}}}}, {"device", "cpu"}};
  auto error = [&](json::object request, const std::string& code) {
    auto response = json::parse(graphmine::runtime::request(json::serialize(request))).as_object();
    check(response.contains("error") && response.at("error").as_object().at("code").as_string() == code, "Unexpected contract result: " + json::serialize(response)); ++cases;
  };
  auto bad = good; bad["extra"] = 1; error(bad, "invalid_input");
  bad = good; bad["parameters"].as_object()["sources"] = json::array{0, 0}; error(bad, "invalid_input");
  bad = good; bad["parameters"].as_object()["sources"] = json::array{true}; error(bad, "invalid_input");
  bad = good; bad["parameters"].as_object()["depth_limit"] = -1; error(bad, "invalid_input");
  bad = good; bad["parameters"].as_object()["return_predecessors"] = "true"; error(bad, "invalid_input");
  bad = good; bad["budget"] = json::object{{"max_candidates", 1}}; error(bad, "resource_limit");
  bad = good; bad["budget"] = json::object{{"max_output_items", 1}}; error(bad, "resource_limit");
  bad = good; bad["budget"] = json::object{{"max_candidates", 0}}; error(bad, "invalid_input");
  bad = good; bad["device"] = "gpu"; bad["backend"] = "cpp"; error(bad, "invalid_input");
  bad = good; bad["operation"] = "not-ported"; error(bad, "unsupported_operation");
  bad = good; bad["graph"].as_object().at("vertices").as_array()[0].as_object()["id"] = 1.0; error(bad, "invalid_input");
  const auto full = call({{"command", "run"}, {"operation", "triangle-counting"}, {"graph", fixture(5, false, 1023)}, {"device", "cpu"}, {"parameters", {{"mode", "enumerate"}, {"result_limit", 2}}}});
  check(full.at("result").as_object().at("count").to_number<int>() == 10 && !full.at("complete").as_bool(), "Truncated enumeration claimed complete");
  check(full.at("ports").as_object().at("count").as_object().at("complete").as_bool(), "Full count lost completeness");
  auto catalog = call({{"command", "catalog"}});
  check(catalog.at("problems").as_array().size() == 71, "Problem inventory drift");
  for (const auto& op : catalog.at("operations").as_array()) {
    bool found = false;
    for (const auto& problem : catalog.at("problems").as_array())
      if (problem.as_object().at("id") == op.as_object().at("problem_id")) found = problem.as_object().at("family") == op.as_object().at("family");
    check(found, "Operation family drift");
  }
  char* output = nullptr; std::size_t size = 0;
  const std::string raw = "{\"command\":\"catalog\"}";
  check(graphmine_runtime_request(raw.data(), raw.size(), &output, &size) == 0 && output && size, "C ABI allocation failed");
  check(json::parse(std::string_view(output, size)) == catalog, "C ABI catalog differs from C++");
  graphmine_runtime_free(output);
  check(graphmine_runtime_request(nullptr, 2, &output, &size) == -1, "Invalid C ABI pointer accepted");
  graphmine_runtime_free(nullptr);
}
}
int main(int argc, char** argv) {
  try {
    const std::string mode = argc > 1 ? argv[1] : "contracts";
    const std::string backend = argc > 2 ? argv[2] : "cpu";
    const int device = argc > 3 ? std::stoi(argv[3]) : 0;
    if (mode == "bfs") bfs_tests(backend, device);
    else if (mode == "triangles") triangle_tests(backend, device);
    else if (mode == "contracts") contract_tests();
    else throw std::runtime_error("Unknown test suite");
    std::cout << json::serialize(json::object{{"suite", mode}, {"backend", backend}, {"gpu_device", device}, {"passed_requests", cases}, {"failed", 0}}) << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Native oracle failure after " << cases << " requests: " << error.what() << '\n'; return 1;
  }
}
