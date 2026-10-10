# Typed analytics workflows

The application can now execute the verified Python library through
`/api/sessions/{session_id}/workflows`. Each step names a registered algorithm
and its parameters. Dependencies connect declared output ports to declared
inputs. Neither algorithm code nor expressions are generated or evaluated.

This is the API integration. The existing chat planner and browser still use
their earlier native execution path. The new browser modes, family-first
routing, native adapter, table operations, MCP access and two-GPU scheduler
remain separate work in the active implementation plan.

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
vector and hypergraph inputs use their declared input kinds and can be uploaded
as JSON attachments. Input kinds must match the algorithm card.

Available selectors are `top_vertices`, `top_vertex`, `group_vertices`,
`vertex`, `flatten_groups`, and `groups`. They have fixed typed contracts;
arbitrary JSON paths, functions and expressions are not accepted. Vertex IDs
remain integers or strings, preserving the distinction between `0` and `"0"`.
Bindings of vertex sets, individual vertices or groups must match the actual
input graph's fingerprint. Transferring IDs to a different graph, including a
coarsened graph, requires an explicit mapping integration that is not yet added.

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

- 19,505 CPU library tests passed with GPUs hidden; 1,546 cuGraph tests passed on
  each physical GPU. No failures or skips. As before, weighted/boundary cases
  repeat on both GPUs, so these counts are test executions, not distinct graphs.
- 254 new focused checks include dependent 2-core/extraction/PageRank workflows
  on all atlas graphs through six vertices, checked by independent peeling and
  linear algebra. They also cover malformed DAGs, typed IDs, namespaces,
  incompleteness, cache invalidation and evidence rejection.
- Fifteen application tests passed on both the working tree and staged
  application sources. These exercise all three API modes with the actual library,
  approval revision changes, pagination, stale evidence at execution, retries
  and result reuse. Separate fault-injection tests verify process-group
  cancellation/deadlines, CPU isolation and exclusive ledger ownership. Actual
  GPU workflows ran on each configured physical GPU and checked its recorded
  device assignment and numerical result. These are serial device checks, not
  evidence of concurrent two-GPU scheduling.

Reports and source/dependency metadata are in `validation/python_analytics/`.
CPU contract coverage remains 57 of 70; these workflow additions do not claim
new algorithm or browser coverage.
