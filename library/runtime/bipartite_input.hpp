#pragma once
#include "matching_input.hpp"

namespace graphmine::runtime {
enum class BipartiteTopology { bicliques, butterflies, count };
struct BipartiteInput { std::vector<bool> left; MiningGraph adjacency; };
BipartiteInput bipartite_input(const Graph&, const json::object&, BipartiteTopology, Work&);
json::object resolve_biclique_parameters(const Graph&, const json::object&);
json::object maximal_bicliques_for_count(const Graph&, const json::object&, Work&);
struct BipartiteMatchingInput { std::vector<bool> left; MatchingEdges edges; };
BipartiteMatchingInput bipartite_matching_input(const Graph&, const std::string& objective, Work&);
}
