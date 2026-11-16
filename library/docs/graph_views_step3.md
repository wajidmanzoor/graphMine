# Standard graph views: Step 3 progress

Step 3 is in progress in `devlopment`. Production is unchanged. This file will
record the CPU-family migrations and their independent commit gates.

## Prerequisite extensions

The user approved two additions needed to preserve existing CPU behavior:

- COO record mode, retaining original edge orientation, identity and order.
- Exact-rational weights, preserving parallel sums that cannot fit f64 or int64.

Both are implemented in the shared factory. Existing defaults remain unchanged.
New tests cover record order, undirected parallel records, loops, incompatible
specs, rational min/max/sum, binary64 fractions, sums beyond binary64 range,
negative loop validation, parser precision restrictions and byte determinism.

The first checkpoint is `validation/graph_views/step3/00-view-extensions/`.
It passes 52 runtime CTests, 238 Python tests, the existing 129,073-request C++
oracle replay and all 82 CPU capability admissions. Existing normalizer byte
goldens are replayed against the Step 2 corpus. No CPU family is declared migrated
by this prerequisite commit.

The checkpoint runner initially resolved a virtualenv interpreter symlink to
system Python. That caused the first agent capability check to fail. It now
retains the virtualenv path, and all three agent checks pass. The initial output
is preserved losslessly under the checkpoint's `diagnostics/` directory.

`tools/validate_graph_view_checkpoint.py` runs the existing gates and refreshes
execution evidence for each family commit. Algorithm-specific input goldens are
retained alongside those reports.

## Traversal

Breadth-first search now reads V1 CSR directly. Its immutable declaration lives
beside the CPU adapter and specifies preserved direction, dropped loops, first
parallel-edge collapse, omitted weights and sorted neighbors. Source selection,
predecessor tie-breaking, depth limits and independent/nearest-source modes are
unchanged. The existing cuGraph path remains for Step 4.

`view_profiles.*` exposes the same declarations used by adapters for later
registry generation. The shared acquisition helper records the actual profile,
resolved spec and normalization in provenance, preserving candidate admission
on fresh and cached views. It performs no normalization itself.

Checkpoint `01-traversal` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Its byte golden compares the actual declared view with the frozen
old adjacency builder on every Step 2 corpus graph, including warm-cache costs.
The declaration test also checks the spec reported by real BFS requests.

## Weighted paths

Single-source and many-source shortest paths now read weighted CSR directly.
Minimum/maximum spanning forests read candidates from that same layout. Five
immutable profiles describe their weight modes and collapse policies. The
unweighted many-source profile retains the original rule that stored negative
lengths are invalid, including dropped self-loops; it requests unit weights from
the factory instead of overwriting them in the adapter.

Checkpoint `02-weighted-paths` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Its five-profile golden compares offsets, neighbors, f64 weight bits,
direction, successful candidate counts and rejection messages against the frozen
old builders, including cold/warm cache cases. Real operation requests also check
that the consumed spec equals the adapter's declaration. CPU path arithmetic and
tie-breaking are unchanged; the cuGraph code path remains for Step 4.

## Connectivity

Weak/strong connected components and topological sorting now consume declared
CSR views. Strong components use the factory's reverse CSR; weak components use
the identical symmetric rows in both directions. The old reverse-index candidate
cost is preserved. Topological sorting retains its existing rejection of
self-loops before consuming the view.

Checkpoint `03-connectivity` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Three profile goldens cover the complete Step 2 corpus and check
forward/reverse arrays, weights, direction and candidate costs. Real-operation
checks verify each selected declaration. GPU connectivity adapters remain for
their later migration steps.

## Cliques and cores

Maximal, maximum and fixed-size cliques, k-core, maximum independent set and
minimum vertex cover now consume declared CSR views. Their vector-row repacking
only copies CSR slices; normalization is entirely in the factory. Complement
construction remains part of the independent-set/vertex-cover algorithm.

