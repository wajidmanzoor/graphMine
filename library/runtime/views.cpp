#include "graphmine/views.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <set>
#include <type_traits>

#include "representation_cache.hpp"
#include "structured_input.hpp"

namespace graphmine {
namespace {
namespace rt = runtime;
namespace json = boost::json;
using Number = HypergraphView::SourceNumber;

void check(bool condition, const std::string& message) {
  rt::require(condition, "Graph view: " + message);
}
bool one_of(const std::string& value, std::initializer_list<const char*> choices) {
  return std::any_of(choices.begin(), choices.end(),
                     [&](const char* choice) { return value == choice; });
}
bool wants(const ViewSpec& spec, const char* label) {
  return std::find(spec.labels.begin(), spec.labels.end(), label) != spec.labels.end();
}
rt::Work input_work() {
  rt::Work work;
  work.max_candidates = work.max_output_items = UINT64_MAX;
  work.timeout_seconds = std::numeric_limits<double>::infinity();
  return work;
}
json::value sorted_json(const json::value& value) {
  if (value.is_object()) {
    std::map<std::string, json::value> fields;
    for (const auto& field : value.as_object())
      fields.emplace(std::string(field.key()), sorted_json(field.value()));
    json::object result;
    for (const auto& [key, item] : fields) result[key] = item;
    return result;
  }
  if (value.is_array()) {
    json::array result;
    for (const auto& item : value.as_array()) result.push_back(sorted_json(item));
    return result;
  }
  return value;
}
json::array id_array(std::vector<ExternalId> values) {
  std::sort(values.begin(), values.end());
  json::array result;
  for (const auto& id : values) result.push_back(rt::id_json(id));
  return result;
}
std::uint64_t add_count(std::uint64_t a, std::uint64_t b) {
  check(a <= UINT64_MAX - b, "count overflow");
  return a + b;
}
std::size_t cells(std::uint64_t rows, std::uint64_t columns, const ViewSpec& spec) {
  check(!columns || rows <= SIZE_MAX / columns, "matrix size overflow");
  const auto size = rows * columns;
  validate_view_counts(spec, std::max(rows, columns), size);
  check(size <= std::vector<double>().max_size(), "matrix allocation size overflow");
  return static_cast<std::size_t>(size);
}

Number numeric(const json::value& value) {
  if (value.is_int64()) return value.as_int64();
  if (value.is_uint64()) return value.as_uint64();
  check(value.is_double() && std::isfinite(value.as_double()), "weight must be finite numeric data");
  return value.as_double();
}
Number attribute_number(const Attributes& attributes, const std::string& path) {
  const PropertyValue::Object* object = &attributes;
  std::size_t begin = 0;
  while (true) {
    const auto end = path.find('.', begin);
    const auto key = path.substr(begin, end == std::string::npos ? end : end - begin);
    check(!key.empty(), "weight attribute path has an empty component");
    const auto found = object->find(key);
    check(found != object->end(), "missing weight attribute: " + path);
    const auto& value = found->second.value();
    if (end == std::string::npos) {
      if (const auto* integer = std::get_if<std::int64_t>(&value)) return *integer;
      if (const auto* real = std::get_if<double>(&value)) return *real;
      check(false, "weight attribute must be numeric: " + path);
    }
    object = std::get_if<PropertyValue::Object>(&value);
    check(object != nullptr, "weight attribute path must traverse objects: " + path);
    begin = end + 1;
  }
}
Number edge_number(const EdgeRecord& edge, const ViewSpec& spec) {
  if (spec.weight_source == "unit") return 1.0;
  if (spec.weight_source.rfind("attribute:", 0) == 0)
    return attribute_number(edge.attributes, spec.weight_source.substr(10));
  if (edge.original_weight) return *edge.original_weight;
  return edge.weight.value_or(1.0);
}
std::int64_t exact_integer(const Number& number) {
  return std::visit([](const auto& value) -> std::int64_t {
    using T = std::decay_t<decltype(value)>;
    if constexpr (std::is_same_v<T, std::uint64_t>)
      check(value <= INT64_MAX, "int64_exact weight is outside signed 64-bit range");
    if constexpr (std::is_same_v<T, double>)
      // A double representation of INT64_MAX rounds to 2^63, so <= MAX is unsafe.
      check(std::isfinite(value) && value >= -0x1p63 && value < 0x1p63 &&
                std::trunc(value) == value,
            "int64_exact requires an exact integer in signed 64-bit range");
    return static_cast<std::int64_t>(value);
  }, number);
}
struct Weight {
  double f64 = 0;
  std::int64_t integer = 0;
};
Weight cast_weight(const Number& number, const ViewSpec& spec, NormalizationSummary& summary) {
  Weight result;
  if (spec.weights == "f64") {
    result.f64 = std::visit([](const auto& value) { return static_cast<double>(value); }, number);
    check(std::isfinite(result.f64), "f64 weight must be finite");
    summary.weights_cast += !std::holds_alternative<double>(number);
  } else if (spec.weights == "int64_exact") {
    result.integer = exact_integer(number);
    summary.weights_cast += !std::holds_alternative<std::int64_t>(number);
  }
  return result;
}
ViewWeights weight_column(const ViewSpec& spec) {
  if (spec.weights == "f64") return std::vector<double>{};
  if (spec.weights == "int64_exact") return std::vector<std::int64_t>{};
  return std::monostate{};
}
void append_weight(ViewWeights& column, const Weight& value) {
  if (auto* data = std::get_if<std::vector<double>>(&column)) data->push_back(value.f64);
  if (auto* data = std::get_if<std::vector<std::int64_t>>(&column)) data->push_back(value.integer);
}
void merge_weight(Weight& stored, const Weight& next, const ViewSpec& spec, EdgeIndex& original,
                  EdgeIndex next_original) {
  if (spec.weights == "none" || spec.parallel_edges == "collapse:first") return;
  const bool integer = spec.weights == "int64_exact";
  if (spec.parallel_edges == "collapse:sum") {
    if (integer) {
      const auto a = stored.integer, b = next.integer;
      check((b <= 0 || a <= INT64_MAX - b) && (b >= 0 || a >= INT64_MIN - b),
            "int64_exact sum overflows signed 64-bit range");
      stored.integer += b;
    } else {
      stored.f64 += next.f64;
      check(std::isfinite(stored.f64), "f64 sum overflows");
    }
  } else {
    const bool smaller = integer ? next.integer < stored.integer : next.f64 < stored.f64;
    const bool larger = integer ? next.integer > stored.integer : next.f64 > stored.f64;
    if ((spec.parallel_edges == "collapse:min" && smaller) ||
        (spec.parallel_edges == "collapse:max" && larger)) {
      stored = next;
      original = next_original;
    }
  }
}
void label_column(const std::vector<std::optional<std::string>>& labels,
                  std::optional<std::vector<std::uint32_t>>& column,
                  std::vector<std::string>& dictionary) {
  std::set<std::string> unique;
  for (const auto& label : labels) if (label) unique.insert(*label);
  check(unique.size() < UINT32_MAX, "too many label categories");
  dictionary.assign(unique.begin(), unique.end());
  column.emplace();
  for (const auto& label : labels)
    column->push_back(label ? std::lower_bound(dictionary.begin(), dictionary.end(), *label) -
                                 dictionary.begin() : UINT32_MAX);
}

ViewVertexMap vertex_map(const Graph& graph, const ViewSpec& spec, std::uint32_t& left_count) {
  ViewVertexMap result;
  std::vector<bool> left(graph.vertex_count(), false);
  if (spec.bipartite_sides != "none") {
    check(!graph.directed() || spec.direction == "symmetrize",
          "bipartite views require undirected input or explicit symmetrize");
    if (spec.bipartite_sides == "parameters") {
      std::vector<bool> seen(graph.vertex_count(), false);
      auto mark = [&](const std::vector<ExternalId>& values, bool is_left) {
        for (const auto& id : values) {
          const auto v = graph.dense_index(id);
          check(!seen[v], "partitions repeat or overlap at a vertex");
          seen[v] = true;
          left[v] = is_left;
        }
      };
      mark(spec.parameters->left_partition, true);
      mark(spec.parameters->right_partition, false);
      check(std::all_of(seen.begin(), seen.end(), [](bool value) { return value; }),
            "partitions must cover every vertex, including isolates");
    } else {
      for (std::size_t v = 0; v < graph.vertex_count(); ++v) {
        const auto& attrs = graph.canonical().vertices[v].attributes;
        const auto found = attrs.find("side");
        check(found != attrs.end(), "every vertex needs attributes.side");
        const auto* side = std::get_if<std::string>(&found->second.value());
        check(side && (*side == "left" || *side == "right"), "side must be left or right");
        left[v] = *side == "left";
      }
    }
    for (VertexIndex v = 0; v < graph.vertex_count(); ++v)
      if (left[v]) result.to_original.push_back(v);
    left_count = result.to_original.size();
    for (VertexIndex v = 0; v < graph.vertex_count(); ++v)
      if (!left[v]) result.to_original.push_back(v);
  } else {
    result.to_original.resize(graph.vertex_count());
    std::iota(result.to_original.begin(), result.to_original.end(), 0);
  }
  result.from_original.resize(graph.vertex_count());
  for (VertexIndex v = 0; v < result.to_original.size(); ++v) {
    result.from_original[result.to_original[v]] = v;
    result.external_ids.push_back(graph.external_id(result.to_original[v]));
  }
  return result;
}

struct Arc { VertexIndex src, dst; Weight weight; EdgeIndex original; };
CooView normalize(const Graph& graph, const ViewSpec& spec, NormalizationSummary& summary,
                  std::uint32_t& left_count) {
  validate_view_counts(spec, graph.vertex_count(), graph.edge_count());
  CooView result;
  result.vertices = vertex_map(graph, spec, left_count);
  result.directed = graph.directed() && spec.direction != "symmetrize";
  result.symmetric = !result.directed;
  result.sorted = spec.sorted_neighbors;
  summary.projection_applied = graph.directed() && spec.direction == "symmetrize";
  summary.directed_projection_applied = summary.projection_applied;
  std::vector<Arc> edges;
  std::map<std::pair<VertexIndex, VertexIndex>, std::size_t> unique;
  for (EdgeIndex i = 0; i < graph.edge_count(); ++i) {
    const auto& edge = graph.canonical().edges[i];
    const auto weight = spec.weights == "none" ? Weight{} : cast_weight(edge_number(edge, spec), spec, summary);
    auto u = result.vertices.from_original[graph.dense_index(edge.source)];
    auto v = result.vertices.from_original[graph.dense_index(edge.target)];
    if (u == v && spec.self_loops == "drop") { ++summary.self_loops_removed; continue; }
    if (spec.bipartite_sides != "none")
      check((u < left_count) != (v < left_count), "edge must cross the bipartite sides");
    if (!result.directed && v < u) std::swap(u, v);
    if (result.directed && spec.direction == "reverse") std::swap(u, v);
    const auto pair = std::make_pair(u, v);
    if (spec.parallel_edges != "keep") {
      const auto [found, inserted] = unique.emplace(pair, edges.size());
      if (!inserted) {
        auto& previous = edges[found->second];
        merge_weight(previous.weight, weight, spec, previous.original, i);
        ++summary.parallel_edges_collapsed;
        continue;
      }
    }
    edges.push_back({u, v, weight, i});
  }
  std::uint64_t count = edges.size();
  if (!result.directed)
    for (const auto& edge : edges) count = add_count(count, edge.src != edge.dst);
  validate_view_counts(spec, graph.vertex_count(), count);
  const auto original_count = edges.size();
  if (!result.directed) {
    edges.reserve(count);
    for (std::size_t i = 0; i < original_count; ++i) {
      const auto edge = edges[i];
      if (edge.src != edge.dst) edges.push_back({edge.dst, edge.src, edge.weight, edge.original});
    }
  }
  if (spec.sorted_neighbors)
    std::stable_sort(edges.begin(), edges.end(), [](const Arc& a, const Arc& b) {
      return std::tie(a.src, a.dst) < std::tie(b.src, b.dst);
    });
  result.weights = weight_column(spec);
  if (spec.edge_ids) result.edge_ids.emplace();
  if (wants(spec, "timestamp")) result.side_tables.timestamp.emplace();
  std::vector<std::optional<std::string>> edge_labels;
  std::set<std::pair<VertexIndex, VertexIndex>> seen;
  result.simple = true;
  for (const auto& edge : edges) {
    result.src.push_back(edge.src);
    result.dst.push_back(edge.dst);
    append_weight(result.weights, edge.weight);
    if (result.edge_ids) result.edge_ids->push_back(edge.original);
    result.simple &= edge.src != edge.dst && seen.emplace(edge.src, edge.dst).second;
    const auto& original = graph.canonical().edges[edge.original];
    if (wants(spec, "edge_label")) edge_labels.push_back(original.type);
    if (result.side_tables.timestamp) {
      check(original.timestamp && std::holds_alternative<std::int64_t>(*original.timestamp),
            "timestamp column requires an explicit int64 timestamp on each retained edge");
      result.side_tables.timestamp->push_back(std::get<std::int64_t>(*original.timestamp));
    }
  }
  if (wants(spec, "edge_label"))
    label_column(edge_labels, result.side_tables.edge_label, result.side_tables.edge_label_dictionary);
  if (wants(spec, "vertex_label")) {
    std::vector<std::optional<std::string>> labels;
    for (auto original : result.vertices.to_original) labels.push_back(graph.canonical().vertices[original].label);
    label_column(labels, result.side_tables.vertex_label, result.side_tables.vertex_label_dictionary);
  }
  summary.vertices = graph.vertex_count();
  summary.edges = edges.size();
  return result;
}

template<class T> void reorder(std::vector<T>& values, const std::vector<EdgeIndex>& order) {
  auto previous = std::move(values);
  values.reserve(order.size());
  for (auto index : order) values.push_back(previous[index]);
}
template<class T> void reorder(std::optional<std::vector<T>>& values, const std::vector<EdgeIndex>& order) {
  if (values) reorder(*values, order);
}
CsrView csr(CooView input, const ViewSpec& spec) {
  CsrView result;
  const auto n = input.vertices.external_ids.size();
  std::vector<EdgeIndex> order(input.src.size());
  std::iota(order.begin(), order.end(), 0);
  // CSR always groups sources; stable grouping preserves unsorted row order.
  std::stable_sort(order.begin(), order.end(), [&](auto a, auto b) { return input.src[a] < input.src[b]; });
  reorder(input.src, order);
  reorder(input.dst, order);
  std::visit([&](auto& values) {
    if constexpr (!std::is_same_v<std::decay_t<decltype(values)>, std::monostate>) reorder(values, order);
  }, input.weights);
  reorder(input.edge_ids, order);
  reorder(input.side_tables.edge_label, order);
  reorder(input.side_tables.timestamp, order);
  result.offsets.assign(n + 1, 0);
  for (auto v : input.src) ++result.offsets[v + 1];
  std::partial_sum(result.offsets.begin(), result.offsets.end(), result.offsets.begin());
  if (spec.direction == "both") {
    result.in_offsets.emplace(n + 1, 0);
    for (auto v : input.dst) ++(*result.in_offsets)[v + 1];
    std::partial_sum(result.in_offsets->begin(), result.in_offsets->end(), result.in_offsets->begin());
    auto next = *result.in_offsets;
    result.in_indices.emplace(input.src.size());
    result.in_edge_indices.emplace(input.src.size());
    for (EdgeIndex e = 0; e < input.src.size(); ++e) {
      const auto index = next[input.dst[e]]++;
      (*result.in_indices)[index] = input.src[e];
      (*result.in_edge_indices)[index] = e;
    }
  }
  result.indices = std::move(input.dst);
  result.weights = std::move(input.weights);
  result.edge_ids = std::move(input.edge_ids);
  result.vertices = std::move(input.vertices);
  result.side_tables = std::move(input.side_tables);
  result.directed = input.directed;
  result.symmetric = input.symmetric;
  result.simple = input.simple;
  result.sorted = input.sorted;
  return result;
}
}  // namespace

void ViewSpec::validate() const {
  check(one_of(kind, {"csr", "coo", "bipartite", "dense", "hypergraph", "collection"}), "unknown kind");
  check(one_of(direction, {"keep", "symmetrize", "reverse", "both"}), "unknown direction");
  check(one_of(self_loops, {"keep", "drop"}), "unknown self_loops policy");
  check(one_of(parallel_edges, {"keep", "collapse:sum", "collapse:min", "collapse:max", "collapse:first"}),
        "unknown parallel_edges policy");
  check(one_of(weights, {"none", "f64", "int64_exact"}), "unknown weight type");
  check(weight_source == "edge.weight" || weight_source == "unit" ||
            (weight_source.rfind("attribute:", 0) == 0 && weight_source.size() > 10),
        "unknown weight source");
  if (weight_source.rfind("attribute:", 0) == 0) {
    const auto path = weight_source.substr(10);
    check(path.front() != '.' && path.back() != '.' && path.find("..") == std::string::npos,
          "weight attribute path has an empty component");
  }
  check(one_of(index_width, {"u32", "i32"}), "unknown index width");
  check(one_of(bipartite_sides, {"none", "attribute:side", "parameters"}), "unknown side source");
  check((bipartite_sides == "parameters") == parameters.has_value(),
        "partition parameters must be present exactly when bipartite_sides=parameters");
  check(bipartite_sides == "none" || kind == "bipartite" || kind == "dense",
        "sides require a bipartite or dense view");
  check(kind != "bipartite" || bipartite_sides != "none", "bipartite view requires sides");
  check(kind != "dense" || weights != "none", "dense view requires numeric weights");
  check(direction != "both" || kind == "csr" || kind == "bipartite" || kind == "collection",
        "both requests forward/reverse CSR and requires a CSR-based view");
  std::set<std::string> seen;
  for (const auto& label : labels) {
    check(one_of(label, {"vertex_label", "edge_label", "timestamp"}), "unknown side table");
    check(seen.insert(label).second, "duplicate side table");
  }
  if (kind == "hypergraph") {
    check(direction == "keep" && self_loops == "keep" && parallel_edges == "keep",
          "hypergraph incidence preserves direction, membership and hyperedge identity");
    check(labels.empty(), "hypergraph input has no graph label/timestamp fields");
  }
}
void validate_view_counts(const ViewSpec& spec, std::uint64_t vertices, std::uint64_t edges) {
  check(vertices <= UINT32_MAX, "vertex count exceeds u32 indices");
  check(vertices <= spec.limits.max_vertices, "max_vertices exceeded");
  check(edges <= spec.limits.max_edges, "max_edges exceeded");
  check(spec.index_width == "u32" || spec.index_width == "i32", "unknown index width");
  if (spec.index_width == "i32")
    check(vertices <= INT32_MAX && edges <= INT32_MAX, "count exceeds INT32_MAX for i32 view");
}
ViewSpec ViewSpec::from_json(std::string_view input) {
  const auto value = rt::object(rt::strict_json(input), "view spec");
  rt::fields(value, {"kind", "direction", "self_loops", "parallel_edges", "weights", "weight_source",
                    "edge_ids", "labels", "bipartite_sides", "sorted_neighbors", "index_width",
                    "limits", "parameters"});
  ViewSpec spec;
  for (auto [key, target] : std::initializer_list<std::pair<const char*, std::string*>>{
           {"kind", &spec.kind}, {"direction", &spec.direction}, {"self_loops", &spec.self_loops},
           {"parallel_edges", &spec.parallel_edges}, {"weights", &spec.weights},
           {"weight_source", &spec.weight_source}, {"bipartite_sides", &spec.bipartite_sides},
           {"index_width", &spec.index_width}})
    if (value.contains(key)) *target = rt::string(value.at(key), key);
  for (auto [key, target] : {std::pair{"edge_ids", &spec.edge_ids}, {"sorted_neighbors", &spec.sorted_neighbors}})
    if (value.contains(key)) {
      check(value.at(key).is_bool(), std::string(key) + " must be boolean");
      *target = value.at(key).as_bool();
    }
  if (value.contains("labels")) {
    check(value.at("labels").is_array(), "labels must be an array");
    for (const auto& label : value.at("labels").as_array()) spec.labels.push_back(rt::string(label, "label"));
  }
  if (value.contains("limits")) {
    const auto limits = rt::object(value.at("limits"), "limits");
    rt::fields(limits, {"max_vertices", "max_edges"});
    if (limits.contains("max_vertices")) spec.limits.max_vertices = rt::uint(limits.at("max_vertices"), "max_vertices");
    if (limits.contains("max_edges")) spec.limits.max_edges = rt::uint(limits.at("max_edges"), "max_edges");
  }
  if (value.contains("parameters")) {
    const auto parameters = rt::object(value.at("parameters"), "view parameters");
    rt::fields(parameters, {"left_partition", "right_partition"}, {"left_partition", "right_partition"});
    spec.parameters.emplace();
    for (auto [key, target] : {std::pair{"left_partition", &spec.parameters->left_partition},
                              {"right_partition", &spec.parameters->right_partition}}) {
      check(parameters.at(key).is_array(), std::string(key) + " must be an ID array");
      for (const auto& id : parameters.at(key).as_array()) target->push_back(rt::external_id(id));
    }
  }
  spec.validate();
  return spec;
}
std::string ViewSpec::canonical_json() const {
  validate();
  auto sorted_labels = labels;
  std::sort(sorted_labels.begin(), sorted_labels.end());
  json::array columns;
  for (const auto& name : sorted_labels) columns.push_back(json::value(name));
  json::object result{{"kind", kind}, {"direction", direction}, {"self_loops", self_loops},
                      {"parallel_edges", parallel_edges}, {"weights", weights}, {"weight_source", weight_source},
                      {"edge_ids", edge_ids}, {"labels", columns}, {"bipartite_sides", bipartite_sides},
                      {"sorted_neighbors", sorted_neighbors}, {"index_width", index_width},
                      {"limits", {{"max_vertices", limits.max_vertices}, {"max_edges", limits.max_edges}}}};
  if (parameters)
    result["parameters"] = json::object{{"left_partition", id_array(parameters->left_partition)},
                                        {"right_partition", id_array(parameters->right_partition)}};
  return json::serialize(sorted_json(result));
}

namespace {
DenseView dense_graph(CooView input, const ViewSpec& spec, std::uint32_t left_count,
                      NormalizationSummary& summary) {
  DenseView result;
  const auto n = input.vertices.external_ids.size();
  const bool bipartite = spec.bipartite_sides != "none";
  result.rows = bipartite ? left_count : n;
  result.columns = bipartite ? n - left_count : n;
  const auto count = cells(result.rows, result.columns, spec);
  result.values = weight_column(spec);
  std::visit([&](auto& values) {
    if constexpr (!std::is_same_v<std::decay_t<decltype(values)>, std::monostate>) values.resize(count, 0);
  }, result.values);
  result.present.assign(count, 0);
  if (input.edge_ids) result.edge_ids.emplace(count, UINT64_MAX);
  if (input.side_tables.edge_label) result.side_tables.edge_label.emplace(count, UINT32_MAX);
  if (input.side_tables.timestamp) result.side_tables.timestamp.emplace(count, 0);
  result.side_tables.edge_label_dictionary = std::move(input.side_tables.edge_label_dictionary);
  result.side_tables.vertex_label_dictionary = std::move(input.side_tables.vertex_label_dictionary);
  if (input.side_tables.vertex_label)
    result.side_tables.vertex_label.emplace(input.side_tables.vertex_label->begin(),
                                            input.side_tables.vertex_label->begin() + result.rows);
  for (std::size_t i = 0; i < result.rows; ++i) {
    result.row_ids.push_back(input.vertices.external_ids[i]);
    result.row_original.push_back(input.vertices.to_original[i]);
  }
  for (std::size_t i = 0; i < result.columns; ++i) {
    const auto v = bipartite ? i + left_count : i;
    result.column_ids.push_back(input.vertices.external_ids[v]);
    result.column_original.push_back(input.vertices.to_original[v]);
  }
  summary.edges = 0;
  for (std::size_t i = 0; i < input.src.size(); ++i) {
    if (bipartite && input.src[i] >= left_count) continue;
    const auto row = input.src[i], column = bipartite ? input.dst[i] - left_count : input.dst[i];
    const auto cell = row * result.columns + column;
    check(!result.present[cell], "dense cells cannot preserve parallel edges; declare a collapse rule");
    result.present[cell] = 1;
    ++summary.edges;
    std::visit([&](auto& values) {
      using T = std::decay_t<decltype(values)>;
      if constexpr (!std::is_same_v<T, std::monostate>) values[cell] = std::get<T>(input.weights)[i];
    }, result.values);
    if (result.edge_ids) (*result.edge_ids)[cell] = (*input.edge_ids)[i];
    if (result.side_tables.edge_label) (*result.side_tables.edge_label)[cell] = (*input.side_tables.edge_label)[i];
    if (result.side_tables.timestamp) (*result.side_tables.timestamp)[cell] = (*input.side_tables.timestamp)[i];
  }
  return result;
}
ViewResult build_graph(const Graph& graph, const ViewSpec& spec) {
  check(one_of(spec.kind, {"csr", "coo", "bipartite", "dense"}), "this kind requires a structured input");
  ViewResult result;
  std::uint32_t left_count = 0;
  auto input = normalize(graph, spec, result.normalization, left_count);
  if (spec.kind == "coo") result.view = std::move(input);
  else if (spec.kind == "csr") result.view = csr(std::move(input), spec);
  else if (spec.kind == "bipartite") result.view = BipartiteView{csr(std::move(input), spec), left_count};
  else result.view = dense_graph(std::move(input), spec, left_count, result.normalization);
  return result;
}
ViewVertexMap identity_map(const std::vector<ExternalId>& ids) {
  ViewVertexMap result;
  result.external_ids = ids;
  result.to_original.resize(ids.size());
  std::iota(result.to_original.begin(), result.to_original.end(), 0);
  result.from_original = result.to_original;
  return result;
}
ViewResult build_features(const json::value& input, const ViewSpec& spec) {
  check(spec.direction == "keep" && spec.self_loops == "keep" && spec.parallel_edges == "keep" &&
            spec.weight_source == "edge.weight" && spec.bipartite_sides == "none" &&
            !spec.edge_ids && spec.labels.empty(), "feature matrix cannot apply graph-edge policies");
  const auto data = rt::object(input, "feature_vectors");
  rt::fields(data, {"dataset_id", "dimension", "vectors"}, {"dataset_id", "dimension", "vectors"});
  check(!rt::string(data.at("dataset_id"), "dataset_id").empty(), "dataset_id must not be empty");
  const auto dimension = rt::uint(data.at("dimension"), "dimension");
  check(dimension > 0 && data.at("vectors").is_array(), "features need positive dimension and a vectors array");
  const auto& rows = data.at("vectors").as_array();
  // Check shape/limits before allocation. The int64 path must not pass through
  // FeatureInput's binary64 matrix; it uses the same IDs and row contract.
  const auto count = cells(rows.size(), dimension, spec);
  rt::StructuredVertices parsed;
  for (const auto& raw : rows) {
    const auto row = rt::object(raw, "vector");
    rt::fields(row, {"id", "values"}, {"id", "values"});
    parsed.add(row.at("id"));
    check(row.at("values").is_array() && row.at("values").as_array().size() == dimension,
          "feature width must match dimension");
  }
  ViewResult result;
  DenseView matrix;
  matrix.rows = rows.size();
  matrix.columns = dimension;
  for (std::uint64_t c = 0; c < matrix.columns; ++c) {
    matrix.column_ids.emplace_back(static_cast<std::int64_t>(c));
    matrix.column_original.push_back(c);
  }
  matrix.values = weight_column(spec);
  matrix.present.assign(count, 1);
  // Read the original tokens for int64_exact, not the parser's rounded doubles.
  for (const auto& raw : rows) {
    const auto row = rt::object(raw, "vector");
    for (const auto& value : row.at("values").as_array()) {
      if (spec.weights == "f64") (void)rt::numeric::float64(value, "feature");
      append_weight(matrix.values, cast_weight(numeric(value), spec, result.normalization));
    }
  }
  matrix.row_ids = parsed.ids;
  matrix.row_original = identity_map(parsed.ids).to_original;
  result.normalization.vertices = matrix.rows;
  result.normalization.edges = count;
  result.view = std::move(matrix);
  return result;
}
ViewResult build_hypergraph(const json::value& input, const ViewSpec& spec) {
  auto work = input_work();
  const rt::HypergraphInput parsed(input, work);
  validate_view_counts(spec, parsed.ids.size(), parsed.edges.size());
  ViewResult result;
  HypergraphView view;
  view.vertices = identity_map(parsed.ids);
  view.he_offsets.push_back(0);
  view.v_offsets.assign(parsed.ids.size() + 1, 0);
  std::uint64_t incidence_count = 0;
  for (const auto& edge : parsed.edges) incidence_count = add_count(incidence_count, edge.vertices.size());
  validate_view_counts(spec, parsed.ids.size(), incidence_count);
  for (const auto& edge : parsed.edges) {
    view.hyperedge_ids.push_back(edge.id);
    auto vertices = edge.vertices;
    if (spec.sorted_neighbors) std::sort(vertices.begin(), vertices.end());
    for (auto v : vertices) { view.he_vertices.push_back(v); ++view.v_offsets[v + 1]; }
    view.he_offsets.push_back(view.he_vertices.size());
  }
  std::partial_sum(view.v_offsets.begin(), view.v_offsets.end(), view.v_offsets.begin());
  auto next = view.v_offsets;
  view.v_hyperedges.resize(incidence_count);
  for (EdgeIndex e = 0; e < parsed.edges.size(); ++e)
    for (auto i = view.he_offsets[e]; i < view.he_offsets[e + 1]; ++i)
      view.v_hyperedges[next[view.he_vertices[i]]++] = e;
  auto weights = [&](const char* key, ViewWeights& values, std::vector<Number>& source) {
    values = weight_column(spec);
    for (const auto& raw : input.as_object().at(key).as_array()) {
      const auto& row = raw.as_object();
      const auto number = row.contains("weight") ? numeric(row.at("weight")) : Number(std::int64_t(1));
      source.push_back(number);
      if (spec.weights == "none") continue;
      Number selected = number;
      if (spec.weight_source == "unit") selected = 1.0;
      else if (spec.weight_source.rfind("attribute:", 0) == 0) {
        // Use the same typed property path resolver as ordinary edge records.
        check(row.contains("attributes"), "missing weight attributes");
        const auto path = spec.weight_source.substr(10);
        const json::value* value = &row.at("attributes");
        std::size_t begin = 0;
        do {
          const auto end = path.find('.', begin);
          const auto part = path.substr(begin, end == std::string::npos ? end : end - begin);
          check(value->is_object() && value->as_object().contains(part), "missing weight attribute: " + path);
          value = &value->as_object().at(part);
          if (end == std::string::npos) break;
          begin = end + 1;
        } while (true);
        selected = numeric(*value);
      }
      append_weight(values, cast_weight(selected, spec, result.normalization));
    }
  };
  weights("vertices", view.vertex_weights, view.source_vertex_weights);
  weights("hyperedges", view.hyperedge_weights, view.source_hyperedge_weights);
  result.normalization.vertices = parsed.ids.size();
  result.normalization.edges = parsed.edges.size();
  result.view = std::move(view);
  return result;
}
ViewResult build_collection(const json::value& input, const ViewSpec& spec) {
  auto work = input_work();
  const auto graphs = rt::graph_collection(input, work, spec.weights == "int64_exact");
  ViewResult result;
  CollectionView collection;
  auto member_spec = spec;
  member_spec.kind = "csr";
  for (const auto& graph : graphs) {
    auto member = build_graph(graph, member_spec);
    const auto& summary = member.normalization;
    auto& total = result.normalization;
    total.projection_applied |= summary.projection_applied;
    total.directed_projection_applied |= summary.directed_projection_applied;
    total.self_loops_removed = add_count(total.self_loops_removed, summary.self_loops_removed);
    total.parallel_edges_collapsed = add_count(total.parallel_edges_collapsed, summary.parallel_edges_collapsed);
    total.weights_cast = add_count(total.weights_cast, summary.weights_cast);
    total.vertices = add_count(total.vertices, summary.vertices);
    total.edges = add_count(total.edges, summary.edges);
    check(total.vertices <= spec.limits.max_vertices && total.edges <= spec.limits.max_edges,
          "collection aggregate exceeds view limits");
    collection.member_indices.push_back(collection.members.size());
    collection.member_ids.push_back(graph.canonical().graph.id);
    collection.normalizations.push_back(summary);
    collection.members.push_back(std::get<CsrView>(std::move(member.view)));
  }
  result.view = std::move(collection);
  return result;
}
std::string graph_hash(const Graph& graph) {
  auto work = input_work();
  auto input = rt::selected_graph(graph, std::vector<bool>(graph.vertex_count(), true), work);
  // Public C++ Graph also admits a binary64 weight without an original JSON
  // token. Preserve both storage forms in the key (casting provenance differs).
  json::array storage;
  for (const auto& edge : graph.canonical().edges)
    storage.push_back(json::array{edge.weight ? json::value(*edge.weight) : json::value(nullptr),
                                  edge.original_weight ? json::value(edge.original_weight->index()) : json::value(nullptr)});
  input["native_weight_storage"] = std::move(storage);
  return rt::input_fingerprint(input);
}
}  // namespace

std::shared_ptr<const ViewResult> make_view(const Graph& graph, const ViewSpec& spec) {
  const auto canonical = spec.canonical_json();
  validate_view_counts(spec, graph.vertex_count(), graph.edge_count());
  const auto snapshot = graph_hash(graph);
  return rt::cached_standard_view(snapshot, canonical, [&] {
    auto result = build_graph(graph, spec);
    result.snapshot_hash = snapshot;
    result.canonical_spec = canonical;
    return result;
  });
}
std::shared_ptr<const ViewResult> make_view(std::string_view input_json, const ViewSpec& spec) {
  const auto canonical = spec.canonical_json();
  const auto input = rt::strict_json(input_json);
  if (one_of(spec.kind, {"csr", "coo", "bipartite"}) ||
      (spec.kind == "dense" && (!input.is_object() || !input.as_object().contains("vectors"))))
    return make_view(rt::parse_graph(input, spec.weights == "int64_exact"), spec);
  const auto snapshot = rt::input_fingerprint(input);
  return rt::cached_standard_view(snapshot, canonical, [&] {
    auto result = spec.kind == "hypergraph" ? build_hypergraph(input, spec)
                : spec.kind == "collection" ? build_collection(input, spec)
                                              : build_features(input, spec);
    result.snapshot_hash = snapshot;
    result.canonical_spec = canonical;
    return result;
  });
}
std::string ViewResult::normalization_json() const {
  return json::serialize(json::object{{"projection_applied", normalization.projection_applied},
      {"self_loops_removed", normalization.self_loops_removed},
      {"parallel_edges_collapsed", normalization.parallel_edges_collapsed},
      {"weights_cast", normalization.weights_cast}, {"vertices", normalization.vertices},
      {"edges", normalization.edges}});
}

namespace {
struct Accounting {
  std::size_t bytes = 0;
  void add(std::size_t value) {
    bytes = value > SIZE_MAX - bytes ? SIZE_MAX : bytes + value;
  }
  template<class T> void column(const std::vector<T>& values) {
    if (values.capacity() > SIZE_MAX / sizeof(T)) bytes = SIZE_MAX;
    else add(values.capacity() * sizeof(T));
  }
  template<class T> void column(const std::optional<std::vector<T>>& values) { if (values) column(*values); }
  void strings(const std::vector<std::string>& values) { column(values); for (const auto& v : values) add(v.capacity() + 32); }
  void ids(const std::vector<ExternalId>& values) {
    column(values);
    for (const auto& v : values) if (const auto* s = std::get_if<std::string>(&v.value())) add(s->capacity() + 32);
  }
  void mapping(const ViewVertexMap& v) { column(v.to_original); column(v.from_original); ids(v.external_ids); }
  void weights(const ViewWeights& w) {
    std::visit([&](const auto& values) {
      if constexpr (!std::is_same_v<std::decay_t<decltype(values)>, std::monostate>) column(values);
    }, w);
  }
  void tables(const ViewSideTables& t) {
    column(t.vertex_label); column(t.edge_label); column(t.timestamp);
    strings(t.vertex_label_dictionary); strings(t.edge_label_dictionary);
  }
  void view(const CsrView& v) {
    add(512);  // allocation overhead, including each collection member
    column(v.offsets); column(v.indices); weights(v.weights); column(v.edge_ids);
    column(v.in_offsets); column(v.in_indices); column(v.in_edge_indices); mapping(v.vertices); tables(v.side_tables);
  }
  void view(const CooView& v) {
    column(v.src); column(v.dst); weights(v.weights); column(v.edge_ids); mapping(v.vertices); tables(v.side_tables);
  }
  void view(const BipartiteView& v) { view(v.csr); }
  void view(const DenseView& v) {
    weights(v.values); ids(v.row_ids); ids(v.column_ids); column(v.row_original); column(v.column_original);
    column(v.present); column(v.edge_ids); tables(v.side_tables);
  }
  void view(const HypergraphView& v) {
    column(v.he_offsets); column(v.he_vertices); column(v.v_offsets); column(v.v_hyperedges);
    mapping(v.vertices); ids(v.hyperedge_ids); weights(v.vertex_weights); weights(v.hyperedge_weights);
    column(v.source_vertex_weights); column(v.source_hyperedge_weights);
  }
  void view(const CollectionView& v) {
    column(v.members); column(v.member_indices); strings(v.member_ids); column(v.normalizations);
    for (const auto& member : v.members) view(member);
  }
};
}  // namespace
std::size_t ViewResult::accounted_bytes() const {
  Accounting a;
  a.add(sizeof(ViewResult) + 1024);  // cache node, shared ownership, allocation overhead
  a.add(snapshot_hash.capacity() + 1);
  a.add(canonical_spec.capacity() + 1);
  std::visit([&](const auto& v) { a.view(v); }, view);
  return a.bytes;
}
}  // namespace graphmine
