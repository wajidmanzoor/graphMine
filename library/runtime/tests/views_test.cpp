#include <boost/json.hpp>
#include <cmath>
#include <cstring>
#include <future>
#include <iostream>
#include <random>
#include <set>
#include <type_traits>

#include "graphmine/runtime.hpp"
#include "graphmine/views.hpp"

namespace {
using namespace graphmine;
namespace json = boost::json;
std::size_t checks = 0;
void check(bool condition, const char* message) {
  ++checks;
  if (!condition) throw std::runtime_error(message);
}
template<class Function> void rejects(Function fn, const char* message) {
  bool failed = false;
  try { fn(); } catch (const std::exception&) { failed = true; }
  check(failed, message);
}
json::object cache(const char* action, std::uint64_t bytes = 128 * 1024 * 1024) {
  json::object request{{"command", "representation_cache"}, {"action", action}};
  if (std::string(action) == "configure") request["max_bytes"] = bytes;
  auto result = json::parse(graphmine::runtime::request(json::serialize(request))).as_object();
  check(!result.contains("error"), "cache control failed");
  return result;
}
json::object graph(bool directed = true) {
  return {{"graph", {{"id", "views-test"}, {"directed", directed},
                      {"allows_self_loops", true}, {"allows_parallel_edges", true}}},
          {"vertices", json::array{json::object{{"id", 0}, {"label", "z"}},
                                    json::object{{"id", 1}, {"label", "a"}},
                                    json::object{{"id", 2}}, json::object{{"id", 3}}}},
          {"edges", json::array{}}};
}
void edge(json::object& graph, json::value u, json::value v, json::value weight = 1) {
  auto& edges = graph.at("edges").as_array();
  edges.push_back(json::object{{"id", edges.size()}, {"source", u}, {"target", v}, {"weight", weight}});
}
json::object multigraph() {
  auto value = graph();
  edge(value, 0, 1, 3); edge(value, 1, 0, 5); edge(value, 0, 1, 2);
  edge(value, 1, 1, 7); edge(value, 2, 0, 4);
  for (std::size_t i = 0; i < 5; ++i) {
    auto& e = value.at("edges").as_array()[i].as_object();
    e["timestamp"] = 10 + i;
    e["type"] = i % 2 ? "b" : "a";
  }
  return value;
}
std::shared_ptr<const ViewResult> view(const json::object& input, ViewSpec spec = {}) {
  return make_view(json::serialize(input), spec);
}

// Compare every scalar array's bytes, optional presence, label dictionary and ID
// map. Never compare struct padding or rely on cached pointer identity here.
struct Bytes {
  std::string data;
  template<class T> void scalar(const T& value) {
    static_assert(std::is_arithmetic_v<T>);
    data.append(reinterpret_cast<const char*>(&value), sizeof(value));
  }
  void string(const std::string& value) { scalar(value.size()); data.append(value); }
  template<class T> void column(const std::vector<T>& values) {
    scalar(values.size());
    for (const auto& value : values) scalar(value);
  }
  template<class T> void column(const std::optional<std::vector<T>>& values) {
    scalar(values.has_value()); if (values) column(*values);
  }
  void strings(const std::vector<std::string>& values) {
    scalar(values.size()); for (const auto& value : values) string(value);
  }
  void ids(const std::vector<ExternalId>& values) {
    scalar(values.size());
    for (const auto& id : values) {
      scalar(id.value().index());
      std::visit([&](const auto& value) {
        if constexpr (std::is_same_v<std::decay_t<decltype(value)>, std::string>) string(value);
        else scalar(value);
      }, id.value());
    }
  }
  void weights(const ViewWeights& value) {
    scalar(value.index());
    std::visit([&](const auto& values) {
      if constexpr (std::is_same_v<std::decay_t<decltype(values)>, std::vector<RationalWeight>>) {
        scalar(values.size());
        for (const auto& weight : values) { string(weight.numerator); string(weight.denominator); }
      } else if constexpr (!std::is_same_v<std::decay_t<decltype(values)>, std::monostate>) column(values);
    }, value);
  }
  void mapping(const ViewVertexMap& value) {
    column(value.to_original); column(value.from_original); ids(value.external_ids);
  }
  void tables(const ViewSideTables& t) {
    column(t.vertex_label); column(t.edge_label); column(t.timestamp);
    strings(t.vertex_label_dictionary); strings(t.edge_label_dictionary);
  }
  void summary(const NormalizationSummary& s) {
    scalar(s.projection_applied); scalar(s.directed_projection_applied);
    scalar(s.self_loops_removed); scalar(s.parallel_edges_collapsed);
    scalar(s.weights_cast); scalar(s.vertices); scalar(s.edges);
  }
  void add(const CsrView& v) {
    column(v.offsets); column(v.indices); weights(v.weights); column(v.edge_ids);
    column(v.in_offsets); column(v.in_indices); column(v.in_edge_indices);
    scalar(v.directed); scalar(v.symmetric); scalar(v.simple); scalar(v.sorted);
    mapping(v.vertices); tables(v.side_tables);
  }
  void add(const CooView& v) {
    column(v.src); column(v.dst); weights(v.weights); column(v.edge_ids);
    scalar(v.directed); scalar(v.symmetric); scalar(v.simple); scalar(v.sorted);
    mapping(v.vertices); tables(v.side_tables);
  }
  void add(const BipartiteView& v) { scalar(v.L); add(v.csr); }
  void add(const DenseView& v) {
    scalar(v.rows); scalar(v.columns); weights(v.values); ids(v.row_ids); ids(v.column_ids);
    column(v.row_original); column(v.column_original); column(v.present); column(v.edge_ids); tables(v.side_tables);
  }
  void numbers(const std::vector<HypergraphView::SourceNumber>& values) {
    scalar(values.size());
    for (const auto& value : values) {
      scalar(value.index()); std::visit([&](auto v) { scalar(v); }, value);
    }
  }
  void add(const HypergraphView& v) {
    column(v.he_offsets); column(v.he_vertices); column(v.v_offsets); column(v.v_hyperedges);
    mapping(v.vertices); ids(v.hyperedge_ids); weights(v.vertex_weights); weights(v.hyperedge_weights);
    numbers(v.source_vertex_weights); numbers(v.source_hyperedge_weights);
  }
  void add(const CollectionView& v) {
    scalar(v.members.size()); for (const auto& m : v.members) add(m);
    column(v.member_indices); strings(v.member_ids);
    scalar(v.normalizations.size()); for (const auto& s : v.normalizations) summary(s);
  }
};
std::string bytes(const ViewResult& result) {
  Bytes b;
  b.scalar(result.view.index()); b.summary(result.normalization);
  std::visit([&](const auto& v) { b.add(v); }, result.view);
  return b.data;
}
void spec_tests() {
  const auto a = ViewSpec::from_json(R"({"weights":"f64","kind":"csr","labels":["vertex_label","timestamp"]})");
  const auto b = ViewSpec::from_json(R"({"labels":["timestamp","vertex_label"]})");
  check(a.canonical_json() == b.canonical_json(), "equivalent JSON specs have different keys");
  check(ViewSpec::from_json(a.canonical_json()).canonical_json() == a.canonical_json(), "spec roundtrip failed");
  for (const auto* invalid : {R"({"kind":"oops"})", R"({"kind":"csr","kind":"coo"})",
       R"({"unknown":0})", R"({"edge_ids":1})", R"({"sorted_neighbors":"true"})",
       R"({"labels":["timestamp","timestamp"]})", R"({"labels":["wrong"]})",
       R"({"limits":{"max_edges":-1}})", R"({"limits":{"max_edges":1.0}})",
       R"({"limits":{"extra":2}})", R"({"bipartite_sides":"parameters"})",
       R"({"kind":"dense","weights":"none"})", R"({"kind":"bipartite"})",
       R"({"weight_source":"attribute:a..b"})", R"({"index_width":"i64"})",
       R"({"kind":"coo","direction":"both"})", R"({"parallel_edges":"collapse:mean"})"})
    rejects([&] { ViewSpec::from_json(invalid); }, "invalid spec accepted");
  ViewSpec spec;
  spec.index_width = "i32";
  validate_view_counts(spec, INT32_MAX, INT32_MAX);
  rejects([&] { validate_view_counts(spec, std::uint64_t(INT32_MAX) + 1, 0); }, "i32 vertex overflow accepted");
  rejects([&] { validate_view_counts(spec, 0, std::uint64_t(INT32_MAX) + 1); }, "i32 edge overflow accepted");
  spec.index_width = "u32";
  validate_view_counts(spec, UINT32_MAX, UINT64_MAX);
  rejects([&] { validate_view_counts(spec, std::uint64_t(UINT32_MAX) + 1, 0); }, "u32 overflow accepted");
  spec.limits.max_vertices = 3;
  rejects([&] { view(graph(), spec); }, "vertex limit ignored");
  spec.limits.max_vertices = 4; spec.limits.max_edges = 1;
  auto input = graph(false); edge(input, 0, 1);
  rejects([&] { view(input, spec); }, "expanded edge count limit ignored");
}
void zero_weight_tests() {
  auto input = graph(false);
  edge(input,0,1,0); edge(input,1,2,2); edge(input,2,1,-2); edge(input,2,3,4);
  for (const auto* weights : {"f64","int64_exact","rational_exact"}) {
    auto spec = ViewSpec::from_json(R"({"kind":"coo","parallel_edges":"collapse:sum","edge_ids":true})");
    spec.weights = weights;
    const auto kept = view(input,spec);
    spec.drop_zero_weights = true;
    const auto dropped = view(input,spec);
    const auto& coo = std::get<CooView>(dropped->view);
    check(coo.src == std::vector<VertexIndex>({2,3}) && coo.dst == std::vector<VertexIndex>({3,2}) &&
          *coo.edge_ids == std::vector<EdgeIndex>({3,3}), "zero weights were not removed after parallel collapse");
    check(kept->normalization.edges == 6 && dropped->normalization.edges == 2 &&
          dropped->normalization.parallel_edges_collapsed == 1 && kept.get() != dropped.get(),
          "zero-weight default, count or cache policy changed");
    const auto expected = bytes(*dropped); cache("clear");
    check(bytes(*view(input,spec)) == expected,"zero-weight filtering is not deterministic");
  }
  auto signed_zero = graph(); edge(signed_zero,0,1,-0.0);
  auto spec = ViewSpec::from_json(R"({"drop_zero_weights":true})");
  check(std::get<CsrView>(view(signed_zero,spec)->view).indices.empty(),"negative zero edge survived filtering");
  for (const auto* invalid : {R"({"drop_zero_weights":true,"weights":"none"})",
                            R"({"drop_zero_weights":true,"kind":"hypergraph"})",
                            R"({"drop_zero_weights":1})"})
    rejects([&] { ViewSpec::from_json(invalid); },"invalid zero-weight policy accepted");
  spec.kind = "dense";
  json::object features{{"dataset_id","zero"},{"dimension",1},
    {"vectors",json::array{json::object{{"id",0},{"values",json::array{0}}}}}};
  rejects([&] { view(features,spec); },"zero-weight graph policy applied to feature cells");
}
void self_connection_tests() {
  auto spec = ViewSpec::from_json(R"({"kind":"csr","direction":"symmetrize",
    "self_loops":"one_per_vertex","parallel_edges":"collapse:first","weights":"none",
    "labels":["vertex_label"]})");
  auto input = multigraph(); edge(input,1,1); edge(input,3,3);
  const auto built = view(input,spec);
  const auto& csr = std::get<CsrView>(built->view);
  check(csr.offsets == std::vector<std::uint64_t>({0,3,5,7,8}) &&
        csr.indices == std::vector<VertexIndex>({0,1,2,0,1,0,2,3}), "self connection rows differ");
  check(built->normalization.self_loops_removed == 3 && built->normalization.parallel_edges_collapsed == 2 &&
        built->normalization.edges == 8, "self connection summary differs");
  check(!csr.simple && csr.symmetric && csr.sorted && csr.side_tables.vertex_label.has_value(),
        "self connection flags/vertex labels differ");
  auto kept = spec; kept.self_loops = "keep";
  check(view(input,kept).get() != built.get(), "self connection policy cache collision");
  cache("clear");
  Bytes before,after; before.add(csr); after.add(std::get<CsrView>(view(input,spec)->view));
  check(before.data == after.data, "self connections are not deterministic");
  const auto isolated = view(graph(),spec);
  check(std::get<CsrView>(isolated->view).indices == std::vector<VertexIndex>({0,1,2,3}),
        "isolated vertices did not receive a self connection");
  spec.limits.max_edges = 3;
  rejects([&] { view(graph(),spec); }, "synthetic self connections exceeded edge limit");
  spec.limits.max_edges = UINT64_MAX;
  auto empty = graph(); empty.at("vertices") = json::array{};
  check(std::get<CsrView>(view(empty,spec)->view).offsets == std::vector<std::uint64_t>({0}),
        "empty self connection graph changed shape");
  for (const auto* invalid : {
    R"({"self_loops":"one_per_vertex"})",
    R"({"self_loops":"one_per_vertex","weights":"none","edge_ids":true})",
    R"({"self_loops":"one_per_vertex","weights":"none","labels":["edge_label"]})",
    R"({"self_loops":"one_per_vertex","weights":"none","labels":["timestamp"]})",
    R"({"self_loops":"one_per_vertex","weights":"none","kind":"coo","coo_layout":"records"})",
    R"({"self_loops":"one_per_vertex","weights":"none","kind":"bipartite","bipartite_sides":"attribute:side"})"})
    rejects([&] { ViewSpec::from_json(invalid); }, "ambiguous synthetic-edge metadata accepted");
  std::mt19937 random(7123);
  for (bool directed : {false,true}) for (const auto* direction : {"keep","reverse","symmetrize","both"})
    for (int repeat=0; repeat<16; ++repeat) {
      auto g = graph(directed); std::vector<std::set<VertexIndex>> expected(4);
      for (VertexIndex v=0; v<4; ++v) expected[v].insert(v);
      for (int e=0; e<12; ++e) {
        auto u = static_cast<VertexIndex>(random()%4), v = static_cast<VertexIndex>(random()%4);
        edge(g,u,v);
        if (directed && std::string(direction)=="reverse") std::swap(u,v);
        expected[u].insert(v);
        if (!directed || std::string(direction)=="symmetrize") expected[v].insert(u);
      }
      spec.direction = direction;
      const auto value = view(g,spec); const auto& actual = std::get<CsrView>(value->view);
      for (VertexIndex v=0; v<4; ++v)
        check(std::vector<VertexIndex>(actual.indices.begin()+actual.offsets[v],actual.indices.begin()+actual.offsets[v+1]) ==
              std::vector<VertexIndex>(expected[v].begin(),expected[v].end()), "self connection property differs");
    }
}
void normalization_tests() {
  zero_weight_tests();
  self_connection_tests();
  ViewSpec spec;
  spec.direction = "symmetrize"; spec.self_loops = "drop"; spec.parallel_edges = "collapse:min";
  spec.edge_ids = true; spec.labels = {"vertex_label", "edge_label", "timestamp"};
  auto result = view(multigraph(), spec);
  const auto& csr = std::get<CsrView>(result->view);
  check(csr.offsets == std::vector<std::uint64_t>({0,2,3,4,4}), "symmetric CSR offsets");
  check(csr.indices == std::vector<VertexIndex>({1,2,0,0}), "symmetric CSR neighbors");
  check(std::get<std::vector<double>>(csr.weights) == std::vector<double>({2,4,2,4}), "min weights");
  check(*csr.edge_ids == std::vector<EdgeIndex>({2,4,2,4}), "representative edge IDs");
  check(csr.side_tables.vertex_label_dictionary == std::vector<std::string>({"a","z"}), "label dictionary order");
  check(*csr.side_tables.vertex_label == std::vector<std::uint32_t>({1,0,UINT32_MAX,UINT32_MAX}), "vertex labels alignment");
  check(*csr.side_tables.timestamp == std::vector<std::int64_t>({12,14,12,14}), "timestamps alignment");
  check(result->normalization.self_loops_removed == 1 && result->normalization.parallel_edges_collapsed == 2,
        "loop and duplicate counts must count original records");
  check(result->normalization.projection_applied && result->normalization.vertices == 4 && result->normalization.edges == 4,
        "summary counts");
  check(!csr.directed && csr.symmetric && csr.simple && csr.sorted, "CSR flags");
  check(json::parse(result->normalization_json()).as_object().at("edges") == 4, "summary serialization");
  for (const auto& [rule, expected, origin] : std::vector<std::tuple<std::string,double,EdgeIndex>>{
           {"sum",10,0}, {"min",2,2}, {"max",5,1}, {"first",3,0}}) {
    spec.parallel_edges = "collapse:" + rule;
    auto result = view(multigraph(), spec);
    const auto& data = std::get<CsrView>(result->view);
    check(std::get<std::vector<double>>(data.weights)[0] == expected && (*data.edge_ids)[0] == origin,
          "collapse rule or edge identity changed");
  }
  spec = {};
  spec.edge_ids = true; spec.direction = "both";
  auto both = view(multigraph(), spec);
  const auto& forward = std::get<CsrView>(both->view);
  check(forward.in_offsets && forward.in_indices && forward.in_edge_indices, "transpose missing");
  for (VertexIndex dst = 0; dst < 4; ++dst)
    for (auto i = (*forward.in_offsets)[dst]; i < (*forward.in_offsets)[dst+1]; ++i) {
      const auto e = (*forward.in_edge_indices)[i];
      const auto src = (*forward.in_indices)[i];
      check(e >= forward.offsets[src] && e < forward.offsets[src+1] && forward.indices[e] == dst,
            "transpose lost forward edge alignment");
    }
  spec.direction = "reverse"; spec.kind = "coo"; spec.sorted_neighbors = false;
  const auto reversed = view(multigraph(), spec);
  const auto& coo = std::get<CooView>(reversed->view);
  check(coo.src == std::vector<VertexIndex>({1,0,1,1,0}) && coo.dst == std::vector<VertexIndex>({0,1,0,1,2}),
        "unsorted COO reverse must preserve record order");
  auto loops = graph(false); edge(loops,0,0,2); edge(loops,0,0,3);
  auto kept = view(loops);
  check(std::get<CsrView>(kept->view).indices.size() == 2 && !std::get<CsrView>(kept->view).simple,
        "undirected self loops must not double");
  // Seeded property check over independent edge sets, with loops and duplicates.
  std::mt19937 random(1847);
  spec = {}; spec.direction = "symmetrize"; spec.self_loops = "drop"; spec.parallel_edges = "collapse:sum";
  for (int trial = 0; trial < 75; ++trial) {
    auto input = graph();
    std::map<std::pair<unsigned,unsigned>, double> expected;
    std::uint64_t loops = 0, nonloops = 0;
    for (unsigned i = 0; i < 20; ++i) {
      auto u = random()%4, v = random()%4; const int w = int(random()%21)-10;
      edge(input,u,v,w);
      if (u == v) ++loops;
      else { ++nonloops; expected[std::minmax(u,v)] += w; }
    }
    const auto result = view(input,spec); const auto& out = std::get<CsrView>(result->view);
    check(result->normalization.self_loops_removed == loops &&
              result->normalization.parallel_edges_collapsed == nonloops - expected.size(), "property summary counts");
    check(out.indices.size() == expected.size()*2, "property symmetric arc count");
    for (unsigned u = 0; u < 4; ++u)
      for (auto e = out.offsets[u]; e < out.offsets[u+1]; ++e) {
        const auto v = out.indices[e];
        check(u != v && expected.count(std::minmax(u,v)) &&
              std::get<std::vector<double>>(out.weights)[e] == expected.at(std::minmax(u,v)), "property symmetric weights");
        check(std::binary_search(out.indices.begin()+out.offsets[v], out.indices.begin()+out.offsets[v+1], u),
              "property missing reverse arc");
      }
  }
}
void weight_tests() {
  ViewSpec spec;
  spec.kind = "coo"; spec.weights = "int64_exact";
  for (auto number : {INT64_MIN, INT64_MAX, std::int64_t(9007199254740993LL), std::int64_t(0)}) {
    auto input = graph(); edge(input,0,1,number);
    auto result = view(input,spec);
    check(std::get<std::vector<std::int64_t>>(std::get<CooView>(result->view).weights)[0] == number,
          "exact original integer was rounded");
  }
  auto wide = graph(); edge(wide,0,1,9007199254740993LL);
  rejects([&] { view(wide); }, "default f64 parser changed its existing precision validation");
  auto validation = json::parse(graphmine::runtime::request(json::serialize(json::object{
      {"command","validate"},{"problem","k-core"},{"graph",wide}})));
  check(validation.as_object().contains("error"), "existing problem admitted a wider integer implicitly");
  for (json::value number : {json::value(0.5), json::value(0x1p63), json::value(-0x1p64), json::value(UINT64_MAX)}) {
    auto input = graph(); edge(input,0,1,number);
    rejects([&] { view(input,spec); }, "invalid int64_exact accepted");
  }
  auto input = graph(); edge(input,0,1,-0x1p63);
  check(std::get<std::vector<std::int64_t>>(std::get<CooView>(view(input,spec)->view).weights)[0] == INT64_MIN,
        "double INT64_MIN must be admitted");
  spec.parallel_edges = "collapse:sum";
  for (const auto number : {INT64_MAX, INT64_MIN}) {
    input = graph(); edge(input,0,1,number); edge(input,0,1,number > 0 ? 1 : -1);
    rejects([&] { view(input,spec); }, "int64 sum overflow accepted");
  }
  spec.weights = "f64";
  input = graph(); edge(input,0,1,std::numeric_limits<double>::max()); edge(input,0,1,std::numeric_limits<double>::max());
  rejects([&] { view(input,spec); }, "f64 sum overflow accepted");
  input = graph(); edge(input,0,1,1e16); edge(input,0,1,1.0); edge(input,0,1,-1e16);
  check(std::get<std::vector<double>>(std::get<CooView>(view(input,spec)->view).weights)[0] == 0,
        "sum must preserve original floating-point addition order");
  input = graph(); edge(input,0,1,99);
  input.at("edges").as_array()[0].as_object()["attributes"] = json::object{{"cost", {{"value", 7}}}};
  spec.weight_source = "attribute:cost.value";
  auto result = view(input,spec);
  check(std::get<std::vector<double>>(std::get<CooView>(result->view).weights)[0] == 7, "attribute weight source");
  check(result->normalization.weights_cast == 1, "integer to f64 cast count");
  spec.weight_source = "attribute:cost.missing";
  rejects([&] { view(input,spec); }, "missing attribute weight accepted");
  spec.weight_source = "unit";
  check(std::get<std::vector<double>>(std::get<CooView>(view(input,spec)->view).weights)[0] == 1, "unit weight source");
  spec.weights = "none";
  check(std::holds_alternative<std::monostate>(std::get<CooView>(view(input,spec)->view).weights), "weights none allocated column");
  spec = {}; spec.labels = {"timestamp"};
  rejects([&] { view(input,spec); }, "missing timestamp accepted");
  input.at("edges").as_array()[0].as_object()["timestamp"] = "2026-01-01T00:00:00Z";
  rejects([&] { view(input,spec); }, "timestamp converted without a declared unit");
}
void records_exact_tests() {
  auto probability_spec = ViewSpec::from_json(R"({"kind":"coo","weights":"rational_exact",
    "parallel_edges":"collapse:probability_union","self_loops":"drop"})");
  auto probabilities = graph(true); edge(probabilities,0,1,0.25); edge(probabilities,0,1,0.5);
  edge(probabilities,0,1,0); edge(probabilities,1,2,0); edge(probabilities,1,2,1);
  const auto probability_result = view(probabilities,probability_spec);
  check(std::get<std::vector<RationalWeight>>(std::get<CooView>(probability_result->view).weights) ==
        std::vector<RationalWeight>({{"5","8"},{"1","1"}}), "exact probability union changed");
  check(probability_result->normalization.parallel_edges_collapsed == 3, "probability collapse count changed");
  check(ViewSpec::from_json(probability_spec.canonical_json()).canonical_json() == probability_spec.canonical_json(),
        "probability spec round trip failed");
  auto sum_spec = probability_spec; sum_spec.parallel_edges = "collapse:sum";
  check(view(probabilities,sum_spec).get() != probability_result.get(), "probability and sum cache keys collide");
  for (double invalid : {-0.01,1.01}) {
    auto bad = graph(true); edge(bad,0,0,invalid);
    rejects([&] { view(bad,probability_spec); }, "invalid loop probability escaped validation");
  }
  for (const auto* type : {"none","f64","int64_exact"}) {
    auto invalid = probability_spec; invalid.weights = type;
    rejects([&] { invalid.validate(); }, "probability union accepted inexact weight mode");
  }
  auto special = ViewSpec::from_json(R"({"kind":"coo","parallel_edges":"collapse:sum",
    "sum_arithmetic":"long_double_round_each","require_edge_weights":true})");
  check(ViewSpec::from_json(special.canonical_json()).canonical_json() == special.canonical_json(),
        "extended arithmetic spec did not round trip");
  auto standard = special; standard.sum_arithmetic = "standard";
  auto rounding = graph(true); edge(rounding,0,1,1.0);
  const double half_plus = std::ldexp(1.0,-53)+std::ldexp(1.0,-64);
  edge(rounding,0,1,half_plus);
  const auto extended_result = view(rounding,special), standard_result = view(rounding,standard);
  const auto extended = std::get<std::vector<double>>(std::get<CooView>(extended_result->view).weights)[0];
  const auto ordinary = std::get<std::vector<double>>(std::get<CooView>(standard_result->view).weights)[0];
  check(extended == static_cast<double>(1.0L + half_plus) && ordinary == 1.0 + half_plus,
        "sum arithmetic differs from its declared intermediate");
  check(extended_result.get() != standard_result.get() && extended_result->canonical_spec != standard_result->canonical_spec,
        "sum arithmetic collided in the view cache");
  if (std::numeric_limits<long double>::digits == 64)
    check(extended == 1.0 && ordinary == std::nextafter(1.0,2.0), "extended-rounding boundary was lost");
  rounding = graph(true); edge(rounding,0,1,-0.0);
  check(!std::signbit(std::get<std::vector<double>>(std::get<CooView>(view(rounding,special)->view).weights)[0]),
        "extended accumulation did not start from positive zero");
  check(std::signbit(std::get<std::vector<double>>(std::get<CooView>(view(rounding,standard)->view).weights)[0]),
        "default signed-zero behavior changed");
  rounding = graph(true); edge(rounding,0,0,1);
  rounding.at("edges").as_array()[0].as_object().erase("weight");
  special.self_loops = "drop";
  rejects([&] { view(rounding,special); }, "missing weight on dropped loop accepted");
  special.require_edge_weights = false;
  check(std::get<CooView>(view(rounding,special)->view).src.empty(), "optional-weight default changed");
  for (const auto* invalid : {
    R"({"sum_arithmetic":"unknown"})", R"({"sum_arithmetic":"long_double_round_each"})",
    R"({"sum_arithmetic":"long_double_round_each","parallel_edges":"collapse:sum","weights":"int64_exact"})",
    R"({"require_edge_weights":true,"weight_source":"unit"})",
    R"({"require_edge_weights":true,"weights":"none"})",
    R"({"require_edge_weights":true,"kind":"hypergraph"})"})
    rejects([&] { ViewSpec::from_json(invalid); }, "invalid extended arithmetic/required-weight spec accepted");
  auto input = graph(false);
  edge(input, 2, 0, 1); edge(input, 0, 2, 2); edge(input, 1, 1, 3);
  auto spec = ViewSpec::from_json(R"({"kind":"coo","coo_layout":"records","edge_ids":true})");
  const auto result = view(input, spec);
  const auto& records = std::get<CooView>(result->view);
  check(records.src == std::vector<VertexIndex>({2,0,1}) &&
        records.dst == std::vector<VertexIndex>({0,2,1}), "record COO changed orientation/order/count");
  check(*records.edge_ids == std::vector<EdgeIndex>({0,1,2}), "record COO changed edge identity");
  check(!records.symmetric && !records.directed && !records.simple, "record COO flags");
  check(result->normalization.edges == 3 && result->normalization.parallel_edges_collapsed == 0,
        "record COO collapsed parallel undirected records");
  spec.self_loops = "drop";
  const auto dropped = view(input,spec);
  check(dropped->normalization.self_loops_removed == 1 && dropped->normalization.edges == 2,
        "record COO loop policy");
  auto incompatible = spec; incompatible.direction = "symmetrize";
  rejects([&] { view(input,incompatible); }, "record COO accepted expansion");
  incompatible = spec; incompatible.sorted_neighbors = true;
  rejects([&] { view(input,incompatible); }, "record COO accepted reordering");
  spec = {}; spec.weights = "rational_exact"; spec.parallel_edges = "collapse:sum";
  input = graph(true); edge(input,0,1,1e16); edge(input,0,1,1); edge(input,0,1,-1e16);
  auto exact = view(input,spec);
  check(std::get<std::vector<RationalWeight>>(std::get<CsrView>(exact->view).weights) ==
        std::vector<RationalWeight>({{"1","1"}}), "rational sum rounded through f64");
  input = graph(true); edge(input,0,1,0.1); edge(input,0,1,0.2);
  exact = view(input,spec);
  check(std::get<std::vector<RationalWeight>>(std::get<CsrView>(exact->view).weights) ==
        std::vector<RationalWeight>({{"10808639105689191","36028797018963968"}}),
        "rational sum changed native binary64 interpretation");
  spec.parallel_edges = "collapse:min";
  const auto minimum = view(input,spec);
  check(std::get<std::vector<RationalWeight>>(std::get<CsrView>(minimum->view).weights)[0] ==
        RationalWeight{"3602879701896397","36028797018963968"}, "rational min changed");
  spec.parallel_edges = "collapse:max";
  const auto maximum = view(input,spec);
  check(std::get<std::vector<RationalWeight>>(std::get<CsrView>(maximum->view).weights)[0] ==
        RationalWeight{"3602879701896397","18014398509481984"}, "rational max changed");
  spec.parallel_edges = "collapse:sum";
  input = graph(true); edge(input,0,1,std::numeric_limits<double>::max());
  edge(input,0,1,std::numeric_limits<double>::max());
  exact = view(input,spec);
  check(std::get<std::vector<RationalWeight>>(std::get<CsrView>(exact->view).weights)[0].numerator.size() > 300,
        "rational sum overflowed float64");
  const auto expected = bytes(*exact);
  for (int i=0; i<4; ++i) { cache("clear"); check(bytes(*view(input,spec)) == expected, "rational arrays nondeterministic"); }
  spec.nonnegative_weights = true;
  input = graph(true); edge(input,0,0,-1); spec.self_loops = "drop";
  rejects([&] { view(input,spec); }, "negative rational loop escaped validation");
  input = graph(true); edge(input,0,1,9007199254740993ULL);
  rejects([&] { view(input,spec); }, "rational mode bypassed existing graph parser precision validation");
}
json::object bipartite_graph() {
  auto input = graph(false);
  input["vertices"] = json::array{
      json::object{{"id","r2"},{"attributes",{{"side","right"}}}},
      json::object{{"id","l1"},{"attributes",{{"side","left"}}}},
      json::object{{"id","r1"},{"attributes",{{"side","right"}}}},
      json::object{{"id",0},{"attributes",{{"side","left"}}}},
      json::object{{"id","isolate"},{"attributes",{{"side","left"}}}}};
  edge(input,"r2","l1",3); edge(input,0,"r1",4);
  return input;
}
void bipartite_tests() {
  auto input = bipartite_graph();
  ViewSpec a; a.kind = "bipartite"; a.bipartite_sides = "attribute:side"; a.edge_ids = true;
  auto attributes = view(input,a);
  const auto& bi = std::get<BipartiteView>(attributes->view);
  check(bi.L == 3 && bi.csr.vertices.to_original == std::vector<VertexIndex>({1,3,4,0,2}), "V3 relabeling");
  check(bi.csr.offsets == std::vector<std::uint64_t>({0,1,2,2,3,4}) &&
            bi.csr.indices == std::vector<VertexIndex>({3,4,0,1}), "V3 CSR");
  for (std::size_t v = 0; v < 5; ++v)
    check(bi.csr.vertices.from_original[bi.csr.vertices.to_original[v]] == v, "inverse vertex map");
  auto b = a; b.bipartite_sides = "parameters";
  b.parameters = ViewSpec::Partitions{{ExternalId("isolate"), ExternalId(0), ExternalId("l1")},
                                     {ExternalId("r1"),ExternalId("r2")}};
  check(bytes(*attributes) == bytes(*view(input,b)), "attribute and parameter V3 differ");
  auto permuted = b; std::reverse(permuted.parameters->left_partition.begin(),permuted.parameters->left_partition.end());
  check(permuted.canonical_json() == b.canonical_json(), "partition order changed canonical spec");
  auto bad = b; bad.parameters->right_partition.push_back(ExternalId(0));
  rejects([&] { view(input,bad); }, "overlapping partitions accepted");
  bad = b; bad.parameters->left_partition.pop_back();
  rejects([&] { view(input,bad); }, "incomplete partitions accepted");
  bad = b; bad.parameters->left_partition[0] = ExternalId("0");
  rejects([&] { view(input,bad); }, "string ID coerced to numeric ID");
  auto same_side = input; edge(same_side,"l1",0);
  rejects([&] { view(same_side,a); }, "same-side edge accepted");
  auto missing = input; missing.at("vertices").as_array()[0].as_object().erase("attributes");
  rejects([&] { view(missing,a); }, "missing side accepted");
  a.kind = "dense"; a.weights = "int64_exact";
  const auto dense = view(input,a); const auto& matrix = std::get<DenseView>(dense->view);
  check(matrix.rows == 3 && matrix.columns == 2 &&
        std::get<std::vector<std::int64_t>>(matrix.values) == std::vector<std::int64_t>({3,0,0,4,0,0}), "dense rectangular costs");
  check(matrix.present == std::vector<std::uint8_t>({1,0,0,1,0,0}), "absent dense cells lost");
  check(matrix.row_ids[1] == ExternalId(0) && matrix.column_ids[0] == ExternalId("r2"), "dense IDs");
}
json::object features() {
  return {{"dataset_id","features"},{"dimension",2},
          {"vectors",json::array{json::object{{"id",0},{"values",json::array{1,2}}},
                                  json::object{{"id","0"},{"values",json::array{3,4}}}}}};
}
json::object hypergraph() {
  return {{"graph",{{"id","hyper"}}},
          {"vertices",json::array{json::object{{"id",0},{"weight",9007199254740993LL}},
                                    json::object{{"id","a"}},json::object{{"id","b"}},json::object{{"id","isolate"}}}},
          {"hyperedges",json::array{json::object{{"id","e1"},{"vertices",json::array{"a",0}},{"weight",2}},
                                      json::object{{"id",1},{"vertices",json::array{"b",0}},{"weight",3}}}}};
}
void structured_tests() {
  ViewSpec spec; spec.kind = "dense";
  auto precise = features();
  precise.at("vectors").as_array()[0].as_object()["values"] = json::array{1.0/11.0,-0.0};
  const json::value parsed_precise = precise;
  const auto precise_view = make_view(ParsedViewInput{parsed_precise},spec);
  const auto& precise_values = std::get<std::vector<double>>(std::get<DenseView>(precise_view->view).values);
  check(precise_values[0] == 1.0/11.0 && std::signbit(precise_values[1]),
        "parsed structured numbers changed binary64 value");
  auto result = view(features(),spec); const auto& dense = std::get<DenseView>(result->view);
  check(std::get<std::vector<double>>(dense.values) == std::vector<double>({1,2,3,4}), "features must be row-major");
  check(dense.row_ids == std::vector<ExternalId>({ExternalId(0),ExternalId("0")}), "feature ID types");
  auto invalid = features(); invalid["dimension"] = 3;
  rejects([&] { view(invalid,spec); }, "mismatched feature width accepted");
  invalid["dimension"] = UINT32_MAX;
  rejects([&] { view(invalid,spec); }, "invalid huge width allocated a dense matrix");
  spec.weights = "int64_exact";
  auto large = features(); large.at("vectors").as_array()[0].as_object().at("values").as_array()[0] = 9007199254740993LL;
  check(std::get<std::vector<std::int64_t>>(std::get<DenseView>(view(large,spec)->view).values)[0] == 9007199254740993LL,
        "dense exact value rounded");
  large.at("vectors").as_array()[0].as_object().at("values").as_array()[0] = 0.5;
  rejects([&] { view(large,spec); }, "fractional exact matrix accepted");
  spec = {}; spec.kind = "hypergraph"; spec.weights = "int64_exact";
  const auto hyper = view(hypergraph(),spec); const auto& h = std::get<HypergraphView>(hyper->view);
  check(h.he_offsets == std::vector<std::uint64_t>({0,2,4}) && h.he_vertices == std::vector<VertexIndex>({0,1,0,2}), "hyperedge incidence");
  check(h.v_offsets == std::vector<std::uint64_t>({0,2,3,4,4}) && h.v_hyperedges == std::vector<EdgeIndex>({0,1,0,1}), "vertex incidence");
  check(std::get<std::vector<std::int64_t>>(h.vertex_weights)[0] == 9007199254740993LL, "hypergraph exact weight");
  check(std::get<std::int64_t>(h.source_vertex_weights[0]) == 9007199254740993LL, "hypergraph source number lost");
  auto repeated = hypergraph(); repeated.at("hyperedges").as_array()[0].as_object().at("vertices").as_array().push_back(0);
  rejects([&] { view(repeated,spec); }, "duplicate hyperedge member accepted");
  auto missing = hypergraph(); missing.at("hyperedges").as_array()[0].as_object().at("vertices").as_array()[0] = "missing";
  rejects([&] { view(missing,spec); }, "unknown hyperedge vertex accepted");
  auto g1 = multigraph(), g2 = graph(); g2.at("graph").as_object()["id"] = "second";
  edge(g2,3,0,6);
  json::object collection{{"dataset_id","collection"},{"graphs",json::array{g1,g2}}};
  spec = {}; spec.kind = "collection"; spec.self_loops = "drop"; spec.parallel_edges = "collapse:sum";
  const auto combined = view(collection,spec); const auto& c = std::get<CollectionView>(combined->view);
  check(c.members.size() == 2 && c.member_indices == std::vector<std::uint64_t>({0,1}) && c.member_ids[1] == "second", "collection identities");
  check(c.members[1].indices == std::vector<VertexIndex>({0}) && combined->normalization.vertices == 8,
        "collection member/summary");
  for (const auto& test : std::vector<std::pair<json::object,ViewSpec>>{
         {collection,spec},{features(),ViewSpec::from_json(R"({"kind":"dense"})")},
         {hypergraph(),ViewSpec::from_json(R"({"kind":"hypergraph","weights":"rational_exact"})")}}) {
    cache("clear");
    std::uint64_t first_work=0,first_edges=0;
    for (int repeat=0; repeat<2; ++repeat) {
      std::uint64_t charged=0,edge_charged=0,observations=0;
      ViewBuildOptions options;
      options.charge = [&](std::uint64_t amount) { charged += amount; };
      options.charge_original_edges = [&](std::uint64_t amount) { edge_charged += amount; };
      options.observe = [&](const ViewResult&,bool hit,bool retained) {
        ++observations; check(hit == (repeat != 0) && retained,"structured cache observation differs");
      };
      const auto value = make_view(json::serialize(test.first),test.second,options);
      check(observations == 1 && charged == value->build_work && edge_charged == value->original_edge_work,
            "structured view charge/observation differs");
      if (!repeat) { first_work=charged; first_edges=edge_charged; }
      else check(charged == first_work && edge_charged == first_edges,"structured cache-hit charge differs");
    }
  }
  collection.at("graphs").as_array()[1] = g1;
  rejects([&] { view(collection,spec); }, "duplicate member IDs accepted");
  spec = {}; spec.kind = "dense";
  rejects([&] { view(multigraph(),spec); }, "dense multiedges overwritten");
  spec.parallel_edges = "collapse:min";
  auto square = view(multigraph(),spec);
  check(std::get<std::vector<double>>(std::get<DenseView>(square->view).values)[1] == 2, "dense collapse minimum");
}
void determinism_tests() {
  cache("configure",0); cache("clear");
  std::vector<std::pair<json::object,ViewSpec>> cases;
  for (const auto* kind : {"csr","coo","dense"}) {
    ViewSpec s; s.kind = kind; s.edge_ids = true; s.parallel_edges = "collapse:sum";
    s.labels = {"vertex_label","edge_label","timestamp"}; cases.emplace_back(multigraph(),s);
  }
  ViewSpec s; s.kind = "bipartite"; s.bipartite_sides = "attribute:side"; cases.emplace_back(bipartite_graph(),s);
  s = {}; s.kind = "dense"; cases.emplace_back(features(),s);
  s = {}; s.kind = "hypergraph"; cases.emplace_back(hypergraph(),s);
  s = {}; s.kind = "collection";
  cases.emplace_back(json::object{{"dataset_id","collection"},{"graphs",json::array{multigraph()}}},s);
  for (const auto& [input,spec] : cases) {
    const auto first = view(input,spec);
    for (int iteration = 0; iteration < 6; ++iteration) {
      const auto next = view(input,ViewSpec::from_json(spec.canonical_json()));
      check(first.get() != next.get() && bytes(*first) == bytes(*next), "uncached rebuild is not byte deterministic");
      check(first->snapshot_hash == next->snapshot_hash && first->canonical_spec == next->canonical_spec, "rebuild identity changed");
    }
    check(first->accounted_bytes() >= bytes(*first).size(), "cache undercounts view payload");
  }
  cache("configure"); cache("clear");
}
void cache_tests() {
  cache("configure"); cache("clear");
  auto input = multigraph(); ViewSpec s;
  const auto a = view(input,s), b = view(input,ViewSpec::from_json("{}"));
  check(a.get() == b.get(), "equivalent specs did not reuse immutable view");
  auto different = s; different.direction = "reverse";
  check(view(input,different).get() != a.get(), "different view spec reused stale cache");
  auto changed = input; changed.at("edges").as_array()[0].as_object()["weight"] = 10;
  check(view(changed,s)->snapshot_hash != a->snapshot_hash, "changed weight did not invalidate snapshot");
  auto exact_a = graph(), exact_b = graph();
  edge(exact_a,0,1,9007199254740992LL); edge(exact_b,0,1,9007199254740993LL);
  s.weights = "int64_exact";
  check(view(exact_a,s)->snapshot_hash != view(exact_b,s)->snapshot_hash, "original integer fingerprint collision");
  cache("clear"); s = {};
  const auto retained = view(input,s);
  const auto used = cache("status").at("accounted_bytes").to_number<std::uint64_t>();
  cache("configure",used);
  view(changed,s);
  check(cache("status").at("entries").to_number<unsigned>() == 1 &&
        cache("status").at("evictions").to_number<unsigned>() == 1, "bounded cache failed to evict");
  check(std::get<CsrView>(retained->view).indices.size() == 5, "eviction invalidated active view owner");
  cache("configure"); cache("clear");
  std::vector<std::future<std::shared_ptr<const ViewResult>>> futures;
  for (int i = 0; i < 16; ++i) futures.push_back(std::async(std::launch::async,[&] { return view(input,s); }));
  std::vector<std::shared_ptr<const ViewResult>> results;
  for (auto& f : futures) results.push_back(f.get());
  for (const auto& result : results) check(result.get() == results.front().get(), "concurrent cache builds did not converge");
  check(cache("status").at("entries").to_number<unsigned>() == 1, "concurrent cache duplicate entries");
  cache("clear"); s.weights = "int64_exact";
  auto bad = graph(); edge(bad,0,1,0.5);
  rejects([&] { view(bad,s); }, "invalid cache build accepted");
  check(cache("status").at("entries").to_number<unsigned>() == 0, "failed view retained in cache");
}
}  // namespace
int main(int argc, char** argv) {
  try {
    if (argc != 2) throw std::runtime_error("one test suite is required");
    const std::string suite = argv[1];
    if (suite == "spec") spec_tests();
    else if (suite == "normalization") normalization_tests();
    else if (suite == "weights") weight_tests();
    else if (suite == "records_exact") records_exact_tests();
    else if (suite == "bipartite") bipartite_tests();
    else if (suite == "structured") structured_tests();
    else if (suite == "determinism") determinism_tests();
    else if (suite == "cache") cache_tests();
    else throw std::runtime_error("unknown suite");
    std::cout << suite << ": " << checks << " checks passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "views test failed after " << checks << " checks: " << error.what() << '\n';
    return 1;
  }
}
