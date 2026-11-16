#pragma once
#include "graphmine/views.hpp"
#include "internal.hpp"

namespace graphmine::runtime {
// The adapter consumes this same immutable declaration that registry generation
// and golden tests inspect. Parameter variants use distinct profile IDs.
struct ViewProfile {
  const std::string id;
  const std::vector<std::string> operations;
  const ViewSpec spec;
  ViewProfile(const char* id, std::initializer_list<const char*> operations, const char* spec_json);
};
const ViewProfile& cpu_view_profile(const std::string&);
json::array cpu_view_declarations();

enum class ViewBudget { algorithm_owned, original_edges, weighted_adjacency };
std::shared_ptr<const ViewResult> consume_view(const Graph&, const ViewProfile&, Work&, ViewBudget);

struct CsrNeighbors {
  using Iterator = std::vector<VertexIndex>::const_iterator;
  Iterator first, last;
  Iterator begin() const { return first; }
  Iterator end() const { return last; }
  std::size_t size() const { return last - first; }
  VertexIndex operator[](std::size_t i) const { return first[i]; }
};
struct CsrRows {
  const CsrView& view;
  std::size_t size() const { return view.offsets.size() - 1; }
  CsrNeighbors operator[](std::size_t v) const {
    return {view.indices.begin() + view.offsets[v], view.indices.begin() + view.offsets[v+1]};
  }
};
Search cpu_bfs(const CsrView&, VertexIndex, std::optional<std::uint64_t>, Work&);
}  // namespace graphmine::runtime
