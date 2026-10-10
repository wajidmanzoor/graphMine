# CPU reference profiles

These executable profiles are part of `python/graphmine` and are connected to
the default browser workspace through evidence-checked typed workflows. See
`TYPED_ANALYTICS_WORKFLOWS.md` for modes, device policy and result views. The
retained `/classic` native workspace still uses its earlier execution path;
native adaptation remains tracked in `VERIFIED_ANALYTICS_IMPLEMENTATION.md`.

## Objectives and implementations

| Operation | Implemented objective and method | Limits and result interpretation |
|---|---|---|
| `densest-subgraph` | Maximize induced k-clique count divided by selected vertex count. Weighted k=2 uses induced weight instead. Maximum-weight closure reduces the unconstrained problem to NetworkX minimum cut with exact integer capacities. | No fixed maximum clique order. Higher-order weighted density is undefined and rejected. `minimum_vertices > 1` uses separate HiGHS models by result cardinality and returns a numerical optimality certificate. |
| `densest-k-subgraph` | Select exactly k vertices maximizing induced edge count or nonnegative edge weight using binary vertex/edge variables in SciPy/HiGHS. | k must be between 1 and the vertex count. This is an NP-hard optimization, so the work/time budget can prevent completion. |
| `quasi-cliques` | Enumerate all vertex sets meeting `ceil(gamma * (size-1))` internal degree. HiGHS enumerates fixed-size feasible sets with exclusion constraints. | The threshold uses the decimal representation of gamma, avoiding binary multiplication/ceiling artifacts. Maximality is within the declared size bounds and tests all larger qualifying sets, not only one-vertex extensions. |
| `maximal-bicliques` | Complete each declared bipartition internally, enumerate NetworkX maximal cliques, then retain the pairs with both sides nonempty. | Partitions must be disjoint and cover all vertices, including isolates. A result limit caps listing and changes the membership port's completeness. |
| `butterfly-counting` | Exact common-neighbor enumeration of 2-by-2 bicliques; global, per-vertex and per-edge participation; threshold peeling for the explicitly selected core measure. | `core_measure=degree` is conventional (alpha,beta)-core peeling. `butterfly_participation` is the collection's original variant. They are different objectives. |
| `bipartite-matching` | NetworkX maximum-weight matching, with negated scores for minimum cost and an explicit cardinality requirement when full smaller-side coverage is requested. | Without required coverage, minimum cost is permitted to select the empty matching. An infeasible coverage request returns `feasible=false` and an infeasibility certificate, not a partial matching presented as a solution. |
| `subgraph-isomorphism` | NetworkX VF2 induced isomorphisms or non-induced monomorphisms. Attribute-constrained parallel edges use an injective bipartite matching inside the VF2 predicate. | Preserves loops, direction and parallel-edge identity. Distinct query-to-data mappings remain distinct. Result limits mark incomplete enumeration. |
| `motif-counting` | VF2 embeddings, optionally divided into automorphism classes using the mapped vertices and mapped motif edges. | A three-vertex path has three non-induced occurrence classes in a triangle, or six embeddings. A vertex-set-only deduplication would be wrong. Counts remain exhaustive when instance lists are capped. |
| `graphlet-counting` | Classify connected induced vertex subsets against the NetworkX atlas. Compute exact vertex orbits from pattern automorphisms. | Supports sizes 2 through 7 because that is the atlas's complete range. Larger sizes require another class dictionary/generator. Orbit identifiers include their structural definitions. |
| `community-detection` | NetworkX Louvain for heuristic modularity; binary same-community variables with transitivity constraints for globally optimized modularity or CPM. | CPM here is the sum of internal edge weights minus resolution times the number of internal unordered vertex pairs. A heuristic request may receive a stronger, completed exact-method result. Louvain does not claim global optimality. Edgeless modularity is defined as zero. |
| `balanced-partitioning` | HiGHS assignment model for edge cut; set-partitioning model for size-normalized cut. Enforces nonempty parts plus both lower and upper balance limits. | Normalized cut means the sum of each part's boundary cost divided by its declared balance size. It does not silently switch to degree-volume normalization. Zero-sized weighted parts are inadmissible for that objective. Infeasible balance is reported explicitly. |
| `signed-balance` | Exact parity propagation decides structural balance. Binary XOR constraints minimize weighted frustration when requested. | Structural balance depends on signs even when costs are zero. `optimal=true` for `balance_check` certifies the decision; `frustration_optimal` separately indicates whether the returned assignment minimizes frustration. |

