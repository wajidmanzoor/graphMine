# GraphMine library

GraphMine is a C++17/CUDA library interface for every implementation that
passed this repository's GPU correctness validation. Applications provide one
canonical `graphmine::Graph`; dense IDs, CSR variants, temporal incidence
indexes, and artifact-specific representations stay inside backend adapters.

Every problem class follows the same high-level shape:

- construct an options object, including a backend choice when several passed;
- construct the algorithm object;
- call `supports(graph)` when capability discovery is useful;
- call `run(...)` and inspect the typed `ExecutionResult`;
- request nonessential materialization through typed output flags.

An explicitly selected unavailable or incompatible backend returns a precise
status. It never silently substitutes a different algorithm.

## Components

| Public class | Validated selectable backends |
|---|---|
| `MaximalCliques` | mce-gpu, G2-AIMD, RDMCE |
| `MaximumClique` | CUDA-MS, GPUMaximumClique, Maximum-Clique-on-GPU |
| `KCore` | KCoreGPU |
| `TriangleCounting` | ToT, WeTriC |
| `DynamicTriangleCounting` | EDTC |
| `KCliques` | KCGPU, GraphSet, GAMMA |
| `BetweennessCentrality` | TurboBC |
| `MaximalBicliques` | cuMBE |
| `QuasiCliques` | cuQC |
| `SubgraphIsomorphism` | gMatch |
| `GraphMotifs` | GraphMiner/G2Miner, GraphSet, DuMato |
| `TemporalMotifMining` | Everest, Mayura |
| `CommunityDetection` | gLeiden, parallel Louvain, parallel Leiden, parallel Leiden+ |

The GPU artifact supplies each required count, score, clique, partition, or
core result. When an artifact is count-only, optional instances are
materialized by a common exact collector and checked against the GPU total.
Results include backend/source provenance, timings, normalization warnings,
and restored external vertex and edge IDs.

Temporal mining currently exposes the exact query that passed validation:
`A->B`, then `B->C`, then `A->C`, with distinct vertices and an inclusive time
window. Integer timestamps live in `EdgeRecord::timestamp`; directed parallel
events are preserved and stably ordered. Community detection currently exposes
the validated unweighted modularity paths.

## Build once and run queries without recompiling

The default build now produces one `graphmine` executable containing every
enabled component. Compile it once, then select the operation and validated
backend with arguments for each query:

```bash
cmake -S library -B library/build -DCMAKE_BUILD_TYPE=Release \
  -DGRAPHMINE_BUILD_CLI=ON
cmake --build library/build --parallel --target graphmine_cli

library/build/graphmine list --pretty
library/build/graphmine validate \
  --graph library/examples/data/triangle.json --pretty
library/build/graphmine run triangle-counting \
  --graph library/examples/data/triangle.json \
  --backend tot \
  --list-instances \
  --include-per-vertex-counts \
  --pretty
```

`graphmine list` reports all 13 operations and whether each of the 26
validated backend choices is compiled in the current binary. `graphmine
describe OPERATION --pretty` reports the exact invocation. All graph, query,
and motif files use `canonical_edge_list_v1`; results are JSON. Optional
result fields are requested with explicit flags, so large materializations are
not produced accidentally.

The compact runtime contract is
[`manifests/graphmine_manifest.json`](manifests/graphmine_manifest.json). It
contains the 12 supported problem specifications, canonical input contract,
auxiliary-input formats, every backend choice, parameters, output flags,
required outputs, and ready-to-run commands. Static and dynamic triangle
counting are separate operations within the same research problem.

For problem identification and query planning, use the richer
[`manifests/graphmine_catalog.json`](manifests/graphmine_catalog.json). It
embeds all 20 authoritative `problems/*/problem.json` contracts exactly and
links the 12 supported problems to C++ types, CLI arguments, backend
capabilities, source provenance, and passing validation evidence. Unsupported
problems are explicitly marked `no_validated_backend` rather than being routed
to a superficially similar operation.

This removes compilation from the user-query path. Each CLI invocation still
starts a process and initializes the selected GPU runtime. If query volume
later makes that startup cost important, the same dispatcher can be hosted in
a long-lived service without changing the manifest or library APIs.

## Build and test

```bash
cmake -S library -B library/build -DCMAKE_BUILD_TYPE=Release
cmake --build library/build -j
ctest --test-dir library/build --output-on-failure
```

The parallel Louvain/Leiden family additionally needs a CUDA-enabled Kokkos
and KokkosKernels installation. Point CMake at its prefix when it is not in a
standard location:

```bash
cmake -S library -B library/build \
  -DCMAKE_PREFIX_PATH=/path/to/kokkos/install
```

If that optional dependency is absent, GraphMine still builds the rest of the
library and marks those three backend choices unavailable. Each backend also
has a `GRAPHMINE_ENABLE_*` CMake option for selective builds. Use
`-DGRAPHMINE_ENABLE_CUDA_BACKENDS=OFF` for a portable core-only build.
Set `-DGRAPHMINE_BUILD_CLI=OFF` only when the install should contain library
targets without the precompiled command-line runner. Building the runner
requires Boost.JSON headers; Boost.JSON is compiled into the executable and is
not an additional runtime library dependency.

## Use one component

```cpp
#include <graphmine/graph.hpp>
#include <graphmine/problems/maximal_cliques.hpp>

auto graph = graphmine::Graph::from_edges(
    "sample", {0, 1, 2, 3}, {{0, 1}, {0, 2}, {1, 2}, {2, 3}});

graphmine::MaximalCliqueOptions options;
options.backend = graphmine::MaximalCliqueBackend::g2_aimd;
options.minimum_clique_size = 2;
options.optional_outputs =
    graphmine::MaximalCliqueOptionalOutput::total_count;

graphmine::MaximalCliques algorithm(options);
auto result = algorithm.run(graph);
if (!result.ok()) {
  // result.status().code() and result.status().message()
}
```

For an installed package, request and link only the component needed:

```cmake
find_package(GraphMine 0.1 REQUIRED COMPONENTS maximal_cliques)
target_link_libraries(my_program PRIVATE GraphMine::maximal_cliques)
```

See `MIGRATION_STATUS.md` for the preserved artifact boundary and verification
status.

## Function-level source reference

The generated [library code reference](../docs/reference/library/) documents
every public class and method, internal C++ helper, backend adapter, CUDA
translation unit, example, and test with symbol and annotated-source indexes.
The adjacent [research artifact portal](../docs/reference/research/) provides
separate low-level references for the original implementations, so symbols
reused by different papers do not collide. Rebuild both with:

```bash
node tools/build_code_docs.mjs
```
