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
The catalog marks profiles still awaiting migration as `pending`.

## Current migration boundary

The shared runtime has native profiles for ten formal problems. All ten have C++ CPU
implementations. GPU dispatch calls native libraries directly:

| Operation | Family | GPU implementation |
| --- | --- | --- |
| Breadth-first search | traversal | libcugraph |
| Single-source shortest paths | traversal | libcugraph, bounded float64 costs |
| Many-source shortest paths | traversal | libcugraph, bounded float64 costs |
| Topological sort | traversal | CPU profile |
| Spanning tree/forest | trees | libcugraph, minimum and maximum |
| Connected components | connectivity | libcugraph, weak and strong |
| PageRank | centrality | libcugraph |
| Personalized PageRank | centrality | libcugraph; custom uniform dangling redistribution uses CPU |
| Local link prediction | similarity | libcugraph Jaccard; eight CPU measures |
| Triangle counting/listing | motifs | Original ToT and WeTriC CUDA backends |

The original `Graph` and typed external IDs are reused. Existing native APIs
remain available while their remaining profiles are brought into the shared
runtime. Original triangle backends are included when building from the
`library` project with their corresponding options enabled.

`graphmine.native.NativeLibrary` is the thin Python binding. Its family methods
are obtained from the native catalog. It does not import NetworkX, cuGraph,
cuDF, NumPy or a Python algorithm module. The existing `graphmine.run` API and
application worker still use the earlier reference implementation and are
awaiting migration; this checkpoint does not claim native coverage of all
73 previously executable Python profiles or all 70 formal contracts.

YiGraph's reviewed CPU integrations wrap NetworkX/PyG. Their capabilities need
native implementations; importing those Python routines inside a C++ facade
would not satisfy this architecture. The existing independently checked Python
implementations remain useful as migration references and test oracles.

## Building and calling the core

A CPU-only build needs a C++17 compiler, Boost.JSON headers, OpenSSL and CMake.
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

## Validation at this checkpoint

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

To reproduce the native matrix after building both configurations:

```sh
python tools/validate_native_runtime.py --cpu-build build/native-cpu \
  --gpu-build build/original-with-rapids/runtime --output validation/native_reference
```

The GPU build must include libcugraph, libcudf, ToT and WeTriC, with both physical
devices visible. The runner records source-bound implementation hashes,
immutable binary snapshots and per-suite logs; an external watchdog bounds
each oracle process.

`tools/audit_native_runtime.py` verifies these reports, the source inventory
embedded in each build, current source contents and the binding test snapshot.
It records binary and resolved dependency hashes in
`catalog/native_runtime_coverage.json`. This is migration evidence for the ten
integrated problems and their listed profiles; it does not establish coverage of pending profiles or
replace the application's evidence gate.
