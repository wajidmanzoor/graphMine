#pragma once
#include "family_util.hpp"

namespace graphmine::runtime {
struct InfluenceInput {
  std::map<std::pair<VertexIndex,VertexIndex>,Exact> weights;
  std::vector<std::vector<std::pair<VertexIndex,Exact>>> incoming;
};
InfluenceInput influence_input(const Graph&, bool independent_cascade, Work&);
}
