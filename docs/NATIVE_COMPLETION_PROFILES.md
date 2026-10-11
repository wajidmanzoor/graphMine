# Native completion profiles

The shared C++ runtime now implements 80 operations covering all 70 formal
problem contracts and seven record-query utilities. These are explicit mathematical
profiles, not claims that every method or architecture in the literature is
implemented. All operations have native CPU support; 23 have an admitted GPU
profile. GPU-only requests for other operations fail explicitly.

The authoritative parameter schemas, descriptions, output ports and quality
claims come from `graphmine-native catalog`. The Python package and application
read that same catalog. The executable evidence gate is
[`catalog/native_execution_evidence.json`](../catalog/native_execution_evidence.json);
the complete per-contract mapping is
[`catalog/native_runtime_coverage.json`](../catalog/native_runtime_coverage.json).

## Profiles added after the 26-problem checkpoint

### `node-lookup`

**Family:** `query`. **Input:** `graph`. **Quality:** `exact`.

Native deterministic selection of original vertex records by typed IDs and AND field predicates. Explicit empty vertex lists select nothing. Missing fields match only exists=false; unknown field paths fail. Counts remain complete when row collections are capped.

### `edge-filter`

**Family:** `query`. **Input:** `graph`. **Quality:** `exact`.

Native deterministic original-edge selection without collapsing loops or parallel events. Edge and source/target predicates use stored endpoints even for undirected input. Typed IDs, exact decimal scalar comparisons and explicit incomplete capped ports.

### `neighbors`

**Family:** `query`. **Input:** `graph`. **Quality:** `exact`.

Native filtered hop reachability with exact distances. Directed out/in/both traversal; undirected edges traverse both ways. Parallel records do not duplicate vertices; include_seed controls the root. Original input vertex ordering and explicit collection completeness.

### `common-neighbors`

**Family:** `query`. **Input:** `graph`. **Quality:** `exact`.

Native intersection of direct filtered neighbor sets, preserving the declared direction and self-loop adjacency meaning. Typed entity IDs; stable original vertex order. Complete count with explicitly capped collections.

### `query-paths`

**Family:** `query`. **Input:** `graph`. **Quality:** `exact`.

Native iterative enumeration of all hop-shortest or all vertex-simple paths within max_hops. Filtered directed out/in/both traversal with parallel edge identities preserved. Source equal to target has one zero-edge path. Counts are exhaustive; capped path and membership ports are incomplete.

### `graph-aggregate`

**Family:** `query`. **Input:** `graph`. **Quality:** `exact`.

Native count, sum, average, minimum or maximum of an explicit field, grouped by a scalar field or vertex. Exact decimal rational arithmetic is authoritative; display values disclose rounding. Per-vertex edge groups include isolates and count loops once. Missing numeric/group fields fail. Stable exact-value sorting and completeness-aware result limits.

### `query-subgraph`

**Family:** `query`. **Input:** `graph`. **Quality:** `exact`.

Native vertex-induced, edge-induced or filtered-neighborhood extraction. Preserve typed IDs, original attributes, direction, weights, loop and parallel records. Edge mode retains endpoints; vertex mode retains selected isolates. Derived graph identity carries source content lineage.

### `node-embedding`

**Family:** `embeddings`. **Input:** `graph`. **Quality:** `learned_estimate`.

Native second-order LINE or DeepWalk/node2vec fixed-window contexts, optimized with full-softmax cross entropy and declared L2 regularization. Weighted outgoing transitions preserve direction unless projection is requested. Explicit loop handling and summed parallel weights; every vertex receives source and context vectors. Report actual context masses, objective, gradient norm, seed and stopping reason; no global optimum or unique embedding claim.

### `knowledge-graph-embedding`

**Family:** `embeddings`. **Input:** `graph`. **Quality:** `learned_estimate`.

Native DistMult with mean logistic loss over declared training positives and fixed sampled corruptions, plus L2 regularization. Relations come only from the training split; duplicate triples collapse, distinct relation identities and self triples remain. Validation never affects fitting. Report entity/relation parameters, training examples and filtered head/tail ranking metrics with average ties; no unseen-relation inference.

### `node-learning`

**Family:** `learning`. **Input:** `graph`. **Quality:** `learned_estimate`.

Native simplified graph convolution: declared mean-message layers, then a trained linear softmax or scalar regression readout. Numeric vertex_features and training_labels use objects containing typed {vertex,value} rows. Disjoint train/validation/test IDs; preprocessing and loss use training labels only. Transductive unlabeled features/topology are explicit. Saved coefficients, split metrics, objective and convergence status; one self message, collapsed parallels, weights ignored.

