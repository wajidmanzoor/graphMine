# Typed analytics workflows

## Reuse, comparison and report APIs

The application exposes private dataset versions through `GET/POST /api/datasets`
and `DELETE /api/datasets/{version_id}`. Saving accepts either an owned `file_id`
and input kind, or `workflow_id`, `expected_revision`, `step`, `port` and an
optional `group_index`. A `dataset_id` appends a new version. Import with
`POST /api/sessions/{session_id}/datasets/{version_id}/import`; the returned
conversation-local file is an ordinary workflow input. Stored provenance is
copied into each workflow's `input_provenance` and report manifest.

`POST /api/sessions/{session_id}/files/preview` accepts a multipart CSV/edge list
and optional `source_column`, `target_column` and `directed` fields. It validates
the complete file on CPU and returns samples without storing an upload.
`POST /api/sessions/{session_id}/projections` defaults to `device: "cpu"`:
CSV tables are read with the bounded CPU parser and passed as inline tables to
native construction. Explicit `device: "gpu"` retains the cuDF reader and GPU
admission. Both paths preserve the projection contract and source provenance.

`GET/POST /api/workflow-templates` lists or saves private validated plans.
`POST /api/sessions/{session_id}/workflow-templates/{template_id}/use` accepts
`inputs` and optional `parameters` keyed by step ID. It validates all bindings
and always returns an unapproved Expert workflow. Templates can be deleted
without changing runs made from them.

`GET /api/workflow-history` lists up to 200 recent owned analyses.
`POST /api/workflows/compare` accepts two to six distinct `workflow_ids` and
returns recorded settings, backends, completeness, exact scalar values and input
fingerprint comparability. It reads saved artifacts only.

`GET /api/workflows/{id}/steps/{step}/ports/{port}/csv` exports the whole retained
port, independent of browser paging. `GET /api/workflows/{id}/report` returns a
deterministic ZIP for that revision with JSON artifacts, full tables, an offline
HTML summary and a hash manifest. Neither endpoint starts computation.

Database schema 2 adds owner-scoped datasets, version counters and templates;
schema 3 adds shared project snapshots and storage accounting. Older code refuses
a newer schema. Rollback requires the matching pre-upgrade backup or compatible code.

`GET/POST /api/projects` lists/creates projects. Owners manage membership through
`POST /api/projects/{id}/members` (`username`, `role: editor|viewer`) and
`DELETE /api/projects/{id}/members/{user_id}`. Publishing through
`POST /api/projects/{id}/items` accepts `name` and one owned `file_id`,
`version_id`, or `workflow_id` with `expected_revision`. It copies data without
changing private session access.

`GET /api/project-items/{id}` returns a snapshot and its notes. POST to
`/annotations` adds `text`; POST to `/views` saves `name`, `layout`, typed
`selected` IDs and `{vertex,x,y}` positions. POST to `/links` takes `days` (1–30)
and returns a read-only URL. Owners revoke with `DELETE /api/project-links/{id}`.
The unauthenticated `POST /api/shared/read` accepts a link `token` and returns
only that snapshot. `POST /api/sessions/{sid}/project-items/{id}/import` creates
an independent input copy after checking membership and session ownership.

`GET /api/connectors` exposes authorized source identifiers, names and types.
`POST /api/connectors/{id}/preview` reads a configured SQLite table or REST export.
Its `sha256` is required as `expected_sha256` by
`POST /api/connectors/{id}/import`, together with dataset `name` and optional
existing `dataset_id`. Changed data returns 409. Browser requests cannot supply
arbitrary paths, endpoints or credentials.

The application can now execute the verified Python library through
`/api/sessions/{session_id}/workflows`. Each step names a registered algorithm
and its parameters. Dependencies connect declared output ports to declared
inputs. Neither algorithm code nor expressions are generated or evaluated.

The default browser workspace at `/` uses this library with Normal and Expert modes.
The previous native workspace remains at `/classic`. Native adaptation,
multi-table problems and MCP access are still
separate work in the active implementation plan.

The **Look up & summarize records** family provides deterministic entity and
relationship queries, neighbors, paths, exact aggregates, and graph extraction.
Its typed vertex/edge outputs can feed later steps. See the
[record-query guide](RECORD_QUERIES.md) for predicates, direction, exact values,
completeness and a dependent workflow example.

