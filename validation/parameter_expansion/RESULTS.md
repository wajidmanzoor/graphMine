# Runtime results

Final-build checks: **15,204/15,204 distinct cases passed**, 0 failed; complete run plus the MBE resource and typed-vertex-ID reruns. All 38 registered choices plus automatic k-clique selection are represented.

Binary SHA-256: `9fbacd0bfc0a958ebb8326aa537a55363ff862029ec90aeab84cc90ff951f338`. Inputs, worker hashes, commands and individual oracle outcomes are retained alongside the summary.

| Operation / backend | Passed | Failed |
| --- | ---: | ---: |
| betweenness-centrality/turbo-bc | 208 | 0 |
| butterfly-counting/gamma-butterfly | 512 | 0 |
| butterfly-counting/graphminer | 512 | 0 |
| community-detection/gleiden | 208 | 0 |
| community-detection/parallel-leiden | 624 | 0 |
| community-detection/parallel-leiden-plus | 624 | 0 |
| community-detection/parallel-louvain | 624 | 0 |
| connected-components/ecl-scc | 368 | 0 |
| densest-subgraph/cds | 1336 | 0 |
| dynamic-triangle-counting/edtc | 208 | 0 |
| graph-motifs/dumato | 208 | 0 |
| graph-motifs/graphminer | 208 | 0 |
| graph-motifs/graphset | 208 | 0 |
| group-steiner-tree/gpu4gst | 160 | 0 |
| influence-maximization/superfuser | 184 | 0 |
| k-cliques/auto | 420 | 0 |
| k-cliques/gamma | 1000 | 0 |
| k-cliques/graphset | 916 | 0 |
| k-cliques/kcgpu | 1252 | 0 |
| k-core/kcore-gpu | 208 | 0 |
| k-truss/acctd | 208 | 0 |
| linear-assignment/hungarian-cuda | 200 | 0 |
| max-flow-min-cut/ecl-maxflow | 184 | 0 |
| maximal-biclique-counting/mbe-gpu | 512 | 0 |
| maximal-bicliques/cumbe | 512 | 0 |
| maximal-cliques/g2-aimd | 208 | 0 |
| maximal-cliques/mce-gpu | 208 | 0 |
| maximal-cliques/rdmce | 208 | 0 |
| maximum-clique/cuda-ms | 208 | 0 |
| maximum-clique/gpu-maximum-clique | 208 | 0 |
| maximum-clique/maximum-clique-on-gpu | 208 | 0 |
| personalized-pagerank/kpar | 184 | 0 |
| quasi-cliques/cuqc | 624 | 0 |
| subgraph-isomorphism/gmatch | 624 | 0 |
| temporal-motif-mining/everest | 160 | 0 |
| temporal-motif-mining/mayura | 160 | 0 |
| transitive-closure/gdlog | 184 | 0 |
| triangle-counting/tot | 208 | 0 |
| triangle-counting/wetric | 208 | 0 |

The full run at eight jobs per GPU recorded 59 MBE-GPU out-of-memory errors. All 512 MBE cases were then repeated with 1 worker on GPU 0: 512 passed / 0 failed. The CLI, worker binaries, generator, instructions and fixtures were identical. Original failures remain in [the full-run summary](results/final/summary.json); [acceptance evidence](results/acceptance/summary.json) identifies the result used for every case. This is not a clean single-attempt run.

The final review also found that the harness serialized string vertex ID `"0"` as integer `0` in CLI arguments. The agent already encoded these IDs correctly. The corrected harness reran all 368 PageRank and max-flow cases: 368 passed / 0 failed. Fixtures and binaries were unchanged; both generator hashes are recorded. Dangling-seed PageRank additionally has an exact check. The earlier PageRank error measurements are superseded by [this rerun](results/vertex-id-rerun/summary.json).

Boundary checks: 51/51; memcheck cases: 41/41.
The separate K514 memcheck reports zero errors, and GAMMA racecheck reports zero warnings/errors.

These are bounded correctness checks, not performance benchmarks or global certificates for heuristic algorithms. See the README for oracle scopes.

Final native CTest: 24/24; agent tests: 229/229. Commands, binary identity and logs are in [final-checks.json](evidence/final-checks.json).

Leiden termination regression: the previous binary timed out in 9/40 replays. The candidate repair passed 60/60 independent partition/score checks on both GPUs. Native tests repeat the fixture 20 times per Leiden variant, with a 60-second test timeout. See [replay evidence](results/leiden-timeout-replay/summary.json).

PPR: 184 cases measured; worst returned-score absolute error 6.3281344e-05. No acceptance error threshold or certified per-run bound was imposed.

## Collected implementations outside the CLI

These tests cover 19 artifact records. Model checks assess execution/parity/gradients, not trained accuracy. Some expected domain rejections are counted as successful checks and shown separately.