### `graph-learning`

**Family:** `learning`. **Input:** `graph_collection`. **Quality:** `learned_estimate`.

Native independent per-graph mean message passing, sum/mean pooling, and trained linear softmax or scalar regression readout. Structural [one,in-degree,out-degree] or declared attribute features; empty graphs pool to zeros. graph_labels uses typed {graph,value} rows. Train-only fitted preprocessing and supervised loss, disjoint graph splits and saved model state. Weights ignored; no cross-graph edges.

### `hypergraph-node-learning`

**Family:** `learning`. **Input:** `hypergraph`. **Quality:** `learned_estimate`.

Native hgnn-linear-v1: weighted hyperedge feature means followed by normalized vertex incidence means and a trained linear softmax/regression layer. No pairwise projection. Isolates retain features, singleton edges remain. Feature, target and split attributes are explicit; only train labels fit parameters or preprocessing. Record model state, finite predictions and metrics with split denominators. Optional model_parameters declare layers and optimizer settings.

### `graph-geolocation`

**Family:** `learning`. **Input:** `graph`. **Quality:** `heuristic`.

Native spatial propagation by sequential discrete geodesic median coordinate descent. Minimize positive edge weight times spherical distance, restricting coordinates to seed locations in each connected component. Undirected nonnegative input, reject loops, sum parallels. Fixed seeds remain exact; seedless components remain unresolved. Haversine handles the antimeridian; report dispersion, stopping status and optional held-out geodesic errors. No supervised model or calibrated confidence claim.

### `graph-condensation`

**Family:** `learning`. **Input:** `graph`. **Quality:** `learned_estimate`.

Native gradient_matching_linear_sgc_v1 matches training softmax gradients at zero readout parameters. Learn synthetic features and fix class-balanced labels on declared edgeless adjacency; this is not graph coarsening. Original weighted SGC features use summed parallel weights plus self messages; reject original loops. Budget must cover training classes and not exceed training vertices. Train labels only, explicit transductive features/topology, new synthetic IDs. Evaluate full versus synthetic training on held-out original labels over declared seeds; report objective and utility variance.

### `graph-anomalies`

**Family:** `statistics`. **Input:** `graph`. **Quality:** `numerical`.

Native structural and numeric features for vertices, original edge instances or supplied induced subgraphs. Population or explicit location/scale reference; weighted standardized L1, L2 or maximum deviation with declared minimum scale. Recompute scores, preserve zero-variance failures and disclose top-k truncation. Numerical deviation scores are not learned ground truth.

### `entity-resolution`

**Family:** `data_preparation`. **Input:** `graph`. **Quality:** `exact`.

Complete native disjunctive blocking rules with equality, Unicode tokens, codepoint Levenshtein or exact numeric difference. ICU NFKC and full case folding; optional missing fields fail the predicate. Input edges are unused hints. Connected-components resolution or exact bounded minimum candidate-pair disagreement partitions; neutral noncandidates and no cross-component clusters.

### `graph-edit-distance`

**Family:** `comparison`. **Input:** `graph`. **Quality:** `exact`.

Exact bounded native partial correspondences over simple normalized directed or undirected graphs. Selected categorical vertex/edge labels; decimal rational costs. Vertex label replacement costs insertion plus deletion, edge substitution competes with deletion plus insertion. Returns normalized graphs and an ordered stable-handle script whose total is checked against the optimum. Weights and timestamps are ignored.

### `maximum-common-subgraph`

**Family:** `comparison`. **Input:** `graph`. **Quality:** `exact`.

Exact bounded native induced matching, or label-compatible maximum vertex matching for non-induced output where isolated vertices are allowed. Preserve direction and selected categorical labels, ignore weights/timestamps. Returns a checked common graph and injective correspondence. No secondary maximum-edge objective. Explicit loop/parallel normalization.

### `graph-coarsening`

**Family:** `construction`. **Input:** `graph`. **Quality:** `parameter_dependent`.

Supplied integer partition or native greedy maximal matching; all vertices remain represented. Undirected nonnegative input, reject loops. Sum original parallel edge weights once, retain or drop intra-cluster edges, sum or mean feature vectors. Exact rational aggregates are reported separately from rounded binary64 graph values. Greedy partition has no optimality claim.

### `spectral-sparsification`

**Family:** `construction`. **Input:** `graph`. **Quality:** `heuristic`.

Native effective-resistance sampling with replacement, exact rational draw normalization and importance reweighting. LAPACK grounded solves and all generalized eigenvalues measure numerical distortion; requested epsilon must pass. Explicit weighted undirected simple input, no loops/parallels. Preserve original IDs/attributes. Identity shortcut when budget covers positive edges, zero-weight edges removed. No probabilistic approximation guarantee is claimed.