All profiles reject unknown parameters. Directed projections are explicit where
an undirected objective is required. For ordinary unweighted structure, parallel
edges collapse; weighted density and partitioning sum parallel weights. Matching
retains the original ID of the edge with the best applicable objective value.

### Numerical, construction and topology profiles

| Operation | Implemented objective and method | Limits and result interpretation |
|---|---|---|
| `laplacian-eigenpairs` | SciPy `eigh` for selected smallest/largest combinatorial or symmetric-normalized eigenpairs, including isolates. Recompute every residual and orthogonality error. | `num_eigenpairs` may equal the vertex count. The direct solver has no iteration-limit parameter; `max_iterations` is rejected rather than ignored. Dense workspace is charged to the work budget. |
| `graph-signal-denoising` | SciPy linear solve for quadratic smoothing; CVXPY/CLARABEL for total variation and graph trend filtering. | Objective is half squared observation error plus the declared penalty. `tolerance` bounds objective suboptimality, not coordinate error. The result reports an L2 solution-error bound separately. Signal values may be scalars or equal-width vectors. |
| `knn-graph` | Exhaustive SciPy distances on a `FeatureVectors` input, followed by explicit self-exclusion and directed/union/mutual symmetrization. | Supports Euclidean, squared Euclidean and cosine distance. Zero vectors are rejected for cosine. Exact means exhaustive float64 search; no approximate index or random seed is used. An approximate request may receive this stronger exact-search result. |
| `graph-coarsening` | A supplied vertex partition or NetworkX maximal matching, followed by exact aggregation of fine edges and declared numeric features. | Each undirected fine edge contributes once, including to a quotient self-loop when requested. Deterministic matching has no seed parameter. Vertices with supplied features use `attributes.features`; partial or mismatched feature arrays are rejected. |
| `hypergraph-partitioning` | SciPy binary assignment and hyperedge-part incidence models for cut-net or connectivity-minus-one cost. | Accepts a `Hypergraph`, not a graph projection. Parts are nonempty and meet the contract's upper weight limit. Balance bounds are rounded inward on the exact rational input-weight grid. Impossible requests return an infeasibility result. |
| `simrank` | SciPy GMRES solves the full SimRank fixed-point equations. Recompute maximum residual and divide by `1-decay_factor` for an absolute error bound. | NetworkX's internal relative stopping tolerance could fail a tighter absolute request, so this profile uses the explicit equation solve. `max_iterations` counts inner GMRES iterations. Single-source results exclude the source itself; a same-vertex single-pair query returns one. |
| `widest-paths` | Descending capacity thresholds and NetworkX reachability produce max-min capacities with a witness predecessor tree. | Preserves direction and exact integer capacity comparisons. Zero capacity is reachable. Source infinity and unreachable values both serialize as null but have distinct `reachable` and `is_source` flags. |
| `top-k-critical-paths` | Expand parallel edges into unique edge nodes, negate costs, perform exact rational Johnson reweighting, then use NetworkX's shortest-simple-path iterator. | Requires a DAG. Handles negative and large integer weights without changing path ranking. Zero-edge paths are included when a source is also a sink. A completed top-k request is distinct from a port containing all paths. |
| `persistent-homology` | GUDHI flag-complex expansion and persistence, with every original vertex inserted at filtration zero. | Computes enough cofaces to determine deaths in the requested dimensions and retains essential H0 intervals. Fields must be prime and at most GUDHI's documented limit of 46337. Cutoffs explicitly distinguish right-censored from complete-filtration essential intervals. |

For quadratic denoising the penalty is
`strength / 2 * trace(X.T @ L @ X)`. Total variation uses
`strength * sum(abs(diag(edge_weight) @ B @ X))`, with oriented unweighted
incidence `B`. For trend order `k`, let `Bw = diag(sqrt(edge_weight)) @ B`
and `L = Bw.T @ Bw`; the difference operator is `Bw @ L^(k/2)` for even
`k` and `L^((k+1)/2)` for odd `k`. The penalty is `strength * ||D X||_1`.
These explicit weighted conventions avoid substituting a different regularizer.

For the nonsmooth objectives, the wrapper obtains a feasible dual vector,
recomputes primal and dual objectives, and verifies the gap. Strong convexity
gives `||X-X_opt||_F <= sqrt(2 * gap)`. Quadratic smoothing uses its stationarity
residual and the system's minimum eigenvalue bound of one for the same purpose.
All these are floating-point certificates with their arithmetic disclosed.

