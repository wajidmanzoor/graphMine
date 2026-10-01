#pragma once

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>
#include <variant>
#include <vector>

namespace graphmine {

class ExternalId {
 public:
  using Value = std::variant<std::int64_t, std::string>;

  /// Constructs the numeric external ID zero.
  ExternalId() : value_(std::int64_t{0}) {}
  /// Constructs an external ID from a signed 64-bit integer.
  ExternalId(std::int64_t value) : value_(value) {}
  /// Constructs an external ID from an integer.
  ExternalId(int value) : value_(static_cast<std::int64_t>(value)) {}
  /// Constructs an external ID from an owned string.
  ExternalId(std::string value) : value_(std::move(value)) {}
  /// Constructs an external ID from a null-terminated string.
  ExternalId(const char* value) : value_(std::string(value)) {}

  /// Returns the underlying integer-or-string value.
  [[nodiscard]] const Value& value() const noexcept { return value_; }
  /// Renders the ID without changing its integer or string identity.
  [[nodiscard]] std::string to_string() const;

  /// Compares external IDs for type-preserving equality.
  friend bool operator==(const ExternalId& lhs, const ExternalId& rhs) {
    return lhs.value_ == rhs.value_;
  }

  /// Compares external IDs for inequality.
  friend bool operator!=(const ExternalId& lhs, const ExternalId& rhs) {
    return !(lhs == rhs);
  }

  /// Orders numeric IDs before string IDs and then orders by stored value.
  friend bool operator<(const ExternalId& lhs, const ExternalId& rhs) {
    if (lhs.value_.index() != rhs.value_.index()) {
      return lhs.value_.index() < rhs.value_.index();
    }
    if (std::holds_alternative<std::int64_t>(lhs.value_)) {
      return std::get<std::int64_t>(lhs.value_) <
             std::get<std::int64_t>(rhs.value_);
    }
    return std::get<std::string>(lhs.value_) <
           std::get<std::string>(rhs.value_);
  }

 private:
  Value value_;
};

struct ExternalIdHash {
  /// Computes a type-sensitive hash for an external vertex or edge ID.
  std::size_t operator()(const ExternalId& id) const noexcept;
};

class PropertyValue {
 public:
  using Array = std::vector<PropertyValue>;
  using Object = std::map<std::string, PropertyValue>;
  using Value = std::variant<std::nullptr_t, bool, std::int64_t, double,
                             std::string, Array, Object>;

  /// Constructs a null property value.
  PropertyValue() : value_(nullptr) {}
  /// Constructs a null property value.
  PropertyValue(std::nullptr_t) : value_(nullptr) {}
  /// Constructs a Boolean property value.
  PropertyValue(bool value) : value_(value) {}
  /// Constructs a signed 64-bit integer property value.
  PropertyValue(std::int64_t value) : value_(value) {}
  /// Constructs an integer property value.
  PropertyValue(int value) : value_(static_cast<std::int64_t>(value)) {}
  /// Constructs a floating-point property value.
  PropertyValue(double value) : value_(value) {}
  /// Constructs an owned string property value.
  PropertyValue(std::string value) : value_(std::move(value)) {}
  /// Constructs a property value from a null-terminated string.
  PropertyValue(const char* value) : value_(std::string(value)) {}
  /// Constructs a nested array property value.
  PropertyValue(Array value) : value_(std::move(value)) {}
  /// Constructs a nested object property value.
  PropertyValue(Object value) : value_(std::move(value)) {}

  /// Returns the underlying JSON-compatible value.
  [[nodiscard]] const Value& value() const noexcept { return value_; }

 private:
  Value value_;
};

using Attributes = PropertyValue::Object;
using Timestamp = std::variant<std::int64_t, std::string>;
using VertexIndex = std::uint32_t;
using EdgeIndex = std::uint64_t;

struct GraphDescriptor {
  std::string id;
  bool directed = false;
  bool allows_self_loops = false;
  bool allows_parallel_edges = false;
  Attributes attributes;
};

struct VertexRecord {
  ExternalId id;
  std::optional<std::string> label;
  std::optional<std::string> type;
  Attributes attributes;
};

struct EdgeRecord {
  ExternalId id;
  ExternalId source;
  ExternalId target;
  std::optional<double> weight;
  std::optional<Timestamp> timestamp;
  std::optional<std::string> type;
  Attributes attributes;
};

struct CanonicalGraphInput {
  GraphDescriptor graph;
  std::vector<VertexRecord> vertices;
  std::vector<EdgeRecord> edges;
};

struct CsrGraph {
  std::vector<std::uint64_t> offsets;
  std::vector<VertexIndex> neighbors;

  /// Returns the number of vertices encoded by the CSR offsets.
  [[nodiscard]] std::size_t vertex_count() const noexcept {
    return offsets.empty() ? 0 : offsets.size() - 1;
  }

  /// Returns the edge count when each undirected edge occurs in both directions.
  [[nodiscard]] std::uint64_t undirected_edge_count() const noexcept {
    return neighbors.size() / 2;
  }
};

struct NormalizationSummary {
  bool directed_projection_applied = false;
  std::uint64_t self_loops_removed = 0;
  std::uint64_t parallel_edges_collapsed = 0;
};

struct UndirectedGraphView {
  CsrGraph csr;
  NormalizationSummary normalization;
};

struct UndirectedProjectionOptions {
  bool allow_directed_projection = false;
};

class Graph {
 public:
  /// Validates and owns one canonical graph input while building dense-ID maps.
  explicit Graph(CanonicalGraphInput input);

  /// Builds a minimal canonical graph from vertex IDs and endpoint pairs.
  static Graph from_edges(
      std::string graph_id, std::vector<ExternalId> vertices,
      const std::vector<std::pair<ExternalId, ExternalId>>& edges,
      bool directed = false);

  /// Returns the exact canonical records supplied by the caller.
  [[nodiscard]] const CanonicalGraphInput& canonical() const noexcept {
    return input_;
  }

  /// Returns the number of canonical vertex records.
  [[nodiscard]] std::size_t vertex_count() const noexcept {
    return input_.vertices.size();
  }

  /// Returns the number of canonical edge records.
  [[nodiscard]] std::size_t edge_count() const noexcept {
    return input_.edges.size();
  }

  /// Returns whether the canonical graph is directed.
  [[nodiscard]] bool directed() const noexcept { return input_.graph.directed; }

  /// Maps a stable external ID to the dense index used by backend adapters.
  [[nodiscard]] VertexIndex dense_index(const ExternalId& id) const;
  /// Restores a stable external ID from a dense backend index.
  [[nodiscard]] const ExternalId& external_id(VertexIndex index) const;

  /// Produces a loop-free, duplicate-free symmetric CSR view for algorithms
  /// that require a simple undirected graph.
  [[nodiscard]] UndirectedGraphView simple_undirected(
      UndirectedProjectionOptions options = {}) const;

 private:
  CanonicalGraphInput input_;
  std::unordered_map<ExternalId, VertexIndex, ExternalIdHash> dense_ids_;
};

}  // namespace graphmine
