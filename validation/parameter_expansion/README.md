# Parameter extensions and correctness sweep

This review covers all 38 executable backend choices, the newer records in the
outer workspace's `problems` folder, and practical runtime checks of newly
collected implementations. The collection contains 70 problem contracts and
219 artifact records; this does **not** mean 219 integrated or validated solvers.

The machine has two RTX 6000 Ada GPUs with 48 GB each. Independent cases are
distributed across physical devices 0 and 1. These tests do not qualify a single
algorithm invocation spanning both GPUs.

## Changes and reasons

| Area | Supported behavior after the repair | Why a limit remains |
| --- | --- | --- |
| KCGPU clique order | k=3..10; common k=2 edge count; automatic routing can reach k=10 | Ten is the expanded, tested profile, not a mathematical maximum. Forward degree is bounded by 1,000 and a conservative clique-count upper bound must fit uint64. |
| GAMMA clique order | k=3..7 | The collected embedding representation has seven slots. Raising it further requires a different representation and new validation. |
| GraphSet clique order | k=3..6 | The selected fixed-depth kernel and scratch layout support six. Forward degree remains bounded by 1,280. |
| CDS density | `--clique-order k`, default 2; density is C_k(S)/abs(S), with returned order and clique count | The public integer order fits signed int; nontrivial searches still need finite worker memory and time. This is clique density, not fixed-cardinality densest-k-subgraph. |
| Community detection | PGGC Louvain/Leiden/Leiden+ accept finite nonnegative resolution | gLeiden's selected integration still requires resolution=1; all remain heuristic, unweighted modularity methods. |
| gMatch | The existing 16-vertex query limit now works with the DFS path | QVMAX=16, query arrays/masks and signed-short candidate storage remain structural limits. Data vertices stay at most 32,767. |
| WeTriC planning | Matrix length at least 64 and a multiple of 64; spread at most 47 in the portable profile | Shared storage uses (256*spread+1)*4 bytes against the current 48 KiB launch budget. Native device checks remain authoritative. |
| Maximum-clique ties | Every singleton is returned on an edgeless graph when all ties are requested | CUDA-MS and Maximum-Clique-on-GPU retain only one witness and cannot accept all-ties=true. |
| Temporal motifs | Strict t1<t2<t3, inclusive final time window, distinct event IDs preserved | Only the integrated feed-forward triangle is supported; relative time span plus window must fit signed int. |
| Betweenness centrality | Direct C++ calls reject non-unit edge weights | The integrated TurboBC path uses unweighted shortest paths. |

CDS now sizes candidate/partial-clique storage from the graph and order, and
retries reported partition overflow with bounded growth in a fresh worker.
All retries share the caller's total time budget. Dense K20 at order 10 is a
regression case. Returned density is independently checked against the witness.

PGGC refreshes its initial objective after setting resolution. Previously its
base constructor could leave resolution=1 state behind, producing wrong scores
or a crash for other resolutions. The host score calculation uses the same
requested resolution. Leiden refinement could also repeatedly append an
unchanged coarse graph, hanging on a six-vertex fixture in 9 of 40 replays.
The generated build now finishes with the current local partition when
refinement cannot contract the graph, then lifts it through previous levels.
Both Leiden variants passed 60 candidate replays across the two GPUs. This is
a termination rule for the heuristic, not a claim of optimal modularity.

GAMMA's prefix intersection compared a query position with a mapped vertex ID,
skipping an adjacency requirement. The repair compares positions and adds warp
barriers where shared state is reused. KCGPU had an unused SM-indexed diagnostic
write into a vertex-sized allocation, an undersized Pascal table, and insufficient
pivot/depth storage. The repaired build removes the diagnostic, uses the full
1,001-square Pascal table, and allocates the terminal depth slot. Before this
repair K405 at k=3 returned 10,827,807 rather than 10,989,810. Closed-form checks
now extend through K1001; oversized degree and uint64 bounds are rejected.

Kernel repairs are applied to generated build copies in CMake. The collected
upstream snapshots are preserved. Native regression cases cover GAMMA's false
4-clique, timestamp ties in both temporal kernels, gMatch's 16-vertex DFS query,
KCGPU's deep pivot search, and repeated Leiden refinement stagnation.

Planner validation and generation schemas now agree on native integer ranges,
backend maxima, equality constraints, unsupported boolean modes, and backend-only
tuning fields. Automatic selection must have an available compatible backend.
[parameter_profiles.json](parameter_profiles.json) records every exposed backend's
current parameters and constraints. Research contracts remain broader than
executable capabilities; unsupported research options are not added to plans.

## Limits retained across the other algorithms