### Sampling, temporal and local analysis profiles

| Operation | Implemented objective and method | Limits and result interpretation |
|---|---|---|
| `random-walks` | NumPy PCG64 draws uniform, weighted or second-order node2vec transitions. | Uniform walks collapse parallel edges; weighted walks sum them. Self-loops remain. Directed walks follow outgoing edges; the declared directed node2vec extension uses the previous-to-candidate arc for the distance-one bias. A zero outgoing weight sum ends the walk. Nondefault p/q are rejected for other models. |
| `neighborhood-sampling` | NumPy draws outgoing edge instances independently per distinct frontier vertex, hop and seed batch. | Preserves edge IDs and parallel instances. Typed overrides need one fanout per hop; unspecified types use the global fanout. `-1` returns all eligible edges, including zero-weight edges. Positive weighted fanouts sample only positive weights. Optional time cutoffs require valid UTC timestamps. |
| `temporal-paths` | NetworkX shortest paths on an exact-rational time-expanded graph. | Supports earliest arrival and fastest duration, with waiting between events. Fastest duration excludes waiting before initial departure. Every event requires a nonnegative traversal duration. Results contain witnesses and retain unreachable vertices. |
| `bounded-paths-cycles` | NetworkX simple edge-path and bounded-cycle generators, with edge-identity expansion for preserved parallels. | Directed input; self-loops drop. Parallel edges collapse to the first input edge unless explicitly preserved. Cycles through a vertex start there; other chronological cycles start at their earliest event. A cap retains shortest results and marks the collection incomplete while the total count remains exhaustive. |
| `temporal-motifs` | NetworkX VF2 vertex mappings, injective event assignments, and exact temporal constraints. | A temporal motif declares a canonical graph and optional precedence pairs. Omitted order means total input-edge order; an empty order array means no precedence constraints. Occurrence identity is the tuple of event IDs in motif-edge order, including for partial orders. Inducedness excludes any additional participating-vertex event in the closed occurrence window. |
| `null-model-significance` | NetworkX uniform G(n,m), or configuration-model rejection sampling conditioned on simplicity and fixed degrees. | Each sample is checked for all declared invariants. Dense fixed-degree graphs use the complement to improve acceptance. The attempt budget can fail explicitly; no unverified mixing claim or degree-changing repair is used. Returns samples, population standard deviation, and an explicitly chosen empirical tail probability. |
| `seeded-local-community` | Checked NetworkX personalized PageRank followed by a degree-normalized sweep with required seeds first. | Returns the best defined conductance among feasible sweep prefixes under the weighted volume bound. This is a heuristic with `optimal=false`; global-exact requests are rejected. Self-loops are rejected; parallel weights sum. If every feasible prefix has zero conductance denominator, returns the seeds with null conductance. |

Sampling records the actual seed even when the request omitted it. Reusing that
seed, input order and package versions reproduces the realization. Floating
probabilities are disclosed; stochastic realizations are not deterministic
optima. A complete random sample means the requested sampling task finished,
not that all possible walks or neighborhoods were enumerated.
Probability normalization uses rational ratios before conversion to float64;
positive probabilities that would underflow to zero are rejected explicitly.
Temporal path objectives also retain `value_fraction` so their exact rational
values are available alongside rounded JSON numeric displays.

For a fixed labeled degree sequence, every simple graph has the same number
of stub-pairing representations. Rejecting entire nonsimple configuration
samples therefore preserves uniformity over simple realizations. Directed
sampling uses separate in/out stubs. Complementation is a bijection between
the original and complementary fixed-degree ensembles. This does not imply
efficient rejection on arbitrary degree sequences; the attempt/work budgets
remain necessary. The empirical p-value is the declared extreme-sample count
divided by sample count, without a hidden pseudocount. Zero null variance
produces a null z-score.

### Comparison, connection and record-analysis profiles

