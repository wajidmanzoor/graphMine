#include <algorithm>
#include <cmath>
#include <set>

#include "internal.hpp"

namespace graphmine::runtime {
json::object link_prediction(const Graph& graph, const json::object& args,
                             const std::string& backend, int device, Work& work) {
  fields(args, {"scoring_measure", "candidate_pairs", "exclude_existing_edges", "top_k"});
  require(!graph.directed(), "Local link prediction requires an undirected graph");
  const auto measure = args.contains("scoring_measure")
                           ? string(args.at("scoring_measure"), "scoring_measure")
                           : "jaccard";
  const std::set<std::string> measures{"jaccard",
                                       "common_neighbors",
                                       "adamic_adar",
                                       "resource_allocation",
                                       "preferential_attachment",
                                       "sorensen",
                                       "overlap",
                                       "cosine"};
  require(measures.count(measure), "Unknown scoring_measure");
  const auto exclude = boolean(args, "exclude_existing_edges", true);
  std::optional<std::uint64_t> top;
  if (args.contains("top_k") && !args.at("top_k").is_null()) {
    top = uint(args.at("top_k"), "top_k");
    require(*top > 0, "top_k must be positive");
  }
  const auto input = weighted_graph(graph, false, false, "collapse", "outgoing", work);
  const auto adj = adjacency(graph, work);
  using Pair = std::pair<VertexIndex, VertexIndex>;
  std::set<Pair> selected;
  auto add = [&](VertexIndex u, VertexIndex v) {
    work.tick();
    require(u != v, "Candidate pairs must contain distinct vertices");
    if (v < u) std::swap(u, v);
    if (exclude && std::binary_search(adj[u].begin(), adj[u].end(), v)) return;
    selected.emplace(u, v);
    work.output(selected.size());
  };
  const bool explicit_pairs =
      args.contains("candidate_pairs") && !args.at("candidate_pairs").is_null();
  if (explicit_pairs) {
    require(args.at("candidate_pairs").is_array(), "candidate_pairs must be an array or null");
    for (const auto& value : args.at("candidate_pairs").as_array()) {
      require(value.is_array() && value.as_array().size() == 2,
              "Each candidate pair must have exactly two vertices");
      add(graph.dense_index(external_id(value.as_array()[0])),
          graph.dense_index(external_id(value.as_array()[1])));
    }
  } else
    for (VertexIndex u = 0; u < adj.size(); ++u)
      for (VertexIndex v = u + 1; v < adj.size(); ++v) add(u, v);
  const std::vector<Pair> pairs(selected.begin(), selected.end());
  std::vector<double> scores;
  if (backend != "cpp")
    scores = cugraph_jaccard(input, pairs, device, work);
  else
    for (const auto [u, v] : pairs) {
      work.tick(adj[u].size() + adj[v].size());
      std::vector<VertexIndex> common;
      std::set_intersection(adj[u].begin(), adj[u].end(), adj[v].begin(), adj[v].end(),
                            std::back_inserter(common));
      const double a = adj[u].size(), b = adj[v].size(), count = common.size();
      double score = 0;
      if (measure == "common_neighbors")
        score = count;
      else if (measure == "preferential_attachment")
        score = a * b;
      else if (measure == "adamic_adar" || measure == "resource_allocation") {
        for (const auto x : common)
          score += measure == "adamic_adar" ? 1.0 / std::log(adj[x].size()) : 1.0 / adj[x].size();
      } else {
        const auto divisor = measure == "jaccard"    ? a + b - count
                             : measure == "sorensen" ? (a + b) / 2
                             : measure == "overlap"  ? std::min(a, b)
                                                     : std::sqrt(a * b);
        score = divisor ? count / divisor : 0;
      }
      scores.push_back(score);
    }
  require(scores.size() == pairs.size(), "Link prediction returned an incomplete score vector");
  std::vector<std::size_t> order;
  json::array normalized_pairs;
  for (std::size_t i = 0; i < pairs.size(); ++i) {
    require(std::isfinite(scores[i]) && scores[i] >= 0,
            "Link prediction returned an invalid score");
    order.push_back(i);
    normalized_pairs.push_back(json::array{id_json(graph.external_id(pairs[i].first)),
                                           id_json(graph.external_id(pairs[i].second))});
  }
  std::sort(order.begin(), order.end(), [&](auto a, auto b) {
    return scores[a] != scores[b] ? scores[a] > scores[b] : pairs[a] < pairs[b];
  });
  if (top && order.size() > *top) order.resize(*top);
  json::array rows;
  for (const auto i : order)
    rows.push_back(json::object{{"source", id_json(graph.external_id(pairs[i].first))},
                                {"target", id_json(graph.external_id(pairs[i].second))},
                                {"score", scores[i]}});
  const bool complete = rows.size() == pairs.size();
  return {
      {"parameters",
       {{"scoring_measure", measure},
        {"candidate_pairs", explicit_pairs ? json::value(normalized_pairs) : json::value(nullptr)},
        {"exclude_existing_edges", exclude},
        {"top_k", top ? json::value(*top) : json::value(nullptr)}}},
      {"result", {{"pairs", rows}, {"candidate_count", pairs.size()}}},
      {"ports", {{"pairs", result_port("table", rows, complete)}}},
      {"complete", complete},
      {"quality", "numerical"}};
}
}  // namespace graphmine::runtime
