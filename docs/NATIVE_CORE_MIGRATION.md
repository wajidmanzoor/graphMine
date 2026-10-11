# Native C++/CUDA core and Python bindings

The user's architecture requirement supersedes the earlier Python-first
reference implementation. Algorithms, input contracts, backend selection and
results belong to the C++/CUDA library. Python transports requests and results
through a versioned C ABI. Native applications and the command-line executable
run without Python.

The shared taxonomy is `library/manifests/problem_families.json`. It assigns
all 70 formal problems and the record-query utilities to families. The native
catalog embeds this file; the Python wrapper obtains its catalog from that
binary. Family membership does not establish implementation or verification.
All formal contracts now have an executable native profile. Compilation and
evidence admission remain separate states.

## Current migration boundary

The shared runtime has **80 operations covering all 70 formal problems**,
including seven record-query utilities. Every operation has a C++ CPU profile;
23 operations have a GPU profile admitted by current evidence. The
[completion profiles](NATIVE_COMPLETION_PROFILES.md) describe the 52 operations
added after the 26-problem checkpoint. GPU dispatch calls native libraries or
isolated native CUDA workers:

| Operation | Family | GPU implementation |
| --- | --- | --- |
| Breadth-first search | traversal | libcugraph |
| Single-source shortest paths | traversal | libcugraph, bounded float64 costs |
| Many-source shortest paths | traversal | libcugraph, bounded float64 costs |
| Topological sort | traversal | CPU profile |
| Spanning tree/forest | trees | libcugraph, minimum and maximum |
| Connected components | connectivity | libcugraph, weak and strong |
| Biconnected edge blocks | connectivity | CPU profile |
| PageRank | centrality | libcugraph |
| Degree centrality | centrality | CPU profile |
| Betweenness centrality | centrality | libcugraph and original TurboBC; unweighted paths |
| Personalized PageRank | centrality | libcugraph; custom uniform dangling redistribution uses CPU |
| Local link prediction | similarity | libcugraph Jaccard; eight CPU measures |
| Maximum flow/minimum cut | flow | Original ECL-MaxFlow CUDA worker, integral capacities totaling at most 1e9 |
| General weighted matching | matching | CPU weighted Blossom profile |
| Bipartite matching/assignment | matching | Original Hungarian CUDA worker for complete square minimum-cost perfect assignment |
| Triangle counting/listing | motifs | Original ToT and WeTriC CUDA backends |
| Maximal cliques | cliques | Original RDMCE, MCE-GPU and G2-AIMD counts; bounded native materialization |
| Maximum clique | cliques | Original CUDA-MS, GPUMaximumClique and Maximum-Clique-on-GPU witnesses; native optimality check |
| Fixed-size cliques | cliques | Original GraphSet, repaired GAMMA and repaired KCGPU counts |
| Core decomposition | cores | Native libcugraph and original KCoreGPU |
| Truss decomposition | cores | Native libcugraph |
| Maximum independent set | independent_sets | Original maximum-clique kernels on the native complement, with optimality check |
| Minimum vertex cover | independent_sets | Exact complement reduction using the same maximum-clique kernels |
| Maximal independent set | independent_sets | Direct libcugraph C++ interface; independence and maximality checked in C++ |
| Vertex coloring | coloring | Direct libcugraph C++ interface; distance-1 and distance-2 conflict graphs |
| Random walk generation | sampling | Native libcugraph uniform and weighted walks; weighted node2vec uses CPU |
| Neighborhood sampling | sampling | CPU profile with exact weighted draws, typed fanouts and temporal cutoff |
| Induced/ego subgraphs | subgraphs | Native libcugraph BFS for ego discovery; C++ preserves original records |

The original `Graph` and typed external IDs are reused. Existing native APIs
remain available for compatibility. Original triangle, mining and centrality backends are included when building from the
`library` project with their corresponding options enabled.

