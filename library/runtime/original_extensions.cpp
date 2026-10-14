#include <cmath>
#include <mutex>
#include <tuple>

#include "family_util.hpp"

#ifdef GRAPHMINE_NATIVE_ORIGINAL_EXTENSIONS
#include "graphmine/problems/community_detection.hpp"
#include "graphmine/problems/dynamic_triangle_counting.hpp"
#include "graphmine/problems/graph_motifs.hpp"
#include "graphmine/problems/maximal_bicliques.hpp"
#include "graphmine/problems/quasi_cliques.hpp"
#include "graphmine/problems/repaired_algorithms.hpp"
#include "graphmine/problems/subgraph_isomorphism.hpp"
#include "graphmine/problems/temporal_motif_mining.hpp"
#endif

namespace graphmine::runtime {
namespace {
using namespace family_util;
using Pair = std::pair<ExternalId, ExternalId>;
const std::map<std::string, std::vector<std::string>> registrations{
    {"community-detection", {"gleiden", "parallel-louvain", "parallel-leiden", "parallel-leiden-plus"}},
    {"quasi-cliques", {"cuqc"}}, {"maximal-bicliques", {"cumbe"}},
    {"maximal-biclique-counting", {"mbe-gpu"}}, {"dynamic-triangle-counting", {"edtc"}},
    {"motif-counting", {"graphminer", "graphset", "dumato"}},
    {"subgraph-isomorphism", {"gmatch"}}, {"temporal-motifs", {"everest", "mayura"}},
    {"connected-components", {"ecl-scc"}}, {"transitive-closure", {"gdlog"}},
    {"butterfly-counting", {"graphminer", "gamma-butterfly"}}, {"k-truss", {"acctd"}},
    {"densest-subgraph", {"cds"}}, {"personalized-pagerank", {"kpar"}},
    {"group-steiner-tree", {"gpu4gst"}}, {"influence-maximization", {"superfuser"}}};
void certify(bool condition, const std::string& message) {
  if (!condition) throw Failure("correctness_mismatch", message);
}
bool nonempty(const json::object& args, const char* key) {
  return args.contains(key) && !args.at(key).is_null() &&
         (!args.at(key).is_array() || !args.at(key).as_array().empty());
}
std::string text_arg(const json::object& args, const char* key, const char* initial) {
  return args.contains(key) ? string(args.at(key), key) : initial;
}
Graph normalized(const Graph& graph, bool simple, bool unit, Work& work) {
  auto input = graph.canonical();
  input.edges.clear();
  std::set<Pair> seen;
  for (auto edge : graph.canonical().edges) {
    work.tick();
    if (edge.source == edge.target) continue;
    auto a = edge.source, b = edge.target;
    if (!graph.directed() && b < a) std::swap(a, b);
    if (simple && !seen.emplace(a, b).second) continue;
    if (unit) { edge.weight.reset(); edge.original_weight.reset(); }
    input.edges.push_back(std::move(edge));
  }
  return Graph(std::move(input));
}
bool is_simple(const Graph& graph) {
  std::set<Pair> seen;
  for (const auto& edge : graph.canonical().edges) {
    auto a = edge.source, b = edge.target;
    if (a == b) return false;
    if (!graph.directed() && b < a) std::swap(a, b);
    if (!seen.emplace(a, b).second) return false;
  }
  return true;
}
json::array external_ids(const std::vector<ExternalId>& ids) {
  json::array result;
  for (const auto& id : ids) result.push_back(id_json(id));
  return result;
}
Exact exact_result_field(const json::object& row, const char* key) {
  const auto& fraction = row.at(std::string(key) + "_exact").as_object();
  return Exact(Integer(string(fraction.at("numerator"), "numerator"))) /
         Integer(string(fraction.at("denominator"), "denominator"));
}

#ifdef GRAPHMINE_NATIVE_ORIGINAL_EXTENSIONS
// These adapters include artifacts with process-global CUDA/host state.
std::timed_mutex extension_mutex;
std::unique_lock<std::timed_mutex> admission(Work& work) {
  work.tick(0);
  std::unique_lock<std::timed_mutex> lock(extension_mutex, std::defer_lock);
  const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - work.started).count();
  if (!lock.try_lock_for(std::chrono::duration<double>(std::min(86400.0, work.timeout_seconds - elapsed))))
    throw Failure("resource_limit", "Original GPU adapter admission timed out");
  work.tick(0);
  return lock;
}
template<class T> T checked(ExecutionResult<T> result, Work& work) {
  if (!result.ok()) {
    const auto code = result.status().code();
    throw Failure(code == StatusCode::resource_exhausted ? "resource_limit"
                  : code == StatusCode::unsupported ? "unsupported_input"
                  : code == StatusCode::backend_unavailable ? "backend_unavailable"
                  : code == StatusCode::correctness_mismatch ? "correctness_mismatch" : "backend_failure",
                  result.status().message());
  }
  work.tick(0);
  return std::move(result.value());
}
template<class T> T isolated(int device, Work& work) {
  T options;
  options.execution.device_ids = {device};
  const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - work.started).count();
  work.tick(0);
  options.timeout_seconds = static_cast<std::uint32_t>(std::max(1.0, std::min(86400.0, std::ceil(work.timeout_seconds - elapsed))));
  return options;
}
CommunityDetectionOptions community_options(const json::object& args, const std::string& backend, int device) {
  CommunityDetectionOptions options;
  options.backend = backend == "gleiden" ? CommunityDetectionBackend::gleiden
                    : backend == "parallel-louvain" ? CommunityDetectionBackend::parallel_louvain
                    : backend == "parallel-leiden" ? CommunityDetectionBackend::parallel_leiden
                    : CommunityDetectionBackend::parallel_leiden_plus;
  options.resolution = args.contains("resolution") ? number(args.at("resolution"), "resolution") : 1;
  options.execution.device_ids = {device};
  return options;
}
QuasiCliqueOptions quasi_options(const json::object& args, int device) {
  QuasiCliqueOptions options;
  options.backend = QuasiCliqueBackend::cuqc;
  options.minimum_degree_ratio = number(args.at("gamma"), "gamma");
  options.minimum_size = uint(args.at("minimum_size"), "minimum_size");
  options.execution.device_ids = {device};
  return options;
}
MaximalBicliqueOptions biclique_options(const json::object& args, int device) {
  MaximalBicliqueOptions options;
  options.backend = MaximalBicliqueBackend::cumbe;
  for (const auto& id : args.at("left_partition").as_array()) options.left_partition.push_back(external_id(id));
  options.minimum_left_size = natural(args, "minimum_left_size", 1, 1);
  options.minimum_right_size = natural(args, "minimum_right_size", 1, 1);
  options.optional_outputs = MaximalBicliqueOptionalOutput::total_count;
  options.execution.device_ids = {device};
  return options;
}
GraphMotifOptions motif_options(const json::object& args, const std::string& backend, int device) {
  GraphMotifOptions options;
  options.backend = backend == "graphminer" ? GraphMotifBackend::graphminer
                    : backend == "graphset" ? GraphMotifBackend::graphset : GraphMotifBackend::dumato;
  options.induced = boolean(args, "induced", false);
  options.occurrence_identity = text_arg(args, "occurrence_identity", "unique_vertex_set_and_mapping_class") == "all_embeddings"
                                  ? MotifOccurrenceIdentity::all_embeddings : MotifOccurrenceIdentity::unique_vertex_set_and_mapping_class;
  options.execution.device_ids = {device};
  return options;
}
std::vector<Graph> motif_graphs(const json::object& args) {
  std::vector<Graph> result;
  for (const auto& record : args.at("motifs").as_array()) result.push_back(parse_graph(record));
  return result;
}
SubgraphIsomorphismOptions match_options(int device) {
  SubgraphIsomorphismOptions options;
  options.backend = SubgraphIsomorphismBackend::gmatch;
  options.respect_vertex_labels = false;
  options.execution.device_ids = {device};
  return options;
}
TemporalMotifOptions temporal_options(const json::object& args, const std::string& backend, int device) {
  TemporalMotifOptions options;
  options.backend = backend == "everest" ? TemporalMotifBackend::everest : TemporalMotifBackend::mayura;
  const double span = number(args.at("maximum_duration_seconds"), "maximum_duration_seconds");
  require(span >= 0 && span <= INT32_MAX && std::trunc(span) == span, "Original temporal kernels require an integral duration in [0, INT32_MAX]");
  options.max_time_span = static_cast<std::int64_t>(span);
  options.execution.device_ids = {device};
  return options;
}
std::string temporal_profile(const json::object& args) {
  if (boolean(args, "allow_equal_timestamps", false) || boolean(args, "temporal_induced", false))
    return "Original temporal kernels require strict timestamps and non-induced events";
  const auto spec = object(args.at("temporal_motif"), "temporal_motif");
  if (nonempty(spec, "vertex_predicates") || nonempty(spec, "edge_predicates")) return "Original temporal kernels do not support attribute predicates";
  const auto query = parse_graph(spec.at("graph"));
  const auto& e = query.canonical().edges;
  if (!query.directed() || query.vertex_count() != 3 || e.size() != 3 || !is_simple(query) ||
      e[0].target != e[1].source || e[0].source != e[2].source || e[1].target != e[2].target)
    return "Original temporal kernels require ordered A->B, B->C, A->C feed-forward events";
  if (spec.contains("order")) {
    bool before[3][3]{};
    for (const auto& raw : spec.at("order").as_array()) {
      const auto& pair = raw.as_array();
      require(pair.size() == 2, "Temporal order needs edge-ID pairs");
      int a = -1, b = -1;
      for (int i = 0; i < 3; ++i) {
        if (e[i].id == external_id(pair[0])) a = i;
        if (e[i].id == external_id(pair[1])) b = i;
      }
      require(a >= 0 && b >= 0, "Unknown temporal order edge");
      before[a][b] = true;
    }
    for (int k = 0; k < 3; ++k) for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j)
      before[i][j] |= before[i][k] && before[k][j];
    for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j)
      if (before[i][j] != (i < j)) return "Original temporal kernels require t1 < t2 < t3";
  }
  return {};
}
GroupSteinerTreeOptions steiner_options(const json::object& args, int device, Work& work) {
  auto options = isolated<GroupSteinerTreeOptions>(device, work);
  for (const auto& group : args.at("groups").as_array()) {
    std::vector<ExternalId> ids;
    for (const auto& id : group.as_array()) ids.push_back(external_id(id));
    options.groups.push_back(std::move(ids));
  }
  if (nonempty(args, "required_vertices"))
    for (const auto& id : args.at("required_vertices").as_array()) options.groups.push_back({external_id(id)});
  return options;
}
PersonalizedPageRankOptions ppr_options(const Graph& graph, const json::object& args, int device, Work& work) {
  auto options = isolated<PersonalizedPageRankOptions>(device, work);
  options.seed_vertex = external_id(args.at("seed_vertices").as_array().front());
  options.top_k = graph.vertex_count(); // Full scores remain available to downstream steps.
  options.epsilon = args.contains("epsilon") ? number(args.at("epsilon"), "epsilon") : .01;
  const auto seed = natural(args, "random_seed", 42);
  require(seed <= INT32_MAX, "kPAR random_seed must fit signed int32");
  options.random_seed = seed;
  return options;
}
InfluenceMaximizationOptions influence_options(const json::object& args, int device, Work& work) {
  auto options = isolated<InfluenceMaximizationOptions>(device, work);
  const auto k = uint(args.at("seed_set_size"), "seed_set_size"), samples = natural(args, "sample_count", 256);
  require(k <= UINT32_MAX && samples <= UINT32_MAX, "Influence counts must fit uint32");
  options.seed_set_size = k;
  options.sample_count = samples;
  options.random_seed = natural(args, "random_seed", 42);
  return options;
}
std::vector<TriangleUpdate> updates(const json::object& args) {
  std::vector<TriangleUpdate> result;
  for (const auto& raw : args.at("updates").as_array()) {
    const auto row = object(raw, "triangle update");
    fields(row, {"kind", "source", "target"}, {"kind", "source", "target"});
    const auto kind = choice(row, "kind", "insert_edge", {"insert_edge", "delete_edge"});
    result.push_back({kind == "insert_edge" ? TriangleUpdateKind::insert_edge : TriangleUpdateKind::delete_edge,
                      external_id(row.at("source")), external_id(row.at("target"))});
  }
  return result;
}
#endif
} // namespace

