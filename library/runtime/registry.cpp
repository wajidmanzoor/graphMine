#include "internal.hpp"
#include "catalog_data.hpp"

namespace graphmine::runtime {
namespace {
json::object parameter(std::string kind, json::value initial, bool required = false,
                       bool nullable = false) {
  json::object result{{"kind", kind}, {"required", required}, {"nullable", nullable}};
  if (!required) result["default"] = std::move(initial);
  return result;
}
json::object card(const char* id, const char* problem, const char* title,
                  const char* description, json::object parameters,
                  json::object ports, json::array gpu_backends) {
  json::array backends{json::object{{"id", "cpp"}, {"device", "cpu"}, {"compiled", true}}};
  for (const auto& backend : gpu_backends) backends.push_back(backend);
  auto taxonomy = json::parse(taxonomy_json).as_object();
  std::string family;
  for (const auto& row : taxonomy.at("problems").as_array())
    if (row.as_object().at("id").as_string() == problem) family = string(row.as_object().at("family"), "family");
  require(!family.empty(), "Native operation has no declared problem family");
  return {{"id", id}, {"problem_id", problem}, {"family", family},
          {"title", title}, {"description", description}, {"input_kind", "graph"},
          {"parameters", parameters}, {"output_ports", ports}, {"backends", backends},
          {"quality", "exact"}, {"implementation_language", "c++/cuda"},
          {"evidence_status", "requires_matching_validation_report"}};
}
struct Operation { json::object metadata; NativeAlgorithm handler; };
std::vector<Operation> definitions() {
  auto source_mode = parameter("string", "independent");
  source_mode["choices"] = json::array{"independent", "nearest_source"};
  auto depth = parameter("integer", nullptr, false, true);
  depth["minimum"] = 0; depth["maximum"] = UINT32_MAX;
  auto mode = parameter("string", "count");
  mode["choices"] = json::array{"count", "enumerate"};
  auto limit = parameter("integer", nullptr, false, true);
  limit["minimum"] = 1;
  auto port = [](const char* kind) { return json::object{{"type", kind}, {"availability", "runtime_checked"}}; };
  auto choice = [](const char* initial, json::array choices) { auto p = parameter("string", initial); p["choices"] = choices; return p; };
  auto positive = [](json::value initial, bool nullable = false) { auto p = parameter("integer", initial, false, nullable); p["minimum"] = 1; return p; };
  auto real = [](double initial, double minimum, std::optional<double> maximum = {}) { auto p = parameter("number", initial); p["minimum"] = minimum; if (maximum) p["maximum"] = *maximum; return p; };
  const json::array gpu{json::object{{"id", "libcugraph"}, {"device", "gpu"}, {"compiled", cugraph_compiled()}}};
  const auto weights = choice("unweighted", {"unweighted", "edge_weight"});
  auto core_backends = gpu;
  for (const auto& backend : original_mining_backends("k-core")) core_backends.push_back(backend);
  auto betweenness_backends = gpu;
  for (const auto& backend : original_mining_backends("betweenness-centrality")) betweenness_backends.push_back(backend);
  std::vector<Operation> result{
    {card("breadth-first-search", "breadth_first_search", "Connections within a number of steps",
         "Minimum hop distances with explicit independent or nearest-source searches. Preserve direction; discard loops and collapse duplicate arcs; weights are ignored. IDs are signed int64 or strings.",
         {{"sources", parameter("array", nullptr, true)}, {"source_mode", source_mode},
          {"depth_limit", depth}, {"return_predecessors", parameter("boolean", true)}},
         {{"vertices", port("vertex_set")}, {"distances", port("table")}},
         gpu), bfs},
    {card("triangle-counting", "triangle_counting_listing", "Count or list triangles",
         "Count three-vertex cliques of an undirected graph. Discard loops and collapse duplicate edges; weights are ignored. GPU enumeration uses native CPU materialization with count verification.",
         {{"mode", mode}, {"result_limit", limit}},
         {{"count", port("scalar")}, {"groups", port("vertex_groups")}},
         {json::object{{"id", "tot"}, {"device", "gpu"}, {"compiled", original_triangles_compiled("tot")}},
          json::object{{"id", "wetric"}, {"device", "gpu"}, {"compiled", original_triangles_compiled("wetric")}}}), triangles},
    {card("single-source-shortest-paths", "single_source_shortest_paths", "Shortest weighted paths from one vertex",
         "Nonnegative lengths; preserve direction, drop loops and keep minimum parallel length. CPU returns exact rational costs over admitted binary64 weights; GPU returns float64 costs. Cutoff is inclusive.",
         {{"source", parameter("vertex_id", nullptr, true)}, {"cutoff", parameter("number", nullptr, false, true)}, {"return_predecessors", parameter("boolean", true)}},
         {{"distances", port("vertex_scores")}}, gpu), shortest_paths},
    {card("many-source-shortest-paths", "many_source_shortest_paths", "Shortest paths between selected vertex sets",
         "Selected origins and destinations, or all vertices for null. Nonnegative lengths, minimum parallel length and preserved direction; CPU exact costs and GPU float64 costs.",
         {{"origins", parameter("array", nullptr, false, true)}, {"destinations", parameter("array", nullptr, false, true)}, {"weight_mode", choice("edge_weight", {"edge_weight", "unweighted"})}},
         {{"distances", port("table")}}, gpu), many_shortest_paths},
    {card("spanning-tree-forest", "spanning_tree_forest", "Minimum or maximum spanning forest",
         "Undirected weighted forests with isolates retained. Negative lengths are allowed. Keep minimum or maximum parallel weights according to the objective; discard loops.",
         {{"objective", choice("minimum", {"minimum", "maximum"})}, {"require_connected", parameter("boolean", false)}},
         {{"vertices", port("vertex_set")}, {"edges", port("edge_set")}}, gpu), spanning_forest},
    {card("connected-components", "connected_components", "Connected vertex groups",
         "Weak or strong connectivity. Weak mode uses an undirected projection; strong mode preserves direction. Loops, duplicate edges and weights do not affect membership.",
         {{"connectivity_mode", choice("weakly_connected", {"weakly_connected", "strongly_connected"})}}, {{"groups", port("vertex_groups")}}, gpu), components},
    {card("topological-sort", "topological_sort", "Order a directed acyclic graph",
         "Return a deterministic topological order. Reject directed cycles, including self-loops. Duplicate arcs collapse; weights are ignored.",
         {}, {{"vertices", port("vertex_set")}}, {}), topological},
    {card("pagerank", "centrality_influential_node_mining", "PageRank influence scores",
         "Directed random-walk scores with uniform restart and dangling distribution. Drop loops, sum parallel weights and independently verify the fixed-point residual.",
         {{"alpha", real(0.85, 0, 1)}, {"tolerance", real(1e-9, 0)}, {"max_iterations", positive(1000)}, {"weight_mode", weights}},
         {{"scores", port("vertex_scores")}}, gpu), pagerank},
    {card("degree-centrality", "centrality_influential_node_mining", "Rank vertices by their number of connections",
         "Exact degree scores with outgoing, incoming, both or undirected-projection semantics. Drop loops, collapse duplicate edges and ignore weights. Optional normalization divides by n-1; isolates score zero.",
         {{"normalized", parameter("boolean", true)}, {"direction_mode", choice("outgoing", {"outgoing", "incoming", "both", "undirected_projection"})}},
         {{"scores", port("vertex_scores")}}, {}), degree_centrality},
    {card("betweenness-centrality", "centrality_influential_node_mining", "Rank vertices that connect shortest paths",
         "All-source betweenness excluding endpoints. Preserve direction, drop loops and keep minimum parallel length. CPU supports exact rational scores and strictly positive weighted paths; GPU profiles use unweighted paths with declared floating-point arithmetic.",
         {{"normalized", parameter("boolean", true)}, {"weight_mode", weights}}, {{"scores", port("vertex_scores")}}, betweenness_backends), betweenness},
    {card("personalized-pagerank", "personalized_pagerank_rwr", "Restart walks around seed vertices",
         "Seeded PageRank with explicit direction, weight and dangling policies. Full score port stays complete when the displayed ranking is filtered or capped.",
         {{"seed_vertices", parameter("array", nullptr, true)}, {"restart_probability", real(0.15, 0, 1)},
          {"direction_mode", choice("outgoing", {"outgoing", "incoming", "undirected_projection"})}, {"weight_mode", weights},
          {"dangling_policy", choice("redistribute_to_seeds", {"redistribute_to_seeds", "redistribute_uniformly", "self_loop"})},
          {"convergence_tolerance", real(1e-9, 0)}, {"max_iterations", positive(1000)}, {"exclude_seeds_from_output", parameter("boolean", false)}, {"top_k", positive(nullptr, true)}},
         {{"scores", port("vertex_scores")}}, gpu), personalized_pagerank},
    {card("link-prediction", "link_prediction", "Score potential links from local neighborhoods",
         "Undirected simple neighborhoods; loops and weights ignored. CPU supports eight local measures; GPU supports Jaccard. Candidate limits apply before top_k; capped output is explicitly incomplete.",
         {{"scoring_measure", choice("jaccard", {"jaccard", "common_neighbors", "adamic_adar", "resource_allocation", "preferential_attachment", "sorensen", "overlap", "cosine"})},
          {"candidate_pairs", parameter("array", nullptr, false, true)}, {"exclude_existing_edges", parameter("boolean", true)}, {"top_k", positive(nullptr, true)}},
         {{"pairs", port("table")}}, gpu), link_prediction},
    {card("max-flow-min-cut", "max_flow_min_cut", "Find capacity and bottlenecks between two places",
         "Exact rational flow and cut certificate. Sum parallel capacities, discard loops and treat undirected edges as two directed arcs. Optional vertex capacities use typed {vertex,capacity} records and include explicitly limited terminals. Mixed cuts return original edge IDs plus cut vertices.",
         {{"source", parameter("vertex_id", nullptr, true)}, {"sink", parameter("vertex_id", nullptr, true)},
          {"capacity_mode", choice("edge_weight", {"edge_weight", "unit_capacity"})}, {"return_cut_side", parameter("boolean", true)},
          {"vertex_capacities", parameter("array", nullptr, false, true)}, {"solution_quality", choice("exact", {"exact", "approximate"})}},
         {{"value", port("scalar")}, {"vertices", port("vertex_set")}}, original_optimization_backends("max-flow-min-cut")), max_flow},
    {card("weighted-matching", "general_graph_weighted_matching", "Find the highest-value non-conflicting pairs",
         "Exact maximum-weight matching on an undirected graph, with no cardinality constraint. Require nonnegative weights; discard loops and keep the largest parallel weight. Preserve selected original edge IDs and return exact rational totals over admitted binary64 weights. Zero-weight edges may be omitted.",
         {{"solution_quality", choice("exact", {"exact", "approximate"})}}, {{"edges", port("edge_set")}}, {}), weighted_matching},
    {card("bipartite-matching", "bipartite_matching_assignment", "Match items on two sides by count, value or cost",
         "Exact cardinality, weight or cost matching with attributes.side=left|right on every vertex. Reject same-side edges and loops; keep the best parallel edge. Weighted objectives require explicit weights. Without required smaller-side coverage, empty matching may be optimal. Infeasible coverage has no witness port.",
         {{"objective", parameter("string", nullptr, true)}, {"weight_mode", weights}, {"perfect_matching_required", parameter("boolean", false)},
          {"solution_quality", choice("exact", {"exact", "approximate"})}}, {{"edges", port("edge_set")}}, original_optimization_backends("bipartite-matching")), bipartite_matching},
    {card("maximal-cliques", "maximal_clique_enumeration", "Find complete groups that cannot be extended",
         "Exact maximal cliques in an undirected simple projection. Drop loops and duplicate edges; ignore weights. Original GPU kernels supply a count, with bounded C++ materialization and explicit list completeness.",
         {{"minimum_clique_size", positive(1)}, {"result_limit", positive(nullptr, true)}},
         {{"groups", port("vertex_groups")}}, original_mining_backends("maximal-cliques")), maximal_cliques},
    {card("maximum-clique", "maximum_clique", "Find the largest fully connected group",
         "Exact maximum clique, optionally all tied optima. Undirected simple projection; loops, duplicate edges and weights ignored. Original GPU witnesses are checked by native coloring or exact search; ties use native materialization.",
         {{"return_all_ties", parameter("boolean", false)}}, {{"groups", port("vertex_groups")}, {"vertices", port("vertex_set")}}, original_mining_backends("maximum-clique")), maximum_clique},
    {card("k-cliques", "k_clique_counting_enumeration", "Count or list complete groups of a chosen size",
         "Exact count for k>=2 with no upper k bound on CPU. Undirected simple projection; loops, duplicate edges and weights ignored. GPU counts require supported k and a uint64 count bound. Counts remain complete when memberships are capped.",
         {{"k", parameter("integer", nullptr, true)}, {"mode", mode}, {"result_limit", positive(nullptr, true)}},
         {{"groups", port("vertex_groups")}, {"count", port("scalar")}}, original_mining_backends("k-cliques")), k_cliques},
    {card("biconnected-components", "biconnected_components", "Find fragile connections and cut vertices",
         "Exact vertex-biconnected edge blocks, bridges and articulation vertices. Undirected input; loops discarded and parallel edges collapsed. Every normalized edge keeps its first original ID and all source edge IDs.",
         {}, {{"groups", port("vertex_groups")}, {"vertices", port("vertex_set")}, {"edges", port("edge_set")}}, {}), biconnected},
    {card("k-truss", "k_truss_decomposition", "Find connections supported by triangles",
         "Complete edge truss numbers using the k-2 support convention, plus optional k-truss selection. Undirected simple projection, weights ignored. First original edge IDs represent collapsed edges; source IDs are retained.",
         {{"requested_k", parameter("integer", nullptr, false, true)}}, {{"edges", port("edge_set")}}, gpu), truss},
    {card("k-core", "k_core_decomposition", "Find the well-connected core",
         "Exact core numbers and optional selected vertices. Undirected simple projection; loops, duplicate edges and weights ignored. Isolates have core number zero.",
         {{"requested_k", parameter("integer", nullptr, false, true)}}, {{"scores", port("vertex_scores")}, {"vertices", port("vertex_set")}}, core_backends), core_numbers},
    {card("maximum-independent-set", "maximum_independent_set", "Find the largest non-conflicting group",
         "Exact maximum independent set via maximum clique of the complement. Undirected simple projection; loops, duplicate edges and weights ignored. Complement construction and search are bounded.",
         {{"mode", choice("exact", {"exact"})}}, {{"vertices", port("vertex_set")}}, original_mining_backends("maximum-clique")), maximum_independent_set},
    {card("minimum-vertex-cover", "minimum_vertex_cover", "Cover every connection with as few vertices as possible",
         "Exact minimum vertex cover, or decision against k, from a maximum independent set. Undirected simple projection; loops, duplicate edges and weights ignored. Native complement construction and search are bounded.",
         {{"mode", choice("exact", {"exact", "decision"})}, {"k", parameter("integer", nullptr, false, true)}},
         {{"vertices", port("vertex_set")}}, original_mining_backends("maximum-clique")), minimum_vertex_cover}
  };
  for (auto& definition : result) {
    auto& metadata = definition.metadata;
    const auto id = string(metadata.at("id"), "operation");
    if (id == "bipartite-matching") metadata.at("parameters").as_object().at("objective").as_object()["choices"] = json::array{"maximum_cardinality", "maximum_weight", "minimum_cost"};
    if (id == "max-flow-min-cut") metadata["gpu_limitations"] = json::array{"ecl-maxflow: nonnegative integral normalized capacities with total <=1e9; no vertex capacities", "At most 1M vertices and 10M input edges; exact residual flow/cut certification"};
    if (id == "bipartite-matching") metadata["gpu_limitations"] = json::array{"hungarian-cuda: minimum-cost perfect assignment, complete equal sides, at most 64 per side", "Every input cost must be an integer in [0,999]; native C++ verifies the optimum"};
    if (id == "k-cliques") {
      metadata.at("parameters").as_object().at("k").as_object()["minimum"] = 2;
      metadata["gpu_limitations"] = json::array{"graphset: k=3..6; gamma: k=3..7; kcgpu: k=3..10; k larger than vertex count returns zero", "A forward-subset count bound must fit uint64"};
    }
    if (id == "maximal-cliques") metadata["gpu_limitations"] = json::array{"GPU count plus bounded native materialization", "A forward-subset count bound must fit uint64"};
    if (id == "k-truss") metadata.at("parameters").as_object().at("requested_k").as_object()["minimum"] = 2;
    if (id == "k-core") metadata.at("parameters").as_object().at("requested_k").as_object()["minimum"] = 0;
    if (id == "minimum-vertex-cover") metadata.at("parameters").as_object().at("k").as_object()["minimum"] = 0;
    if (id == "pagerank" || id == "personalized-pagerank" || id == "link-prediction") metadata["quality"] = "numerical";
    if (id == "single-source-shortest-paths" || id == "many-source-shortest-paths") metadata["quality"] = "backend_dependent";
    if (id == "betweenness-centrality") {
      metadata["quality"] = "backend_dependent";
      metadata["gpu_limitations"] = json::array{"Unweighted paths only", "Original turbo-bc supports undirected graphs and uses float32 accumulation; libcugraph supports either direction", "Shortest-path counts must fit signed int32; larger inputs receive bounded CPU admission checks"};
    }
    if (id == "personalized-pagerank") metadata["gpu_limitations"] = json::array{"Custom uniform dangling redistribution uses the CPU profile"};
    if (id == "link-prediction") metadata["gpu_limitations"] = json::array{"Only scoring_measure=jaccard"};
    if (id == "single-source-shortest-paths" || id == "many-source-shortest-paths") metadata["gpu_limitations"] = json::array{"Path cost bounds must fit float64; integral costs beyond 2^53 require CPU"};
  }
  return result;
}
}

json::array operation_cards() {
  json::array output;
  for (auto& definition : definitions()) output.push_back(std::move(definition.metadata));
  return output;
}
NativeAlgorithm operation_handler(const std::string& operation) {
  for (const auto& definition : definitions()) if (definition.metadata.at("id").as_string() == operation) return definition.handler;
  throw Failure("unsupported_operation", "No native runtime integration for " + operation);
}

json::object catalog() {
  auto result = json::parse(taxonomy_json).as_object();
  const auto cards = operation_cards();
  for (auto& family : result.at("families").as_array()) {
    json::array operations;
    for (const auto& op : cards)
      if (op.as_object().at("family") == family.as_object().at("id")) operations.push_back(op.as_object().at("id"));
    family.as_object()["operations"] = operations;
  }
  for (auto& problem : result.at("problems").as_array()) {
    json::array operations;
    for (const auto& op : cards)
      if (op.as_object().at("problem_id") == problem.as_object().at("id")) operations.push_back(op.as_object().at("id"));
    problem.as_object()["operations"] = operations;
    problem.as_object()["runtime_integration"] = operations.empty() ? "pending" : "implemented";
  }
  result["operations"] = cards;
  result["abi_version"] = 1;
  result["implementation_sha256"] = implementation_sha256;
  result["python_runtime_required"] = false;
  result["file_readers"] = json::array{json::object{{"id", "libcudf-csv"}, {"compiled", cudf_compiled()}, {"device", "gpu"}}};
  return result;
}
}  // namespace graphmine::runtime