| Operation | Implemented objective and method | Limits and result interpretation |
|---|---|---|
| `group-steiner-tree` | SciPy/HiGHS selects vertices, edges and a root, enforces group coverage and tree edge count, then separates valid connectivity cuts until the selected graph is connected. | Returns a validated tree and a representative from every group, or explicit infeasibility. Overlapping groups may share representatives. Keeps the cheapest original parallel edge ID and removes loops. Requires nonnegative weights. Completed solver optimality is numerical, not a formal rational certificate. |
| `network-alignment` | SciPy/HiGHS linearizes injective vertex assignment and conserved-edge terms. Every vertex in the smaller graph must be mapped. | Supports global one-to-one alignment; local many-to-one and `top_k` are not accepted. Prior rows preserve both graphs' typed IDs. Weighted conservation sums parallel weights and takes the minimum normalized weight of the conserved edge pair; unweighted conservation counts edges. Weights are nonnegative. |
| `entity-resolution` | RapidFuzz unit-cost Levenshtein plus declared equality, shared-token and numeric-distance predicates; NetworkX connected components or a SciPy/HiGHS correlation-clustering model. | Blocking rules are a disjunction of predicate conjunctions. Missing required attributes are errors; an optional missing field makes its predicate false. Correlation clustering minimizes unit disagreements on candidate pairs; noncandidate pairs are neutral and clusters remain within candidate-graph components. Connected-component resolution may transitively merge a pair that its direct match rule rejects. |
| `graph-anomalies` | NetworkX feature extraction and SciPy reference statistics, followed by declared standardized L1, L2 or maximum-absolute scoring. | Supports vertices, original edge instances and explicitly listed induced subgraphs. Candidate selection does not alter the reference population. Scores measure deviation from that reference, not ground-truth anomaly labels. A top-k ranking port is incomplete when other scored entities are omitted. |

Alignment maximizes
`topology_weight * sum(conserved_edge_values) + sum(selected_pair_priors)`.
The per-pair score allocates half each incident conserved-edge contribution to
each endpoint, so pair scores sum to the reported objective. Direction must
match across the two graphs. Conserved edge correctness is the fraction of
normalized graph-A edges conserved; it is null when graph A has no edges.

For entity resolution, record fields are paths relative to vertex `attributes`.
An example blocking rule is:

```json
{
  "id": "similar_names_in_city",
  "all": [
    {"field": "city", "operator": "eq", "normalization": "nfkc_casefold"},
    {"field": "name", "operator": "edit_distance", "max_distance": 2}
  ]
}
```

Supported operators are `eq`, `shared_token`, `edit_distance` and
`numeric_difference`. Distance predicates require `max_distance`; edit
distance uses a nonnegative integer and numeric distance a nonnegative number.
Text normalization is `none`, `casefold` or `nfkc_casefold`, the last applying
NFKC before case folding. Tokenization splits on Unicode whitespace without
discarding punctuation. Equality distinguishes JSON value types. Optional
missing values never match one another. `match_decision_rule` contains the
same nonempty `all` array without a rule ID. Input edges are unused hints and
cannot override the declared candidate or match rules. With fewer than two
records, the reduction ratio is defined as zero because no comparisons exist.

Anomaly feature definitions have a unique `name` and a `measure`:

- Vertices: `degree`, `in_degree`, `out_degree`, `strength`, `in_strength`,
  `out_strength`, `triangle_count`, `ego_edge_count`, `event_count`,
  `in_event_count`, `out_event_count`, or `numeric_attribute`.
- Edges: `edge_weight`, `source_degree`, `target_degree`, `common_neighbors`,
  or `numeric_attribute`.
- Subgraphs: `vertex_count`, `edge_count`, `density`, `weight_sum`, or
  `numeric_attribute`.

Numeric attributes additionally declare `field`. In/out features require
directed graphs; triangle, ego and common-neighbor features require undirected
graphs. Structural degree collapses parallel edges and counts a self-loop
twice; strength sums weights. Incident event count retains parallel events and
counts a self-event once. Subgraph edge counts and weight sums retain original
edge instances; density uses the loop-free simple projection. Subgraphs are
declared as `{id, vertices, attributes?}`; no implicit subgraph search is claimed.

A normality reference is either `kind=population`, optionally naming another
graph and a subset of its entities, or `kind=statistics` with explicit
`location`/`scale` arrays. Features are computed against their full source graph
before reference-entity selection. Population scale uses standard deviation
with `ddof=0`. Centering retains a numerical origin and mean offset to avoid
losing small deviations around large values; constant columns have exactly
zero scale. Reference subgraphs must be supplied for an external subgraph
population.

