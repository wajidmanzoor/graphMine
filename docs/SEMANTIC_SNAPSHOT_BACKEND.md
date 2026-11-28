# Query workspace and semantic backend

The data workspace uses one Cypher editor next to a graph preview. Choose the
dataset at the top, write the source selection and optional model annotations,
and select **Run query**. There is no separate refinement step. New installations
use live model execution by default; existing administrator restrictions remain
in force. Mock aliases are rejected by the query annotation endpoint.

```cypher
MATCH (r:Review)-[e:REVIEWS]->(b:Business)
WHERE r.text IS NOT NULL
SET r.summary = llm('qwen', 'Summarize the main praise or complaint: {{r.text}} {summary STRING}')
RETURN r, e, b
LIMIT 10
```

`SET` annotates the **result graph only**. The compiler sends Neo4j a read query
with the same source selection and captures prompt inputs alongside those exact
rows. Filters, ordering and the final LIMIT select rows before model calls.
Generated attributes cannot be used to filter or order the source in that same
query. No writes or model functions are sent to Neo4j, and no partial graph is
published after failure or cancellation.

Use one terminal SET clause with up to eight comma-separated assignments. Each
value is `llm('alias', 'prompt')` or `llm_score('alias', 'prompt')`; each target
must be a named node or relationship explicitly returned, optionally with AS.
Put grouping, DISTINCT and source aggregates in WITH before SET. For example,
collect review text in WITH, then summarize the collected input onto a business
node. Repeated identical target/input pairs are evaluated once. Conflicting
inputs for one target are rejected instead of selecting an arbitrary answer.
The legacy native read dialect remains available through its API below.

The alias in each expression selects its configured provider/model. Different
assignments may use different aliases; all share the query's HTTP request limit.
Every run makes fresh calls; cross-run answer reuse is off for annotations.
Model configuration shows aliases and allows smaller request, batch and timeout
limits within administrator limits. The admin link manages providers and model
aliases. Strict structured output, temperature zero and thinking off remain
required. Install the source-built engine using the
[build guide](../deploy/tento/README.md).

The preview offers Spread, Circular, Bipartite, Grid, Concentric and Hierarchy
layouts. Layout and node-label changes do not rerun the query or change graph
contents. Bipartite layout reports an odd cycle when the graph is not bipartite.
Select a node or edge to inspect its attributes, including generated summaries.
Save the complete graph to datasets or use it in chat through the existing
immutable snapshot lifecycle. On mobile, Query and Graph preview are tabs;
dataset selection remains at the top.

Schema opens an interactive diagram for the selected database. Mapped sources
use their graph mappings. Unmapped sources use all Neo4j catalog labels with
bounded property samples per label and relationship type. Neo4j infers possible
relationship patterns, which the dialog explicitly explains. If catalog access
is unavailable, the diagram reports its bounded sample and possible omissions.

`POST /api/database-sources/{source_id}/queries` accepts these queries using its
normal sync/async job, cancellation, save and chat routes. Optional request
fields are `call_limit`, `batch_size`, and `model_timeout_seconds`.
`GET /api/query-models` exposes non-secret aliases, defaults, limits and account
availability. `GET /api/database-sources/{source_id}/schema?dataset_id=…&diagram=true`
returns the diagram schema. A completed snapshot records the original query,
model targets, effective model settings, source lineage and observed usage.

## Legacy snapshot API

The snapshot API evaluates an owned, complete database graph in a disposable
in-memory Tentō process without rerunning the original Neo4j query. It remains
available for native semantic operators and existing integrations. Its explicit
mock mode is retained for test fixtures and historical compatibility; it is not
part of the query workspace. Historical simulated results retain that label.


All routes use the application's existing authentication and account scope.
Responses use `Cache-Control: private, no-store`.

| Request | Result |
| --- | --- |
| `GET /api/database-query-snapshots/{id}/semantic-schema` | Actual loaded tables, property aliases/types, labels, helpers and capability limits |
| `POST /api/semantic-queries/validate` | Ownership/policy check and model-step summary; no execution or job reservation |
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

