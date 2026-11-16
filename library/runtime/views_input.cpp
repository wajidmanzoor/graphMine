#include "views_internal.hpp"
#include "structured_input.hpp"
#include <algorithm>
#include <numeric>
namespace graphmine {
namespace {
namespace rt = runtime;
namespace json = boost::json;
using namespace view_detail;
rt::Work input_work() {
  rt::Work work;
  work.max_candidates = work.max_output_items = UINT64_MAX;
  work.timeout_seconds = std::numeric_limits<double>::infinity();
  return work;
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
            !spec.edge_ids && spec.labels.empty() && !spec.require_edge_weights,
        "feature matrix cannot apply graph-edge policies");
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
  result.build_work = count;
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
  result.build_work = work.candidates;
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
ViewResult build_collection(const json::value& input, const ViewSpec& spec, const ViewBuildOptions& options) {
  auto work = input_work();
  const auto graphs = rt::graph_collection(input, work, spec.weights == "int64_exact");
  ViewResult result;
  result.build_work = work.candidates;
  if (options.charge) options.charge(result.build_work);
  CollectionView collection;
  auto member_spec = spec;
  member_spec.kind = "csr";
  for (const auto& graph : graphs) {
    auto member = build_graph(graph, member_spec, options);
    result.build_work = add_count(result.build_work, member.build_work);
    result.original_edge_work = add_count(result.original_edge_work, member.original_edge_work);
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

}  // namespace
std::shared_ptr<const ViewResult> make_view(std::string_view input_json, const ViewSpec& spec) {
  return make_view(input_json, spec, {});
}
std::shared_ptr<const ViewResult> make_view(std::string_view input_json, const ViewSpec& spec,
                                          const ViewBuildOptions& options) {
  const auto input = rt::strict_json(input_json);
  return make_view(ParsedViewInput{input},spec,options);
}
std::shared_ptr<const ViewResult> make_view(ParsedViewInput parsed, const ViewSpec& spec,
                                          const ViewBuildOptions& options) {
  const auto canonical = spec.canonical_json();
  const auto& input = parsed.value;
  if (one_of(spec.kind, {"csr", "coo", "bipartite"}) ||
      (spec.kind == "dense" && (!input.is_object() || !input.as_object().contains("vectors"))))
    return make_view(rt::parse_graph(input, spec.weights == "int64_exact"), spec, options);
  const auto snapshot = rt::input_fingerprint(input);
  return view_detail::cached_view(snapshot, canonical, options, [&] {
    if (options.charge) options.charge(0);
    auto result = spec.kind == "hypergraph" ? build_hypergraph(input, spec)
                : spec.kind == "collection" ? build_collection(input, spec, options)
                                              : build_features(input, spec);
    if (spec.kind != "collection" && options.charge) options.charge(result.build_work);
    result.snapshot_hash = snapshot;
    result.canonical_spec = canonical;
    return result;
  });
}

}  // namespace graphmine