Scoring declares `method` (`standardized_l1`, `standardized_l2`, `max_abs_z`),
optional nonnegative `feature_weights`, and optional nonnegative
`minimum_scale`. Let `z_j = (x_j-location_j)/max(scale_j,minimum_scale)`.
Scores are `sum(w_j*abs(z_j))`, `sqrt(sum(w_j*z_j^2))`, or
`max(w_j*abs(z_j))`, respectively. A zero denominator with zero deviation
contributes zero. A nonzero deviation in an active zero-scale feature is an
error unless the user supplied a positive floor. Zero-weight features make no
score contribution. Results include feature values and contributions, with
deterministic ties ordered by typed entity ID (integers before strings).

### Diffusion, drawing and spectral sparsification

| Operation | Implemented objective and method | Limits and result interpretation |
|---|---|---|
| `influence-maximization` | Enumerate seed sets and exact rational live-edge probabilities; NetworkX reachability supplies activation counts. Supports independent cascade, random-threshold LT, and progressive activation for supplied fixed LT thresholds. | Exponential CPU reference method, limited by candidate/time budgets rather than a fixed k cap. Requires `1 <= seed_set_size <= vertex_count`. Returns the exact rational expectation and optimum; sampling-method and statistical-tuning parameters are not accepted. |
| `force-directed-layout` | NetworkX Fruchterman–Reingold force iterations, explicit distance regularization, recomputed potential and force residual. | Supports 2D/3D and fixed nonnegative iteration counts. `iterations=null` and ForceAtlas2 are not integrated in this profile. Zero iterations preserve supplied initial coordinates. A requested converged result must pass the force-residual criterion; no drawing optimality is claimed. |
| `spectral-sparsification` | Effective-resistance sampling with replacement, importance reweighting, and SciPy generalized-eigenvalue verification on grounded positive-weight components. | Static weighted simple graphs only. An explicit edge budget bounds retained edges; repeat draws merge. An optional `epsilon` must pass the numerical all-vector check. Dynamic-update parameters are not accepted. Zero weights can be dropped; loops/parallel edges are rejected. |

Diffusion weights are explicit probabilities. Parallel independent-cascade
probabilities combine as `1 - product(1-p)`; linear-threshold weights sum and
each vertex's incoming total must not exceed one. Loops are removed. Fixed
thresholds use typed `{vertex, value}` rows, and a fixed zero threshold activates
without an active predecessor. This matters even in an edgeless graph. A seed
budget above the vertex count is rejected because the required distinct
cardinality is impossible. Exact rational comparisons preserve influence
differences smaller than the rounded displayed spread.

The layout profile explicitly requests `method="force"`, including above
NetworkX's automatic method-switch boundary, and disables final rescaling.
For pair distance `r`, edge attraction weight `w` (zero on a nonedge), length
`k`, and `d=max(r,0.01)`, its force on a vertex is
`(position_u-position_v) * (k^2/d^2 - w*d/k)`.
The returned energy sums the continuous antiderivative of that clipped force.
Above the distance floor it is `w*r^3/(3*k) - k^2*log(r)`; below the floor it is
`w*(0.01*r^2/2 - 0.01^3/6)/k - k^2*log(0.01) + k^2*(1-r^2/0.01^2)/2`.
Coincident coordinates therefore have finite energy. The reported convergence
test is the maximum uncooled force norm, including for disconnected layouts.
The browser can display the computed coordinates with uniform scaling; 3D
coordinates have an explicitly labeled XY projection and remain intact in the
table and full export.

Sparsification samples edge `e` with probability proportional to `w_e R_e` and
assigns retained weight `w_e * multiplicity / (draws * probability_e)`.
All original vertices and retained edge IDs survive. Generalized eigenvalues
measure the extreme quadratic-form ratios across all vectors modulo the
original Laplacian nullspace. They are numerical diagnostics, not exact
arithmetic or probabilistic certificates. Component checks separately detect
new null directions, so rounding a zero eigenvalue upward cannot permit a
strict `epsilon<1` claim after a bridge is lost. The full positive-edge and
zero-edge cases have algebraic bounds; ill-resolved numerical systems are
rejected. The default work budget also covers dense solve and verification
cost, so these are reference integrations rather than large-graph benchmarks.

## Numerical and resource limits

The mathematical models implement the stated objectives. SciPy's `milp` wraps
HiGHS and converts coefficients to double precision. The wrapper requests zero
relative MIP gap, requires an optimal solver status, validates rounded binary
variables and constraints, and compares the recomputed objective with the dual
bound. It rejects unrepresentable integer coefficients and total objective
magnitude beyond the supported float64 integer range. A numerical certificate
is labeled `numerical_optimum`; it is not a formal rational proof.