| Operation / backends | Retained constraint and reason |
| --- | --- |
| Maximal cliques: MCE-GPU, G2-AIMD, RDMCE | Finite index/count storage; G2-AIMD degree below 100,000 and fixed scratch. Memberships use the common host materializer. |
| Maximum clique: CUDA-MS, GPUMaximumClique, Maximum-Clique-on-GPU | Finite integer indices and, for CUDA-MS, dense adjacency memory; only GPUMaximumClique supports all ties. |
| cuQC | Degree ratio 0.5..1: diameter-two pruning relies on that mathematical assumption. |
| KCoreGPU and AccTD | Full unweighted undirected core/truss decompositions; no artificial small-k ceiling. Integer graph storage still limits scale. |
| cuMBE | Declared bipartition and cooperative CUDA launch; membership output uses the host materializer. |
| MBE-GPU | Scheduled count-only variant; no memberships, size filters or alternative bitmap/multi-GPU modes. Fixed per-block scratch is large even for tiny inputs; several concurrent workers can exhaust a 48 GB GPU. |
| ToT, WeTriC, EDTC | Triangle-specific objectives; static or batch-update counts. Listings use host materialization. |
| GraphMiner, GraphSet, DuMato motifs | Connected motifs with 3 or 4 vertices and fixed class tables; GraphSet is non-induced, the other two induced. |
| ECL-SCC | Worker resource caps of one million vertices and ten million input edges; weak and strong connectivity are separate modes. |
| ECL-Maxflow | Nonnegative integer capacities, conservative total at most one billion, due to signed-int residual/excess arithmetic. |
| HungarianCUDA | Complete square assignment, at most 64 vertices per side and integer costs 0..999; compile-time arrays and sentinel/padding costs. |
| GDlog | At most 1,024 vertices for full materialized reflexive closure, due to quadratic collector/output size. |
| GraphMiner/GAMMA butterfly counting | Global K2,2 count on declared bipartite input; no participation, listing or peeling decomposition. |
| KPAR | One seed, restart exactly 0.2, epsilon 0.01..0.5; propagation/index construction fixes alpha. Approximate scores have no certified per-run error bound. |
| GPU4GST | 1..16 groups, checked integer weights/costs and exponential vertex-by-subset state; no hop/diameter constraint. |
| SuperFuseR | Independent cascade, probabilities in [0,1], 32..65,536 samples in multiples of 32; warp layout and resource profile. No certified approximation guarantee. |

The [original static audit](../../problems/_collection/parameter_limit_audit_2026_10_09.md)
records the pre-change source investigation. Its old ranges and lack of runtime
testing are historical; use this report and the runtime results for current status.

## Evidence and scope

The completed result tables are generated in [RESULTS.md](RESULTS.md). Individual
cases, commands, seeds, binary/worker hashes and oracle outcomes are under
`results/`. The first complete run (`results/full`) retained 36 failures: 20 GAMMA,
6 automatic selections of GAMMA, and 5 each for Everest and Mayura. Interrupted
runs preceding the KCGPU memory/table repairs are retained separately and are
not final evidence.
The last complete run before the Leiden termination repair is retained in
`results/before-pggc-stagnation-fix`: 15,203/15,204 passed, with the one
reproduced Leiden timeout. The final run uses the repaired binary throughout.

The final suite includes every unlabeled simple graph on 1..6 vertices (208
graphs), all 512 labeled 3-by-3 bipartite graphs, all 64 loop-free directed
three-vertex graphs, seeded larger directed cases, temporal ties/parallel events,
assignments, group Steiner instances, and clique/density orders on 7..13 vertices.
There are 15,204 CLI cases, including additional automatic-backend cases.

Exact operations use exhaustive independent references, including witness and
membership checks where the API returns them. Heuristic community results are
checked for partition validity and their actual objective, not a global optimum.
PPR errors are measured against exact stationary distributions without treating
epsilon as a certificate. Influence fixtures use deterministic probabilities 0/1;
they do not certify stochastic quality or a general approximation ratio.

The [219-record matrix](research_gaps.md) lists all remaining research gaps.
[Research runtime results](../research_runtime/README.md) describe separately
built/imported implementations, including failures. The outer folder's
[inventory](../../../validation/parameter_expansion_outer/inventory.json) and
[results](../../../validation/parameter_expansion_outer/summary.json) cover its
37 contracts / 91 records, with execution screens for 15 of the 37 records in
newer problems 21..37. The other 22 newer records lack executable test integrations;
the older 54 outer records were inventoried, not rerun as raw artifacts.

Reproduce the full native sweep from the repository root with:

```sh
python3 validation/parameter_expansion/validate.py --mode full --gpus 0,1 --workers-per-gpu 4 --work /tmp/graphmine-retest
python3 validation/parameter_expansion/boundaries.py
python3 validation/parameter_expansion/coverage_matrix.py
```

Four jobs per GPU worked for these bounded fixtures on 48 GB devices. The final
build's eight-job run exceeded memory when four MBE-GPU processes landed on one
device. Every MBE case was therefore rerun at lower concurrency; the report
retains both the original failures and the rerun. `reconcile_resource_rerun.py`
accepts only allocation failures, verifies identical binaries and fixtures, and
requires a complete MBE rerun before combining evidence. Reduce concurrency
further on smaller GPUs. Output limits do not generally bound search work or memory.

The harness also now JSON-encodes vertex-ID arguments, as the agent already
does, to preserve string `"0"` versus integer `0`. All PageRank and max-flow
fixtures were repeated after correcting this command construction. Their
graphs, requested IDs and library binary were unchanged; the report uses these
corrected results and records both generator versions. A dangling PageRank seed
has an additional exact point-mass check rather than only a measured error.
