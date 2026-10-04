# GPU correctness expansion — 2026-10-04

Package note: the original artifact screens were run in the surrounding
`graphDatabaseAgent` workspace. This package includes their metadata, fixtures,
results and logs, plus the sources for promoted profiles. Rebuilding the other
research artifacts requires their original code snapshots under the surrounding
`problems/` tree. The 99-check public library replay is self-contained here.
See [agent integration](../../docs/ALGORITHM_EXPANSION.md) for the subsequent
packaged-library replay and routing changes.

Five bounded library profiles passed all 99 public CLI checks; four isolated workers passed Compute Sanitizer memcheck. The existing 17 GPU regressions and the new C++ API regression passed. A CUDA-disabled build passed its three existing active tests and the new unavailable-backend regression.

This is a correctness screen on small and medium synthetic fixtures, not a proof of universal correctness or a performance benchmark. Source snapshots under `problems/` were not modified. Pinned, licensed copies and reviewed host adapters are in the library.

## Screening disposition

| Classification | Paper artifacts |
|---|---:|
| correctness_fail | 4 |
| validated_profile | 5 |
| no_local_code | 18 |
| partial_pass | 4 |
| build_blocked | 4 |
| artifact_mismatch | 2 |

`validated_profile` certifies only the explicit API surface below. A smoke test is not a mathematical correctness pass. Unavailable code, blocked builds, partial profiles and mismatches were not promoted.

## Added to the library

| Operation | Limits |
|---|---|
| `connected-components` | Exact weak/strong; canonical external-ID component numbering. |
| `max-flow-min-cut` | Directed integer capacities; non-loop sum <= 1e9; flow/cut certified at runtime; no vertex capacities. |
| `linear-assignment` | Complete square minimum-cost perfect assignment; <=64 vertices per side; integer costs [0,999]. |
| `transitive-closure` | Full reflexive directed closure; <=1024 vertices; no persistent index. |
| `butterfly-counting` | Exact global count; declared bipartite sides; no core/participation modes. |

The root `library/build/graphmine list` now contains 18 operations and 31 backend choices. See [API/build/installation documentation](../../library/docs/validated_expansion.md). The separate packaged agent catalog under `graphMine-repo/` is not changed; no model training or deployment was performed.

## Artifact evidence

| Artifact | Disposition | Checks / limitation |
|---|---|
| `2020_kpar` | correctness_fail | Returns five rows for k=4; the 64-cycle run also omits the highest-score source. Score tolerance alone is insufficient. [Evidence](results/kpar.json) |
| `2025_ecl_maxflow` | validated_profile | Raw artifact: 12/13, including an edgeless launch error. Promoted only with tested launch guards, sparse-degree fix, empty-input handling and flow/cut certification. [Evidence](results/ecl_flow.json) |
| `2025_wbpr` | partial_pass | 12/12 scalar flow values; full flow/cut certificate not exported or validated. License in maxflow-bcsr2 does not establish license of the tested maxflow-cuda folder. [Evidence](results/wbpr.json) |
| `2022_g2miner_reuse` | validated_profile | 12/12 global counts using the existing native square kernel. New public facade enforces declared bipartite sides. Other problem modes remain unsupported. [Evidence](results/graphminer_butterfly.json) |
| `2022_gamma_reuse` | correctness_fail | Single K2,2 produces 16 embeddings instead of 8 injective embeddings; other fixtures mismatch or fail. Generic matcher is not a validated butterfly backend. [Evidence](results/gamma_butterfly.json) |
| `2026_fast_ged` | build_blocked | javac is unavailable. No GED/MCS correctness claim. [Evidence](builds/fast_ged.json) |
| `2021_gpusteiner_kmb` | partial_pass | 8/8 singleton-group tree fixtures: cost and complete returned edge set checked. General group Steiner and approximation guarantees unverified. [Evidence](results/gpusteiner.json) |
| `2022_gpu_vlsi_gst` | partial_pass | 2/2 singleton-group path costs. General group coverage and certificate checks remain missing; no explicit license detected. [Evidence](results/gst_vlsi.json) |
| `2025_gpu4gst` | correctness_fail | Both 8- and 64-vertex path queries time out after 20 seconds, even after selecting the available GPU. No returned tree witness; no explicit license detected. [Evidence](results/gpu4gst.json) |
| `2020_curipples` | build_blocked | CMake cannot find spdlog; dependency set is not installed. No algorithm correctness claim. [Evidence](builds/curipples_configure.json) |
| `2021_gim` | partial_pass | 18/18 probability-one IC screens meet the predeclared 0.63 quality threshold. General probabilities, LT semantics and failure bounds remain unvalidated. [Evidence](results/gim.json) |
| `2021_superfuser` | correctness_fail | 17/18 probability-one screens meet the 0.63 target. One 64-chain run selects vertex 25 (spread 39/64, below the test threshold). This is a failed quality screen, not a proof that every heuristic run is invalid. [Evidence](results/superfuser.json) |
| `2019_hungariangpu` | validated_profile | 11/11 square integer minimum-cost assignment tests versus SciPy, including size 64. Only the bounded perfect-assignment profile is promoted. [Evidence](results/hungarian.json) |
| `2021_graphbplus` | artifact_mismatch | Three execution smoke checks succeeded. Output is edge/tree sampling statistics rather than the required minimum-frustration partition and certificate. Mathematical correctness is not certified. [Evidence](results/graphbplus.json) |
| `2026_ecl_sgb` | artifact_mismatch | Three execution smoke checks succeeded. Output is edge/tree sampling statistics rather than the required minimum-frustration partition and certificate. Mathematical correctness is not certified. [Evidence](results/ecl_sgb.json) |
| `2024_gdlog` | validated_profile | 8/8 full pair-set checks. Native adapter also passes a 128-cycle (16,384 pairs), removing the diagnostic printer cap. SM89 is pinned after the inherited SM52 build failed. [Evidence](results/gdlog_tc.json) |
| `2025_hyperblocker` | build_blocked | CMake cannot find gflags; required dependency/submodule tree is incomplete. No entity-resolution correctness claim. [Evidence](builds/hyperblocker_configure.json) |
| `2023_eclscc` | validated_profile | 13/13 whole-partition oracle checks. Native facade additionally checks weak mode, canonical labels, isolated vertices, mixed external IDs, loops and duplicate arcs. [Evidence](results/ecl_scc.json) |
| `2017_gpugraphlayout` | build_blocked | Build cannot find the pngwriter submodule header. No layout correctness claim. [Evidence](builds/gpu_layout.json) |