### `frequent-subgraphs`

**Family:** `pattern_mining`. **Input:** `graph_collection`. **Quality:** `exact`.

Exact bounded native enumeration of simple labeled directed or undirected patterns, including disconnected and isolated vertices. Support counts transactions once. Native lexicographic canonicalization has its own stable pattern IDs. Positive support fraction uses exact decimal comparison. Explicit loop and parallel policies; no Python runtime.

### `single-graph-frequent-subgraphs`

**Family:** `pattern_mining`. **Input:** `graph`. **Quality:** `exact`.

Exact connected undirected patterns including single vertices. Minimum-image support is the smallest host image-set size over all injective embeddings. Every vertex needs the selected label or type. Reject loops; explicit parallel collapse. Native canonical IDs, bounded enumeration and complete counts; count mode does not materialize patterns.

### `temporal-motifs`

**Family:** `pattern_mining`. **Input:** `graph`. **Quality:** `exact`.

Exact native structural matching and injective event assignments. Rational UTC timestamps, acyclic partial order, inclusive duration limit, optional temporal inducedness and typed predicates. Event tuples in query-edge input order identify occurrences. Counts and vertex participation remain complete when instance lists are capped.

### `knn-graph`

**Family:** `construction`. **Input:** `feature_vectors`. **Quality:** `numerical`.

Native exhaustive pairwise Euclidean, squared Euclidean or cosine distances with self-exclusion and input-order tie breaking. Directed, union or mutual symmetrization. Cosine rejects zero vectors. Exact neighbor search under numerical distances even when approximate is requested; preserves typed vector IDs.

### `hypergraph-partitioning`

**Family:** `partitioning`. **Input:** `hypergraph`. **Quality:** `exact`.

Exact native enumeration of nonempty parts, optimizing weighted cut-net or connectivity-minus-one without graph projection. Exact rational vertex and hyperedge weights, decimal imbalance tolerance and upper part-weight bound. Certified infeasibility when no partition qualifies; exponential search obeys work budgets.

### `subgraph-isomorphism`

**Family:** `pattern_mining`. **Input:** `graph`. **Quality:** `exact`.

Exact native induced or non-induced injective matching, preserving direction, loops and parallel multiplicities. Declarative typed vertex and edge predicates; distinct query edges must match distinct data edges. Capped mapping collections are explicitly incomplete.

### `motif-counting`

**Family:** `pattern_mining`. **Input:** `graph`. **Quality:** `exact`.

Exact structural embeddings with explicit occurrence identity: all mappings or unique vertex-set and image-edge classes. Preserve direction; simple projections discard loops, duplicate edges and weights. Non-induced motifs on the same vertex set can be distinct instances. Counts remain complete when lists are capped.

### `graphlet-counting`

**Family:** `pattern_mining`. **Input:** `graph`. **Quality:** `exact`.

Native isomorphism classification against the complete connected undirected graph atlas for sizes two through seven. Static atlas IDs and exact automorphism orbits are embedded; Python is not required. Discard loops and duplicate edges, ignore weights. Counts and optional orbit participation stay complete when memberships are capped.

### `group-steiner-tree`

**Family:** `optimization`. **Input:** `graph`. **Quality:** `exact`.

Exact bounded vertex-subset optimization with a minimum spanning tree for each feasible induced subgraph. Covers every group and required vertex, allowing overlapping representatives. Undirected nonnegative weighted input, loops removed, cheapest original parallel edge retained. Reports exact rational cost or certified infeasibility.

### `network-alignment`

**Family:** `comparison`. **Input:** `graph`. **Quality:** `exact`.

Exact bounded global injective assignment covering every vertex of the smaller graph. Maximize topology_weight times conserved edge value plus pair priors. Direction must match. Drop loops and collapse unweighted or sum nonnegative weighted parallel edges. Weighted conservation is the minimum of paired normalized edge weights.

### `influence-maximization`

**Family:** `centrality`. **Input:** `graph`. **Quality:** `exact`.

Exact rational live-edge and seed-set enumeration for independent cascade or random-threshold LT. Fixed LT thresholds use progressive activation, including spontaneous activation at zero. Directed input, explicit probabilities, loops removed. Parallel IC probabilities combine by independent failure; LT weights sum with incoming mass at most one. Exponential work is bounded; no sampling claims.

### `null-model-significance`

**Family:** `statistics`. **Input:** `graph`. **Quality:** `statistical_estimate`.