`graphmine.native.NativeLibrary` is the thin Python binding. Its family methods
are obtained from the native catalog. It does not import NetworkX, cuGraph,
cuDF, NumPy or a Python algorithm module. `graphmine.run`, typed workflows and
the application worker now dispatch through this native binding. The public
package has no mandatory Python algorithm dependencies. Historical Python
implementations are explicit `graphmine.reference` oracles, never automatic
fallbacks.

YiGraph's reviewed CPU integrations wrap NetworkX/PyG. Their capabilities need
native implementations; importing those Python routines inside a C++ facade
would not satisfy this architecture. The existing independently checked Python
implementations remain useful as migration references and test oracles.

## Building and calling the core

A CPU-only build needs a C++17 compiler, Boost.JSON headers, OpenSSL, LAPACK,
ICU and CMake 3.24 or newer.
It has no Python or CUDA runtime dependency:

```sh
cmake -S library/runtime -B build/native-cpu -DCMAKE_BUILD_TYPE=Release
cmake --build build/native-cpu -j4
ctest --test-dir build/native-cpu --output-on-failure
build/native-cpu/graphmine-native catalog
build/native-cpu/graphmine-native run breadth-first-search graph.json \
  --parameters bfs.json --device cpu
```

`bfs.json` can contain `{"sources":[0],"source_mode":"independent"}`. The
canonical graph format is the same as the original core's input. C++ consumers
include `graphmine/runtime.hpp` and call `graphmine::runtime::request`; C
consumers use `graphmine/runtime_c.h`. Install with `cmake --install`, then use
`find_package(GraphMineRuntime CONFIG REQUIRED)` and `GraphMine::runtime`.
The C response allocation must be released with `graphmine_runtime_free`.
Minimal external C and C++ consumers are in `library/examples/native_runtime`.

To include the original CUDA backends, configure the `library` project;
`GRAPHMINE_BUILD_NATIVE_RUNTIME=ON` adds the runtime to its existing targets.
The original backend build options still control which GPU algorithms compile.

For direct RAPIDS integration, enable `GRAPHMINE_NATIVE_CUGRAPH` and/or
`GRAPHMINE_NATIVE_CUDF`. With the locally installed native distributions:

```sh
cmake -S library/runtime -B build/native-rapids \
  -DGRAPHMINE_NATIVE_CUGRAPH=ON -DGRAPHMINE_NATIVE_CUDF=ON \
  -DGRAPHMINE_RAPIDS_ROOT="$PWD/.venv-analytics/lib/python3.12/site-packages"
cmake --build build/native-rapids -j4
```

This prefix locates native headers and shared libraries. No interpreter is
invoked by the build or runtime. A conventional native installation can instead
set `GRAPHMINE_LIBCUGRAPH_ROOT`, `GRAPHMINE_LIBCUDF_ROOT`,
`GRAPHMINE_RAPIDS_INCLUDE_DIRS` and `GRAPHMINE_RAPIDS_LIBRARY_DIRS` explicitly.
The tested RAPIDS version is 26.10.0. Its libcudf headers require C++20 and the
matching bundled CUDA C++ headers. Native dependency paths are recorded in the
build and install RPATH; deploy those dependencies at the configured locations
or rebuild against the deployment prefix.

```python
from graphmine.native import NativeLibrary

library = NativeLibrary("build/native-rapids/libgraphmine_runtime.so")
result = library.family("traversal").breadth_first_search(
    canonical_graph,
    parameters={"sources": [0], "depth_limit": 3},
    device="gpu",
    gpu_device=0,
)
```

`cpu` never invokes CUDA; `gpu` fails when the requested backend/device is
unavailable. `auto` chooses a compiled GPU profile when the device and requested
variant are supported, otherwise the native CPU implementation with a recorded
reason. An explicit GPU request for a CPU-only variant fails.
A failed GPU computation is reported; requested parameters
are not altered to manufacture success. Backend selection and validation occur
in C++, including for Python calls.