`model` defaults to `qwen`; live steps require permitted live mode
and the verified patched installation. A query
with no model operators works without a provider. Mock operators require an
explicit request `model: "mock"` and query alias `'mock'` or `'mock:echo'`.
Every model step must use the selected configured alias. No arbitrary
endpoint/model configuration is accepted from query text.
Omit `call_limit`, or send null, to use the current administrator default. The
server clamps an explicit limit to the current maximum when the worker starts.
With accounts enabled, only administrators may run model steps by default;
administrators can grant access to selected accounts or all accounts. Plain
snapshot reads retain normal snapshot access without model-step permission.

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
be literals. The supported operators are `llm`, `llm_score`, `llm_agg`,
`llm_path_agg` and both `llm_sg_agg` forms. `subgraph` retains native graph types.
`llm_score` supplies its integer output automatically; omit `{score INT64}` from
its prompt. Other operators accept typed outputs, with STRING as the default.

Current server ceilings:

- 64 MiB serialized worker input and output; 256 KiB parameters.
- Default 120-second execution timeout, configurable from 5 to 600 seconds;
  256 MiB native buffer pool; two compute threads.
- One model dispatch thread per worker. Default 16 inputs per batch, configurable
  from 1 to 128. Default call limit 100 and maximum 1,000, both configurable from
  1 to 1,000, with default no greater than maximum. A requested `call_limit` is
  clamped to the current maximum. Live limits cover **all query HTTP attempts**;
  mock limits retain the upstream per-expression scope. Live requests require
  thinking off, temperature zero, strict JSON and at most 4,096 output tokens.
- One semantic worker at once by default, configurable from 1 to 4. Kernel locks
  share this limit across application processes using the same data root,
  including admin mock tests. Lowering the limit admits no new worker until
  active work falls below it. Slot waiting uses the existing model queue timeout.
- Scalar tables: 100,000 rows; row samples: 50 rows and 256 KiB at collection.
- Existing account storage, pending-job and upload-concurrency limits apply.

`CALL llm_usage()` resets counters on read, so the worker accumulates each
observation. `calls` counts engine calls; mock execution sends zero HTTP
requests. `input_rows` and `llm_rows` describe candidate/selected inputs, not
confirmed completed judgments. `cache_hits` includes cached inputs; `stored_hits` identifies independently
retained answers. `http_requests` counts outbound attempts and `completed_rows`
counts valid answer evaluations. `answers_retained` counts distinct stored keys
for the account, including answers beyond this query. These counters never reset
the atomic request budget. The budget counts native completion attempts; parent
quota-tokenization and power-control requests are outside that count. Counters observed
before termination may omit work performed since the last progress event.

The parent monitors the child independently of native execution and kills/reaps
it on cancellation or timeout. On Linux, a child also receives SIGKILL if its
supervisor dies. Temporary files are private and removed when the supervisor
exits normally, including handled errors, cancellation and timeout. A live child receives only its selected provider
credential; mock children receive no provider credential. Errors
expose stable codes and parser positions where available, not raw engine messages
that can contain query/property values. Complete results are validated before
publication; failure exposes no partial snapshot.

Provenance records the parent hash, query/parameters, model steps, actual schema,
engine commit/hash, effective settings, usage, effective graph direction and simulation status. It preserves
original source identity and filtered entity lineage. Mock judgments are marked
as simulated. Live provenance is model dependent and records the patch identity,
provider/model, strict/thinking controls and effective request budget. The
[verification report](../agent/evaluation/reports/tento_fixes_20261127.md) records
real Qwen and CPU-solver measurements. A model-derived input does not change the
solver's independently recorded quality guarantee.

## Administration

The Semantic engine page uses existing administrator sessions, cookie mutation
protection and the secret-free Activity audit. Settings persist in the existing
settings database and apply without restarting services. `GRAPHMINE_SEMANTIC_*`
names identify durable admin overrides; this phase does not add environment
variable parsing for them. The default model-step mode is `mock`; `disabled`
blocks model operators while allowing plain reads. Enabling `live` or retained
answers requires the verified patched installation; clearing lock blocker lists
alone is insufficient.