Binary objectives are reduced onto their exact rational coefficient grid when
the reduced integer coefficients fit the supported range. Otherwise they are
normalized by their largest absolute coefficient, with numerical status still
explicit. This prevents uniformly tiny costs from being discarded by absolute
solver tolerances while preserving integer objective differences. Diagnostics
record the scaling rule and rational unit, scaled objective/dual bound, and
the bound and tolerance converted back to original objective units. Coefficient
underflow after scaling is rejected.

For unconstrained clique density, floating edge values are converted to their
exact rational representation, integer capacity units preserve ordering, and
the final density fraction is retained. The displayed numeric density is the
rounded JSON number; the fraction and original induced edge value retain the
exact result.

Candidate, output and elapsed-time budgets bound work. HiGHS also receives the
remaining solver time. General synchronous library calls still require the
planned subprocess worker for hard cancellation and memory limits. There is
no claim that NP-hard or enumerative operations will finish on arbitrary large
graphs. Budget exhaustion raises a resource error and never produces a result
marked exhaustive or optimal.

## Data and predicate conventions

JSON map keys cannot distinguish the original vertex IDs `0` and `"0"`.
Per-vertex inputs and outputs therefore use arrays of records. For example:

```json
{
  "vertex_weights": [
    {"vertex": 0, "value": 2},
    {"vertex": "0", "value": 3}
  ]
}
```

Mappings contain `{query_vertex, data_vertex}` rows. Bipartite algorithms that
do not take explicit partition parameters read each vertex's
`attributes.side`, whose value must be `left` or `right`.

Pattern predicates are data objects, not executable expressions. Every
predicate names a `field` and an `operator`. Supported operators are `eq`,
`ne`, `lt`, `le`, `gt`, `ge`, `in`, `exists`, and `eq_query`.

```json
{
  "vertex_predicates": [
    {"field": "type", "operator": "eq_query"},
    {"query_vertex": "person", "field": "attributes.age", "operator": "ge", "value": 18}
  ],
  "edge_predicates": [
    {"field": "type", "operator": "eq_query"}
  ]
}
```

Vertex fields are `label`, `type`, or an `attributes` path. Edge fields are
`type`, `weight`, `timestamp`, or an `attributes` path. `eq_query` compares
the corresponding query field, optionally named by `query_field`. A
`query_vertex` or `query_edge` restricts the predicate to that query record.
Missing fields fail comparison predicates; `exists` checks presence explicitly.
Equality uses typed JSON values. Ordering applies to numbers or strings;
timestamp strings are compared lexically and must already use a comparable
canonical representation if temporal ordering is intended.

## Frequent-pattern mining

`frequent-subgraphs` takes a `GraphCollection` (`dataset_id` plus a `graphs`
array). All members use the canonical graph format, have unique graph IDs,
and agree on direction. A vertex ID belongs to its transaction; equal vertex
IDs across transactions do not merge vertices or transactions. Identical graph
content with distinct graph IDs counts as separate observations.

The exact reference enumerates vertex subsets and bounded edge subsets, or
induced vertex subsets when requested. This includes disconnected patterns
and patterns with isolated vertices. `minimum_vertices` defaults to one;
setting it to zero explicitly includes the empty pattern when the edge bounds
permit it. `maximum_vertices=null` considers every size occurring in a member.
No fixed maximum edge count is imposed. The support of an isomorphism class
is the number of transactions containing it, regardless of occurrence count.
The supplied decimal support fraction is compared as an exact rational; the
displayed fraction is rounded floating point. An empty database has no patterns.

`label_semantics` selects vertex `type`, edge `type`, both, or neither. Selected
missing types form a category distinct from the empty string. Display labels,
weights, timestamps and unselected attributes do not participate. Loops are
rejected or explicitly dropped. Parallel edges are rejected by default; an
explicit collapse requires identical selected edge types. The same policies
apply to every transaction.

`single-graph-frequent-subgraphs` takes one simple undirected host. It discovers
connected patterns, including single-vertex patterns, through
`max_pattern_edges`. Every vertex must have the selected string `label` or
`type`; repeated values never merge distinct host vertices. Edge attributes
are ignored. Loops are rejected and parallel-edge collapse must be explicit.
For each canonical pattern vertex, NetworkX VF2 enumerates all induced
isomorphisms or non-induced monomorphisms and collects distinct host images.
MNI support is the smallest of those image-set sizes. It is neither the
number of embeddings nor the number of edge-disjoint copies. Optional image
sets preserve the original typed host IDs. `output_mode=count` returns an exact
count and no pattern port; `include_images` requires pattern output.

