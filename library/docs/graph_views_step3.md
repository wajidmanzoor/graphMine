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