Uniform G(n,m), or uniform stub pairing conditioned on simplicity and exact degree invariants. Dense fixed-degree graphs use complement sampling. Preserve direction, discard loops and collapse duplicates. Statistics: triangles, directed triangles, k-cliques, density or a supplied-partition modularity. Report every sample, population standard deviation and declared empirical tail; no hidden pseudocount.

### `persistent-homology`

**Family:** `topology`. **Input:** `graph`. **Quality:** `exact`.

Exact sparse boundary reduction of a flag complex over a declared prime field. Vertices start at zero; include cofaces needed to compute deaths in requested dimensions. Undirected input; reject loops, require nonnegative weights, keep minimum parallel filtration. Optional cutoff marks unpaired intervals right-censored.

### `seeded-local-community`

**Family:** `communities`. **Input:** `graph`. **Quality:** `heuristic`.

Heuristic personalized-PageRank degree-normalized sweep with required seeds first. Returns the lowest defined weighted conductance among feasible prefixes. Exact cut/volume recomputation, no global-optimum claim. Undirected input; reject loops, sum nonnegative parallel weights. If all conductance denominators vanish, return the seeds.

### `force-directed-layout`

**Family:** `layout`. **Input:** `graph`. **Quality:** `heuristic`.

Native Fruchterman-Reingold iterations in two or three dimensions. Explicit 0.01 distance regularization, linear cooling from one tenth of the maximum coordinate span, no final rescaling. Recompute matching potential and uncooled force residual; no drawing optimality claim. Project direction, drop loops, collapse unweighted or sum weighted parallels.

### `laplacian-eigenpairs`

**Family:** `spectral`. **Input:** `graph`. **Quality:** `numerical`.

Native LAPACK symmetric eigensolver with independently recomputed absolute residual and orthogonality checks. Combinatorial or symmetric-normalized Laplacian, including isolates. Undirected input; reject loops and negative weights, sum parallel weights. Dense solver uses work budgets; no iteration parameter.

### `graph-signal-denoising`

**Family:** `spectral`. **Input:** `graph`. **Quality:** `numerical`.

Minimize half squared signal error plus Laplacian quadratic, weighted total variation, or explicit graph-trend penalty. Native positive-definite solve or accelerated feasible-dual optimization; tolerance bounds objective gap, with a separate L2 solution-error bound. Undirected input, no loops, nonnegative summed parallel weights.

### `simrank`

**Family:** `similarity`. **Input:** `graph`. **Quality:** `numerical`.

Native float64 SimRank fixed-point iteration with a recomputed contraction error bound. Incoming or undirected-projection neighborhoods; drop loops and duplicates, ignore weights. Single-source output excludes itself. Top-k ports explicitly disclose omitted pairs.

### `widest-paths`

**Family:** `traversal`. **Input:** `graph`. **Quality:** `exact`.

Exact max-min capacities with a predecessor witness, preserving direction. Every edge needs nonnegative capacity; loops discarded and largest parallel capacity wins. Zero is reachable. Source infinity and unreachable nulls have distinct flags.

### `top-k-critical-paths`

**Family:** `traversal`. **Input:** `graph`. **Quality:** `exact`.

Exact rational k-best DAG paths, retaining parallel edge identities and negative weights. Omitted sources and sinks select zero-in/out-degree vertices. A zero-edge path is included when a source is also a sink. Finishing top-k does not imply the path collection is exhaustive.

### `temporal-paths`

**Family:** `temporal`. **Input:** `graph`. **Quality:** `exact`.

Exact rational time-expanded shortest paths. Directed event input; every edge needs a timestamp and nonnegative duration attribute. Waiting is allowed. Fastest duration excludes waiting before initial departure. Inclusive ready time and deadline preserve distinct parallel events.

### `bounded-paths-cycles`

**Family:** `traversal`. **Input:** `graph`. **Quality:** `exact`.

Exact directed simple edge paths and cycles up to max_hops. Drop loops; collapse to first parallel edge or retain identities. Optional strict chronological order applies after canonical cycle rotation. A result cap retains the shortest sequences while the total count remains exhaustive.

### `community-detection`

**Family:** `communities`. **Input:** `graph`. **Quality:** `parameter_dependent`.

Undirected modularity or constant Potts objective. Exact mode enumerates partitions with rational objectives; heuristic mode uses seeded positive-gain vertex moves and makes no global-optimum claim. Drop loops and collapse unweighted or sum weighted parallel edges. CPM is internal edge weight minus resolution times within-part vertex pairs.

### `balanced-partitioning`

**Family:** `partitioning`. **Input:** `graph`. **Quality:** `exact`.