## Backend admission and run telemetry

Native workflow steps use the native `backend_capabilities` preflight, retaining
only compiled, evidence-admitted backends with supported inputs and declared
size/index bounds. Their predicted peak memory must fit within 80% of measured
free RAM or the leased GPU's free memory. GPU jobs use **physical GPU 1** only;
the worker sees that UUID as CUDA logical device 0. A shared filesystem lease
serializes GPU work across app workers and offline benchmarks for the account,
independently of their data directories. The lease is runtime state at
`/run/user/<uid>/graphmine-gpu-1.lock`. Worker processes inherit it so a parent crash cannot
release it while native work survives. CPU and explicit device choices retain their existing semantics.
An explicit native backend that fails admission produces an error.

The safe default is `legacy`: first feasible GPU in native order, otherwise `cpp`.
Aggregate terminal rows, including preflight rejections and failed attempts,
are appended asynchronously under `backend_data_dir` (default
`/data/labdata/wajid/graphmine_data/rlModelData`). Run-log schema 4 adds model
predictions, shadow choices, exploration reservations and fallback identities
to benchmark provenance and feasibility. Schemas 1–3 remain readable. `SCHEMA.md` in the
data directory defines the fields. Exports and reports use the authoritative
JSONL through `graphmine backend-runs export` and `graphmine backend-runs report`.

`graphmine backend-runs fit-memory` rebuilds the per-backend memory documents
from non-evaluation rows. Fits use nonnegative intercept, vertex, edge and
output-budget coefficients. Each problem/implementation/hardware/parameter
context needs at least 20 completed observations across five snapshots, an
independent snapshot holdout with no underprediction, and a 25% safety margin.
Outside a validated fit's range, the existing conservative estimate applies.
The asynchronous writer immediately adds OOM memory lower bounds for the same
snapshot and context. Rebuilding under the same lock preserves those bounds. Workflow
admission still reserves the conservative estimate regardless of fitted weights.
No additional observations are generated to activate a fit: initial warm-start
collection is limited to **1–3 examples per algorithm**, with later usage
providing further observations. Shadow selection is available; live selection
requires the measured gates described below.

## Offline backend benchmarks

Run `tools/benchmark_backends.py` with the agent Python environment in a named
`tmux` session, outside the web app. The default bootstrap records at most three
terminal attempts **per algorithm across all graphs and benchmark IDs** for the
same native implementation. `--examples-per-problem 1` or `2` lowers that cap.
It measures `cpp` first, then admitted GPUs in native order (or a configured
bootstrap subset for incompatible parameter profiles), repeating only after
each selected backend has had an opportunity within the cap. Failures and unfinished
attempts consume the cap. It never generates extra samples to enable a fit.

```bash
tmux new-session -d -s graphmine-bootstrap \
  '.venv/bin/python tools/benchmark_backends.py --benchmark-id initial'
```

`benchmarks/backend_selection.json` describes 60 fixed graph configurations:
36 seeded Erdos-Renyi, preferential-attachment and planted-dense graphs, eight
typed small inputs, and 16 bounded extracts from the four verified Neo4j datasets.
The bootstrap lazily prepares one appropriate snapshot per problem. Neo4j
reads use the registered read-only path, transaction timeouts, row/byte limits,
and rollback. Only anonymous simple topology is saved, with its extraction
query and parameters; source labels, properties and element IDs are discarded.

The full configured workload requires explicit `--full`. It runs every admitted
backend, including `cpp`, for each applicable graph and parameter combination,
with three repetitions and a hard 1,800-second deadline per attempt. Physical
GPU 1 is the only permitted GPU; current free memory is rechecked after support
preflight. `--is-evaluation` excludes a collection from all training.

Use the same `--benchmark-id` to resume. The manifest pins code, native binary,
implementation, parameters, and graph hashes. Completed attempts are skipped;
uncertain attempts are recovered once from their journals, and verified live
workers are awaited. Changed manifests require a new ID, which still shares
the bootstrap quota. Paths can be configured with `--data-dir` and `--model-dir`;
repository and `/tmp` destinations are rejected.

