# Repaired algorithms in the library and agent

Nine repaired implementations are integrated: seven prepared worker executables
and the two existing maximum-clique adapters. The public contract now has **24
operations, 22 supported problem families, and 38 backend choices**. Availability
still depends on the compiled library and installed workers. The other 15 of the
37 cataloged families remain unavailable.

| Operation | Backend | Executable profile |
|---|---|---|
| `k-truss` | `acctd` | Exact full truss numbers for normalized undirected edges and their maximum. Unweighted input; loops removed; duplicates collapsed. |
| `densest-subgraph` | `cds` | Exact unweighted edge density `|E(S)| / |S|`, with a vertex witness, on nonempty undirected input. This is the repaired `k=2` path, without a fixed size or higher-order objective. |
| `maximal-biclique-counting` | `mbe-gpu` | Exact number of nonempty maximal bicliques. Every vertex declares `attributes.side` as `left` or `right`. Scheduled single-GPU variant; no membership listing, size filters, or bitmap variant. |
| `maximum-clique` | `cuda-ms`, `maximum-clique-on-gpu` | Exact single maximum-clique witness with original vertex IDs and `optimal=true`. Does not enumerate all tied optima. |
| `personalized-pagerank` | `kpar` | Approximate outgoing unweighted directed PPR from one explicit seed, with restart probability **0.2**. Dangling mass returns to that seed. No certified per-run error bound. |
| `butterfly-counting` | `gamma-butterfly` | Exact global butterfly count on declared bipartite undirected input, from injective C4 embeddings divided by eight. No participation counts or core decomposition. |
| `group-steiner-tree` | `gpu4gst` | Exact undirected minimum-cost tree meeting 1–16 nonempty groups, with a checked tree witness. Nonnegative integer costs; no hop constraint. Infeasibility is an explicit result. |
| `influence-maximization` | `superfuser` | Approximate independent-cascade seed selection using explicit edge probabilities. Spread is estimated on independent holdout samples; `guarantee_met=false`. No linear-threshold model or certified approximation ratio. |

The count-only biclique operation is separate from `maximal-bicliques`, whose
cuMBE backend returns biclique memberships. Neither operation is silently
substituted for the other. The earlier GraphMiner butterfly backend remains
available alongside GAMMA.

## Build and install

The seven workers are prepared once from pinned upstream objects plus the
published repair patches. Newly added upstream code and worker binaries are not
committed. Source provenance and licensing records are in
[THIRD_PARTY.md](../../THIRD_PARTY.md) and
[catalog/artifact_sources.json](../../catalog/artifact_sources.json).

The tested environment is Linux, Python 3.12, CUDA 12.8, and an RTX 6000 Ada
(SM89). Builders need Git, `patch`, CMake, a C++17 compiler, OpenMP, Boost headers
(including JSON), and the TBB development package used by the relevant upstream
builders. Other architectures have not been validated.

```bash
# Physical GPU 1 was used for validation. Choose your available GPU explicitly.
python3 library/tools/prepare_repaired_workers.py --fetch --gpu 1 --arch 89
CUDA_VISIBLE_DEVICES=1 cmake -S library -B library/build \
  -DCMAKE_BUILD_TYPE=Release -DGRAPHMINE_BUILD_CLI=ON
cmake --build library/build --parallel
CUDA_VISIBLE_DEVICES=1 library/build/graphmine list --pretty
cmake --install library/build --prefix /your/install/prefix
```

If pinned checkouts are already available, replace `--fetch` with
`--source-root /path/to/problems`. `--backend NAME` can select individual workers.
The preparation script verifies source/patch hashes, keeps build logs and binary
hashes in the ignored `library/repaired-workers/`, and reuses matching builds.
With a custom `--output`, configure CMake's `GRAPHMINE_REPAIRED_WORKER_DIR` to that
directory. Run preparation **before** CMake configuration so workers are copied
into the build and install rules.

Installed workers live in `libexec/graphmine`. The CLI locates them relative to
its executable; arbitrary C++ applications can set `GRAPHMINE_WORKER_DIR` or the
options object's `worker_directory`. Missing workers yield `backend_unavailable`.
A CUDA-disabled build exposes the same headers but no executable GPU capability.
`GRAPHMINE_ENABLE_REPAIRED_WORKERS=OFF` disables the seven workers.

Worker calls accept one logical CUDA device, respect `CUDA_VISIBLE_DEVICES`, use
private temporary files, and impose time/output limits. The agent owns the worker
path and timeout, and cancels the entire job process group. No query compiles code.

## C++ API

The six new problem classes share the `GraphMine::repaired_algorithms` component.
`ButterflyCounting` remains in `GraphMine::validated_expansion`; maximum clique
remains in `GraphMine::maximum_clique`.

```cmake
find_package(GraphMine 1 REQUIRED COMPONENTS repaired_algorithms)
target_link_libraries(my_application PRIVATE GraphMine::repaired_algorithms)
```

