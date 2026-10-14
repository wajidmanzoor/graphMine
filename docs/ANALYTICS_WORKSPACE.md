# Native analysis workspace

The browser at `/` starts with the original domain picker and opens a chat
workspace. The selected domain is saved with the conversation and supplies
vocabulary to the planner. Questions, clarification replies, planning decisions
and model-returned reasoning are saved as authenticated workspace events.
Follow-ups receive bounded conversation context; evaluation requests exclude it.
The task-family picker is removed from the UI; constrained family selection
still runs inside the planner.

Chat provides three modes over the same validated workflow API.
Normal runs a validated plan immediately. Interactive saves it for inspection
and explicit approval. Expert accepts an explicit JSON workflow and also
requires review before execution. Editing increments the revision and
invalidates prior approval. `/classic` retains the earlier application.

**Automatic (GPU first)** prefers a permitted GPU with current execution
evidence for the selected calculation. If no such GPU has capacity, or the
algorithm does not support the input or requested parameters on GPU, execution
falls back to a verified CPU implementation. CPU-only workflows do not reserve
a GPU. Explicit **CPU only** and **GPU only** remain strict; GPU-only work fails
when it cannot run on an admitted GPU. Each result records its actual backend
and, when supplied by the native runtime, the CPU fallback reason.

Compute device and solution quality are separate choices. Calculation settings,
plan review, chat summaries and results distinguish exact algorithms (which
establish the declared result or optimum) from heuristics (which do not guarantee
a global optimum). Where supported, **Solution quality** is a visible setting;
its declared default applies when omitted. GPU preference never changes this
parameter or substitutes another objective. Approximate, numerical, stochastic
and learned/statistical estimates retain their own labels. A complete collection
does not imply an exact solution. The current native community-detection profile
is CPU-only, with separate exact and heuristic solution-quality choices.

The **Results** tab and each answer's **View results & visualizations** link
open a separate page for graph exploration, tables and downloads. Chat remains
visible during planning and execution. Routes such as
`#workspace/{session}/chat` and `#workspace/{session}/results/{workflow}` restore
the selected conversation and result on refresh. Old `#workspace/{session}`
links still open the conversation. Reasoning appears after each model stage
returns; the UI does not fabricate a live token stream or numerical findings.
Each question has a request ID. If its HTTP reply is lost, the browser retrieves
the saved planning outcome from authenticated events without repeating model
generation. A saved plan retains its original input files and mode for recovery.
The sidebar puts model reasoning first and keeps a history grouped by question.
Understanding, operation selection, plan attempts, and validation outcomes appear
below it, including failed validation and repairs. New planning events retain the
proposed plan; older saved workflows supply their validated plan. A follow-up is
shown immediately and stays visible until its matching request ID is acknowledged.
The chat scroll follows new messages above any older plan panel.

## Library and application setup

Build the [native runtime](NATIVE_CORE_MIGRATION.md), install the thin Python
package in the analytics worker environment, and configure the application:

```sh
python -m pip install -e python/graphmine
export GRAPHMINE_NATIVE_LIBRARY=/absolute/build/libgraphmine_runtime.so
export GRAPHMINE_NATIVE_BINARY=/absolute/build/graphmine-native
export GRAPHMINE_ANALYTICS_PYTHON=/absolute/worker-environment/bin/python
```

For subsequent launches, save these settings in the ignored `agent/.env` and
start the application with `./deploy/start-agent.sh`. A branch switch does not
rebuild native artifacts or update shell variables. Without explicit paths the
agent expects `library/build/runtime/graphmine-native` and its adjacent
`libgraphmine_runtime.so`; an older `library/build/graphmine` is not a substitute.
Use a build matching this branch's native execution evidence.

Domains and saved conversations load independently of native capability
verification. Calculations become available after verification finishes; an
unavailable runtime leaves conversation navigation available and shows an
analysis status with a reconnect option.

`GRAPHMINE_NATIVE_BINARY` needs native libcudf for CSV loading. JSON graph
analysis can use a CPU-only runtime. `GRAPHMINE_NATIVE_LIBRARY` is loaded by the
worker; `GRAPHMINE_NATIVE_BINARY` handles native tabular reads and construction.
The standalone library supports C, C++ and Python consumers; the application
adds evidence admission, durable review, scheduling and cancellation.

`catalog/native_execution_evidence.json` must match the binary, implementation,
source files, linked dependencies, operation profile and, for GPU execution,
physical GPU UUID. Missing or stale evidence disables the profile. Reproduce
native tests and run `tools/build_native_execution_evidence.py` for each build;
its `--help` documents required reports. `tools/audit_native_completion.py`
generates the 70-contract inventory through that same gate. Historical reports
and failed attempts remain archived but do not establish admission.