Results live under `backend_data_dir/benchmarks/<id>/`: `runs.jsonl` is the
append-only authoritative log; `config.json`, canonical `graphs/` and provenance,
`attempts/` recovery journals, `status.json`, and `summary.json`/`summary.csv` are supporting
artifacts. The summary reports medians, ranges, spread, fastest observed backends
and wins for identical inputs, parameters, budgets and implementations. It marks
incomplete backend coverage explicitly; a tiny bootstrap is not a full oracle.

## Backend runtime models and shadow rollout

`GRAPHMINE_BACKEND_SELECTION=shadow` predicts a backend but executes the legacy
native `auto` choice. Workflow steps can name `backend: <id>` explicitly; that
choice must be compiled, admitted, input-compatible and consistent with the
device policy. Forced choices are never replaced. An unavailable or corrupt
model leaves native `auto` in control and records a warning.

Each multi-backend problem has a Bayesian linear model with a separate reward head per
backend. The reward is `-log(seconds)`. Aggregate graph sizes and shape,
input flags, safe parameter values/counts, physical GPU 1 memory, busy state and
model are standardized using training rows only. An isolation flag distinguishes
older direct benchmark timings from supervised application timings. No user,
vertex identifier or label is a feature. A newly admitted head has a wide Normal
prior (intercept variance 25, slope variance 4). Observation variance is fixed
at 1 in log-seconds; predictive p90 includes that noise. A timeout contributes
`-log(2 * timeout_seconds)`; an OOM updates memory feasibility only.

Train and report from the existing authoritative history:

```sh
graphmine backend-model train
graphmine backend-model report
graphmine backend-runs report --problem triangle-counting
graphmine backend-model rollback triangle-counting
```

The native CLI uses `GRAPHMINE_ANALYTICS_PYTHON` and the configured runtime
checkout. The agent CLI exposes the same subcommands. Nightly fitting is a
CPU-only CLI job; it never launches a benchmark or generates more examples.
`deploy/install-backend-model-timer.py --config <private-environments.json>`
installs one user timer for the deployed production environment, at 03:15 local
time with up to 15 minutes jitter. `--check` validates the units without installing
them. Application shutdown does not interrupt this independent fit job.
Standalone installs can instead supply `--env-file <private-environment-file>`.

Models live only under `backend_model_dir` (default
`/data/labdata/wajid/graphmine-models/rlModel`), as
`<problem>/<UTC-timestamp>-<data-hash>/{model.json,metadata.json}`. Versions are
immutable plain JSON. `current` and `previous` are atomic text pointers, never
symlinks. The first model is available for shadow use; subsequent candidates
replace `current` only after their mean, worst and permitted-exploration regret
are no worse than the previous weights on the same held-out comparisons. A
runtime upgrade compares previous weights against current implementation
measurements, without training on the old implementation's timings. Invalid
previous files fail closed and remain untouched. Rollback verifies the previous
files, swaps the two pointers and recomputes rollout eligibility. Workers reload
when pointers or files change and verify the model hash.

One narrowly checked warm-start exception preserves data across a standalone CLI
dispatcher change: both evidence inventories must have identical non-CLI sources,
profiles, isolated workers, dependency binaries and isolated build recipes. The
current native binary still needs fresh correctness admission. Only historical
benchmark rows qualify; application shadow history never receives this exemption.
JSONL retains its original implementation hash. Model metadata records both
implementations, their binary hashes, the source proof and observation counts.
Any algorithm/runtime or dependency change excludes the old benchmark timings.

The permanent snapshot split reserves approximately 20% of fingerprints for
held-out comparisons; repeated runs of a graph cannot enter both partitions.
Reports require complete feasible backend coverage for a measured oracle.
Missing comparisons remain missing. Reports include selection accuracy, failure
rate, mean/worst regret and legacy, fastest-on-average and oracle baselines.
Warm-start fit diagnostics are explicitly in-sample and never satisfy a live
gate. Evaluation records never train a model, grant exploration budget or count
toward shadow observation.

