# Cliques & dense subgraphs

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

Which tightly connected groups exist? Clique: every pair connected. Biclique: every cross pair connected. k-core: at least k neighbours each. k-truss: each edge in at least k−2 triangles. Densest: most edges per vertex, or the declared weighted or higher-order clique density. Quasi-clique: a minimum internal-degree fraction. These operations select subgraphs satisfying a structural definition; they do not require a partition of all vertices.

**Start with this question:** Which tightly connected groups exist?

[Explore these operations](../explorer.md#family/dense) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [Maximal Clique Enumeration](#maximal_clique_enumeration)
- [Maximum Clique](#maximum_clique)
- [k-Clique Counting and Enumeration](#k_clique_counting_enumeration)
- [Maximal Biclique Enumeration](#maximal_biclique_enumeration)
- [Quasi-Clique Mining](#quasi_clique_mining)
- [Densest Subgraph](#densest_subgraph)
- [Densest k-Subgraph](#densest_k_subgraph)
- [k-Core Decomposition](#k_core_decomposition)
- [k-Truss Decomposition](#k_truss_decomposition)

## Maximal Clique Enumeration {#maximal_clique_enumeration}

Given an undirected graph, enumerate every vertex set that forms a clique and is not a proper subset of another clique.

$$
\mathcal C=\{S:G[S]\text{ complete},\ \nexists T\supsetneq S\text{ complete}\}
$$

Maximal means that no vertex can be added; it does not mean largest.

**Example question:** “Find all fully connected groups that cannot be extended.”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Every materialized set must be exact; complete=true requires exhaustive enumeration.

**Required outputs:** `cliques`, `returned_count`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`maximal-cliques`](../explorer.md#problem/maximal_clique_enumeration) | `cpp` | `rdmce`, `mce-gpu`, `g2-aimd` | Exact |

**`maximal-cliques`** — Exact maximal cliques in an undirected simple projection. Drop loops and duplicate edges; ignore weights. Original GPU kernels supply a count, with bounded C++ materialization and explicit list completeness.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run maximal-cliques INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/maximal_clique_enumeration) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/01_maximal_clique_enumeration/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Parallelizing Maximal Clique Enumeration on GPUs](https://arxiv.org/abs/2212.01473). PACT 2023, 2023 · [Author code](https://github.com/yen-hsiang-chang/mce-gpu).
- [G2-AIMD: A Memory-Efficient Subgraph-Centric Framework for Efficient Subgraph Finding on GPUs](https://doi.org/10.1109/ICDE60146.2024.00245). IEEE ICDE 2024, 2024 · [Author code](https://github.com/Pz1996/g2-aimd).
- [Root-Down Exposure for Maximal Clique Enumeration on GPUs](https://craft.cs.tsinghua.edu.cn/publication/root-down-exposure-for-maximal-clique-enumeration-on-gpus/). PPoPP 2026, 2026 · [Author code](https://github.com/Pz1996/RDMCE).

## Maximum Clique {#maximum_clique}

Given an undirected graph, find a clique with the largest possible number of vertices.

$$
\omega(G)=\max_{S:G[S]\text{ complete}}|S|
$$

Every pair of selected vertices must be adjacent; the objective is group size.

**Example question:** “What is the largest fully connected group?”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** An exact completed result must have optimal=true; interrupted solvers may return a feasible clique and certified bound.

**Required outputs:** `maximum_size`, `cliques`, `optimal`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`maximum-clique`](../explorer.md#problem/maximum_clique) | `cpp` | `cuda-ms`, `gpu-maximum-clique`, `maximum-clique-on-gpu` | Exact |

**`maximum-clique`** — Exact maximum clique, optionally all tied optima. Undirected simple projection; loops, duplicate edges and weights ignored. Original GPU witnesses are checked by native coloring or exact search; ties use native materialization.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run maximum-clique INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/maximum_clique) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/02_maximum_clique/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Implementation of a Maximum Clique Search Procedure on CUDA](https://doi.org/10.1007/s10732-018-9393-x). Journal of Heuristics, 2019 · [Author code](https://github.com/pawelld/CUDA-MS).
- [Maximum Clique Enumeration on the GPU](https://escholarship.org/uc/item/7j96s061). IPDPSW/GrAPL 2023, 2023 · [Author code](https://github.com/owensgroup/GPUMaximumClique).
- [Efficiently Computing Maximum Clique of Sparse Graphs with Many-Core Graphical Processing Units](https://doi.org/10.5220/0012852700003753). ICSOFT 2024, 2024 · [Author code](https://github.com/stefanoquer/Maximum-Clique-on-GPU).

## k-Clique Counting and Enumeration {#k_clique_counting_enumeration}

Given an undirected graph and integer k, count or enumerate every complete vertex set containing exactly k vertices.

$$
C_k(G)=\sum_{S\subseteq V,\ |S|=k}\mathbf1[G[S]\text{ complete}]
$$

k is the exact number of vertices in each clique.

**Example question:** “How many fully connected groups of four are there?”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** complete=true requires an exact exhaustive result.

**Required outputs:** `count`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`k-cliques`](../explorer.md#problem/k_clique_counting_enumeration) | `cpp` | `graphset`, `gamma`, `kcgpu` | Exact |

**`k-cliques`** — Exact count for k>=2 with no upper k bound on CPU. Undirected simple projection; loops, duplicate edges and weights ignored. GPU counts require supported k and a uint64 count bound. Counts remain complete when memberships are capped.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run k-cliques INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/k_clique_counting_enumeration) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/03_k_clique_counting_enumeration/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Parallel K-Clique Counting on GPUs](https://arxiv.org/abs/2104.13209). ACM ICS 2022, 2022 · [Author code](https://github.com/ssmoha7/KCGPU).
- [GraphSet: High Performance Graph Mining through Equivalent Set Transformations](https://doi.org/10.1145/3581784.3613213). SC 2023, 2023 · [Author code](https://github.com/sth1997/GraphSet).
- [A Graph Pattern Mining Framework for Large Graphs on GPU](https://doi.org/10.1007/s00778-024-00883-8). The VLDB Journal, 2024 · [Author code](https://github.com/pkumod/GAMMA).

## Maximal Biclique Enumeration {#maximal_biclique_enumeration}

Given a bipartite graph, enumerate complete bipartite subgraphs that cannot be extended by adding a vertex to either side.

$$
A\subseteq L,\ B\subseteq R,\ A\times B\subseteq E
$$

A and B form a complete two-sided group and neither side can be enlarged while preserving completeness.

**Example question:** “Which groups of users are each connected to every business in a group?”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: partition information required; edge attributes: ignored.

**Guarantee.** Every returned pair must be exact; complete=true requires exhaustive enumeration.

**Required outputs:** `bicliques`, `returned_count`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`maximal-biclique-counting`](../explorer.md#problem/maximal_biclique_enumeration) | `cpp` | `mbe-gpu` | Exact |
| [`maximal-bicliques`](../explorer.md#problem/maximal_biclique_enumeration) | `cpp` | `cumbe` | Exact |

**`maximal-biclique-counting`** — Count nonempty maximal bicliques with attributes.side=left|right on every vertex. Undirected simple projection. MBE-GPU count is checked against bounded native enumeration; no size filtering.

**`maximal-bicliques`** — Exact inclusion-maximal bicliques with nonempty sides. Supply both disjoint partitions covering every vertex, or omit both to use every vertex's attributes.side=left|right. Undirected input; loops discarded and duplicate edges collapsed. Capped memberships are marked incomplete.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run maximal-biclique-counting INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/maximal_biclique_enumeration) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/09_maximal_biclique_enumeration/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Efficient Maximal Biclique Enumeration on GPUs](https://doi.org/10.1145/3581784.3607059). SC 2023, 2023 · [Author code](https://github.com/fhxu00/MBE-GPU).
- [cuMBE: GPU-Accelerated Maximal Biclique Enumeration](https://arxiv.org/abs/2401.05039). arXiv preprint, 2024 · [Author code](https://github.com/NTUDDSNLab/cuMBE).
- [Advanced Maximal Biclique Enumeration on GPUs Using Bitmaps](https://doi.org/10.1109/TC.2025.3566898). IEEE Transactions on Computers, 2025 · [Author code](https://github.com/fhxu00/MBE-GPU).

## Quasi-Clique Mining {#quasi_clique_mining}

Find vertex subsets whose induced subgraphs satisfy a minimum internal-degree fraction, allowing dense groups that are not complete cliques.

$$
\deg_{G[S]}(v)\ge\lceil\gamma(|S|-1)\rceil\quad\forall v\in S
$$

gamma is the required fraction of possible neighbors inside a group; the contract also sets minimum size and maximality.

**Example question:** “Find groups where each member connects to most of the others.”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** All reported sets must satisfy the threshold; complete=true means exhaustive enumeration.

**Required outputs:** `quasi_cliques`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`quasi-cliques`](../explorer.md#problem/quasi_clique_mining) | `cpp` | `cuqc` | Exact |

**`quasi-cliques`** — Exact gamma quasi-cliques on an undirected simple projection. Thresholds use decimal-rational gamma; maximality is relative to all qualifying sets within the size bounds. Search is bounded by work and output budgets.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run quasi-cliques INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/quasi_clique_mining) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/04_quasi_clique_mining/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [GPU-Accelerated Maximal Quasi-Clique Mining](https://doi.org/10.1109/BigData66926.2025.11401709). IEEE BigData 2025, 2025 · [Author code](https://github.com/Mike12041204/cuQC).

## Densest Subgraph {#densest_subgraph}

Find a nonempty vertex subset maximizing its induced k-clique count divided by the number of selected vertices. Clique order k=2 gives ordinary edge density; the k=2 weighted variant uses total induced edge weight. Clique order does not constrain result cardinality.

$$
\max_{\varnothing\ne S\subseteq V}\frac{C_k(G[S])}{|S|}
$$

C_k counts k-cliques. k=2 gives edges per vertex; weighted k=2 uses the sum of edge weights. k does not fix the result size.

**Example question:** “Find the densest subgraph by edges per vertex.”

**Input assumptions.** direction: undirected; weights: optional nonnegative; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exact mode requires optimal=true; approximate mode must disclose its bound when known.

**Required outputs:** `vertices`, `density`, `clique_order`, `clique_count`, `induced_edge_value`, `optimal`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`densest-subgraph`](../explorer.md#problem/densest_subgraph) | `cpp` | `cds` | Exact |

**`densest-subgraph`** — Exact induced k-clique count divided by vertex count. Weighted density is defined for clique_order=2, summing parallel weights. Undirected input; loops discarded. Native rational maximum-weight closure for minimum_vertices=1; bounded exhaustive cardinality search otherwise.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run densest-subgraph INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/densest_subgraph) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/05_densest_subgraph/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Bound-Tightened Densest Subgraph Discovery on GPU](https://doi.org/10.1145/3802023). PACMMOD / SIGMOD 2026, 2026 · [Author code](https://github.com/wajidmanzoor/CDS).

## Densest k-Subgraph {#densest_k_subgraph}

Given an undirected graph and integer k, find exactly k vertices maximizing the total value of edges induced by those vertices.

$$
\max_{S\subseteq V,\ |S|=k}\sum_{e\in E(G[S])}w(e)
$$

Here k fixes the number of selected vertices; unweighted edges have unit value.

**Example question:** “Which ten vertices have the greatest induced edge value?”

**Input assumptions.** direction: undirected; weights: optional nonnegative; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exact mode requires optimal=true; approximate mode returns a feasible set and any known bound.

**Required outputs:** `vertices`, `induced_edge_value`, `density`, `optimal`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`densest-k-subgraph`](../explorer.md#problem/densest_k_subgraph) | `cpp` | — | Exact |

**`densest-k-subgraph`** — Exact bounded cardinality search. Sum parallel nonnegative weights, discard loops, require undirected input. An approximate request receives the stronger exact result when search completes.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run densest-k-subgraph INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/densest_k_subgraph) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/06_densest_k_subgraph/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

This utility group has no separate research-paper entry in the catalog.

## k-Core Decomposition {#k_core_decomposition}

Assign every vertex its largest k for which it belongs to the maximal induced subgraph whose vertices all have internal degree at least k.

$$
c(v)=\max\{k:v\in S,\ \min_{u\in S}\deg_{G[S]}(u)\ge k\}
$$

The k-core is the maximal induced subgraph meeting the internal-degree threshold.

**Example question:** “Find the core where everyone has at least three neighbors inside it.”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Core numbers and degeneracy are exact.

**Required outputs:** `core_number_by_vertex`, `degeneracy`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`k-core`](../explorer.md#problem/k_core_decomposition) | `cpp` | `libcugraph`, `kcore-gpu` | Exact |

**`k-core`** — Exact core numbers and optional selected vertices. Undirected simple projection; loops, duplicate edges and weights ignored. Isolates have core number zero.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run k-core INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/k_core_decomposition) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/07_k_core_decomposition/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Gunrock: GPU Graph Analytics](https://arxiv.org/abs/1701.01170). ACM Transactions on Parallel Computing, 2017 · [Author code](https://github.com/gunrock/gunrock).
- [Hornet: An Efficient Data Structure for Dynamic Sparse Graphs and Matrices on GPUs](https://davidbader.net/publication/2018-bgbb/). IEEE HPEC 2018, 2018 · [Author code](https://github.com/hornet-gt/hornet).
- [Accelerating k-Core Decomposition by a GPU](https://doi.org/10.1109/ICDE55515.2023.00142). IEEE ICDE 2023, 2023 · [Author code](https://github.com/akhlaqueak/KCoreGPU).
- cuGraph Core-number peeling — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## k-Truss Decomposition {#k_truss_decomposition}

Assign every edge the largest k for which it belongs to a maximal subgraph where each edge participates in at least k-2 triangles within that subgraph.

$$
\operatorname{support}_{H}(e)\ge k-2\quad\forall e\in E(H)
$$

Support counts triangles containing an edge within H; a k-truss is maximal under this condition.

**Example question:** “Which edges remain in tightly supported triangle groups?”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** All truss numbers are exact.

**Required outputs:** `truss_number_by_edge`, `maximum_truss_number`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`k-truss`](../explorer.md#problem/k_truss_decomposition) | `cpp` | `libcugraph`, `acctd` | Exact |

**`k-truss`** — Complete edge truss numbers using the k-2 support convention, plus optional k-truss selection. Undirected simple projection, weights ignored. First original edge IDs represent collapsed edges; source IDs are retained.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run k-truss INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/k_truss_decomposition) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/08_k_truss_decomposition/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Hornet: An Efficient Data Structure for Dynamic Sparse Graphs and Matrices on GPUs](https://davidbader.net/publication/2018-bgbb/). IEEE HPEC 2018, 2018 · [Author code](https://github.com/hornet-gt/hornet).
- [Accelerating Truss Decomposition on Heterogeneous Processors](https://www.vldb.org/pvldb/vol13/p1751-che.pdf). PVLDB, 2020 · [Author code](https://github.com/RapidsAtHKUST/AccTrussDecomposition).
- cuGraph Fixed-k truss extraction — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