## cuDF ingestion and visualization

The native `read_csv` request and binding method use libcudf for file access
and GPU value parsing. The reader preserves original nonempty, unique header
names and returns text for every field. Supplying `columns` additionally checks
the complete column set. Leading zeroes, large integer strings, quoted
delimiters, multiline strings, Unicode and literal `NA` survive parsing.
Native structural validation rejects ragged rows, malformed quotes, invalid
UTF-8 and NUL bytes before cuDF can discard or reinterpret fields.

```python
table = library.read_csv(
    "transactions.csv", columns=["source", "target", "amount"], gpu_device=0
)
```

The standalone equivalent is `graphmine-native read-csv transactions.csv
--columns column-names.json`, where the names file contains a JSON array.
The current ingestion profile limits files to 64 MiB and returned tables to
100,000 rows by default, with at most 4,096 columns and 1,000,000 cells including
headers. `max_rows` may be raised to 1,000,000 within the cell bound. Exceeding
these limits fails; it does not return an
apparently complete truncated table. cuDF ingestion requires a GPU and a
libcudf-enabled build. Once a graph has been constructed, the native CPU
algorithms can run without a GPU. Canonical graph JSON remains a native JSON
input format rather than being misinterpreted as a tabular file.

The web upload endpoint now uses the same native reader and C++ graph
constructor. Set `GRAPHMINE_NATIVE_BINARY` to a libcudf-enabled
`graphmine-native`; ingestion runs in an isolated process on
`GRAPHMINE_GRAPH_GPU_UUID` with a deadline and an output byte limit. A missing
native reader or unavailable GPU produces an explicit upload error.

```python
result = library.read_graph(
    "transactions.csv", source_column="sender", target_column="recipient",
    directed=True, id_type="canonical", gpu_device=0,
)
canonical_graph = result["graph"]
```

`graphmine-native read-graph transactions.csv --source-column sender
--target-column recipient --directed true` uses this same entry point. The
compatibility construction profile trims fields, maps canonical signed 64-bit
integer endpoint text to integers, preserves lexical IDs such as `001`, and
retains labels, types, scalar JSON attributes, weights, timestamps and parallel
records. Use `id_type="string"` to keep all endpoint IDs as strings. Conflicting
vertex attributes, duplicate edge IDs, nonfinite weights and precision loss
are rejected. Source hashes, the native implementation hash and resolved
mapping are retained in ingestion provenance.

Headerless edge lists support two to four positional fields:
`source target [weight] [timestamp]`. A file uses either commas or whitespace;
tabs outside quoted fields are normalized before cuDF parsing. Optional
source/target headers and `#`/`%` comment lines are supported. CSV records use
LF or CRLF; CSV quoted values can span lines. Edge-list quoted fields stay on
one line. Multi-table joins, explicit per-attribute schemas, task-specific
projections and wider format support remain migration work.
Rendering stays in Cytoscape and predefined browser charts/tables; NetworkX
does not render this workspace.

## Contracts and remaining work

The native profiles preserve string versus signed 64-bit integer IDs, including
integers above JavaScript's safe range. Unsupported larger integers and integer
weights that the original native `Graph` cannot represent exactly are rejected.
Extending native numeric storage is required before porting the exact rational
query and graph-comparison profiles; silently narrowing them is unacceptable.
Original JSON tokens are checked before constructing a DOM: overflowing
integer literals, nonfinite numbers and duplicate object keys are rejected.
Escaped spellings of the same key also count as duplicates. This applies to
native requests and CLI graph/parameter files.

CPU weighted paths use exact rational arithmetic over the binary64 weights
admitted by the original `Graph`. Each reachable distance includes
`distance_exact: {"numerator": "...", "denominator": "..."}`. The convenient
`distance` field is an integer when representable, otherwise a finite double
with `distance_rounded`, or a rational object if it exceeds floating range.
Only unreachable/cutoff-excluded vertices have null distance. Integer cutoff
values are compared without conversion to double. This preserves exact sums
but does not add arbitrary-precision input weights or IDs to `Graph`.

