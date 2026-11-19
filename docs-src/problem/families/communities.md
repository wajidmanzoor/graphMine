# Communities & partitions

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

How should vertices be grouped or partitioned? Find communities, balanced partitions or signed-network group structure. Full partitions assign vertices to groups; local and overlapping communities may cover only part of the graph. Unlike dense, the organizing question is group membership or partition structure, rather than selecting a subgraph by a clique, core, truss or density definition.

**Start with this question:** How should vertices be grouped or partitioned?

[Explore these operations](../explorer.md#family/communities) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [Disjoint Community Detection](#community_detection)
- [Seeded Local Community Detection](#seeded_local_community_detection)
- [Overlapping Community Detection by k-Clique Percolation](#overlapping_community_detection)
- [Balanced k-Way Graph Partitioning](#balanced_graph_partitioning)
- [Balanced Hypergraph Partitioning](#hypergraph_partitioning)
- [Signed Network Structural Balance and Frustration Minimization](#signed_network_structural_balance)

## Disjoint Community Detection {#community_detection}

Partition all graph vertices into nonoverlapping communities that maximize a declared within-community quality function.

$$
\mathcal P^*\in\arg\max_{\mathcal P}Q(\mathcal P;G)
$$

P is a partition and Q is the declared community objective. Heuristic profiles do not certify a global optimum.

**Example question:** “Split this network into communities.”

**Input assumptions.** direction: undirected; weights: optional nonnegative; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Heuristic mode returns a feasible partition without claiming a global optimum.

**Required outputs:** `community_by_vertex`, `community_count`, `quality_score`, `optimal`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`community-detection`](../explorer.md#problem/community_detection) | `cpp` | `gleiden`, `parallel-louvain`, `parallel-leiden`, `parallel-leiden-plus` | Parameter dependent |

**`community-detection`** — Undirected modularity or constant Potts objective. Exact mode enumerates partitions with rational objectives; heuristic mode uses seeded positive-gain vertex moves and makes no global-optimum claim. Drop loops and collapse unweighted or sum weighted parallel edges. CPM is internal edge weight minus resolution times within-part vertex pairs.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run community-detection INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/community_detection) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/16_community_detection/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- cuGraph Ensemble Clustering for Graphs — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
- cuGraph Leiden community detection — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
- cuGraph Louvain modularity optimization — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
- [gLeiden: Accelerated Community Detection Algorithms Using Directed and Undirected Graphs on GPUs](https://pmc.ncbi.nlm.nih.gov/articles/PMC12987761/). Bioinformatics Advances, 2026 · [Author code](https://github.com/Beenishgul/Leiden).
- [GPU-Accelerated Multilevel Graph Clustering: A Parallel Perspective on Louvain and Leiden](https://arxiv.org/abs/2608.01503). IEEE IPDPS 2026, 2026 · [Author code](https://github.com/euphoricpoptarts/PennsylvaniaGPUGraphClustering).

## Seeded Local Community Detection {#seeded_local_community_detection}

Find a nontrivial low-conductance vertex subset containing a specified seed set.

$$
\min_{S\supseteq S_0}\phi(S),\qquad\phi(S)=\frac{w(S,V\setminus S)}{\min(\operatorname{vol}(S),\operatorname{vol}(V\setminus S))}
$$

S_0 is the seed set; a nontrivial feasible set is required and volume follows the contract.

**Example question:** “Find a well-connected community around these seed vertices.”

**Input assumptions.** direction: undirected; weights: optional nonnegative; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Typical diffusion-and-sweep methods are heuristic; diffusion scores alone are an incomplete implementation of this contract.

**Required outputs:** `vertices`, `conductance`, `optimal`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`seeded-local-community`](../explorer.md#problem/seeded_local_community_detection) | `cpp` | — | Heuristic |

**`seeded-local-community`** — Heuristic personalized-PageRank degree-normalized sweep with required seeds first. Returns the lowest defined weighted conductance among feasible prefixes. Exact cut/volume recomputation, no global-optimum claim. Undirected input; reject loops, sum nonnegative parallel weights. If all conductance denominators vanish, return the seeds.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run seeded-local-community INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/seeded_local_community_detection) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/49_seeded_local_community_detection/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Gunrock: GPU Graph Analytics](https://arxiv.org/abs/1701.01170). ACM Transactions on Parallel Computing, 2017 · [Author code](https://github.com/gunrock/gunrock).
- [Gunrock: GPU Graph Analytics](https://arxiv.org/abs/1701.01170). ACM Transactions on Parallel Computing, 2017 · [Author code](https://github.com/gunrock/gunrock).
- [GraphBLAST: A High-Performance Linear Algebra-based Graph Framework on the GPU](https://arxiv.org/abs/1908.01407). arXiv; later published in ACM TOPC, 2019 · [Author code](https://github.com/gunrock/graphblast).

## Overlapping Community Detection by k-Clique Percolation {#overlapping_community_detection}

Find overlapping communities formed by connected components of the clique-adjacency graph, where two k-cliques are adjacent when they share k-1 vertices.

$$
C_i\sim C_j\iff |C_i\cap C_j|=k-1
$$

Each C_i is a k-clique; connected components of this clique-adjacency graph induce overlapping communities.

**Example question:** “Find overlapping communities joined through shared cliques.”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** All qualifying k-cliques and their components are computed exactly.

**Required outputs:** `communities`, `community_ids_by_vertex`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`overlapping-communities`](../explorer.md#problem/overlapping_community_detection) | `cpp` | — | Exact |

**`overlapping-communities`** — Exact k-clique percolation. Undirected simple projection; discard loops and duplicates. Communities can overlap. Unassigned vertices are outside all percolation communities before minimum-size display filtering.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run overlapping-communities INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/overlapping_community_detection) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/17_overlapping_community_detection/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

This utility group has no separate research-paper entry in the catalog.

## Balanced k-Way Graph Partitioning {#balanced_graph_partitioning}

Given an undirected graph and a target part count k, assign every vertex to exactly one of k parts of approximately equal size so that the total weight of edges crossing between parts is minimized.

$$
\min_{\mathcal P}\sum_{(u,v)\in E}w_{uv}\mathbf1[\mathcal P(u)\ne\mathcal P(v)]
$$

The partition has a declared number of nonempty parts and balance bounds. Other declared objectives use their own normalization.

**Example question:** “Split the graph into four balanced groups with few crossing edges.”

**Input assumptions.** direction: undirected; weights: optional nonnegative; timestamps: ignored; vertex attributes: optional as balance weight; edge attributes: ignored.

**Guarantee.** Exact mode requires optimal=true and is only expected to terminate on small graphs; approximate mode must disclose imbalance_ratio and, when known, approximation_bound.

**Required outputs:** `partition_assignment`, `objective_value`, `part_sizes`, `balanced`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`balanced-partitioning`](../explorer.md#problem/balanced_graph_partitioning) | `cpp` | — | Exact |

**`balanced-partitioning`** — Exact bounded partition search with nonempty parts and both lower and upper balance limits. Undirected input, nonnegative edge weights, loop removal and duplicate collapse or weighted sum. Normalized cut sums each part boundary divided by its declared balance size. Decimal-rational imbalance tolerance; exact objective and infeasibility certificates.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run balanced-partitioning INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/balanced_graph_partitioning) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/30_balanced_graph_partitioning/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [G-kway: Multilevel GPU-Accelerated k-way Graph Partitioner using Task Graph Parallelism](https://doi.org/10.1145/3649329.3656238). ACM/IEEE DAC 2024 (journal version: ACM TODAES 2025), 2024.
- [HyperG: Multilevel GPU-Accelerated k-way Hypergraph Partitioner](https://doi.org/10.1145/3658617.3697551). ACM/IEEE ICCAD 2024, 2024.
- [iG-kway: Incremental k-way Graph Partitioning on GPU](https://www.researchgate.net/publication/395608469_iG-kway_Incremental_k-way_Graph_Partitioning_on_GPU). ACM/IEEE DAC 2025, 2025.

## Balanced Hypergraph Partitioning {#hypergraph_partitioning}

Partition vertices of a weighted hypergraph into balanced parts while minimizing a declared hyperedge cut objective.

$$
\min_{\mathcal P}\sum_{e\in E_H}w_e\mathbf1[\lambda_e>1]
$$

lambda_e counts parts touched by hyperedge e. Connectivity mode uses lambda_e minus one instead; parts must satisfy balance bounds.

**Example question:** “Divide this hypergraph into balanced groups.”

**Input assumptions.** direction: undirected hypergraph; weights: optional nonnegative hyperedge weights; timestamps: ignored; vertex attributes: optional nonnegative vertex weights; edge attributes: ignored.

**Guarantee.** Heuristic optimization; feasibility and objective recomputation are exact checks.

**Required outputs:** `partition`, `objective_value`, `part_weights`, `feasible`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`hypergraph-partitioning`](../explorer.md#problem/hypergraph_partitioning) | `cpp` | — | Exact |

**`hypergraph-partitioning`** — Exact native enumeration of nonempty parts, optimizing weighted cut-net or connectivity-minus-one without graph projection. Exact rational vertex and hyperedge weights, decimal imbalance tolerance and upper part-weight bound. Certified infeasibility when no partition qualifies; exponential search obeys work budgets.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run hypergraph-partitioning INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/hypergraph_partitioning) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/54_hypergraph_partitioning/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [gHyPart: GPU-friendly End-to-End Hypergraph Partitioner](https://doi.org/10.1145/3711925). ACM TACO, 2025 · [Author code](https://github.com/zlwu92/gHyPart_TACO).
- [Hypergraph Partitioning on GPU with Distinct Incident Hyperedges and Size Constraints](https://arxiv.org/abs/2605.20497). Research reference, 2026 · [Author code](https://github.com/EMJzero/AxonCUDA).
- FastPartitioner GPU hypergraph refinement — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/sparcityeu/FastPartitioner).
- [HGNN-Part: A High-Quality Hypergraph Partitioner Based on Hypergraph Generative Model](https://doi.org/10.23919/DATE69613.2026.11539511). DATE 2026, 2026 · [Author code](https://github.com/THU-numbda/HGNN-Part).
- [HySpecPro: Scalable Hypergraph Partitioning via Spectral Projection Optimization](https://arxiv.org/abs/2607.00055). Research preprint, 2026 · [Author code](https://github.com/NVlabs/HySpecPro).

## Signed Network Structural Balance and Frustration Minimization {#signed_network_structural_balance}

Given a graph whose edges are each labeled positive or negative, determine whether it is structurally balanced (partitionable into two factions so every positive edge stays within a faction and every negative edge crosses factions), and when it is not, find a two-faction assignment minimizing the total weight of frustrated edges.

$$
\min_{x_v\in\{-1,1\}}\sum_{(u,v)\in E}w_{uv}\mathbf1[x_ux_v\ne s_{uv}]
$$

s is the edge sign. Zero disagreement certifies two-faction balance.

**Example question:** “Can positive and negative relationships be explained by two factions?”

**Input assumptions.** direction: undirected; weights: optional nonnegative as frustration cost; timestamps: ignored; vertex attributes: ignored; edge attributes: required sign label.

**Guarantee.** For balance_check, optimal=true certifies the balance decision, not a minimum-frustration assignment on an unbalanced graph. For frustration_minimization, optimal=true certifies the optimization under the declared numerical certificate; approximate mode must disclose approximation_bound.

**Required outputs:** `balanced`, `faction_assignment`, `frustrated_weight`, `optimal`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`signed-balance`](../explorer.md#problem/signed_network_structural_balance) | `cpp` | — | Exact |

**`signed-balance`** — Exact signed parity balance test and bounded rational frustration minimization. Every edge type is positive or negative. Undirected input; drop loops, reject contradictory parallel signs and collapse unweighted or sum weighted parallels. Zero-cost violations still make the network structurally unbalanced.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run signed-balance INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/signed_network_structural_balance) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/32_signed_network_structural_balance/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Discovering and Balancing Fundamental Cycles in Large Signed Graphs](https://doi.org/10.1145/3458817.3476153). ACM/IEEE SC 2021, 2021 · [Author code](https://github.com/burtscher/graphBplus).
- [Signed Graph Balancing in Linear Time](https://doi.org/10.1145/3818671.3818675). ACM GPGPU 2026 (18th Workshop on General Purpose Processing Using GPU), 2026 · [Author code](https://github.com/burtscher/ECL-SGB).