bool original_extension_backend(const std::string& operation, const std::string& backend) {
  const auto found = registrations.find(operation);
  return found != registrations.end() && std::find(found->second.begin(), found->second.end(), backend) != found->second.end();
}
json::array original_extension_backends(const std::string& operation) {
  const auto found = registrations.find(operation);
  if (found == registrations.end()) return {};
  std::map<std::string, bool> compiled;
#ifdef GRAPHMINE_NATIVE_ORIGINAL_EXTENSIONS
  auto add = [&](const auto& entries) { for (const auto& entry : entries) compiled[entry.id] = entry.compiled; };
  if (operation == "community-detection") add(CommunityDetection::backends());
  else if (operation == "quasi-cliques") add(QuasiCliques::backends());
  else if (operation == "maximal-bicliques") add(MaximalBicliques::backends());
  else if (operation == "maximal-biclique-counting") add(MaximalBicliqueCounting::backends());
  else if (operation == "dynamic-triangle-counting") add(DynamicTriangleCounting::backends());
  else if (operation == "motif-counting") add(GraphMotifs::backends());
  else if (operation == "subgraph-isomorphism") add(SubgraphIsomorphism::backends());
  else if (operation == "temporal-motifs") add(TemporalMotifMining::backends());
  else if (operation == "connected-components") add(ConnectedComponents::backends());
  else if (operation == "transitive-closure") add(TransitiveClosure::backends());
  else if (operation == "butterfly-counting") add(ButterflyCounting::backends());
  else if (operation == "k-truss") add(KTruss::backends());
  else if (operation == "densest-subgraph") add(DensestSubgraph::backends());
  else if (operation == "personalized-pagerank") add(PersonalizedPageRank::backends());
  else if (operation == "group-steiner-tree") add(GroupSteinerTree::backends());
  else if (operation == "influence-maximization") add(InfluenceMaximization::backends());
#endif
  json::array result;
  for (const auto& id : found->second)
    result.push_back(json::object{{"id", id}, {"device", "gpu"}, {"compiled", compiled[id]},
                                 {"execution", "original native CUDA adapter; runtime profile and output checks"}});
  return result;
}

