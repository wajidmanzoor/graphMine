# Graph views — foundation (step 1)

The public C++ API in `graphmine/views.hpp` builds immutable standard views in
the native runtime. This is the foundation for the migration specified in
[`GRAPH_VIEW_FORMATS.md`](../../GRAPH_VIEW_FORMATS.md). Existing algorithms still
use their current adapters. Steps 2–9, per-backend golden comparisons, exporters
and registry declarations have not been implemented yet.

## API and ownership

```cpp
#include <graphmine/views.hpp>

auto spec = graphmine::ViewSpec::from_json(R"({
  "kind": "csr",
  "direction": "symmetrize",
  "self_loops": "drop",
  "parallel_edges": "collapse:first",
  "weights": "none"
})");
auto result = graphmine::make_view(graph, spec);
const auto& csr = std::get<graphmine::CsrView>(result->view);
```

Link against `GraphMine::runtime`. `make_view(const Graph&, const ViewSpec&)`
supports ordinary graphs. The `std::string_view` overload accepts the existing
canonical graph, feature-vector, hypergraph and collection JSON formats. It
selects the input format from `kind` (`dense` accepts a graph or feature vectors).
Both overloads return `shared_ptr<const ViewResult>`; returned arrays and ID maps
remain valid after the source graph or cache entry is released.

| Kind | Owned layout | ID mapping |
| --- | --- | --- |
| `csr` | u64 offsets, u32 indices, optional numeric weights/edge IDs, optional transpose | Both directions between view and original dense indices, plus external IDs |
| `coo` | u32 sources and destinations, optional numeric weights/edge IDs | Same vertex mapping as CSR |
| `bipartite` | CSR with left vertices before right vertices, plus `L` | Reversible permutation; canonical order within each side |
| `dense` | Row-major f64 or i64 values, presence mask, optional edge metadata | Separate row/column external IDs and original indices |
| `hypergraph` | Hyperedge-to-vertex and vertex-to-hyperedge incidence CSR | Vertex mapping and original hyperedge IDs |
| `collection` | Array of CSR members, member indices/IDs and per-member summaries | Each member retains its own reversible vertex map |

For ordinary graphs, edge IDs are positions in the original canonical edge
array. Side tables follow the same permutations as their arrays. A transpose's
`in_edge_indices` maps each incoming entry to its forward entry and its aligned
weights, edge ID and side tables.

## Declared semantics

Specs reject unknown fields, duplicate JSON keys, invalid types and unknown
policies. Canonical serialization includes all defaults, sorts object keys and
side-table names, and retains typed partition IDs. Defaults preserve direction,
self-loops and parallel edges, use f64 weights from `edge.weight`, sort neighbors,
and use u32 vertex indices with u64 offsets. Missing ordinary edge weights are
unit weights, matching the existing weighted adjacency helper. `weights: none`
omits the column. `attribute:a.b` resolves numeric nested object attributes.

- Undirected edges and `symmetrize` produce both orientations, except that each
  retained self-loop produces one entry. `reverse` reverses directed edges.
  `both` produces forward/reverse CSR and is supported for CSR-based kinds.
- Loop and parallel-edge counts refer to original records, before symmetric
  expansion. Parallel edges are identified after direction projection. Sum
  follows canonical record order and checks overflow. Min/max choose the first
  record at the winning weight; first and sum retain the first record's ID and
  metadata. With weights omitted, collapsing retains the first identity.
- CSR always groups rows. With sorting disabled it preserves order within each
  row. COO with sorting disabled preserves the normalized edge-stream order.
- The `simple` flag means no loops or parallel arcs remain. `symmetric` guarantees
  both orientations; `directed` records the declared interpretation.
- Requested vertex labels come from `VertexRecord.label`; edge labels come from
  `EdgeRecord.type`. Dictionaries use sorted strings. Missing labels are
  `UINT32_MAX`, distinct from empty strings. Requested timestamps require int64
  input; this foundation does not guess units for timestamp strings.

`bipartite_sides: attribute:side` and `parameters` produce identical V3 arrays for
equivalent partitions, including isolates. Explicit partitions must be disjoint
and cover every vertex; each retained edge must cross sides. The resolved
parameters are included in the spec, so they also participate in cache identity:

```json
{
  "kind": "bipartite",
  "bipartite_sides": "parameters",
  "parameters": {
    "left_partition": [0, "alice"],
    "right_partition": ["0", "bob"]
  }
}
```

Ordinary dense graphs produce square adjacency matrices. Supplying bipartite
sides produces a left-by-right matrix. Absent cells are zero with `present=0`;
explicit zero-weight edges have `present=1`. Parallel edges require a declared
collapse policy, since one cell cannot hold multiple values. Feature inputs
retain their row IDs and use integer column IDs `0..dimension-1`; graph-edge
policies, labels and partition options are inapplicable and rejected.

Hypergraphs preserve hyperedge identity and set membership; ordinary graph
projection/loop/parallel-edge policies and label/timestamp columns are rejected.
Both vertex and hyperedge weight columns support the requested numeric type.
Original numeric tokens are also retained for existing exact arithmetic.
Collection members use the same CSR spec; member order and IDs are preserved.

## Numeric validation and limits

`int64_exact` uses original numeric tokens, never a rounded intermediate double.
Fractional or out-of-range values and integer sum overflow fail. The user
approved an exact-weight graph parser mode used only by new `int64_exact` views.
Existing operation parsing, C ABI, CLI, operation parameters and result JSON keep
their current binary64 precision checks. f64 feature matrices also retain their
existing rejection of integers that lose precision.

u32 limits vertex counts to `UINT32_MAX`. i32 limits vertex and entry counts to
`INT32_MAX`; CSR storage itself remains u64/u32. Limits are checked on ordinary
input and expanded output, dense cell counts and hypergraph incidence counts.
Collections enforce member limits and aggregate vertex/entry limits. Unspecified
limits introduce no application cap beyond the representable widths.
`validate_view_counts` supports boundary checks without allocating huge graphs.

The summary contains projection status, removed original loops/collapsed edges,
the number of input numeric type conversions, and output sizes. Graph views count
arcs, dense graph views count present cells, feature matrices count cells, and
hypergraphs count hyperedges. `normalization_json()` exposes the requested six
fields. Attaching this summary to algorithm provenance belongs to the adapter
migration; no existing result fields are changed in step 1.

## Cache

Views share the existing process-local representation cache (128 MiB default,
configurable through the existing `representation_cache` command). Keys include
the content hash, canonical resolved spec, implementation hash and view format
version. Source numeric storage is included in graph identity to prevent exact
integer collisions. The cache accounts for owned arrays, mappings, dictionaries,
key strings and allocation overhead; oversize views are returned without retention.

Entries are immutable, concurrent builds converge on the retained object, and
eviction does not invalidate active owners. Failed builds are not retained.
There is no disk cache. The user approved this storage choice and the extension
to existing structured input types.

## Validation

The seven `graphmine_views_*` CTest suites cover spec validation, all collapse
rules, seeded symmetry/count properties, exact integer/overflow boundaries, i32
count checks, both bipartite side sources, dense/structured inputs, byte comparison
of fresh uncached builds, and cache eviction/concurrency. See
[`graph_views_step1.md`](graph_views_step1.md) for the recorded run and admission
status. No backend-equivalence or worker-file golden result is claimed at this
foundation stage.
