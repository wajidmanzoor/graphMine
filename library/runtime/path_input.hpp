#pragma once
#include "family_util.hpp"

namespace graphmine::runtime {
using CapacityRows = std::vector<std::vector<std::pair<VertexIndex,double>>>;
CapacityRows widest_path_input(const Graph&, Work&);
struct CriticalPathInput {
  std::vector<std::vector<std::size_t>> adjacency;
  std::vector<std::size_t> indegree;
  std::vector<VertexIndex> ends;
  std::vector<Exact> weights;
};
CriticalPathInput critical_path_input(const Graph&, Work&);
struct TemporalPathEvent { VertexIndex u,v; Exact departure,arrival; std::size_t edge; };
std::vector<TemporalPathEvent> temporal_path_input(const Graph&, const Exact& ready,
    const std::optional<Exact>& deadline, const std::string& duration_attribute, Work&);
}
