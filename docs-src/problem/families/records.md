# Look up records

Find the right problem in this family, understand its contract, and choose a compiled operation to run.

Which stored records or connections match my request? Look up, filter and summarize stored vertex and edge records, including bounded connection queries and extraction by record selectors. Path queries overlap with paths, and graph extraction overlaps with preparation; choose this family when the goal is retrieving records satisfying a request.

**Start with this question:** Which stored records or connections match my request?

[Explore these operations](../explorer.md#family/records) · [Install the library](../../library/install.md) · [Code reference](../../library/code-reference.md)

The definitions below describe the formal problems. Each operation implements a particular parameter profile; check its inputs before running it. Research references are reading material, not a list of installed implementations.

Here, $G=(V,E)$ denotes the input graph, $S$ a vertex subset, and $G[S]$ its induced graph. Other symbols are defined with each problem.

## Problems in this family

- [Canonical graph record queries](#graph_record_queries)

## Canonical graph record queries {#graph_record_queries}

Look up, filter and summarize canonical vertex and edge records. These workflow utilities are listed separately from the formal research problem contracts.

$$
R' = \{r\in R : P_1(r)\land\cdots\land P_m(r)\}
$$

R is a collection of original records; each P is a declared predicate.

**Example question:** “Which records have at least ten connections?”

### Available operations

| Operation | CPU | GPU | Quality |
| --- | --- | --- | --- |
| [`common-neighbors`](../explorer.md#problem/graph_record_queries) | `cpp` | — | Exact |
| [`edge-filter`](../explorer.md#problem/graph_record_queries) | `cpp` | — | Exact |
| [`graph-aggregate`](../explorer.md#problem/graph_record_queries) | `cpp` | — | Exact |
| [`neighbors`](../explorer.md#problem/graph_record_queries) | `cpp` | — | Exact |
| [`node-lookup`](../explorer.md#problem/graph_record_queries) | `cpp` | — | Exact |
| [`query-paths`](../explorer.md#problem/graph_record_queries) | `cpp` | — | Exact |
| [`query-subgraph`](../explorer.md#problem/graph_record_queries) | `cpp` | — | Exact |

**`common-neighbors`** — Native intersection of direct filtered neighbor sets, preserving the declared direction and self-loop adjacency meaning. Typed entity IDs; stable original vertex order. Complete count with explicitly capped collections.

**`edge-filter`** — Native deterministic original-edge selection without collapsing loops or parallel events. Edge and source/target predicates use stored endpoints even for undirected input. Typed IDs, exact decimal scalar comparisons and explicit incomplete capped ports.

**`graph-aggregate`** — Native count, sum, average, minimum or maximum of an explicit field, grouped by a scalar field or vertex. Exact decimal rational arithmetic is authoritative; display values disclose rounding. Per-vertex edge groups include isolates and count loops once. Missing numeric/group fields fail. Stable exact-value sorting and completeness-aware result limits.

**`neighbors`** — Native filtered hop reachability with exact distances. Directed out/in/both traversal; undirected edges traverse both ways. Parallel records do not duplicate vertices; include_seed controls the root. Original input vertex ordering and explicit collection completeness.

**`node-lookup`** — Native deterministic selection of original vertex records by typed IDs and AND field predicates. Explicit empty vertex lists select nothing. Missing fields match only exists=false; unknown field paths fail. Counts remain complete when row collections are capped.

**`query-paths`** — Native iterative enumeration of all hop-shortest or all vertex-simple paths within max_hops. Filtered directed out/in/both traversal with parallel edge identities preserved. Source equal to target has one zero-edge path. Counts are exhaustive; capped path and membership ports are incomplete.

**`query-subgraph`** — Native vertex-induced, edge-induced or filtered-neighborhood extraction. Preserve typed IDs, original attributes, direction, weights, loop and parallel records. Edge mode retains endpoints; vertex mode retains selected isolates. Derived graph identity carries source content lineage.

### Run it

After [building the runtime](../../library/install.md), put a compatible input in `INPUT.json` and the operation's parameters in `PARAMETERS.json`.

```sh
graphmine-native run common-neighbors INPUT.json \
  --parameters PARAMETERS.json --device cpu
```

The [operation details](../explorer.md#problem/graph_record_queries) list required parameters, defaults, and output ports. This is a command template, not a ready-made dataset.

### Research references

These papers study this problem. A paper or linked repository does not by itself establish support in the compiled runtime.

This utility group has no separate research-paper entry in the catalog.
