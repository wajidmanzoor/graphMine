# Typed analytics workflows

The application can now execute the verified Python library through
`/api/sessions/{session_id}/workflows`. Each step names a registered algorithm
and its parameters. Dependencies connect declared output ports to declared
inputs. Neither algorithm code nor expressions are generated or evaluated.

The default browser workspace at `/` uses this library and the three modes.
The previous native workspace remains at `/classic`. Native adaptation,
deterministic table operations, MCP access and two-GPU scheduling are still
separate work in the active implementation plan.

## Browser workspace

Open `/`, configure the API token through **Connection** if required, and upload
a canonical graph or relationship CSV. Upload settings also accept feature
vector and hypergraph JSON with an explicit input kind. Choose **CPU only**,
**GPU only**, or **Automatic**, then either describe a question or browse a task
family and select an exact calculation. The available choices come from the
current evidence-checked operation cards. The task picker works with the
question planner disabled.

Interactive mode shows the input scope, dependency sources, parameters, method
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

`POST /api/sessions/{session_id}/analytics/plan` first selects a task family,
then a shortlist of exact operations within that family, then a typed workflow.
Each stage uses a constrained JSON schema. A wrong-family decision may reroute
once. A rejected workflow may receive one contract-based repair while retaining
the selected operations and device policy. Unresolved ambiguity returns a
question rather than a guessed execution. Planning alone does not save or run
a workflow; the selected execution mode governs the next API request.

The request contains `message`, uploaded `inputs`, `device`, optionally
`family_id`, and optionally `previous_workflow_id` for a follow-up. A previous
workflow must belong to the current session. Context includes its reviewed plan
and bounded input metadata/samples; samples are identified as excerpts.

The planner uses the configured base model through the OpenAI-compatible
`GRAPHMINE_LLM_BASE_URL`, with `GRAPHMINE_LLM_ENABLED=true`. Its schema differs
from the previous native-operation routing adapter. Authored-decision and HTTP
transport tests verify the constraints and application wiring. They are not
evidence of a model's routing accuracy. Held-out evaluation against the deployed
model and full natural-language conversation evaluation remain open.

## Configuration and capabilities

The worker interpreter defaults to `.venv-analytics/bin/python` under the
repository. Set `GRAPHMINE_ANALYTICS_PYTHON` to use another installed analytics
environment. The ASGI process does not import CUDA or the analytics package.
No Node.js process is involved in workflow execution.

`GET /api/analytics/capabilities` exposes the registered family/operation cards,
executable parameters, possible output ports, quality claims and current test
evidence. An output port may depend on the selected operation variant; its
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
problem variant. Native and research-only implementations have separate evidence.

## Modes and review

- **Normal:** validate the supplied plan, save the input snapshot, then queue it.
- **Interactive:** validate and save the plan for review. Execution requires its
  current workflow hash and revision number.
- **Expert:** accept an explicit structured plan, validate it, and wait for an
  explicit run request with the current hash and revision.

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
  "mode": "interactive",
  "inputs": {"main": {"file_id": "UPLOADED_FILE_ID", "kind": "graph"}},
  "plan": {
    "version": 1,
    "device": "cpu",
    "steps": [
      {
        "id": "core",
        "operation": "k-core",
        "input": {"input": "main"},
        "parameters": {"requested_k": 2}
      },
      {
        "id": "subgraph",
        "operation": "induced-subgraph",
        "input": {"input": "main"},
        "bindings": {
          "vertices_or_seeds": {"step": "core", "port": "vertices"}
        }
      },
      {
        "id": "rank",
        "operation": "pagerank",
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

## Execution, limits and reuse

Workers use a separate process group. Cancellation and wall-clock deadlines
terminate that group, including a native call or child process. CPU requests
receive `CUDA_VISIBLE_DEVICES=''`. GPU requests use the configured graph GPU;
automatic selection can use CPU while preserving the requested parameters.
Automatic steps without current GPU evidence are explicitly routed to CPU.
The current analytics queue is serial; memory-aware two-GPU admission remains
open. No new LLM/GPU sharing policy is introduced by these endpoints.

Plans contain at most 64 steps. Combined input snapshots default to 64 MiB,
configurable with `GRAPHMINE_ANALYTICS_MAX_INPUT_BYTES`. Existing job timeout,
result byte and pending-job limits also apply. Each step retains its declared
candidate, output and cooperative time budgets. Exceeding a budget produces a
failure or explicitly incomplete output, according to the operation contract.

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
  `complete: false` to the operation and workflow, while count-only operations
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
  staged application sources. These exercise all three
  API modes with the actual library,
  approval revision changes, pagination, stale evidence at execution, retries
  and result reuse. Separate fault-injection tests verify process-group
  cancellation/deadlines, CPU isolation and exclusive ledger ownership. Actual
  GPU workflows ran on each configured physical GPU and checked its recorded
  device assignment and numerical result. These are serial device checks, not
  evidence of concurrent two-GPU scheduling. Routing tests replay authored
  decisions, including ambiguity, rerouting, bounded repair, follow-up scope
  and attempts to escape the allowed operation/parameter schema.
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