Provider metadata and aliases are stored centrally. **GraphMine vLLM** follows
the server base endpoint and base model; `qwen` and `mock` are reserved aliases.
Additional OpenAI-compatible providers use private key files under
`data_root/semantic-credentials` (directory 0700, files 0600). Responses and audit
records expose only whether a key is set. Credentials are not stored in SQLite.
Changing an endpoint requires replacing or explicitly removing its saved key.
Provider/alias edits reject stale revisions; a provider with aliases cannot be
removed until those aliases are removed. Back up private credentials with the
data root and preserve their ownership and permissions.

**Test connection** performs a real bounded `GET /models` against the chosen
base URL, checks configured model IDs and reports the observation time. It does
not follow redirects, inherit proxy settings, or send a completion request. A
successful catalog check does not establish live semantic readiness. **Test mock
pipeline** runs one native `mock:echo` query and verifies its returned value,
one engine call and zero HTTP requests.

| Admin API | Behavior |
| --- | --- |
| `GET /api/admin/semantic` | Current settings, public provider metadata, aliases, accounts and capabilities |
| `PATCH /api/admin/semantic/settings` | Confirmed update with expected prior values |
| `POST /api/admin/semantic/providers` | Add provider, optionally supplying a private key |
| `PUT / DELETE /api/admin/semantic/providers/{id}` | Update/remove with expected revision; delete requires confirmation |
| `POST /api/admin/semantic/providers/{id}/test` | Check model catalog and configured model IDs |
| `PUT /api/admin/semantic/aliases` | Add or update an alias; update requires expected revision |
| `DELETE /api/admin/semantic/aliases/{alias}` | Confirm removal with expected revision |
| `POST /api/admin/semantic/test-mock` | Native mock pipeline test under the shared semantic worker limit |
| `POST /api/admin/semantic/cache/clear` | Confirmed all-account clear; active workers prevent deletion |

Account access is checked at submission, worker admission and before result
publication. Queued work uses current limits; an active worker retains its
recorded limits. Changing settings, providers or aliases does not rewrite saved
provenance. Legacy operation without accounts retains its existing local access.

Answer reuse defaults off. The maximum answer age is 30 days by default,
configurable from 1 to 365 days. Thinking off, strict JSON and temperature zero
are enforced on live requests. The page warns when semantic concurrency meets
or exceeds `GRAPHMINE_LLM_MAX_NUM_SEQS`; it never raises planner/server capacity.
Each live attempt uses existing planner admission and model wake/sleep leases.

See the [Phase 3 report](../agent/evaluation/reports/tento_phase3_20261127.md) for
authorization, secret handling, concurrency and browser evidence.

## Retained answers and request admission

Retention is independent of graph storage. Private `semantic-answers` files use
account-derived filenames, a 0700 directory and 0600 files. Process-shared locks
serialize writers within an account and exclude administrative clearing. An
active worker prevents clear; retry after it finishes. Clear changes no saved
snapshot or provenance. Maximum age controls reuse eligibility. Retained bytes
remain until cleared; this setting is not a scheduled deletion policy.

The engine persists and fsyncs each valid batch before attempting the next
request. Killing a worker or exhausting its budget preserves those answers. A
subsequent run over the same snapshot can reuse them. Changed input, prompt,
model/provider, schema, credential or relevant configuration revisions miss the
cache. Reuse-disabled runs bypass reads while retaining new completed answers.
Cache retention defaults off and can be cleared through the audited admin route.

Before each native HTTP attempt the supervisor uses the same account/model
quota, token reservation and power lease as planner requests. Cancellation
closes its private socket and releases the lease. Native requests are not
proxied. Provider schema rejection and malformed final answers fail without
publishing a partial result. Shared vLLM defaults are unchanged.