std::string original_extension_support(const std::string& operation, const std::string& backend,
                                       const Graph& graph, const json::object& args, Work& work) {
#ifdef GRAPHMINE_NATIVE_ORIGINAL_EXTENSIONS
  const auto report = [](SupportReport value) { return value.supported ? std::string{} : value.reason; };
  const auto simple = normalized(graph, true, true, work);
  if (operation == "community-detection") {
    if (text_arg(args, "quality_function", "modularity") != "modularity" ||
        text_arg(args, "solution_quality", "heuristic") != "heuristic" ||
        text_arg(args, "weight_mode", "unweighted") != "unweighted" || natural(args, "seed", 0) != 0)
      return "Original community GPUs support unweighted heuristic modularity and seed=0; exact, CPM, weighted or custom-seed requests use CPU";
    return report(CommunityDetection(community_options(args, backend, 0)).supports(simple));
  }
  if (operation == "quasi-cliques") {
    if (!boolean(args, "maximal_only", true) || nonempty(args, "maximum_size")) return "cuQC supports maximal quasi-cliques without a maximum_size bound";
    return report(QuasiCliques(quasi_options(args, 0)).supports(simple));
  }
  if (operation == "maximal-bicliques") {
    if (nonempty(args, "result_limit")) return "cuMBE runtime verification requires an uncapped biclique collection";
    return report(MaximalBicliques(biclique_options(args, 0)).supports(simple));
  }
  if (operation == "maximal-biclique-counting") return report(MaximalBicliqueCounting(isolated<MaximalBicliqueCountingOptions>(0, work)).supports(simple));
  if (operation == "dynamic-triangle-counting") {
    DynamicTriangleOptions options;
    return report(DynamicTriangleCounting(options).supports(simple, updates(args)));
  }
  if (operation == "motif-counting") return report(GraphMotifs(motif_options(args, backend, 0)).supports(simple, motif_graphs(args)));
  if (operation == "subgraph-isomorphism") {
    const auto query = parse_graph(args.at("query_graph"));
    if (boolean(args, "induced", false) || nonempty(args, "vertex_predicates") || nonempty(args, "edge_predicates") || nonempty(args, "result_limit") || !is_simple(graph) || !is_simple(query))
      return "gMatch runtime profile requires simple non-induced graphs, no predicates and an uncapped result";
    return report(SubgraphIsomorphism(match_options(0)).supports(graph, query));
  }
  if (operation == "temporal-motifs") {
    const auto reason = temporal_profile(args);
    if (!reason.empty()) return reason;
    const auto span = number(args.at("maximum_duration_seconds"), "maximum_duration_seconds");
    if (span < 0 || span > INT32_MAX || std::trunc(span) != span)
      return "Original temporal kernels require an integral duration in [0, INT32_MAX]";
    return report(TemporalMotifMining(temporal_options(args, backend, 0)).supports(graph));
  }
  if (operation == "connected-components") {
    auto options = isolated<ConnectedComponentsOptions>(0, work);
    options.connectivity_mode = text_arg(args, "connectivity_mode", "weakly_connected") == "strongly_connected" ? ConnectivityMode::strongly_connected : ConnectivityMode::weakly_connected;
    return report(ConnectedComponents(options).supports(simple));
  }
  if (operation == "transitive-closure") return report(TransitiveClosure(isolated<ReachabilityOptions>(0, work)).supports(simple));
  if (operation == "butterfly-counting") {
    auto options = isolated<ButterflyOptions>(0, work); options.backend = backend;
    return report(ButterflyCounting(options).supports(simple));
  }
  if (operation == "k-truss") return report(KTruss(isolated<KTrussOptions>(0, work)).supports(simple));
  if (operation == "densest-subgraph") {
    if (text_arg(args, "weight_mode", "unweighted") != "unweighted" || natural(args, "minimum_vertices", 1) != 1)
      return "CDS supports unweighted clique density with minimum_vertices=1";
    auto options = isolated<DensestSubgraphOptions>(0, work);
    const auto k = natural(args, "clique_order", 2); if (k > INT32_MAX) return "CDS clique_order must fit int32";
    options.clique_order = k;
    return report(DensestSubgraph(options).supports(simple));
  }
  if (operation == "group-steiner-tree") return report(GroupSteinerTree(steiner_options(args, 0, work)).supports(graph));
  if (operation == "personalized-pagerank") {
    if (text_arg(args, "solution_quality", "numerical") != "approximate" || args.at("seed_vertices").as_array().size() != 1 ||
        !args.contains("restart_probability") || number(args.at("restart_probability"), "restart_probability") != .2 ||
        text_arg(args, "direction_mode", "outgoing") != "outgoing" || text_arg(args, "weight_mode", "unweighted") != "unweighted" ||
        text_arg(args, "dangling_policy", "redistribute_to_seeds") != "redistribute_to_seeds")
      return "kPAR requires solution_quality=approximate, one seed, restart_probability=0.2, unweighted outgoing edges and dangling redistribution to seeds";
    if (args.contains("convergence_tolerance") || args.contains("max_iterations"))
      return "kPAR uses epsilon sampling; convergence_tolerance and max_iterations apply to power iteration";
    if (natural(args, "random_seed", 42) > INT32_MAX) return "kPAR random_seed must fit signed int32";
    return report(PersonalizedPageRank(ppr_options(graph, args, 0, work)).supports(normalized(graph, false, true, work)));
  }
  if (operation == "influence-maximization") {
    if (text_arg(args, "solution_quality", "exact") != "heuristic" || text_arg(args, "diffusion_model", "independent_cascade") != "independent_cascade" || nonempty(args, "vertex_thresholds"))
      return "SuperFuser requires solution_quality=heuristic and independent_cascade; it does not certify a global optimum";
    return report(InfluenceMaximization(influence_options(args, 0, work)).supports(graph));
  }
  return "Unknown original GPU runtime profile";
#else
  return "Original GPU adapters are not linked in this standalone build";
#endif
}