The native planner uses `GRAPHMINE_LLM_MODEL` by default. A compatible model or
adapter can be selected with `GRAPHMINE_ANALYTICS_PLANNER_MODEL`. Native planning
uses `GRAPHMINE_ANALYTICS_REASONING_EFFORT=medium` by default. The legacy V1
planner/analyst adapter settings remain scoped to the old protocol. Family,
operation and workflow selection are separate constrained stages, followed by
the same actual-input validation used for manually edited plans. Routing may
request clarification; model accuracy is reported separately from executable
algorithm correctness. A plan is never a computed answer.

For the local vLLM server started with `--reasoning-parser qwen3`, set
`GRAPHMINE_ANALYTICS_THINKING_TOKEN_BUDGET=1536` to reserve part of the 3072-token
response allowance for the structured decision. This optional server extension
is omitted when the setting is blank; leave it blank on servers that do not
support `thinking_token_budget`. Its value must be smaller than
`GRAPHMINE_LLM_PLAN_MAX_TOKENS`. Reasoning remains enabled.

Routing decisions choose a status first. A selection requires at least one
operation; a reroute requires at least one destination family; clarification
and unsupported decisions cannot also select operations. The JSON schemas
enforce these states during generation and response validation.

Model generation assigns each argument either a literal or a reference to an
earlier result. Each reference first selects `source: input` for an uploaded
input or `source: step` for a previous result. Steps use zero-based positional
references (`step_index`) rather than model-generated names. Their schemas allow
only indices of earlier steps. Operation selection sees output-port contracts,
and generated references can name only ports from selected operations. The
server assigns stable step IDs and converts references to the public workflow
format. It rejects duplicate argument names, missing or forward references,
and invalid typed dependencies. An invalid reference enters the bounded repair
path; the server never guesses which input the model intended. Planning retains
the operation selection's explanation as fallible context and distinguishes
calculations on derived graphs from independent calculations on original inputs.
There is at most one family reroute and one plan repair. Individual model
requests have a 120-second deadline and the entire planning attempt is bounded
at 360 seconds. See the [acceptance report](NATIVE_ANALYTICS_ACCEPTANCE.md) for
the measured accuracy and timing of the local model.

## Construct a graph from tables

Choose **Build a graph from tables**, upload CSV files, and select the endpoint
columns, direction, calculation, weight column and duplicate policy. IDs remain
text by default, including leading zeros. The calculation determines the
meaning of weights: cost, capacity or strength. The advanced settings support
explicit joins, typed attributes and `[start,end)` time windows.

The authenticated endpoints are:

- `GET /api/sessions/{session}/tables/{file}/schema`
- `POST /api/sessions/{session}/projections`

The POST body maps aliases to files already uploaded in that workspace. The
server resolves paths, loads CSV with native cuDF, and runs joins, conversions,
aggregation and graph construction in C++. For example:

```json
{
  "tables": {"transfers": "uploaded-file-id", "accounts": "other-file-id"},
  "projection": {
    "version": 1,
    "id": "transfers-in-window",
    "task": "max_flow",
    "edge_table": "transfers",
    "joins": [{
      "table": "accounts", "alias": "sender", "left": "transfers.from",
      "right": "id", "kind": "required", "cardinality": "many_to_one"
    }],
    "source": {
      "field": "transfers.from", "type": "string",
      "attributes": {"branch": {"field": "sender.branch", "type": "string"}}
    },
    "target": {"field": "transfers.to", "type": "string"},
    "directed": true,
    "weight": {"field": "transfers.amount", "type": "integer", "meaning": "capacity"},
    "timestamp": {"field": "transfers.time", "type": "integer"},
    "time_window": {"start": 10, "end": 20},
    "duplicates": "sum"
  }
}
```

Joins compare exact text keys. Empty keys do not match; duplicate right-side
keys violate the many-to-one contract. Required joins reject missing matches;
inner joins discard them; left joins preserve unmatched rows. Counts and
content hashes disclose every exclusion. Duplicate keys include endpoints and
timestamp, with undirected endpoint normalization. Conflicting attributes and
inexact numeric aggregation are rejected. The saved graph includes the source
hashes and full construction settings, so it can be reused in later workflows.

## Execution, memory and outputs

CPU, GPU and Auto are explicit policies. GPU-only work never silently runs on
CPU. `GRAPHMINE_ANALYTICS_GPU_UUIDS` is a comma-separated physical UUID pool;
`GRAPHMINE_GRAPH_GPU_UUID` is also eligible. The scheduler probes actual free
memory, subtracts active reservations and headroom, and admits isolated native
worker processes. The default is two concurrent CPU workers and 512 MiB GPU
headroom. Estimates include input representations and bounded output; they are
admission estimates, not guarantees about a vendor allocator.