Checkpoint `04-cliques` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Six profile goldens compare CSR arrays and the repacked row bytes
against the frozen old adjacency builder on all 6,571 corpus graphs, with cold
and warm cache calls and equal candidate costs (39,426 profile cases). Operation
requests check the consumed declaration, including tie enumeration, fixed-size
enumeration, core selection and vertex-cover decision modes. GPU paths retain
their existing adapters.

## Reachability and clique percolation

Transitive closure now searches CSR directly. Overlapping communities copies
CSR slices into the existing clique enumerator's row layout. Both declare
unweighted, loop-free, sorted neighbors with first parallel-edge collapse.

Checkpoint `05-reachability` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Both input profiles pass 13,142 cold/warm corpus cases against the
frozen adjacency builder, including row bytes and candidate costs. Declaration
checks cover full/count-only closure, single/batch pairs, and clique-percolation
options. Their algorithm results remain covered by the existing CPU tests.

## Density

Densest subgraph and fixed-size densest subgraph now obtain their exact edge
lists from rational COO views. A layout decoder reconstructs numerator and
denominator integers without a floating-point round trip and stores each
symmetric undirected edge once. Weighted profiles sum parallel weights exactly;
unweighted profiles retain one unit edge. Higher-order clique terms and
quasi-cliques consume separate declared adjacency views.

The factory offers an original-record budget callback so the exact adapters
retain validation/resource-limit ordering, including negative weights on loops.
Successful cache hits pay the same record cost. Existing f64 defaults and other
adapters' budgets remain unchanged.

Checkpoint `06-density` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Six profiles pass 39,426 corpus cases, checking endpoint and original
edge-index bytes, canonical rational numerator/denominator bytes, candidate
costs and matching rejections. Contract tests include sums beyond f64 precision
and range, weighted/unweighted modes, small candidate budgets and declarations
consumed by real density requests.

## Centrality

PageRank and personalized PageRank now declare f64 CSR inputs for each weight
and direction mode. Their layout-only row copy feeds the existing Markov
transition calculation, including its long-double row sums and dangling-node
policy. Betweenness and degree centrality read weighted CSR directly. The
positive-length guard, exact Brandes arithmetic, normalization and tie-breaking
remain unchanged.

Checkpoint `07-centrality` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Fourteen profile goldens cover 91,994 corpus cases, checking CSR and
repacked row bytes, weight bits, direction, successful candidate costs and
matching rejections. Declaration checks exercise every weight/direction profile
and all three personalized PageRank dangling policies. GPU solver paths retain
their existing input builders.

## Coloring and maximal independent set

The seeded greedy coloring and maximal-independent-set algorithms now obtain
their adjacency rows from declared CSR views. Their seeded traversal, conflict
checks and distance-two conflict construction remain unchanged. GPU adapters
continue to use their existing input path.

Checkpoint `08-coloring` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Both profiles pass 13,142 corpus cases comparing CSR and copied row
bytes, with identical candidate costs. Real-operation checks verify declarations
for maximal independent set and both supported coloring distances.

## Similarity

Link prediction now obtains its unit-weight and neighbor inputs from one
declared CSR view while retaining the old combined preparation cost. SimRank
declares reverse and symmetric CSR profiles for its incoming-neighbor and
undirected-projection modes. Both retain their existing scoring algorithms.

Checkpoint `09-similarity` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Three profiles pass 19,713 corpus cases, comparing arrays and copied
rows with the frozen weighted, adjacency and SimRank builders. Link prediction
checks both former input layouts and their combined candidate cost. Declaration
checks cover all eight link scores and all three SimRank query modes in both
directions. The cuGraph Jaccard path remains unchanged.

## Pattern counts

Triangle, graphlet and motif counting now consume declared CSR views. Motif
queries declare both forward and reverse CSR; their connectivity check copies
the two slices in the previous order, including reciprocal entries. Embedded
graphlet templates and the counting/enumeration algorithms remain unchanged.

