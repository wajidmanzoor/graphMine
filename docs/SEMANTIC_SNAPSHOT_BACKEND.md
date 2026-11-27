# Semantic snapshot backend

Phase 2 refines an owned, complete database graph snapshot in a disposable
in-memory Tentō process. It creates a separate immutable graph or table preview,
retains the parent snapshot hash and source lineage, and reuses save/chat/export
and database-job controls. It never reruns the original Neo4j query.

The pinned engine currently supports **plain reads and explicit mock execution**
through this backend. Live models and saved-answer reuse return 503 before
starting a worker. Admin controls and the query UI belong to later phases.
Install the optional source-built engine using the [build guide](../deploy/tento/README.md).

## API

All routes use the application's existing authentication and account scope.
Responses use `Cache-Control: private, no-store`.

| Request | Result |
| --- | --- |
| `GET /api/database-query-snapshots/{id}/semantic-schema` | Actual loaded tables, property aliases/types, labels, helpers and capability limits |
| `POST /api/semantic-queries` | 202 with a durable database job; supports `Idempotency-Key` |
| `GET /api/database-jobs?kind=semantic` | Active jobs owned by the caller |
| `GET /api/database-jobs/{id}` | Progress or terminal state |
| `GET /api/database-jobs/{id}/result` | Completed graph/table snapshot and bounded row sample |
| `DELETE /api/database-jobs/{id}` | Cancel queued work or terminate its child before publication |
| `POST /api/database-jobs/{id}/retry` | Explicit new run for failed/cancelled/interrupted work |

Example mock request:

```json
{
  "base_version_id": "dataset_version_REPLACE_WITH_OWNED_SNAPSHOT",
  "statement": "MATCH (n:Vertex) WHERE has_label(n, 'Review') RETURN n, llm('mock', 'Describe {{n.text}} {answer STRING}') AS answer",
  "parameters": {},
  "model": "mock",
  "call_limit": 100,
  "reuse_answers": false,
  "projection": "elements"
}
```

`model` defaults to `qwen`, whose live calls are blocked at this pin. A query
with no model operators works without a provider. Mock operators require an
explicit request `model: "mock"` and query alias `'mock'` or `'mock:echo'`.
No arbitrary endpoint/model configuration is accepted from query text.

Optional fields are `directed`, `weight_property` and `name`. In `elements`
projection, `weight_property` selects a finite numeric edge attribute. In `rows`
projection, return real nodes as `source` and `target`, a scalar `type` if desired,
and a numeric column named `weight`. Each row creates a distinct derived edge;
these edges have no SQL relationship lineage. Return aliases must be unique.

```cypher
MATCH (a:Vertex)-[r:KNOWS]->(b:Vertex)
RETURN a AS source, b AS target, 'RELATED' AS type, count(*) AS weight
```

There are no estimate or judgment-inspection endpoints. A running job holds a
durable lease on its base snapshot: expiry and deletion cannot remove it.
Promotion to a saved dataset keeps the lease. Completion, failure, cancellation
or restart recovery releases it. Queued work survives restart; running work is
marked interrupted and is never automatically replayed. Save the base if future
reruns must remain available after its preview expires. Finished job receipts
retain the existing five-minute in-memory delivery lifetime; snapshots have
their existing independent preview/save lifetime.

## Explicit labels and properties

Every vertex appears once in `Vertex`. Its full Neo4j label set is retained;
the source `type` is used only when `attributes.neo4j_labels` is absent.

```cypher
MATCH (n:Vertex)
WHERE has_label(n, 'Person') AND has_label(n, 'Employee')
RETURN n, labels_of(n) AS labels, graph_id(n) AS original_id
```

`MATCH (n:Person)` is not rewritten. Native `label(n)` describes the loaded
table; use `labels_of(n)` for original labels. `graph_id(n)` returns the original
typed vertex/edge ID. Native `id(n)` is an internal engine ID and is not a stable
GraphMine ID. Numeric `1` and string `"1"` remain different identities.

Relationship tables follow the original relationship type. Reserved or colliding
table/property names receive stable aliases, exposed with their original names
in the schema response. Edge IDs are validated for uniqueness before loading.
Parallel edges and loops retain their own IDs and endpoints.

| Source values in a property | Loaded representation |
| --- | --- |
| One primitive type | `INT64`, `DOUBLE`, `BOOLEAN` or `STRING` |
| Mixed primitive types | Tagged `UNION`, preserving number versus text and boolean |
| Lists, objects, integers beyond signed 64-bit, other irregular mixes | `JSON` |
| All values null | Nullable `JSON` |

Nested JSON is returned as decoded JSON cells; it is never globally converted
to text or flattened. JSON path functions are unavailable in this pinned build.
Mixed unions require explicit native union extraction/casts for some operators.
Use `has_property(n, 'field')` to distinguish absent from explicitly null, and
`property_names(n)` for original property names. Empty strings remain distinct
from null. Native CSV bulk loading is followed by bounded vectorized updates
to restore union tags and lists that CSV alone cannot represent reliably.

Graph collection dispatches on native logical types. Returned nodes, edges,
paths, lists and supported nested structs recover original snapshot records;
scalar objects with keys such as `_ID` cannot impersonate graph elements.
Graph-bearing `UNION` results are rejected because the Python driver omits the
active type tag. Scalar-only results become complete typed tables. Display
samples do not truncate the saved artifact.

## Validation, limits and usage

The read dialect rejects writes, multiple statements, procedures, extension or
file loading, database import/export, images, arbitrary functions and
`llm_build_graph`. Prompt inputs are checked too. Model aliases and prompts must
be literals. The supported mock operators are `llm`, `llm_score`, `llm_agg`,
`llm_path_agg` and both `llm_sg_agg` forms. `subgraph` retains native graph types.
`llm_score` supplies its integer output automatically; omit `{score INT64}` from
its prompt. Other operators accept typed outputs, with STRING as the default.

Current server ceilings, pending Phase 3 administration:

- 64 MiB serialized worker input and output; 256 KiB parameters.
- 120-second execution timeout; 256 MiB native buffer pool; two compute threads.
- One mock dispatch thread, 16 inputs per batch, at most 1,000 calls **per
  expression**. A requested `call_limit` is clamped to this ceiling. It is not
  a total query budget: two expressions may each consume that limit.
- Scalar tables: 100,000 rows; row samples: 50 rows and 256 KiB at collection.
- Existing account storage, pending-job and upload-concurrency limits apply.

`CALL llm_usage()` resets counters on read, so the worker accumulates each
observation. `calls` counts engine calls; mock execution sends zero HTTP
requests. `input_rows` and `llm_rows` describe candidate/selected inputs, not
confirmed completed judgments. `cache_hits` describes reuse inside the worker,
not durable answer retention. `answers_retained` is zero; answer reuse is
rejected until the author provides an independent answer store. Counters observed
before termination may omit work performed since the last progress event.

The parent monitors the child independently of native execution and kills/reaps
it on cancellation or timeout. Temporary files are private and removed on every
exit path. No provider credentials enter the current mock-only child. Errors
expose stable codes and parser positions where available, not raw engine messages
that can contain query/property values. Complete results are validated before
publication; failure exposes no partial snapshot.

Provenance records the parent hash, query/parameters, model steps, actual schema,
engine commit/hash, effective settings, usage and simulation status. It preserves
original source identity and filtered entity lineage. Mock judgments are marked
as simulated. Thinking controls, strict structured output without fallback,
durable answers, a query-wide call budget and shared live-provider scheduling
must be verified before live execution can be enabled. See the
[remaining author requests](../deploy/tento/AUTHOR_REQUESTS.md).