GPU shortest paths return numerical float64 results and an acyclic path
witness, including for zero-weight cycles. Bounds that could reach the
float64 unreachable sentinel or lose exact large integral costs require CPU.
All-zero lengths use native libcugraph BFS reachability and assign distance
zero to reached vertices. This avoids a reproduced libcugraph SSSP stall on
a single directed zero-weight edge; it does not substitute a CPU algorithm.
Spanning forests preserve original weights and exact total-weight fractions.
The GPU solver receives consecutive weight ranks (reversed for maximum);
this preserves the optimal forest while avoiding overflow in upstream weight
adjustments. Parallel edges collapse according to the requested objective.

Both PageRank solvers validate probability mass and independently recompute
the fixed-point L1 residual. Diagnostics record the requested tolerance,
accepted residual (with a 1e-12 numerical floor) and residual-based L1 error
estimate. Dangling policies and direction projections retain the reference
contract. A displayed personalized ranking may be filtered/capped while its
full score port remains complete. Link prediction instead marks its pair port
incomplete when `top_k` omits candidates; budgets apply before that cap.

BFS preserves direction, ignores weights, drops loops and collapses parallel
arcs. Its independent and nearest-source modes share exact hop distances;
nearest-source ties use the supplied source order. Triangle counting requires
explicit undirected input and uses the corresponding simple graph. Capped
triangle membership is incomplete even though its total count remains exact.
GPU triangle enumeration materializes and checks memberships in native CPU
code. Budgets bound CPU search, output, GPU PageRank iterations and path
working-state size; timeouts on
uninterruptible native GPU calls require the isolated worker boundary.

Before completing the user goal, migrate the remaining algorithms and native
backends, extend exact numeric types, connect the application's validated
algorithm worker to this core, and replace the reference evidence inventory with a
source/binary/dependency-aware native gate. Complete the remaining review
requirements in `VERIFIED_ANALYTICS_IMPLEMENTATION.md`, including the seven
previously missing formal problems, table projections, routing/evaluation,
recovery, MCP, reviewed examples, scheduling and representation caching.

## Earlier native reference validation

`validation/native_reference` records **39,231 successful native requests**:

| Suite | CPU | GPU 0 | GPU 1 |
| --- | ---: | ---: | ---: |
| Original runtime contracts | 20 | — | — |
| BFS | 4,608 | 4,608 | 4,608 |
| Triangles | 2,048 | 2,048 ToT | 2,048 WeTriC |
| New profile contracts | 28 | 30 | 30 |
| Weighted paths | 3,645 | 3,645 | 3,645 |
| Minimum/maximum forests | 1,458 | 1,458 | 1,458 |
| Connectivity/topological order | 320 | 256 | 256 |
| PageRank/personalized PageRank | 706 | 514 | 514 |
| Local link scores | 1,024 | 128 | 128 |

The independent C++ oracles use Floyd–Warshall matrices, exhaustive spanning
edge subsets, reachability equivalence, topological witnesses, pivoted linear
systems for PageRank, adjacency-matrix local scores and exhaustive triangle
triples. They cover typed IDs, isolates, zero lengths/cycles, negative forest
weights, parallel records, inclusive cutoffs, exact large costs, output
completeness, strict parameter validation and resource limits. Both physical
GPUs run the same supported profiles. CPU-only variants are explicitly tested
as CPU capabilities rather than counted as skipped GPU checks.

A further **30 binding/CLI tests**, **64 cuDF/construction tests**, and **41
working-app / 25 staged-app acceptance tests** passed with zero failures or
skips. Installed C and C++ consumers ran with Python off PATH and GPUs hidden;
the CPU shared library has no Python or CUDA linkage. The preserved working
tree retains additional streaming tests. Native, binding and app reports
record unchanged source/configuration/binary snapshots. Earlier checkpoints
remain under `validation/native_runtime` and `validation/native_ingestion`.