## Independent oracles and boundary coverage

- Components: NetworkX strong/weak partitions, complete membership, sizes and canonical labels.
- Flow: NetworkX maximum-flow value; every edge capacity, vertex conservation, residual reachability, cut capacity and edge removal independently checked. Original IDs and parallel-edge flows restored.
- Assignment: SciPy linear-sum assignment, objective recomputation and a one-to-one matching.
- Closure: exhaustive NetworkX descendants including every reflexive pair; medium fixture exceeds the original 3,000-row diagnostic cap.
- Butterfly: independent common-neighbor intersections and choose-two counts, including K5,7, empty graphs and random bipartite graphs.
- Public boundary: mixed ID types, self-loops, duplicates, edgeless inputs, integer bounds, unsupported profiles, missing workers, malformed worker output, nonzero exits and timeout cleanup.
- Approximate influence results use an explicitly declared 0.63 quality screen only on probability-one independent-cascade fixtures. They do not establish a general stochastic guarantee.

## Failures retained and fixes applied

The [raw ECL flow result](results/ecl_flow.json) remains a 12/13 failure. Two zero-grid launch sites are guarded in generated host code, the sparse average-degree calculation avoids truncation/division by zero, and the facade handles exact zero-capacity cases. Kernels are unchanged. The [initial public-API run](results/library_expansion_before_fixes.json) remains 95/99: a one-edge flow also exposed the launch issue, and GDlog failed when compiled for inherited SM52. The SM89 build plus guards passes [all 99 checks](results/library_expansion.json), including those failures.

GAMMA fixtures use the documented vertex-count prefix in `.vlabel`; the mismatches in the final evidence are after correcting the converter. GPU4GST was adjusted only to select GPU 0 rather than hardcoded GPU 3; both bounded runs timed out. kPAR release source is pinned by archive SHA-256 and keeps its upstream algorithm; CUB include compatibility and a missing standard header were handled locally.

## Reproduction

```bash
cmake -S library -B library/build -DCMAKE_BUILD_TYPE=Release
cmake --build library/build --target graphmine_cli graphmine_validated_expansion_test -j4
python3 validation/gpu_correctness_expansion/validate_library.py
ctest --test-dir library/build --output-on-failure
python3 validation/gpu_correctness_expansion/make_report.py
```

The Python oracle suite requires NumPy, SciPy and NetworkX. Exact build/run commands, exit statuses, timeouts and output are in `builds/` and `runs/`; logical inputs and expected results are in `datasets/` and `results/`. Upstream hashes, licenses and source commits are in [PROVENANCE.json](../../library/src/backends/expansion/upstream/PROVENANCE.json). The library generator verifies hashes and writes adapter patches in `library/build/expansion-generated/`. Candidate-specific screening is in `run.py`, `validate_extra.py`, `screen_candidates.py` and `screen_remaining.py`.

The original 20-problem validation totals remain historical evidence in `../gpu_correctness/`. Do not add these scoped passes to those totals and call all algorithms fully correct. Missing build dependencies and missing result/certificate semantics must be resolved before any further promotions.
