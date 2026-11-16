#pragma once
#include "family_util.hpp"

namespace graphmine::runtime {
struct TemporalQueryInput {
  std::set<VertexIndex> incident;
  std::map<ExternalId,std::size_t> indices;
  std::vector<VertexIndex> sources, targets;
  std::vector<std::size_t> originals;
};
struct TemporalEventInput {
  std::vector<Exact> times;
  std::vector<json::object> records;
  std::vector<std::pair<VertexIndex,VertexIndex>> endpoints;
  std::map<std::pair<VertexIndex,VertexIndex>,std::vector<std::size_t>> by_pair;
};
TemporalQueryInput temporal_motif_query_input(const Graph&, Work&);
TemporalEventInput temporal_motif_event_input(const Graph&, Work&);
}
