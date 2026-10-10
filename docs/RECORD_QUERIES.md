# Record queries and dependent analysis

The review's lookup layer is available in the **Look up & summarize records**
family. Its seven operations use the public library, workflow validator, API,
and browser modes. These are CPU utilities over canonical graph records;
GPU-only requests are rejected. They do not expand the count of formal graph
mining problems with implementations.

| Operation | Meaning | Workflow outputs |
| --- | --- | --- |
| `node-lookup` | Select original vertices by typed IDs and field predicates | Record table, vertex set, match count |
| `edge-filter` | Filter original relationships and their source/target records | Record table, edge IDs, endpoint set, match count |
| `neighbors` | Vertices within a hop bound over filtered relationships | Distances, vertex set, match count |
| `common-neighbors` | Intersection of direct neighbor sets | Table, vertex set, match count |
| `query-paths` | All hop-shortest or all vertex-simple paths within a bound | Paths with edge witnesses, vertex/edge IDs, match count |
| `graph-aggregate` | Count, sum, average, minimum, maximum; optionally grouped | Table, exact rational values, per-vertex scores when applicable |
| `query-subgraph` | Extract by vertices, edges, or a filtered neighborhood | Canonical graph, original vertex/edge IDs |

The planner receives the actual parameter and nested predicate schemas. Direct
API callers and Expert plans use the same validator. Literal predicates and
fields are checked against uploaded records before a workflow is queued.
Derived inputs are checked again when their actual records become available.
Unknown fields and incompatible operations remain errors. No SQL, Cypher,
Python expression, or regular-expression execution is exposed.
An empty record scope cannot establish which domain attribute fields exist;
well-formed attribute predicates yield empty results there, and empty numeric
aggregates retain the zero/null semantics below.

## Predicates and identity

Each filter is an AND clause with exactly `field`, `op`, and `value`:

```json
[
  {"field": "attributes.amount", "op": "gte", "value": 10000},
  {"field": "type", "op": "eq", "value": "transfer"}
]
```

Supported operators are `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in`, `not_in`,
`contains`, and `exists`. `contains` is string containment or membership of a
scalar in an array. Ordered comparisons require compatible strings or numbers.
There is no implicit conversion between strings, booleans and numbers. IDs
accept only nonempty strings and integers; `0` and `"0"` remain distinct.

Use `attributes.balance` for nested record data. A missing field never matches
a comparison, including `ne` and `not_in`. Use `exists=false` to select missing
fields. Explicit JSON null is present and can be tested with `eq=null`.
Numeric aggregation fails when a matched record has a missing, null, boolean,
or nonnumeric value; it does not silently treat such values as zero.

Omitting `vertices` or `edge_ids` selects all applicable records; supplying
`[]` selects none. `query-subgraph` in `vertices` mode requires an explicit
vertex list or a typed vertex-set binding, so an empty selection produces an
empty graph. Edge-induced extraction retains only endpoints, while vertex-
induced extraction can retain isolates. All extracted records preserve their
attributes, timestamps, direction, weights, loops and parallel edges.
Neighborhood extraction follows only the selected edge IDs and edge predicates;
vertex predicates then filter the retained vertices. Explicit vertex lists use
`vertices` mode. Nondefault parameters that do not apply to the selected mode
are rejected rather than ignored.

## Direction, paths and aggregates

`direction` is `out`, `in`, or `both`. For undirected graphs all three use
undirected adjacency. Neighbor output deduplicates vertices. Path output keeps
parallel-edge alternatives separately through edge IDs. Self-loops count once
in a vertex's incident-record aggregation; vertex-simple paths cannot repeat
a vertex. A source-to-itself path is the length-zero path.

`query-paths.mode=shortest` enumerates all minimum-hop paths that satisfy the
bound. `all_simple` enumerates all vertex-simple paths within it. Neither
mode minimizes weights. Use a shortest-path algorithm for weighted distances.
Work/time budgets are enforced; exhausting a computation budget fails rather
than returning a supposedly exhaustive answer.

Aggregation groups by an explicit record field, `vertex`, or null for one
overall group. Per-vertex edge aggregation follows the selected direction and
includes isolates. Grouping edges by `source` or `target`, and edge-filter
endpoint predicates, use the stored endpoints even for an undirected graph.
Vertex-record grouping applies its filters before forming groups.
An empty count/sum is zero; an empty average/min/max is null.

Each numeric aggregate retains `exact_value.numerator` and `denominator`.
Decimal JSON values use their decimal representation for exact arithmetic.
The `value` column is a display number, with `rounded=true` when needed. The
browser marks those displays with `≈`; sorting and workflow top-vertex
selection use the exact rational values. Integer sums preserve integers above
the JavaScript safe-integer limit. A score can select an entity; a rounded
aggregate is not implicitly bound as an exact numeric algorithm parameter.

## Example: filter transfers, extract their graph, summarize senders

Supply an uploaded canonical graph as the `main` input to this plan:

```json
{
  "version": 1,
  "device": "cpu",
  "steps": [
    {
      "id": "transfers",
      "operation": "edge-filter",
      "input": {"input": "main"},
      "parameters": {
        "edge_filters": [
          {"field": "attributes.amount", "op": "gte", "value": 10000}
        ]
      }
    },
    {
      "id": "network",
      "operation": "query-subgraph",
      "input": {"input": "main"},
      "parameters": {"mode": "edges"},
      "bindings": {"edge_ids": {"step": "transfers", "port": "edges"}}
    },
    {
      "id": "senders",
      "operation": "graph-aggregate",
      "input": {"step": "network", "port": "graph"},
      "parameters": {
        "scope": "edges",
        "group_by": "vertex",
        "direction": "out",
        "metric": "sum",
        "field": "attributes.amount",
        "order": "descending"
      }
    }
  ]
}
```

Edge and vertex bindings carry the source graph fingerprint. Equal-looking IDs
from another dataset cannot silently enter a step. The graph output carries
its own fingerprint and the original input lineage.

`result_limit` caps retained rows, not the match count. Collection ports are
incomplete when capped, and a dependent step cannot consume that collection.
The browser explains how to narrow the query; paging/download operates on the
retained output and does not change computation. Subgraph extraction is complete
or fails its resource budget.

This layer addresses canonical-graph queries. Joins and graph construction
from multiple tables remain tracked under R2/R8 in the integration checklist.
Real-model routing and conversation accuracy remain a separate R9 gate.

## Review evaluation probes

The application includes 20 authored development cases: ten lookups and ten
dependent workflows, including query-to-BFS, exact ranking, filtered paths,
isolates and empty derived graphs. They share a small fictional fixture and
are neither a held-out benchmark nor training approval.

```sh
.venv/bin/python -m graphmine_agent.learning.analytics_queries \
  --mode reference --output validation/python_analytics/query-workflows-reference.json
```

The runner creates an isolated temporary application data store, executes real
validated workers, and grades operation choice, full normalized parameters,
dependency wiring, execution, port completeness and expected values separately.
It accepts arbitrary step names while preserving the wiring. Reference mode
does not invoke a model and explicitly reports that it measures no model
accuracy. With an enabled model endpoint, `--mode model` also invokes the
family-first planner for every question and saves its trace. The runner records
case, implementation and capability hashes; it does not modify training data.
