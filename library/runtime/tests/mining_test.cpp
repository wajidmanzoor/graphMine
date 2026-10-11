#include <algorithm>
#include <boost/json.hpp>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include "graphmine/runtime.hpp"

namespace json = boost::json;
namespace {
std::size_t calls = 0;
std::string backend = "cpp";
int device = 0;
void check(bool value, const std::string& message) {
  if (!value) throw std::runtime_error(message);
}
json::value id(int v) {
  return v == 0   ? json::value(0)
         : v == 1 ? json::value("0")
                  : json::value(INT64_C(9007199254740991) + v);
}
int index(const json::value& value, int n) {
  for (int v = 0; v < n; ++v)
    if (id(v) == value) return v;
  throw std::runtime_error("Lost typed ID");
}
struct Fixture {
  int n;
  std::vector<std::vector<bool>> edges;
  json::object graph;
  Fixture(int count, unsigned mask, bool complete = false)
      : n(count), edges(n, std::vector<bool>(n, false)) {
    json::array vertices, records;
    for (int v = 0; v < n; ++v) vertices.push_back(json::object{{"id", id(v)}});
    unsigned bit = 0;
    for (int u = 0; u < n; ++u)
      for (int v = u + 1; v < n; ++v, ++bit)
        if (complete || (bit < 32 && (mask & (1U << bit)))) {
          edges[u][v] = edges[v][u] = true;
          records.push_back(json::object{
              {"id", records.size()}, {"source", id(u)}, {"target", id(v)}, {"weight", -3.5}});
        }
    if (!records.empty() && mask % 7 == 0) {
      auto extra = records.front().as_object();
      extra["id"] = "parallel";
      records.push_back(extra);
    }
    if (n && mask % 11 == 0)
      records.push_back(json::object{{"id", "loop"}, {"source", id(0)}, {"target", id(0)}});
    graph = {{"graph",
              {{"id", "mining-oracle"},
               {"directed", false},
               {"allows_self_loops", true},
               {"allows_parallel_edges", true}}},
             {"vertices", vertices},
             {"edges", records}};
  }
  bool clique(unsigned set, bool complement = false) const {
    for (int u = 0; u < n; ++u)
      if (set & (1U << u))
        for (int v = u + 1; v < n; ++v)
          if ((set & (1U << v)) && edges[u][v] == complement) return false;
    return true;
  }
  unsigned mask(const json::array& values) const {
    unsigned output = 0;
    for (const auto& value : values) {
      const auto v = index(value, n);
      check(!(output & (1U << v)), "Repeated vertex");
      output |= 1U << v;
    }
    return output;
  }
};
json::object request(const char* operation, const Fixture& fixture, json::object args = {}) {
  return {{"command", "run"},       {"operation", operation},
          {"graph", fixture.graph}, {"parameters", args},
          {"backend", backend},     {"device", backend == "cpp" ? "cpu" : "gpu"},
          {"gpu_device", device}};
}
json::object invoke(json::object input, const char* expected_error = nullptr) {
  const auto output = json::parse(graphmine::runtime::request(json::serialize(input))).as_object();
  ++calls;
  if (calls % 500 == 0) std::cerr << "Validated " << calls << " requests with " << backend << '\n';
  if (expected_error) {
    check(output.contains("error") && output.at("error").as_object().at("code") == expected_error,
          "Wrong error: " + json::serialize(output));
    return output;
  }
  check(!output.contains("error"),
        "Request failed: " + json::serialize(input) + " => " + json::serialize(output));
  if (input.at("backend") != "auto")
    check(output.at("backend").as_object().at("id") == input.at("backend"), "Wrong native backend");
  return output;
}
std::set<unsigned> groups(const json::object& output, const Fixture& fixture) {
  std::set<unsigned> values;
  const auto& rows = output.at("result").as_object().at("groups").as_array();
  for (const auto& value : rows) {
    const auto& row = value.as_object();
    const auto set = fixture.mask(row.at("vertices").as_array());
    check(row.at("size").to_number<int>() == __builtin_popcount(set) && values.insert(set).second,
          "Invalid or repeated group");
  }
  return values;
}
void verify(const Fixture& f, const std::string& suite) {
  std::set<unsigned> cliques, maximal, maxima, independent;
  int maximum = 0, alpha = 0;
  for (unsigned set = 1; set < (1U << f.n); ++set) {
    const auto size = __builtin_popcount(set);
    if (f.clique(set)) {
      cliques.insert(set);
      bool extendable = false;
      for (int v = 0; v < f.n; ++v)
        if (!(set & (1U << v))) extendable |= f.clique(set | (1U << v));
      if (!extendable) maximal.insert(set);
      if (size > maximum) {
        maximum = size;
        maxima.clear();
      }
      if (size == maximum) maxima.insert(set);
    }
    if (f.clique(set, true)) {
      if (size > alpha) {
        alpha = size;
        independent.clear();
      }
      if (size == alpha) independent.insert(set);
    }
  }
  if (suite == "maximal")
    for (const auto minimum : {1, 3})
      for (const bool capped : {false, true}) {
        const auto output =
            invoke(request("maximal-cliques", f,
                           {{"minimum_clique_size", minimum},
                            {"result_limit", capped ? json::value(1) : json::value(nullptr)}}));
        std::set<unsigned> expected;
        for (const auto set : maximal)
          if (__builtin_popcount(set) >= minimum) expected.insert(set);
        const auto actual = groups(output, f);
        check(
            actual.size() == (capped ? std::min<std::size_t>(1, expected.size()) : expected.size()),
            "Wrong maximal clique count");
        for (const auto set : actual) check(expected.count(set), "Returned a nonmaximal clique");
        const bool complete = actual.size() == expected.size();
        check(output.at("complete").as_bool() == complete &&
                  output.at("result").as_object().at("count_is_exhaustive").as_bool() == complete,
              "Wrong capped maximal completeness");
      }
  if (suite == "maximum")
    for (const bool ties : {false, true}) {
      const auto output = invoke(request("maximum-clique", f, {{"return_all_ties", ties}}));
      const auto actual = groups(output, f);
      check(output.at("result").as_object().at("maximum_size").to_number<int>() == maximum,
            "Incorrect maximum clique size");
      if (ties)
        check(actual == maxima, "Missing or incorrect tied optima");
      else {
        check(actual.size() == (f.n ? 1U : 0U), "Wrong number of selected optima");
        for (const auto set : actual) check(maxima.count(set), "Clique is not maximum");
      }
    }
  if (suite == "fixed")
    for (unsigned k = backend == "cpp" ? 2 : 3; k <= (backend == "cpp"        ? 7U
                                                      : backend == "graphset" ? 6U
                                                      : backend == "gamma"    ? 7U
                                                                              : 10U);
         ++k)
      for (int mode = 0; mode < 3; ++mode) {
        const auto output =
            invoke(request("k-cliques", f,
                           {{"k", k},
                            {"mode", mode ? "enumerate" : "count"},
                            {"result_limit", mode == 2 ? json::value(1) : json::value(nullptr)}}));
        std::set<unsigned> expected;
        for (const auto set : cliques)
          if (__builtin_popcount(set) == static_cast<int>(k)) expected.insert(set);
        const auto actual = groups(output, f);
        const auto& result = output.at("result").as_object();
        check(result.at("count").to_number<std::size_t>() == expected.size() &&
                  result.at("count_is_exhaustive").as_bool(),
              "Incorrect fixed-size clique count");
        const auto listed = !mode       ? 0
                            : mode == 2 ? std::min<std::size_t>(1, expected.size())
                                        : expected.size();
        check(
            actual.size() == listed && result.at("listed_count").to_number<std::size_t>() == listed,
            "Wrong listed count");
        for (const auto set : actual) check(expected.count(set), "Invalid fixed-size clique");
        check(output.at("ports").as_object().at("groups").as_object().at("complete").as_bool() ==
                  (mode && actual.size() == expected.size()),
              "Incorrect count-only/capped group completeness");
        check(output.at("ports").as_object().at("count").as_object().at("complete").as_bool(),
              "Count port lost completeness");
      }
  if (suite == "core") {
    std::vector<int> expected(f.n, 0);
    for (unsigned set = 1; set < (1U << f.n); ++set) {
      int degree = f.n;
      for (int u = 0; u < f.n; ++u)
        if (set & (1U << u)) {
          int local = 0;
          for (int v = 0; v < f.n; ++v) local += (set & (1U << v)) && f.edges[u][v];
          degree = std::min(degree, local);
        }
      for (int u = 0; u < f.n; ++u)
        if (set & (1U << u)) expected[u] = std::max(expected[u], degree);
    }
    for (const int k : {-1, 0, 2, 5}) {
      const auto output = invoke(
          request("k-core", f, {{"requested_k", k < 0 ? json::value(nullptr) : json::value(k)}}));
      const auto& rows = output.at("result").as_object().at("vertices").as_array();
      check(rows.size() == static_cast<unsigned>(f.n), "Missing core numbers");
      for (const auto& raw : rows) {
        const auto& row = raw.as_object();
        check(row.at("core_number").to_number<int>() == expected[index(row.at("vertex"), f.n)],
              "Core number disagrees with induced-subset oracle");
      }
      if (k >= 0) {
        unsigned wanted = 0;
        for (int v = 0; v < f.n; ++v)
          if (expected[v] >= k) wanted |= 1U << v;
        check(f.mask(output.at("result").as_object().at("selected_vertices").as_array()) == wanted,
              "Wrong k-core selection");
      }
    }
  }
  if (suite == "optimization") {
    const auto output = invoke(request("maximum-independent-set", f));
    const auto& result = output.at("result").as_object();
    const auto selected = f.mask(result.at("vertices").as_array());
    check(__builtin_popcount(selected) == alpha && (f.n ? independent.count(selected) : !selected),
          "Incorrect maximum independent set");
    for (const bool decision : {false, true}) {
      const auto cover = invoke(request("minimum-vertex-cover", f,
                                        {{"mode", decision ? "decision" : "exact"}, {"k", 1}}));
      const auto& data = cover.at("result").as_object();
      const auto vertices = f.mask(data.at("vertices").as_array());
      check(__builtin_popcount(vertices) == f.n - alpha, "Vertex cover is not minimum");
      for (int u = 0; u < f.n; ++u)
        for (int v = u + 1; v < f.n; ++v)
          if (f.edges[u][v]) check(vertices & ((1U << u) | (1U << v)), "Uncovered edge");
      if (decision)
        check(data.at("exists").as_bool() == (f.n - alpha <= 1), "Incorrect cover decision");
    }
  }
}
std::vector<std::string> supported_suites() {
  if (backend == "cpp") return {"maximal", "maximum", "fixed", "core", "optimization"};
  if (backend == "rdmce" || backend == "mce-gpu" || backend == "g2-aimd") return {"maximal"};
  if (backend == "graphset" || backend == "gamma" || backend == "kcgpu") return {"fixed"};
  if (backend == "libcugraph" || backend == "kcore-gpu") return {"core"};
  return {"maximum", "optimization"};
}
void contracts() {
  const Fixture f(5, 513);
  std::vector<std::pair<const char*, json::object>> operations;
  for (const auto& suite : supported_suites()) {
    if (suite == "maximal") operations.push_back({"maximal-cliques", {}});
    if (suite == "maximum") operations.push_back({"maximum-clique", {}});
    if (suite == "fixed") operations.push_back({"k-cliques", {{"k", 3}}});
    if (suite == "core") operations.push_back({"k-core", {}});
    if (suite == "optimization") {
      operations.push_back({"maximum-independent-set", {}});
      operations.push_back({"minimum-vertex-cover", {}});
    }
  }
  for (const auto& [operation, args] : operations) {
    auto directed = request(operation, f, args);
    directed.at("graph").as_object().at("graph").as_object()["directed"] = true;
    invoke(directed, "invalid_input");
    auto unknown = request(operation, f, args);
    unknown.at("parameters").as_object()["unknown"] = 1;
    invoke(unknown, "invalid_input");
    auto candidates = request(operation, f, args);
    candidates["budget"] = {{"max_candidates", 1}};
    invoke(candidates, "resource_limit");
    auto deadline = request(operation, f, args);
    deadline["budget"] = {{"timeout_seconds", 1e-12}};
    invoke(deadline, "resource_limit");
  }
  if (backend != "cpp") return;
  for (const auto& args :
       {json::object{{"minimum_clique_size", 0}}, json::object{{"minimum_clique_size", true}},
        json::object{{"result_limit", 0}}})
    invoke(request("maximal-cliques", f, args), "invalid_input");
  invoke(request("maximum-clique", f, {{"return_all_ties", 1}}), "invalid_input");
  for (const auto& args :
       {json::object{}, json::object{{"k", 1}}, json::object{{"k", 3.0}}, json::object{{"k", true}},
        json::object{{"k", 3}, {"mode", "bad"}}, json::object{{"k", 3}, {"result_limit", -1}}})
    invoke(request("k-cliques", f, args), "invalid_input");
  for (const auto value : {json::value(-1), json::value(true), json::value(2.0)})
    invoke(request("k-core", f, {{"requested_k", value}}), "invalid_input");
  invoke(request("maximum-independent-set", f, {{"mode", "approximate"}}), "invalid_input");
  for (const auto& args : {json::object{{"mode", "decision"}}, json::object{{"k", -1}},
                           json::object{{"mode", "bad"}}, json::object{{"k", true}}})
    invoke(request("minimum-vertex-cover", f, args), "invalid_input");
  for (const auto& [operation, args] : std::vector<std::pair<const char*, json::object>>{
           {"maximal-cliques", {}},
           {"maximum-clique", {{"return_all_ties", true}}},
           {"k-cliques", {{"k", 2}, {"mode", "enumerate"}}},
           {"k-core", {}},
           {"maximum-independent-set", {}},
           {"minimum-vertex-cover", {}}}) {
    auto bounded = request(operation, f, args);
    bounded["budget"] = {{"max_output_items", 1}};
    invoke(bounded, "resource_limit");
  }
}
void boundaries() {
  const auto suites = supported_suites();
  for (const auto& suite : suites) {
    verify(Fixture(12, 0, true), suite);
    for (const auto mask : {0x091ffabU, 0x0de9235U, 0x0830dfeU, 0x05ba853U})
      verify(Fixture(8, mask), suite);
  }
  if (std::find(suites.begin(), suites.end(), "fixed") != suites.end()) {
    const Fixture complete(12, 0, true);
    if (backend == "cpp")
      for (int k = 8; k <= 12; ++k) {
        unsigned expected = 1;
        for (int j = 1; j <= k; ++j) expected = expected * (13 - j) / j;
        const auto value =
            invoke(request("k-cliques", complete, {{"k", k}, {"mode", "enumerate"}}));
        check(value.at("result").as_object().at("count").to_number<unsigned>() == expected,
              "Unbounded CPU clique order");
      }
    const auto empty =
        invoke(request("k-cliques", complete, {{"k", UINT64_MAX}, {"mode", "enumerate"}}));
    check(empty.at("complete").as_bool() && groups(empty, complete).empty(),
          "Huge k empty boundary");
    if (backend != "cpp") {
      invoke(request("k-cliques", complete, {{"k", 2}}), "unsupported_input");
      const auto maximum = backend == "graphset" ? 6 : backend == "gamma" ? 7 : 10;
      invoke(request("k-cliques", complete, {{"k", maximum + 1}}), "unsupported_input");
      auto automatic = request("k-cliques", complete, {{"k", 2}});
      automatic["backend"] = "auto";
      automatic["device"] = "auto";
      const auto fallback = invoke(automatic);
      check(fallback.at("backend").as_object().at("id") == "cpp" &&
                fallback.at("result").as_object().at("count").to_number<int>() == 66,
            "Automatic CPU parameter fallback");
    }
  }
  if (std::find(suites.begin(), suites.end(), "maximal") != suites.end() && backend != "cpp")
    invoke(request("maximal-cliques", Fixture(66, 0, true)), "unsupported_input");
}
}  // namespace
int main(int argc, char** argv) {
  try {
    const std::string suite = argc > 1 ? argv[1] : "maximal";
    if (argc > 2) backend = argv[2];
    if (argc > 3) device = std::stoi(argv[3]);
    check(suite == "maximal" || suite == "maximum" || suite == "fixed" || suite == "core" ||
              suite == "optimization" || suite == "contracts" || suite == "boundaries",
          "Unknown suite");
    if (suite == "contracts")
      contracts();
    else if (suite == "boundaries")
      boundaries();
    else {
      const int n = backend == "cpp" ? 5 : 4;
      for (unsigned mask = 0; mask < (1U << (n * (n - 1) / 2)); ++mask)
        verify(Fixture(n, mask), suite);
      for (int size : {0, 1}) verify(Fixture(size, 0), suite);
    }
    const auto catalog =
        json::parse(graphmine::runtime::request("{\"command\":\"catalog\"}")).as_object();
    std::cout << json::serialize(
                     json::object{{"suite", suite},
                                  {"backend", backend},
                                  {"gpu_device", device},
                                  {"passed_requests", calls},
                                  {"failed", 0},
                                  {"implementation_sha256", catalog.at("implementation_sha256")}})
              << '\n';
    return 0;
  } catch (const std::exception& failure) {
    std::cerr << "Mining oracle failed after " << calls << " requests: " << failure.what() << '\n';
    return 1;
  }
}