std::vector<std::size_t> original_communities(const Graph& graph, const json::object& args,
                                             const std::string& backend, int device, Work& work) {
#ifdef GRAPHMINE_NATIVE_ORIGINAL_EXTENSIONS
  auto lock = admission(work);
  const auto result = checked(CommunityDetection(community_options(args, backend, device)).run(normalized(graph, true, true, work)), work);
  std::vector<std::size_t> labels(graph.vertex_count(), graph.vertex_count());
  std::vector<bool> seen(graph.vertex_count(), false);
  for (const auto& row : result.assignment_by_vertex) {
    const auto v = graph.dense_index(row.vertex);
    certify(!seen[v] && row.community < result.community_count, "Invalid original community assignment");
    seen[v] = true; labels[v] = row.community;
  }
  certify(std::all_of(seen.begin(), seen.end(), [](bool v) { return v; }), "Original community assignment omitted a vertex");
  return labels;
#else
  throw Failure("backend_unavailable", "Original community adapters are not linked");
#endif
}

json::object original_extension_run(const std::string& operation, const Graph& graph,
                                    const json::object& args, const std::string& backend, int device, Work& work) {
  if (operation == "community-detection") return community_detection(graph, args, backend, device, work);
  if (operation == "dynamic-triangle-counting") return dynamic_triangles(graph, args, backend, device, work);
  if (operation == "maximal-biclique-counting") return maximal_biclique_count(graph, args, backend, device, work);
#ifdef GRAPHMINE_NATIVE_ORIGINAL_EXTENSIONS
  if (operation == "personalized-pagerank") {
    auto lock = admission(work);
    const auto result = checked(PersonalizedPageRank(ppr_options(graph, args, device, work)).run(normalized(graph, false, true, work)), work);
    work.output(2 * graph.vertex_count());
    json::array scores, ranking;
    const auto top = limit(args, "top_k");
    const bool exclude = boolean(args, "exclude_seeds_from_output", false);
    for (const auto& row : result.ranked_vertices) {
      json::object record{{"vertex", id_json(row.vertex)}, {"score", row.score}};
      scores.push_back(record);
      if ((!exclude || row.vertex != external_id(args.at("seed_vertices").as_array().front())) && (!top || ranking.size() < *top)) ranking.push_back(record);
    }
    auto port = result_port("vertex_scores", scores); port["score_field"] = "score";
    auto resolved = args; resolved["epsilon"] = result.epsilon_used; resolved["random_seed"] = natural(args, "random_seed", 42);
    return output(resolved, {{"scores", scores}, {"ranking", ranking}, {"approximate", true},
                             {"error_bound_certified", false}, {"restart_probability", .2}}, {{"scores", port}}, true, "approximate");
  }
  if (operation == "influence-maximization") {
    auto lock = admission(work);
    const auto result = checked(InfluenceMaximization(influence_options(args, device, work)).run(graph), work);
    work.output(result.seed_set.size());
    const auto ids = external_ids(result.seed_set);
    auto resolved = args; resolved["sample_count"] = result.sample_count; resolved["random_seed"] = natural(args, "random_seed", 42);
    return output(resolved, {{"seed_set", ids}, {"expected_spread", result.expected_spread},
                             {"sample_count", result.sample_count}, {"guarantee_met", false}, {"optimal", false}},
                  {{"vertices", result_port("vertex_set", ids)}, {"spread", result_port("scalar", result.expected_spread)}}, true, "heuristic");
  }
  // Existing runtime materialization preserves its richer output contract. The
  // GPU's count/objective/partition is independently checked before publication.
  auto result = operation_handler(operation)(graph, args, "cpp", device, work);
  const auto& data = result.at("result").as_object();
  auto lock = admission(work);
  const auto input = normalized(graph, true, true, work);
  if (operation == "quasi-cliques") {
    const auto value = checked(QuasiCliques(quasi_options(args, device)).run(input), work);
    std::set<std::set<ExternalId>> expected, actual;
    for (const auto& row : data.at("quasi_cliques").as_array()) {
      std::set<ExternalId> group;
      for (const auto& id : row.as_object().at("vertices").as_array()) group.insert(external_id(id));
      expected.insert(group);
    }
    for (const auto& group : value.quasi_cliques) actual.emplace(group.begin(), group.end());
    certify(value.complete && expected == actual, "cuQC disagrees with exact runtime quasi-cliques");
  } else if (operation == "maximal-bicliques") {
    const auto value = checked(MaximalBicliques(biclique_options(args, device)).run(input), work);
    using Biclique = std::pair<std::set<ExternalId>, std::set<ExternalId>>;
    std::set<Biclique> expected, actual;
    for (const auto& row : data.at("bicliques").as_array()) {
      Biclique entry;
      for (const auto& id : row.as_object().at("left_vertices").as_array()) entry.first.insert(external_id(id));
      for (const auto& id : row.as_object().at("right_vertices").as_array()) entry.second.insert(external_id(id));
      expected.insert(entry);
    }
    for (const auto& row : value.bicliques) actual.emplace(std::set<ExternalId>(row.left.begin(), row.left.end()), std::set<ExternalId>(row.right.begin(), row.right.end()));
    certify(value.complete && expected == actual, "cuMBE disagrees with exact runtime bicliques");
  } else if (operation == "motif-counting") {
    const auto value = checked(GraphMotifs(motif_options(args, backend, device)).run(input, motif_graphs(args)), work);
    for (const auto& row : value.motifs)
      certify(exact_number(data.at("count_by_motif").as_object().at(row.motif_id), "motif count") == Exact(row.count), "GPU motif count disagrees with runtime occurrences");
  } else if (operation == "subgraph-isomorphism") {
    const auto value = checked(SubgraphIsomorphism(match_options(device)).run(graph, parse_graph(args.at("query_graph"))), work);
    certify(value.count == uint(data.at("returned_count"), "match count"), "gMatch disagrees with runtime embeddings");
  } else if (operation == "temporal-motifs") {
    const auto value = checked(TemporalMotifMining(temporal_options(args, backend, device)).run(graph), work);
    certify(value.count == uint(data.at("occurrence_count"), "temporal count"), "GPU temporal count disagrees with runtime events");
  } else if (operation == "connected-components") {
    auto options = isolated<ConnectedComponentsOptions>(device, work);
    options.connectivity_mode = text_arg(args, "connectivity_mode", "weakly_connected") == "strongly_connected" ? ConnectivityMode::strongly_connected : ConnectivityMode::weakly_connected;
    const auto value = checked(ConnectedComponents(options).run(input), work);
    std::map<std::uint32_t, std::set<ExternalId>> observed;
    std::set<std::set<ExternalId>> expected, actual;
    for (const auto& row : value.component_assignment) observed[row.component].insert(row.vertex);
    for (const auto& entry : observed) actual.insert(entry.second);
    for (const auto& row : data.at("groups").as_array()) {
      std::set<ExternalId> ids;
      for (const auto& id : row.as_object().at("vertices").as_array()) ids.insert(external_id(id));
      expected.insert(ids);
    }
    certify(actual == expected, "ECL-SCC disagrees with runtime components");
  } else if (operation == "transitive-closure") {
    const auto value = checked(TransitiveClosure(isolated<ReachabilityOptions>(device, work)).run(input), work);
    std::set<Pair> pairs;
    for (const auto& pair : value.reachable_pairs) pairs.emplace(pair.source, pair.target);
    const bool full = text_arg(args, "query_mode", "full_transitive_closure") == "full_transitive_closure";
    if (full) certify(value.reachable_pair_count == uint(data.at("count"), "closure count"), "GDlog disagrees with closure count");
    if (data.at("pairs").is_array()) for (const auto& row : data.at("pairs").as_array()) {
      const auto& pair = row.as_object();
      const bool present = pairs.count({external_id(pair.at("source")), external_id(pair.at("target"))});
      certify(present == (full || pair.at("reachable").as_bool()), "GDlog disagrees with reachability");
    }
  } else if (operation == "butterfly-counting") {
    auto options = isolated<ButterflyOptions>(device, work); options.backend = backend;
    const auto value = checked(ButterflyCounting(options).run(input), work);
    certify(value.butterfly_count == uint(data.at("butterfly_count"), "butterfly count"), "GPU butterfly count disagrees with runtime participation");
  } else if (operation == "k-truss") {
    const auto value = checked(KTruss(isolated<KTrussOptions>(device, work)).run(input), work);
    std::map<ExternalId, Pair> endpoints;
    for (const auto& edge : input.canonical().edges) endpoints[edge.id] = std::minmax(edge.source, edge.target);
    std::map<Pair, std::uint32_t> actual;
    for (const auto& row : value.truss_number_by_edge) actual[endpoints.at(row.edge)] = row.truss_number;
    for (const auto& raw : data.at("edges").as_array()) {
      const auto& row = raw.as_object();
      certify(actual.at(std::minmax(external_id(row.at("source")), external_id(row.at("target")))) == uint(row.at("truss_number"), "truss number"), "AccTD disagrees with runtime truss numbers");
    }
  } else if (operation == "densest-subgraph") {
    auto options = isolated<DensestSubgraphOptions>(device, work); options.clique_order = natural(args, "clique_order", 2);
    const auto value = checked(DensestSubgraph(options).run(input), work);
    certify(value.optimal && !value.vertices.empty() && Exact(value.clique_count) / value.vertices.size() == exact_result_field(data, "density"), "CDS disagrees with exact runtime density");
  } else if (operation == "group-steiner-tree") {
    const auto value = checked(GroupSteinerTree(steiner_options(args, device, work)).run(graph), work);
    certify(value.feasible == data.at("feasible").as_bool() && (!value.feasible || Exact(value.tree_weight) == exact_result_field(data, "tree_weight")), "GPU4GST disagrees with exact runtime optimum");
  } else throw Failure("unsupported_operation", "Missing original GPU adapter dispatch");
  if (!result.contains("diagnostics")) result["diagnostics"] = json::object{};
  result.at("diagnostics").as_object()["execution"] = "original GPU result with bounded CPU verification/materialization";
  result.at("diagnostics").as_object()["original_gpu_backend"] = backend;
  return result;
#else
  throw Failure("backend_unavailable", "Original GPU adapters are not linked");
#endif
}

