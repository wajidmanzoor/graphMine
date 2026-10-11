#include <algorithm>
#include <boost/json.hpp>
#include <boost/multiprecision/cpp_int.hpp>
#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include "graphmine/runtime.hpp"

namespace json = boost::json;
using Exact = boost::multiprecision::cpp_rational;
using Integer = boost::multiprecision::cpp_int;
namespace {
std::size_t calls = 0;
std::string backend = "cpp";
int device = 0;
void check(bool ok, const std::string& message) {
  if (!ok) throw std::runtime_error(message);
}
json::value vid(int v) {
  return v == 0   ? json::value(0)
         : v == 1 ? json::value("0")
                  : json::value(INT64_C(9007199254740991) + v);
}
json::value eid(int e) {
  return e == 0   ? json::value(0)
         : e == 1 ? json::value("0")
                  : json::value("edge-" + std::to_string(e));
}
struct Fixture {
  int n, left;
  json::object graph;
  Fixture(int count, int split, unsigned mask, unsigned base = 2) : n(count), left(split) {
    json::array vertices, edges;
    const auto initial = mask;
    for (int v = 0; v < n; ++v) {
      json::object row{{"id", vid(v)}};
      if (left >= 0) row["attributes"] = json::object{{"side", v < left ? "left" : "right"}};
      vertices.push_back(row);
    }
    for (int u = 0; u < (left < 0 ? n : left); ++u)
      for (int v = left < 0 ? u + 1 : left; v < n; ++v) {
        const auto digit = mask % base;
        mask /= base;
        if (!digit) continue;
        double weight = base > 2 ? (digit == 1   ? 0
                                    : digit == 2 ? 0.5
                                                 : 2)
                                 : ((u * 7 + v * 5 + initial) % 11) * 0.5;
        if (left >= 0 && (u + v + initial) % 3 == 0) weight = -weight;
        edges.push_back(json::object{
            {"id", eid(edges.size())}, {"source", vid(u)}, {"target", vid(v)}, {"weight", weight}});
      }
    if (!edges.empty() && initial % 7 == 0) {
      auto duplicate = edges.front().as_object();
      duplicate["id"] = "parallel";
      duplicate["weight"] = duplicate.at("weight").to_number<double>() + 1;
      std::swap(duplicate.at("source"), duplicate.at("target"));
      edges.push_back(duplicate);
    }
    if (n && left < 0 && initial % 11 == 0)
      edges.push_back(
          json::object{{"id", "loop"}, {"source", vid(0)}, {"target", vid(0)}, {"weight", 100}});
    graph = {{"graph",
              {{"id", "matching-oracle"},
               {"directed", false},
               {"allows_self_loops", true},
               {"allows_parallel_edges", true}}},
             {"vertices", vertices},
             {"edges", edges}};
  }
  int vertex(const json::value& id) const {
    for (int v = 0; v < n; ++v)
      if (vid(v) == id) return v;
    throw std::runtime_error("Lost typed vertex ID");
  }
};
json::object request(const Fixture& f, json::object args) {
  return {{"command", "run"},
          {"operation", f.left < 0 ? "weighted-matching" : "bipartite-matching"},
          {"graph", f.graph},
          {"parameters", args},
          {"device", backend == "cpp" ? "cpu" : "gpu"},
          {"backend", backend},
          {"gpu_device", device}};
}
json::object invoke(json::object input, const char* error = nullptr) {
  const auto result = json::parse(graphmine::runtime::request(json::serialize(input))).as_object();
  ++calls;
  if (calls % 500 == 0) std::cerr << "Validated " << calls << " matching requests\n";
  if (error) {
    check(result.contains("error") && result.at("error").as_object().at("code") == error,
          "Wrong rejection: " + json::serialize(result));
    return result;
  }
  check(!result.contains("error"), "Native failure: " + json::serialize(result));
  return result;
}
Exact exact(const json::object& row, const char* key) {
  const auto& value = row.at(std::string(key) + "_exact").as_object();
  return Exact(Integer(std::string(value.at("numerator").as_string()))) /
         Integer(std::string(value.at("denominator").as_string()));
}
struct Answer {
  bool feasible = false;
  Exact value = 0;
  int size = 0;
};
void verify(const Fixture& f, const std::string& objective, bool perfect,
            const char* quality = "exact") {
  const bool cardinality = objective == "maximum_cardinality",
             minimum = objective == "minimum_cost";
  std::vector<std::vector<std::optional<Exact>>> weight(f.n,
                                                        std::vector<std::optional<Exact>>(f.n));
  std::map<std::pair<int, int>, json::value> original;
  for (const auto& raw : f.graph.at("edges").as_array()) {
    const auto& row = raw.as_object();
    const auto u = f.vertex(row.at("source")), v = f.vertex(row.at("target"));
    if (u == v) continue;
    const Exact value = cardinality ? Exact(1) : Exact(row.at("weight").to_number<double>());
    if (!weight[u][v] || (minimum ? value < *weight[u][v] : value > *weight[u][v])) {
      weight[u][v] = weight[v][u] = value;
      original[std::minmax(u, v)] = row.at("id");
    }
  }
  // Subset dynamic programming branches on the first available vertex. It
  // neither contracts odd cycles nor runs augmenting paths or residual costs.
  std::map<std::pair<unsigned, int>, Answer> memo;
  std::function<Answer(unsigned, int)> solve = [&](unsigned available, int needed) -> Answer {
    if (needed == 0 || !available) return {needed <= 0, 0, 0};
    const auto key = std::make_pair(available, needed);
    if (memo.count(key)) return memo.at(key);
    const int u = __builtin_ctz(available);
    const auto rest = available & ~(1U << u);
    Answer best = solve(rest, needed);
    for (int v = u + 1; v < f.n; ++v)
      if ((rest & (1U << v)) && weight[u][v]) {
        auto candidate = solve(rest & ~(1U << v), needed < 0 ? -1 : needed - 1);
        if (!candidate.feasible) continue;
        candidate.value += *weight[u][v];
        ++candidate.size;
        if (!best.feasible ||
            (minimum ? candidate.value < best.value : candidate.value > best.value))
          best = candidate;
      }
    memo[key] = best;
    return best;
  };
  const auto target = perfect ? std::min(f.left, f.n - f.left) : -1;
  const auto expected = solve((1U << f.n) - 1, target);
  json::object args{{"solution_quality", quality}};
  if (f.left >= 0) {
    args["objective"] = objective;
    args["weight_mode"] = cardinality ? "unweighted" : "edge_weight";
    args["perfect_matching_required"] = perfect;
  }
  const auto output = invoke(request(f, args));
  const auto& result = output.at("result").as_object();
  check(result.at("feasible").as_bool() == expected.feasible, "Wrong coverage feasibility");
  if (!expected.feasible) {
    check(result.at("infeasibility_certified").as_bool() && !result.at("optimal").as_bool(),
          "Infeasibility disguised as optimal matching");
    check(result.at("matching_edges").as_array().empty() &&
              result.at("objective_value").is_null() && output.at("ports").as_object().empty(),
          "Infeasible matching leaked a witness");
    return;
  }
  check(result.at("optimal").as_bool() && exact(result, "objective_value") == expected.value,
        "Objective differs from exact subset optimum");
  const auto& rows = result.at("edges").as_array();
  check(rows.size() == result.at("matching_size").to_number<std::size_t>(),
        "Incorrect matching size");
  if (perfect) check(rows.size() == static_cast<std::size_t>(target), "Missing required coverage");
  unsigned used = 0;
  Exact sum = 0;
  json::array ids;
  for (const auto& raw : rows) {
    const auto& row = raw.as_object();
    const auto u = f.vertex(row.at("source")), v = f.vertex(row.at("target"));
    check(u != v && !(used & ((1U << u) | (1U << v))) && weight[u][v],
          "Invalid matching endpoints");
    used |= (1U << u) | (1U << v);
    check(row.at("id") == original.at(std::minmax(u, v)), "Lost best parallel edge identity");
    if (f.left >= 0) check(u < f.left && v >= f.left, "Matching orientation must be left-to-right");
    check(exact(row, "weight") == *weight[u][v], "Wrong selected weight");
    sum += *weight[u][v];
    ids.push_back(row.at("id"));
  }
  check(sum == expected.value && ids == result.at("matching_edges"),
        "Objective/ID output does not match its witness");
  check(output.at("ports").as_object().at("edges").as_object().at("value") == rows &&
            output.at("quality") == "exact",
        "Incomplete or approximate exact result");
  if (f.left >= 0)
    for (const auto side : {"unmatched_left_vertices", "unmatched_right_vertices"}) {
      unsigned unmatched = 0;
      for (const auto& value : result.at(side).as_array()) {
        const auto v = f.vertex(value);
        check(!(unmatched & (1U << v)), "Duplicate unmatched ID");
        unmatched |= 1U << v;
      }
      unsigned desired = 0;
      for (int v = 0; v < f.n; ++v)
        if (!(used & (1U << v)) &&
            ((v < f.left) == (std::string(side) == "unmatched_left_vertices")))
          desired |= 1U << v;
      check(unmatched == desired, "Incorrect unmatched vertices");
    }
}
void contracts() {
  for (const int split : {-1, 2}) {
    const Fixture f(4, split, 63);
    json::object args;
    if (split >= 0) args = {{"objective", "maximum_weight"}, {"weight_mode", "edge_weight"}};
    auto input = request(f, args);
    input.at("parameters").as_object()["unknown"] = true;
    invoke(input, "invalid_input");
    input = request(f, args);
    input.at("graph").as_object().at("graph").as_object()["directed"] = true;
    invoke(input, "invalid_input");
    input = request(f, args);
    input.at("graph").as_object().at("edges").as_array()[0].as_object().erase("weight");
    invoke(input, "invalid_input");
    input = request(f, args);
    input.at("parameters").as_object()["solution_quality"] = "unproved";
    invoke(input, "invalid_input");
    for (const auto key : {"max_candidates", "max_output_items"}) {
      input = request(f, args);
      input["budget"] = json::object{{key, 1}};
      invoke(input, "resource_limit");
    }
    input = request(f, args);
    input["budget"] = json::object{{"timeout_seconds", 1e-12}};
    invoke(input, "resource_limit");
    if (split < 0) {
      input = request(f, args);
      input.at("graph").as_object().at("edges").as_array()[0].as_object()["weight"] = -1;
      invoke(input, "invalid_input");
    } else {
      input = request(f, args);
      input.at("graph").as_object().at("vertices").as_array()[0].as_object().erase("attributes");
      invoke(input, "invalid_input");
      input = request(f, args);
      input.at("graph").as_object().at("edges").as_array()[0].as_object()["target"] = vid(1);
      invoke(input, "invalid_input");
      input = request(f, args);
      input.at("parameters").as_object()["weight_mode"] = "unweighted";
      invoke(input, "invalid_input");
      input = request(f, args);
      input.at("parameters").as_object()["perfect_matching_required"] = 1;
      invoke(input, "invalid_input");
    }
  }
}
Fixture square(int size, unsigned code, unsigned base = 2) {
  Fixture f(2 * size, size, 0);
  json::array edges;
  for (int u = 0; u < size; ++u)
    for (int v = 0; v < size; ++v) {
      const auto cost = code % base;
      code /= base;
      edges.push_back(json::object{{"id", eid(edges.size())},
                                   {"source", vid(u)},
                                   {"target", vid(size + v)},
                                   {"weight", cost}});
    }
  f.graph["edges"] = edges;
  return f;
}
json::object gpu_request(const Fixture& f) {
  return request(f, {{"objective", "minimum_cost"},
                     {"weight_mode", "edge_weight"},
                     {"perfect_matching_required", true}});
}
void gpu_contracts() {
  auto f = square(2, 3);
  auto input = gpu_request(f);
  input.at("graph").as_object().at("graph").as_object()["directed"] = true;
  invoke(input, "invalid_input");
  input = gpu_request(f);
  input.at("graph").as_object().at("edges").as_array()[0].as_object().erase("weight");
  invoke(input, "invalid_input");
  for (const auto key :
       {"unknown", "weight_mode", "solution_quality", "perfect_matching_required"}) {
    input = gpu_request(f);
    input.at("parameters").as_object()[key] = 17;
    invoke(input, "invalid_input");
  }
  for (const auto key : {"max_candidates", "max_output_items"}) {
    input = gpu_request(f);
    input["budget"] = json::object{{key, 1}};
    invoke(input, "resource_limit");
  }
  input = gpu_request(f);
  input["budget"] = json::object{{"timeout_seconds", 1e-12}};
  invoke(input, "resource_limit");
}
void gpu_boundaries() {
  verify(square(0, 0), "minimum_cost", true);
  verify(square(1, 0), "minimum_cost", true);
  verify(square(1, 999, 1000), "minimum_cost", true);
  auto f = square(2, 3);
  for (const auto cost : {-1.0, 0.5, 1000.0}) {
    auto copy = f;
    copy.graph.at("edges").as_array()[0].as_object()["weight"] = cost;
    auto input = gpu_request(copy);
    invoke(input, "unsupported_input");
    input["device"] = "auto";
    input["backend"] = "auto";
    check(invoke(input).at("backend").as_object().at("id") == "cpp",
          "Unsupported assignment cost was not routed to CPU");
  }
  for (unsigned kind = 0; kind < 3; ++kind) {
    auto input = gpu_request(f);
    if (kind == 0) input.at("parameters").as_object()["objective"] = "maximum_weight";
    if (kind == 1) input.at("parameters").as_object()["perfect_matching_required"] = false;
    if (kind == 2) input.at("graph").as_object().at("edges").as_array().pop_back();
    invoke(input, "unsupported_input");
    input["device"] = "auto";
    input["backend"] = "auto";
    check(invoke(input).at("backend").as_object().at("id") == "cpp",
          "Unsupported assignment variant was not routed to CPU");
  }
  Fixture unequal(3, 1, 3);
  invoke(gpu_request(unequal), "unsupported_input");
  invoke(gpu_request(square(65, 0)), "unsupported_input");
  for (const unsigned size : {63, 64})
    for (bool constant : {false, true}) {
      auto large = square(size, 0);
      auto& edges = large.graph.at("edges").as_array();
      for (unsigned i = 0; i < edges.size(); ++i)
        edges[i].as_object()["weight"] =
            constant ? 999 : (i % size == (i / size + 1) % size ? 0 : 999);
      auto input = gpu_request(large);
      input["budget"] = json::object{{"max_candidates", 100000000}};
      const auto output = invoke(input);
      const auto& result = output.at("result").as_object();
      check(result.at("matching_size").to_number<unsigned>() == size &&
                exact(result, "objective_value") == Exact(constant ? 999 * size : 0),
            "Large assignment optimum is incorrect");
      std::set<unsigned> used_left, used_right;
      for (const auto& raw : result.at("edges").as_array()) {
        const auto& row = raw.as_object();
        check(used_left.insert(large.vertex(row.at("source"))).second &&
                  used_right.insert(large.vertex(row.at("target"))).second,
              "Large assignment repeats an endpoint");
      }
      check(used_left.size() == size && used_right.size() == size,
            "Large assignment is incomplete");
    }
}
void boundaries() {
  for (const int n : {0, 1, 2}) {
    verify(Fixture(n, -1, 0), "maximum_weight", false);
    for (int left = 0; left <= n; ++left)
      for (bool perfect : {false, true}) verify(Fixture(n, left, 0), "minimum_cost", perfect);
  }
  for (const int split : {-1, 2})
    for (const auto weights :
         {std::vector<double>{9007199254740992.0, 9007199254740992.0, 1, 2},
          std::vector<double>{1e308, 1e308, 1e308, 5e307},
          std::vector<double>{std::numeric_limits<double>::denorm_min(), 1e308, 1e308,
                              std::numeric_limits<double>::denorm_min()}}) {
      Fixture f(4, split, 0);
      json::array edges;
      for (int i = 0; i < 4; ++i)
        edges.push_back(json::object{{"id", eid(i)},
                                     {"source", vid(i / 2)},
                                     {"target", vid(2 + i % 2)},
                                     {"weight", weights[i]}});
      f.graph["edges"] = edges;
      verify(f, "maximum_weight", false, "approximate");
      if (split >= 0) {
        verify(f, "minimum_cost", true);
        verify(f, "minimum_cost", false);
      }
    }
  // Odd cycles and overlapping blossoms with deterministic varied weights.
  std::uint64_t state = 91;
  for (unsigned trial = 0; trial < 128; ++trial) {
    Fixture f(10, -1, 0);
    json::array edges;
    for (int u = 0; u < 10; ++u)
      for (int v = u + 1; v < 10; ++v) {
        state = state * UINT64_C(6364136223846793005) + 1;
        if ((state >> 60) < 9)
          edges.push_back(json::object{{"id", eid(edges.size())},
                                       {"source", vid(u)},
                                       {"target", vid(v)},
                                       {"weight", static_cast<double>((state >> 52) % 100) / 8}});
      }
    f.graph["edges"] = edges;
    verify(f, "maximum_weight", false);
  }
}
}  // namespace
int main(int argc, char** argv) {
  try {
    const std::string suite = argc > 1 ? argv[1] : "general";
    backend = argc > 2 ? argv[2] : "cpp";
    device = argc > 3 ? std::stoi(argv[3]) : 0;
    if (suite == "contracts") {
      if (backend == "cpp")
        contracts();
      else
        gpu_contracts();
    } else if (suite == "boundaries") {
      if (backend == "cpp")
        boundaries();
      else
        gpu_boundaries();
    } else if (suite == "general") {
      for (unsigned mask = 0; mask < 1024; ++mask)
        verify(Fixture(5, -1, mask), "maximum_weight", false);
      for (unsigned mask = 0; mask < 4096; ++mask)
        verify(Fixture(4, -1, mask, 4), "maximum_weight", false);
    } else if (suite == "assignment") {
      for (unsigned code = 0; code < 512; ++code) verify(square(3, code), "minimum_cost", true);
      for (unsigned code = 0; code < 81; ++code) verify(square(2, code, 3), "minimum_cost", true);
      for (unsigned trial = 0; trial < 128; ++trial) {
        auto f = square(4, 0);
        unsigned state = trial + 41;
        for (auto& raw : f.graph.at("edges").as_array()) {
          state = state * 1664525U + 1013904223U;
          raw.as_object()["weight"] = (state >> 16) % 1000;
        }
        verify(f, "minimum_cost", true);
      }
    } else if (suite == "bipartite") {
      for (unsigned mask = 0; mask < 512; ++mask)
        for (const auto objective : {"maximum_cardinality", "maximum_weight", "minimum_cost"})
          for (bool perfect : {false, true}) verify(Fixture(6, 3, mask), objective, perfect);
      for (unsigned mask = 0; mask < 729; ++mask)
        for (const auto objective : {"maximum_cardinality", "maximum_weight", "minimum_cost"})
          for (bool perfect : {false, true}) verify(Fixture(5, 2, mask, 3), objective, perfect);
    } else
      throw std::runtime_error("Unknown matching suite");
    const auto catalog =
        json::parse(graphmine::runtime::request("{\"command\":\"catalog\"}")).as_object();
    std::cout << json::serialize(json::object{
                     {"suite", suite},
                     {"backend", backend},
                     {"gpu_device", backend == "cpp" ? json::value(nullptr) : json::value(device)},
                     {"passed_requests", calls},
                     {"failed", 0},
                     {"implementation_sha256", catalog.at("implementation_sha256")}})
              << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Matching oracle failed after " << calls << " requests: " << error.what() << '\n';
    return 1;
  }
}
