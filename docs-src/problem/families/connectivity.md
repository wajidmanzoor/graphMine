# Connectivity, cuts & trees

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

Is it connected, where does it break, or what is the cheapest way to connect it? Find components and biconnected blocks, identify capacity bottlenecks with flow and cuts, or connect vertices and required groups with trees.

**Start with this question:** Is it connected, where does it break, or what is the cheapest way to connect it?

[Explore these operations](../explorer.md#family/connectivity) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [Connected Components (Weakly and Strongly Connected)](#connected_components)
- [Biconnected Components, Articulation Points and Bridges](#biconnected_components)
- [Maximum Flow and Minimum s-t Cut](#max_flow_min_cut)
- [Minimum and Maximum Spanning Trees and Forests](#spanning_tree_forest)
- [Group Steiner Tree](#group_steiner_tree)

## Connected Components (Weakly and Strongly Connected) {#connected_components}

Partition all vertices into maximal groups such that every pair of vertices within a group is connected according to a declared connectivity definition: weak (undirected) connectivity, or strong (directed, mutual-reachability) connectivity.

$$
u\sim v\iff u\leadsto v\text{ and }v\leadsto u
$$

This defines strong components. Weak components ignore direction before testing connectivity.

**Example question:** “Which groups are disconnected from one another?”

**Input assumptions.** direction: directed or undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** This problem is always solved exactly; component identity is a decidable equivalence relation with no approximate mode.

**Required outputs:** `component_assignment`, `component_count`, `component_sizes`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`connected-components`](../explorer.md#problem/connected_components) | `cpp` | `libcugraph`, `ecl-scc` | Exact |

**`connected-components`** — Weak or strong connectivity. Weak mode uses an undirected projection; strong mode preserves direction. Loops, duplicate edges and weights do not affect membership.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run connected-components INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/connected_components) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/35_connected_components/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Gunrock: GPU Graph Analytics](https://arxiv.org/abs/1701.01170). ACM Transactions on Parallel Computing, 2017 · [Author code](https://github.com/gunrock/gunrock).
- [A High-Performance Connected Components Implementation for GPUs](https://doi.org/10.1145/3208040.3208041). ACM HPDC 2018, 2018 · [Author code](https://cs.txstate.edu/~burtscher/research/ECL-CC/).
- [Hornet: An Efficient Data Structure for Dynamic Sparse Graphs and Matrices on GPUs](https://davidbader.net/publication/2018-bgbb/). IEEE HPEC 2018, 2018 · [Author code](https://github.com/hornet-gt/hornet).
- [GraphBLAST: A High-Performance Linear Algebra-based Graph Framework on the GPU](https://arxiv.org/abs/1908.01407). arXiv; later published in ACM TOPC, 2019 · [Author code](https://github.com/gunrock/graphblast).
- [A GPU Algorithm for Detecting Strongly Connected Components](https://doi.org/10.1145/3581784.3607071). ACM ICS 2023, 2023 · [Author code](https://github.com/burtscher/ECL-SCC).
- cuGraph Strongly connected components — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
- cuGraph Weakly connected components — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).

## Biconnected Components, Articulation Points and Bridges {#biconnected_components}

Compute vertex-biconnected blocks of a simple undirected graph, plus vertices and edges whose removal increases component count.

$$
B\text{ remains connected after removing any one vertex}
$$

Blocks are maximal sets under this condition; bridges and isolated cases follow the contract.

**Example question:** “Which single vertices or edges hold this network together?”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exact decomposition. Ordinary connected components do not satisfy this problem.

**Required outputs:** `blocks`, `articulation_vertices`, `bridges`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`biconnected-components`](../explorer.md#problem/biconnected_components) | `cpp` | — | Exact |

**`biconnected-components`** — Exact vertex-biconnected edge blocks, bridges and articulation vertices. Undirected input; loops discarded and parallel edges collapsed. Every normalized edge keeps its first original ID and all source edge IDs.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run biconnected-components INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/biconnected_components) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/56_biconnected_components/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [GPU Algorithms for Biconnected Components on Large Graphs](https://github.com/Abhijeetkumar96/FAST-BCC-on-GPUs). IPDPS 2026, 2026 · [Author code](https://github.com/Abhijeetkumar96/FAST-BCC-on-GPUs).
- [GPU Algorithms for Biconnected Components on Large Graphs](https://github.com/Abhijeetkumar96/FAST-BCC-on-GPUs). IPDPS 2026, 2026 · [Author code](https://github.com/Abhijeetkumar96/FAST-BCC-on-GPUs).
- [GPU Algorithms for Biconnected Components on Large Graphs](https://github.com/Abhijeetkumar96/FAST-BCC-on-GPUs). IPDPS 2026, 2026 · [Author code](https://github.com/Abhijeetkumar96/FAST-BCC-on-GPUs).

## Maximum Flow and Minimum s-t Cut {#max_flow_min_cut}

Given a capacitated graph and distinct source and sink vertices, compute a maximum feasible flow and a minimum-capacity separating cut. With optional vertex capacities, the cut can contain both original edges and capacity-limited vertices.

$$
\max_f |f|=\min_{(S,T)}c(S,T)
$$

Flow respects capacities and conservation. S contains the source and T the sink; optional vertex capacities require the corresponding cut model.

**Example question:** “What is the maximum flow between these terminals?”

**Input assumptions.** direction: directed; weights: required nonnegative as capacity; timestamps: ignored; vertex attributes: ignored; edge attributes: optional.

**Guarantee.** Exact mode requires optimal=true and max_flow_value == min_cut_value within tolerance.

**Required outputs:** `max_flow_value`, `min_cut_value`, `min_cut_edges`, `optimal`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`max-flow-min-cut`](../explorer.md#problem/max_flow_min_cut) | `cpp` | `ecl-maxflow` | Exact |

**`max-flow-min-cut`** — Exact rational flow and cut certificate. Sum parallel capacities, discard loops and treat undirected edges as two directed arcs. Optional vertex capacities use typed {vertex,capacity} records and include explicitly limited terminals. Mixed cuts return original edge IDs plus cut vertices.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run max-flow-min-cut INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/max_flow_min_cut) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/22_max_flow_min_cut/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [An Efficient Push-Relabel Implementation for Max-Flow Computations on GPUs](https://userweb.cs.txstate.edu/~mb92/papers/ipccc25a.pdf). IPCCC 2025, 2025 · [Author code](https://github.com/burtscher/ECL-MaxFlow).
- [Novel GPU-Based Method for the Generalized Maximum Flow Problem](https://www.mdpi.com/2079-3197/13/2/40). Computation (MDPI) 13(2):40, 2025.
- [Accelerating Push-Relabel Algorithm on GPU via Two-Level Parallelism Paradigm and Efficient CSR Designs](https://github.com/NTUDDSNLab/WBPR). IEEE HPEC 2025, 2025 · [Author code](https://github.com/NTUDDSNLab/WBPR).

## Minimum and Maximum Spanning Trees and Forests {#spanning_tree_forest}

Select an acyclic spanning subgraph minimizing or maximizing total edge weight independently within each connected component.

$$
F^*\in\arg\min_F\sum_{e\in F}w(e)
$$

F spans each connected component without cycles. Maximum mode replaces the minimum with a maximum.

**Example question:** “Connect every location at minimum total cost.”

**Input assumptions.** direction: undirected; weights: required finite; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Globally optimal forest; equal-weight alternatives are valid.

**Required outputs:** `forest_edges`, `total_weight`, `component_count`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`spanning-tree-forest`](../explorer.md#problem/spanning_tree_forest) | `cpp` | `libcugraph` | Exact |

**`spanning-tree-forest`** — Undirected weighted forests with isolates retained. Negative lengths are allowed. Keep minimum or maximum parallel weights according to the objective; discard loops.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run spanning-tree-forest INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/spanning_tree_forest) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/41_spanning_tree_forest/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Lowering IrGL to CUDA](https://arxiv.org/abs/1607.05707). Research reference, 2016 · [Author code](https://github.com/IntelligentSoftwareSystems/Galois).
- [GARDENIA: A Domain-specific Benchmark Suite for Next-generation Accelerators](https://arxiv.org/abs/1708.04567). arXiv; ACM JETC 2018, 2017 · [Author code](https://github.com/chenxuhao/gardenia).
- [Gunrock: GPU Graph Analytics](https://arxiv.org/abs/1701.01170). ACM Transactions on Parallel Computing, 2017 · [Author code](https://github.com/gunrock/gunrock).

## Group Steiner Tree {#group_steiner_tree}

Given an edge-weighted graph and a collection of potentially overlapping vertex groups, find a minimum-weight connected subtree that includes at least one vertex from every group.

$$
\min_T\sum_{e\in T}w(e)\quad\text{s.t. }V(T)\cap G_i\ne\varnothing\ \forall i
$$

T is a connected tree and each G_i is a required group.

**Example question:** “What is the cheapest tree reaching at least one member of each group?”

**Input assumptions.** direction: undirected; weights: required nonnegative; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Exact mode requires optimal=true; approximate mode must disclose approximation_bound.

**Required outputs:** `tree_edges`, `tree_weight`, `selected_vertices`, `optimal`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`group-steiner-tree`](../explorer.md#problem/group_steiner_tree) | `cpp` | `gpu4gst` | Exact |

**`group-steiner-tree`** — Exact bounded vertex-subset optimization with a minimum spanning tree for each feasible induced subgraph. Covers every group and required vertex, allowing overlapping representatives. Undirected nonnegative weighted input, loops removed, cheapest original parallel edge retained. Reports exact rational cost or certified infeasibility.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run group-steiner-tree INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/group_steiner_tree) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/27_group_steiner_tree/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Accelerating Computation of Steiner Trees on GPUs](https://doi.org/10.1007/s10766-021-00723-0). International Journal of Parallel Programming, 2021 · [Author code](https://github.com/mrprajesh/gpuSteiner).
- [GPU-Accelerated VLSI Routing using Group Steiner Trees](https://jocse.org/articles/8/1/4/). Journal of Computational Science Education, 2022 · [Author code](https://github.com/yosephbasileal/group-steiner-vlsi-routing-gpu).
- [Fast Optimal Group Steiner Tree Search using GPUs](https://dl.acm.org/doi/10.1145/3769792). Proc. ACM Manag. Data (SIGMOD) 3(6), article 327, 2025 · [Author code](https://github.com/toziki/GPU4GST-sigmod).