json::object maximal_biclique_count(const Graph& graph, const json::object& args, const std::string& backend, int device, Work& work) {
  fields(args, {});
  json::array left, right;
  for (const auto& vertex : graph.canonical().vertices) {
    const auto found = vertex.attributes.find("side");
    require(found != vertex.attributes.end() && std::holds_alternative<std::string>(found->second.value()), "Every vertex requires attributes.side=left|right");
    const auto& side = std::get<std::string>(found->second.value());
    require(side == "left" || side == "right", "Invalid bipartite side");
    (side == "left" ? left : right).push_back(id_json(vertex.id));
  }
  const auto cpu = maximal_bicliques(graph, {{"left_partition", left}, {"right_partition", right}}, "cpp", device, work);
  const auto count = cpu.at("result").as_object().at("total_count");
  if (backend != "cpp") {
#ifdef GRAPHMINE_NATIVE_ORIGINAL_EXTENSIONS
    auto lock = admission(work);
    const auto value = checked(MaximalBicliqueCounting(isolated<MaximalBicliqueCountingOptions>(device, work)).run(normalized(graph, true, true, work)), work);
    certify(value.total_count == uint(count, "biclique count"), "MBE-GPU disagrees with exact maximal biclique count");
#else
    throw Failure("backend_unavailable", "MBE-GPU is not linked");
#endif
  }
  return output({}, {{"total_count", count}}, {{"count", result_port("scalar", count)}});
}