By default, live selection requires every multi-backend problem to have at least 14 days
of real shadow history or 200 real shadow decisions, plus measured superiority
over both non-oracle baselines and worst regret at most 1.5. Comparisons require
at least five distinct held-out snapshots and two training comparison snapshots.
The gate also bounds the cost of all exploration choices permitted by the policy,
instead of trusting one favorable random seed. A release manifest pins every
current version, the native implementation and correctness admission. Setting
`GRAPHMINE_BACKEND_SELECTION=bandit` while these gates are incomplete continues
shadow execution and records the unmet gate.
Live execution also requires exploration settings covered by that evaluation.
Increasing the budget or slowdown cap, or enabling previously disabled
exploration, returns execution to shadow until evaluated. Tightening limits or
switching exploration off takes effect immediately without extra training.

An operator can explicitly activate the existing weights before those rollout
metrics pass by setting `GRAPHMINE_BACKEND_SELECTION=bandit` and
`GRAPHMINE_BACKEND_REQUIRE_ROLLOUT_EVIDENCE=false`. This waives the rollout wait
and evaluation gate. Model hashes and implementation identity, native correctness
admission, memory feasibility, forced choices and exploration limits still apply.
Telemetry records `rollout_evidence_required=false`; the measured readiness
report remains unchanged. Missing or invalid weights still use native `auto`.
Nightly publication continues to require held-out nonregression.

When live, only feasible candidates participate in Thompson sampling. Exploration
must satisfy the 1.5× p50 cap and the completed graph-size range. A head with fewer
than five runs may instead use its measured benchmark range. Unknown ranges
cannot authorize exploration. Per-problem daily reservations use a locked
ledger against completed log entries; lost reservations conservatively consume
budget. Fallback attempts share one decision identity. Defaults and controls:

| Environment setting | Default |
| --- | --- |
| `GRAPHMINE_BACKEND_SELECTION` | `legacy` |
| `GRAPHMINE_BACKEND_REQUIRE_ROLLOUT_EVIDENCE` | `true` |
| `GRAPHMINE_BACKEND_EXPLORATION_ENABLED` | `true` |
| `GRAPHMINE_BACKEND_EXPLORATION_BUDGET` | `0.10` |
| `GRAPHMINE_BACKEND_MAX_EXPLORE_RATIO` | `1.5` (maximum 1.5) |
| `GRAPHMINE_BACKEND_MIN_TIMEOUT_SECONDS` | `60` |
| `GRAPHMINE_BACKEND_MEMORY_SAFETY` | `0.8` |

Each native attempt runs in a killable child. The live timeout is
`min(1800, remaining_step_budget, job_limit, max(min_timeout, 3 * p90))`.
A timeout or OOM permits one retry with the next-best feasible backend after
fresh admission, excluding the previous backend. Other failures are not retried.
The full step, including preparation and fallback, shares a deadline of at most
1,800 seconds and retains any smaller reviewed budget. Under 60 seconds remaining,
fallback is skipped with a clear timeout message. The parent watchdog enforces
the step deadline even if a worker becomes unresponsive, kills descendants before
releasing the GPU lease, and records exactly one terminal row per attempt.

## Browser workspace

For maximal bicliques, the application prepares complete partitions from the
full selected snapshot and checks that every edge crosses between them. The
model can select an offered entity-type choice (for example Users or Businesses);
the server supplies both complete vertex-ID arrays before native validation.
Complete `attributes.side` declarations are also supported. Sampled vertices
never stand in for a complete partition. Missing sides become a clarification,
and directed inputs require confirmation before creating an undirected copy.
Partitions remain scoped to their original graph; transformed graphs require
partitions belonging to that transformed graph.
Prepared biclique plans use a 20-million-candidate search budget because the
two completed sides produce more candidates than the original edge count
suggests. The native 60-second and 100,000-output-item defaults still apply;
explicit execution budgets are preserved.

Open `/`, configure the API token through **Connection** if required, and upload
a canonical graph or relationship CSV. Upload settings also accept feature
vector and hypergraph JSON with an explicit input kind. Choose **CPU only**,
**GPU only**, or **Automatic**, then either describe a question or browse a task
family and select an exact calculation. The available choices come from the
current evidence-checked problem cards. The task picker works with the
question planner disabled.