The LLM GPU is excluded unless `GRAPHMINE_ALLOW_SHARED_GPU` is enabled. With
sharing enabled, `GRAPHMINE_ANALYTICS_LLM_RESERVE_BYTES=0` reserves 80% of that
device's total memory; an explicit positive value overrides that reservation.
Cancellation kills the worker process group and releases its lease. Workflow
records save device UUID, admission estimates, hashes, parameters and results.

Native graph and normalized weighted representations use a bounded,
process-local cache keyed by input content, semantics, implementation and
representation version. Warm access does not bypass resource accounting.
Dependent-step reuse additionally checks the plan, inputs and admitted backend
set. Independent worker processes do not share mutable graph objects.

The browser uses Cytoscape and fixed JavaScript renderers with no Node runtime
and no generated chart code. Graph previews disclose their bounds; execution
uses the full uploaded input. Results retain original typed IDs and exact
rational values. Pagination and export access saved full results. Incomplete
collections are labeled and cannot feed steps requiring a complete collection;
complete counts may coexist with an incomplete or unrequested enumeration.

Community results open with all groups visible, stable group colors, and a layout
that separates communities. The group selector, legend, and group rows filter the
preview to that group's vertices and internal connections; **All groups** or
**Clear selection** restores the overview. Preview limits remain explicit. Group
membership comes from the saved partition, including the original typed IDs.
The result names its solver: this branch's native local-vertex-move heuristic
can produce a different partition from the classic GPU Leiden backend, even on
the same graph at the same resolution. Display filtering does not recompute or
change the returned communities.

## Reviewed examples

After a complete successful workflow, **Review as a reusable example** opens an
explicit review form. A successful run alone never approves an example. The
server checks the current workflow revision, plan hash and result hash before
storing the review. Examples are scoped to the workspace, native implementation,
input kinds and selected operations; their provenance is included in planning.
They supply hints, not executable instructions or correctness evidence.

Evaluation workflows carry an immutable `evaluation_id`. They cannot be saved
as reviewed examples, and evaluation planning retrieves no reviewed examples.
The API supports listing and revoking approvals. Development probes, held-out
model scores and independent native oracle reports have separate labels.

## MCP

Run the stdio bridge in the agent environment:

```sh
export GRAPHMINE_API_URL=http://127.0.0.1:8000
export GRAPHMINE_API_TOKEN=your-configured-token
python -m graphmine_agent.mcp
```

The bridge uses [MCP 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)
JSON-RPC initialization, tool discovery and newline-delimited stdio messages.
Its 14 tools inspect capabilities, create workspaces, list files, inspect tables,
construct graphs, plan questions, create/list/get/revise/approve/cancel workflows,
and retrieve full results or result pages. Upload files through the HTTP API or
browser first. The bridge calls the same authenticated HTTP endpoints and
approval checks; it contains no alternative algorithm or arbitrary-code path.
Messages are bounded at 16 MiB; larger outputs use `result_page`.

## Reproduce the scale checks

```sh
python tools/fetch_native_scale_datasets.py --output /tmp/graphmine-scale-datasets
python tools/validate_native_scale.py --datasets /tmp/graphmine-scale-datasets \
  --cpu-build /absolute/cpu-build --gpu-build /absolute/gpu-build \
  --output /tmp/graphmine-native-scale-results
python tools/validate_analytics_scale.py \
  --native-results /tmp/graphmine-native-scale-results \
  --library /absolute/gpu-build/libgraphmine_runtime.so \
  --gpus GPU-uuid-0,GPU-uuid-1 --output /tmp/api-scale.json
```

The research environment needs SciPy/NetworkX for independent oracles, pytest
for regression checks, and `zstd` for the pinned public archives. Those Python
packages are not runtime algorithm dependencies. The datasets include official
[Graphalytics references](https://ldbcouncil.org/benchmarks/graphalytics/datasets/),
[SNAP ca-CondMat](https://snap.stanford.edu/data/ca-CondMat.html), and a seeded
100,000-vertex, 500,000-edge graph. BFS, SSSP and WCC match published references;
PageRank uses a convergence oracle rather than Graphalytics' fixed iterations.
The test-WCC archive's `.v` edge-file property is inconsistent with its actual
`.e` file; the loader explicitly reads the edge file. These are correctness and
latency measurements, not a certified LDBC benchmark submission. RSS is a Linux
high-water measurement; sampled GPU usage is not an exact allocator peak.