json::object dynamic_triangles(const Graph& graph, const json::object& args, const std::string& backend, int device, Work& work) {
  fields(args, {"updates", "list_changed_instances", "result_limit"}, {"updates"});
  require(!graph.directed(), "Dynamic triangles require an undirected graph");
  require(args.at("updates").is_array(), "updates must be an array");
  const bool listing = boolean(args, "list_changed_instances", false);
  const auto cap = limit(args);
  require(!cap || listing, "result_limit requires list_changed_instances");
  auto input = normalized(graph, true, true, work);
  std::set<Pair> edges;
  for (const auto& edge : input.canonical().edges) edges.emplace(std::minmax(edge.source, edge.target));
  auto triangle_set = [&] {
    std::set<std::vector<ExternalId>> result;
    combinations(graph.vertex_count(), 3, work, [&](const auto& selected) {
      std::vector<ExternalId> ids;
      for (const auto v : selected) ids.push_back(graph.external_id(v));
      if (edges.count(std::minmax(ids[0], ids[1])) && edges.count(std::minmax(ids[0], ids[2])) && edges.count(std::minmax(ids[1], ids[2]))) { std::sort(ids.begin(), ids.end()); result.insert(ids); }
      return true;
    });
    return result;
  };
  const auto initial = triangle_set();
  std::vector<std::pair<std::string, Pair>> changes;
  std::set<std::pair<std::string, Pair>> seen;
  for (const auto& raw : args.at("updates").as_array()) {
    const auto row = object(raw, "update");
    fields(row, {"kind", "source", "target"}, {"kind", "source", "target"});
    auto a = external_id(row.at("source")), b = external_id(row.at("target"));
    (void)graph.dense_index(a); (void)graph.dense_index(b);
    require(a != b, "Triangle updates cannot be self-loops");
    const auto kind = choice(row, "kind", "insert_edge", {"insert_edge", "delete_edge"});
    const auto change = std::make_pair(kind, Pair(std::minmax(a, b)));
    require(seen.insert(change).second, "Duplicate triangle update"); changes.push_back(change);
  }
  for (const auto& [kind, edge] : changes) if (kind == "delete_edge") require(edges.erase(edge), "Cannot delete an absent edge");
  const auto after_deletions = triangle_set();
  for (const auto& [kind, edge] : changes) if (kind == "insert_edge") require(edges.insert(edge).second, "Cannot insert an existing edge");
  const auto final = triangle_set();
  std::vector<std::vector<ExternalId>> deleted, inserted;
  std::set_difference(initial.begin(), initial.end(), after_deletions.begin(), after_deletions.end(), std::back_inserter(deleted));
  std::set_difference(final.begin(), final.end(), after_deletions.begin(), after_deletions.end(), std::back_inserter(inserted));
  if (backend != "cpp") {
#ifdef GRAPHMINE_NATIVE_ORIGINAL_EXTENSIONS
    DynamicTriangleOptions options; options.backend = DynamicTriangleBackend::edtc; options.execution.device_ids = {device};
    auto lock = admission(work);
    const auto value = checked(DynamicTriangleCounting(options).run(input, updates(args)), work);
    certify(value.deleted_triangle_count == deleted.size() && value.inserted_triangle_count == inserted.size(), "EDTC disagrees with exact dynamic triangle changes");
#else
    throw Failure("backend_unavailable", "EDTC is not linked");
#endif
  }
  json::object data{{"deleted_triangle_count", deleted.size()}, {"inserted_triangle_count", inserted.size()},
                    {"net_triangle_change", static_cast<std::int64_t>(inserted.size()) - static_cast<std::int64_t>(deleted.size())},
                    {"initial_global_triangle_count", initial.size()}, {"final_global_triangle_count", final.size()}};
  json::object ports{{"count", result_port("scalar", final.size())}};
  bool complete = true;
  if (listing) for (const auto& item : {std::make_pair("deleted", &deleted), std::make_pair("inserted", &inserted)}) {
    json::array rows;
    for (const auto& group : *item.second) {
      if (cap && rows.size() == *cap) break;
      work.output(4 * (rows.size() + 1)); rows.push_back(json::object{{"vertices", external_ids(group)}});
    }
    const bool all = rows.size() == item.second->size(); complete &= all;
    data[std::string(item.first) + "_triangles"] = rows;
    ports[item.first] = result_port("vertex_groups", rows, all);
  }
  data["changed_instances_complete"] = complete;
  return output(args, data, ports, complete);
}
} // namespace graphmine::runtime
