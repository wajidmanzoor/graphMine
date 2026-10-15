# Native analysis workspace

The browser at `/` shows saved conversations first, followed by the domain
picker for a new chat. The selected domain is saved with the conversation and supplies
vocabulary to the planner. Questions, clarification replies, planning decisions
and model-returned reasoning are saved as authenticated workspace events.
Follow-ups receive bounded conversation context; evaluation requests exclude it.
The task-family picker is removed from the UI; the planner's routing call sees
operations grouped by family.

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
links still open the conversation. Reasoning streams in while each model stage
runs and the full text is kept when it finishes; the UI never fabricates numerical findings.
Each question has a request ID. If its HTTP reply is lost, the browser retrieves
the saved planning outcome from authenticated events without repeating model
generation. A saved plan retains its original input files and mode for recovery.
The sidebar shows one timeline per question: its stages, then a collapsible copy of the model's reasoning for that question.
Understanding, operation selection, plan attempts, and validation outcomes appear
below it, including failed validation and repairs. New planning events retain the
proposed plan; older saved workflows supply their validated plan. A follow-up is
shown immediately and stays visible until its matching request ID is acknowledged.
The chat scroll follows new messages above any older plan panel.

## Answers, follow-ups and results

When a calculation finishes, the chat answers with facts computed from the
result: what was found, the main entities, and whether the method is exact or a
heuristic and whether the output is complete. A model may choose and order these
facts and add one lead sentence, but it cannot write numbers; if it is
unavailable, the facts are shown on their own.

Follow-up questions see a short summary of the previous result. On the results
page, choosing a group or clique and returning to chat attaches it to the next
question ("Asking about Clique 2"); the server reads its members from the saved
result. When the planner needs more information it offers short replies to
click. Interrupted or failed planning shows **Try again**, which resends the
question with its original inputs.

Failed, interrupted, cancelled and incomplete analyses offer **Adjust parameters**
and **Narrow input** in the plan panel. Parameter changes retain bound inputs;
narrowing replaces one graph input with a smaller uploaded graph while keeping
the other aliases. Both paths validate and save a new revision in Interactive
mode, so the user reviews the changed plan before execution. When no smaller
graph is available, the narrowing dialog offers an upload. Known vertex and
edge counts exclude replacements that are larger in either dimension.

Conversation management and saved analyses are collapsed in the data sidebar.
On phones, **Data & chats** opens the sidebar from the conversation header;
the composer stays ahead of data controls and activity in page order.

Before an expensive run (an exact search on more than 5,000 connections, or one
similar to past runs that took over two minutes), even Normal mode shows the
steps, guarantees, input size and memory estimate and waits for approval. Queued
and running work shows elapsed time and place in line.

A selected group is drawn from the full input graph rather than the bounded
preview. Score outputs size nodes by score, and selecting a path highlights its
own connections. Outputs longer than 2,000 rows arrive cut down for charts; the
table then searches and pages through all rows on the server, and **Download
full result** always downloads everything. Conversations can be renamed,
archived, searched and deleted, and uploaded files removed.

Group outputs show counts, distinct members, size ranges and shared-member
counts. Server summaries cover the whole retained group collection, including
when its rows are paged. Minimum/maximum size and **Contains member ID** filter
the result table across the retained output; `42` and `"42"` select different
typed IDs. Filtered rows retain their original positions, so selecting a clique
loads the correct full-input graph and attaches the correct selection to chat.
These filters change the view, not the calculation or its completeness.

**Highlight shared members** marks visible vertices appearing in more than one
group in the full retained output. For paged results, a bounded lookup checks
the displayed IDs against all saved groups, preserving integer and string IDs.
Failed lookups turn highlighting off and show an error. For maximum-flow
results, **Show computed flow direction** draws positive flow assignments with
arrows, including for undirected input edges. Turning it off restores the input
connections; clicking an arrow reveals its recorded flow and capacity, including
exact fractions where provided by the engine.

### Pending-items audit — 2026-10-15

- Combined routing and first-stage explain/view/calculate actions are deployed.
  Four synthetic live-model checks passed: calculation, display, explanation and
  clarification. This is a smoke check, not a general model-accuracy evaluation.