```cpp
#include <graphmine/problems/repaired_algorithms.hpp>

auto graph = graphmine::Graph::from_edges(
    "triangle", {0, "0", -3}, {{0, "0"}, {"0", -3}, {-3, 0}});
graphmine::KTruss algorithm;
auto result = algorithm.run(graph);
if (!result.ok()) {
  // Inspect result.status(); unavailable and invalid inputs fail explicitly.
} else {
  for (const auto& edge : result.value().truss_number_by_edge) {
    // edge.edge is an original external edge ID; edge.truss_number is exact.
  }
}
```

The remaining classes are `DensestSubgraph`, `MaximalBicliqueCounting`,
`PersonalizedPageRank`, `GroupSteinerTree`, and `InfluenceMaximization`, with
matching `*Options` types. PPR options require `seed_vertex`; set `top_k` to the
desired limit. Its restart probability is fixed by this profile, not configurable
in C++. Tree options require `groups` as `vector<vector<ExternalId>>`. Influence
options set `seed_set_size`, `sample_count`, and `random_seed`.

Use `ButterflyOptions.backend = "gamma-butterfly"` for GAMMA. The C++ and installed
package tests in [library/tests](../tests/) exercise every new class and that
dispatch path.

## CLI and JSON parameters

All inputs use `canonical_edge_list_v1`. Examples below assume a suitable
`graph.json`; `describe OPERATION --pretty` lists the native contract.

```bash
CUDA_VISIBLE_DEVICES=1 library/build/graphmine run k-truss --graph graph.json
CUDA_VISIBLE_DEVICES=1 library/build/graphmine run densest-subgraph --graph graph.json
CUDA_VISIBLE_DEVICES=1 library/build/graphmine run maximal-biclique-counting --graph bipartite.json
CUDA_VISIBLE_DEVICES=1 library/build/graphmine run butterfly-counting \
  --graph bipartite.json --backend gamma-butterfly
CUDA_VISIBLE_DEVICES=1 library/build/graphmine run personalized-pagerank \
  --graph directed.json --seed-vertex '"0"' --top-k 10 --restart-probability 0.2
CUDA_VISIBLE_DEVICES=1 library/build/graphmine run group-steiner-tree \
  --graph weighted.json --groups '[[0,"0"],[-3]]'
CUDA_VISIBLE_DEVICES=1 library/build/graphmine run influence-maximization \
  --graph probabilities.json --diffusion-model independent_cascade \
  --seed-set-size 2 --sample-count 256 --random-seed 42
```

Integer `0` and string `"0"` remain different IDs. CLI seeds and groups are JSON
values; quote them for the shell as shown. Native results always restore the
original typed vertex/edge IDs. Truss duplicates select the smallest typed edge
ID. Tree duplicates select the cheapest edge, with the smallest typed ID breaking
equal-cost ties. Tree witnesses are checked for input-edge membership, cost,
acyclicity, connectivity, and coverage of every group.

General worker limits are one million vertices and ten million input edges;
these are input safety limits, not claims of practical runtime at those sizes.
PPR `epsilon` must be 0.01–0.5 and `random_seed` at most `INT_MAX`; its measured
test tolerance is not a certified output bound. Tree weights must be integers in
`[0, 2^53-1]`, with the implementation's conservative total-cost bound below
`2^58`. Influence probabilities must lie in `[0,1]`, the seed budget in `[1,n]`,
and samples in `[32,65536]` in multiples of 32. AccTD, CDS, MBE-GPU, kPAR and GAMMA reject
nonunit weights rather than using them as costs.

## Agent integration

[program_instructions.json](../../agent/program_instructions.json) allowlists
the parameters, backend names, and required outputs. For example, a plan's
`parameters` can contain:

```json
{"groups": [[0, "0"], [-3]]}
```

The API, exported schemas, constrained planner schema, and command builder all
preserve these nested typed IDs. Seed/group members must still exist after graph
filtering. For tree costs or influence probabilities, a selected
`application_intent.weight_attribute` is mapped into the execution copy's
`weight` field after filtering. The uploaded graph is unchanged. Missing,
fractional tree costs and invalid probabilities are rejected.

The regenerated [catalog](../../graphmine_catalog.json), [manifest](../../graphmine_manifest.json),
and [repair profiles](../../catalog/repaired_profiles.json) use routing contract
`repaired-37-v2`. Expanded routing uses the base model; the frozen legacy routing
adapter is unchanged. There was no new training or measurement of natural-language
routing accuracy. Current maximum-clique selection permits both repaired backends,
keeps GPUMaximumClique as the agent default, and discards their pre-repair timing
rankings. No new performance ranking is claimed.

Answers distinguish counts from enumerations, approximate PPR from exact results,
estimated influence spread from guarantees, and an infeasible tree from a
zero-cost solution. Tree network views contain only the returned tree edges.
Truss edge labels are available in the raw native result and answer `edge_rows`.

## Evidence and remaining scope

See [the integration report](../../validation/repaired_library/REPORT.md) for
commands, numerical tests, API tests, CUDA memory checks, and packaging results.
Standalone repairs and historical failures are retained in
[validation/algorithm_repairs](../../validation/algorithm_repairs/README.md).
These checks validate the stated profiles on tested inputs; they do not establish
unlimited scale, multi-GPU execution, or other research modes. Other unresolved
implementations and the six excluded builds were not promoted.
