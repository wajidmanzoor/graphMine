# Prepare, sample & draw

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

Build, clean, shrink, sample, extract or draw a graph before analysis. Resolve entities, construct or reduce graphs, sample neighborhoods or walks, and compute layouts. Graph extraction overlaps with records; choose this family when the goal is preparing a graph for subsequent analysis.

**Start with this question:** Build, clean, shrink, sample, extract or draw a graph before analysis.

[Explore these operations](../explorer.md#family/preparation) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [Graph-Based Entity Resolution and Rule-Based Blocking](#entity_resolution_blocking)
- [Graph Coarsening and Quotient Construction](#graph_coarsening)
- [Induced Subgraph and Ego-Network Extraction](#induced_subgraph_ego_extraction)
- [k-Nearest-Neighbor Graph Construction](#knn_graph_construction)
- [Spectral Graph Sparsification](#spectral_graph_sparsification)
- [Neighborhood Sampling](#neighborhood_sampling)
- [Graph Random-Walk Generation](#random_walk_generation)
- [Force-Directed Graph Layout](#graph_layout_force_directed)

## Graph-Based Entity Resolution and Rule-Based Blocking {#entity_resolution_blocking}

Given a collection of candidate entity records and one or more declared blocking rules over record attributes, generate the reduced set of candidate record pairs worth comparing, and optionally confirm matches and merge them into resolved-entity clusters.

$$
C=\{(u,v):u\ne v,\ \exists b\text{ with }b(u)=b(v)\}
$$

Blocking keys b generate candidate pairs; optional confirmation rules determine actual matches.

**Example question:** “Which records should be compared as possible duplicates?”

**Input assumptions.** direction: ignored; weights: ignored; timestamps: ignored; vertex attributes: required record fields; edge attributes: ignored.

**Guarantee.** blocking is exact and deterministic given blocking_rules; resolution's connected_components clustering is exact given match_decision, while correlation_clustering is NP-hard in general and approximate mode must disclose a bound.

**Required outputs:** `candidate_pairs`, `reduction_ratio`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`entity-resolution`](../explorer.md#problem/entity_resolution_blocking) | `cpp` | — | Exact |

**`entity-resolution`** — Complete native disjunctive blocking rules with equality, Unicode tokens, codepoint Levenshtein or exact numeric difference. ICU NFKC and full case folding; optional missing fields fail the predicate. Input edges are unused hints. Connected-components resolution or exact bounded minimum candidate-pair disagreement partitions; neutral noncandidates and no cross-component clusters.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run entity-resolution INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/entity_resolution_blocking) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/34_entity_resolution_blocking/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [HyperBlocker: Accelerating Rule-based Blocking in Entity Resolution using GPUs](https://arxiv.org/abs/2410.04349). PVLDB 18, 2025 · [Author code](https://github.com/hsiaoko/HyperBlocker).

## Graph Coarsening and Quotient Construction {#graph_coarsening}

Map every vertex to a nonempty coarse cluster and construct the weighted quotient graph with declared edge and feature aggregation.

$$
\pi:V\twoheadrightarrow V',\quad w'_{ab}=\sum_{\pi(u)=a,\pi(v)=b}w_{uv}
$$

This shows sum aggregation; the declared profile controls aggregation, loops, and feature handling.

**Example question:** “Collapse these groups into a smaller graph.”

**Input assumptions.** direction: undirected; weights: optional finite nonnegative weights default one; timestamps: ignored; vertex attributes: optional numeric feature vectors; edge attributes: ignored.

**Guarantee.** Clustering may be heuristic; quotient aggregation must be exact within numeric tolerance.

**Required outputs:** `fine_to_coarse`, `coarse_graph`, `cluster_sizes`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`graph-coarsening`](../explorer.md#problem/graph_coarsening) | `cpp` | — | Parameter dependent |

**`graph-coarsening`** — Supplied integer partition or native greedy maximal matching; all vertices remain represented. Undirected nonnegative input, reject loops. Sum original parallel edge weights once, retain or drop intra-cluster edges, sum or mean feature vectors. Exact rational aggregates are reported separately from rounded binary64 graph values. Greedy partition has no optimality claim.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run graph-coarsening INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/graph_coarsening) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/62_graph_coarsening/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Fast Graph Representation Learning with PyTorch Geometric](https://arxiv.org/abs/1903.02428). ICLR 2019 workshop, 2019 · [Author code](https://github.com/pyg-team/pytorch_geometric).
- cuGraph Weighted graph coarsening — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
- nvGRAPH graph contraction — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/nvgraph).

## Induced Subgraph and Ego-Network Extraction {#induced_subgraph_ego_extraction}

Extract the graph induced by an explicit vertex set or by vertices within a hop radius of declared seeds.

$$
G[S]=(S,\{(u,v)\in E:u,v\in S\})
$$

S is explicit or discovered within the requested hop radius around seeds.

**Example question:** “Show the two-hop neighborhood around this vertex.”

**Input assumptions.** direction: directed or undirected; weights: preserve; timestamps: preserve; vertex attributes: preserve; edge attributes: preserve.

**Guarantee.** Exact extraction, preserving edge identities and properties.

**Required outputs:** `subgraph`, `vertex_mapping`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`induced-subgraph`](../explorer.md#problem/induced_subgraph_ego_extraction) | `cpp` | `libcugraph` | Exact |

**`induced-subgraph`** — Exact induced or ego subgraph, preserving typed IDs, edge instances and properties. Ego radius includes all vertices within that distance. Direction affects discovery only; output retains original edge direction. GPU ego discovery uses libcugraph BFS with native materialization.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run induced-subgraph INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/induced_subgraph_ego_extraction) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/48_induced_subgraph_ego_extraction/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Deep Graph Library: A Graph-Centric, Highly-Performant Package for Graph Neural Networks](https://arxiv.org/abs/1909.01315). Research reference, 2019 · [Author code](https://github.com/dmlc/dgl).
- [Fast Graph Representation Learning with PyTorch Geometric](https://arxiv.org/abs/1903.02428). ICLR 2019 workshop, 2019 · [Author code](https://github.com/pyg-team/pytorch_geometric).
- [Fast Graph Representation Learning with PyTorch Geometric](https://arxiv.org/abs/1903.02428). ICLR 2019 workshop, 2019 · [Author code](https://github.com/pyg-team/pytorch_geometric).
- cuGraph Ego-network extraction — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
- cuGraph Induced subgraph extraction — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## k-Nearest-Neighbor Graph Construction {#knn_graph_construction}

Construct a graph connecting each feature vector to its k nearest distinct input vectors under a declared distance metric.

$$
N_k(i)=\operatorname{arg\,topk}_{j\ne i}^{\min}\ d(x_i,x_j)
$$

The metric, tie handling, and symmetrization are declared parameters.

**Example question:** “Build a nearest-neighbor graph from these vectors.”

**Input assumptions.** direction: not applicable feature vectors; weights: ignored; timestamps: ignored; vertex attributes: required finite equal length vectors; edge attributes: ignored.

**Guarantee.** Exact and approximate modes are separate and must be reported.

**Required outputs:** `neighbor_lists`, `graph`, `search_metadata`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`knn-graph`](../explorer.md#problem/knn_graph_construction) | `cpp` | — | Numerical |

**`knn-graph`** — Native exhaustive pairwise Euclidean, squared Euclidean or cosine distances with self-exclusion and input-order tie breaking. Directed, union or mutual symmetrization. Cosine rejects zero vectors. Exact neighbor search under numerical distances even when approximate is requested; preserves typed vector IDs.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run knn-graph INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/knn_graph_construction) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/64_knn_graph_construction/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Billion-scale similarity search with GPUs](https://arxiv.org/abs/1702.08734). IEEE Transactions on Big Data, published 2019, 2017 · [Author code](https://github.com/facebookresearch/faiss).
- [Fast Graph Representation Learning with PyTorch Geometric](https://arxiv.org/abs/1903.02428). ICLR 2019 workshop, 2019 · [Author code](https://github.com/rusty1s/pytorch_cluster).
- [Fast k-NN Graph Construction by GPU based NN-Descent](https://doi.org/10.1145/3459637.3482344). ACM CIKM 2021, 2021 · [Author code](https://github.com/rapidsai/cuvs).

## Spectral Graph Sparsification {#spectral_graph_sparsification}

Construct a sparse reweighted subgraph approximating the quadratic form of a weighted undirected graph Laplacian.

$$
(1-\varepsilon)x^\top L_Gx\le x^\top L_Hx\le(1+\varepsilon)x^\top L_Gx
$$

This is the target quadratic-form guarantee for all x. The result must disclose what guarantee its profile actually establishes.

**Example question:** “Make a smaller graph that preserves Laplacian behavior.”

**Input assumptions.** direction: undirected; weights: required nonnegative; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Distinguish proved bounds, probabilistic guarantees and empirical diagnostics; sampled-vector tests do not certify all-vector bounds.

**Required outputs:** `sparsifier`, `quality_summary`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`spectral-sparsification`](../explorer.md#problem/spectral_graph_sparsification) | `cpp` | — | Heuristic |

**`spectral-sparsification`** — Native effective-resistance sampling with replacement, exact rational draw normalization and importance reweighting. LAPACK grounded solves and all generalized eigenvalues measure numerical distortion; requested epsilon must pass. Explicit weighted undirected simple input, no loops/parallels. Preserve original IDs/attributes. Identity shortcut when budget covers positive edges, zero-weight edges removed. No probabilistic approximation guarantee is claimed.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run spectral-sparsification INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/spectral_graph_sparsification) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/55_spectral_graph_sparsification/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [inGRASS: Incremental Graph Spectral Sparsification via Low-Resistance-Diameter Decomposition](https://arxiv.org/abs/2402.16990). Research reference, 2024.
- [dyGRASS: Dynamic Spectral Graph Sparsification via Localized Random Walks on GPUs](https://arxiv.org/abs/2505.02741). ICCAD 2025, 2025 · [Author code](https://github.com/Feng-Research/dyGRASS).
- [dyGRASS: Dynamic Spectral Graph Sparsification via Localized Random Walks on GPUs](https://arxiv.org/abs/2505.02741). ICCAD 2025, 2025 · [Author code](https://github.com/Feng-Research/dyGRASS).

## Neighborhood Sampling {#neighborhood_sampling}

Sample multihop neighborhoods around seed vertices using declared fanouts and neighbor-selection probabilities.

$$
N_{\ell+1}=\operatorname{sample}(\bigcup_{v\in N_\ell}N(v),f_\ell)
$$

f is the fanout per hop; replacement, weights, types, and temporal rules determine the sampling distribution.

**Example question:** “Sample a bounded neighborhood around these seeds.”

**Input assumptions.** direction: directed or undirected; weights: optional nonnegative; timestamps: optional for temporal sampling; vertex attributes: ignored; edge attributes: optional edge types.

**Guarantee.** Structural validity and sampling semantics are exact; realizations are stochastic.

**Required outputs:** `sampled_edges`, `sampled_vertices`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`neighborhood-sampling`](../explorer.md#problem/neighborhood_sampling) | `cpp` | — | Stochastic |

**`neighborhood-sampling`** — Outgoing edge-instance sampling with hop and seed-batch provenance. Support uniform or exact weighted draws, replacement, typed fanouts and inclusive time cutoff. Fanout -1 includes every eligible edge, including zero-weight edges; loops and parallel identities are retained.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run neighborhood-sampling INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/neighborhood_sampling) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/47_neighborhood_sampling/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [C-SAW: A Framework for Graph Sampling and Random Walk on GPUs](https://arxiv.org/abs/2009.09103). SC 2020, 2020 · [Author code](https://github.com/concept-inversion/C-SAW).
- [Accelerating Graph Sampling for Graph Machine Learning using GPUs](https://arxiv.org/abs/2009.06693). arXiv; EuroSys 2021, 2020 · [Author code](https://github.com/plasma-umass/NextDoor).
- [Skywalker: Efficient Alias-Method-Based Graph Sampling and Random Walk on GPUs](https://ieeexplore.ieee.org/document/9563020). PACT 2021, 2021 · [Author code](https://github.com/sjtu-SAIL-lab/Skywalker).
- cuGraph Neighbor sampling — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## Graph Random-Walk Generation {#random_walk_generation}

Generate vertex sequences sampled from a declared graph transition process.

$$
\Pr[X_{t+1}=v\mid X_t=u]=P_{uv}
$$

P follows the declared walk rule; biased walks may also depend on the previous vertex.

**Example question:** “Generate random walks starting at these vertices.”

**Input assumptions.** direction: directed or undirected; weights: optional nonnegative; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Every transition must be valid and obey the requested probability distribution; finite samples are stochastic outputs.

**Required outputs:** `walks`, `lengths`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`random-walks`](../explorer.md#problem/random_walk_generation) | `cpp` | `libcugraph` | Stochastic |

**`random-walks`** — Uniform, weighted or node2vec walks with length measured in transitions. Preserve direction and loops. Uniform walks collapse parallel neighbors; weighted walks sum parallel weights. CPU probabilities use exact rational arithmetic. Repeated starts produce separate walks.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run random-walks INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/random_walk_generation) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/46_random_walk_generation/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [C-SAW: A Framework for Graph Sampling and Random Walk on GPUs](https://arxiv.org/abs/2009.09103). SC 2020, 2020 · [Author code](https://github.com/concept-inversion/C-SAW).
- [Accelerating Graph Sampling for Graph Machine Learning using GPUs](https://arxiv.org/abs/2009.06693). arXiv; EuroSys 2021, 2020 · [Author code](https://github.com/plasma-umass/NextDoor).
- [Skywalker: Efficient Alias-Method-Based Graph Sampling and Random Walk on GPUs](https://ieeexplore.ieee.org/document/9563020). PACT 2021, 2021 · [Author code](https://github.com/sjtu-SAIL-lab/Skywalker).
- cuGraph GPU random walks — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## Force-Directed Graph Layout {#graph_layout_force_directed}

Given a graph, compute a position for every vertex in 2 or 3 dimensions under a declared force model, so that connected vertices are pulled together and all vertices repel each other, producing a drawing that visually reveals clusters and hubs.

$$
X=(x_v)_{v\in V},\quad x_v\in\mathbb R^d
$$

The declared force model updates these positions; a useful drawing is not a structural optimum certificate.

**Example question:** “Draw this graph with connected vertices pulled together.”

**Input assumptions.** direction: undirected projection; weights: optional as attractive force strength; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** This problem has no exact mode and no unique global optimum; solution_quality=converged requires meeting the iteration's own stated tolerance, and solution_quality=approximate permits a fixed iteration budget with final_energy disclosed.

**Required outputs:** `vertex_positions`, `final_energy`, `converged`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`force-directed-layout`](../explorer.md#problem/graph_layout_force_directed) | `cpp` | — | Heuristic |

**`force-directed-layout`** — Native Fruchterman-Reingold iterations in two or three dimensions. Explicit 0.01 distance regularization, linear cooling from one tenth of the maximum coordinate span, no final rescaling. Recompute matching potential and uncooled force residual; no drawing optimality claim. Project direction, drop loops, collapse unweighted or sum weighted parallels.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run force-directed-layout INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/graph_layout_force_directed) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/36_graph_layout_force_directed/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Exploiting GPUs for Fast Force-Directed Visualization of Large-Scale Networks](https://ieeexplore.ieee.org/document/8025312/). 46th International Conference on Parallel Processing (ICPP 2017), 2017 · [Author code](https://github.com/govertb/GPUGraphLayout).
- cuGraph ForceAtlas2 layout — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
