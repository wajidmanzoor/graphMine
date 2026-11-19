# Paths & reachability

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

How do I get from A to B, what can reach what, or in what order? Search, optimize or enumerate routes, compute reachability, or order dependencies. Bounded path queries also exist in records; choose this family when the goal is route analysis or dependency order.

**Start with this question:** How do I get from A to B, what can reach what, or in what order?

[Explore these operations](../explorer.md#family/paths) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [Breadth-First Search and Unweighted Shortest Paths](#breadth_first_search)
- [Weighted Single-Source Shortest Paths](#single_source_shortest_paths)
- [Many-Source and All-Pairs Shortest Distances](#many_source_shortest_paths)
- [Single-Source Widest Paths](#widest_paths)
- [Temporal Fastest and Earliest-Arrival Paths](#temporal_fastest_paths)
- [Top-k Critical Paths in DAGs](#top_k_critical_paths_dag)
- [Hop-Constrained Simple Path and Cycle Enumeration](#hop_constrained_cycle_path_enumeration)
- [Transitive Closure and Reachability Indexing](#transitive_closure_reachability)
- [Topological Sorting and DAG Levels](#topological_sort)

## Breadth-First Search and Unweighted Shortest Paths {#breadth_first_search}

Compute minimum hop distances and optional predecessor paths from one or more source vertices.

$$
d(s,v)=\min_{p:s\leadsto v}|p|
$$

The distance is the number of edges in a shortest path; unreachable vertices have no finite distance.

**Example question:** “How many hops connect this person to everyone else?”

**Input assumptions.** direction: directed or undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Distances are exact within the declared cutoff. A predecessor may be any valid shortest-path predecessor.

**Required outputs:** `distances`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`breadth-first-search`](../explorer.md#problem/breadth_first_search) | `cpp` | `libcugraph` | Exact |

**`breadth-first-search`** — Minimum hop distances with explicit independent or nearest-source searches. Preserve direction; discard loops and collapse duplicate arcs; weights are ignored. IDs are signed int64 or strings.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run breadth-first-search INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/breadth_first_search) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/38_breadth_first_search/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [GARDENIA: A Domain-specific Benchmark Suite for Next-generation Accelerators](https://arxiv.org/abs/1708.04567). arXiv; ACM JETC 2018, 2017 · [Author code](https://github.com/chenxuhao/gardenia).
- [Gunrock: GPU Graph Analytics](https://arxiv.org/abs/1701.01170). ACM Transactions on Parallel Computing, 2017 · [Author code](https://github.com/gunrock/gunrock).
- [Hornet: An Efficient Data Structure for Dynamic Sparse Graphs and Matrices on GPUs](https://davidbader.net/publication/2018-bgbb/). IEEE HPEC 2018, 2018 · [Author code](https://github.com/hornet-gt/hornet).
- [GraphBLAST: A High-Performance Linear Algebra-based Graph Framework on the GPU](https://arxiv.org/abs/1908.01407). arXiv; later published in ACM TOPC, 2019 · [Author code](https://github.com/gunrock/graphblast).
- cuGraph Breadth-first traversal — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## Weighted Single-Source Shortest Paths {#single_source_shortest_paths}

Compute minimum path-weight sums from one source to every vertex in a graph with nonnegative edge weights.

$$
d(s,v)=\min_{p:s\leadsto v}\sum_{e\in p}w(e)
$$

Edge weights w are nonnegative path costs.

**Example question:** “What is the lowest-cost route from this location?”

**Input assumptions.** direction: directed or undirected; weights: required nonnegative; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exact distances up to declared floating-point tolerance; negative weights are outside this contract.

**Required outputs:** `distances`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`single-source-shortest-paths`](../explorer.md#problem/single_source_shortest_paths) | `cpp` | `libcugraph` | Backend dependent |

**`single-source-shortest-paths`** — Nonnegative lengths; preserve direction, drop loops and keep minimum parallel length. CPU returns exact rational costs over admitted binary64 weights; GPU returns float64 costs. Cutoff is inclusive.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run single-source-shortest-paths INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/single_source_shortest_paths) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/39_single_source_shortest_paths/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [GARDENIA: A Domain-specific Benchmark Suite for Next-generation Accelerators](https://arxiv.org/abs/1708.04567). arXiv; ACM JETC 2018, 2017 · [Author code](https://github.com/chenxuhao/gardenia).
- [Gunrock: GPU Graph Analytics](https://arxiv.org/abs/1701.01170). ACM Transactions on Parallel Computing, 2017 · [Author code](https://github.com/gunrock/gunrock).
- [Hornet: An Efficient Data Structure for Dynamic Sparse Graphs and Matrices on GPUs](https://davidbader.net/publication/2018-bgbb/). IEEE HPEC 2018, 2018 · [Author code](https://github.com/hornet-gt/hornet).
- [GraphBLAST: A High-Performance Linear Algebra-based Graph Framework on the GPU](https://arxiv.org/abs/1908.01407). arXiv; later published in ACM TOPC, 2019 · [Author code](https://github.com/gunrock/graphblast).
- cuGraph Single-source shortest paths — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## Many-Source and All-Pairs Shortest Distances {#many_source_shortest_paths}

Compute a matrix of minimum path-weight sums for selected origins and destinations, including all-pairs queries.

$$
D_{ij}=d(s_i,t_j)
$$

D contains shortest-path costs for the requested origins and destinations.

**Example question:** “What are the shortest distances between these locations?”

**Input assumptions.** direction: directed or undirected; weights: optional nonnegative; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exact within numeric tolerance. Batched SSSP and matrix-based implementations must return the same distances.

**Required outputs:** `distance_matrix`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`many-source-shortest-paths`](../explorer.md#problem/many_source_shortest_paths) | `cpp` | `libcugraph` | Backend dependent |

**`many-source-shortest-paths`** — Selected origins and destinations, or all vertices for null. Nonnegative lengths, minimum parallel length and preserved direction; CPU exact costs and GPU float64 costs.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run many-source-shortest-paths INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/many_source_shortest_paths) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/40_many_source_shortest_paths/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [A Multi-Stage CUDA Kernel for Floyd-Warshall](https://arxiv.org/abs/1001.4108). Research preprint, 2010 · [Author code](https://github.com/MTB90/cuda-floyd_warshall).
- [The Floyd-Warshall Algorithm Re-implemented Using 3D-Tensors and Hardware Acceleration](https://arxiv.org/abs/2310.03983). Research reference, 2023 · [Author code](https://github.com/tanjary21/APSP_GPU).
- [The Floyd-Warshall Algorithm Re-implemented Using 3D-Tensors and Hardware Acceleration](https://arxiv.org/abs/2310.03983). Research reference, 2023 · [Author code](https://github.com/tanjary21/APSP_GPU).
- cuGraph origin-destination shortest distances (software entry; no paper collected). Research reference, date not recorded · [Author code](https://github.com/rapidsai/cugraph).

## Single-Source Widest Paths {#widest_paths}

For each vertex v, maximize the minimum edge capacity along a directed path from a designated source to v.

$$
b(s,v)=\max_{p:s\leadsto v}\min_{e\in p}c(e)
$$

c is edge capacity; a path is only as wide as its smallest capacity.

**Example question:** “Which route has the largest bottleneck capacity?”

**Input assumptions.** direction: directed or undirected; weights: required finite nonnegative capacities; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exact mathematical objective; implementations must declare approximation and termination status.

**Required outputs:** `bottleneck_capacity`, `reachable`, `is_source`, `predecessor`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`widest-paths`](../explorer.md#problem/widest_paths) | `cpp` | — | Exact |

**`widest-paths`** — Exact max-min capacities with a predecessor witness, preserving direction. Every edge needs nonnegative capacity; loops discarded and largest parallel capacity wins. Zero is reachable. Source infinity and unreachable nulls have distinct flags.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run widest-paths INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/widest_paths) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/61_widest_paths/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- nvGRAPH max-min widest path — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/nvgraph).

## Temporal Fastest and Earliest-Arrival Paths {#temporal_fastest_paths}

Find time-respecting journeys minimizing elapsed duration or arrival time in a directed temporal graph.

$$
p^*\in\arg\min_{p\in\mathcal J(s,t)}\bigl(t_{\mathrm{arrival}}(p)-t_{\mathrm{departure}}(p)\bigr)
$$

The set of journeys J obeys edge times. Earliest-arrival mode minimizes arrival time instead of duration.

**Example question:** “What is the fastest time-respecting journey?”

**Input assumptions.** direction: directed; weights: ignored; timestamps: required numeric departure time; vertex attributes: ignored; edge attributes: required nonnegative duration.

**Guarantee.** Exact objective values; chronological path enumeration alone is insufficient.

**Required outputs:** `values`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`temporal-paths`](../explorer.md#problem/temporal_fastest_paths) | `cpp` | — | Exact |

**`temporal-paths`** — Exact rational time-expanded shortest paths. Directed event input; every edge needs a timestamp and nonnegative duration attribute. Waiting is allowed. Fastest duration excludes waiting before initial departure. Inclusive ready time and deadline preserve distinct parallel events.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run temporal-paths INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/temporal_fastest_paths) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/57_temporal_fastest_paths/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [GPU Algorithm for Earliest Arrival Time Problem in Public Transport Networks](https://arxiv.org/abs/1912.00966). arXiv; HiPC 2020, 2019.
- [GPU Algorithms for Fastest Path Problem in Temporal Graphs](https://doi.org/10.1145/3673038.3673105). ICPP 2024, 2024.
- [TempGraph: An Efficient Chain-driven Temporal Graph Computing Framework on the GPU](https://doi.org/10.1145/3676642.3736116). ASPLOS 2025, 2025.

## Top-k Critical Paths in DAGs {#top_k_critical_paths_dag}

Return up to k distinct source-to-sink paths of greatest total edge delay in a directed acyclic graph.

$$
\operatorname{TopK}_{p:s\leadsto t}\;\sum_{e\in p}w(e)
$$

Paths run from declared sources to sinks in a directed acyclic graph; w is delay.

**Example question:** “Which dependency paths have the greatest total delay?”

**Input assumptions.** direction: directed; weights: required finite; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exact top-k ranking; equal-cost ties may be selected arbitrarily at the kth boundary.

**Required outputs:** `paths`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`top-k-critical-paths`](../explorer.md#problem/top_k_critical_paths_dag) | `cpp` | — | Exact |

**`top-k-critical-paths`** — Exact rational k-best DAG paths, retaining parallel edge identities and negative weights. Omitted sources and sinks select zero-in/out-degree vertices. A zero-edge path is included when a source is also a sink. Finishing top-k does not imply the path collection is exhaustive.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run top-k-critical-paths INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/top_k_critical_paths_dag) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/58_top_k_critical_paths_dag/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [GPU-accelerated Path-based Timing Analysis](https://doi.org/10.1109/DAC18074.2021.9586316). DAC 2021, 2021.
- [HeteroCPPR: Accelerating Common Path Pessimism Removal with Heterogeneous CPU-GPU Parallelism](https://tsung-wei-huang.github.io/publications/). ICCAD 2021, 2021.
- [G-PathGen: An Efficient GPU-Parallel k-Critical Path Generation Algorithm](https://yi-huaaa.github.io/publications/g-pathgen/). ICS 2026, 2026.

## Hop-Constrained Simple Path and Cycle Enumeration {#hop_constrained_cycle_path_enumeration}

Given a directed graph and a hop bound k, enumerate every simple (vertex-disjoint except endpoints) s-t path with at most k edges, or every simple cycle through a given vertex or edge with at most k edges.

$$
\mathcal P_k(s,t)=\{p:s\leadsto t,\ p\text{ simple},\ \ell(p)\le k\}
$$

The hop length is ell. Cycle mode instead closes a simple path through the requested vertex or edge.

**Example question:** “List simple paths between these vertices within four hops.”

**Input assumptions.** direction: directed; weights: ignored unless requested; timestamps: optional for temporal ordering variant; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** complete=true requires no qualifying path/cycle within scope was omitted; complete=false is only acceptable when result_limit truncated output.

**Required outputs:** `paths_or_cycles`, `result_count`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`bounded-paths-cycles`](../explorer.md#problem/hop_constrained_cycle_path_enumeration) | `cpp` | — | Exact |

**`bounded-paths-cycles`** — Exact directed simple edge paths and cycles up to max_hops. Drop loops; collapse to first parallel edge or retain identities. Optional strict chronological order applies after canonical cycle rotation. A result cap retains the shortest sequences while the total count remains exhaustive.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run bounded-paths-cycles INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/hop_constrained_cycle_path_enumeration) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/26_hop_constrained_cycle_path_enumeration/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [A GPU-based parallel algorithm for enumerating all chordless cycles in graphs](https://arxiv.org/abs/1410.4876). arXiv preprint, 2014.
- [Fast parallel algorithms for finding elementary circuits of a directed graph: a GPU-based approach](https://link.springer.com/article/10.1007/s11227-022-04835-3). The Journal of Supercomputing, 2022.
- cuGraph Elementary cycle enumeration — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## Transitive Closure and Reachability Indexing {#transitive_closure_reachability}

Given a directed graph, determine for queried vertex pairs whether the target is reachable from the source via a directed path, and optionally materialize or index full reachability to answer many such queries efficiently.

$$
R_{uv}=\mathbf1[\exists p:u\leadsto v]
$$

The contract declares whether zero-length paths count as reachability.

**Example question:** “Can this vertex reach that vertex?”

**Input assumptions.** direction: directed; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Reachability is always answered exactly; no approximate mode is defined for this problem.

**Required outputs:** `reachability_results`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`transitive-closure`](../explorer.md#problem/transitive_closure_reachability) | `cpp` | `gdlog` | Exact |

**`transitive-closure`** — Exact reflexive reachability: every vertex reaches itself by a zero-length path. Preserve graph direction, ignore weights, loops and duplicates. Count-only closure has a complete scalar and incomplete pair-list port.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run transitive-closure INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/transitive_closure_reachability) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/33_transitive_closure_reachability/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Anti-Section Transitive Closure](https://ieeexplore.ieee.org/document/9680370/). IEEE HiPC 2021, 2021.
- [Optimizing Datalog for the GPU](https://doi.org/10.1145/3669940.3707274). ACM PPoPP 2025, 2024 · [Author code](https://github.com/harp-lab/gdlog).
- [cuRPQ: A High-Performance GPU-Based Framework for Processing Regular and Conjunctive Regular Path Queries](https://arxiv.org/abs/2602.20748). ACM SIGMOD 2026, 2026.

## Topological Sorting and DAG Levels {#topological_sort}

Determine whether a directed graph is acyclic and return a valid topological vertex order and optional dependency levels.

$$
\pi(u)<\pi(v)\quad\forall (u,v)\in E
$$

pi is a vertex ordering; a directed cycle prevents such an ordering.

**Example question:** “In which order can I process these dependencies?”

**Input assumptions.** direction: directed; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exact acyclicity and ordering; algorithms may reject cyclic input with an explicit diagnostic.

**Required outputs:** `is_dag`, `order`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`topological-sort`](../explorer.md#problem/topological_sort) | `cpp` | — | Exact |

**`topological-sort`** — Return a deterministic topological order. Reject directed cycles, including self-loops. Duplicate arcs collapse; weights are ignored.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run topological-sort INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/topological_sort) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/45_topological_sort/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Parallel Depth-First Search for Directed Acyclic Graphs](https://mgarland.org/papers/2017/dfs/). NVIDIA technical report; IA3 2017, 2017.
- cuGraph frontier-based topological levels (software entry; no paper collected). Research reference, date not recorded · [Author code](https://github.com/rapidsai/cugraph).
- [GPU-Accelerated Computation of Persistent Homology for Topological Analysis of Image Data](https://arxiv.org/abs/2610.10959). TPAMI 2026 accepted, 2026 · [Author code](https://github.com/seravee08/GPU-Computation-of-Persistent-Homology-for-Image-Data).