Checkpoint `10-patterns` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Four profiles pass 26,284 corpus cases, including forward/reverse
arrays and the exact concatenated weak-connectivity rows. Request checks cover
counts, limited listings, graphlet orbits and directed/undirected motif modes,
and verify both input and motif declarations. The first build found a type
comparison error in the test helper; it was corrected before these successful
gates, and the original build log is preserved in `diagnostics/`.

## Community detection and balanced partitioning

Both CPU operations now declare exact-rational COO profiles for weighted and
unweighted input. Parallel sums, canonical edge order, original edge identities
and rejection behavior match the frozen exact edge-list builder. Partition
objectives, search order and the community heuristic remain unchanged.

Checkpoint `11-partitioning` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Four profiles pass 26,284 corpus cases. Real-operation declaration
checks cover both community quality functions, exact/heuristic search, both
weight modes and both balanced-cut objectives. GPU adapters and the separate
signed-balance operation retain their existing paths for subsequent migrations.

## Spectral operators

Laplacian eigenpairs and graph-signal denoising now pass their declared exact
COO profile into Laplacian construction. Denoising's incidence operator consumes
the same profile. Matrix assembly, precision/underflow guards, LAPACK calls,
optimization and residual checks remain unchanged.

Checkpoint `12-spectral` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Both profiles pass 13,142 exact edge-input corpus cases. Declaration
checks cover combinatorial/normalized Laplacians, both eigenvalue selections,
all three denoising regularizers and zero-strength denoising. Existing numerical
tests continue to verify independent residuals and objective certificates.

## Network alignment

Both alignment graphs now consume the selected weighted or unit exact-COO
profile. The explicit-weight guard, edge-conservation objective, node priors,
assignment order and tie-breaking remain unchanged.

Checkpoint `13-alignment` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Two profiles pass 13,142 exact edge-input corpus cases, including
direction, edge order, original identities and exact sums. Request checks cover
directed/undirected input, both weight modes and node-similarity priors while
verifying the declaration consumed for each graph.

## Seeded local community

The seed-first community sweep now consumes an exact COO edge view for its
degree, volume and cut calculations. Its personalized PageRank subroutine uses
the already-migrated CSR profile. Seed constraints, sweep order, conductance
arithmetic and result fields remain unchanged.

Checkpoint `14-local-community` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. The exact edge profile passes all 6,571 corpus cases. Request checks
cover single/multiple seeds and an explicit volume bound, including the local
profile alongside its nested PageRank view.

## Geolocation and explicit cache-state regression

Geodesic propagation now consumes an exact COO edge profile. Seed handling,
medoid candidates, numerical energy calculations and convergence checks are
unchanged. Checkpoint `15-geolocation` passes 53 CTests, 238 Python tests, all 82
CPU admissions and all 6,571 input corpus cases. Real requests verify the
declared profile with fixed and movable seeds.

The golden runner now explicitly clears the cache before each input comparison
and verifies a miss followed by a retained hit. Its test-only 1 GiB capacity
accommodates the largest corpus view; the production/default capacity is not
changed. All 14 previous family suites were replayed with these stronger
assertions: 361,405 profile cases passed, with no input differences. Their
reports and binary hash are retained in `15-geolocation/cache-regression/`.

## Graph condensation

Condensation's transductive graph operator now consumes an exact COO edge view.
Feature/label/split handling, gradient matching, optimization seeds and the
downstream utility evaluation remain unchanged.

Checkpoint `16-condensation` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Its input profile passes all 6,571 corpus cases with explicit fresh
build/cache-hit assertions. A real training/evaluation request verifies the
consumed declaration; existing learning tests continue to check the gradient
objective, propagated features and downstream utility.

## Record queries

Node lookup, edge filtering, neighbors, common neighbors, query paths, graph
aggregation and query subgraphs now declare record COO inputs. Their backend
index copies original edge orientation, ordering and identities from the view;
arbitrary typed properties still come from the unchanged common-front records.
The existing common-front parameter validator retains its original index path.

