# Importance & influence

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

Which vertices matter most, or which seeds spread furthest? Measure vertex centrality, rank vertices globally or relative to chosen seeds, or select seeds for an explicitly defined spreading process.

**Start with this question:** Which vertices matter most, or which seeds spread furthest?

[Explore these operations](../explorer.md#family/importance) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [Centrality and Influential-Node Mining](#centrality_influential_node_mining)
- [Personalized PageRank and Random Walk with Restart](#personalized_pagerank_rwr)
- [Influence Maximization under Diffusion Models](#influence_maximization)

## Centrality and Influential-Node Mining {#centrality_influential_node_mining}

Compute a declared centrality score for graph vertices and rank the most structurally influential vertices under that definition.

$$
\operatorname{rank}(V) = \operatorname{sort}_{v\in V} c(v)
$$

c is the chosen centrality, such as degree, PageRank, or betweenness; these measure different forms of importance.

**Example question:** “Which vertices have the most direct connections?”

**Input assumptions.** direction: directed or undirected; weights: optional measure dependent; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exactness is measure-specific; iterative and approximate methods must disclose convergence or bounds.

**Required outputs:** `ranked_vertices`, `score_definition`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`betweenness-centrality`](../explorer.md#problem/centrality_influential_node_mining) | `cpp` | `libcugraph`, `turbo-bc` | Backend dependent |
| [`degree-centrality`](../explorer.md#problem/centrality_influential_node_mining) | `cpp` | — | Exact |
| [`pagerank`](../explorer.md#problem/centrality_influential_node_mining) | `cpp` | `libcugraph` | Numerical |

**`betweenness-centrality`** — All-source betweenness excluding endpoints. Preserve direction, drop loops and keep minimum parallel length. CPU supports exact rational scores and strictly positive weighted paths; GPU profiles use unweighted paths with declared floating-point arithmetic.

**`degree-centrality`** — Exact degree scores with outgoing, incoming, both or undirected-projection semantics. Drop loops, collapse duplicate edges and ignore weights. Optional normalization divides by n-1; isolates score zero.

**`pagerank`** — Directed random-walk scores with uniform restart and dangling distribution. Drop loops, sum parallel weights and independently verify the fixed-point residual.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run betweenness-centrality INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/centrality_influential_node_mining) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/18_centrality_influential_node_mining/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Gunrock: GPU Graph Analytics](https://arxiv.org/abs/1701.01170). ACM Transactions on Parallel Computing, 2017 · [Author code](https://github.com/gunrock/gunrock).
- [Hornet: An Efficient Data Structure for Dynamic Sparse Graphs and Matrices on GPUs](https://davidbader.net/publication/2018-bgbb/). IEEE HPEC 2018, 2018 · [Author code](https://github.com/hornet-gt/hornet).
- [Hornet: An Efficient Data Structure for Dynamic Sparse Graphs and Matrices on GPUs](https://davidbader.net/publication/2018-bgbb/). IEEE HPEC 2018, 2018 · [Author code](https://github.com/hornet-gt/hornet).
- [GraphBLAST: A High-Performance Linear Algebra-based Graph Framework on the GPU](https://arxiv.org/abs/1908.01407). arXiv; later published in ACM TOPC, 2019 · [Author code](https://github.com/gunrock/graphblast).
- [TurboBC: A Memory Efficient and Scalable GPU Based Betweenness Centrality Algorithm in the Language of Linear Algebra](https://doi.org/10.1145/3458744.3474047). ACM/IEEE SC 2021, 2021 · [Author code](https://github.com/pcdslab/TurboBC).
- cuGraph Betweenness centrality — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
- cuGraph Eigenvector centrality — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
- cuGraph Katz centrality — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## Personalized PageRank and Random Walk with Restart {#personalized_pagerank_rwr}

Given one or more seed vertices, compute each vertex's steady-state visitation probability under a random walk that restarts to the seed distribution with fixed probability, and rank vertices by that score relative to the seeds.

$$
p=\alpha s+(1-\alpha)P^\top p
$$

s is the seed distribution, alpha the restart probability, and P the declared transition matrix.

**Example question:** “Which vertices are most relevant to these seeds?”

**Input assumptions.** direction: directed or undirected; weights: optional nonnegative; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** exact_or_converged requires the L1 residual below convergence_tolerance; approximate mode must disclose its error_bound.

**Required outputs:** `ranked_vertices`, `restart_probability_used`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`personalized-pagerank`](../explorer.md#problem/personalized_pagerank_rwr) | `cpp` | `libcugraph`, `kpar` | Parameter dependent |

**`personalized-pagerank`** — Seeded PageRank with explicit direction, weight and dangling policies. Full score port stays complete when the displayed ranking is filtered or capped.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run personalized-pagerank INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/personalized_pagerank_rwr) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/21_personalized_pagerank_rwr/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Gunrock: GPU Graph Analytics](https://arxiv.org/abs/1701.01170). ACM Transactions on Parallel Computing, 2017 · [Author code](https://github.com/gunrock/gunrock).
- [GraphBLAST: A High-Performance Linear Algebra-based Graph Framework on the GPU](https://arxiv.org/abs/1908.01407). arXiv; later published in ACM TOPC, 2019 · [Author code](https://github.com/gunrock/graphblast).
- [Realtime Top-k Personalized PageRank over Large Graphs on GPUs](https://vldb.org/pvldb/vol13/p15-shi.pdf). PVLDB 13(1), 2020 · [Author code](https://github.com/jmshi123/kPAR).
- cuGraph Personalized PageRank — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## Influence Maximization under Diffusion Models {#influence_maximization}

Given a directed graph with edge-level influence probabilities and a declared stochastic diffusion model, select a seed set of a given size that maximizes the expected number of vertices eventually activated.

$$
\max_{S\subseteq V,\ |S|=k}\mathbb E[|A(S)|]
$$

A(S) is the activated set under the declared diffusion model. Sampling or heuristic selection does not prove the optimum.

**Example question:** “Which seed group is expected to reach the most vertices?”

**Input assumptions.** direction: directed; weights: required as influence probability or threshold input; timestamps: ignored; vertex attributes: optional as threshold; edge attributes: optional.

**Guarantee.** Exact computation of expected_spread is #P-hard in general; guarantee_met=true requires the disclosed approximation_guarantee and failure_probability to hold under the estimation_method's established theoretical bounds.

**Required outputs:** `seed_set`, `expected_spread`, `guarantee_met`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`influence-maximization`](../explorer.md#problem/influence_maximization) | `cpp` | `superfuser` | Parameter dependent |

**`influence-maximization`** — Exact native IC/LT optimization, or explicitly requested SuperFuser independent-cascade heuristic with holdout spread estimation. The heuristic does not certify optimality or an approximation guarantee.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run influence-maximization INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/influence_maximization) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/28_influence_maximization/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [cuRipples: Influence Maximization on Multi-GPU Systems](https://eecs.wsu.edu/~ananth/papers/Minutoli_ICS20.pdf). ACM ICS 2020, 2020 · [Author code](https://github.com/pnnl/ripples).
- [gIM: GPU Accelerated RIS-Based Influence Maximization Algorithm](https://arxiv.org/abs/2009.07325). IEEE Transactions on Parallel and Distributed Systems, 2021 · [Author code](https://github.com/LIS-Laboratory/gim).
- [Fast and Parallel Influence Maximization using Fused Sampling and Memory Access Regularization](https://github.com/ggokturk/infuser). IEEE Transactions on Parallel and Distributed Systems, 2021 · [Author code](https://github.com/ggokturk/infuser).
- [DiFuseR: A Distributed Sketch-based Influence Maximization Algorithm for GPUs](https://arxiv.org/abs/2410.14047). The Journal of Supercomputing, 2024.