To run the current native matrix after building both configurations:

```sh
python tools/validate_native_runtime.py --cpu-build build/native-cpu \
  --gpu-build build/original-with-rapids/runtime --output validation/native_mining
```

For the current matrix, the GPU build must include libcugraph, libcudf, ToT,
WeTriC, TurboBC and all ten original mining backends listed above, with both physical
devices visible. The runner records source-bound implementation hashes,
immutable binary snapshots and per-suite logs; an external watchdog bounds
each oracle process.

`tools/audit_native_runtime.py` verifies these reports, the source inventory
embedded in each build, current source contents and the binding test snapshot.
It records binary and resolved dependency hashes in
`catalog/native_runtime_coverage.json`. This is migration evidence for the 26
integrated problems and their listed profiles; it does not establish coverage of pending profiles or
replace the application's evidence gate.

## Native selection and sampling contracts

Maximal independent sets are checked for independence and maximality; they do
not claim maximum cardinality. Greedy distance-1 and distance-2 coloring returns
proper colors and discloses that its color count is heuristic. Both use an
undirected simple projection with isolates preserved, loops discarded and
parallel edges collapsed. The optional native cuGraph C++ adapter is controlled
by `GRAPHMINE_NATIVE_CUGRAPH_CPP`, enabled by default with native cuGraph.

Random walks preserve direction, loops and repeated starting vertices. Length
counts transitions. Uniform walks sample distinct neighbors; weighted walks
sum parallel weights. C++ uses exact rational mass and integer rejection
sampling, including probabilities that underflow floating point. Weighted
node2vec applies return/outward bias against the previous-to-candidate arc.
The native GPU profile supports uniform and weighted walks with float64
probabilities. It rejects underflowing positive weights and oversized dense
walk allocations. Node2vec requests use C++ in automatic mode; explicit GPU
requests fail instead of changing the model. Seeds and the generator are
recorded; CPU and GPU random streams are not required to match.

Neighborhood sampling is a native CPU profile over original edge instances.
It supports replacement, exact weighted draws, repeated seed batches,
per-edge-type fanouts and inclusive temporal cutoffs. Fanout `-1` includes
all eligible edges, including zero-weight edges; finite weighted draws require
positive mass. Integer epoch seconds and timezone-aware RFC 3339 timestamps
are compared exactly, including fractional seconds and timezone offsets.
The frontier contains distinct vertices per hop and seed batch. Sample ports
describe the requested sample rather than an exhaustive graph traversal.

Induced and ego extraction preserve vertex/edge IDs, direction, parallel edge
instances and nested properties. Empty optional attribute maps are omitted.
Incoming, outgoing and undirected discovery affect ego membership; the returned
graph retains the original direction and records. Each graph port has its own
fingerprint plus the original input fingerprint, so it can feed another native
operation without losing lineage. Explicit induced selection uses CPU; GPU ego
discovery uses native libcugraph BFS followed by native record materialization.

Independent checks cover all undirected graphs through five vertices for
independence/coloring, exhaustive small directed and undirected selections,
edge-instance sampling, empirical seeded probabilities and exact timestamp
boundaries. Larger path/isolate fixtures cross GPU block boundaries and check
output budgets and deadlines. The Python family methods and standalone CLI use
the same native catalog, preserve typed IDs and restore the caller's GPU device.
Acceptance reports for this checkpoint are in `validation/native_selection`.


## Native mining contracts and verification

The clique algorithms use an undirected simple projection: loops and repeated
edges are discarded, weights are ignored and external ID types are preserved.
CPU search uses an iterative, budgeted Bron–Kerbosch implementation and bounded
fixed-size enumeration. A capped maximal-clique list is marked incomplete;
fixed-size count-only results expose a complete count and an incomplete group
port. Maximum-clique ties are materialized in C++ when requested. A GPU maximum
witness must match a native coloring upper bound or a bounded exact search.
Independent sets and vertex covers use the same exact complement reduction;
cover decision mode requires a nonnegative integer threshold.

