# Pattern matching & mining

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

Where does a given pattern occur, or which patterns are frequent? Match a supplied pattern or mine frequent subgraphs in one graph or a graph collection, using the operation's declared matching and support semantics.

**Start with this question:** Where does a given pattern occur, or which patterns are frequent?

[Explore these operations](../explorer.md#family/patterns) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [Subgraph Isomorphism and Pattern Matching](#subgraph_isomorphism)
- [Frequent Subgraph Mining](#frequent_subgraph_mining)
- [Frequent Subgraphs in One Labeled Graph](#single_graph_frequent_subgraph_mining)

## Subgraph Isomorphism and Pattern Matching {#subgraph_isomorphism}

Find injective mappings from the vertices of a query graph to a data graph that preserve required edges, direction, and requested attribute predicates.

$$
f:V_H\hookrightarrow V_G,\quad (u,v)\in E_H\Rightarrow(f(u),f(v))\in E_G
$$

f is injective; induced mode also preserves nonedges, and declared label predicates must hold.

**Example question:** “Find all matches of this query graph.”

**Input assumptions.** direction: query and data semantics must match; weights: available to predicates; timestamps: available to predicates; vertex attributes: available to predicates; edge attributes: available to predicates.

**Guarantee.** Every returned mapping is exact; complete=true requires exhaustive matching.

**Required outputs:** `matches`, `returned_count`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`subgraph-isomorphism`](../explorer.md#problem/subgraph_isomorphism) | `cpp` | `gmatch` | Exact |

**`subgraph-isomorphism`** — Exact native induced or non-induced injective matching, preserving direction, loops and parallel multiplicities. Declarative typed vertex and edge predicates; distinct query edges must match distinct data edges. Capped mapping collections are explicitly incomplete.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run subgraph-isomorphism INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/subgraph_isomorphism) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/13_subgraph_isomorphism/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [gMatch: A Fast GPU-Based Subgraph Matching System](https://arxiv.org/abs/2604.10601). PVLDB 2026, 2026 · [Author code](https://github.com/SJTU-Liquid/gMatch).

## Frequent Subgraph Mining {#frequent_subgraph_mining}

Given a collection of graphs, discover unique subgraph patterns appearing in at least a specified fraction of the collection.

$$
\operatorname{support}(H)=|\{G_i:H\subseteq G_i\}|
$$

A pattern is frequent when its graph-collection support reaches the declared threshold; containment follows the contract.

**Example question:** “Which subgraphs occur in many graphs in this collection?”

**Input assumptions.** direction: consistent across collection; weights: ignored; timestamps: ignored; vertex attributes: labels or types optional; edge attributes: labels or types optional.

**Guarantee.** complete=true requires exact exhaustive pattern discovery.

**Required outputs:** `patterns`, `complete`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`frequent-subgraphs`](../explorer.md#problem/frequent_subgraph_mining) | `cpp` | — | Exact |

**`frequent-subgraphs`** — Exact bounded native enumeration of simple labeled directed or undirected patterns, including disconnected and isolated vertices. Support counts transactions once. Native lexicographic canonicalization has its own stable pattern IDs. Positive support fraction uses exact decimal comparison. Explicit loop and parallel policies; no Python runtime.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run frequent-subgraphs INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/frequent_subgraph_mining) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/14_frequent_subgraph_mining/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

This utility group has no separate research-paper entry in the catalog.

## Frequent Subgraphs in One Labeled Graph {#single_graph_frequent_subgraph_mining}

Enumerate or count connected labeled patterns meeting a declared minimum-image-support threshold in one labeled host graph.

$$
\operatorname{support}_{G}(H)\ge\theta
$$

Support uses the declared single-host measure and embedding rules, not automatically a graph-collection count.

**Example question:** “Which labeled subgraphs repeat in this graph?”

**Input assumptions.** direction: undirected; weights: ignored; timestamps: ignored; vertex attributes: required discrete vertex labels; edge attributes: ignored.

**Guarantee.** Exact mathematical objective; implementations must declare approximation and termination status.

**Required outputs:** `frequent_pattern_count`, `patterns`, `completed`.

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`single-graph-frequent-subgraphs`](../explorer.md#problem/single_graph_frequent_subgraph_mining) | `cpp` | — | Exact |

**`single-graph-frequent-subgraphs`** — Exact connected undirected patterns including single vertices. Minimum-image support is the smallest host image-set size over all injective embeddings. Every vertex needs the selected label or type. Reject loops; explicit parallel collapse. Native canonical IDs, bounded enumeration and complete counts; count mode does not materialize patterns.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run single-graph-frequent-subgraphs INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/single_graph_frequent_subgraph_mining) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

[Full formal contract](https://github.com/wajidmanzoor/graphMine/blob/main/problems/68_single_graph_frequent_subgraph_mining/problem.json) · [Native API and implementation](../../library/code-reference.md)

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

- [Efficient and Scalable Graph Pattern Mining on GPUs](https://www.usenix.org/conference/osdi22/presentation/chen). USENIX OSDI 2022, 2022 · [Author code](https://github.com/chenxuhao/GraphMiner).
- [Pangolin: An Efficient and Flexible Graph Pattern Mining System on CPU and GPU](https://arxiv.org/abs/1911.06969). PVLDB 2020, 2019 · [Author code](https://github.com/chenxuhao/GraphMiner).
