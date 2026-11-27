# Tentō Phase 2 — snapshot backend with explicit labels

2026-11-27. **The approved backend scope is implemented and verified: plain
snapshot reads and explicit mock runs. Live acceptance remains pending author
fixes.** The user approved explicit label helpers and broad data preservation,
replacing the original one-table-per-label rule. Tentō itself is unchanged.
Phase 3 admin controls and Phase 4 UI work have not started.

The [backend guide](../../../docs/SEMANTIC_SNAPSHOT_BACKEND.md) contains the
request format, examples, mapping, limits and current feature boundaries.
[Machine-readable evidence](tento_phase2_20261127.json) records test counts,
engine identity and the remaining gates.

## Approved mapping

- Each source vertex occurs once in `Vertex`, retaining its complete label set.
  `has_label(n, 'Review')` and `labels_of(n)` expose original labels. Native
  `(n:Review)` is not rewritten. Relationship tables follow source types, with
  stable aliases for reserved/colliding names exposed in the schema.
- Encoded identity keys distinguish numeric and string IDs. The loader validates
  vertex/edge uniqueness and endpoints before native loading. Parallel edges and
  self-loops retain their original identities. `graph_id()` returns original IDs;
  native internal IDs remain implementation details.
- Primitive properties retain native types. Mixed primitives use tagged UNION
  columns; nested/irregular values and integers beyond signed 64-bit use JSON.
  Empty strings, nulls, absence, nested arrays/objects and large integers survive.
  `has_property()` and `property_names()` retain property presence information.
- Bulk CSV COPY loads graph rows. Bounded vectorized updates restore strings,
  label/property lists and union tags that CSV alone cannot distinguish. Quoted
  multiline strings require sequential COPY at this pin. Graph collection uses
  native logical types and recovers original snapshot records and lineage.

The native driver exposes JSON as text; collection decodes it into JSON cells.
This build has no JSON path functions. We did not install an upstream extension
or change Tentō to compensate. Graph-bearing UNION results are rejected because
the driver does not expose the active tag; ordinary mixed scalar unions work.

## Backend behavior

Added `semantic_validation`, `semantic_loader`, `semantic_collector`,
`semantic_worker` and `semantic_queries` modules. The schema route reports the
actual mapping. The run route accepts an owned complete graph snapshot, query,
parameters and projection settings, and returns an existing durable database job.
Generated API contracts include the new routes, request model and semantic job
kind.

Validation covers strings, quoted identifiers, comments and embedded prompt
inputs. It rejects writes, multiple statements, procedures, external loading,
extension installation, images, arbitrary functions and unapproved/dynamic model
aliases. Prompts must be literals. All five model operators, including both
subgraph aggregate forms, are verified with explicit mocks; `subgraph()` returns
graph values. `llm_score()` supplies its INT64 output automatically.

One disposable child loads the pinned native artifact and an in-memory database.
The parent monitors JSON-lines output independently of native execution. Timeout
and cancellation kill and reap the child, even when it hangs mid-event. Worker
files live in a private temporary directory and are removed on success/failure.
The current child inherits no provider credentials and sends no model HTTP
requests. Errors return stable codes and parser positions when available, without
echoing native query/property text. Progress reports observed stages and counters;
it does not invent matched-row or completed-judgment counts.

Semantic jobs retain owner/backend visibility, idempotency, account quotas,
pending-work limits, explicit retry and restart semantics. Active durable job rows
lease their base snapshots. Expiry/deletion cannot remove leased input; promotion
keeps its identity and lease. Completion, cancellation, failure or recovery releases
the lease. Queued jobs survive restart; running jobs become interrupted and are
not automatically replayed. No Neo4j refresh is required, including after a source
mapping/name change; access and input hash are still checked.

Successful collection validates the whole graph/table before the publication
boundary, then stores a new immutable preview with parent identity/hash. Original
versions remain unchanged. Save, chat attachment and table storage use existing
paths. Provenance includes the original source and filtered lineage, query and
parameters, model steps, loaded schema, engine commit/native hash, effective
settings, usage and simulation status. Derived row-projection edges have their
own identities and no invented SQL lineage.

## Usage and current limits

