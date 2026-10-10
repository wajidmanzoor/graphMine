#pragma once

#include "exact_number.hpp"
#include <algorithm>
#include <queue>

namespace graphmine::runtime {
// Exact Dinic residual network. DFS uses explicit stacks so long paths do not
// consume the host call stack. Every traversal participates in Work budgets.
class ExactFlow {
 public:
  struct Edge { std::size_t to, reverse; Exact capacity, initial; };
  std::vector<std::vector<Edge>> rows;
  explicit ExactFlow(std::size_t size) : rows(size) {}
  std::size_t add(std::size_t u, std::size_t v, const Exact& capacity) {
    require(u != v && capacity >= 0, "Invalid residual edge");
    const auto index = rows[u].size();
    rows[u].push_back({v, rows[v].size(), capacity, capacity});
    rows[v].push_back({u, index, 0, 0}); return index;
  }
  void set_flow(std::size_t u, std::size_t index, const Exact& amount) {
    auto& edge = rows[u][index];
    if (amount < 0 || amount > edge.initial) throw Failure("correctness_mismatch", "CUDA flow violates capacity");
    edge.capacity = edge.initial - amount; rows[edge.to][edge.reverse].capacity = amount;
  }
  Exact solve(std::size_t source, std::size_t sink, Work& work) {
    Exact total = 0;
    while (true) {
      work.tick(rows.size()); std::vector<std::int64_t> level(rows.size(), -1);
      std::queue<std::size_t> queue; queue.push(source); level[source] = 0;
      while (!queue.empty()) {
        const auto u = queue.front(); queue.pop();
        for (const auto& edge : rows[u]) { work.tick(); if (edge.capacity > 0 && level[edge.to] < 0) { level[edge.to] = level[u] + 1; queue.push(edge.to); } }
      }
      if (level[sink] < 0) break;
      std::vector<std::size_t> next(rows.size(), 0);
      while (true) {
        std::vector<std::size_t> vertices{source}; std::vector<std::pair<std::size_t, std::size_t>> path;
        while (!vertices.empty() && vertices.back() != sink) {
          work.tick(); const auto u = vertices.back();
          while (next[u] < rows[u].size()) {
            work.tick(); const auto& edge = rows[u][next[u]];
            if (edge.capacity > 0 && level[edge.to] == level[u] + 1) break;
            ++next[u];
          }
          if (next[u] == rows[u].size()) {
            level[u] = -1; vertices.pop_back();
            if (!path.empty()) { ++next[path.back().first]; path.pop_back(); }
          } else { path.emplace_back(u, next[u]); vertices.push_back(rows[u][next[u]].to); }
        }
        if (vertices.empty()) break;
        Exact amount = rows[path.front().first][path.front().second].capacity;
        for (const auto& [u, i] : path) { work.tick(); amount = std::min(amount, rows[u][i].capacity); }
        for (const auto& [u, i] : path) { work.tick(); auto& edge = rows[u][i]; edge.capacity -= amount; rows[edge.to][edge.reverse].capacity += amount; }
        total += amount;
      }
    }
    return total;
  }
  std::vector<bool> reachable(std::size_t source, Work& work) const {
    work.tick(rows.size()); std::vector<bool> seen(rows.size(), false); seen[source] = true;
    std::queue<std::size_t> queue; queue.push(source);
    while (!queue.empty()) {
      const auto u = queue.front(); queue.pop();
      for (const auto& edge : rows[u]) { work.tick(); if (edge.capacity > 0 && !seen[edge.to]) { seen[edge.to] = true; queue.push(edge.to); } }
    }
    return seen;
  }
  Exact flow(std::size_t u, std::size_t index) const { return rows[u][index].initial - rows[u][index].capacity; }
};
}  // namespace graphmine::runtime