Both profiles use igraph's BLISS canonical permutation, encoding each edge as
a subdivision vertex with a separate color category. Directed edges become
directed two-arc paths; selected types color the original and subdivision
vertices. The complete serialized canonical key, including categorical values,
deduplicates patterns. SHA-256 names the resulting pattern graph; the digest
is not the equality test. Canonical IDs are reproducible within the recorded
library version, not promised stable across canonicalizer upgrades. Pattern
vertex IDs are local to each pattern; they are not host identifiers.

These are exponential reference integrations, subject to explicit candidate,
time and output budgets. Budget exhaustion fails without a completed claim.
Direct calls cooperate between library calls; the application additionally
uses cancellable workers for hard deadlines. Pattern ports can be selected by
the fixed `pattern_graph` workflow selector, creating a graph with its own
fingerprint and namespace. The browser's fixed renderer switches to the graph
belonging to the selected pattern row.

Primary implementation references: [igraph BLISS canonicalization](https://python.igraph.org/en/main/api/igraph.GraphBase.html#canonical_permutation)
and [NetworkX VF2 matching semantics](https://networkx.org/documentation/stable/reference/algorithms/isomorphism.vf2.html).
The independently generated graph universes and brute-force vertex injections
in `test_frequent_patterns.py` do not use either production routine. They cover
all 64 four-vertex graphs with all 16 binary vertex-label assignments under
both match modes, transaction/occurrence distinctions, directed shapes, empty
and disconnected patterns, categorical semantics, original-ID permutations,
seven/eight-edge patterns, budget failures and downstream pattern graphs.

## Exact graph edit distance and common subgraphs

`graph-edit-distance` and `maximum-common-subgraph` take two graphs with the
same direction. Selected categorical vertex fields default to `label` and
`type`; the edge field defaults to `type`. Missing and empty categories differ.
`ignore_labels` disables category matching. Weights, timestamps and unselected
attributes do not affect either objective. Loops are dropped by default or
explicitly rejected. Parallel edges require explicit collapse, which retains
the first edge and requires matching selected categories unless labels are
ignored. Both result witnesses refer to these normalized graphs.

Edit distance supports five nonnegative decimal costs: vertex insertion and
deletion, and edge insertion, deletion and substitution. Each defaults to one.
Equal or ignored vertex labels have zero replacement cost; unequal selected
labels cost vertex insertion plus deletion, as specified by this contract's
exact label policy. An independent `vertex_substitution` parameter is rejected.
Edge relabeling uses the cheaper of substitution and deletion plus insertion.
Graph IDs, vertex IDs and edge IDs are identities, not paid-for labels.

The exact reference reduces partial injective vertex correspondences to a
nonnegative rational-weighted state DAG and calls NetworkX Dijkstra. A feasible
incumbent permits pruning states whose accumulated cost cannot improve it.
Label-compatible bipartite matching handles edgeless inputs, and VF2 detects
zero-cost isomorphisms. Every returned objective is independently recomputed
from its correspondence. Arithmetic uses exact fractions of the supplied
decimal numbers, preserving costs such as `1 + 1e-200` and large integers.
The `rational_scalar` distance port retains numerator, denominator and a
possibly rounded display value. It cannot bind implicitly to a floating-point
or integer workflow parameter.

The ordered edit script includes per-operation rational costs and stable
vertex/edge handles. Original and target external IDs remain record data until
final serialization; swapping IDs cannot collide with a still-live object.
Incident edges are deleted before a vertex is deleted, and all endpoints exist
before an edge is inserted. Source handle tables and normalized source/target
graphs make the script independently replayable. The correspondence includes
matched, inserted and deleted vertices; a missing side is `null`.

Common-subgraph search maximizes **vertex count**. The default induced variant
uses NetworkX VF2 on subsets in decreasing size. Non-induced subgraphs may be
disconnected or edgeless, so their maximum vertex count reduces to
label-compatible bipartite matching. The returned graph includes compatible
common edges for that mapping; there is no secondary edge-count objective.
Its vertices retain the first graph's IDs. Its graph identity incorporates both
parent fingerprints, preventing a downstream selection from crossing into an
unrelated comparison with identical-looking IDs and topology.

These are completed exact reference profiles, with no fixed small vertex
ceiling. Search remains exponential, and exhausted candidate/time/output
budgets fail without an optimum claim. Approximate modes, timed incumbent
results, custom predicates, connected-only MCS and maximum-edge MCS are not
advertised. The agent's worker enforces hard deadlines around library calls.

`test_graph_comparison.py` independently enumerates partial injections and
replays edit scripts. It covers all 361 pairs of graph-atlas graphs through
four vertices, all 4,096 pairs of three-vertex directed graphs, selected
categorical labels, both MCS modes, unequal and zero costs, tiny decimal
differences, large costs and typed IDs, normalization, budgets and dependent
workflows. These oracles do not use Dijkstra, VF2 or bipartite matching.

Primary implementation references: [NetworkX single-source Dijkstra](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.shortest_paths.weighted.single_source_dijkstra.html),
[VF2](https://networkx.org/documentation/stable/reference/algorithms/isomorphism.vf2.html)
and [Hopcroft–Karp matching](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.bipartite.matching.hopcroft_karp_matching.html).

## Independent evidence

The new oracle suite uses subsets, permutations and set partitions to check
the production flow, VF2, matching and HiGHS implementations. It includes all
208 nonempty unlabeled undirected graphs through six vertices, all 512 simple
3-by-3 bipartite graphs, all 729 signed four-vertex graphs, all 64 loop-free
three-vertex digraphs, weighted fixtures, mixed IDs, large integers, loops,
parallel edges, infeasible constraints, truncated listings and resource failure.

This is evidence for the tested profiles. It does not establish full parameter
coverage, scale suitability or completion of the entire 70-problem collection.
The authoritative inventory is generated by
`tools/audit_python_analytics.py --write` in the analytics environment.

## Primary references

- [SciPy MILP and HiGHS interface](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html): solver statuses, floating-point conversion and gap controls.
- [NetworkX VF2](https://networkx.org/documentation/stable/reference/algorithms/isomorphism.vf2.html): induced matching, monomorphisms and attribute semantics.
- [NetworkX graph atlas](https://networkx.org/documentation/stable/reference/generated/networkx.generators.atlas.graph_atlas_g.html): complete unlabeled graph dictionary through seven vertices.
- [NetworkX Louvain](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.community.louvain.louvain_communities.html): modularity optimization and resolution.
- [VLDB 2025 bipartite community paper, Definition 2.1](https://www.vldb.org/2025/Workshops/VLDB-Workshops-2025/LSGDA/LSGDA25_02.pdf): degree-based (alpha,beta)-core definition.
- [SciPy GMRES](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.gmres.html): absolute residual stopping and iteration-count semantics.
- [GUDHI simplex tree](https://gudhi.inria.fr/python/latest/simplex_tree_ref.html): flag expansion, persistence in the top complex dimension and supported prime fields.
- [CVXPY solver interface](https://www.cvxpy.org/tutorial/solvers/index.html): declared solver choice, termination status and solver statistics.
- [NetworkX simple edge paths](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.simple_paths.all_simple_edge_paths.html) and [bounded simple cycles](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.cycles.simple_cycles.html): path/cycle identity, multiplicity and hop bounds.
- [NetworkX configuration model](https://networkx.org/documentation/stable/reference/generated/networkx.generators.degree_seq.configuration_model.html): stub sampling and why removing loops/parallel edges would change the degree sequence.
- [NetworkX G(n,m)](https://networkx.org/documentation/stable/reference/generated/networkx.generators.random_graphs.gnm_random_graph.html): uniform simple graphs at fixed vertex/edge counts.
- [node2vec paper](https://arxiv.org/abs/1607.00653): second-order return and exploration biases. The directed extension used here is separately declared in the profile.
- [RapidFuzz Levenshtein](https://rapidfuzz.github.io/RapidFuzz/Usage/distance/Levenshtein.html): unit edit costs and bounded-distance evaluation.
- [SciPy standardized scores](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.zscore.html): reference mean, standard deviation and degrees-of-freedom convention.
- [Kempe, Kleinberg and Tardos influence models](https://www.cs.cornell.edu/home/kleinber/kdd03-inf.pdf): progressive diffusion and live-edge equivalence.
- [NetworkX spring layout](https://networkx.org/documentation/stable/reference/generated/networkx.drawing.layout.spring_layout.html): force-method selection, distance regularization and rescaling controls.
- [Effective-resistance sparsification](https://arxiv.org/abs/0803.0929) and [SciPy generalized eigenvalues](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.eigvalsh.html): sampling construction and the numerical verification used here.
