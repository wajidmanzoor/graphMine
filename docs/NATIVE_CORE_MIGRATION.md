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

The new runtime implements native CPU breadth-first search and triangle
counting. BFS can dispatch directly to `libcugraph` through its native API.
When built from the original library tree, triangle counting also uses the
existing ToT and WeTriC CUDA implementations. The original `Graph` and typed
external IDs are reused. Existing native APIs remain available while their
remaining profiles are brought into the shared runtime.

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
unavailable. `auto` may choose a compiled GPU profile or the native CPU
implementation. A failed GPU computation is reported; requested parameters
are not altered to manufacture success. Backend selection and validation occur
in C++, including for Python calls.

## cuDF ingestion and visualization

The native `read_csv` request and binding method call libcudf. Declare every
column name; the reader rejects missing or unexpected columns and returns text
for every field. Leading zeroes, large integer strings, quoted delimiters,
multiline strings, Unicode and literal `NA` survive parsing. Numeric IDs and
weights require an explicit subsequent schema conversion. The reader preserves
cuDF's unique header names and checks them against the declared set.

```python
table = library.read_csv(
    "transactions.csv", columns=["source", "target", "amount"], gpu_device=0
)
```

The standalone equivalent is `graphmine-native read-csv transactions.csv
--columns column-names.json`, where the names file contains a JSON array.
The current ingestion profile limits files to 64 MiB and returned tables to
100,000 rows by default. Exceeding the row bound fails; it does not return an
apparently complete truncated table. cuDF ingestion requires a GPU and a
libcudf-enabled build. Once a graph has been constructed, the native CPU
algorithms can run without a GPU. Canonical graph JSON remains a native JSON
input format rather than being misinterpreted as a tabular file.

The web upload endpoint has not yet been switched to this reader. Multi-table
joins, graph projection and wider format support remain migration work.
Rendering stays in Cytoscape and predefined browser charts/tables; NetworkX
does not render this workspace.

## Contracts and remaining work

The initial profiles preserve string versus signed 64-bit integer IDs, including
integers above JavaScript's safe range. Unsupported larger integers and integer
weights that the original native `Graph` cannot represent exactly are rejected.
Extending native numeric storage is required before porting the exact rational
query and graph-comparison profiles; silently narrowing them is unacceptable.

BFS preserves direction, ignores weights, drops loops and collapses parallel
arcs. Its independent and nearest-source modes share exact hop distances;
nearest-source ties use the supplied source order. Triangle counting requires
explicit undirected input and uses the corresponding simple graph. Capped
triangle membership is incomplete even though its total count remains exact.
GPU triangle enumeration materializes and checks memberships in native CPU
code. Budgets bound CPU search, output and BFS working-state size; timeouts on
uninterruptible native GPU calls require the isolated worker boundary.

Before completing the user goal, migrate the remaining algorithms and native
backends, extend exact numeric types, connect the application's validated worker
and uploads to this core, and replace the reference evidence inventory with a
source/binary/dependency-aware native gate. Complete the remaining review
requirements in `VERIFIED_ANALYTICS_IMPLEMENTATION.md`, including the seven
previously missing formal problems, table projections, routing/evaluation,
recovery, MCP, reviewed examples, scheduling and representation caching.

## Validation at this checkpoint

`validation/native_runtime` records 19,981 successful native requests: 13
contract cases, 4,608 BFS requests on each of CPU/GPU 0/GPU 1, and 2,048 triangle
requests on each of native CPU/ToT GPU 0/WeTriC GPU 1. The C++ oracles use
independent shortest-path matrices and exhaustive vertex triples. A further
19 tests cover the Python/C boundary, catalog parity, concurrent calls,
libcudf text ingestion on both GPUs, CLI JSON output and CUDA device restoration.
Installed C and C++ consumers were also checked without Python on PATH.

`tools/audit_native_runtime.py` verifies these reports, the source inventory
embedded in each build, current source contents and the binding test snapshot.
It records binary and resolved dependency hashes in
`catalog/native_runtime_coverage.json`. This is migration evidence for the two
implemented problems; it does not establish coverage of pending profiles or
replace the application's evidence gate.
