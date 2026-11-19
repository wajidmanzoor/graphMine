# Graph inputs and in-memory views

Create a canonical graph without losing vertex identity, relationship meaning, or operation-specific roles.

## Canonical graph JSON

```json
{
  "graph": {
    "id": "triangle",
    "directed": false,
    "allows_self_loops": false,
    "allows_parallel_edges": false
  },
  "vertices": [{"id": 0}, {"id": 1}, {"id": 2}],
  "edges": [
    {"id": "ab", "source": 0, "target": 1},
    {"id": "bc", "source": 1, "target": 2},
    {"id": "ac", "source": 0, "target": 2}
  ]
}
```

Vertices and edges can carry attributes. IDs are typed: integer `0` and string `"0"` are different vertices. Edge endpoints must refer to known vertices. The [canonical schema](https://github.com/wajidmanzoor/graphMine/blob/main/problems/graph_input.schema.json) specifies allowed fields.

## Edge lists and roles

A relationship CSV supplies source and target columns, with optional relationship attributes. Declare ID types, direction, and weight meaning before using it. The native file readers report whether their required backend is available; the canonical JSON path works in the standalone CPU build.

Some operations need more than a host graph. A query graph defines a pattern to match; a motif defines a small shape to count; update batches change a dynamic graph; a partition or declared `attributes.side` identifies the two sides of a bipartite input. A graph collection, feature matrix, or hypergraph uses its own contract. Do not substitute an ordinary graph object for one of these inputs.

Normalization is problem-specific. A simple undirected algorithm may remove loops and collapse parallel edges; record queries preserve original records. Weights can mean costs, capacities, or strengths. Inspect the [formal problem](../problem/explorer.md) and operation parameters before projecting or aggregating them.

## Standard native views

| View | Representation | Typical use |
| --- | --- | --- |
| CSR | Neighbor offsets and indices, optional weights and reverse adjacency | Traversal, cliques, cores, centrality |
| COO | Source and destination arrays, optional time and edge identity | Edge streams and temporal work |
| Bipartite | Relabelled adjacency with explicit left/right boundary | Bicliques and assignment |
| Dense matrix | Row-major values with row and column identity maps | Assignment and vector comparisons |
| Set-structured | Hyperedge incidence or a graph collection | Hypergraphs and collection algorithms |

The view specification declares direction, loop handling, duplicate aggregation, numeric representation, labels, and index limits. `make_view` constructs the declared representation and records a normalization summary. External IDs are mapped back into results. A cached view is associated with both its graph snapshot and specification.

The [code reference](code-reference.md) documents `Graph`, `ViewSpec`, `NormalizationSummary`, and the view builders in the current source.