Exact bounded partition search with nonempty parts and both lower and upper balance limits. Undirected input, nonnegative edge weights, loop removal and duplicate collapse or weighted sum. Normalized cut sums each part boundary divided by its declared balance size. Decimal-rational imbalance tolerance; exact objective and infeasibility certificates.

### `signed-balance`

**Family:** `partitioning`. **Input:** `graph`. **Quality:** `exact`.

Exact signed parity balance test and bounded rational frustration minimization. Every edge type is positive or negative. Undirected input; drop loops, reject contradictory parallel signs and collapse unweighted or sum weighted parallels. Zero-cost violations still make the network structurally unbalanced.

### `densest-subgraph`

**Family:** `dense_structures`. **Input:** `graph`. **Quality:** `exact`.

Exact induced k-clique count divided by vertex count. Weighted density is defined for clique_order=2, summing parallel weights. Undirected input; loops discarded. Native rational maximum-weight closure for minimum_vertices=1; bounded exhaustive cardinality search otherwise.

### `densest-k-subgraph`

**Family:** `dense_structures`. **Input:** `graph`. **Quality:** `exact`.

Exact bounded cardinality search. Sum parallel nonnegative weights, discard loops, require undirected input. An approximate request receives the stronger exact result when search completes.

### `quasi-cliques`

**Family:** `dense_structures`. **Input:** `graph`. **Quality:** `exact`.

Exact gamma quasi-cliques on an undirected simple projection. Thresholds use decimal-rational gamma; maximality is relative to all qualifying sets within the size bounds. Search is bounded by work and output budgets.

### `maximal-bicliques`

**Family:** `dense_structures`. **Input:** `graph`. **Quality:** `exact`.

Exact inclusion-maximal bicliques with nonempty sides. Explicit disjoint partitions must cover every vertex. Undirected input; loops discarded and duplicate edges collapsed. Capped memberships are marked incomplete.

### `butterfly-counting`

**Family:** `pattern_mining`. **Input:** `graph`. **Quality:** `exact`.

Exact 2-by-2 biclique counts, participation and alpha/beta cores. Every vertex requires attributes.side=left|right. Reject directed input, loops and same-side edges; collapse duplicates. Core thresholds explicitly use degree or butterfly participation.

### `transitive-closure`

**Family:** `traversal`. **Input:** `graph`. **Quality:** `exact`.

Exact reflexive reachability: every vertex reaches itself by a zero-length path. Preserve graph direction, ignore weights, loops and duplicates. Count-only closure has a complete scalar and incomplete pair-list port.

### `overlapping-communities`

**Family:** `community`. **Input:** `graph`. **Quality:** `exact`.

Exact k-clique percolation. Undirected simple projection; discard loops and duplicates. Communities can overlap. Unassigned vertices are outside all percolation communities before minimum-size display filtering.

## Numerical and scaling boundaries

Exact combinatorial profiles enumerate or optimize the declared finite search
space. Candidate, output, time and memory budgets reject excess work or mark
incomplete output; an unfinished search is not certified as an optimum. These
profiles are primarily correctness baselines for small or bounded inputs.

Spectral methods use native LAPACK. Numerical certificates report residuals and
tolerances; they are not symbolic proofs. Iterative embeddings, learning and
layout methods report their actual finite iteration profile, objective and
seed. SGC, pooled graph convolution, hypergraph convolution, LINE, DeepWalk,
node2vec, DistMult, graph condensation and geolocation are the specific native
architectures described above. They do not stand for arbitrary neural models,
paper-reported benchmark accuracy, or automatic model selection.

Original signed 64-bit and string IDs remain distinct throughout. Exact
rational outputs use decimal numerator/denominator strings. Graph algorithm
weights use binary64; integer weights requiring rounding beyond its exact
integer range are rejected. Query aggregation separately preserves native JSON
integer values and computes exact rational statistics over the admitted values.
Unicode entity resolution uses ICU normalization/case folding with the linked
ICU version recorded in dependency evidence.

## Validation

The completion suites call the C ABI directly with GPUs hidden. Independent
checks include exhaustive subsets and mappings, integer/rational arithmetic,
SQL joins, explicit live-edge probabilities, persistence boundary ranks,
finite-difference learning gradients, replayable edit scripts, and numerical
residuals. Passing a finite suite establishes the tested profiles and boundaries;
it does not prove arbitrary large inputs or model generalization.

Final native reports are under [`validation/native_final`](../validation/native_final).
The historical Python algorithms remain available only through
`graphmine.reference` for migration comparisons and test oracles. The default
`graphmine.run`, workflows and application use the native runtime.
