#include "legacy_normalizers.hpp"
#include "graphmine/views.hpp"
#include <cstring>
#include <iostream>
#include <limits>
#include "../representation_cache.hpp"

namespace gm = graphmine;
namespace rt = graphmine::runtime;
namespace old = graphmine::legacy_test;
template<class T> void equal_bytes(const std::vector<T>& a, const std::vector<T>& b) {
  if (a.size() != b.size() || (!a.empty() && std::memcmp(a.data(), b.data(), a.size()*sizeof(T))))
    throw std::runtime_error("normalizer array bytes differ");
}
rt::Work unlimited() {
  rt::Work w;
  w.max_candidates = w.max_output_items = UINT64_MAX;
  w.timeout_seconds = std::numeric_limits<double>::infinity();
  return w;
}
std::size_t verify(const gm::Graph& graph) {
  auto expected = old::simple(graph, {true});
  auto current = graph.simple_undirected({true});
  gm::ViewSpec spec;
  spec.direction = "symmetrize";
  spec.self_loops = "drop";
  spec.parallel_edges = "collapse:first";
  spec.weights = "none";
  const auto result = gm::make_view(graph, spec);
  const auto& csr = std::get<gm::CsrView>(result->view);
  equal_bytes(expected.csr.offsets, csr.offsets);
  equal_bytes(expected.csr.neighbors, csr.indices);
  equal_bytes(expected.csr.offsets, current.csr.offsets);
  equal_bytes(expected.csr.neighbors, current.csr.neighbors);
  for (const auto* summary : std::initializer_list<const gm::NormalizationSummary*>{&result->normalization, &current.normalization}) {
    if (summary->directed_projection_applied != expected.normalization.directed_projection_applied ||
        summary->self_loops_removed != expected.normalization.self_loops_removed ||
        summary->parallel_edges_collapsed != expected.normalization.parallel_edges_collapsed)
      throw std::runtime_error("normalization counts differ");
  }
  std::size_t profiles = 1;
  for (bool weighted : {false, true})
    for (const auto* aggregation : {"first", "min", "max", "sum"})
      for (const auto* direction : {"outgoing", "incoming", "undirected_projection"}) {
        spec.weights = "f64";
        spec.weight_source = weighted ? "edge.weight" : "unit";
        spec.parallel_edges = std::string("collapse:") + aggregation;
        spec.direction = std::string(direction) == "incoming" ? "reverse" :
                         std::string(direction) == "undirected_projection" ? "symmetrize" : "keep";
        auto work = unlimited(), current_work = unlimited();
        const auto reference = old::weighted(graph, weighted, false, aggregation, direction, work);
        const auto actual = rt::weighted_graph(graph, weighted, false, aggregation, direction, current_work);
        if (work.candidates != current_work.candidates) throw std::runtime_error("work cost differs");
        const auto view = gm::make_view(graph, spec);
        const auto& data = std::get<gm::CsrView>(view->view);
        if (data.directed != reference.directed || actual.directed != reference.directed)
          throw std::runtime_error("direction differs");
        std::vector<std::uint64_t> offsets{0};
        std::vector<gm::VertexIndex> indices;
        std::vector<double> weights;
        for (std::size_t u = 0; u < reference.rows.size(); ++u) {
          if (reference.rows[u].size() != actual.rows.at(u).size()) throw std::runtime_error("row length differs");
          for (std::size_t i = 0; i < reference.rows[u].size(); ++i) {
            const auto& edge = reference.rows[u][i];
            const auto& next = actual.rows[u][i];
            if (edge.target != next.target || std::memcmp(&edge.weight, &next.weight, sizeof(double)))
              throw std::runtime_error("weighted adapter bytes differ");
            indices.push_back(edge.target);
            weights.push_back(edge.weight);
          }
          offsets.push_back(indices.size());
        }
        equal_bytes(offsets, data.offsets);
        equal_bytes(indices, data.indices);
        equal_bytes(weights, std::get<std::vector<double>>(data.weights));
        ++profiles;
      }
  return profiles;
}
void edge_cases() {
  for (bool directed : {false, true}) {
    for (const std::vector<double> weights : {std::vector<double>{-0.0, 0.0, 1e16, -1e16, 1.0},
                                            std::vector<double>{1, 3, 2, 1, 4}}) {
      gm::CanonicalGraphInput input;
      input.graph = {"budget-cases", directed, true, true};
      for (int i = 0; i < 4; ++i) input.vertices.push_back({gm::ExternalId(i)});
      for (std::size_t i = 0; i < weights.size(); ++i) {
        gm::EdgeRecord e;
        e.id = gm::ExternalId(std::int64_t(i)); e.source = 0; e.target = i == 4 ? 0 : 1; e.weight = weights[i];
        input.edges.push_back(e);
      }
      const gm::Graph graph(input);
      verify(graph);
      for (bool weighted : {false, true}) for (bool nonnegative : {false, true})
        for (const char* aggregation : {"sum", "min", "max", "first"})
          for (const char* direction : {"outgoing", "incoming", "undirected_projection"})
            for (unsigned budget = 0; budget < 25; ++budget) {
              rt::representation_cache_request({{"command", "representation_cache"}, {"action", "clear"}});
              // Repeat on warm storage, preserving total candidate admission.
              for (int repeat = 0; repeat < 2; ++repeat) {
                auto a = unlimited(), b = unlimited(); a.max_candidates = b.max_candidates = budget;
                std::string expected, actual;
                try { (void)old::weighted(graph, weighted, nonnegative, aggregation, direction, a); }
                catch (const std::exception& e) { expected = e.what(); }
                try { (void)rt::weighted_graph(graph, weighted, nonnegative, aggregation, direction, b); }
                catch (const std::exception& e) { actual = e.what(); }
                if (expected != actual || (expected.empty() && a.candidates != b.candidates))
                  throw std::runtime_error("budget/rejection differs: " + expected + " / " + actual);
              }
            }
    }
  }
  // An ignored nonfinite C++ weight must not break an unweighted view/hash.
  auto input = gm::Graph::from_edges("ignored-weight", {0,1}, {{0,1}}).canonical();
  input.edges[0].weight = std::numeric_limits<double>::infinity();
  const gm::Graph graph(input);
  equal_bytes(graph.simple_undirected().csr.neighbors, old::simple(graph).csr.neighbors);
  input.graph.allows_parallel_edges = true;
  input.edges[0].weight = std::numeric_limits<double>::max();
  auto duplicate = input.edges[0]; duplicate.id = 1; input.edges.push_back(duplicate);
  const gm::Graph overflowing(input);
  auto a = unlimited(), b = unlimited(); std::string expected, actual;
  try { (void)old::weighted(overflowing, true, false, "sum", "outgoing", a); }
  catch (const std::exception& e) { expected = e.what(); }
  try { (void)rt::weighted_graph(overflowing, true, false, "sum", "outgoing", b); }
  catch (const std::exception& e) { actual = e.what(); }
  if (actual != expected || actual.empty() || a.candidates != b.candidates)
    throw std::runtime_error("overflow rejection/work differs");
  std::cout << "9600 cold/warm budget and rejection comparisons passed\n";
}
int main(int argc, char**) {
  std::string line;
  std::size_t datasets = 0, profiles = 0;
  try {
    if (argc > 1) { edge_cases(); return 0; }
    while (std::getline(std::cin, line)) {
      const auto item = rt::strict_json(line).as_object();
      const auto name = rt::string(item.at("dataset"), "dataset");
      try {
        const auto count = verify(rt::parse_graph(item.at("graph")));
        std::cout << rt::json::serialize(rt::json::object{{"dataset", name}, {"profiles", count}, {"equal", true}}) << '\n';
        ++datasets;
        profiles += count;
      } catch (const std::exception& e) { throw std::runtime_error(name + ": " + e.what()); }
    }
    std::cerr << datasets << " datasets, " << profiles << " equivalent normalizer profiles\n";
    return datasets ? 0 : 2;
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
