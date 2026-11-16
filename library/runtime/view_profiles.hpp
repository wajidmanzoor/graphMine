#pragma once
#include <iterator>
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
  bool incoming = false;
  std::size_t size() const { return view.offsets.size() - 1; }
  CsrNeighbors operator[](std::size_t v) const {
    const auto& offsets = incoming ? *view.in_offsets : view.offsets;
    const auto& indices = incoming ? *view.in_indices : view.indices;
    return {indices.begin() + offsets[v], indices.begin() + offsets[v+1]};
  }
};
struct CsrArcs {
  struct Iterator {
    using iterator_category = std::forward_iterator_tag;
    using value_type = Arc;
    using difference_type = std::ptrdiff_t;
    using pointer = void;
    using reference = Arc;
    const CsrView* view;
    EdgeIndex index;
    Arc operator*() const { return {view->indices[index], std::get<std::vector<double>>(view->weights)[index]}; }
    Iterator& operator++() { ++index; return *this; }
    Iterator operator++(int) { auto previous = *this; ++index; return previous; }
    bool operator==(const Iterator& other) const { return view == other.view && index == other.index; }
    bool operator!=(const Iterator& other) const { return !(*this == other); }
  };
  const CsrView* view;
  EdgeIndex first, last;
  Iterator begin() const { return {view, first}; }
  Iterator end() const { return {view, last}; }
  std::size_t size() const { return last - first; }
  bool empty() const { return first == last; }
  Arc operator[](std::size_t i) const { return *Iterator{view, first+i}; }
};
struct WeightedCsrRows {
  const CsrView& view;
  std::size_t size() const { return view.offsets.size() - 1; }
  CsrArcs operator[](std::size_t v) const { return {&view, view.offsets[v], view.offsets[v+1]}; }
};
struct WeightedCsrInput {
  WeightedCsrRows rows;
  bool directed;
  explicit WeightedCsrInput(const CsrView& view) : rows{view}, directed(view.directed) {}
};
Search cpu_bfs(const CsrView&, VertexIndex, std::optional<std::uint64_t>, Work&);
}  // namespace graphmine::runtime