Expert mode shows the input scope, dependency sources, parameters, method
quality and execution device before approval. Step settings can be edited in
place; every edit creates a new review revision. Expert mode exposes the same
validated workflow as structured JSON. Uploaded inputs use `main` for the
active input and stable `data_N` aliases for the other files. Pattern matching
and graph comparison fields can bind another uploaded graph directly.

The browser uses locally served Cytoscape and plain JavaScript/CSS. No Node.js
runtime or build step is needed. Graph layouts, score bars, group-size bars and
result tables are predefined. A model cannot supply rendering code. Selecting
a graph vertex, score bar or result row links the other views. Graph previews
show at most 500 vertices and 2,000 edges; calculations still use the full
input. Selection outside the preview is identified explicitly. Layout positions
are display coordinates, not computed graph metrics.

When a layout algorithm returns a `vertex_positions` port, **Computed
coordinates** displays those values with uniform scale. Three-dimensional
positions use a labeled XY projection; all three coordinates remain in the
table and export. Choosing a display layout changes only the drawing.

Tables search and page the retained result collection; they do not change the
calculation. Output completeness is distinct from pagination and graph-preview
limits. The raw provenance preview is bounded, with a full JSON download.
Cancelled/interrupted workflows can expose their completed steps without
pretending that the whole workflow finished. A lossless JSON codec and typed
vertex keys preserve `0`, `"0"` and adjacent integers beyond JavaScript's safe
integer range through plans, tables, graph selection and exported results.

## Question planning

`POST /api/sessions/{session_id}/analytics/plan` makes one routing call, then,
for a new calculation, builds a typed workflow. Routing sees a compact listing
of every problem, grouped by task family, and returns one intent:

- `calculate`: the exact problems to plan. The plan stage then sees their
  full cards.
- `view`: a display change of the saved result (show a group or clique, change
  the layout, highlight named entities, open another output, search its rows or
  open the results page). The response has `status: "view"` and a `view`
  action the page carries out. Nothing is computed.
- `explain`: the saved result's computed facts already answer the question.
  The response has `status: "answered"` and the chosen fact statements in
  `answer`. The model's lead sentence is dropped if it contains a digit.
- `needs_information` or `unsupported`.

`view` and `explain` exist only when the previous workflow has a saved result.
Their schemas list only that result's outputs, group labels ("Clique 3",
"Group 7", as on the page), available layouts, matched entities and fact IDs.
The server writes the chat reply for a view from the checked action, not from
the model. Each stage uses a constrained JSON schema. A rejected workflow may
receive one contract-based repair while retaining the selected problems and
device policy. Unresolved ambiguity returns a question rather than a guessed
execution. Planning alone does not save or run a workflow; the selected
execution mode governs the next API request.

The request contains `message`, uploaded `inputs`, `device`, optionally
`family_id` (a hint; routing may choose problems from other families), and
optionally `previous_workflow_id` for a follow-up. A previous
workflow must belong to the current session. Context includes its reviewed plan
and bounded input metadata/samples; samples are identified as excerpts.

The planner uses the configured base model through the OpenAI-compatible
`GRAPHMINE_LLM_BASE_URL`, with `GRAPHMINE_LLM_ENABLED=true`. Its schema differs
from the previous native-problem routing adapter. Authored-decision and HTTP
transport tests verify the constraints and application wiring. They are not
evidence of a model's routing accuracy. Held-out evaluation against the deployed
model and full natural-language conversation evaluation remain open.

## Configuration and capabilities

The worker interpreter defaults to `.venv-analytics/bin/python` under the
repository. Set `GRAPHMINE_ANALYTICS_PYTHON` to use another installed analytics
environment. The ASGI process does not import CUDA or the analytics package.
No Node.js process is involved in workflow execution.

`GET /api/analytics/capabilities` exposes the registered family/problem cards,
executable parameters, possible output ports, quality claims and current test
evidence. An output port may depend on the selected problem variant; its
availability and completeness are checked again before consumption.

The worker rechecks the evidence on validation and execution. It reads the
JUnit reports and their metadata, checks report/metadata hashes, the exact
Python source and formal-contract inventory, dependency versions, Python
runtime, collected test count and zero failures/errors/skips. CPU evidence must
cover every library test module with GPUs hidden. GPU evidence must include
both fixture shards. A profile card must match the audited profile hash.
Stale or missing evidence blocks that profile in this application path.