- Recovery controls and sidebar/home navigation are implemented as described
  above. Group filters, summaries, flow arrows and overlap highlighting are in
  the result view; overlap checks now cover the full retained collection.
- vLLM was restarted under systemd with `--max-num-seqs 2`; two simultaneous
  model requests passed after restart.
- Both user services are installed, enabled and running. Lingering is enabled
  for startup at boot without an active login. See [deployment](../deploy/README.md).
- Evidence-hash caching is integrated at the application worker boundary.
  Native sources and their evidence remain unchanged. Every worker still
  verifies admission; changed file identities force rehashing. Actual native
  checks reject a modified source even when its size and modification time are
  preserved. A local cold/warm check measured 4.2 versus 1.5 seconds with the
  same admitted operations.
- Planner-adapter retraining still requires reviewed examples: the production
  store contains zero. Synthetic deployment probes are excluded from review and
  training. This was the P1 deployment checkpoint; the P2 implementation is
  described below, followed by the P3 collaboration and connector implementation.

Validation for this batch: all 37 Firefox tests in the loading, conversation/graph
and recovery/view suites passed. The backend run passed 129 tests and skipped
two GPU checks that require explicit device UUIDs. Its only failure was an
existing restart-test fixture referencing a session it had never created;
using the saved-session fixture made that check pass on the focused rerun
(130 backend checks passed in total). Changed-file Python lint/format checks,
JavaScript syntax and source diff checks passed. The application has since been
deployed from a versioned snapshot, preserving the production data directory;
a verified backup and private rollback configuration were retained.

The deployment follow-up adds worker cache invalidation, bounded membership
lookup, ownership/quota checks and launchers that honor an explicit production
environment file. The API and model use separate environments so model-specific
CUDA compatibility libraries cannot change native admission. Explicit worker
interpreter paths retain their virtual environment instead of resolving to the
system interpreter. Across the follow-up runs, 94 distinct backend/launcher
checks and 39 Firefox checks passed; two GPU workflow checks were skipped because
device UUIDs were not configured for that test run. Validation artifacts and
their scope are recorded with the local release.

### P2 release gate — 2026-10-15

The ten P2 roadmap areas are implemented: reusable datasets and provenance,
parameterized workflow templates and comparison, operation/resource guidance,
suggested follow-ups, visual workflows and exploration, exports/reports, CPU CSV
imports and dataset versions, administrator activity, local release checks, and
shared UI controls with classic-interface deprecation. The sections below
describe their supported scope and limits.

The complete local release gate passed 255 backend and 64 Firefox checks. Four
explicit GPU checks were skipped in this CPU gate. All workspace JavaScript
syntax checks passed, both Python wheels built, and a fresh environment passed
native CPU workflows, dataset reuse, template approval and report-hash checks.
The bounded load check sent 64 reads with eight concurrent clients and verified
authentication, admission limits and unchanged question/job allowances. Source
fingerprints remained unchanged throughout the gate. A separate migration
rehearsal upgraded a copy of the production database from schema 1 to 2 while
preserving all existing table counts.

Deployed as `p2-20261015T092509Z` with a verified pre-migration backup. HTTPS,
served asset hashes, authentication and SQLite integrity checks passed; existing
production record counts were preserved. Both services are enabled and active,
with the model process unchanged. The deployed application and environment also
passed an isolated native CPU calculation and admitted all 82 operations. Schema
2 rollback requires compatible code or the pre-upgrade backup.

### P3 release gate — 2026-10-15

Both P3 roadmap areas are implemented and deployed within the scope documented
below: project workspaces, member roles, annotations, saved views and revocable
read-only links; and SQLite/REST imports into immutable dataset versions.

The final release gate passed 273 backend and 66 Firefox checks. Four explicit
GPU checks were skipped in this CPU gate. All application JavaScript syntax
checks passed, both wheels built, and a fresh installation passed native CPU
workflows, dataset/template/report checks, project-link revocation and SQLite
imports. The bounded HTTP check used 64 requests and eight concurrent clients.
The gate recorded unchanged fingerprints for 223 source and test files. A
separate rehearsal upgraded a copy of the production database from schema 2 to
3 and preserved existing table counts.