The provisional worker ceilings are 64 MiB input/output, 256 KiB parameters,
120 seconds, a 256 MiB native buffer pool, two compute threads, one mock dispatch
thread and batches of 16. Mock `call_limit` is clamped to 1,000 per expression.
The existing bounded queue/upload slots limit concurrent work. Admin settings and
shared live-provider capacity coordination belong to later authorized work.

`llm_usage()` resets on each read, so observations are accumulated. Two distinct
expressions with a limit of one made two mock calls: the result explicitly says
`call_limit_scope: per_expression` and `query_wide_call_limit_supported: false`.
A 40-input query with a one-call limit fails before dispatch because the engine
reserves the entire batch set. Its measured usage is **0 calls and 40 selected
`llm_rows`**, demonstrating why that counter is not completed judgments.

Mocks are explicitly selected in both the request and query. Provenance marks
simulation, zero HTTP requests and zero retained answers. There is no durable
answer-store workaround. Live calls and answer reuse return 503; estimation and
judgment-inspection routes remain unavailable.

## Verification

The final focused run passed **174 tests**, with no failures or skips, in 20.60
seconds. It includes all **92 new Phase 2 tests**, the nine Phase 1 engine tests,
and the affected API-contract, database-job, query-preview, dataset and database
workspace tests. TypeScript contract freshness and type checking passed.

| Area | Verified evidence |
| --- | --- |
| Mapping | Multiple labels/intersection, one vertex identity, typed IDs, mixed primitives, huge integers, nested JSON, empty/null/absent properties, reserved-name aliases |
| Collection | Native nodes/edges, paths with omitted endpoint nodes, arrays, nested structs, subgraphs, scalar lookalikes, parallel derived edges, finite weights, complete tables beyond samples |
| Read boundary | Writes/procedures/external functions rejected, prompt-expression checks, image rejection including escaped modifiers, approved literal aliases |
| Native execution | `llm`, `llm_score`, `llm_agg`, `llm_path_agg`, both `llm_sg_agg` signatures, `subgraph`, mock usage and per-expression exhaustion |
| Child lifecycle | Timeout, cancellation, process reaping, incomplete/invalid stdout events, temporary-file cleanup, provider-environment isolation, error redaction |
| Snapshots and queue | Ownership, hash integrity, lineage, save/chat, scalar tables, input leasing/expiry/promotion, idempotency, cancellation/retry, bounded queue, restart recovery |
| Optional engine | Startup without native loading; useful 503 when missing; ordinary database queries remain available |

The initial full `agent/tests` and `deploy/tests` run completed in 410.76 seconds:
**2,178 passed, 54 skipped, 3 failed and 4 setup errors**. Two failures introduced
by this phase were resolved and verified in the final focused run:

- Regenerated the TypeScript contracts for the new routes/model/job kind.
- Corrected the call-limit test's expected dispatch count from one to zero,
  after inspecting `reserveCalls(batches.size())` in the pinned runtime and
  reproducing its measured 0-call/40-selected-row behavior.

The remaining failure and four errors match the previously reproduced baseline
in the [Phase 1 report](tento_phase1_20261127.md): the embedded-client fixture
expects a data directory not to exist although fixture setup creates it, and four
Yelp cases call `neo4j_session()` without settings and fail before querying.
They are unrelated and unchanged. The full suite was not repeated after the two
fixes; the final affected-suite run was clean. The entire repository is therefore
not described as having a green full suite.

Logs and JUnit XML are retained under the workspace's
`validation/tento-phase2-20261127/`. Tests used development runtime paths,
four pytest workers, no visible GPU and isolated data directories. No service
was deployed, restarted or reconfigured. No live semantic request was sent.

## Remaining live acceptance

The [author requests](../../../deploy/tento/AUTHOR_REQUESTS.md) now mark label
mapping resolved by the user's approved GraphMine mapping. These requirements
remain open: thinking-off controls, strict JSON without fallback, an independent
durable answer store and a true query-wide budget including retries.

The engine remains pinned to
`62e124217e2c0f82e327136b5888263e95671fae`, with unchanged tracked source and
native SHA-256 `a388ba5ac37262944615148666791009050e37b11b6a442d4134c0f2cbf15c50`.
Clearing lock flags cannot enable live calls. Phase 2's approved mock/backend
scope is complete; the original end-to-end live gate is not. Phase 3 requires
the planned next-phase approval.