The report inventory is `catalog/python_analytics_coverage.json`. Regenerate it
with `tools/audit_python_analytics.py --write` in the tested analytics environment
after running the complete CPU and GPU suites. Regenerating the inventory alone
does not make stale reports valid. These checks establish the recorded test
coverage, not correctness for every possible input or support for every formal
topic variant. Native and research-only implementations have separate evidence.

## Modes and review

- **Normal:** validate the supplied plan, save the input snapshot, then queue it.
- **Expert:** validate a generated or explicit structured plan, save it for
  review and editing, and wait for an explicit run request with the current
  hash and revision.

Question planning defaults to Normal. Creating or revising a workflow through
the API defaults to Expert, so omitting the mode never bypasses approval. These
are the only accepted modes. Older saved manual workflows open as Expert while
retaining their results, revision and approval requirements.

Every revision resets approval, execution status and timestamps. Approval for a
previous revision is rejected even if the plan content happens to be identical.
The workflow hash includes normalized parameters and budgets, input fingerprints,
library implementation and dependency versions. A change between review and
execution requires a new validation/review. Uploaded inputs are copied to a
workflow revision snapshot; the reviewed job uses that snapshot.

All endpoints use the existing API authentication. Uploaded file references must
belong to the workflow's session. Requests accept file IDs rather than arbitrary
filesystem paths. Client-supplied resume records are not accepted.

## Example: select a core, extract it, rank it

After uploading a canonical graph with the existing file API, create a workflow:

```json
{
  "mode": "expert",
  "inputs": {"main": {"file_id": "UPLOADED_FILE_ID", "kind": "graph"}},
  "plan": {
    "version": 1,
    "device": "cpu",
    "steps": [
      {
        "id": "core",
        "problem": "k-core",
        "input": {"input": "main"},
        "parameters": {"requested_k": 2}
      },
      {
        "id": "subgraph",
        "problem": "induced-subgraph",
        "input": {"input": "main"},
        "bindings": {
          "vertices_or_seeds": {"step": "core", "port": "vertices"}
        }
      },
      {
        "id": "rank",
        "problem": "pagerank",
        "input": {"step": "subgraph", "port": "graph"}
      }
    ]
  }
}
```

The response contains `id`, `revision`, and
`validation.workflow_hash`. Send these last two values to
`POST /api/workflows/{id}/run`:

```json
{"workflow_hash": "RETURNED_64_CHARACTER_HASH", "expected_revision": 1}
```

`POST /api/workflows/{id}/revise` accepts a replacement workflow request with
`expected_revision`. It rejects concurrent stale edits and edits to a running
or queued job. Editing a failed workflow's budget can permit a retry while
preserving its mathematical objective.

The Python API also exposes the same DAG validation and execution functions:

```python
from graphmine.workflows import validate_workflow, execute_workflow

inputs = {"main": {"kind": "graph", "data": canonical_graph}}
checked = validate_workflow(plan, inputs)
result = execute_workflow(plan, inputs)
```

Direct Python calls remain a library API and do not enforce the application's
local evidence gate or hard process deadline. Callers must use isolated workers
when cancellation of native numerical calls is required.

## Binding rules and results

Graph inputs can refer to an uploaded graph or a generated graph port. Feature
vector, hypergraph and graph-collection inputs use their declared input kinds
and can be uploaded as JSON attachments. A graph collection has `dataset_id`
and a `graphs` array of canonical graphs with unique graph IDs and consistent
direction. Its members keep separate vertex namespaces. Input kinds must match
the algorithm card.

Available selectors are `top_vertices`, `top_vertex`, `group_vertices`,
`vertex`, `flatten_groups`, `groups`, and `pattern_graph`. They have fixed typed contracts;
arbitrary JSON paths, functions and expressions are not accepted. Vertex IDs
remain integers or strings, preserving the distinction between `0` and `"0"`.
Bindings of vertex sets, individual vertices or groups must match the actual
input graph's fingerprint. Transferring IDs to a different graph, including a
coarsened graph, requires an explicit mapping integration that is not yet added.

