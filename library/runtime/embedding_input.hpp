#pragma once
#include "walk_input.hpp"

namespace graphmine::runtime {
WalkAdjacency embedding_adjacency(const Graph&, const std::string& loops, const std::string& direction, Work&);
struct KnowledgeInput {
  std::map<ExternalId,std::size_t> edge_indices;
  std::vector<VertexIndex> sources,targets;
  std::vector<std::string> relations;
};
KnowledgeInput knowledge_input(const Graph&, Work&);
}
