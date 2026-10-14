#include "catalog_data.hpp"
#include "internal.hpp"

namespace graphmine::runtime {
namespace {
json::object parameter(std::string kind, json::value initial, bool required = false,
                       bool nullable = false) {
  json::object result{{"kind", kind}, {"required", required}, {"nullable", nullable}};
  if (!required) result["default"] = std::move(initial);
  return result;
}
json::object card(const char* id, const char* problem, const char* title, const char* description,
                  json::object parameters, json::object ports, json::array gpu_backends) {
  json::array backends{json::object{{"id", "cpp"}, {"device", "cpu"}, {"compiled", true}}};
  for (const auto& backend : gpu_backends) backends.push_back(backend);
  static const auto taxonomy = json::parse(taxonomy_json).as_object();
  std::string family;
  for (const auto& row : taxonomy.at("problems").as_array())
    if (row.as_object().at("id").as_string() == problem)
      family = string(row.as_object().at("family"), "family");
  require(!family.empty(), "Native operation has no declared problem family");
  return {{"id", id},
          {"problem_id", problem},
          {"family", family},
          {"title", title},
          {"description", description},
          {"input_kind", "graph"},
          {"parameters", parameters},
          {"output_ports", ports},
          {"backends", backends},
          {"quality", "exact"},
          {"implementation_language", "c++/cuda"},
          {"evidence_status", "requires_matching_validation_report"}};
}
struct Operation {
  json::object metadata;
  NativeAlgorithm handler;
  NativeInputAlgorithm input_handler = nullptr;
};
const std::vector<Operation>& definitions() {
  static const auto registry = [] {
    auto source_mode = parameter("string", "independent");
    source_mode["choices"] = json::array{"independent", "nearest_source"};
    auto depth = parameter("integer", nullptr, false, true);
    depth["minimum"] = 0;
    depth["maximum"] = UINT32_MAX;
    auto mode = parameter("string", "count");
    mode["choices"] = json::array{"count", "enumerate"};
    auto limit = parameter("integer", nullptr, false, true);
    limit["minimum"] = 1;
    auto port = [](const char* kind) {
      return json::object{{"type", kind}, {"availability", "runtime_checked"}};
    };
    auto choice = [](const char* initial, json::array choices) {
      auto p = parameter("string", initial);
      p["choices"] = choices;
      return p;
    };
    auto positive = [](json::value initial, bool nullable = false) {
      auto p = parameter("integer", initial, false, nullable);
      p["minimum"] = 1;
      return p;
    };
    auto real = [](double initial, double minimum, std::optional<double> maximum = {}) {
      auto p = parameter("number", initial);
      p["minimum"] = minimum;
      if (maximum) p["maximum"] = *maximum;
      return p;
    };
    const json::array gpu{
        json::object{{"id", "libcugraph"}, {"device", "gpu"}, {"compiled", cugraph_compiled()}}};
    const json::array cpp_gpu{json::object{
        {"id", "libcugraph"}, {"device", "gpu"}, {"compiled", cugraph_cpp_compiled()}}};
    const auto seed = parameter("integer", nullptr, false, true);
    const auto weights = choice("unweighted", {"unweighted", "edge_weight"});
    auto core_backends = gpu;
    for (const auto& backend : original_mining_backends("k-core")) core_backends.push_back(backend);
    auto betweenness_backends = gpu;
    for (const auto& backend : original_mining_backends("betweenness-centrality"))
      betweenness_backends.push_back(backend);
    std::vector<Operation> result{
        {card(
             "node-lookup", "graph_record_queries", "Look up entity records",
             "Native deterministic selection of original vertex records by typed IDs and AND field "
             "predicates. Explicit empty vertex lists select nothing. Missing fields match only "
             "exists=false; unknown field paths fail. Counts remain complete when row collections "
             "are capped.",
             {{"vertices", parameter("array", nullptr, false, true)},
              {"vertex_filters", parameter("array", json::array{})},
              {"result_limit", positive(nullptr, true)}},
             {{"rows", port("table")}, {"count", port("scalar")}, {"vertices", port("vertex_set")}},
             {}),
         node_lookup},
        {card("edge-filter", "graph_record_queries",
              "Filter relationship records and join endpoint attributes",
              "Native deterministic original-edge selection without collapsing loops or parallel "
              "events. Edge and source/target predicates use stored endpoints even for undirected "
              "input. Typed IDs, exact decimal scalar comparisons and explicit incomplete capped "
              "ports.",
              {{"edge_ids", parameter("array", nullptr, false, true)},
               {"edge_filters", parameter("array", json::array{})},
               {"source_filters", parameter("array", json::array{})},
               {"target_filters", parameter("array", json::array{})},
               {"result_limit", positive(nullptr, true)}},
              {{"rows", port("table")},
               {"count", port("scalar")},
               {"edges", port("edge_ids")},
               {"vertices", port("vertex_set")}},
              {}),
         edge_filter},
        {card(
             "neighbors", "graph_record_queries",
             "Find nearby entities over selected relationships",
             "Native filtered hop reachability with exact distances. Directed out/in/both "
             "traversal; undirected edges traverse both ways. Parallel records do not duplicate "
             "vertices; include_seed controls the root. Original input vertex ordering and "
             "explicit collection completeness.",
             {{"entity", parameter("vertex_id", nullptr, true)},
              {"hops", parameter("integer", 1)},
              {"direction", choice("out", {"out", "in", "both"})},
              {"edge_filters", parameter("array", json::array{})},
              {"include_seed", parameter("boolean", false)},
              {"result_limit", positive(nullptr, true)}},
             {{"rows", port("table")}, {"count", port("scalar")}, {"vertices", port("vertex_set")}},
             {}),
         query_neighbors},
        {card(
             "common-neighbors", "graph_record_queries",
             "Find the direct neighbors two entities share",
             "Native intersection of direct filtered neighbor sets, preserving the declared "
             "direction and self-loop adjacency meaning. Typed entity IDs; stable original vertex "
             "order. Complete count with explicitly capped collections.",
             {{"source", parameter("vertex_id", nullptr, true)},
              {"target", parameter("vertex_id", nullptr, true)},
              {"direction", choice("out", {"out", "in", "both"})},
              {"edge_filters", parameter("array", json::array{})},
              {"result_limit", positive(nullptr, true)}},
             {{"rows", port("table")}, {"count", port("scalar")}, {"vertices", port("vertex_set")}},
             {}),
         query_common_neighbors},
        {card("query-paths", "graph_record_queries",
              "Find bounded connections between two entities",
              "Native iterative enumeration of all hop-shortest or all vertex-simple paths within "
              "max_hops. Filtered directed out/in/both traversal with parallel edge identities "
              "preserved. Source equal to target has one zero-edge path. Counts are exhaustive; "
              "capped path and membership ports are incomplete.",
              {{"source", parameter("vertex_id", nullptr, true)},
               {"target", parameter("vertex_id", nullptr, true)},
               {"mode", choice("shortest", {"shortest", "all_simple"})},
               {"max_hops", parameter("integer", 3)},
               {"direction", choice("out", {"out", "in", "both"})},
               {"edge_filters", parameter("array", json::array{})},
               {"result_limit", positive(nullptr, true)}},
              {{"rows", port("table")},
               {"count", port("scalar")},
               {"vertices", port("vertex_set")},
               {"edges", port("edge_ids")}},
              {}),
         query_paths},
        {card("graph-aggregate", "graph_record_queries", "Summarize recorded numeric values",
              "Native count, sum, average, minimum or maximum of an explicit field, grouped by a "
              "scalar field or vertex. Exact decimal rational arithmetic is authoritative; display "
              "values disclose rounding. Per-vertex edge groups include isolates and count loops "
              "once. Missing numeric/group fields fail. Stable exact-value sorting and "
              "completeness-aware result limits.",
              {{"scope", choice("edges", {"vertices", "edges"})},
               {"filters", parameter("array", json::array{})},
               {"metric", choice("count", {"count", "sum", "avg", "min", "max"})},
               {"field", parameter("string", nullptr, false, true)},
               {"group_by", parameter("string", nullptr, false, true)},
               {"direction", choice("out", {"out", "in", "both"})},
               {"order", choice("input", {"input", "ascending", "descending"})},
               {"result_limit", positive(nullptr, true)}},
              {{"rows", port("table")},
               {"count", port("scalar")},
               {"scores", port("vertex_scores")}},
              {}),
         graph_aggregate},
        {card("query-subgraph", "graph_record_queries", "Extract selected records as a graph",
              "Native vertex-induced, edge-induced or filtered-neighborhood extraction. Preserve "
              "typed IDs, original attributes, direction, weights, loop and parallel records. Edge "
              "mode retains endpoints; vertex mode retains selected isolates. Derived graph "
              "identity carries source content lineage.",
              {{"mode", choice("vertices", {"vertices", "edges", "neighborhood"})},
               {"vertices", parameter("array", nullptr, false, true)},
               {"edge_ids", parameter("array", nullptr, false, true)},
               {"entity", parameter("vertex_id", nullptr, false, true)},
               {"hops", parameter("integer", 1)},
               {"direction", choice("out", {"out", "in", "both"})},
               {"vertex_filters", parameter("array", json::array{})},
               {"edge_filters", parameter("array", json::array{})}},
              {{"graph", port("graph")},
               {"vertices", port("vertex_set")},
               {"edges", port("edge_ids")}},
              {}),
         query_subgraph},
        {card("node-embedding", "node_embedding",
              "Learn vertex vectors from edge or walk context objectives",
              "Native second-order LINE or DeepWalk/node2vec fixed-window contexts, optimized with "
              "full-softmax cross entropy and declared L2 regularization. Weighted outgoing "
              "transitions preserve direction unless projection is requested. Explicit loop "
              "handling and summed parallel weights; every vertex receives source and context "
              "vectors. Report actual context masses, objective, gradient norm, seed and stopping "
              "reason; no global optimum or unique embedding claim.",
              {{"model", parameter("string", nullptr, true)},
               {"dimensions", parameter("integer", nullptr, true)},
               {"training_parameters", parameter("object", nullptr, true)},
               {"random_seed", seed}},
              {{"embeddings", port("vertex_embeddings")},
               {"context_embeddings", port("vertex_embeddings")}},
              {}),
         node_embedding},
        {card("knowledge-graph-embedding", "knowledge_graph_embedding",
              "Learn typed directed triple scores with DistMult",
              "Native DistMult with mean logistic loss over declared training positives and fixed "
              "sampled corruptions, plus L2 regularization. Relations come only from the training "
              "split; duplicate triples collapse, distinct relation identities and self triples "
              "remain. Validation never affects fitting. Report entity/relation parameters, "
              "training examples and filtered head/tail ranking metrics with average ties; no "
              "unseen-relation inference.",
              {{"model", parameter("string", nullptr, true)},
               {"dimensions", parameter("integer", nullptr, true)},
               {"training_triples", parameter("array", nullptr, true)},
               {"validation_triples", parameter("array", json::array{})},
               {"training_parameters", parameter("object", nullptr, true)}},
              {{"entities", port("vertex_embeddings")}, {"relations", port("relation_embeddings")}},
              {}),
         knowledge_embedding},
        {card("node-learning", "node_classification_regression",
              "Train a graph-based vertex classifier or regressor",
              "Native simplified graph convolution: declared mean-message layers, then a trained "
              "linear softmax or scalar regression readout. Numeric vertex_features and "
              "training_labels use objects containing typed {vertex,value} rows. Disjoint "
              "train/validation/test IDs; preprocessing and loss use training labels only. "
              "Transductive unlabeled features/topology are explicit. Saved coefficients, split "
              "metrics, objective and convergence status; one self message, collapsed parallels, "
              "weights ignored.",
              {{"task", parameter("string", nullptr, true)},
               {"vertex_features", parameter("object", nullptr, true)},
               {"training_labels", parameter("object", nullptr, true)},
               {"split", parameter("object", nullptr, true)},
               {"model_definition", parameter("object", nullptr, true)}},
              {{"predictions", port("vertex_predictions")},
               {"model", port("model_state")},
               {"metrics", port("learning_metrics")}},
              {}),
         node_learning},
        {card("graph-learning", "graph_classification_regression",
              "Train a permutation-invariant graph predictor",
              "Native independent per-graph mean message passing, sum/mean pooling, and trained "
              "linear softmax or scalar regression readout. Structural [one,in-degree,out-degree] "
              "or declared attribute features; empty graphs pool to zeros. graph_labels uses typed "
              "{graph,value} rows. Train-only fitted preprocessing and supervised loss, disjoint "
              "graph splits and saved model state. Weights ignored; no cross-graph edges.",
              {{"task", parameter("string", nullptr, true)},
               {"graph_labels", parameter("object", nullptr, true)},
               {"split", parameter("object", nullptr, true)},
               {"model_definition", parameter("object", nullptr, true)}},
              {{"predictions", port("graph_predictions")},
               {"model", port("model_state")},
               {"metrics", port("learning_metrics")}},
              {}),
         nullptr, graph_learning},
        {card("hypergraph-node-learning", "hypergraph_node_learning",
              "Learn vertex targets through the original hyperedge incidence",
              "Native hgnn-linear-v1: weighted hyperedge feature means followed by normalized "
              "vertex incidence means and a trained linear softmax/regression layer. No pairwise "
              "projection. Isolates retain features, singleton edges remain. Feature, target and "
              "split attributes are explicit; only train labels fit parameters or preprocessing. "
              "Record model state, finite predictions and metrics with split denominators. "
              "Optional model_parameters declare layers and optimizer settings.",
              {{"task", choice("classification", {"classification", "regression"})},
               {"feature_key", parameter("string", "features")},
               {"target_key", parameter("string", "target")},
               {"split_key", parameter("string", "split")},
               {"model", parameter("string", nullptr, true)},
               {"seed", parameter("integer", 0)},
               {"model_parameters", parameter("object", json::object{})}},
              {{"predictions", port("vertex_predictions")},
               {"model", port("model_state")},
               {"metrics", port("learning_metrics")}},
              {}),
         nullptr, hypergraph_learning},
        {card("graph-geolocation", "graph_based_geolocation",
              "Propagate geographic seed locations under a geodesic objective",
              "Native spatial propagation by sequential discrete geodesic median coordinate "
              "descent. Minimize positive edge weight times spherical distance, restricting "
              "coordinates to seed locations in each connected component. Undirected nonnegative "
              "input, reject loops, sum parallels. Fixed seeds remain exact; seedless components "
              "remain unresolved. Haversine handles the antimeridian; report dispersion, stopping "
              "status and optional held-out geodesic errors. No supervised model or calibrated "
              "confidence claim.",
              {{"method_family", parameter("string", nullptr, true)},
               {"seed_locations", parameter("object", nullptr, true)},
               {"method_definition", parameter("object", nullptr, true)},
               {"hold_seeds_fixed", parameter("boolean", true)},
               {"training_definition", parameter("object", nullptr, false, true)}},
              {{"locations", port("vertex_locations")}, {"confidence", port("vertex_confidence")}},
              {}),
         graph_geolocation},
        {card("graph-condensation", "graph_condensation",
              "Learn synthetic graph features by matching supervised gradients",
              "Native gradient_matching_linear_sgc_v1 matches training softmax gradients at zero "
              "readout parameters. Learn synthetic features and fix class-balanced labels on "
              "declared edgeless adjacency; this is not graph coarsening. Original weighted SGC "
              "features use summed parallel weights plus self messages; reject original loops. "
              "Budget must cover training classes and not exceed training vertices. Train labels "
              "only, explicit transductive features/topology, new synthetic IDs. Evaluate full "
              "versus synthetic training on held-out original labels over declared seeds; report "
              "objective and utility variance.",
              {{"synthetic_vertex_budget", parameter("integer", nullptr, true)},
               {"feature_key", parameter("string", "features")},
               {"label_key", parameter("string", "label")},
               {"split_key", parameter("string", "split")},
               {"method", parameter("string", nullptr, true)},
               {"seed", parameter("integer", 0)},
               {"method_parameters", parameter("object", json::object{})}},
              {{"graph", port("graph")}}, {}),
         graph_condensation},
        {card("graph-anomalies", "graph_anomaly_detection",
              "Rank graph entities against a declared reference",
              "Native structural and numeric features for vertices, original edge instances or "
              "supplied induced subgraphs. Population or explicit location/scale reference; "
              "weighted standardized L1, L2 or maximum deviation with declared minimum scale. "
              "Recompute scores, preserve zero-variance failures and disclose top-k truncation. "
              "Numerical deviation scores are not learned ground truth.",
              {{"anomaly_target", parameter("string", nullptr, true)},
               {"feature_definitions", parameter("array", nullptr, true)},
               {"normality_reference", parameter("object", nullptr, true)},
               {"scoring_definition", parameter("object", nullptr, true)},
               {"candidate_entities", parameter("array", nullptr, false, true)},
               {"subgraphs", parameter("array", nullptr, false, true)},
               {"top_k", parameter("integer", nullptr, true)}},
              {{"ranking", port("entity_ranking")}}, {}),
         graph_anomalies},
        {card("entity-resolution", "entity_resolution_blocking",
              "Find candidate record pairs and resolve declared matches",
              "Complete native disjunctive blocking rules with equality, Unicode tokens, codepoint "
              "Levenshtein or exact numeric difference. ICU NFKC and full case folding; optional "
              "missing fields fail the predicate. Input edges are unused hints. "
              "Connected-components resolution or exact bounded minimum candidate-pair "
              "disagreement partitions; neutral noncandidates and no cross-component clusters.",
              {{"task", parameter("string", nullptr, true)},
               {"blocking_rules", parameter("array", nullptr, true)},
               {"match_decision_rule", parameter("object", nullptr, false, true)},
               {"clustering_policy",
                choice("connected_components", {"connected_components", "correlation_clustering"})},
               {"solution_quality", choice("exact", {"exact", "approximate"})}},
              {{"candidates", port("record_pair_collection")},
               {"clusters", port("vertex_partition")}},
              {}),
         entity_resolution},
        {card("graph-edit-distance", "graph_edit_distance_mcs",
              "Compute minimum graph edit cost with an executable witness",
              "Exact bounded native partial correspondences over simple normalized directed or "
              "undirected graphs. Selected categorical vertex/edge labels; decimal rational costs. "
              "Vertex label replacement costs insertion plus deletion, edge substitution competes "
              "with deletion plus insertion. Returns normalized graphs and an ordered "
              "stable-handle script whose total is checked against the optimum. Weights and "
              "timestamps are ignored.",
              {{"other_graph", parameter("object", nullptr, true)},
               {"label_match_policy", choice("exact", {"exact", "ignore_labels"})},
               {"vertex_label_fields", parameter("array", json::array{"label", "type"})},
               {"edge_label_fields", parameter("array", json::array{"type"})},
               {"self_loops", choice("drop", {"drop", "reject"})},
               {"parallel_edges", choice("reject", {"reject", "collapse"})},
               {"edit_costs", parameter("object", json::object{})}},
              {{"distance", port("rational_scalar")},
               {"mapping", port("cross_graph_mapping")},
               {"edits", port("table")}},
              {}),
         graph_edit_distance},
        {card("maximum-common-subgraph", "graph_edit_distance_mcs",
              "Find the largest common graph by vertex count",
              "Exact bounded native induced matching, or label-compatible maximum vertex matching "
              "for non-induced output where isolated vertices are allowed. Preserve direction and "
              "selected categorical labels, ignore weights/timestamps. Returns a checked common "
              "graph and injective correspondence. No secondary maximum-edge objective. Explicit "
              "loop/parallel normalization.",
              {{"other_graph", parameter("object", nullptr, true)},
               {"label_match_policy", choice("exact", {"exact", "ignore_labels"})},
               {"vertex_label_fields", parameter("array", json::array{"label", "type"})},
               {"edge_label_fields", parameter("array", json::array{"type"})},
               {"self_loops", choice("drop", {"drop", "reject"})},
               {"parallel_edges", choice("reject", {"reject", "collapse"})},
               {"induced", parameter("boolean", true)}},
              {{"graph", port("graph")},
               {"mapping", port("cross_graph_mapping")},
               {"size", port("scalar")}},
              {}),
         maximum_common_subgraph},
        {card("graph-coarsening", "graph_coarsening",
              "Aggregate vertices and edges into a weighted quotient graph",
              "Supplied integer partition or native greedy maximal matching; all vertices remain "
              "represented. Undirected nonnegative input, reject loops. Sum original parallel edge "
              "weights once, retain or drop intra-cluster edges, sum or mean feature vectors. "
              "Exact rational aggregates are reported separately from rounded binary64 graph "
              "values. Greedy partition has no optimality claim.",
              {{"cluster_assignment", parameter("array", nullptr, false, true)},
               {"method", choice("greedy_matching", {"greedy_matching"})},
               {"self_loop_policy", choice("keep", {"keep", "drop"})},
               {"feature_reduction", choice("sum", {"sum", "mean"})}},
              {{"graph", port("graph")}, {"mapping", port("vertex_coarsening")}}, {}),
         graph_coarsening},
        {card("spectral-sparsification", "spectral_graph_sparsification",
              "Sample fewer edges and measure every Laplacian distortion direction",
              "Native effective-resistance sampling with replacement, exact rational draw "
              "normalization and importance reweighting. LAPACK grounded solves and all "
              "generalized eigenvalues measure numerical distortion; requested epsilon must pass. "
              "Explicit weighted undirected simple input, no loops/parallels. Preserve original "
              "IDs/attributes. Identity shortcut when budget covers positive edges, zero-weight "
              "edges removed. No probabilistic approximation guarantee is claimed.",
              {{"mode", choice("static", {"static"})},
               {"edge_budget", parameter("integer", nullptr, true)},
               {"epsilon", parameter("number", nullptr, false, true)},
               {"random_seed", parameter("integer", 0)}},
              {{"graph", port("graph")}}, {}),
         spectral_sparsification},
        {card("frequent-subgraphs", "frequent_subgraph_mining",
              "Mine patterns shared across graph transactions",
              "Exact bounded native enumeration of simple labeled directed or undirected patterns, "
              "including disconnected and isolated vertices. Support counts transactions once. "
              "Native lexicographic canonicalization has its own stable pattern IDs. Positive "
              "support fraction uses exact decimal comparison. Explicit loop and parallel "
              "policies; no Python runtime.",
              {{"minimum_support_fraction", parameter("number", nullptr, true)},
               {"minimum_edges", parameter("integer", 1)},
               {"maximum_edges", parameter("integer", nullptr, true)},
               {"minimum_vertices", parameter("integer", 1)},
               {"maximum_vertices", parameter("integer", nullptr, false, true)},
               {"induced", parameter("boolean", false)},
               {"label_semantics",
                choice("vertex_and_edge_type",
                       {"unlabeled", "vertex_type", "edge_type", "vertex_and_edge_type"})},
               {"self_loops", choice("reject", {"reject", "drop"})},
               {"parallel_edges", choice("reject", {"reject", "collapse"})},
               {"include_supporting_graph_ids", parameter("boolean", false)}},
              {{"patterns", port("pattern_collection")}, {"count", port("scalar")}}, {}),
         nullptr, frequent_subgraphs},
        {card("single-graph-frequent-subgraphs", "single_graph_frequent_subgraph_mining",
              "Mine frequent labeled patterns within a graph",
              "Exact connected undirected patterns including single vertices. Minimum-image "
              "support is the smallest host image-set size over all injective embeddings. Every "
              "vertex needs the selected label or type. Reject loops; explicit parallel collapse. "
              "Native canonical IDs, bounded enumeration and complete counts; count mode does not "
              "materialize patterns.",
              {{"minimum_image_support", parameter("integer", nullptr, true)},
               {"max_pattern_edges", parameter("integer", nullptr, true)},
               {"match_mode", choice("non_induced", {"non_induced", "induced"})},
               {"output_mode", choice("count", {"count", "patterns"})},
               {"vertex_label_field", choice("label", {"label", "type"})},
               {"parallel_edges", choice("reject", {"reject", "collapse"})},
               {"include_images", parameter("boolean", false)}},
              {{"patterns", port("pattern_collection")}, {"count", port("scalar")}}, {}),
         single_graph_frequent},
        {card("temporal-motifs", "temporal_motif_mining",
              "Count graph patterns with ordered edge events",
              "Exact native structural matching and injective event assignments. Rational UTC "
              "timestamps, acyclic partial order, inclusive duration limit, optional temporal "
              "inducedness and typed predicates. Event tuples in query-edge input order identify "
              "occurrences. Counts and vertex participation remain complete when instance lists "
              "are capped.",
              {{"temporal_motif", parameter("object", nullptr, true)},
               {"maximum_duration_seconds", parameter("number", nullptr, true)},
               {"allow_equal_timestamps", parameter("boolean", false)},
               {"temporal_induced", parameter("boolean", false)},
               {"list_instances", parameter("boolean", false)},
               {"result_limit", positive(nullptr, true)}},
              {{"instances", port("temporal_occurrence_collection")}}, {}),
         temporal_motifs},
        {card("knn-graph", "knn_graph_construction", "Connect nearby feature vectors",
              "Native exhaustive pairwise Euclidean, squared Euclidean or cosine distances with "
              "self-exclusion and input-order tie breaking. Directed, union or mutual "
              "symmetrization. Cosine rejects zero vectors. Exact neighbor search under numerical "
              "distances even when approximate is requested; preserves typed vector IDs.",
              {{"k", parameter("integer", nullptr, true)},
               {"distance",
                choice("squared_euclidean", {"squared_euclidean", "euclidean", "cosine"})},
               {"search_mode", choice("exact", {"exact", "approximate"})},
               {"symmetrization", choice("directed", {"directed", "union", "mutual"})}},
              {{"graph", port("graph")}, {"neighbors", port("neighbor_lists")}}, {}),
         nullptr, knn_graph},
        {card(
             "hypergraph-partitioning", "hypergraph_partitioning",
             "Partition hyperedges directly with bounded vertex weights",
             "Exact native enumeration of nonempty parts, optimizing weighted cut-net or "
             "connectivity-minus-one without graph projection. Exact rational vertex and hyperedge "
             "weights, decimal imbalance tolerance and upper part-weight bound. Certified "
             "infeasibility when no partition qualifies; exponential search obeys work budgets.",
             {{"num_parts", parameter("integer", nullptr, true)},
              {"imbalance_tolerance", real(0.03, 0)},
              {"objective", choice("cut_net", {"cut_net", "connectivity_minus_one"})}},
             {{"partition", port("vertex_partition")}}, {}),
         nullptr, hypergraph_partitioning},
        {card("subgraph-isomorphism", "subgraph_isomorphism",
              "Find matches for a supplied graph pattern",
              "Exact native induced or non-induced injective matching, preserving direction, loops "
              "and parallel multiplicities. Declarative typed vertex and edge predicates; distinct "
              "query edges must match distinct data edges. Capped mapping collections are "
              "explicitly incomplete.",
              {{"query_graph", parameter("object", nullptr, true)},
               {"induced", parameter("boolean", false)},
               {"vertex_predicates", parameter("array", json::array{})},
               {"edge_predicates", parameter("array", json::array{})},
               {"result_limit", positive(nullptr, true)}},
              {{"matches", port("vertex_mappings")}}, {}),
         subgraph_isomorphism},
        {card("motif-counting", "graph_motif_counting", "Count supplied connected motifs",
              "Exact structural embeddings with explicit occurrence identity: all mappings or "
              "unique vertex-set and image-edge classes. Preserve direction; simple projections "
              "discard loops, duplicate edges and weights. Non-induced motifs on the same vertex "
              "set can be distinct instances. Counts remain complete when lists are capped.",
              {{"motifs", parameter("array", nullptr, true)},
               {"induced", parameter("boolean", false)},
               {"occurrence_identity",
                choice("unique_vertex_set_and_mapping_class",
                       {"unique_vertex_set_and_mapping_class", "all_embeddings"})},
               {"list_instances", parameter("boolean", false)},
               {"result_limit_per_motif", positive(nullptr, true)}},
              {{"counts", port("table")}, {"instances", port("motif_instances")}}, {}),
         motif_counting},
        {card("graphlet-counting", "graphlet_counting",
              "Count connected induced graph shapes and vertex roles",
              "Native isomorphism classification against the complete connected undirected graph "
              "atlas for sizes two through seven. Static atlas IDs and exact automorphism orbits "
              "are embedded; Python is not required. Discard loops and duplicate edges, ignore "
              "weights. Counts and optional orbit participation stay complete when memberships are "
              "capped.",
              {{"graphlet_sizes", parameter("array", nullptr, true)},
               {"include_orbit_counts", parameter("boolean", false)},
               {"list_instances", parameter("boolean", false)},
               {"result_limit_per_graphlet", positive(nullptr, true)}},
              {{"counts", port("table")}, {"instances", port("graphlet_instances")}}, {}),
         graphlet_counting},
        {card("group-steiner-tree", "group_steiner_tree",
              "Connect representatives of every required group",
              "Exact bounded vertex-subset optimization with a minimum spanning tree for each "
              "feasible induced subgraph. Covers every group and required vertex, allowing "
              "overlapping representatives. Undirected nonnegative weighted input, loops removed, "
              "cheapest original parallel edge retained. Reports exact rational cost or certified "
              "infeasibility.",
              {{"groups", parameter("array", nullptr, true)},
               {"required_vertices", parameter("array", nullptr, false, true)},
               {"solution_quality", choice("exact", {"exact", "approximate"})}},
              {{"vertices", port("vertex_set")}, {"edges", port("edge_set")}}, {}),
         group_steiner},
        {card("network-alignment", "network_alignment",
              "Align two graphs while conserving edges and supplied similarities",
              "Exact bounded global injective assignment covering every vertex of the smaller "
              "graph. Maximize topology_weight times conserved edge value plus pair priors. "
              "Direction must match. Drop loops and collapse unweighted or sum nonnegative "
              "weighted parallel edges. Weighted conservation is the minimum of paired normalized "
              "edge weights.",
              {{"other_graph", parameter("object", nullptr, true)},
               {"alignment_mode", choice("global_one_to_one", {"global_one_to_one"})},
               {"node_similarity_prior", parameter("array", nullptr, false, true)},
               {"topology_weight", real(1, 0)},
               {"weight_mode", weights},
               {"solution_quality", choice("exact", {"exact", "approximate"})}},
              {{"mapping", port("cross_graph_mapping")}}, {}),
         network_alignment},
        {card("influence-maximization", "influence_maximization",
              "Choose seeds that maximize expected diffusion",
              "Exact rational live-edge and seed-set enumeration for independent cascade or "
              "random-threshold LT. Fixed LT thresholds use progressive activation, including "
              "spontaneous activation at zero. Directed input, explicit probabilities, loops "
              "removed. Parallel IC probabilities combine by independent failure; LT weights sum "
              "with incoming mass at most one. Exponential work is bounded; no sampling claims.",
              {{"diffusion_model", parameter("string", nullptr, true)},
               {"seed_set_size", parameter("integer", nullptr, true)},
               {"vertex_thresholds", parameter("array", nullptr, false, true)}},
              {{"vertices", port("vertex_set")}, {"spread", port("scalar")}}, {}),
         influence_maximization},
        {card("null-model-significance", "null_model_significance_testing",
              "Compare a statistic with a random graph ensemble",
              "Uniform G(n,m), or uniform stub pairing conditioned on simplicity and exact degree "
              "invariants. Dense fixed-degree graphs use complement sampling. Preserve direction, "
              "discard loops and collapse duplicates. Statistics: triangles, directed triangles, "
              "k-cliques, density or a supplied-partition modularity. Report every sample, "
              "population standard deviation and declared empirical tail; no hidden pseudocount.",
              {{"null_model", choice("degree_preserving_configuration",
                                     {"degree_preserving_configuration", "erdos_renyi"})},
               {"statistic_definition", parameter("object", nullptr, true)},
               {"observed_value", parameter("number", nullptr, false, true)},
               {"sample_count", parameter("integer", nullptr, true)},
               {"random_seed", seed},
               {"tail", choice("greater", {"greater", "less", "two_sided_about_null_mean"})},
               {"max_randomization_attempts", positive(100000)},
               {"return_randomized_edges", parameter("boolean", false)}},
              {{"samples", port("numeric_sample")}}, {}),
         null_significance},
        {card("persistent-homology", "persistent_homology",
              "Track connected components and holes across edge thresholds",
              "Exact sparse boundary reduction of a flag complex over a declared prime field. "
              "Vertices start at zero; include cofaces needed to compute deaths in requested "
              "dimensions. Undirected input; reject loops, require nonnegative weights, keep "
              "minimum parallel filtration. Optional cutoff marks unpaired intervals "
              "right-censored.",
              {{"max_homology_dimension", parameter("integer", 1)},
               {"max_filtration", parameter("number", nullptr, false, true)},
               {"field_prime", parameter("integer", 2)}},
              {{"intervals", port("persistence_intervals")}}, {}),
         persistent_homology},
        {card("seeded-local-community", "seeded_local_community_detection",
              "Find a community around required seeds",
              "Heuristic personalized-PageRank degree-normalized sweep with required seeds first. "
              "Returns the lowest defined weighted conductance among feasible prefixes. Exact "
              "cut/volume recomputation, no global-optimum claim. Undirected input; reject loops, "
              "sum nonnegative parallel weights. If all conductance denominators vanish, return "
              "the seeds.",
              {{"seeds", parameter("array", nullptr, true)},
               {"maximum_volume", parameter("number", nullptr, false, true)},
               {"method_parameters", parameter("object", json::object{})},
               {"solution_quality", choice("heuristic", {"heuristic"})}},
              {{"vertices", port("vertex_set")}}, {}),
         seeded_local_community},
        {card("force-directed-layout", "graph_layout_force_directed",
              "Compute a force-directed network drawing",
              "Native Fruchterman-Reingold iterations in two or three dimensions. Explicit 0.01 "
              "distance regularization, linear cooling from one tenth of the maximum coordinate "
              "span, no final rescaling. Recompute matching potential and uncooled force residual; "
              "no drawing optimality claim. Project direction, drop loops, collapse unweighted or "
              "sum weighted parallels.",
              {{"dimensions", parameter("integer", 2)},
               {"force_model", choice("fruchterman_reingold", {"fruchterman_reingold"})},
               {"weight_mode", weights},
               {"iterations", parameter("integer", 50)},
               {"random_seed", parameter("integer", 0)},
               {"initial_positions", parameter("array", nullptr, false, true)},
               {"optimal_distance", parameter("number", nullptr, false, true)},
               {"force_tolerance", real(1e-6, 0)},
               {"solution_quality", choice("approximate", {"approximate", "converged"})}},
              {{"positions", port("vertex_positions")}}, {}),
         force_layout},
        {card("laplacian-eigenpairs", "graph_laplacian_eigenpairs",
              "Compute Laplacian eigenvalues and eigenvectors",
              "Native LAPACK symmetric eigensolver with independently recomputed absolute residual "
              "and orthogonality checks. Combinatorial or symmetric-normalized Laplacian, "
              "including isolates. Undirected input; reject loops and negative weights, sum "
              "parallel weights. Dense solver uses work budgets; no iteration parameter.",
              {{"num_eigenpairs", parameter("integer", nullptr, true)},
               {"laplacian", choice("combinatorial", {"combinatorial", "symmetric_normalized"})},
               {"selection", choice("smallest", {"smallest", "largest"})},
               {"tolerance", real(1e-6, 0)}},
              {{"eigenpairs", port("eigenpairs")}}, {}),
         laplacian_eigenpairs},
        {card("graph-signal-denoising", "graph_signal_denoising",
              "Smooth noisy measurements over a graph",
              "Minimize half squared signal error plus Laplacian quadratic, weighted total "
              "variation, or explicit graph-trend penalty. Native positive-definite solve or "
              "accelerated feasible-dual optimization; tolerance bounds objective gap, with a "
              "separate L2 solution-error bound. Undirected input, no loops, nonnegative summed "
              "parallel weights.",
              {{"observed_signal", parameter("array", nullptr, true)},
               {"regularizer", choice("total_variation", {"total_variation", "trend_filtering",
                                                          "laplacian_quadratic"})},
               {"regularization_strength", parameter("number", nullptr, true)},
               {"difference_order", parameter("integer", 0)},
               {"tolerance", real(1e-6, 0)},
               {"max_iterations", positive(1000)}},
              {{"signal", port("vertex_signal")}}, {}),
         signal_denoising},
        {card("simrank", "simrank_vertex_similarity",
              "Compare vertices by the similarity of their neighbors",
              "Native float64 SimRank fixed-point iteration with a recomputed contraction error "
              "bound. Incoming or undirected-projection neighborhoods; drop loops and duplicates, "
              "ignore weights. Single-source output excludes itself. Top-k ports explicitly "
              "disclose omitted pairs.",
              {{"query_mode", parameter("string", nullptr, true)},
               {"source_vertex", parameter("vertex_id", nullptr, false, true)},
               {"target_vertex", parameter("vertex_id", nullptr, false, true)},
               {"decay_factor", real(0.8, 0, 1)},
               {"direction_mode", choice("incoming", {"incoming", "undirected_projection"})},
               {"top_k", positive(nullptr, true)},
               {"solution_quality", choice("exact", {"exact", "approximate"})},
               {"convergence_tolerance", real(1e-6, 0)},
               {"max_iterations", positive(1000)}},
              {{"pairs", port("pair_scores")}}, {}),
         simrank},
        {card("widest-paths", "widest_paths", "Find the greatest bottleneck capacity from a source",
              "Exact max-min capacities with a predecessor witness, preserving direction. Every "
              "edge needs nonnegative capacity; loops discarded and largest parallel capacity "
              "wins. Zero is reachable. Source infinity and unreachable nulls have distinct flags.",
              {{"source_vertex", parameter("vertex_id", nullptr, true)}},
              {{"paths", port("widest_path_tree")}}, {}),
         widest_paths},
        {card("top-k-critical-paths", "top_k_critical_paths_dag",
              "Find the highest-cost paths through a DAG",
              "Exact rational k-best DAG paths, retaining parallel edge identities and negative "
              "weights. Omitted sources and sinks select zero-in/out-degree vertices. A zero-edge "
              "path is included when a source is also a sink. Finishing top-k does not imply the "
              "path collection is exhaustive.",
              {{"k", parameter("integer", nullptr, true)},
               {"sources", parameter("array", nullptr, false, true)},
               {"sinks", parameter("array", nullptr, false, true)}},
              {{"paths", port("path_set")}}, {}),
         critical_paths},
        {card("temporal-paths", "temporal_fastest_paths",
              "Find earliest arrivals or fastest journeys through timed events",
              "Exact rational time-expanded shortest paths. Directed event input; every edge needs "
              "a timestamp and nonnegative duration attribute. Waiting is allowed. Fastest "
              "duration excludes waiting before initial departure. Inclusive ready time and "
              "deadline preserve distinct parallel events.",
              {{"source", parameter("vertex_id", nullptr, true)},
               {"ready_time", parameter("number", nullptr, true)},
               {"deadline", parameter("number", nullptr, false, true)},
               {"objective", choice("fastest_duration", {"fastest_duration", "earliest_arrival"})},
               {"duration_attribute", parameter("string", "duration")}},
              {{"paths", port("temporal_path_table")}}, {}),
         temporal_paths},
        {card("bounded-paths-cycles", "hop_constrained_cycle_path_enumeration",
              "Enumerate bounded simple paths or cycles",
              "Exact directed simple edge paths and cycles up to max_hops. Drop loops; collapse to "
              "first parallel edge or retain identities. Optional strict chronological order "
              "applies after canonical cycle rotation. A result cap retains the shortest sequences "
              "while the total count remains exhaustive.",
              {{"task", parameter("string", nullptr, true)},
               {"source", parameter("vertex_id", nullptr, false, true)},
               {"target", parameter("vertex_id", nullptr, false, true)},
               {"anchor_edge", parameter("vertex_id", nullptr, false, true)},
               {"max_hops", parameter("integer", nullptr, true)},
               {"result_limit", positive(nullptr, true)},
               {"chronological_order_required", parameter("boolean", false)},
               {"parallel_edge_policy", choice("collapse_first", {"collapse_first", "preserve"})}},
              {{"sequences", port("edge_sequence_collection")}}, {}),
         bounded_paths_cycles},
        {card("community-detection", "community_detection", "Divide a network into communities",
              "Undirected modularity or constant Potts objective. Exact mode enumerates partitions "
              "with rational objectives; heuristic mode uses seeded positive-gain vertex moves and "
              "makes no global-optimum claim. Drop loops and collapse unweighted or sum weighted "
              "parallel edges. CPM is internal edge weight minus resolution times within-part "
              "vertex pairs.",
              {{"quality_function", choice("modularity", {"modularity", "constant_potts_model"})},
               {"resolution", real(1, 0)},
               {"weight_mode", weights},
               {"solution_quality", choice("heuristic", {"exact", "heuristic"})},
               {"seed", parameter("integer", 0)}},
              {{"partition", port("vertex_partition")}, {"groups", port("vertex_groups")}}, {}),
         community_detection},
        {card("balanced-partitioning", "balanced_graph_partitioning",
              "Split a graph into balanced groups with few crossing edges",
              "Exact bounded partition search with nonempty parts and both lower and upper balance "
              "limits. Undirected input, nonnegative edge weights, loop removal and duplicate "
              "collapse or weighted sum. Normalized cut sums each part boundary divided by its "
              "declared balance size. Decimal-rational imbalance tolerance; exact objective and "
              "infeasibility certificates.",
              {{"num_parts", parameter("integer", nullptr, true)},
               {"balance_mode", choice("vertex_count", {"vertex_count", "vertex_weight"})},
               {"vertex_weights", parameter("array", nullptr, false, true)},
               {"imbalance_tolerance", real(0.03, 0)},
               {"edge_weight_mode", weights},
               {"objective", choice("edge_cut", {"edge_cut", "normalized_cut"})},
               {"solution_quality", choice("exact", {"exact", "approximate"})}},
              {{"partition", port("vertex_partition")}, {"groups", port("vertex_groups")}}, {}),
         balanced_partitioning},
        {card("signed-balance", "signed_network_structural_balance",
              "Check balance or minimize frustrated connections",
              "Exact signed parity balance test and bounded rational frustration minimization. "
              "Every edge type is positive or negative. Undirected input; drop loops, reject "
              "contradictory parallel signs and collapse unweighted or sum weighted parallels. "
              "Zero-cost violations still make the network structurally unbalanced.",
              {{"task", parameter("string", nullptr, true)},
               {"weight_mode", weights},
               {"solution_quality", choice("exact", {"exact", "approximate"})}},
              {{"partition", port("vertex_partition")}}, {}),
         signed_balance},
        {card("densest-subgraph", "densest_subgraph",
              "Find the region with the most edges or cliques per vertex",
              "Exact induced k-clique count divided by vertex count. Weighted density is defined "
              "for clique_order=2, summing parallel weights. Undirected input; loops discarded. "
              "Native rational maximum-weight closure for minimum_vertices=1; bounded exhaustive "
              "cardinality search otherwise.",
              {{"clique_order", positive(2)},
               {"minimum_vertices", positive(1)},
               {"weight_mode", weights},
               {"solution_quality", choice("exact", {"exact", "approximate"})}},
              {{"vertices", port("vertex_set")}}, {}),
         densest_subgraph},
        {card("densest-k-subgraph", "densest_k_subgraph",
              "Find exactly k vertices with the greatest internal edge value",
              "Exact bounded cardinality search. Sum parallel nonnegative weights, discard loops, "
              "require undirected input. An approximate request receives the stronger exact result "
              "when search completes.",
              {{"k", parameter("integer", nullptr, true)},
               {"weight_mode", weights},
               {"solution_quality", choice("exact", {"exact", "approximate"})}},
              {{"vertices", port("vertex_set")}}, {}),
         densest_k_subgraph},
        {card("quasi-cliques", "quasi_clique_mining",
              "Find groups meeting a minimum internal-degree fraction",
              "Exact gamma quasi-cliques on an undirected simple projection. Thresholds use "
              "decimal-rational gamma; maximality is relative to all qualifying sets within the "
              "size bounds. Search is bounded by work and output budgets.",
              {{"gamma", parameter("number", nullptr, true)},
               {"minimum_size", parameter("integer", nullptr, true)},
               {"maximum_size", positive(nullptr, true)},
               {"maximal_only", parameter("boolean", true)}},
              {{"groups", port("vertex_groups")}}, {}),
         quasi_cliques},
        {card("maximal-bicliques", "maximal_biclique_enumeration",
              "Find completely connected groups across two sides",
              "Exact inclusion-maximal bicliques with nonempty sides. Explicit disjoint partitions "
              "must cover every vertex. Undirected input; loops discarded and duplicate edges "
              "collapsed. Capped memberships are marked incomplete.",
              {{"left_partition", parameter("array", nullptr, true)},
               {"right_partition", parameter("array", nullptr, true)},
               {"minimum_left_size", positive(1)},
               {"minimum_right_size", positive(1)},
               {"result_limit", positive(nullptr, true)}},
              {{"bicliques", port("bipartite_groups")}}, {}),
         maximal_bicliques},
        {card("butterfly-counting", "butterfly_counting_bipartite",
              "Count four-way connections between two sides",
              "Exact 2-by-2 biclique counts, participation and alpha/beta cores. Every vertex "
              "requires attributes.side=left|right. Reject directed input, loops and same-side "
              "edges; collapse duplicates. Core thresholds explicitly use degree or butterfly "
              "participation.",
              {{"mode", choice("count", {"count", "per_vertex", "per_edge", "alpha_beta_core"})},
               {"alpha", positive(nullptr, true)},
               {"beta", positive(nullptr, true)},
               {"core_measure",
                choice("butterfly_participation", {"butterfly_participation", "degree"})},
               {"solution_quality", choice("exact", {"exact", "approximate"})}},
              {{"count", port("scalar")},
               {"scores", port("vertex_scores")},
               {"edges", port("edge_scores")},
               {"cores", port("vertex_groups")}},
              {}),
         butterflies},
        {card("transitive-closure", "transitive_closure_reachability",
              "Find which places can reach each other",
              "Exact reflexive reachability: every vertex reaches itself by a zero-length path. "
              "Preserve graph direction, ignore weights, loops and duplicates. Count-only closure "
              "has a complete scalar and incomplete pair-list port.",
              {{"query_mode", choice("full_transitive_closure",
                                     {"single_pair", "batch_pairs", "full_transitive_closure"})},
               {"query_pairs", parameter("array", nullptr, false, true)},
               {"enumerate_closure_edges", parameter("boolean", true)}},
              {{"pairs", port("table")}, {"count", port("scalar")}}, {}),
         transitive_closure},
        {card("overlapping-communities", "overlapping_community_detection",
              "Find overlapping tightly connected groups",
              "Exact k-clique percolation. Undirected simple projection; discard loops and "
              "duplicates. Communities can overlap. Unassigned vertices are outside all "
              "percolation communities before minimum-size display filtering.",
              {{"k", parameter("integer", nullptr, true)},
               {"minimum_community_size", positive(1)},
               {"include_unassigned_vertices", parameter("boolean", true)}},
              {{"groups", port("vertex_groups")}}, {}),
         overlapping_communities},
        {card("breadth-first-search", "breadth_first_search",
              "Connections within a number of steps",
              "Minimum hop distances with explicit independent or nearest-source searches. "
              "Preserve direction; discard loops and collapse duplicate arcs; weights are ignored. "
              "IDs are signed int64 or strings.",
              {{"sources", parameter("array", nullptr, true)},
               {"source_mode", source_mode},
               {"depth_limit", depth},
               {"return_predecessors", parameter("boolean", true)}},
              {{"vertices", port("vertex_set")}, {"distances", port("table")}}, gpu),
         bfs},
        {card("triangle-counting", "triangle_counting_listing", "Count or list triangles",
              "Count three-vertex cliques of an undirected graph. Discard loops and collapse "
              "duplicate edges; weights are ignored. GPU enumeration uses native CPU "
              "materialization with count verification.",
              {{"mode", mode}, {"result_limit", limit}},
              {{"count", port("scalar")}, {"groups", port("vertex_groups")}},
              {json::object{{"id", "tot"},
                            {"device", "gpu"},
                            {"compiled", original_triangles_compiled("tot")}},
               json::object{{"id", "wetric"},
                            {"device", "gpu"},
                            {"compiled", original_triangles_compiled("wetric")}}}),
         triangles},
        {card("single-source-shortest-paths", "single_source_shortest_paths",
              "Shortest weighted paths from one vertex",
              "Nonnegative lengths; preserve direction, drop loops and keep minimum parallel "
              "length. CPU returns exact rational costs over admitted binary64 weights; GPU "
              "returns float64 costs. Cutoff is inclusive.",
              {{"source", parameter("vertex_id", nullptr, true)},
               {"cutoff", parameter("number", nullptr, false, true)},
               {"return_predecessors", parameter("boolean", true)}},
              {{"distances", port("vertex_scores")}}, gpu),
         shortest_paths},
        {card("many-source-shortest-paths", "many_source_shortest_paths",
              "Shortest paths between selected vertex sets",
              "Selected origins and destinations, or all vertices for null. Nonnegative lengths, "
              "minimum parallel length and preserved direction; CPU exact costs and GPU float64 "
              "costs.",
              {{"origins", parameter("array", nullptr, false, true)},
               {"destinations", parameter("array", nullptr, false, true)},
               {"weight_mode", choice("edge_weight", {"edge_weight", "unweighted"})}},
              {{"distances", port("table")}}, gpu),
         many_shortest_paths},
        {card("spanning-tree-forest", "spanning_tree_forest", "Minimum or maximum spanning forest",
              "Undirected weighted forests with isolates retained. Negative lengths are allowed. "
              "Keep minimum or maximum parallel weights according to the objective; discard loops.",
              {{"objective", choice("minimum", {"minimum", "maximum"})},
               {"require_connected", parameter("boolean", false)}},
              {{"vertices", port("vertex_set")}, {"edges", port("edge_set")}}, gpu),
         spanning_forest},
        {card("connected-components", "connected_components", "Connected vertex groups",
              "Weak or strong connectivity. Weak mode uses an undirected projection; strong mode "
              "preserves direction. Loops, duplicate edges and weights do not affect membership.",
              {{"connectivity_mode",
                choice("weakly_connected", {"weakly_connected", "strongly_connected"})}},
              {{"groups", port("vertex_groups")}}, gpu),
         components},
        {card("topological-sort", "topological_sort", "Order a directed acyclic graph",
              "Return a deterministic topological order. Reject directed cycles, including "
              "self-loops. Duplicate arcs collapse; weights are ignored.",
              {}, {{"vertices", port("vertex_set")}}, {}),
         topological},
        {card("pagerank", "centrality_influential_node_mining", "PageRank influence scores",
              "Directed random-walk scores with uniform restart and dangling distribution. Drop "
              "loops, sum parallel weights and independently verify the fixed-point residual.",
              {{"alpha", real(0.85, 0, 1)},
               {"tolerance", real(1e-9, 0)},
               {"max_iterations", positive(1000)},
               {"weight_mode", weights}},
              {{"scores", port("vertex_scores")}}, gpu),
         pagerank},
        {card("degree-centrality", "centrality_influential_node_mining",
              "Rank vertices by their number of connections",
              "Exact degree scores with outgoing, incoming, both or undirected-projection "
              "semantics. Drop loops, collapse duplicate edges and ignore weights. Optional "
              "normalization divides by n-1; isolates score zero.",
              {{"normalized", parameter("boolean", true)},
               {"direction_mode",
                choice("outgoing", {"outgoing", "incoming", "both", "undirected_projection"})}},
              {{"scores", port("vertex_scores")}}, {}),
         degree_centrality},
        {card("betweenness-centrality", "centrality_influential_node_mining",
              "Rank vertices that connect shortest paths",
              "All-source betweenness excluding endpoints. Preserve direction, drop loops and keep "
              "minimum parallel length. CPU supports exact rational scores and strictly positive "
              "weighted paths; GPU profiles use unweighted paths with declared floating-point "
              "arithmetic.",
              {{"normalized", parameter("boolean", true)}, {"weight_mode", weights}},
              {{"scores", port("vertex_scores")}}, betweenness_backends),
         betweenness},
        {card("personalized-pagerank", "personalized_pagerank_rwr",
              "Restart walks around seed vertices",
              "Seeded PageRank with explicit direction, weight and dangling policies. Full score "
              "port stays complete when the displayed ranking is filtered or capped.",
              {{"seed_vertices", parameter("array", nullptr, true)},
               {"restart_probability", real(0.15, 0, 1)},
               {"direction_mode",
                choice("outgoing", {"outgoing", "incoming", "undirected_projection"})},
               {"weight_mode", weights},
               {"dangling_policy",
                choice("redistribute_to_seeds",
                       {"redistribute_to_seeds", "redistribute_uniformly", "self_loop"})},
               {"convergence_tolerance", real(1e-9, 0)},
               {"max_iterations", positive(1000)},
               {"exclude_seeds_from_output", parameter("boolean", false)},
               {"top_k", positive(nullptr, true)}},
              {{"scores", port("vertex_scores")}}, gpu),
         personalized_pagerank},
        {card("link-prediction", "link_prediction",
              "Score potential links from local neighborhoods",
              "Undirected simple neighborhoods; loops and weights ignored. CPU supports eight "
              "local measures; GPU supports Jaccard. Candidate limits apply before top_k; capped "
              "output is explicitly incomplete.",
              {{"scoring_measure",
                choice("jaccard",
                       {"jaccard", "common_neighbors", "adamic_adar", "resource_allocation",
                        "preferential_attachment", "sorensen", "overlap", "cosine"})},
               {"candidate_pairs", parameter("array", nullptr, false, true)},
               {"exclude_existing_edges", parameter("boolean", true)},
               {"top_k", positive(nullptr, true)}},
              {{"pairs", port("table")}}, gpu),
         link_prediction},
        {card("maximal-independent-set", "maximal_independent_set",
              "Find a non-conflicting group that cannot be extended",
              "Greedy maximal independent set with verified independence and maximality; no "
              "maximum-size claim. Undirected simple projection; discard loops and duplicate "
              "edges, ignore weights and preserve isolates.",
              {{"random_seed", seed}}, {{"vertices", port("vertex_set")}}, cpp_gpu),
         maximal_independent},
        {card("vertex-coloring", "vertex_coloring", "Assign different colors to nearby vertices",
              "Proper greedy distance-1 or distance-2 coloring; no minimum-color claim. Undirected "
              "simple projection with isolates preserved. GPU colors the native C++ constructed "
              "distance conflict graph.",
              {{"distance", parameter("integer", 1)}, {"random_seed", seed}},
              {{"colors", port("table")}}, cpp_gpu),
         vertex_coloring},
        {card("random-walks", "random_walk_generation", "Generate walks from chosen vertices",
              "Uniform, weighted or node2vec walks with length measured in transitions. Preserve "
              "direction and loops. Uniform walks collapse parallel neighbors; weighted walks sum "
              "parallel weights. CPU probabilities use exact rational arithmetic. Repeated starts "
              "produce separate walks.",
              {{"start_vertices", parameter("array", nullptr, true)},
               {"length", parameter("integer", nullptr, true)},
               {"walk_model", choice("uniform", {"uniform", "weighted", "node2vec"})},
               {"p", real(1, 0)},
               {"q", real(1, 0)},
               {"random_seed", seed}},
              {{"walks", port("walk_sample")}}, gpu),
         random_walks},
        {card("neighborhood-sampling", "neighborhood_sampling",
              "Sample connections around starting vertices",
              "Outgoing edge-instance sampling with hop and seed-batch provenance. Support uniform "
              "or exact weighted draws, replacement, typed fanouts and inclusive time cutoff. "
              "Fanout -1 includes every eligible edge, including zero-weight edges; loops and "
              "parallel identities are retained.",
              {{"seeds", parameter("array", nullptr, true)},
               {"fanouts", parameter("array", nullptr, true)},
               {"replacement", parameter("boolean", false)},
               {"sampling_model", choice("uniform", {"uniform", "weighted"})},
               {"edge_type_fanouts", parameter("object", nullptr, false, true)},
               {"time_cutoff", parameter("number", nullptr, false, true)},
               {"random_seed", seed}},
              {{"edges", port("edge_sample")}, {"vertices", port("vertex_set")}}, {}),
         neighborhood_sampling},
        {card("induced-subgraph", "induced_subgraph_ego_extraction",
              "Extract a graph around selected vertices",
              "Exact induced or ego subgraph, preserving typed IDs, edge instances and properties. "
              "Ego radius includes all vertices within that distance. Direction affects discovery "
              "only; output retains original edge direction. GPU ego discovery uses libcugraph BFS "
              "with native materialization.",
              {{"mode", parameter("string", nullptr, true)},
               {"vertices_or_seeds", parameter("array", nullptr, true)},
               {"radius", parameter("integer", 1)},
               {"direction_mode",
                choice("outgoing", {"outgoing", "incoming", "undirected_projection"})}},
              {{"graph", port("graph")}, {"vertices", port("vertex_set")}}, gpu),
         induced_subgraph},
        {card("max-flow-min-cut", "max_flow_min_cut",
              "Find capacity and bottlenecks between two places",
              "Exact rational flow and cut certificate. Sum parallel capacities, discard loops and "
              "treat undirected edges as two directed arcs. Optional vertex capacities use typed "
              "{vertex,capacity} records and include explicitly limited terminals. Mixed cuts "
              "return original edge IDs plus cut vertices.",
              {{"source", parameter("vertex_id", nullptr, true)},
               {"sink", parameter("vertex_id", nullptr, true)},
               {"capacity_mode", choice("edge_weight", {"edge_weight", "unit_capacity"})},
               {"return_cut_side", parameter("boolean", true)},
               {"vertex_capacities", parameter("array", nullptr, false, true)},
               {"solution_quality", choice("exact", {"exact", "approximate"})}},
              {{"value", port("scalar")}, {"vertices", port("vertex_set")}},
              original_optimization_backends("max-flow-min-cut")),
         max_flow},
        {card("weighted-matching", "general_graph_weighted_matching",
              "Find the highest-value non-conflicting pairs",
              "Exact maximum-weight matching on an undirected graph, with no cardinality "
              "constraint. Require nonnegative weights; discard loops and keep the largest "
              "parallel weight. Preserve selected original edge IDs and return exact rational "
              "totals over admitted binary64 weights. Zero-weight edges may be omitted.",
              {{"solution_quality", choice("exact", {"exact", "approximate"})}},
              {{"edges", port("edge_set")}}, {}),
         weighted_matching},
        {card("bipartite-matching", "bipartite_matching_assignment",
              "Match items on two sides by count, value or cost",
              "Exact cardinality, weight or cost matching with attributes.side=left|right on every "
              "vertex. Reject same-side edges and loops; keep the best parallel edge. Weighted "
              "objectives require explicit weights. Without required smaller-side coverage, empty "
              "matching may be optimal. Infeasible coverage has no witness port.",
              {{"objective", parameter("string", nullptr, true)},
               {"weight_mode", weights},
               {"perfect_matching_required", parameter("boolean", false)},
               {"solution_quality", choice("exact", {"exact", "approximate"})}},
              {{"edges", port("edge_set")}}, original_optimization_backends("bipartite-matching")),
         bipartite_matching},
        {card("maximal-cliques", "maximal_clique_enumeration",
              "Find complete groups that cannot be extended",
              "Exact maximal cliques in an undirected simple projection. Drop loops and duplicate "
              "edges; ignore weights. Original GPU kernels supply a count, with bounded C++ "
              "materialization and explicit list completeness.",
              {{"minimum_clique_size", positive(1)}, {"result_limit", positive(nullptr, true)}},
              {{"groups", port("vertex_groups")}}, original_mining_backends("maximal-cliques")),
         maximal_cliques},
        {card("maximum-clique", "maximum_clique", "Find the largest fully connected group",
              "Exact maximum clique, optionally all tied optima. Undirected simple projection; "
              "loops, duplicate edges and weights ignored. Original GPU witnesses are checked by "
              "native coloring or exact search; ties use native materialization.",
              {{"return_all_ties", parameter("boolean", false)}},
              {{"groups", port("vertex_groups")}, {"vertices", port("vertex_set")}},
              original_mining_backends("maximum-clique")),
         maximum_clique},
        {card("k-cliques", "k_clique_counting_enumeration",
              "Count or list complete groups of a chosen size",
              "Exact count for k>=2 with no upper k bound on CPU. Undirected simple projection; "
              "loops, duplicate edges and weights ignored. GPU counts require supported k and a "
              "uint64 count bound. Counts remain complete when memberships are capped.",
              {{"k", parameter("integer", nullptr, true)},
               {"mode", mode},
               {"result_limit", positive(nullptr, true)}},
              {{"groups", port("vertex_groups")}, {"count", port("scalar")}},
              original_mining_backends("k-cliques")),
         k_cliques},
        {card("biconnected-components", "biconnected_components",
              "Find fragile connections and cut vertices",
              "Exact vertex-biconnected edge blocks, bridges and articulation vertices. Undirected "
              "input; loops discarded and parallel edges collapsed. Every normalized edge keeps "
              "its first original ID and all source edge IDs.",
              {},
              {{"groups", port("vertex_groups")},
               {"vertices", port("vertex_set")},
               {"edges", port("edge_set")}},
              {}),
         biconnected},
        {card("k-truss", "k_truss_decomposition", "Find connections supported by triangles",
              "Complete edge truss numbers using the k-2 support convention, plus optional k-truss "
              "selection. Undirected simple projection, weights ignored. First original edge IDs "
              "represent collapsed edges; source IDs are retained.",
              {{"requested_k", parameter("integer", nullptr, false, true)}},
              {{"edges", port("edge_set")}}, gpu),
         truss},
        {card("k-core", "k_core_decomposition", "Find the well-connected core",
              "Exact core numbers and optional selected vertices. Undirected simple projection; "
              "loops, duplicate edges and weights ignored. Isolates have core number zero.",
              {{"requested_k", parameter("integer", nullptr, false, true)}},
              {{"scores", port("vertex_scores")}, {"vertices", port("vertex_set")}}, core_backends),
         core_numbers},
        {card("maximum-independent-set", "maximum_independent_set",
              "Find the largest non-conflicting group",
              "Exact maximum independent set via maximum clique of the complement. Undirected "
              "simple projection; loops, duplicate edges and weights ignored. Complement "
              "construction and search are bounded.",
              {{"mode", choice("exact", {"exact"})}}, {{"vertices", port("vertex_set")}},
              original_mining_backends("maximum-clique")),
         maximum_independent_set},
        {card("minimum-vertex-cover", "minimum_vertex_cover",
              "Cover every connection with as few vertices as possible",
              "Exact minimum vertex cover, or decision against k, from a maximum independent set. "
              "Undirected simple projection; loops, duplicate edges and weights ignored. Native "
              "complement construction and search are bounded.",
              {{"mode", choice("exact", {"exact", "decision"})},
               {"k", parameter("integer", nullptr, false, true)}},
              {{"vertices", port("vertex_set")}}, original_mining_backends("maximum-clique")),
         minimum_vertex_cover}};
    result.push_back({card("dynamic-triangle-counting", "triangle_counting_listing",
                          "Update triangle counts after an edge batch",
                          "Exact deletion-before-insertion batch on an undirected simple graph. "
                          "Reject repeated updates, absent deletions and existing insertions; preserve "
                          "external IDs. EDTC GPU counts are checked against bounded native materialization.",
                          {{"updates", parameter("array", nullptr, true)},
                           {"list_changed_instances", parameter("boolean", false)},
                           {"result_limit", positive(nullptr, true)}},
                          {{"count", port("scalar")}, {"deleted", port("vertex_groups")},
                           {"inserted", port("vertex_groups")}}, {}), dynamic_triangles});
    result.push_back({card("maximal-biclique-counting", "maximal_biclique_enumeration",
                          "Count all maximal bicliques",
                          "Count nonempty maximal bicliques with attributes.side=left|right on every "
                          "vertex. Undirected simple projection. MBE-GPU count is checked against "
                          "bounded native enumeration; no size filtering.", {},
                          {{"count", port("scalar")}}, {}), maximal_biclique_count});
    const auto nested_schemas = json::parse(native_parameter_schemas_json).as_object();
    for (auto& definition : result) {
      auto& metadata = definition.metadata;
      const auto id = string(metadata.at("id"), "operation");
      for (const auto& backend : original_extension_backends(id))
        metadata.at("backends").as_array().push_back(backend);
      auto& parameters = metadata.at("parameters").as_object();
      if (id == "influence-maximization") {
        parameters["solution_quality"] = choice("exact", {"exact", "heuristic"});
        parameters["sample_count"] = positive(256);
        parameters["random_seed"] = parameter("integer", 42);
        metadata["description"] = "Exact native IC/LT optimization, or explicitly requested "
            "SuperFuser independent-cascade heuristic with holdout spread estimation. "
            "The heuristic does not certify optimality or an approximation guarantee.";
        metadata["quality"] = "parameter_dependent";
        metadata["gpu_limitations"] = json::array{"SuperFuser: solution_quality=heuristic, "
            "independent_cascade, explicit probabilities, sample_count a multiple of 32 in [32,65536]"};
      }
      if (id == "personalized-pagerank") {
        parameters["solution_quality"] = choice("numerical", {"numerical", "approximate"});
        parameters["epsilon"] = real(.01, .01, .5);
        parameters["random_seed"] = parameter("integer", 42);
      }
      if (id == "community-detection")
        metadata["gpu_limitations"] = json::array{"Unweighted heuristic modularity; seed=0; "
            "gLeiden resolution=1, parallel backends support positive resolution; no exact or CPM GPU profile"};
      if (id == "quasi-cliques")
        metadata["gpu_limitations"] = json::array{"cuQC: gamma in [0.5,1], minimum_size>=2, "
            "maximal_only=true, no maximum_size; GPU memberships checked by bounded CPU enumeration"};
      if (id == "maximal-bicliques")
        metadata["gpu_limitations"] = json::array{"cuMBE: uncapped materialization; GPU memberships checked by bounded CPU enumeration"};
      if (id == "motif-counting")
        metadata["gpu_limitations"] = json::array{"Connected undirected 3/4-vertex motifs; "
            "graphminer/dumato require induced=true; graphset requires induced=false; "
            "GPU count with bounded CPU materialization"};
      if (id == "subgraph-isomorphism")
        metadata["gpu_limitations"] = json::array{"gMatch: simple undirected non-induced graphs, connected query <=16 vertices, "
            "data <=32767 vertices; no predicates or result_limit; bounded CPU materialization"};
      if (id == "temporal-motifs")
        metadata["gpu_limitations"] = json::array{"Everest/Mayura: ordered A->B, B->C, A->C; "
            "strict integer timestamps and integral duration; no temporal inducedness or predicates; "
            "GPU count with bounded CPU materialization"};
      if (id == "densest-subgraph")
        metadata["gpu_limitations"] = json::array{"CDS: unweighted, minimum_vertices=1; exact objective checked by native CPU"};
      if (id == "group-steiner-tree")
        metadata["gpu_limitations"] = json::array{"GPU4GST: explicit nonnegative integer weights; "
            "at most 16 groups including required singleton vertices; native optimum verification"};
      if (id == "transitive-closure")
        metadata["gpu_limitations"] = json::array{"GDlog: directed, at most 1024 vertices; GPU pairs checked by native reachability"};
      if (nested_schemas.contains(id)) {
        auto& parameters = metadata.at("parameters").as_object();
        for (const auto& schema : nested_schemas.at(id).as_object())
          if (parameters.contains(schema.key()))
            parameters.at(schema.key()).as_object()["json_schema"] = schema.value();
      }
      if (id == "frequent-subgraphs") metadata["input_kind"] = "graph_collection";
      if (id == "graph-learning") metadata["input_kind"] = "graph_collection";
      if (id == "hypergraph-partitioning") metadata["input_kind"] = "hypergraph";
      if (id == "hypergraph-node-learning") metadata["input_kind"] = "hypergraph";
      if (id == "node-embedding" || id == "knowledge-graph-embedding" || id == "node-learning" ||
          id == "graph-learning" || id == "hypergraph-node-learning" || id == "graph-condensation")
        metadata["quality"] = "learned_estimate";
      if (id == "graph-geolocation") metadata["quality"] = "heuristic";
      if (id == "knn-graph") {
        metadata["input_kind"] = "feature_vectors";
        metadata["quality"] = "numerical";
      }
      if (id == "graph-anomalies") metadata["quality"] = "numerical";
      if (id == "graph-coarsening") metadata["quality"] = "parameter_dependent";
      if (id == "spectral-sparsification") metadata["quality"] = "heuristic";
      if (id == "vertex-coloring") {
        metadata["quality"] = "heuristic";
        metadata.at("parameters").as_object().at("distance").as_object()["choices"] =
            json::array{1, 2};
      }
      if (id == "random-walks" || id == "neighborhood-sampling") metadata["quality"] = "stochastic";
      if (id == "random-walks")
        metadata["gpu_limitations"] =
            json::array{"Uniform and weighted models; node2vec uses exact native CPU",
                        "Dense allocation must fit the output budget; positive normalized weights "
                        "must not underflow float64"};
      if (id == "random-walks")
        metadata.at("parameters").as_object().at("length").as_object()["minimum"] = 0;
      if (id == "induced-subgraph") {
        metadata.at("parameters").as_object().at("mode").as_object()["choices"] =
            json::array{"induced", "ego"};
        metadata.at("parameters").as_object().at("radius").as_object()["minimum"] = 0;
        metadata["gpu_limitations"] =
            json::array{"GPU ego discovery; explicit induced selection uses native CPU"};
      }
      if (id == "bipartite-matching")
        metadata.at("parameters").as_object().at("objective").as_object()["choices"] =
            json::array{"maximum_cardinality", "maximum_weight", "minimum_cost"};
      if (id == "max-flow-min-cut")
        metadata["gpu_limitations"] = json::array{
            "ecl-maxflow: nonnegative integral normalized capacities with total <=1e9; no vertex "
            "capacities",
            "At most 1M vertices and 10M input edges; exact residual flow/cut certification"};
      if (id == "bipartite-matching")
        metadata["gpu_limitations"] = json::array{
            "hungarian-cuda: minimum-cost perfect assignment, complete equal sides, at most 64 per "
            "side",
            "Every input cost must be an integer in [0,999]; native C++ verifies the optimum"};
      if (id == "k-cliques") {
        metadata.at("parameters").as_object().at("k").as_object()["minimum"] = 2;
        metadata["gpu_limitations"] = json::array{
            "graphset: k=3..6; gamma: k=3..7; kcgpu: k=3..10; k larger than vertex count returns "
            "zero",
            "A forward-subset count bound must fit uint64"};
      }
      if (id == "maximal-cliques")
        metadata["gpu_limitations"] = json::array{"GPU count plus bounded native materialization",
                                                  "A forward-subset count bound must fit uint64"};
      if (id == "k-truss")
        metadata.at("parameters").as_object().at("requested_k").as_object()["minimum"] = 2;
      if (id == "k-core")
        metadata.at("parameters").as_object().at("requested_k").as_object()["minimum"] = 0;
      if (id == "minimum-vertex-cover")
        metadata.at("parameters").as_object().at("k").as_object()["minimum"] = 0;
      if (id == "community-detection") metadata["quality"] = "parameter_dependent";
      if (id == "seeded-local-community" || id == "force-directed-layout")
        metadata["quality"] = "heuristic";
      if (id == "null-model-significance") metadata["quality"] = "statistical_estimate";
      if (id == "pagerank" || id == "personalized-pagerank" || id == "link-prediction" ||
          id == "simrank" || id == "laplacian-eigenpairs" || id == "graph-signal-denoising")
        metadata["quality"] = "numerical";
      if (id == "single-source-shortest-paths" || id == "many-source-shortest-paths")
        metadata["quality"] = "backend_dependent";
      if (id == "betweenness-centrality") {
        metadata["quality"] = "backend_dependent";
        metadata["gpu_limitations"] =
            json::array{"Unweighted paths only",
                        "Original turbo-bc supports undirected graphs and uses float32 "
                        "accumulation; libcugraph supports either direction",
                        "Shortest-path counts must fit signed int32; larger inputs receive bounded "
                        "CPU admission checks"};
      }
      if (id == "personalized-pagerank")
        metadata["quality"] = "parameter_dependent";
      if (id == "personalized-pagerank")
        metadata["gpu_limitations"] =
            json::array{"Custom uniform dangling redistribution uses the CPU profile",
                        "kPAR: solution_quality=approximate, one seed, restart_probability=0.2, "
                        "unweighted outgoing directed edges, dangling mass to seeds; epsilon is a "
                        "sampling parameter, no certified convergence tolerance; random_seed<=INT32_MAX"};
      if (id == "link-prediction")
        metadata["gpu_limitations"] = json::array{"Only scoring_measure=jaccard"};
      if (id == "single-source-shortest-paths" || id == "many-source-shortest-paths")
        metadata["gpu_limitations"] = json::array{
            "Path cost bounds must fit float64; integral costs beyond 2^53 require CPU"};
    }
    return result;
  }();
  return registry;
}
}  // namespace

json::array operation_cards() {
  json::array output;
  for (const auto& definition : definitions()) output.push_back(definition.metadata);
  return output;
}
const json::object& operation_card(const std::string& operation) {
  for (const auto& definition : definitions())
    if (definition.metadata.at("id").as_string() == operation) return definition.metadata;
  throw Failure("unsupported_operation", "No native runtime integration for " + operation);
}
NativeAlgorithm operation_handler(const std::string& operation) {
  for (const auto& definition : definitions())
    if (definition.metadata.at("id").as_string() == operation && definition.handler)
      return definition.handler;
  throw Failure("unsupported_operation", "No native runtime integration for " + operation);
}
NativeInputAlgorithm input_operation_handler(const std::string& operation) {
  for (const auto& definition : definitions())
    if (definition.metadata.at("id").as_string() == operation && definition.input_handler)
      return definition.input_handler;
  throw Failure("unsupported_operation", "No native structured-input integration for " + operation);
}

json::object catalog() {
  auto result = json::parse(taxonomy_json).as_object();
  const auto cards = operation_cards();
  for (auto& family : result.at("families").as_array()) {
    json::array operations;
    for (const auto& op : cards)
      if (op.as_object().at("family") == family.as_object().at("id"))
        operations.push_back(op.as_object().at("id"));
    family.as_object()["operations"] = operations;
  }
  for (auto& problem : result.at("problems").as_array()) {
    json::array operations;
    for (const auto& op : cards)
      if (op.as_object().at("problem_id") == problem.as_object().at("id"))
        operations.push_back(op.as_object().at("id"));
    problem.as_object()["operations"] = operations;
    problem.as_object()["runtime_integration"] = operations.empty() ? "pending" : "implemented";
  }
  result["operations"] = cards;
  result["abi_version"] = 1;
  result["implementation_sha256"] = implementation_sha256;
  result["python_runtime_required"] = false;
  result["file_readers"] = json::array{
      json::object{{"id", "libcudf-csv"}, {"compiled", cudf_compiled()}, {"device", "gpu"}}};
  result["table_projection"] =
      json::object{{"command", "project_graph"},
                   {"profile", "native-table-projection-v1"},
                   {"inline_tables", true},
                   {"csv_files", cudf_compiled()},
                   {"joins", "explicit many-to-one; required, inner or left"},
                   {"duplicates", json::array{"preserve", "reject", "sum", "min", "max", "count"}},
                   {"time_window", "integer timestamp; start inclusive, end exclusive"},
                   {"python_runtime_required", false}};
  return result;
}
}  // namespace graphmine::runtime