`{"step":"mine","port":"patterns","select":{"kind":"pattern_graph","index":0}}`
selects a canonical graph from a complete `pattern_collection` port. Its graph
fingerprint and vertex namespace belong to that pattern. Pattern vertices must
not be treated as original host vertices; MNI image sets explicitly record the
host IDs when requested. Count-only mining has no patterns port. The browser's
fixed pattern view lets users select a row to inspect that pattern's graph and
support, and labels the separate vertex namespace.

Graph edit distance exposes its exact cost as a `rational_scalar`, retaining
integer numerator and denominator alongside a display value. The browser
marks a rounded display with `≈`; the exact fraction remains in the table and
download. This port cannot be bound implicitly to an ordinary numeric
parameter. Its edit table uses stable handles and retains original IDs in
record payloads. Maximum common subgraph returns a regular graph port for
downstream analysis, with identity derived from both comparison inputs.

The executor validates cycles and references before running any step. It then
checks actual output availability, completeness, graph identity and resolved
parameters. A count-only or truncated collection cannot become an exhaustive
downstream input. Failed dependencies mark affected steps `blocked`; independent
steps may still complete. A completed workflow with capped output retains
`complete: false`.

| Endpoint | Purpose |
|---|---|
| `GET /api/sessions/{session_id}/workflows` | Saved workflows in a session |
| `GET /api/workflows/{id}` | Status, reviewed plan, per-step summaries and errors |
| `GET /api/workflows/{id}/result` | Full saved workflow result for the current revision |
| `GET /api/workflows/{id}/steps/{step}/result` | A completed step, including when another step failed or execution was cancelled |
| `GET /api/workflows/{id}/steps/{step}/ports/{port}?offset=0&limit=100` | A bounded port page with collection completeness and total retained items |
| `DELETE /api/workflows/{id}` | Cancel queued or running execution |

Port pagination reports `has_more` separately from collection `complete`.
An API page can be partial while the saved collection is complete, and a fully
read saved collection can itself be a truncated algorithm output.

For `vertex_groups` ports, pagination also accepts inclusive `min_size` and
`max_size` bounds and an exact `member` ID. Member IDs use JSON integers or
strings (`member=42` differs from `member="42"`); plain non-JSON text is a string
ID. Other JSON types, negative sizes, reversed size bounds and group filters on
non-group ports are rejected. Filters combine with `search` and `sort` before
paging. Response `positions` remain indices into the original saved collection,
for subsequent group-graph and planner selection requests.

`GET /api/workflows/{id}/result?summary=true` adds `group_summary` to group ports:
`groups`, `unique_members`, `shared_members`, `smallest`, and `largest` describe
the full retained collection even when `value` is shortened for the browser.
The original saved result and completeness flags are unchanged.

`POST /api/workflows/{id}/steps/{step}/ports/{port}/memberships` accepts
`{"vertices": [1, "1"]}` with 1–500 integer or string IDs. It returns a bounded
`memberships` list of `{vertex, groups}` counts across the full retained
collection, plus `total_groups`, `complete` and `scope: "retained_groups"`.
Duplicate IDs within one group count once. Missing IDs have count zero.
Ownership is checked before loading the result. This display request uses the
preview concurrency limit and consumes no model tokens or daily job allowance.

## Execution, limits and reuse

Isolated workers cache evidence-file hashes under
`analytics/cache/evidence-hashes.json` in their own data store. Reuse requires
unchanged device, inode, size, modification time and change time. Each worker
still validates native admission, sources, reports and dependencies. The cache
is installed by the application bootstrap, without modifying the verified
library sources. Invalid or unavailable cache storage falls back to hashing;
cache files are private and replaced atomically.

Workers use a separate process group. Cancellation and wall-clock deadlines
terminate that group, including a native call or child process. CPU requests
receive `CUDA_VISIBLE_DEVICES=''`. GPU requests use the configured graph GPU;
automatic selection can use CPU while preserving the requested parameters.
Automatic steps without current GPU evidence are explicitly routed to CPU.
The current analytics queue is serial; memory-aware two-GPU admission remains
open. No new LLM/GPU sharing policy is introduced by these endpoints.

