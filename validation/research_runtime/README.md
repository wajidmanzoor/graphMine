# Scoped checks of collected implementations

These are runtime tests of pinned research sources, separate from the 38 public
GraphMine backends. They do not add executable agent integrations. Exact tests,
model execution checks, expected domain rejections and research failures are
reported separately in [../parameter_expansion/RESULTS.md](../parameter_expansion/RESULTS.md).

There are 19 tested artifact records across problems 48, 52, 53 and 62..69.
The fixtures include all 208 simple graph atlas entries on 1..6 vertices,
80 seeded graphs on 7..12 vertices, tied feature vectors, singleton hyperedges,
disconnected/repeated Laplacian eigenvalues and small metric filtrations.

| Sources | Test meaning |
| --- | --- |
| PyG avg_pool, induced and k-hop extraction | Independent quotient/edge/vertex oracles; supplied coarsening assignments, not learned partition discovery. |
| PyG GCN, GAT, GraphSAGE, GIN, DiffPool, SAGPool | CUDA/CPU layer parity and finite backward checks where applicable. No training or predictive-quality claim. |
| DHG HGNN, HNHN, HyperGCN | Logits/gradients, deterministic CPU parity where applicable, independent incidence formula for HGNN. HyperGCN's singleton-hyperedge rejection is explicitly tested. |
| Faiss FlatL2 | Built collected CUDA source; explicit self-ID removal after k+1 search; exact distance/neighbor checks including ties. |
| torch-cluster | Built collected CUDA source; raw knn_graph results checked for exactly k unique non-self neighbors. Duplicate vectors expose failures for zero and positive k. |
| CuPy dense eigh, Lanczos, LOBPCG | Pinned Python algorithm files over separately installed CuPy 14.2 compiled runtime. NumPy eigenvalues, residuals and orthonormality are checked. This is not a complete build of the pinned CuPy repository. |
| Ripser++ | Built pinned implementation; independent F2 boundary reduction through H2. Finite bars pass; Python export omits the essential H0 interval, so the full barcode contract fails. |
| Component-aware MVC | Both hybrid and stack-only modes checked against exhaustive optimum size on 288 graphs each. Upstream emits no vertex-cover witness. |

All per-case fixtures, seeds, failures and scopes are in `results/*/cases.jsonl`.
The first diagnostic runs are preserved in `diagnostics/initial`: CuPy needed
the local CUDA include path and a CUDA dense array before CSR conversion;
Ripser++ finite and essential bars were separated; HyperGCN's declared domain
rejection was separated from successful model execution. These harness fixes
do not turn an invalid algorithm result into a passing result.

Known remaining gaps include nvGraph widest paths/contraction (legacy configure
failure), cuGraph (pinned source requires CMake >=4; the installed build setup uses
3.28.3), cuVS NN-descent integration, learned MIS/MVC checkpoint/inference paths,
GraphMiner/Pangolin MNI mining adapters, and GraphSlim condensation training and
evaluation. Configure logs are in [build_failures](build_failures/). The complete
219-record inventory is in [research_gaps.md](../parameter_expansion/research_gaps.md).

The torch-cluster CUDA kernel has k<=100 storage, while knn_graph(loop=False)
requests k+1, making 99 the raw wrapper's upper bound. A future canonical adapter
must handle k=0 explicitly and trim ties after self-ID removal. HyperGCN requires
at least two vertices in every hyperedge; HGNN/HNHN accept the singleton fixtures.
LOBPCG's two failures concern residual/Gram-matrix breakdown at the tested
tolerance and runtime combination; dense eigh and Lanczos pass the same matrices.
For a concrete kNN failure, a nine-vector fixture with duplicates and k=0
returns four edges instead of an empty graph. A two-point Ripser++ fixture
returns no essential H0 bar where the reference requires [0, infinity).

[environment.json](environment.json) records versions, GPU/toolkit details and
source manifests. Build products and isolated environments are ignored by Git.
The pinned source directories are never edited by this harness.

Run an installed test environment from the repository root, for example:

```sh
validation/research_runtime/torch-venv/bin/python validation/research_runtime/validate.py pyg --gpu 0
CUDA_PATH=/usr validation/research_runtime/venv/bin/python validation/research_runtime/validate.py eigen --gpu 1
```

Other family arguments are `knn`, `faiss`, `models`, `hypergraph`, `persistence`
and `mvc`. The Faiss driver is `faiss_knn.cpp`; torch-cluster, Faiss, Ripser++ and
MVC were compiled for sm_89 in ignored `build/` directories. Raw upstream failures
are retained for review and have not been hidden behind a replacement solver.