CPU clique order has no fixed upper bound. Original GPU count ranges are
GraphSet 3–6, GAMMA 3–7 and KCGPU 3–10; orders larger than the vertex count
return zero without launching a kernel. GPU count admission requires a
conservative forward-subset bound that fits uint64. KCGPU additionally requires
oriented degree at most 1000. Unsupported GPU variants have an explicit error;
auto selection can choose a supported GPU backend or native CPU. Candidate,
output and deadline budgets cover CPU search and native admission. Original
kernel entry points are serialized because some retain process-global state.
Hard interruption and GPU memory admission still belong to the pending worker
and scheduler integration.

KCGPU's generated headers repair an unused out-of-bounds diagnostic counter,
the terminal search-depth slot and Pascal-table depth. GAMMA's generated
headers repair its prefix-neighbor comparison and warp synchronization. Its
adapter prepares eligible roots from native CSR degrees; the redundant
Thrust root filter failed after GraphSet in a shared host process. An explicit
regression alternates both backends and both GPU orders.
Embedded original backends suppress normal console diagnostics; their
standalone artifact behavior is retained. Native libcugraph core decomposition
uses outgoing degree on the symmetric graph, avoiding double-counted cores.
Catalog strings and implementation hashes have per-library storage so CPU
and GPU builds loaded together cannot share the wrong provenance.

The mining checkpoint reports live in `validation/native_mining`. They retain the failed
binding comparison that exposed the provenance defect and the corrected
acceptance run. The matrix checks exhaustive subsets on all five-vertex CPU
graphs and four-vertex GPU graphs, larger complete/random fixtures, typed IDs,
loops, duplicate edges, caps, ties, malformed parameters and resource limits.
Depth/storage and race checks are separate from graph-oracle counts. The audit
requires an exact index match for the isolated root build script while keeping
unrelated pre-existing working changes outside this checkpoint.

```sh
python tools/validate_native_runtime.py --cpu-build build/native-cpu \
  --gpu-build build/original-with-rapids/runtime --output validation/native_mining
python tools/validate_native_consumers.py --cpu-build build/native-cpu \
  --prefix /tmp/graphmine-install --consumer-build /tmp/graphmine-consumer \
  --output validation/native_mining/installed-consumers.json
python tools/validate_native_mining_depth.py --gpu-build build/original-with-rapids/runtime \
  --output validation/native_mining/depth-sanitizers
```

Standalone C and C++ examples execute core decomposition and maximum
clique. Their verification removes
Python from PATH and hides CUDA. The native Python binding obtains the same
operations and family assignments from the shared catalog; the application algorithm worker
and the broader reference API still require migration.

The completed mining checkpoint contains **83,624 passing native requests**:
45,872 on CPU and 18,876 on each GPU. Eight additional depth/admission checks
pass, including K514 triangle counts under CUDA memcheck and K12 seven-clique
counts under racecheck on both devices, with zero reported errors or hazards.
The binding suite has 88 passes, native cuDF construction has 64, and working
and staged app acceptance has 41 and 25 respectively. No acceptance checks are
skipped. The two app runs retain an existing Starlette deprecation warning.


## Native structure and centrality contracts

Biconnected decomposition returns edge blocks, corresponding vertex groups,
bridges, articulation vertices and isolated vertices. Its iterative Tarjan
traversal handles deep graphs without recursive stack growth. Truss
decomposition returns every edge's largest k under the k-2 triangle-support
convention, the maximum truss number (zero when empty), and an optional selected
k-truss. Both operations require undirected input, discard loops, collapse
parallel edges and ignore weights. Each normalized edge uses its first original
ID and retains all collapsed source edge IDs. These outputs and their family
assignments are identical through C++, the CLI and Python.

