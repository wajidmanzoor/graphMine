#pragma once
#include "walk_input.hpp"

namespace graphmine::runtime {
struct SamplingNeighbor { VertexIndex vertex; std::size_t edge; Exact weight; };
struct SamplingInput {
  std::vector<std::vector<SamplingNeighbor>> adjacency;
  std::vector<std::optional<std::string>> types;
};
SamplingInput sampling_input(const Graph&, bool weighted, bool typed, const std::optional<Exact>& cutoff, Work&);
}
