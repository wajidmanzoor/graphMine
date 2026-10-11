#pragma once

#include <algorithm>
#include <charconv>
#include <map>
#include <numeric>
#include <set>

#include "exact_number.hpp"

namespace graphmine::runtime::family_util {
using Vertices = std::vector<VertexIndex>;
inline std::string choice(const json::object& args, const char* key, const char* initial,
                          std::initializer_list<std::string_view> choices) {
  const auto value = args.contains(key) ? string(args.at(key), key) : std::string(initial);
  require(std::find(choices.begin(), choices.end(), value) != choices.end(),
          std::string("Invalid ") + key);
  return value;
}
inline std::uint64_t natural(const json::object& args, const char* key, std::uint64_t initial,
                             std::uint64_t minimum = 0) {
  const auto value = args.contains(key) ? uint(args.at(key), key) : initial;
  require(value >= minimum, std::string(key) + " is below its minimum");
  return value;
}
inline std::optional<std::uint64_t> limit(const json::object& args,
                                          const char* key = "result_limit",
                                          std::uint64_t minimum = 1) {
  if (!args.contains(key) || args.at(key).is_null()) return {};
  return natural(args, key, 0, minimum);
}
inline Vertices vertices(const Graph& graph, const json::value& value, const char* context,
                         bool duplicates = false) {
  require(value.is_array(), std::string(context) + " must be an array");
  Vertices output;
  std::set<VertexIndex> seen;
  for (const auto& id : value.as_array()) {
    const auto v = graph.dense_index(external_id(id));
    require(duplicates || seen.insert(v).second, std::string(context) + " contains duplicate IDs");
    output.push_back(v);
  }
  return output;
}
inline json::array ids(const Graph& graph, const Vertices& vertices) {
  json::array output;
  for (const auto v : vertices) output.push_back(id_json(graph.external_id(v)));
  return output;
}
inline Vertices all_vertices(const Graph& graph) {
  Vertices output(graph.vertex_count());
  std::iota(output.begin(), output.end(), 0);
  return output;
}
inline std::vector<json::value> vertex_values(const Graph& graph, const json::value& input,
                                              const char* context) {
  require(input.is_array(), std::string(context) + " must contain {vertex,value} rows");
  std::vector<json::value> result(graph.vertex_count());
  std::vector<bool> seen(graph.vertex_count(), false);
  for (const auto& raw : input.as_array()) {
    const auto row = object(raw, context);
    fields(row, {"vertex", "value"}, {"vertex", "value"});
    const auto v = graph.dense_index(external_id(row.at("vertex")));
    require(!seen[v], std::string(context) + " repeats a vertex");
    result[v] = row.at("value");
    seen[v] = true;
  }
  require(std::all_of(seen.begin(), seen.end(), [](bool v) { return v; }),
          std::string(context) + " must cover every vertex");
  return result;
}
// Restricted-growth strings enumerate each unlabeled partition exactly once.
template <class Emit>
void partitions(std::size_t n, std::size_t minimum, std::size_t maximum, Work& work, Emit emit) {
  if (n == 0) {
    if (minimum == 0) emit(std::vector<std::size_t>{});
    return;
  }
  if (!maximum || minimum > n) return;
  work.tick(3 * n);
  std::vector<std::size_t> values(n), next(n, 0), used(n + 1, 0);
  std::size_t depth = 0;
  for (;;) {
    work.tick();
    if (depth == n) {
      if (used[n] >= minimum) emit(values);
      --depth;
      continue;
    }
    const auto bound = std::min(maximum - 1, used[depth]);
    if (next[depth] > bound || used[depth] + n - depth < minimum) {
      next[depth] = 0;
      if (!depth) break;
      --depth;
      continue;
    }
    values[depth] = next[depth]++;
    used[depth + 1] = std::max(used[depth], values[depth] + 1);
    ++depth;
    if (depth < n) next[depth] = 0;
  }
}
template <class Emit, class Allow>
bool injective_assignments(std::size_t domain, std::size_t range, Work& work, Emit emit,
                           Allow allow) {
  if (domain > range) return true;
  if (!domain) return emit(Vertices{});
  work.tick(domain + range);
  Vertices chosen;
  std::vector<std::size_t> next(domain, 0);
  std::vector<bool> used(range, false);
  std::size_t depth = 0;
  for (;;) {
    work.tick();
    if (depth == domain) {
      if (!emit(chosen)) return false;
      --depth;
      used[chosen.back()] = false;
      chosen.pop_back();
      continue;
    }
    if (next[depth] == range) {
      next[depth] = 0;
      if (!depth) break;
      --depth;
      used[chosen.back()] = false;
      chosen.pop_back();
      continue;
    }
    const auto candidate = next[depth]++;
    if (used[candidate] || !allow(chosen, candidate)) continue;
    used[candidate] = true;
    chosen.push_back(candidate);
    ++depth;
    if (depth < domain) next[depth] = 0;
  }
  return true;
}
// Iterative combinations have no fixed vertex-count mask or recursive stack limit.
// Returning false from the callback stops only when the caller declares truncation.
template <class Emit>
bool combinations(std::size_t n, std::size_t k, Work& work, Emit emit) {
  if (k > n) return true;
  work.tick(k);
  Vertices selected(k);
  std::iota(selected.begin(), selected.end(), 0);
  for (;;) {
    work.tick();
    if (!emit(selected)) return false;
    std::size_t i = k;
    while (i && selected[i - 1] == n - k + i - 1) --i;
    if (!i) return true;
    ++selected[i - 1];
    for (std::size_t j = i; j < k; ++j) selected[j] = selected[j - 1] + 1;
  }
}
inline bool adjacent(const MiningGraph& graph, VertexIndex u, VertexIndex v) {
  return std::binary_search(graph[u].begin(), graph[u].end(), v);
}
inline bool clique(const MiningGraph& graph, const Vertices& selected, Work& work) {
  for (std::size_t i = 0; i < selected.size(); ++i)
    for (std::size_t j = i + 1; j < selected.size(); ++j) {
      work.tick();
      if (!adjacent(graph, selected[i], selected[j])) return false;
    }
  return true;
}
template <class Emit>
bool each_clique(const MiningGraph& graph, std::size_t minimum, std::size_t maximum, Work& work,
                 Emit emit) {
  if (!maximum) return true;
  struct Frame {
    Vertices candidates;
    std::size_t next = 0;
  };
  Vertices all(graph.size()), selected;
  std::iota(all.begin(), all.end(), 0);
  std::vector<Frame> stack{{std::move(all), 0}};
  while (!stack.empty()) {
    work.tick();
    auto& frame = stack.back();
    if (frame.next == frame.candidates.size()) {
      stack.pop_back();
      if (!selected.empty()) selected.pop_back();
      continue;
    }
    const auto v = frame.candidates[frame.next++];
    selected.push_back(v);
    if (selected.size() >= minimum && !emit(selected)) return false;
    Vertices next;
    if (selected.size() < maximum) {
      work.tick(frame.candidates.size() - frame.next + graph[v].size());
      std::set_intersection(frame.candidates.begin() + frame.next, frame.candidates.end(),
                            graph[v].begin(), graph[v].end(), std::back_inserter(next));
    }
    stack.push_back({std::move(next), 0});
  }
  return true;
}
struct Edge {
  VertexIndex u, v;
  Exact weight;
  std::size_t original;
};
inline std::vector<Edge> edges(const Graph& graph, bool weighted, Work& work,
                               bool nonnegative = true, bool loops = false) {
  std::map<std::pair<VertexIndex, VertexIndex>, Edge> normalized;
  for (std::size_t i = 0; i < graph.edge_count(); ++i) {
    work.tick();
    const auto& raw = graph.canonical().edges[i];
    auto u = graph.dense_index(raw.source), v = graph.dense_index(raw.target);
    Exact weight = weighted ? Exact(raw.weight.value_or(1)) : Exact(1);
    require(!nonnegative || weight >= 0, "Weights must be nonnegative");
    if (u == v && !loops) continue;
    if (!graph.directed() && u > v) std::swap(u, v);
    auto [it, inserted] = normalized.emplace(std::make_pair(u, v), Edge{u, v, weight, i});
    if (!inserted && weighted) it->second.weight += weight;
  }
  std::vector<Edge> output;
  for (auto& entry : normalized) output.push_back(std::move(entry.second));
  return output;
}
inline json::object output(json::object args, json::object data, json::object ports,
                           bool complete = true, const char* quality = "exact") {
  return {{"parameters", args},
          {"result", data},
          {"ports", ports},
          {"complete", complete},
          {"quality", quality}};
}
// Quasi-clique thresholds use the shortest decimal spelling, rather than the
// binary approximation of gamma: ceil(0.14 * 50) is exactly seven.
inline Exact decimal_number(const json::value& value, const char* context) {
  if (!value.is_double()) return exact_number(value, context);
  char buffer[128];
  const auto converted = std::to_chars(buffer, buffer + sizeof(buffer), number(value, context));
  require(converted.ec == std::errc(), "Cannot represent decimal parameter");
  std::string digits(buffer, converted.ptr);
  const auto exponent_at = digits.find_first_of("eE");
  int exponent = 0;
  if (exponent_at != std::string::npos) {
    exponent = std::stoi(digits.substr(exponent_at + 1));
    digits.resize(exponent_at);
  }
  const auto point = digits.find('.');
  if (point != std::string::npos) {
    exponent -= digits.size() - point - 1;
    digits.erase(point, 1);
  }
  bool negative = !digits.empty() && digits.front() == '-';
  if (negative) digits.erase(0, 1);
  Integer numerator = 0;
  for (char digit : digits) numerator = numerator * 10 + (digit - '0');
  Exact result(negative ? -numerator : numerator);
  while (exponent > 0) {
    result *= 10;
    --exponent;
  }
  while (exponent < 0) {
    result /= 10;
    ++exponent;
  }
  return result;
}
}  // namespace graphmine::runtime::family_util