Degree centrality supports incoming, outgoing, both and undirected projection;
normalization divides by n-1 when n>1. Betweenness excludes endpoints and scores
every source. Its C++ implementation uses unbounded integer path counts and
exact rational dependencies/distances over the admitted binary64 lengths.
Weighted paths require strictly positive lengths and minimum parallel weights.
Exact fractions accompany display scores. PageRank, degree and betweenness
return their score definitions and full ranked vertices, with numeric IDs
before string IDs and ascending stored values as the tie break. Remaining
centrality measures and contract variants are still pending.

Direct libcugraph betweenness handles directed or undirected unweighted graphs.
Original TurboBC handles undirected unweighted graphs and uses float32
accumulation. Both are numerical profiles. Normalized and raw scores follow
the same conventions as C++; a three-vertex path has raw center score one and
normalized center score one. GPU work is admitted before native execution.

The linked GPU profiles cannot safely count more than INT32_MAX shortest
paths. Bounded native BFS checks larger inputs before dispatch. Explicit GPU
requests outside this limit fail; automatic selection records the reason for
using exact C++. A reproduced 66-vertex layered graph returned a raw-score sum
of 21,609 from libcugraph where the exact pair-distance identity requires
21,857. Its request, results and pre-admission binary hashes are retained in
`validation/native_structure/known-failures`; the current admission rule
excludes that failure. This is a path-count limit, not a vertex-count limit.


The structure/centrality checkpoint reports in `validation/native_structure`
contain **125,924 passing native requests**: 68,344 CPU and 28,790 per GPU.
This includes the earlier BFS, triangle, path, forest, ranking, similarity
and original mining regressions. New structure checks use exhaustive edge
subsets on all five-vertex graphs; centrality checks independently enumerate
simple paths and verify exact shortest-path fractions. Larger cases include
a 20,000-vertex path, a 64-vertex complete graph and layered graphs whose
shortest-path counts exceed fixed-width integer capacity.

Eight original mining depth/admission checks and eight centrality sanitizer
runs pass on both GPUs. The latter cover libcugraph and TurboBC with memcheck
and initcheck, each running nine boundary requests, with zero reported errors.
There are also 104 binding/CLI checks, 64 cuDF/construction checks, 41 working-app
and 25 staged-app acceptance checks, with no failures or skips. Installed
C/C++ consumers run with Python off PATH and CUDA hidden. The audit verifies
43 CPU source files, 1,023 GPU source files, seven binaries per build and
32 resolved native dependencies. All GPU build sources match the Git index;
unrelated working changes remain outside this checkpoint.

```sh
python tools/validate_native_runtime.py --cpu-build build/native-cpu \
  --gpu-build build/original-with-rapids/runtime --output validation/native_structure
python tools/validate_native_centrality_sanitizers.py \
  --gpu-build build/original-with-rapids/runtime \
  --output validation/native_structure/centrality-sanitizers
```

The remaining 52 formal problems, unfinished variants within migrated
problems, and the application algorithm worker still require native migration.
This checkpoint does not close the review-integration goal.

## Native matching and flow profiles

`weighted-matching` computes an exact maximum-weight matching with native Boost
weighted Blossom. It requires an undirected graph and nonnegative explicit
weights, removes loops, and retains the largest parallel edge with its original
ID. No cardinality constraint is implied; zero-weight pairs may be omitted.
Component-local power-of-two scaling preserves admitted binary64 weights in
checked 4096-bit integer arithmetic. A cubic admission bound limits Blossom
work before its call; hard interruption of an in-process CPU solver remains
part of the application-worker migration.

`bipartite-matching` requires `attributes.side` equal to `left` or `right` on
every vertex, including isolates. C++ supports maximum cardinality, maximum
weight and minimum cost, with optional coverage of the smaller side. Weighted
objectives require explicit weights and use exact rational residual costs.
Without required coverage, an empty matching can be optimal. Infeasible
coverage is explicitly certified and produces no edge witness port.

