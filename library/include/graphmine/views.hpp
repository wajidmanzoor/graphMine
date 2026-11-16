#pragma once

#include <limits>
#include <functional>
#include <memory>
#include <string_view>

#include "graphmine/graph.hpp"

namespace graphmine {

struct ViewSpec {
  std::string kind = "csr";
  // COO records retain each original edge's orientation and input order.
  std::string coo_layout = "arcs";
  std::string direction = "keep";
  std::string self_loops = "keep";
  std::string parallel_edges = "keep";
  std::string weights = "f64";
  std::string weight_source = "edge.weight";
  // Validate all selected input weights, including edges subsequently dropped.
  bool nonnegative_weights = false;
  bool edge_ids = false;
  std::vector<std::string> labels;
  std::string bipartite_sides = "none";
  bool sorted_neighbors = true;
  std::string index_width = "u32";
  struct Limits {
    std::uint64_t max_vertices = UINT32_MAX;
    std::uint64_t max_edges = UINT64_MAX;
  } limits;
  struct Partitions {
    std::vector<ExternalId> left_partition, right_partition;
  };
  // Resolved operation parameters are part of the canonical spec/cache key.
  std::optional<Partitions> parameters;

  static ViewSpec from_json(std::string_view);
  [[nodiscard]] std::string canonical_json() const;
  void validate() const;
};

// Also usable before allocating arrays, including for i32 boundary checks.
void validate_view_counts(const ViewSpec&, std::uint64_t vertices, std::uint64_t edges);

struct RationalWeight {
  // Reduced decimal integers, positive denominator. No binary64 round-trip.
  std::string numerator = "0", denominator = "1";
  friend bool operator==(const RationalWeight& a, const RationalWeight& b) {
    return a.numerator == b.numerator && a.denominator == b.denominator;
  }
};
using ViewWeights = std::variant<std::monostate, std::vector<double>,
                                 std::vector<std::int64_t>, std::vector<RationalWeight>>;

struct ViewVertexMap {
  std::vector<VertexIndex> to_original, from_original;
  std::vector<ExternalId> external_ids;
};

struct ViewSideTables {
  // Missing labels use UINT32_MAX; dictionaries are lexicographically ordered.
  std::optional<std::vector<std::uint32_t>> vertex_label, edge_label;
  std::vector<std::string> vertex_label_dictionary, edge_label_dictionary;
  std::optional<std::vector<std::int64_t>> timestamp;
};

struct CsrView {
  std::vector<std::uint64_t> offsets;
  std::vector<VertexIndex> indices;
  ViewWeights weights;
  std::optional<std::vector<EdgeIndex>> edge_ids;
  std::optional<std::vector<std::uint64_t>> in_offsets;
  std::optional<std::vector<VertexIndex>> in_indices;
  // Transpose entry -> forward entry (weights and side tables stay aligned).
  std::optional<std::vector<EdgeIndex>> in_edge_indices;
  bool directed = false, symmetric = false, simple = false, sorted = false;
  ViewVertexMap vertices;
  ViewSideTables side_tables;
};

struct CooView {
  std::vector<VertexIndex> src, dst;
  ViewWeights weights;
  std::optional<std::vector<EdgeIndex>> edge_ids;
  bool directed = false, symmetric = false, simple = false, sorted = false;
  ViewVertexMap vertices;
  ViewSideTables side_tables;
};

struct BipartiteView {
  CsrView csr;
  std::uint32_t L = 0;
};

struct DenseView {
  std::uint64_t rows = 0, columns = 0;
  ViewWeights values;  // row-major; always f64 or int64_exact
  std::vector<ExternalId> row_ids, column_ids;
  std::vector<VertexIndex> row_original, column_original;
  // Absent graph cells are zero but distinguishable from explicit zero edges.
  std::vector<std::uint8_t> present;
  std::optional<std::vector<EdgeIndex>> edge_ids;  // UINT64_MAX for absent cells
  ViewSideTables side_tables;  // vertex labels: rows, edge columns: cells
};

struct HypergraphView {
  std::vector<std::uint64_t> he_offsets, v_offsets;
  std::vector<VertexIndex> he_vertices;
  std::vector<EdgeIndex> v_hyperedges;
  ViewVertexMap vertices;
  std::vector<ExternalId> hyperedge_ids;
  ViewWeights vertex_weights, hyperedge_weights;
  // Uncast input numbers remain available for existing exact arithmetic.
  using SourceNumber = std::variant<std::int64_t, std::uint64_t, double>;
  std::vector<SourceNumber> source_vertex_weights, source_hyperedge_weights;
};

struct CollectionView {
  std::vector<CsrView> members;
  std::vector<std::uint64_t> member_indices;
  std::vector<std::string> member_ids;
  std::vector<NormalizationSummary> normalizations;
};

using View = std::variant<CsrView, CooView, BipartiteView, DenseView, HypergraphView,
                          CollectionView>;
struct ViewResult {
  View view;
  NormalizationSummary normalization;
  std::string snapshot_hash, canonical_spec;
  std::uint64_t build_work = 0;
  [[nodiscard]] std::size_t accounted_bytes() const;
  [[nodiscard]] std::string normalization_json() const;
};

struct ViewBuildOptions {
  // Cache hits pay the same candidate cost as a successful fresh build.
  std::function<void(std::uint64_t)> charge;
  std::function<void(const ViewResult&, bool hit, bool retained)> observe;
};

// Immutable, process-local cached results.
// The JSON overload accepts the existing graph, feature_vectors, hypergraph and
// graph_collection input formats, selected by the declared kind.
std::shared_ptr<const ViewResult> make_view(const Graph&, const ViewSpec&);
std::shared_ptr<const ViewResult> make_view(const Graph&, const ViewSpec&, const ViewBuildOptions&);
std::shared_ptr<const ViewResult> make_view(std::string_view input_json, const ViewSpec&);

}  // namespace graphmine
