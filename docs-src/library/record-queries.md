# Record queries

Look up, filter, and summarize original graph records before or after a mining calculation.

| Operation | Use |
| --- | --- |
| `node-lookup` | Select vertices by typed IDs and field predicates. |
| `edge-filter` | Select relationships, with source and target predicates. |
| `neighbors` | Find vertices within a filtered hop bound. |
| `common-neighbors` | Intersect direct neighbor sets. |
| `query-paths` | Enumerate hop-shortest or bounded simple paths. |
| `graph-aggregate` | Count, sum, average, minimum, or maximum, optionally grouped. |
| `query-subgraph` | Extract by vertices, edges, or a filtered neighborhood. |

These are CPU utilities. They are separate from the formal research-problem count. Their [catalog entries](../problem/families/records.md) contain the current parameter schemas.

## Predicate semantics

A predicate contains `field`, `op`, and `value`. A filter list is an AND clause:

```json
[
  {"field": "attributes.amount", "op": "gte", "value": 100},
  {"field": "type", "op": "eq", "value": "transfer"}
]
```

Supported operators include `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in`, `not_in`, `contains`, and `exists`. Types are not silently converted. Missing fields match only `exists=false`; explicit null is present. An omitted selection means the applicable records, while an explicit empty ID list selects none.

Direction is `out`, `in`, or `both`; undirected graphs use undirected adjacency. `query-paths` minimizes hops in shortest mode, not edge weights. Use a weighted shortest-path operation for cost minimization.

## Aggregates and bounded collections

An empty count or sum is zero. An empty average, minimum, or maximum is null. Numeric aggregation rejects missing or nonnumeric values in matched records. Exact rational metadata preserves numerator and denominator when applicable. A complete match count can accompany a capped collection of rows; inspect completeness for each output.
