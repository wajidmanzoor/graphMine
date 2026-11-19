# Counting motifs

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

How many small shapes (triangles, butterflies, graphlets, motifs, timed motifs) are there? Count or list the supported shapes, including updates to triangle counts and ordered temporal events. Bipartite and temporal input requirements determine eligibility, not separate families.

**Start with this question:** How many small shapes (triangles, butterflies, graphlets, motifs, timed motifs) are there?

[Explore these operations](../explorer.md#family/motifs) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [Triangle Counting and Listing](#triangle_counting_listing)
- [Butterfly Counting and (alpha,beta)-Core Decomposition on Bipartite Graphs](#butterfly_counting_bipartite)
- [Graphlet Counting](#graphlet_counting)
- [Graph Motif Counting](#graph_motif_counting)
- [Temporal Motif Mining](#temporal_motif_mining)

## Triangle Counting and Listing {#triangle_counting_listing}

Count all unordered triples of vertices connected by all three possible edges and optionally list the triples or their per-vertex and per-edge participation counts.

$$
T(G)=\sum_{S\subseteq V,\ |S|=3}\mathbf1[G[S]\text{ complete}]
$$

Each unordered triple is counted once after the contract's normalization.

**Example question:** “How many triangles are in this graph?”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** The global count and requested participation counts are exact.

**Required outputs:** `global_triangle_count`, `instances_complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`dynamic-triangle-counting`](../explorer.md#problem/triangle_counting_listing) | `cpp` | `edtc` | Exact |
| [`triangle-counting`](../explorer.md#problem/triangle_counting_listing) | `cpp` | `tot`, `wetric` | Exact |

**`dynamic-triangle-counting`** — Exact deletion-before-insertion batch on an undirected simple graph. Reject repeated updates, absent deletions and existing insertions; preserve external IDs. EDTC GPU counts are checked against bounded native materialization.

**`triangle-counting`** — Count three-vertex cliques of an undirected graph. Discard loops and collapse duplicate edges; weights are ignored. GPU enumeration uses native CPU materialization with count verification.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run dynamic-triangle-counting INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/triangle_counting_listing) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/10_triangle_counting_listing/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Gunrock: GPU Graph Analytics](https://arxiv.org/abs/1701.01170). ACM Transactions on Parallel Computing, 2017 · [Author code](https://github.com/gunrock/gunrock).
- [Hornet: An Efficient Data Structure for Dynamic Sparse Graphs and Matrices on GPUs](https://davidbader.net/publication/2018-bgbb/). IEEE HPEC 2018, 2018 · [Author code](https://github.com/hornet-gt/hornet).
- [GraphBLAST: A High-Performance Linear Algebra-based Graph Framework on the GPU](https://arxiv.org/abs/1908.01407). arXiv; later published in ACM TOPC, 2019 · [Author code](https://github.com/gunrock/graphblast).
- [Triangle Counting on Tensor Cores](https://doi.org/10.1109/TPDS.2025.3606878). IEEE TPDS, 2025 · [Author code](https://github.com/yuang-chen/ToT-TPDS25).
- [Wedge-Parallel Triangle Counting for GPUs](https://doi.org/10.1007/978-3-031-99872-0_1). Euro-Par 2025, 2025 · [Author code](https://github.com/jeffreyspaan/wedge-parallel-triangle-counting).
- cuGraph Vertex triangle counting — upstream implementation documentation. Official upstream implementation and API documentation, 2026 · [Author code](https://github.com/rapidsai/cugraph).
- [Exact Triangle Counting for Dynamic Graphs on GPU](https://doi.org/10.1109/TPDS.2025.3627974). IEEE TPDS, 2026 · [Author code](https://github.com/WXZ0v0/EDTC).

## Butterfly Counting and (alpha,beta)-Core Decomposition on Bipartite Graphs {#butterfly_counting_bipartite}

Given a bipartite graph, count butterflies (complete 2x2 bicliques) globally and per vertex/edge, and optionally compute maximal vertex sets satisfying separate left/right thresholds. core_measure explicitly distinguishes conventional degree-based (alpha,beta)-cores from the butterfly-participation variant.

$$
B(G)=\sum_{\{u,v\}\subseteq L}\binom{|N(u)\cap N(v)|}{2}
$$

Each butterfly has two vertices on each side and all four cross edges.

**Example question:** “How many two-by-two complete groups are in this bipartite graph?”

**Input assumptions.** direction: undirected bipartite; weights: ignored; timestamps: ignored; vertex attributes: required side label; edge attributes: ignored.

**Guarantee.** Exact mode requires every butterfly to be counted exactly once; approximate mode must disclose its bound.

**Required outputs:** `butterfly_count`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`butterfly-counting`](../explorer.md#problem/butterfly_counting_bipartite) | `cpp` | `graphminer`, `gamma-butterfly` | Exact |

**`butterfly-counting`** — Exact 2-by-2 biclique counts, participation and alpha/beta cores. Every vertex requires attributes.side=left|right. Reject directed input, loops and same-side edges; collapse duplicates. Core thresholds explicitly use degree or butterfly participation.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run butterfly-counting INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/butterfly_counting_bipartite) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/23_butterfly_counting_bipartite/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Efficient and Scalable Graph Pattern Mining on GPUs](https://www.usenix.org/conference/osdi22/presentation/chen). USENIX OSDI 2022, 2022 · [Author code](https://github.com/chenxuhao/GraphMiner).
- [A Graph Pattern Mining Framework for Large Graphs on GPU](https://doi.org/10.1007/s00778-024-00883-8). The VLDB Journal, 2024 · [Author code](https://github.com/pkumod/GAMMA).
- [Efficient Load-Balanced Butterfly Counting on GPU](https://doi.org/10.14778/3551793.3551806). PVLDB 15(11), 2022.
- [Accelerating Biclique Counting on GPU](https://arxiv.org/abs/2403.07858). IEEE ICDE 2024, 2024.

## Graphlet Counting {#graphlet_counting}

Classify and count small connected induced subgraphs by their unlabeled isomorphism class, optionally including per-vertex orbit participation.

$$
N_H(G)=|\{S\subseteq V:G[S]\cong H\}|
$$

H is a connected induced graphlet; each vertex subset is counted once by its isomorphism class.

**Example question:** “How many induced graphlets of each shape occur?”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Class counts and requested orbit counts are exact.

**Required outputs:** `count_by_graphlet`, `graphlet_dictionary`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`graphlet-counting`](../explorer.md#problem/graphlet_counting) | `cpp` | — | Exact |

**`graphlet-counting`** — Native isomorphism classification against the complete connected undirected graph atlas for sizes two through seven. Static atlas IDs and exact automorphism orbits are embedded; Python is not required. Discard loops and duplicate edges, ignore weights. Counts and optional orbit participation stay complete when memberships are capped.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run graphlet-counting INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/graphlet_counting) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/12_graphlet_counting/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Efficient and Scalable Graph Pattern Mining on GPUs](https://www.usenix.org/conference/osdi22/presentation/chen). USENIX OSDI 2022, 2022 · [Author code](https://github.com/chenxuhao/GraphMiner).
- [Efficient and Scalable Graph Pattern Mining on GPUs](https://www.usenix.org/conference/osdi22/presentation/chen). USENIX OSDI 2022, 2022 · [Author code](https://github.com/chenxuhao/GraphMiner).
- [Pangolin: An Efficient and Flexible Graph Pattern Mining System on CPU and GPU](https://arxiv.org/abs/1911.06969). PVLDB 2020, 2019 · [Author code](https://github.com/chenxuhao/GraphMiner).

## Graph Motif Counting {#graph_motif_counting}

Count occurrences of one or more supplied small structural patterns in a directed or undirected graph.

$$
N_H(G)=|\operatorname{occurrences}(H,G)|
$$

The declared motif, inducedness, and symmetry rules define an occurrence.

**Example question:** “Count occurrences of this small graph pattern.”

**Input assumptions.** direction: must match each motif; weights: ignored; timestamps: ignored; vertex attributes: ignored; edge attributes: ignored.

**Guarantee.** Counts are exact; listing may be capped but must disclose completeness.

**Required outputs:** `count_by_motif`, `instances_complete_by_motif`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`motif-counting`](../explorer.md#problem/graph_motif_counting) | `cpp` | `graphminer`, `graphset`, `dumato` | Exact |

**`motif-counting`** — Exact structural embeddings with explicit occurrence identity: all mappings or unique vertex-set and image-edge classes. Preserve direction; simple projections discard loops, duplicate edges and weights. Non-induced motifs on the same vertex set can be distinct instances. Counts remain complete when lists are capped.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run motif-counting INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/graph_motif_counting) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/11_graph_motif_counting/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Efficient and Scalable Graph Pattern Mining on GPUs](https://www.usenix.org/conference/osdi22/presentation/chen). USENIX OSDI 2022, 2022 · [Author code](https://github.com/chenxuhao/GraphMiner).
- [GraphSet: High Performance Graph Mining through Equivalent Set Transformations](https://doi.org/10.1145/3581784.3613213). SC 2023, 2023 · [Author code](https://github.com/sth1997/GraphSet).
- [DuMato: A Dynamic GPU System for Graph Pattern Mining](https://doi.org/10.1016/j.jpdc.2024.104903). Journal of Parallel and Distributed Computing, 2024 · [Author code](https://github.com/samuelbferraz/DuMato).

## Temporal Motif Mining {#temporal_motif_mining}

Count occurrences of a small ordered edge pattern whose matched events occur in the required order within a bounded time window.

$$
t_1<\cdots<t_m,\qquad t_m-t_1\le\Delta
$$

An occurrence must match the declared event pattern and its time window; profile-specific ordering rules also apply.

**Example question:** “How many ordered interaction patterns occur within this time window?”

**Input assumptions.** direction: must match motif; weights: ignored; timestamps: required; vertex attributes: optional for predicates; edge attributes: optional for predicates.

**Guarantee.** The occurrence count is exact; listing may be capped.

**Required outputs:** `occurrence_count`, `instances_complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`temporal-motifs`](../explorer.md#problem/temporal_motif_mining) | `cpp` | `everest`, `mayura` | Exact |

**`temporal-motifs`** — Exact native structural matching and injective event assignments. Rational UTC timestamps, acyclic partial order, inclusive duration limit, optional temporal inducedness and typed predicates. Event tuples in query-edge input order identify occurrences. Counts and vertex participation remain complete when instance lists are capped.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run temporal-motifs INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/temporal_motif_mining) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/15_temporal_motif_mining/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Everest: GPU-Accelerated System for Mining Temporal Motifs](https://www.vldb.org/pvldb/vol17/p162-yuan.pdf). PVLDB, 2024 · [Author code](https://github.com/yichao-yuan-99/Everest).
- [Mayura: Exploiting Similarities in Motifs for Temporal Co-Mining](https://arxiv.org/abs/2507.14813). PVLDB, 2025 · [Author code](https://github.com/singam-sanjay/Mayura).