Checkpoint `17-record-queries` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Seven profiles pass 45,997 corpus cases, comparing endpoint arrays,
incoming/outgoing original-edge lists, ID maps, complete record JSON bytes and
candidate costs. Fresh/cache-hit assertions and small budget rejection checks
pass. Real requests verify all seven declarations, directed/undirected inputs,
both-direction discovery, path enumeration, grouped aggregation and extraction.

## Force-directed layout

Layout now declares dense weighted and unit adjacency views. The user approved
`sum_arithmetic: long_double_round_each` to preserve its existing extended
intermediate and per-addition rounding, including positive-zero initialization.
The default f64 arithmetic is unchanged. Required-weight and sign validation
still precede loop removal; dense allocation guards still precede edge checks.

Checkpoint `18-layout` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Weighted/unit input in both 2D and 3D passes 26,284 corpus cases.
These comparisons use the existing 2,000,000-candidate budget: accepted matrices
and initial position arrays match byte for byte on fresh builds and cache hits;
large inputs reproduce the old rejection before allocating a dense matrix.
Boundary tests cover a demonstrated one-bit arithmetic difference, signed zero,
sequential rounding, reciprocal edges, missing and negative loop weights,
overflow, and budget-error precedence. Real requests verify both declarations.

## Subgraph isomorphism

Both data and query graphs now use a declared COO view that retains loops,
parallel edges and original identities. Its canonical undirected half is copied
into the existing edge bundles. Complete typed property records still come from
the common front. Predicate evaluation and the assignment search are unchanged.
Other callers of the shared matcher keep their legacy constructor until their
own family migration.

Checkpoint `19-subgraph-matching` passes 53 CTests, 238 Python tests and all 82
CPU admissions. All 6,571 corpus cases match vertex/edge JSON bytes, ordered
bundle endpoints, original-edge index arrays and costs, on fresh and cached
views. Budget tests and real induced/non-induced requests with parallel-weight
predicates and result limits pass and verify the consumed declaration.

## Biconnected components and k-truss

Both CPU adapters now declare a collapsed CSR topology and a COO view of all
contributing non-loop records. Repacking preserves canonical pair order,
neighbor/edge-index arrays and every original source ID. The second view avoids
losing parallel-edge identities from the existing results. The GPU k-truss path
remains on its earlier input constructor for its own migration.

Checkpoint `20-structure` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. The two adapters pass 13,142 corpus cases, each comparing both views'
combined algorithm input on fresh builds and retained cache hits. Budget checks
and real requests verify all four declarations, including requested truss levels.
An initial constructor parameter/local-variable name collision was corrected;
the failed build log is retained under `diagnostics/`.

## Influence maximization

Both diffusion models now declare exact COO inputs. The user approved the new
`collapse:probability_union` rule for independent cascade; linear threshold
keeps exact sum. Probability validation, zero-probability entries, incoming-row
order, fixed-threshold propagation and exhaustive seed selection are unchanged.

Checkpoint `21-influence` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. The two profiles pass 13,142 corpus cases: admissible directed inputs
match endpoint/probability arrays and incoming rows byte for byte, while invalid
direction or missing/out-of-range probabilities reproduce the old rejection.
Tests cover exact parallel composition, zero/one probabilities, invalid dropped
loops, budget precedence, and both real diffusion models including fixed vertex
thresholds. Fresh/cache-hit assertions and declaration checks pass.

## Group Steiner tree

The CPU solver now consumes a minimum-weight exact COO view with original edge
identities. The factory selects the cheapest parallel edge, preserving the
first original edge on ties. The solver retains its cost/index visitation order,
group constraints, required vertices and exact optimization.

Checkpoint `22-steiner` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. All 6,571 corpus cases match edge endpoints, exact weights, selected
original IDs, visit order, costs and rejections. Tests cover equal/lower parallel
weights, negative/missing loop weights, budgets and both accepted quality
settings, with fresh/cache-hit and real-operation declaration checks.

