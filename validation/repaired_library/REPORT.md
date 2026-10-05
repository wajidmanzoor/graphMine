# Repaired algorithms: library and agent integration — 2026-10-05

All nine repaired implementations are exposed through their tested executable
profiles. There are now **24 operations, 22 supported families, and 38 backend
choices**, while all 37 formal problem definitions remain in the catalog.
The [API guide](../../library/docs/repaired_algorithms.md) specifies each profile,
normalization, parameters, outputs, build dependencies and limits.

| Backend | Public operation | Integration |
|---|---|---|
| AccTD | `k-truss` | Full edge truss numbers with original edge IDs |
| CDS | `densest-subgraph` | Exact unweighted edge-density objective and vertex witness |
| MBE-GPU | `maximal-biclique-counting` | Complete count; separate from cuMBE membership enumeration |
| CUDA-MS | `maximum-clique` | Repaired exact completion and clique witness |
| Maximum-Clique-on-GPU | `maximum-clique` | Repaired solver, graph reduction, synchronization and witness |
| kPAR | `personalized-pagerank` | Approximate single-seed outgoing PPR, restart probability 0.2 |
| GAMMA butterfly | `butterfly-counting` | Exact declared-bipartite C4 count, divided by eight |
| GPU4GST / TrimCDP-WB | `group-steiner-tree` | Exact tree, cost and group-coverage certificate; explicit infeasibility |
| SuperFuser | `influence-maximization` | Independent-cascade seed selection and holdout spread; no quality guarantee |

Seven prepared workers are built from pinned external source objects and the
[standalone repair patches](../algorithm_repairs/README.md). The two clique
adapters remain linked into GraphMine. Native facades normalize canonical input,
preserve typed external IDs, check certificates, and reject unsupported modes.
The numerical algorithm runs on the GPU; independent CPU solvers are test oracles.

## Verification

| Check | Result | Evidence |
|---|---|---|
| Independent public CLI oracle suite | **372/372**, including 21 invalid-input checks | [summary](results/native-summary.json), [full records](results/native-full.json.gz) |
| CUDA memcheck through the public CLI and its children | **9/9**, one per repaired backend | [summary](results/memcheck-summary.json), [records](results/native-memcheck.json.gz) |
| Agent contract, planner, API, execution and answer regressions | **387/387**, including real API execution of all nine repaired backends | [JUnit](results/agent-tests.xml), [test log](results/agent-tests.log) |
| Original expansion public CLI regression suite | **99/99** | [records](results/expansion-replay.json.gz) |
| Installed CLI oracle replay | **49/49** | [summary](results/installed-summary.json), [records](results/installed-quick.json.gz) |
| Installed external C++ consumers | **Both passed**; includes all seven new worker paths | [build/run evidence](results/package-checks.json) |
| Fresh CUDA-disabled build | **6/6 enabled tests passed**; 17 GPU-dependent tests disabled | [CTest log](results/cpu-ctest.log) |
| Full CUDA-enabled CTest suite | **22/23 passed**; existing gMatch test exhausted available GPU memory | [CTest log](results/native-ctest.log) |
| Regenerated documentation | **539,595 local links checked across 4,548 HTML pages** | [generation log](results/code-docs.log) |

The full native suite is not reported as entirely green: the unchanged gMatch
backend failed with CUDA out-of-memory while GPU 1 had approximately 20,599 MiB
free. Its fixed large memory pools are outside these repairs. The new repaired
C++ test and all nine repaired backend CLI/API paths passed. GPU 0 and other
users' GPU processes were left untouched.

The executable under test has SHA-256
`b18babf302965e4c038faa19f1cd6374149033761a03312077738d76ceb6d508`.
[integration-summary.json](results/integration-summary.json) records build hashes,
worker hashes and contract hashes. Compressed records retain each command,
result and check; [worker logs](results/native-logs.tar.gz) retain native output
and memcheck diagnostics. These integration counts are separate from the larger,
overlapping standalone repair suites and should not be summed as unique graphs.

The oracle suite includes every labeled undirected four-vertex graph for truss,
edge density and both repaired clique solvers, plus larger seeded graphs,
isolates, duplicates, loops, mixed integer/string IDs and 64-bit tree costs.
Oracles use NetworkX truss peeling, exhaustive vertex subsets, a linear-system
PPR solution, group-covering subset/MST search, biclique closed sets,
common-neighbor butterfly counts, and an independent sampled-cascade traversal.
Agent tests additionally cover nested group schemas, selected weight fields,
filtered-out IDs, invalid model/guarantee requests, source preservation and
faithful answers. Infeasible tree results do not become zero-cost solutions;
PPR and influence outputs retain their approximation limitations.

## Reproduce

Build as described in the [guide](../../library/docs/repaired_algorithms.md).
The oracle runner needs Python with NumPy and NetworkX. The earlier expansion
replay also needs SciPy. CUDA validation used only physical GPU 1 on an RTX 6000
Ada with CUDA 12.8; other architectures and multi-GPU modes are not claimed.

```bash
CUDA_VISIBLE_DEVICES=1 python3 validation/repaired_library/validate.py \
  --binary library/build/graphmine --work /tmp/repair-oracles --suite full
CUDA_VISIBLE_DEVICES=1 python3 validation/repaired_library/validate.py \
  --binary library/build/graphmine --work /tmp/repair-memcheck --suite sanitizer
CUDA_VISIBLE_DEVICES=1 ctest --test-dir library/build --output-on-failure

CUDA_VISIBLE_DEVICES=1 \
  GRAPHMINE_REPAIRED_TEST_BINARY="$PWD/library/build/graphmine" \
  GRAPHMINE_EXPANSION_TEST_BINARY="$PWD/library/build/graphmine" \
  .venv/bin/python -m pytest agent/tests -q

python3 tools/update_repair_catalog.py
node tools/build_catalog.mjs
.venv/bin/graphmine-agent export-schemas agent/schemas
node tools/build_code_docs.mjs
```

The installed consumer is `library/tests/install_consumer`. Supply the installed
GraphMine prefix and the same optional dependency prefixes used for its build
(Kokkos/KokkosKernels when the community backend is enabled). Set
`GRAPHMINE_WORKER_DIR` to the installation's `libexec/graphmine` for a consumer
outside its `bin` directory. The installed CLI resolves workers relative to its
own location.

The earlier expansion runner now respects `CUDA_VISIBLE_DEVICES` and accepts
`GRAPHMINE_VALIDATION_ROOT` for isolated replay results. Copy its Hungarian and
GraphMiner butterfly input fixtures and butterfly reference JSON into that root
before running `validation/gpu_correctness_expansion/validate_library.py`; this
preserves the historical audit files.

## Agent policy and remaining scope

The regenerated JSON contracts use `repaired-37-v2`. Both repaired clique backends
are eligible for agent selection. GPUMaximumClique remains the agent default;
the old maximum-clique timing rankings were retired. The original benchmark
policy is frozen at [v1-backend-policy.json](../../benchmarks/reports/v1-backend-policy.json),
with its original report hash still verified. No new performance ranking,
natural-language routing accuracy, model training or deployment is claimed.
Restart existing agent processes after installation to load the updated code and
catalog.

Historical failures remain attached to their original binaries. Remaining partial
validation cases, including TDFS, partitioned dynamic PageRank, GraphMiner/G2Miner
`k=3`, and missing output certificates, are separate work. The six excluded builds
(SIGMo, MG-alphaGCD, FastGED, cuRipples, HyperBlocker and GPUGraphLayout) remain
excluded. Passing these tests does not establish unlimited graph size, every
research variant, or a formal guarantee for the approximate algorithms.
