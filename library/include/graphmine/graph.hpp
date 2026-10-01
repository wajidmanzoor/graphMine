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

  ExternalId() : value_(std::int64_t{0}) {}
  ExternalId(std::int64_t value) : value_(value) {}
  ExternalId(int value) : value_(static_cast<std::int64_t>(value)) {}
  ExternalId(std::string value) : value_(std::move(value)) {}
  ExternalId(const char* value) : value_(std::string(value)) {}

  [[nodiscard]] const Value& value() const noexcept { return value_; }
  [[nodiscard]] std::string to_string() const;

  friend bool operator==(const ExternalId& lhs, const ExternalId& rhs) {
    return lhs.value_ == rhs.value_;
  }

  friend bool operator!=(const ExternalId& lhs, const ExternalId& rhs) {
    return !(lhs == rhs);
  }

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
  std::size_t operator()(const ExternalId& id) const noexcept;
};

class PropertyValue {
 public:
  using Array = std::vector<PropertyValue>;
  using Object = std::map<std::string, PropertyValue>;
  using Value = std::variant<std::nullptr_t, bool, std::int64_t, double,
                             std::string, Array, Object>;

  PropertyValue() : value_(nullptr) {}
  PropertyValue(std::nullptr_t) : value_(nullptr) {}
  PropertyValue(bool value) : value_(value) {}
  PropertyValue(std::int64_t value) : value_(value) {}
  PropertyValue(int value) : value_(static_cast<std::int64_t>(value)) {}
  PropertyValue(double value) : value_(value) {}
  PropertyValue(std::string value) : value_(std::move(value)) {}
  PropertyValue(const char* value) : value_(std::string(value)) {}
  PropertyValue(Array value) : value_(std::move(value)) {}
  PropertyValue(Object value) : value_(std::move(value)) {}

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

  [[nodiscard]] std::size_t vertex_count() const noexcept {
    return offsets.empty() ? 0 : offsets.size() - 1;
  }

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
  explicit Graph(CanonicalGraphInput input);

  static Graph from_edges(
      std::string graph_id, std::vector<ExternalId> vertices,
      const std::vector<std::pair<ExternalId, ExternalId>>& edges,
      bool directed = false);

  [[nodiscard]] const CanonicalGraphInput& canonical() const noexcept {
    return input_;
  }

  [[nodiscard]] std::size_t vertex_count() const noexcept {
    return input_.vertices.size();
  }

  [[nodiscard]] std::size_t edge_count() const noexcept {
    return input_.edges.size();
  }

  [[nodiscard]] bool directed() const noexcept { return input_.graph.directed; }

  [[nodiscard]] VertexIndex dense_index(const ExternalId& id) const;
  [[nodiscard]] const ExternalId& external_id(VertexIndex index) const;

  [[nodiscard]] UndirectedGraphView simple_undirected(
      UndirectedProjectionOptions options = {}) const;

 private:
  CanonicalGraphInput input_;
  std::unordered_map<ExternalId, VertexIndex, ExternalIdHash> dense_ids_;
};

}  // namespace graphmine