Plans contain at most 64 steps. Combined input snapshots default to 64 MiB,
configurable with `GRAPHMINE_ANALYTICS_MAX_INPUT_BYTES`. Complete database-query
graphs are exempt from that input byte cap, including their saved input snapshots
and worker transport. Ownership, account storage, and hardware memory admission
still apply. Existing analytics job timeout,
result byte and pending-job limits also apply. Each step retains its declared
candidate, output and cooperative time budgets. Exceeding a budget produces a
failure or explicitly incomplete output, according to the problem contract.

The SQLite ledger and revision artifacts live under the agent data root's
`analytics/` directory. An interrupted service marks unfinished execution
`interrupted`; it does not silently restart expensive work. Successful step
records can be reused on an explicit retry or revision. Reuse checks resolved
inputs/parameters, step settings, implementation and dependency versions, device
policy, and stored result hashes. Corrupt entries are recomputed. Cache records
are trusted local artifacts, not client-submitted results or signed certificates.

## Verification for this checkpoint

- 29,098 CPU library tests passed with GPUs hidden; 1,546 cuGraph tests passed on
  each physical GPU. No failures or skips. As before, weighted/boundary cases
  repeat on both GPUs, so these counts are test executions, not distinct graphs.
- The workflow suite includes dependent 2-core/extraction/PageRank workflows
  on all atlas graphs through six vertices, checked by independent peeling and
  linear algebra. They also cover malformed DAGs, typed IDs, namespaces,
  incompleteness, cache invalidation and evidence rejection. An additional 106
  checks compare capped clique/triangle lists with independent combinations
  across atlas graphs through five vertices. Capped listings now propagate
  `complete: false` to the problem and workflow, while count-only problems
  retain complete counts with incomplete materialized-list ports.
- A further 2,525 checks cover exact diffusion, force-law energy and iteration
  equations, and spectral quadratic-form ratios. Random-threshold diffusion
  is checked independently by integrating threshold intervals; sparsifier bounds
  use an independent orthogonal Laplacian basis. Work-budget failures and
  unsupported options are included.
- Pattern mining adds 2,300 checks covering independent transaction/MNI support,
  complete pattern universes, labels, direction, image sets and dependent pattern
  graphs. Graph comparison adds 4,662 checks using exhaustive partial vertex
  injections and independently replayed edit scripts, including exact cost
  fractions and rejection of bindings across distinct comparison inputs.
- The application/planner suite passed all 40 checks on both working-tree and
  staged application sources. These exercise both
  API modes with the actual library,
  approval revision changes, pagination, stale evidence at execution, retries
  and result reuse. Separate fault-injection tests verify process-group
  cancellation/deadlines, CPU isolation and exclusive ledger ownership. Actual
  GPU workflows ran on each configured physical GPU and checked its recorded
  device assignment and numerical result. These are serial device checks, not
  evidence of concurrent two-GPU scheduling. Routing tests replay authored
  decisions, including ambiguity, rerouting, bounded repair, follow-up scope
  and attempts to escape the allowed problem/parameter schema.
- Ten browser checks passed on both working-tree and staged application
  sources. They use actual Firefox, API and library computations with Node
  absent from the server PATH. They cover approval/editing, dependent plans,
  lossless IDs and downloads, narrow-screen layout, linked selections, paging,
  preview limits, graph-input bindings, workspace reset and question-to-workflow
  transport. The coordinate-view test checks uniform scaling, typed vertex IDs,
  the explicit 3D-to-XY projection and switching to a display-only layout.
  Pattern checks cover graph-collection upload, selected canonical patterns,
  original MNI image IDs and count-only output. Graph-comparison checks cover
  lossless exact fractions, visibly rounded display values, edit records and
  common-subgraph-to-degree workflows.
  The model transport is an authored fixture, not a real LLM.
  The two `/classic` browser regressions passed at the earlier workspace
  checkpoint against the working tree, using their synthetic native executable
  fixture; they were not rerun for these library additions.

Reports and source/dependency metadata are in `validation/python_analytics/`.
Current reports use the `graph-pair` suffix. CPU contract coverage is 63 of 70,
with seven integrations still required. GPU coverage remains 13 cuGraph profiles.
The browser tests cover the new workspace;
the retained `/classic` workspace still has its earlier execution policy.
