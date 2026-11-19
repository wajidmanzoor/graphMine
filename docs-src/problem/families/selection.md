# Assignment & selection

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

Pick non-conflicting pairs or items, cover every edge, or colour without conflicts. Match pairs or assign workers to tasks, select independent vertices, cover connections with vertices, or assign colours under the declared conflict rules.

**Start with this question:** Pick non-conflicting pairs or items, cover every edge, or colour without conflicts.

[Explore these operations](../explorer.md#family/selection) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [Bipartite Matching and Linear Assignment](#bipartite_matching_assignment)
- [General-Graph Weighted Matching](#general_graph_weighted_matching)
- [Maximal Independent Set](#maximal_independent_set)
- [Maximum Independent Set](#maximum_independent_set)
- [Minimum Vertex Cover](#minimum_vertex_cover)
- [Vertex Coloring](#vertex_coloring)

## Bipartite Matching and Linear Assignment {#bipartite_matching_assignment}

Given a bipartite graph, find a matching (a set of edges with no shared endpoints) that is optimal under a declared objective: maximum cardinality, maximum total weight, or minimum total cost.

$$
\max_{M\subseteq E}\sum_{e\in M}w(e),\qquad \deg_M(v)\le1
$$

M is a matching across declared sides; cardinality and minimum-cost modes have distinct objectives.

**Example question:** “Assign these tasks to workers at minimum cost.”

**Input assumptions.** direction: undirected bipartite; weights: required for weighted objectives; timestamps: ignored; vertex attributes: required side label; edge attributes: ignored.

**Guarantee.** Exact mode requires optimal=true; this problem admits polynomial-time exact algorithms (augmenting paths, Hungarian algorithm), so approximate mode is only for extreme scale and must disclose approximation_bound.

**Required outputs:** `matching_edges`, `matching_size`, `objective_value`, `optimal`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`bipartite-matching`](../explorer.md#problem/bipartite_matching_assignment) | `cpp` | `hungarian-cuda` | Exact |

**`bipartite-matching`** — Exact cardinality, weight or cost matching with attributes.side=left|right on every vertex. Reject same-side edges and loops; keep the best parallel edge. Weighted objectives require explicit weights. Without required smaller-side coverage, empty matching may be optimal. Infeasible coverage has no witness port.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run bipartite-matching INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/bipartite_matching_assignment) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/31_bipartite_matching_assignment/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [GPU Accelerated Maximum Cardinality Matching Algorithms for Bipartite Graphs](https://doi.org/10.1007/978-3-642-40047-6_84). Euro-Par 2013, 2013 · [Author code](http://tda.gatech.edu/software/matchmaker2/index.html).
- [Fast block distributed CUDA implementation of the Hungarian algorithm](https://github.com/paclopes/HungarianGPU). Journal of Parallel and Distributed Computing, 2019 · [Author code](https://github.com/paclopes/HungarianGPU).
- cuGraph Dense Hungarian assignment — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## General-Graph Weighted Matching {#general_graph_weighted_matching}

Find a matching of high total nonnegative edge weight in an undirected graph without a bipartiteness assumption.

$$
\max_{M\subseteq E}\sum_{e\in M}w(e),\qquad \deg_M(v)\le1
$$

No bipartite partition is assumed. A heuristic profile need not attain the maximum.

**Example question:** “Choose disjoint pairs with the highest total weight.”

**Input assumptions.** direction: undirected; weights: required nonnegative; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Approximate mode returns a feasible matching with any proven bound disclosed; exact mode requires optimal=true.

**Required outputs:** `matching_edges`, `total_weight`, `optimal`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`weighted-matching`](../explorer.md#problem/general_graph_weighted_matching) | `cpp` | — | Exact |

**`weighted-matching`** — Exact maximum-weight matching on an undirected graph, with no cardinality constraint. Require nonnegative weights; discard loops and keep the largest parallel weight. Preserve selected original edge IDs and return exact rational totals over admitted binary64 weights. Zero-weight edges may be omitted.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run weighted-matching INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/general_graph_weighted_matching) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/44_general_graph_weighted_matching/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [A GPU Algorithm for Greedy Graph Matching](https://research-portal.uu.nl/en/publications/a-gpu-algorithm-for-greedy-graph-matching). Facing the Multicore-Challenge II, LNCS 7174, 2012 · [Author code](https://github.com/dmlc/dgl).
- [A GPU Algorithm for Greedy Graph Matching](https://research-portal.uu.nl/en/publications/a-gpu-algorithm-for-greedy-graph-matching). Facing the Multicore-Challenge II, LNCS 7174, 2012 · [Author code](https://github.com/rusty1s/pytorch_cluster).
- [Optimizing Approximate Weighted Matching on Nvidia Kepler K40](https://hpc.pnl.gov/people/hala/suitor.html). HiPC 2015, 2015 · [Author code](https://hpc.pnl.gov/people/hala/suitor.html).
- [AMG based on compatible weighted matching for GPUs](https://arxiv.org/abs/1810.04221). Research reference, 2018 · [Author code](https://github.com/bootcmatch/BootCMatchG).
- [Efficient Weighted Graph Matching on GPUs](https://doi.org/10.1109/SC41406.2024.00024). SC 2024, 2024.
- cuGraph Approximate weighted matching — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## Maximal Independent Set {#maximal_independent_set}

Find one independent vertex set that cannot be enlarged by adding any remaining vertex.

$$
E(G[S])=\varnothing,\quad\forall v\notin S:\ N(v)\cap S\ne\varnothing
$$

S is independent and cannot be enlarged by one vertex; it need not be largest.

**Example question:** “Find a nonconflicting group that cannot be extended.”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Independence and maximality are exact requirements; maximum cardinality is not required.

**Required outputs:** `vertices`, `size`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`maximal-independent-set`](../explorer.md#problem/maximal_independent_set) | `cpp` | `libcugraph` | Exact |

**`maximal-independent-set`** — Greedy maximal independent set with verified independence and maximality; no maximum-size claim. Undirected simple projection; discard loops and duplicate edges, ignore weights and preserve isolates.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run maximal-independent-set INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/maximal_independent_set) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/42_maximal_independent_set/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Lowering IrGL to CUDA](https://arxiv.org/abs/1607.05707). Research reference, 2016 · [Author code](https://github.com/IntelligentSoftwareSystems/Galois).
- [A High-Quality and Fast Maximal Independent Set Implementation for GPUs](https://userweb.cs.txstate.edu/~mb92/research/ECL-MIS/). ACM TOPC, 2018 · [Author code](https://userweb.cs.txstate.edu/~mb92/research/ECL-MIS/).
- [GraphBLAST: A High-Performance Linear Algebra-based Graph Framework on the GPU](https://arxiv.org/abs/1908.01407). arXiv; later published in ACM TOPC, 2019 · [Author code](https://github.com/gunrock/graphblast).
- [A Multi-GPU Algorithm for Computing Maximal Independent Sets in Large Graphs](https://github.com/burtscher/MG-MIS). ACM ICS 2025, 2025 · [Author code](https://github.com/burtscher/MG-MIS).
- cuGraph Maximal independent set — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## Maximum Independent Set {#maximum_independent_set}

Find an independent vertex set of maximum cardinality in a simple undirected graph.

$$
\alpha(G)=\max_{S:E(G[S])=\varnothing}|S|
$$

The selected vertices have no edges between them and maximum cardinality is the objective.

**Example question:** “What is the largest group with no internal connections?”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exact mathematical objective; implementations must declare approximation and termination status.

**Required outputs:** `independent_set`, `cardinality`, `optimality_proven`, `termination_reason`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`maximum-independent-set`](../explorer.md#problem/maximum_independent_set) | `cpp` | `cuda-ms`, `gpu-maximum-clique`, `maximum-clique-on-gpu` | Exact |

**`maximum-independent-set`** — Exact maximum independent set via maximum clique of the complement. Undirected simple projection; loops, duplicate edges and weights ignored. Complement construction and search are bounded.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run maximum-independent-set INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/maximum_independent_set) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/66_maximum_independent_set/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [DIFUSCO: Graph-based Diffusion Solvers for Combinatorial Optimization](https://papers.nips.cc/paper_files/paper/2023/hash/0ba520d93c3df592c83a611961314c98-Abstract-Conference.html). NeurIPS 2023, 2023 · [Author code](https://github.com/Edward-Sun/DIFUSCO).
- [Maximum Independent Set: Self-Training through Dynamic Programming](https://arxiv.org/abs/2310.18672). NeurIPS 2023, 2023 · [Author code](https://github.com/LIONS-EPFL/dynamic-MIS).
- [Differentiable Quadratic Optimization For the Maximum Independent Set Problem](https://proceedings.mlr.press/v267/alkhouri25a.html). ICML 2025, 2025 · [Author code](https://github.com/ledenmat/pCQO-mis-benchmark).

## Minimum Vertex Cover {#minimum_vertex_cover}

Find a smallest set of vertices touching every edge, or decide whether a cover of size at most k exists.

$$
\min_{S\subseteq V}|S|\quad\text{s.t. }\{u,v\}\cap S\ne\varnothing\ \forall\{u,v\}\in E
$$

Every edge must touch a selected vertex.

**Example question:** “What is the smallest set touching every relationship?”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exact mathematical objective; implementations must declare approximation and termination status.

**Required outputs:** `cover`, `cover_size`, `decision`, `optimality_proven`, `termination_reason`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`minimum-vertex-cover`](../explorer.md#problem/minimum_vertex_cover) | `cpp` | `cuda-ms`, `gpu-maximum-clique`, `maximum-clique-on-gpu` | Exact |

**`minimum-vertex-cover`** — Exact minimum vertex cover, or decision against k, from a maximum independent set. Undirected simple projection; loops, duplicate edges and weights ignored. Native complement construction and search are bounded.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run minimum-vertex-cover INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/minimum_vertex_cover) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/69_minimum_vertex_cover/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Parallel Vertex Cover Algorithms on GPUs](https://arxiv.org/abs/2204.10402). Research preprint, 2022 · [Author code](https://github.com/pky00/Parallel-Vertex-Cover-Algorithms-on-GPUs).
- [Maximum Independent Set: Self-Training through Dynamic Programming](https://arxiv.org/abs/2310.18672). NeurIPS 2023, 2023 · [Author code](https://github.com/LIONS-EPFL/dynamic-MIS).
- [Faster Vertex Cover Algorithms on GPUs with Component-Aware Parallel Branching](https://arxiv.org/abs/2512.18334). IEEE TPDS 37(2), 2026, 2025 · [Author code](https://github.com/HusseinAmro/component-aware-vertex-cover-gpu).

## Vertex Coloring {#vertex_coloring}

Assign colors so vertices within a declared graph distance receive different colors.

$$
c(u)\ne c(v)\quad\text{whenever }0<d(u,v)\le r
$$

r is the declared conflict distance. A valid coloring need not use the fewest possible colors.

**Example question:** “Assign nonconflicting colors to connected vertices.”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Coloring feasibility is exact; minimum chromatic number is not required.

**Required outputs:** `colors`, `color_count`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`vertex-coloring`](../explorer.md#problem/vertex_coloring) | `cpp` | `libcugraph` | Heuristic |

**`vertex-coloring`** — Proper greedy distance-1 or distance-2 coloring; no minimum-color claim. Undirected simple projection with isolates preserved. GPU colors the native C++ constructed distance conflict graph.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run vertex-coloring INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/vertex_coloring) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/43_vertex_coloring/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Efficient and High-quality Sparse Graph Coloring on the GPU](https://arxiv.org/abs/1606.06025). arXiv; Concurrency and Computation 2017, 2016 · [Author code](https://github.com/chenxuhao/gardenia).
- [Gunrock: GPU Graph Analytics](https://arxiv.org/abs/1701.01170). ACM Transactions on Parallel Computing, 2017 · [Author code](https://github.com/gunrock/gunrock).
- [GraphBLAST: A High-Performance Linear Algebra-based Graph Framework on the GPU](https://arxiv.org/abs/1908.01407). arXiv; later published in ACM TOPC, 2019 · [Author code](https://github.com/gunrock/graphblast).
- cuGraph Vertex coloring — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