Deployed as `p3-20261015T103529Z` after a verified pre-upgrade backup. HTTPS,
served asset fingerprints, protected project/connector routes, invalid public
links and SQLite integrity checks passed; existing production record counts
were preserved. Both services remain enabled and active, with lingering enabled
and the model process unchanged. The deployed application and service
environment passed an isolated native CPU calculation and admitted all 82
operations. Wheels, test reports, screenshots, migration evidence and deployment
checks are retained under the release's `validation/p3` directory. Schema 3
rollback requires compatible code or the verified pre-upgrade backup.

This was the P3 deployment checkpoint. The subsequent completion work adds
self-service connections and prepares the existing successful workflows for
explicit review; see below. Synthetic checks do not qualify as reviewed examples.

### Review completion — 2026-10-15

The four application GPU checks previously skipped by the CPU gate passed on
both physical RTX 6000 Ada GPUs: native workflows and GPU table projection on
each device. Tests used temporary stores and did not restart the model service.

**Data connections → Add connection** now supports uploaded SQLite databases,
Node.js/REST exports and Neo4j relationship exports. Users can edit mappings,
preview a source, save dataset versions and remove their own connections.
Credentials remain private, and uploaded databases count against account storage.
Schema 4 adds these records; a migration rehearsal preserved all 22 existing
production table counts. The focused checks passed 80 backend tests and five
Firefox workflows, including SQLite, REST and Neo4j setup.

The complete release gate subsequently passed **279 backend tests and 69 Firefox
tests**. The four GPU exclusions in the CPU gate are covered by the separate
successful GPU run described above. JavaScript checks, both wheel builds, a
fresh installation and bounded concurrent HTTP checks passed. The built agent
wheel includes the new connection setup assets. An earlier interrupted run had
one process-deadline test failure; its focused rerun and the complete final run
passed. That interrupted attempt is not counted as a successful gate.

At the user's request, saved workflows were prepared for review rather than
automatically approved: nine candidates from twelve completed runs, with three
excluded because no original question was recorded. The private HTML/JSON packet
includes questions, earlier context, exact plans, inputs/results and revision
hashes. Zero examples are approved and no training has started. Review the
candidates in the existing authenticated workflow review form before preparing
a source-separated training and evaluation dataset. The legacy routing-adapter
trainer is not a direct export path for the current native planner protocol.

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

Ordinary relationship CSVs and whitespace edge lists load on CPU. Imports keep
canonical integer IDs, text IDs such as `001`, attributes, parallel edges and
self connections. The preview checks the full file and shows a bounded sample
before the user confirms the import. Limits are 100,000 rows, 2,000,000 cells,
64 columns and the configured upload byte allowance; exceeding a limit rejects
the import rather than silently truncating it. `GRAPHMINE_NATIVE_LIBRARY` is
loaded by the worker; `GRAPHMINE_NATIVE_BINARY` handles native construction.
The standalone library supports C, C++ and Python consumers; the application
adds evidence admission, durable review, scheduling and cancellation.

## Reusable datasets and workflow templates

Ordinary UTF-8 relationship CSVs and whitespace edge lists load on CPU. Before
saving a CSV, the import dialog checks the whole file and previews the endpoint
columns, direction, row count and sample records. It preserves text identifiers
such as `001` and exact integer IDs. Malformed rows, ambiguous quotes, conflicting
vertex attributes and nonfinite weights fail the import without leaving a
partial file. The CPU reader permits at most 100,000 rows, 64 columns and
2,000,000 cells, within the configured upload/input byte limits.

The table-construction dialog also reads CSVs on CPU and passes bounded inline
tables to native graph construction. Joins, conversions and duplicate aggregation
retain the native projection contract. API callers can request `device: "gpu"`
to use the cuDF path; this requires an available configured GPU. Imported and
projected graphs record their source hashes and construction settings.

**Dataset library** stores private, immutable snapshots that survive deletion of
their original conversation. **Save this input for reuse** saves the complete
canonical input. From a result, **Save graph for reuse** saves either a computed
graph or the full induced graph for the selected group, including vertices
outside the preview. A group derived from an earlier computed graph uses that
computed graph's connections. Original integer and text IDs remain distinct.