| Implementation / check | Passed | Failed | Scope |
| --- | ---: | ---: | --- |
| cupy-dense-eigh | 301 | 0 | Pinned upstream algorithm; independent NumPy eigenvalues, residuals, orthonormality, repeated zero eigenvalues |
| cupy-lanczos | 300 | 0 | Pinned upstream algorithm; independent NumPy eigenvalues, residuals, orthonormality, repeated zero eigenvalues |
| cupy-lobpcg | 298 | 2 | Pinned upstream algorithm; independent NumPy eigenvalues, residuals, orthonormality, repeated zero eigenvalues |
| faiss-flat-knn | 200 | 0 | Collected GPU FlatL2 search plus explicit self-ID removal, exact distances and tied-neighbor optimum vs NumPy |
| dhg-hgnn | 100 | 0 | Upstream model forward/backward, finite logits and gradients; HGNN/HNHN CPU parity; no training/generalization claim |
| dhg-hnhn | 100 | 0 | Upstream model forward/backward, finite logits and gradients; HGNN/HNHN CPU parity; no training/generalization claim |
| dhg-hypergcn | 55 | 0 | Upstream model forward/backward, finite logits and gradients; HGNN/HNHN CPU parity; no training/generalization claim |
| dhg-hgnn-formula | 100 | 0 | Independent dense NumPy incidence-matrix formula for HGNN convolution |
| dhg-hypergcn-domain-rejection | 45 | 0 | Expected rejection of singleton hyperedges; no model output |
| torch-cluster-knn | 203 | 51 | Exact squared-Euclidean directed kNN, distinct IDs including tied/duplicate vectors |
| pyg-gcn | 58 | 0 | Collected model layer: CUDA/CPU output parity and finite backward gradients; no trained predictive-quality claim |
| pyg-gat | 58 | 0 | Collected model layer: CUDA/CPU output parity and finite backward gradients; no trained predictive-quality claim |
| pyg-graphsage | 58 | 0 | Collected model layer: CUDA/CPU output parity and finite backward gradients; no trained predictive-quality claim |
| pyg-gin | 58 | 0 | Collected model layer: CUDA/CPU output parity and finite backward gradients; no trained predictive-quality claim |
| pyg-diffpool | 58 | 0 | CUDA/CPU layer-output parity only; no trained graph classifier |
| pyg-sagpool | 58 | 0 | CUDA/CPU pooling parity only; no trained graph classifier |
| component-aware-mvc-hybrid | 288 | 0 | Exact optimum SIZE vs exhaustive subsets; upstream exports no cover witness |
| component-aware-mvc-stackonly | 288 | 0 | Exact optimum SIZE vs exhaustive subsets; upstream exports no cover witness |
| ripserplusplus-finite-bars | 100 | 0 | Hybrid upstream implementation vs independent F2 boundary reduction, finite intervals H0 through H2 |
| ripserplusplus-essential-h0 | 0 | 100 | Full barcode contract: Python export must include essential H0 interval |
| pyg-average-pool | 288 | 0 | Exact quotient for supplied assignment, drop self-loops, mean features, sum weights; no clustering generation |
| pyg-induced-subgraph | 288 | 0 | Exact selected-vertex edge extraction; caller preserves isolated vertices |
| pyg-khop-subgraph | 288 | 0 | Exact undirected k-hop induced extraction |

Observed research failures: torch-cluster violates exact neighbor counts with duplicate/tied vectors (including k=0); collected CuPy LOBPCG fails on two dense Laplacians under the recorded compiled runtime; Ripser++ omits the essential H0 interval from Python output. Finite Ripser++ intervals pass independently. These implementations remain research-only.

## Outer workspace additions

The outer folder has 37 contracts / 91 records. Problems 21..37 contain 37 newer records: 15 have runnable diagnostic integrations, 22 remain gaps. Historical binaries were hashed; GPU4GST was rebuilt from current outer source containing earlier repairs. A partial pass retains the limitations of the original screen.

| Outer backend | Passed / cases | Status |
| --- | ---: | --- |
| graphminer_butterfly | 12 / 12 | partial_pass |
| ecl_scc | 141 / 141 | pass |
| hungarian | 11 / 11 | pass |
| gim | 18 / 18 | partial_pass |
| wbpr | 12 / 12 | partial_pass |
| gpusteiner | 8 / 8 | partial_pass |
| graphbplus | 3 / 3 | partial_pass |
| gst_vlsi | 2 / 2 | partial_pass |
| ecl_flow | 83 / 141 | correctness_fail |
| gdlog_tc | 8 / 8 | pass |
| superfuser | 18 / 18 | partial_pass |
| gamma_butterfly | 1 / 12 | correctness_fail |
| kpar | 0 / 2 | correctness_fail |
| ecl_sgb | 3 / 3 | partial_pass |
| gpu4gst | 2 / 2 | partial_pass |

Concrete outer failures: ECL-Maxflow exits with CUDA invalid-configuration errors on 58 inputs (including an edgeless graph and a single source-to-sink edge); some print the correct scalar before failing, so these are runtime failures rather than evidence of an incorrect flow value. GAMMA reports two butterflies for a single K2,2 whose reference count is one. KPAR returns five entries when top-4 is requested on the cycle fixtures; this failure does not establish an approximation-error violation.

GraphB+ and ECL-SGB are output/execution smoke checks only; they do not certify frustration or balance optima. KPAR is a limited approximate top-k screen. Group Steiner screens cover small path/scalar cases. See each JSON result for its limitations.

The inner collection passed offline checks of all 70 contracts / 219 artifact records, including documented availability gaps: 181 local GPU source entries and 161 local main papers. The outer 37 contracts passed structural/schema-reference checks. Integrity does not imply numerical correctness. The per-record gaps are in [research_gaps.md](research_gaps.md) and the outer [inventory](../../../validation/parameter_expansion_outer/inventory.json).
