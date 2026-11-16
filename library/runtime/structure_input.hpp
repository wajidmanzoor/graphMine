#pragma once
#include "view_profiles.hpp"

namespace graphmine::runtime {
struct StructureInput {
  std::vector<std::pair<VertexIndex,VertexIndex>> pairs;
  std::vector<json::array> source_ids;
  std::vector<std::vector<std::pair<VertexIndex,std::size_t>>> adjacency;
};
StructureInput structure_input(const Graph&, const ViewProfile& topology,
                                const ViewProfile& records, Work&);
}