`max-flow-min-cut` sums parallel capacities exactly, removes loops and expands
undirected edges into two directed capacity arcs. Iterative Dinic avoids host
stack growth on long paths. Exact flow assignments retain original edge IDs;
undirected assignments also identify their orientation. Optional vertex limits
are encoded as `[{"vertex": 0, "capacity": 2}, ...]`, preserving typed IDs.
Explicit terminal limits apply too. Splitting vertices makes the returned cut
certificate include both `min_cut_edges` and `min_cut_vertices`; their combined
capacity equals the flow value. Source-side membership refers to reachability
of the input copy, and `split_source_side` exposes both copies. The authoritative
formal contract and its four embedded copies define this mixed-cut convention.

Enable `GRAPHMINE_NATIVE_OPTIMIZATION=ON` to build two original CUDA workers:

- `ecl-maxflow`: integral normalized capacities whose total is at most 1e9;
  at most one million vertices and ten million input edges; no vertex limits.
  C++ checks capacity, conservation, residual reachability and exact cut equality.
- `hungarian-cuda`: minimum-cost perfect assignment on a complete square
  bipartite graph, at most 64 vertices per side, every input cost integral in
  `[0,999]`. C++ checks its permutation and independently verifies the optimum.

The pinned upstream source adapters are prepared by Python at build time. Both
workers and the shared core execute entirely in C++/CUDA. Worker processes have
precise deadlines, bounded output, and are killed and reaped on timeout. Their
failure is returned explicitly; automatic routing never hides a failed GPU run
by recomputing its result. Unsupported variants can select CPU before execution.
Workers install in `libexec/graphmine` and are located from the installed CLI or
shared library, including calls made through the Python wrapper.

The optimization checkpoint reports in `validation/native_optimization` contain
**167,891 passing native requests**: 106,671 CPU and 30,610 per GPU. The new CPU
matching checks total 12,740; flow checks total 25,587. On each GPU, assignment
has 751 checks and flow has 1,069. Independent oracles enumerate matching
subsets and split-network cuts, checking original edge identities, feasibility,
exact objectives, residual certificates and all declared variants. Larger
cases include 20,000-vertex flow paths and 64-by-64 assignment matrices.

Sixteen direct-worker memcheck/initcheck cases pass, alongside the previous
8 centrality sanitizer and 8 original mining depth/admission checks. The
20,000-vertex flow path passes normally but times out under instrumentation at
the default 60-second deadline; its failed instrumented report is retained
under `known-failures`, separately from successful kernel checks. Successful
kernel checks cover 256-vertex residual networks, total capacity 1e9 and
64-by-64 assignment cost boundaries.

There are also 117 wrapper/CLI checks, 64 cuDF construction checks, 41
working-app and 25 staged-app checks, with no acceptance failures or skips.
Installed native C/C++ consumers and installed CUDA CLI/worker execution do not
require Python on PATH. Installed wrapper/CLI parity passes on both GPUs.
The audit verifies 49 CPU source files, 1,060 GPU source files, nine CPU and
eleven GPU binaries, generated worker sources and 32 linked dependencies.
All GPU source hashes match the exact Git index.

```sh
python tools/validate_native_runtime.py --cpu-build build/native-cpu \
  --gpu-build build/original-with-rapids/runtime --output validation/native_optimization
python tools/validate_native_optimization_sanitizers.py \
  --gpu-build build/original-with-rapids/runtime \
  --output validation/native_optimization/optimization-sanitizers
python tools/validate_native_optimization_install.py \
  --gpu-build build/original-with-rapids/runtime --prefix /tmp/native-gpu-install \
  --output validation/native_optimization/installed-optimization.json
```

Native coverage for the remaining 49 formal problems, unfinished variants of
migrated problems, the application algorithm worker and the outstanding review
requirements remain open. Tabular ingestion uses native cuDF, and browser
visualizations use Cytoscape.