## Graph coarsening

Automatic matching now reads a collapsed exact COO view; the quotient algorithm
reads an exact record COO view, once per original edge in its original order and
orientation. Existing input rejection, supplied cluster assignments, quotient
aggregation and feature reductions remain unchanged.

Checkpoint `23-coarsening` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Both profiles pass 13,142 corpus cases, comparing endpoints, original
IDs, exact weight fractions, costs and applicable rejections on fresh and cached
views. Request checks cover automatic/supplied partitions, quotient-loop keep
and drop policies, sum/mean feature reduction and both consumed declarations.

## Random walks

Uniform walks now read a unit CSR view; weighted and node2vec walks read exact
summed CSR weights. Self-loops, zero-mass transitions, missing-weight defaults
and sorted neighbor order are preserved. The random generator, node2vec bias
and stopping behavior are unchanged. The cuGraph preparation remains for Step 4.

Checkpoint `24-walks` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Both profiles pass 13,142 corpus cases comparing neighbor arrays,
exact transition weights, costs and rejections on fresh and cached views.
Directed/undirected real requests cover all three walk models with fixed seeds,
parallel/zero weights, loops and nondefault node2vec parameters.

## Null-model significance

The original edge set now comes from a declared COO view with dropped loops and
first-edge parallel collapse. Direction, canonical pair order, degree counts,
seeded randomization and statistic evaluation remain unchanged.

Checkpoint `25-null-models` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. All 6,571 corpus cases match endpoint bytes and candidate costs on
fresh builds and cache hits. Budget checks and real requests cover both null
models, all three tail choices, directed/undirected inputs, randomized-edge
output and multiple statistics while verifying the consumed declaration.

## Persistent homology

Minimum filtration weights now come from an exact COO view. The existing
loop/required-weight checks keep their order and messages; filtration cutoffs,
simplex enumeration, finite-field reduction and output intervals are unchanged.

Checkpoint `26-topology` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. All 6,571 corpus cases match canonical endpoints, exact minimum
weights, candidate costs and input rejections. Fresh/cache-hit comparisons,
parallel-weight and budget boundaries, and real requests across three field
primes and homology dimensions pass with the declared profile.

## Signed balance

Weighted/unit signed graphs now come from exact COO views and aligned edge-label
columns. The adapter retains its validation of positive/negative types,
nonnegative costs and contradictory parallel signs. Projection, dropped loops,
casts and weighted parallel sums occur in the factory. Parity traversal and
frustration optimization remain unchanged.

Checkpoint `27-signed-balance` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Both profiles pass 13,142 corpus cases comparing endpoint and sign
arrays, exact costs, ordering, budgets and rejections. Request tests verify both
tasks and quality settings, and boundary cases cover contradictory parallel
signs, fractional sums, missing types and negative loop costs.

## General weighted matching

General matching now consumes an exact maximum-weight COO view with selected
original edge IDs. Ties retain the first original edge. Directed-input,
required-weight and nonnegative-weight validation keep their existing errors.
Blossom construction, exact integer scaling and tie-breaking are unchanged.
Bipartite matching retains its earlier path for its separate V3 migration.

Checkpoint `28-general-matching` passes 53 CTests, 238 Python tests and all 82
CPU admissions. All 6,571 corpus cases match canonical endpoints, exact weights,
selected original IDs, ordering, costs and rejections, with fresh/cache-hit
checks. Boundary and request tests cover parallel maxima/ties, missing or
negative loop weights, small budgets and both accepted quality settings.

## Entity resolution

Entity resolution now reads vertex identities/order through a declared record
COO view and obtains unchanged typed records through its original-index map.
Blocking predicates, ICU text normalization, match decisions and clustering
remain unchanged. Input edge hints are still ignored by the algorithm.