Save a new dataset or another version of an existing one. Deleting a version
does not reuse its version number. Each version retains a content hash, source
file or workflow revision, plan and source completeness. Importing a version
creates a separate file in the current conversation, so later source edits or
deletion do not change an analysis. Dataset versions and templates count toward
the account's storage allowance and are removed explicitly through the library;
conversation retention does not remove them.
Backup verification also checks each saved dataset's content against its size
and hash before accepting a snapshot for restore.

**Save as template** captures the validated steps and settings without approval
or execution state. **Workflow templates** lets the user bind inputs from the
current conversation and change literal parameters. Parameters bound to earlier
steps remain bound. Every use creates a new validated workflow in Interactive
mode, requiring approval before execution. Templates are private and survive
source-conversation deletion.

**Compare saved runs** accepts two to six runs across the user's conversations.
It displays algorithms, parameters, recorded backends, run time, exact scalar
values, completeness and findings. Input fingerprints are compared explicitly;
different or unknown fingerprints are called out rather than presenting the
runs as equivalent experiments.

## Exploration and exports

Advanced calculation controls show the verified operation's input description,
quality, available devices, GPU restrictions and parameter bounds. Server byte
and runtime limits are shown alongside the plan's memory estimate and step
budgets. Completed answers offer follow-up prompts based on their actual output
types and completeness, without another model call to generate suggestions.

Expert mode includes a visual workflow editor with dependency arrows, typed
input choices, step parameters and add/remove controls. Existing selectors and
parameter bindings remain intact; the JSON editor handles advanced binding edits.
Saving from the visual editor always validates and waits for review.

Graphs with timestamps offer inclusive start/end sliders and a choice to include
untimed connections. These controls affect the displayed preview, leaving saved
data and calculations unchanged. Embedding outputs plot chosen original vector
dimensions with clickable, keyboard-accessible points. The plot shows at most
1,000 loaded embeddings and labels its scope; it does not claim that projected
distances equal distances in the full embedding.

Exports include the visible graph as PNG, full retained output tables as CSV,
and a reproducible report ZIP, under **Save, compare & export**. Reports contain an offline HTML summary, full
tables, exact JSON inputs/results, the plan, a replay request and SHA-256 hashes.
CSV text that could be interpreted as a spreadsheet formula is escaped; JSON
retains original types and values. Replaying requires a compatible installation
with matching native evidence and environment. Randomized calculations can vary.

Administrators can page through successful account and allowance changes in
**Settings → Manage users → Administrator activity**. Audit entries commit in
the same transaction as the change and contain no passwords or login tokens.

New feature controls live in separate library, import, template, export, editor
and exploration scripts. Parameter controls are shared by the main workspace,
template dialog and visual editor. `/classic` is deprecated and remains
available for existing conversations and results.

## Project collaboration

**Project workspaces** opens `/projects.html`. Owners add existing accounts as
Editors or Viewers; only owners manage members, delete projects/shared snapshots,
or create and revoke public links. Editors publish their own inputs/results,
annotate snapshots and save graph views. Viewers read shared material and can
copy shared inputs into their own conversations. Editors remove their own notes;
owners can moderate all notes. Removing membership removes subsequent access.

**Share input to project** copies an owned input. **Share result to project**
copies the selected revision's result, exact input snapshots and plan. The dialog
states this scope. Conversation messages and private conversation permissions
remain unchanged. Shared copies survive deletion of their original source.
Snapshot and note storage counts against the project owner; imported copies
count against the importing account. An owner can create 50 projects, and each
shared snapshot is limited to 32 MiB.

The viewer displays up to 500 vertices and 2,000 connections, with the full
snapshot available as JSON. Saved views retain graph layout, visible positions
and typed selections. Read-only links grant access to the complete snapshot,
including a shared result's inputs and plan, but exclude project discussion and
membership. Links expire within 1–30 days and can be revoked; disabling the owner
also invalidates public links. The server stores link hashes and the viewer sends
the URL-fragment secret in a POST body. Public reads have bounded admission
through response completion and use no-store/no-referrer behavior.

## Database and REST connections

