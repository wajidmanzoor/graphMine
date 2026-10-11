#include "internal.hpp"

#include <cugraph_c/array.h>
#include <cugraph_c/centrality_algorithms.h>
#include <cugraph_c/core_algorithms.h>
#include <cugraph_c/community_algorithms.h>
#include <cugraph_c/graph.h>
#include <cugraph_c/graph_functions.h>
#include <cugraph_c/labeling_algorithms.h>
#include <cugraph_c/resource_handle.h>
#include <cugraph_c/similarity_algorithms.h>
#include <cugraph_c/traversal_algorithms.h>
#include <cugraph_c/tree_algorithms.h>
#include <cugraph_c/sampling_algorithms.h>
#include <cugraph_c/random.h>
#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <memory>
#include <numeric>
#include <queue>
#include <type_traits>

namespace graphmine::runtime {
namespace {
template<class T, void (*Free)(T*)> using Owned = std::unique_ptr<T, decltype(Free)>;
struct Error {
  cugraph_error_t* value = nullptr;
  ~Error() { if (value) cugraph_error_free(value); }
  void check(cugraph_error_code_t status) {
    if (status != CUGRAPH_SUCCESS)
      throw Failure(status == CUGRAPH_ALLOC_ERROR ? "resource_limit" : "backend_failure",
                    value ? cugraph_error_message(value) : "libcugraph failed without an error message");
  }
};
template<class T> constexpr cugraph_data_type_id_t type_id() { return std::is_same_v<T, double> ? FLOAT64 : INT32; }
struct Array {
  Owned<cugraph_type_erased_device_array_t, cugraph_type_erased_device_array_free> value{nullptr, cugraph_type_erased_device_array_free};
  Owned<cugraph_type_erased_device_array_view_t, cugraph_type_erased_device_array_view_free> view{nullptr, cugraph_type_erased_device_array_view_free};
  template<class T> Array(const cugraph_resource_handle_t* handle, const std::vector<T>& data) {
    Error error; cugraph_type_erased_device_array_t* raw = nullptr;
    const auto status = cugraph_type_erased_device_array_create(handle, data.size(), type_id<T>(), &raw, &error.value);
    value.reset(raw); error.check(status);
    view.reset(cugraph_type_erased_device_array_view(value.get()));
    if (!view) throw Failure("resource_limit", "libcugraph array view allocation failed");
    if (!data.empty()) error.check(cugraph_type_erased_device_array_view_copy_from_host(handle, view.get(), reinterpret_cast<const byte_t*>(data.data()), &error.value));
  }
};
template<class T> std::vector<T> copy(const cugraph_resource_handle_t* handle, cugraph_type_erased_device_array_view_t* view) {
  Owned<cugraph_type_erased_device_array_view_t, cugraph_type_erased_device_array_view_free> owner(view, cugraph_type_erased_device_array_view_free);
  require(view && cugraph_type_erased_device_array_view_type(view) == type_id<T>(), "Unexpected libcugraph result array type");
  std::vector<T> result(cugraph_type_erased_device_array_view_size(view));
  Error error;
  if (!result.empty()) error.check(cugraph_type_erased_device_array_view_copy_to_host(handle, reinterpret_cast<byte_t*>(result.data()), view, &error.value));
  return result;
}
struct Instance {
  DeviceScope device;
  Owned<cugraph_resource_handle_t, cugraph_free_resource_handle> handle{nullptr, cugraph_free_resource_handle};
  std::vector<std::int32_t> ids;
  std::unique_ptr<Array> vertices, starts, ends, weights;
  Owned<cugraph_graph_t, cugraph_graph_free> graph{nullptr, cugraph_graph_free};
  Instance(const WeightedGraph& input, int ordinal, Work& work, bool transposed = false) : device(ordinal) {
    if (input.rows.size() >= INT32_MAX) throw Failure("unsupported_input", "This libcugraph profile requires fewer than INT32_MAX vertices");
    ids.resize(input.rows.size()); std::iota(ids.begin(), ids.end(), 0);
    std::vector<std::int32_t> src, dst;
    std::vector<double> weight;
    for (VertexIndex u = 0; u < input.rows.size(); ++u) for (const auto& arc : input.rows[u]) {
      work.tick(); src.push_back(u); dst.push_back(arc.target); weight.push_back(arc.weight);
    }
    if (src.size() >= INT32_MAX) throw Failure("unsupported_input", "This libcugraph profile requires fewer than INT32_MAX arcs");
    handle.reset(cugraph_create_resource_handle(nullptr));
    if (!handle) throw Failure("resource_limit", "libcugraph resource allocation failed");
    vertices = std::make_unique<Array>(handle.get(), ids); starts = std::make_unique<Array>(handle.get(), src);
    ends = std::make_unique<Array>(handle.get(), dst); weights = std::make_unique<Array>(handle.get(), weight);
    cugraph_graph_properties_t properties{input.directed ? FALSE : TRUE, FALSE};
    cugraph_graph_t* raw = nullptr; Error error;
    const auto status = cugraph_graph_create_with_times_sg(handle.get(), &properties, vertices->view.get(), starts->view.get(), ends->view.get(),
        weights->view.get(), nullptr, nullptr, nullptr, nullptr, transposed ? TRUE : FALSE, TRUE, FALSE, FALSE, FALSE, TRUE, &raw, &error.value);
    graph.reset(raw); error.check(status);
  }
};
bool edgeless(const WeightedGraph& input) {
  return std::all_of(input.rows.begin(), input.rows.end(), [](const auto& row) { return row.empty(); });
}
template<class T> std::vector<T> mapped(const std::vector<std::int32_t>& ids, const std::vector<T>& values, std::size_t n) {
  require(ids.size() == n && values.size() == n, "libcugraph returned an incomplete vertex mapping");
  std::vector<T> result(n); std::vector<bool> seen(n, false);
  for (std::size_t i = 0; i < n; ++i) {
    require(ids[i] >= 0 && static_cast<std::size_t>(ids[i]) < n && !seen[ids[i]], "libcugraph returned an invalid vertex mapping");
    seen[ids[i]] = true; result[ids[i]] = values[i];
  }
  return result;
}
}

std::vector<std::vector<VertexIndex>> cugraph_walks(const WeightedGraph& input, const std::vector<VertexIndex>& starts,
    std::uint64_t length, const std::string& model, double p, double q, std::uint64_t seed, int device, Work& work) {
  if (starts.empty()) return {};
  if (!length || edgeless(input)) {
    work.output(starts.size()); std::vector<std::vector<VertexIndex>> output;
    for (const auto v : starts) output.push_back({v}); return output;
  }
  // cuGraph allocates a dense matrix even when walks reach dead ends early.
  if (length == UINT64_MAX || starts.size() > work.max_output_items / (length+1))
    throw Failure("resource_limit", "Dense GPU walk allocation exceeds the output budget");
  const auto capacity = starts.size()*(length+1); work.output(capacity); work.tick(capacity);
  Instance instance(input, device, work); std::vector<std::int32_t> ids(starts.begin(), starts.end());
  Array sources(instance.handle.get(), ids); Error error; cugraph_rng_state_t* raw_rng = nullptr;
  auto status = cugraph_rng_state_create(instance.handle.get(),seed,&raw_rng,&error.value);
  Owned<cugraph_rng_state_t,cugraph_rng_state_free> rng(raw_rng,cugraph_rng_state_free); error.check(status);
  cugraph_random_walk_result_t* raw = nullptr;
  if (model == "uniform") status = ::cugraph_uniform_random_walks(instance.handle.get(),rng.get(),instance.graph.get(),sources.view.get(),length,&raw,&error.value);
  else if (model == "weighted") status = ::cugraph_biased_random_walks(instance.handle.get(),rng.get(),instance.graph.get(),sources.view.get(),length,&raw,&error.value);
  else throw Failure("unsupported_input", "Native GPU walks support uniform and weighted models; node2vec uses native CPU");
  Owned<cugraph_random_walk_result_t,cugraph_random_walk_result_free> result(raw,cugraph_random_walk_result_free); error.check(status); work.tick(0);
  const auto values = copy<std::int32_t>(instance.handle.get(),cugraph_random_walk_result_get_paths(result.get()));
  if (cugraph_random_walk_result_get_max_path_length(result.get()) != length || values.size() != capacity)
    throw Failure("correctness_mismatch", "libcugraph returned an invalid walk matrix shape");
  std::vector<std::vector<VertexIndex>> output;
  for (std::size_t row = 0; row < starts.size(); ++row) {
    std::vector<VertexIndex> path; bool stopped = false;
    for (std::uint64_t col = 0; col <= length; ++col) {
      work.tick(); const auto v = values[row*(length+1)+col];
      if (v == -1) { stopped = true; continue; }
      if (stopped || v < 0 || static_cast<std::size_t>(v) >= input.rows.size())
        throw Failure("correctness_mismatch", "libcugraph returned an invalid walk vertex or padding");
      path.push_back(v);
    }
    output.push_back(std::move(path));
  }
  return output;
}

std::vector<WeightedSearch> cugraph_shortest_paths(const WeightedGraph& input, const std::vector<VertexIndex>& sources, int device, Work& work) {
  std::vector<WeightedSearch> output;
  if (sources.empty()) return output;
  std::unique_ptr<Instance> instance;
  if (!edgeless(input)) instance = std::make_unique<Instance>(input, device, work);
  const bool all_zero = std::all_of(input.rows.begin(), input.rows.end(), [](const auto& row) {
    return std::all_of(row.begin(), row.end(), [](const Arc& arc) { return arc.weight == 0; });
  });
  const auto n = input.rows.size();
  for (const auto source : sources) {
    work.tick(n);
    WeightedSearch result{std::vector<double>(n, std::numeric_limits<double>::max()), std::vector<std::int64_t>(n, -1)};
    result.distances[source] = 0;
    if (instance) {
      cugraph_paths_result_t* raw = nullptr; Error error;
      // libcugraph SSSP can stall when every stored length is zero. In that
      // case the answer is exactly GPU reachability with zero distance.
      std::unique_ptr<Array> seeds;
      if (all_zero) seeds = std::make_unique<Array>(instance->handle.get(), std::vector<std::int32_t>{static_cast<std::int32_t>(source)});
      const auto status = all_zero
          ? ::cugraph_bfs(instance->handle.get(), instance->graph.get(), seeds->view.get(), FALSE, n, FALSE, TRUE, &raw, &error.value)
          : ::cugraph_sssp(instance->handle.get(), instance->graph.get(), source, std::numeric_limits<double>::max(), FALSE, TRUE, &raw, &error.value);
      Owned<cugraph_paths_result_t, cugraph_paths_result_free> paths(raw, cugraph_paths_result_free); error.check(status);
      const auto ids = copy<std::int32_t>(instance->handle.get(), cugraph_paths_result_get_vertices(paths.get()));
      if (all_zero) {
        const auto hops = mapped(ids, copy<std::int32_t>(instance->handle.get(), cugraph_paths_result_get_distances(paths.get())), n);
        for (std::size_t v = 0; v < n; ++v) if (hops[v] >= 0 && hops[v] < INT32_MAX) result.distances[v] = 0;
      } else result.distances = mapped(ids, copy<double>(instance->handle.get(), cugraph_paths_result_get_distances(paths.get())), n);
      require(result.distances[source] == 0, "libcugraph returned a nonzero source distance");
      // Build an acyclic witness tree from tight edges. Equal-cost zero cycles
      // may have cyclic predecessor choices in the upstream result.
      std::queue<VertexIndex> queue; queue.push(source);
      std::vector<bool> seen(n, false); seen[source] = true;
      while (!queue.empty()) {
        const auto u = queue.front(); queue.pop();
        for (const auto& arc : input.rows[u]) {
          work.tick();
          const auto sum = result.distances[u] + arc.weight, distance = result.distances[arc.target];
          require(distance <= sum, "libcugraph distance violates an edge relaxation");
          if (!seen[arc.target] && distance == sum) {
            seen[arc.target] = true; result.predecessors[arc.target] = u; queue.push(arc.target);
          }
        }
      }
      for (VertexIndex v = 0; v < n; ++v) {
        require(std::isfinite(result.distances[v]) && result.distances[v] >= 0, "libcugraph returned an invalid path distance");
        require((result.distances[v] < std::numeric_limits<double>::max()) == seen[v], "libcugraph distance has no path witness");
      }
    }
    output.push_back(std::move(result));
  }
  return output;
}

std::vector<std::pair<VertexIndex, VertexIndex>> cugraph_spanning_forest(const WeightedGraph& input, bool maximum, int device, Work& work) {
  if (edgeless(input)) return {};
  // A spanning forest depends only on edge-weight ordering. Consecutive ranks
  // preserve that ordering exactly and keep the upstream solver away from
  // extreme magnitudes, negative weights and overflow in its tie adjustment.
  std::map<double, std::size_t> ranks;
  for (const auto& row : input.rows) for (const auto& arc : row) ranks.emplace(arc.weight, 0);
  std::size_t next = 0; for (auto& [weight, rank] : ranks) rank = ++next;
  auto ordered = input;
  for (auto& row : ordered.rows) for (auto& arc : row) arc.weight = maximum ? ranks.size() + 1 - ranks.at(arc.weight) : ranks.at(arc.weight);
  Instance instance(ordered, device, work);
  cugraph_induced_subgraph_result_t* raw = nullptr; Error error;
  const auto status = ::cugraph_minimum_spanning_tree(instance.handle.get(), instance.graph.get(), TRUE, &raw, &error.value);
  Owned<cugraph_induced_subgraph_result_t, cugraph_induced_subgraph_result_free> result(raw, cugraph_induced_subgraph_result_free); error.check(status);
  const auto src = copy<std::int32_t>(instance.handle.get(), cugraph_induced_subgraph_get_sources(result.get()));
  const auto dst = copy<std::int32_t>(instance.handle.get(), cugraph_induced_subgraph_get_destinations(result.get()));
  require(src.size() == dst.size(), "libcugraph forest returned mismatched endpoints");
  std::vector<std::pair<VertexIndex, VertexIndex>> output;
  for (std::size_t i = 0; i < src.size(); ++i) { require(src[i] >= 0 && dst[i] >= 0, "libcugraph forest returned negative endpoints"); output.emplace_back(src[i], dst[i]); }
  return output;
}

std::vector<std::vector<VertexIndex>> cugraph_components(const WeightedGraph& input, bool strong, int device, Work& work) {
  std::vector<std::vector<VertexIndex>> output;
  if (edgeless(input)) { for (VertexIndex v = 0; v < input.rows.size(); ++v) output.push_back({v}); return output; }
  Instance instance(input, device, work);
  cugraph_labeling_result_t* raw = nullptr; Error error;
  const auto status = strong ? ::cugraph_strongly_connected_components(instance.handle.get(), instance.graph.get(), TRUE, &raw, &error.value)
                            : ::cugraph_weakly_connected_components(instance.handle.get(), instance.graph.get(), TRUE, &raw, &error.value);
  Owned<cugraph_labeling_result_t, cugraph_labeling_result_free> result(raw, cugraph_labeling_result_free); error.check(status);
  const auto ids = copy<std::int32_t>(instance.handle.get(), cugraph_labeling_result_get_vertices(result.get()));
  const auto labels = mapped(ids, copy<std::int32_t>(instance.handle.get(), cugraph_labeling_result_get_labels(result.get())), input.rows.size());
  std::map<std::int32_t, std::vector<VertexIndex>> groups;
  for (VertexIndex v = 0; v < labels.size(); ++v) groups[labels[v]].push_back(v);
  for (auto& [label, members] : groups) output.push_back(std::move(members));
  return output;
}

std::vector<double> cugraph_pagerank(const WeightedGraph& input, const std::vector<double>& personalization, double alpha,
                                    double tolerance, std::uint64_t iterations, int device, Work& work) {
  if (edgeless(input)) return personalization;
  Instance instance(input, device, work, true);
  Array seeds(instance.handle.get(), instance.ids), weights(instance.handle.get(), personalization);
  // Reserve a bounded worst-case iteration cost before entering an upstream
  // call that cannot consult Work during its CUDA iterations.
  std::uint64_t cost = input.rows.size();
  for (const auto& row : input.rows) cost += row.size();
  const auto remaining = work.max_candidates - std::min(work.candidates, work.max_candidates);
  const auto allowed = remaining > cost ? std::min(iterations, (remaining - cost) / std::max<std::uint64_t>(1, cost)) : 0;
  if (!allowed) throw Failure("resource_limit", "PageRank GPU iteration budget exhausted");
  cugraph_centrality_result_t* raw = nullptr; Error error;
  const auto status = ::cugraph_personalized_pagerank_allow_nonconvergence(instance.handle.get(), instance.graph.get(), nullptr, nullptr, nullptr, nullptr,
      seeds.view.get(), weights.view.get(), alpha, std::max(tolerance, 1e-12) * 0.25 / input.rows.size(), allowed, TRUE, &raw, &error.value);
  Owned<cugraph_centrality_result_t, cugraph_centrality_result_free> result(raw, cugraph_centrality_result_free); error.check(status);
  const auto used = cugraph_centrality_result_get_num_iterations(result.get());
  require(used <= allowed, "libcugraph exceeded its PageRank iteration bound");
  work.tick(cost * used);
  if (!cugraph_centrality_result_converged(result.get()))
    throw Failure(allowed < iterations ? "resource_limit" : "convergence_failure", "libcugraph PageRank did not converge within its iteration budget");
  const auto ids = copy<std::int32_t>(instance.handle.get(), cugraph_centrality_result_get_vertices(result.get()));
  return mapped(ids, copy<double>(instance.handle.get(), cugraph_centrality_result_get_values(result.get())), input.rows.size());
}

std::vector<double> cugraph_jaccard(const WeightedGraph& input, const std::vector<std::pair<VertexIndex, VertexIndex>>& pairs, int device, Work& work) {
  if (pairs.empty()) return {};
  if (edgeless(input)) return std::vector<double>(pairs.size(), 0);
  Instance instance(input, device, work);
  std::vector<std::int32_t> first, second;
  std::map<std::pair<VertexIndex, VertexIndex>, std::size_t> positions;
  for (std::size_t i = 0; i < pairs.size(); ++i) { first.push_back(pairs[i].first); second.push_back(pairs[i].second); positions[pairs[i]] = i; }
  Array a(instance.handle.get(), first), b(instance.handle.get(), second);
  cugraph_vertex_pairs_t* raw_pairs = nullptr; Error error;
  auto status = cugraph_create_vertex_pairs(instance.handle.get(), instance.graph.get(), a.view.get(), b.view.get(), &raw_pairs, &error.value);
  Owned<cugraph_vertex_pairs_t, cugraph_vertex_pairs_free> selected(raw_pairs, cugraph_vertex_pairs_free); error.check(status);
  cugraph_similarity_result_t* raw = nullptr;
  status = ::cugraph_jaccard_coefficients(instance.handle.get(), instance.graph.get(), selected.get(), FALSE, TRUE, &raw, &error.value);
  Owned<cugraph_similarity_result_t, cugraph_similarity_result_free> result(raw, cugraph_similarity_result_free); error.check(status);
  const auto scores = copy<double>(instance.handle.get(), cugraph_similarity_result_get_similarity(result.get()));
  first = copy<std::int32_t>(instance.handle.get(), cugraph_vertex_pairs_get_first(selected.get()));
  second = copy<std::int32_t>(instance.handle.get(), cugraph_vertex_pairs_get_second(selected.get()));
  require(scores.size() == pairs.size() && first.size() == pairs.size() && second.size() == pairs.size(), "libcugraph returned incomplete pair scores");
  std::vector<double> output(pairs.size()); std::vector<bool> seen(pairs.size(), false);
  for (std::size_t i = 0; i < scores.size(); ++i) {
    const auto found = positions.find({first[i], second[i]});
    require(found != positions.end() && !seen[found->second], "libcugraph returned an invalid pair mapping");
    seen[found->second] = true; output[found->second] = scores[i];
  }
  return output;
}
std::vector<double> cugraph_betweenness(const WeightedGraph& input, int device, Work& work) {
  if (input.rows.size() < 3 || edgeless(input)) return std::vector<double>(input.rows.size(), 0);
  std::uint64_t per_source = input.rows.size();
  for (const auto& row : input.rows) per_source += row.size();
  const auto remaining = work.max_candidates - std::min(work.candidates, work.max_candidates);
  if (input.rows.size() > remaining / per_source) throw Failure("resource_limit", "All-source betweenness exceeds the GPU work budget");
  work.tick(per_source * input.rows.size());
  Instance instance(input, device, work); cugraph_centrality_result_t* raw = nullptr; Error error;
  const auto status = ::cugraph_betweenness_centrality(instance.handle.get(), instance.graph.get(), nullptr, FALSE, FALSE, TRUE, &raw, &error.value);
  Owned<cugraph_centrality_result_t, cugraph_centrality_result_free> result(raw, cugraph_centrality_result_free); error.check(status);
  const auto ids = copy<std::int32_t>(instance.handle.get(), cugraph_centrality_result_get_vertices(result.get()));
  auto values = mapped(ids, copy<double>(instance.handle.get(), cugraph_centrality_result_get_values(result.get())), input.rows.size());
  if (!input.directed) for (auto& value : values) value *= 2;
  work.tick(0); return values;
}
std::vector<std::uint32_t> cugraph_core_numbers(const WeightedGraph& input, int device, Work& work) {
  if (edgeless(input)) return std::vector<std::uint32_t>(input.rows.size(), 0);
  Instance instance(input, device, work); cugraph_core_result_t* raw = nullptr; Error error;
  const auto status = ::cugraph_core_number(instance.handle.get(), instance.graph.get(), K_CORE_DEGREE_TYPE_OUT, TRUE, &raw, &error.value);
  Owned<cugraph_core_result_t, cugraph_core_result_free> result(raw, cugraph_core_result_free); error.check(status);
  const auto ids = copy<std::int32_t>(instance.handle.get(), cugraph_core_result_get_vertices(result.get()));
  const auto values = mapped(ids, copy<std::int32_t>(instance.handle.get(), cugraph_core_result_get_core_numbers(result.get())), input.rows.size());
  std::vector<std::uint32_t> output;
  for (const auto value : values) { require(value >= 0, "libcugraph returned a negative core number"); output.push_back(value); }
  return output;
}
std::vector<std::uint32_t> cugraph_truss_numbers(const WeightedGraph& input,
    const std::vector<std::pair<VertexIndex, VertexIndex>>& edges, int device, Work& work) {
  std::vector<std::uint32_t> values(edges.size(), 2);
  if (edges.empty()) return values;
  Instance instance(input, device, work);
  std::map<std::pair<VertexIndex, VertexIndex>, std::size_t> positions;
  for (std::size_t e = 0; e < edges.size(); ++e) positions[edges[e]] = e;
  std::size_t maximum_degree = 0;
  for (const auto& row : input.rows) maximum_degree = std::max(maximum_degree, row.size());
  std::vector<bool> previous(edges.size(), true);
  for (std::size_t k = 3; k <= maximum_degree + 1; ++k) {
    work.tick(input.rows.size() + edges.size());
    cugraph_induced_subgraph_result_t* raw = nullptr; Error error;
    const auto status = ::cugraph_k_truss_subgraph(instance.handle.get(), instance.graph.get(), k, TRUE, &raw, &error.value);
    Owned<cugraph_induced_subgraph_result_t, cugraph_induced_subgraph_result_free> result(raw, cugraph_induced_subgraph_result_free); error.check(status);
    const auto sources = copy<std::int32_t>(instance.handle.get(), cugraph_induced_subgraph_get_sources(result.get()));
    const auto targets = copy<std::int32_t>(instance.handle.get(), cugraph_induced_subgraph_get_destinations(result.get()));
    require(sources.size() == targets.size(), "libcugraph returned inconsistent truss endpoints");
    if (sources.empty()) break;
    std::vector<bool> current(edges.size(), false);
    for (std::size_t i = 0; i < sources.size(); ++i) {
      work.tick(); require(sources[i] >= 0 && targets[i] >= 0 && sources[i] != targets[i], "libcugraph returned invalid truss endpoints");
      const std::pair<VertexIndex, VertexIndex> edge = std::minmax(sources[i], targets[i]);
      const auto found = positions.find(edge);
      require(found != positions.end() && previous[found->second], "libcugraph truss output lost original edge identity or nesting");
      values[found->second] = k; current[found->second] = true;
    }
    previous = std::move(current);
  }
  return values;
}
}  // namespace graphmine::runtime