Checkpoint `29-entity-resolution` passes 53 CTests, 238 Python tests and all 82
CPU admissions. All 6,571 corpus cases match complete vertex-record JSON bytes,
ordering, costs and budget behavior on fresh and cached views. Real requests
verify blocking and both clustering policies with Unicode names and large exact
integer attributes; existing independent Unicode/decision tests still pass.

## Widest and critical paths

Widest paths now read a required-weight CSR view. Layout repacking restores each
row's original-edge visitation order, including interleaved undirected mirrors,
without changing its arcs or weights. Critical paths read exact record COO
weights, endpoint arrays and original-edge adjacency. Cycle checks, source/sink
selection, dynamic programming and result ordering are unchanged.

Checkpoint `30-path-profiles` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Both adapters pass 13,142 corpus cases comparing neighbor order,
float64 capacity bytes, original-edge rows, indegrees, endpoints, exact weight
fractions, costs and rejections. Tests cover signed zero, reciprocal/parallel
records, missing weights, small budgets, negative DAG weights, explicit
sources/sinks and limited top-k output, with fresh/cache-hit assertions.

## Induced and ego subgraphs

CPU ego discovery now declares outgoing, incoming and undirected-projection CSR
profiles. Record extraction declares a record COO view and selects original
records through its endpoints/IDs. Complete typed properties, record order,
weights, timestamps and graph metadata remain unchanged. Existing non-CPU
callers retain the original common-front serialization path.

Checkpoint `31-induced-subgraph` passes 53 CTests, 238 Python tests and all 82
CPU admissions. Four declarations pass 39,426 corpus comparisons: three
discovery directions plus empty/all/alternating vertex-selection masks. The
latter compare full serialized graph bytes and costs. Tests cover candidate and
output budgets, both graph directions, direct extraction and nonzero/zero-radius
ego requests, with fresh/cache-hit and consumed-declaration assertions.

## Bounded paths and cycles

Bounded enumeration now consumes record and directed COO views. The record view
preserves each original edge's endpoint and order; the retained view applies the
existing loop removal and first-edge or parallel-preserving policy. Timestamp
parsing, exact fractional time arithmetic, anchor validation and enumeration
remain unchanged.

Checkpoint `32-enumeration` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Both parallel policies, with and without chronological ordering,
pass 26,284 corpus cases comparing original-edge adjacency, endpoint arrays,
exact timestamps, costs and input rejections. Fresh/cache-hit checks and real
requests cover all four tasks, anchor failures, invalid discarded timestamps,
RFC3339 fractions, time zones and candidate/output limits.

## Node learning

Node propagation now reads declared incoming, outgoing and undirected-projection
CSR views. The approved `one_per_vertex` loop policy replaces input loops with
one self-connection per vertex in the factory. Synthetic arcs cannot request
original-edge IDs or edge side tables. Feature preparation, split handling,
mean accumulation and the fitting objective remain unchanged.

Checkpoint `33-node-learning` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. All 19,713 corpus cases match CSR arrays, two-layer propagated feature
bytes and candidate costs on fresh and cached views. Property tests cover
synthetic-arc limits, empty/isolated vertices, direction, determinism and invalid
metadata combinations; request checks cover regression and classification. An
initial missing `<set>` test include was corrected before the passing run; its
build diagnostic is retained with the checkpoint.

## Graph learning

Graph learning now consumes declared V5 collection views for all three
propagation directions and for structural degree features. Member order and ID
maps remain unchanged, and the former per-graph loop/duplicate builder is
removed. Attribute features, pooling, training splits and fitting are unchanged.
The structured factory overload accepts the same observation/charge hooks as
ordinary graph views and records successful-build costs consistently on hits.

Checkpoint `34-graph-learning` passes 53 CTests, 238 Python tests and all 82 CPU
admissions. Four profiles pass 26,284 corpus comparisons of member maps, CSR
arrays, structural features, propagated binary64 values, costs and rejections.
Multi-member requests cover empty members, both feature sources and both
readouts. Structured cache tests check one observation per build/hit and equal
charges for collections, feature matrices and hypergraphs.