**Data connections** lists sources available to the signed-in account.
**Add connection** offers three types:

- **SQLite database:** upload a consistent `.sqlite3`, `.sqlite` or `.db` backup,
  then choose a regular table and its source/target columns. The uploaded copy
  is private and does not synchronize later changes to the original database.
- **Node.js / REST API:** provide an HTTP(S) export URL, optional bearer token,
  response format (graph JSON, scalar JSON records or CSV), and column mapping.
  Object-wrapped JSON arrays can name their top-level field.
- **Neo4j:** provide the HTTP(S) server address, database, username/password and
  optional source-label/relationship-type filters. The fixed parameterized read
  uses the [Neo4j Query API](https://neo4j.com/docs/query-api/current/query/).
  It imports matching relationships and their endpoints, excluding isolated
  nodes. Arbitrary Cypher and Bolt connections are not exposed by this driver.

Connections belong to their creating account. **Edit connection** changes the
mapping or credentials; blank credential fields retain existing credentials for
the same server. **Remove connection** preserves previously imported versions.
Credentials are omitted from API responses and dataset provenance. Private
backups contain saved connection credentials and SQLite uploads. Up to 50 saved
connections are allowed per account; their bytes count against storage.

Public HTTPS endpoints are supported directly. Private-network servers and HTTP
origins require the operator's `GRAPHMINE_CONNECTOR_ALLOWED_ORIGINS` setting.
Every network read resolves and checks the endpoint, pins its address while
preserving TLS verification, and follows no redirects. Operator-managed sources
in `GRAPHMINE_CONNECTORS_FILE` remain supported. SQLite/JSON endpoint IDs retain
integer/string types; CSV follows the existing canonical-integer policy.

Preview validates the source and shows counts and samples. Saving reads again,
checks the preview fingerprint, rechecks authorization, and creates an immutable
dataset version. Changed sources require another preview. Use the saved version
in the current conversation or import it later through the Dataset library.
These actions do not run calculations or consume question/job allowances.

CPU row/cell/byte limits apply. SQLite imports include the whole table or fail.
REST records its scope as one response and marks source completeness conservatively
unless configured as a complete export. Responses advertising another page or
incomplete output are rejected, as are redirects and compressed bodies. REST
requests ask for uncompressed data and enforce time/byte limits. See
[server configuration](../deploy/README.md#data-connections).

Schema 4 adds private connections and their storage accounting. Older code
refuses it; rollback requires compatible code or a verified pre-migration backup.

Run the local release gate from the repository with:

```sh
PYTHONPATH=agent .venv/bin/python tools/check_local_release.py --output /tmp/graphmine-release-check
```

It requires a new output directory, uv, Firefox/geckodriver, Node for syntax
checking, and already verified native artifacts. It runs backend and browser
checks, builds both wheels, installs them in a clean Python environment and
checks CPU workflows and bounded concurrent HTTP traffic using a temporary
account/store. Reports state their scope; native compilation and live-model
accuracy remain separate checks.

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
planner/analyst adapter settings remain scoped to the old protocol. One
routing call chooses the operations, and a separate constrained stage builds the
workflow, followed by the same actual-input validation used for manually edited
plans. Routing can also return a display change or an answer from the saved
result's facts; neither computes anything. Routing may
request clarification; model accuracy is reported separately from executable
algorithm correctness. A plan is never a computed answer.

For the local vLLM server started with `--reasoning-parser qwen3`, set
`GRAPHMINE_ANALYTICS_THINKING_TOKEN_BUDGET=1536` to reserve part of the 3072-token
response allowance for the structured decision. This optional server extension
is omitted when the setting is blank; leave it blank on servers that do not
support `thinking_token_budget`. Its value must be smaller than
`GRAPHMINE_LLM_PLAN_MAX_TOKENS`. Reasoning remains enabled.

Routing decisions choose an intent first. A calculation requires at least one
operation from the catalog; clarification and unsupported decisions cannot also
select operations; display changes and fact answers can only name what the
saved result contains. The JSON schemas enforce these states during generation
and response validation. The catalog sits at the end of the fixed instructions,
so the model server can reuse its cached prefix between questions.

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
There is at most one plan repair. Individual model
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
