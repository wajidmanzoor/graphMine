# Native analysis workspace

The [database and Cypher workspace](DATABASE_CYPHER_WORKSPACE.md) adds local
PostgreSQL → Neo4j → chat analysis, result-specific graph views, and SQL attribute
and relationship lookups from those results.

The browser at `/` keeps searchable conversation history in a collapsible left
sidebar, with data and domain starting points on home. **Explore all domains** reveals
the remaining starting points. The selected domain is saved with the conversation and supplies
vocabulary to the planner. Questions, clarification replies, planning decisions
and model-returned reasoning are saved as authenticated workspace events.
Follow-ups receive bounded conversation context; evaluation requests exclude it.
The task-family picker is removed from the UI. The first model call's catalog
context is only `catalog/family.json`: the 14 family titles, descriptions and
deciding questions. The second receives only the chosen family's entries from
`catalog/problems.json`, and selects up to two ranked problem candidates.
Both receive the question and, for follow-ups, at most four conversation
messages capped at 1,000 characters each. Plans, input samples and result
records enter only later planning stages.
These are alternatives, not a request to execute both. The existing operation,
implementation and parameter planning then uses their operation contracts.
When the question explicitly needs steps across families, those dependencies
are available in the later operation stage. One family reroute is allowed;
a second failure asks for clarification. Confirmed choices and saved UI actions
retain their existing direct paths. [Families and problems](https://wajidmanzoor.github.io/graphMine/problem/taxonomy/) is
generated from the same catalogs.

Calculation choices contain one or two supported alternatives. The second needs
actual sampling support and a Medium or High match; a zero-vote runner-up is
kept in diagnostic evidence but is not displayed. A single supported calculation
still waits for the person's choice. Related calculations with different
objectives are not added just to fill a second card.

Choice identity includes the input, operations and effective parameter values.
The native catalog's fixed guarantee takes precedence over a weaker requested
quality: the current exact densest-subgraph contract accepts approximate requests
but still uses its exact solver. Those requests form one choice. Contracts with
real parameter-dependent methods, such as exact/heuristic community detection,
retain separate choices. Badges use server-supplied guarantees and update after
quality edits; historical duplicate cards collapse for display while their saved
requests and event records remain unchanged. Option policy version 2 invalidates
the earlier calibration; High labels require a matching recalibration.

Home does not display recent-analysis or recent-dataset cards. Saved conversations
remain accessible from the sidebar, with saved analyses and the dataset library
available inside a conversation. Home does not request recent-work summaries.

The API retains `GET /api/workspace/recent/{datasets|queries|analyses}`
(default `limit=4`, maximum 12, bounded `offset`) and
`POST /api/datasets/{version_id}/conversation` with `{"domain_id":"general"}`.
Both use the existing authentication and owner checks; dataset copying also uses
the existing integrity checks, upload admission and storage accounting.

The workspace keeps Kashmiri flag green and yellow as its brand colors: green
for primary actions and focus indicators, with yellow highlights for navigation,
the selected mode and conversation accents.

Workspace text uses a relative type scale: at the default browser size, body
text is 16 pixels and supporting labels are at least 14 pixels. Common controls
have a minimum height of 40 pixels on desktop and 44 pixels on small screens or
touch devices. Inputs on small screens use 16-pixel text. Secondary labels and
input outlines have stronger contrast; keyboard focus has a visible outline.
Mobile drawers isolate the background until they close, then return focus to
their trigger. Location-chart points support Enter and Space and retain focus
when selection updates the result.
Account settings use the same type scale; on small screens, the header keeps
the username and settings icon with a complete accessible button label.

Page zoom uses the responsive layouts. When the viewport is 560 CSS pixels tall
or less, chat and Data use document scrolling so their editors, previews and
actions remain reachable. Reduced-motion preferences disable smooth scrolling
and transitions; forced colors retain borders for controls and selected states.
The command menu fits below the toolbar and becomes part of the document flow
on short viewports; selecting a command brings the composer back into view.
The browser checks cover desktop and 320-pixel views, real 200% and 400% Firefox
zoom, keyboard navigation, and rendered text contrast. Contrast checks use the
[WCAG text contrast thresholds](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html);
the short 320-pixel viewport checks follow the
[reflow guidance](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html).

The message composer provides two modes over the same validated workflow API.
Normal asks for required information, offers up to two calculation cards, and runs
the selected, validated plan. Expert saves plans for inspection, editing, and
explicit approval, including structured JSON workflows with validator errors
shown directly. Editing increments the revision and
invalidates prior approval. `/classic` retains the earlier application.

A routed clarification stays pending even when the router suggests an operation:
if that operation has no missing input, the application still asks which objective
the person intended before sampling calculation options. For shortest paths,
an explicit request between selected endpoints must supply those endpoints;
the nullable native default means all vertices, not unknown accounts. Named
endpoints are resolved against the snapshot, and missing endpoints are asked
one at a time. Explicit all-pairs requests keep the native defaults.

Data and conceptual answers include `text` and `citations`, whose entries contain
`id`, `kind` (`fact`, `contract`, `doc`, or `web`) and `ref`. The **Sources** step in Activity
shows the evidence behind each answer. Inline documentation citations open that step. Tool results are registered for the
current turn; saved results are read again and identified by workflow revision.
The checker compares complete factual sentences with the cited evidence. This
conservative check rejects unsupported paraphrases as well as changed names,
counts, units, negation and invented explanations. Data writers select source
placeholders; code inserts actual values and vertex identifiers. A failed draft
gets one repair attempt, then code displays the bare facts. A service outage
falls back immediately. Scalar results and input descriptions need no writer.
Dataset Studio retains the original schema for historical `lead`/`fact_ids`
captures. New answer reviews use `text`/`source_ids` with their recorded sources
and the same grounding checker; offline review does not claim fresh retrieval.

Web search is disabled by default (`GRAPHMINE_GOOGLE_SEARCH_ENABLED=false`).
Explicit search requests report that web search is disabled, with no outbound
request, browser launch, or search link. Graph answers and local documentation
replies remain available. The implementation is retained for later development;
see [Deferred Google search](DEFERRED_GOOGLE_SEARCH.md).

When explicitly enabled for development, Google/web searches and requests for current general information can
use public Google search in the `reply` lane without an API key. The tool sends
only the question, not the graph or conversation history. It first reads public
results; the optional `web` Python extra, Firefox and geckodriver allow pages
requiring JavaScript to be rendered. Search excerpts are limited to 25 words per
destination and labelled as excerpts; destination pages are not fetched. A bot
check, including HTTP 403/429 challenges, is never retried through a browser.
When Google blocks the server or returns no usable
results, the answer records that status and offers **Open this search in Google**.
Data answers cannot cite web sources. Live search availability depends on Google
accepting requests from the deployment network.

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
The [saved-view contract](VISUALIZATION_VIEWS.md) defines the result-first views,
shared selection, named explorations, exports, display budgets and optional map
and projection configuration.
Each question has a request ID. If its HTTP reply is lost, the browser retrieves
the saved planning outcome from authenticated events without repeating model
generation. A saved plan retains its original input files and mode for recovery.
Chat shows the answer followed by one footer with the recorded guarantee, device,
validation status, a result link when available, and **Details**. Sources,
explanations, and calculation traces live in **Activity**. Details opens and
highlights the matching question; documentation citations open its Sources step.
Only the latest assistant message shows suggested next questions.

Activity has one question block and one stable, initially collapsed row per step.
Model reasoning provided by the API renders as Markdown with model and latency
metadata. Retries stay within the same step. Calculation details include final
parameters, the immutable input snapshot and its source query, device selection,
runtime, validation, guarantees, and result counts. Grounding shows the evidence
supporting the answer; internal IDs have copy buttons. Finished turns cannot leave
planning steps spinning. A follow-up stays visible until its matching request ID
is acknowledged. Existing API authorization still controls access to events.
The chat scroll follows new messages while you are near the latest answer, and
keeps your reading position while you inspect earlier messages. **Show new
messages** returns to the latest answer. Conversations initially load the most
recent 30 message/analysis entries and their complete associated turns. **Load
older messages** retrieves earlier pages without renumbering questions or
resetting expanded details. Completed reasoning replaces its redundant display
chunks; the original events remain in the source ledger. Unchanged message and
Activity nodes retain focus. A graph refresh reuses its existing instance when
the displayed connections and source/result scope match, preserving dragged
positions, pan and zoom; changed attributes and colors still update.

`GET /api/sessions/{id}/workspace?history_limit=30` and
`GET /api/sessions/{id}/conversation-page?limit=30&before={cursor}` return indexed
history with an opaque older-page cursor and stable question numbers. Each page
may include the other half of a boundary turn. The workspace's `event_cursor`
starts forward polling; loading an older page does not advance it. The browser
polls `events?after={sequence}&limit=500&paged=true` and drains a backlog in bounded
batches. Legacy unpaged endpoints remain available. Saved-analysis discovery
uses `workflows?summary=true`; full fingerprints and input provenance load when
an analysis is opened. The lightweight analysis selector still lists the full
catalog; old manual analysis cards follow conversation paging. Classic archive
files are indexed on first access and incrementally when the archive directory
changes. These indexes are private and included in backups. Schema 11 backfills
public entries and question numbers from retained evidence without changing it.

Exploration settings save per conversation: the active input, selected result
step/port/item and context mode, layout, viewport and visible node positions,
selection, table/group/time filters, fetched source overlays, labels and colors.
Reopening an older analysis can retain a newer active chat input; the analysis
keeps its original input and computed values. Resizing the graph does not refit
the viewport; **Fit graph** remains an explicit action.

Settings retain at most 32 recent views within 512 KiB, including positions for
up to 500 visible nodes and selections for 2,000 visible edges. They are private,
quota-accounted, included in backups and deleted with the conversation.
Unavailable files and changed workflow revisions are omitted during recovery.
Saved attributes are read from integrity-checked graph versions without a live
SQL lookup. Older enrichments without fetched IDs use recorded mapping lineage.

Failed saves keep a recovery journal scoped to the server, account and
conversation in this browser, when browser storage is available. The status
offers retry; simultaneous edits in another tab require **Reload saved view**
or **Keep this view**. A storage failure leaves server saving available; if both
are unavailable, keep the tab open until saving succeeds. The browser does not
silently replace a newer server version with an older local journal.

## Answers, follow-ups and results

When a calculation finishes, the chat answers with facts computed from the
result: what was found, the main entities, and whether the method is exact or a
heuristic and whether the output is complete. Each fact is labelled with its
calculation's title. One grouping returned both as a partition and as group
lists is stated once, and vertices that score zero are summarised rather than
listed among the highest scores. The facts appear as soon as the result is
saved. A model may then choose and order them and add one lead sentence, shown
as **Writing a summary…** until it arrives. The lead cannot state numbers in
digits or words; if it does, or the model is unavailable, the facts stand alone.
Each step's exact or heuristic quality is shown beside the answer, so the
default fact list leads with findings.

While a question is being planned, the chat shows its stages (understanding
the question, building a plan, checking it against the data), the elapsed
time and **Stop**. Stopping cancels the model request; nothing was calculated,
and the question offers **Try again**
(`POST /api/sessions/{id}/analytics/plan/{request_id}/cancel`). The first
question of an unnamed conversation becomes its title; conversation history
(`GET /api/sessions?hide_empty=true`) omits unnamed conversations that have no
messages, files or events yet.

Follow-up questions see a short summary of the previous result. On the results
page, choosing a group or clique and returning to chat attaches it to the next
question ("Asking about Clique 2"); the server reads its members from the saved
result. Viewing a whole output attaches nothing, because the follow-up already
refers to that analysis. When the planner needs more information it offers
short replies to click. Interrupted or failed planning shows **Try again**,
which resends the question with its original inputs.

Failed, interrupted, cancelled and incomplete analyses offer **Adjust parameters**
and **Narrow input** in the plan panel. Parameter changes retain bound inputs;
narrowing replaces one graph input with a smaller uploaded graph while keeping
the other aliases. Both paths validate and save a new revision in Expert
mode, so the user reviews the changed plan before execution. When no smaller
graph is available, the narrowing dialog offers an upload. Known vertex and
edge counts exclude replacements that are larger in either dimension.

**Data** in the conversation header, or **+** in the composer, opens the dedicated
data workspace. Wide screens show connection/schema, query and preview panes;
smaller screens have Connection → Query → Preview steps. **Upload file** also
contains the dataset library and existing input controls. Routes such as
`#data/query` and `#workspace/{session}/data/files` reopen the correct workspace;
the Back control returns to the originating conversation or result. Changing
steps preserves the draft and preview without running another query.

The header keeps Chat, Data, and Results tabs with status and Activity on the right.
The domain subtitle opens the domain picker. Each sidebar conversation has a
Rename / Archive / Delete menu. Data contains upload settings, a single input-kind
control, nested derived inputs, dataset and project actions, and saved analyses.
The composer gear holds per-conversation compute settings. The `/` palette opens
workflow templates and advanced calculations, searchable by title or operation ID
with guarantee badges. New conversations offer sample data and editable question
suggestions. Activity closes with Escape and restores focus to its trigger.
On phones, the sidebar button opens conversation history while the composer
stays at the bottom of the chat viewport. Desktop sidebar visibility is saved
in the browser; Ctrl/Cmd+K focuses conversation search.

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

The library displays 20 lightweight versions per page and searches all retained
versions on the server. **Source and provenance** fetches lineage only when
expanded and offers its own retry. The **Save as** picker searches and pages the
latest retained version of each compatible collection; older collections remain
available even when they are outside the library's current page. The home page
uses the same summary index. Search, pagination and provenance reads discard
responses superseded by a newer search or a closed dialog.

`GET /api/datasets/page` accepts `offset`, `limit` (1–100, default 20), `q`,
`kind` and `latest`. It returns `items`, `offset`, `limit` and `has_more`, without
the source document or content. `GET /api/datasets/{version}/provenance` returns
the owned version's hash, source and completeness. The original `GET /api/datasets`
list remains available for older clients; the current UI uses the paged route.
Schema 10 backfills the summary index and keeps it synchronized transactionally
when versions are saved, promoted or deleted.

Workflow summaries, output pages, group selection and membership counts use
rebuildable SQLite indexes beside their saved JSON artifacts. The first indexed
read parses the bounded source once. Later reads decode only selected rows;
exact field filters, typed group membership and stable sort ranks have indexes.
Integer and text IDs stay distinct, integers beyond 64 bits remain exact, and
missing values sort last in either direction. Case-insensitive substring search
scans normalized text in SQLite. Deep offsets still traverse earlier index
entries; graph rendering may still read its full source artifact.

Every indexed read checks ownership and revision before accessing the cache,
and rejects a source changed during the read. Missing or stale indexes rebuild
atomically from the original artifact. Workflow index files and temporary index
files are excluded from account storage accounting and backups. Source JSON
remains authoritative and is retained for downloads and recovery. Indexes add
disk use and a first-read construction cost; they do not populate the in-memory
full-result cache.

Parsed full results use a least-recently-used cache bounded by estimated Python
allocations and eight entries. `GRAPHMINE_ANALYTICS_RESULT_CACHE_BYTES` defaults
to 64 MiB; `0` disables retention. An entry larger than the cache budget is used
for its current read without evicting other cached files. Cold cache reads are
serialized, and file identity, size and timestamps invalidate replaced artifacts.
The source byte limit still applies before parsing. This bounds retained cache
memory, not total process memory: active graph operations, a cold index build,
report inputs and individual large rows or strings need working allocations.

**Save as template** captures the validated steps and settings without approval
or execution state. **Workflow templates** lets the user bind inputs from the
current conversation and change literal parameters. Parameters bound to earlier
steps remain bound. Every use creates a new validated workflow in Expert
mode, requiring approval before execution. Templates are private and survive
source-conversation deletion.

**Compare saved runs** accepts two to six runs across the user's conversations.
It displays algorithms, parameters, recorded backends, run time, exact scalar
values, completeness and findings. Input fingerprints are compared explicitly;
different or unknown fingerprints are called out rather than presenting the
runs as equivalent experiments.

## Exploration and exports

**About this result** brings four kinds of evidence together: saved inputs,
source scope, recorded calculation and display limits. It names the workflow
revision, step and output. New or revised workflows capture each input's name,
kind, hash and graph counts alongside its existing dataset/query provenance.
These descriptors survive deletion of the original upload. The primary step's
graph counts come from its actual saved input, including intermediate workflow
outputs; ancestor input counts remain in the provenance disclosure.

Source details follow the selected step's declared inputs and bindings through
table projections, reused outputs and resaved datasets. Query text, exact typed
parameters, source/mapping revision and fetch time are disclosed when recorded.
Expanded inputs identify the query as the initial selection. Missing legacy
metadata is labelled as unrecorded, without substituting the active input or
current operation catalog. A complete source selection does not establish
coverage of the entire database, and complete output does not make a heuristic
exact. Retained completed steps of failed/interrupted workflows remain clearly
identified.

Display counts distinguish preview bounds from group/positive-flow selections,
time filtering, table pages and loaded chart rows. Saved attribute overlays show
their own version and fetch time; they do not replace calculation provenance.
**Hide context** collapses the cards. Desktop uses two columns; narrow screens
stack the cards with keyboard-accessible disclosures.

Advanced calculation controls show the verified operation's input description,
quality, available devices, GPU restrictions and parameter bounds. Server byte
and runtime limits are shown alongside the plan's memory estimate and step
budgets. Completed answers offer follow-up prompts based on their actual output
types and completeness, without another model call to generate suggestions.
Prompts that the saved result can satisfy (show the largest group, highlight
the top-ranked entities, state the guarantees) carry their display or fact
action. The server rebuilds the offer from the same result and accepts only an
identical action, so these run without a routing model call. Other prompts are
planned like typed questions. A score output from a workflow that also grouped
the same vertices without overlap is coloured by that grouping, with a legend;
filters and selections still apply to the output being shown.

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
Result, step, graph-view, group, membership, table-page, CSV and report requests
accept optional `expected_revision`. The workspace supplies its displayed
revision; a mismatch returns `409 revision_conflict` after checking ownership.
This prevents another tab's revision from silently replacing the data behind the
displayed provenance. Downloads keep the requested analysis/revision in their
filename even if workspace state changes while the request finishes. A failed
graph or table read is labelled unavailable instead of claiming loaded coverage.

Workflow JSON/CSV, query-table JSON/CSV, report ZIPs, classic HTML reports,
feedback JSONL and conversation archives are prepared in private temporary
files, then transferred in 64 KiB chunks. Preparation runs off the event loop.
`GRAPHMINE_ANALYTICS_MAX_EXPORTS` defaults to `2` (allowed range 1–32) and limits
simultaneous preparation plus transfer across these routes. Additional requests
receive `429 busy`. Files close on completion, disconnect, cancellation or an
error; a cancelled preparation retains its slot until the worker finishes and
its file is removed. Downloads use `Cache-Control: private, no-store`.

Warm workflow and query-table CSV exports iterate indexed rows without building
a full row list. JSON copies the saved artifact in chunks; table JSON verifies
its content hash while reading a SQLite BLOB. Original map-shaped native outputs
retain their CSV shape and may need a full parsed result. Reports write entries
and their hashes directly into the ZIP, checking the byte budget before each
write. Workflow CSV is limited to four times the result byte limit, table CSV
to four times the input limit, and reports/partial workflows to four times their
sum. JSON retains its source byte limit. Conversation archives and feedback
retain the complete history; their size is not capped by the per-result limit.
Archive source snapshots still construct existing transcript/event views, and
large report inputs still need parsing. Temporary disk space must accommodate
the admitted downloads. These changes avoid whole encoded export buffers and
do not promise constant memory for every source operation.

The browser saves workflow JSON directly as a Blob, preserving source bytes and
large integers without parsing and re-encoding the download. Interrupted or
failed workflows use `GET /api/workflows/{id}/result?partial=true` with the
displayed revision to include all completed step artifacts. History archives
retain original evidence and omit rebuildable workflow row indexes.

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

**Data workspace → Database** lists query and import sources available to the account.
**Add connection** offers three types:

- **SQLite database:** upload a consistent `.sqlite3`, `.sqlite` or `.db` backup,
  then choose a regular table and its source/target columns. The uploaded copy
  is private and does not synchronize later changes to the original database.
- **Node.js / REST API:** provide an HTTP(S) export URL, optional bearer token,
  response format (graph JSON, scalar JSON records or CSV), and column mapping.
  Object-wrapped JSON arrays can name their top-level field.
- **Neo4j:** provide a Bolt/Neo4j URI, database and username/password. Query the
  graph directly using Cypher. PostgreSQL is optional;
  enable it for mapped table enrichment and synchronization. An unavailable SQL
  service does not block the default Neo4j graph. See
  [Database queries and result views](DATABASE_CYPHER_WORKSPACE.md).

Existing Neo4j HTTP export connections remain listed and editable. That legacy
driver uses a fixed parameterized relationship read through the
[Neo4j Query API](https://neo4j.com/docs/query-api/current/query/); it excludes
isolated nodes. New Neo4j connections use the native Cypher workflow above.

Connections belong to their creating account. **Edit connection** changes the
mapping or credentials; blank credential fields retain existing credentials for
the same server. **Remove connection** preserves previously imported versions.
Credentials are omitted from API responses and dataset provenance. Private
backups contain saved connection credentials and SQLite uploads. Each account
can retain up to 50 import connections and 100 native Neo4j connections; their
bytes count against storage.

Public HTTPS endpoints are supported directly. Private-network servers and HTTP
origins require the operator's `GRAPHMINE_CONNECTOR_ALLOWED_ORIGINS` setting.
Every network read resolves and checks the endpoint, pins its address while
preserving TLS verification, and follows no redirects. Operator-managed sources
in `GRAPHMINE_CONNECTORS_FILE` remain supported. SQLite/JSON endpoint IDs retain
integer/string types; CSV follows the existing canonical-integer policy.

Preview validates the source and shows counts and samples. Saving reads again,
checks the preview fingerprint, rechecks authorization, and creates an immutable
dataset version. Changed sources require another preview. The SQLite/REST
**Import** step displays source completeness and preview counts separately.
Use the saved version in the current or a new conversation, or import it later
through the Dataset library. Removing a connection does not prevent opening
its saved dataset versions.
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

It requires a new output directory, `agent[test,databases]`, uv,
Firefox/geckodriver, Node for syntax checking, and already verified native
artifacts. Missing prerequisites produce a failed `summary.json` before tests
start. It runs backend and browser
checks, builds both wheels, installs them in a clean Python environment and
checks CPU workflows and bounded concurrent HTTP traffic using a temporary
account/store. Reports state their scope; native compilation and live-model
accuracy remain separate checks.

`--list` prints the selected suites without running them. Database, mapping,
query, result-view and workspace regressions are discovered automatically.
Database fixtures are required local checks. To run the disposable seeded
PostgreSQL/Neo4j round trip and source-picker integration, load its demo
configuration and add `--with-databases`. This synchronizes that demo's mapped
graph. `--with-benchmarks` additionally checks its completed benchmark import.
`--with-gpus` explicitly enables checks on both UUIDs supplied through
`GRAPHMINE_ANALYTICS_TEST_GPUS`. The default gate clears inherited integration
flags; reports identify unrequested phases and individual skipped tests.

`catalog/native_execution_evidence.json` must match the binary, implementation,
source files, linked dependencies, operation profile and, for GPU execution,
physical GPU UUID. Missing or stale evidence disables the profile. Reproduce
native tests and run `tools/build_native_execution_evidence.py` for each build;
its `--help` documents required reports. `tools/audit_native_completion.py`
generates the 70-contract inventory through that same gate. Superseded reports
containing retired family identifiers are available in Git history and do not
establish current admission.

The native planner uses `GRAPHMINE_LLM_MODEL` by default. A compatible model or
adapter can be selected with `GRAPHMINE_ANALYTICS_PLANNER_MODEL`. Native planning
uses `GRAPHMINE_ANALYTICS_REASONING_EFFORT=medium` by default. The legacy V1
planner/analyst adapter settings remain scoped to the old protocol. Family and
problem selection narrow the catalog before operation selection. A separate
constrained stage builds the workflow, followed by the same actual-input validation used for manually edited
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

Routing has its own budget, `GRAPHMINE_ANALYTICS_ROUTE_THINKING_TOKEN_BUDGET`,
which defaults to 384 tokens; blank or `none` removes it. Reasoning tokens
dominate planning time (about 30 tokens per second on the local server). On
`review-query-workflows-v1` the routing budget kept the same 17 of 20 cases
passing, with a median routing time of 15 seconds; one unbudgeted routing call
on a live question took 35 seconds. A 1024-token plan budget lost
three of the ten dependent-workflow cases, so plan reasoning is unbounded by
default. Answer composition only chooses computed facts and runs without
reasoning.

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

## Dataset Studio handoff

After explicitly reviewing a completed, non-evaluation workflow, select
**Download this reviewed workflow for Dataset Studio** in the review dialog.
The authenticated `GET /api/workflows/{id}/studio-export` endpoint requires
`example_id` and `expected_revision`. It rechecks the approved example, saved
result hash and verified implementation, including changes during capability
loading. Oversized exchanges fail rather than silently dropping evidence.

Dataset Studio defaults to this checkout. Its **Import analytics** action checks
the exchange's hashes, production schema and evidence binding, retains source
attribution and requires a local content-bound review before training export.
Content edits invalidate approval; changes to a question or plan require newly
executed and reviewed evidence. Concurrent saves and exports use revision checks.

The bounded 4 MiB exchange contains a normalized workflow, derived prompt,
operation/input contracts, explicit source review and complete saved result.
Its adapter is `workflow` and schema is `AnalyticsPlanNormalized`; it is distinct
from the original planner's positional `AnalyticsPlan` model response. Studio
also validates `AnalyticsRoute`, `AnalyticsPlan` and `AnalyticsAnswer` against
production schema builders when the required context is supplied. The legacy
Studio replay engine does not execute analytics plans. Portable hashes establish
integrity, not signed authorship, fresh execution or continuing upstream approval.
See the sibling `dataset-studio/README.md` for the review/export workflow.

## Client contracts and module boundaries

The workspace keeps its browser scripts independent of a runtime bundler. Shared
modules now separate HTTP transport (`analytics-transport.js`), cancellation and
retry timing (`analytics-async.js`), typed route construction (`analytics-client.js`),
page routing (`analytics-navigation.js`), conversation/workflow observation
(`analytics-polling.js`) and DOM primitives/domain rendering
(`analytics-rendering.js`). `analytics-ui.js` coordinates conversation state and
the specialized graph, result and input views. Database-job reads, results,
cancellation use the shared route client. Account authentication
continues to wrap fetch for cookie/CSRF handling.

Reads retain both an AbortSignal and a scope check, so a completed or
non-cancellable transport cannot replace a newer conversation. Concurrency retry
waits are abortable; only explicit read retries repeat a request. Mutations do
not retry implicitly. The transport preserves lossless JSON identifiers and
structured status, error code, details and bounded retry hints, including a proxy
response that is not valid JSON. Workflow and database polling share the retry
timing policy while retaining their own progress and lifecycle rules.

Server workflow routes live in `workflow_api.py` and delegate to the existing
analytics/planning services. `api_errors.py` registers the common HTTP error
policy; `errors.py` owns the service exception, re-exported by `analytics.py` for
compatibility. `api.py` composes routes, authentication and application lifecycle.
This extraction does not change workflow review, execution or storage policy.

Generate TypeScript declarations directly from FastAPI's route/model definitions:

```bash
cd agent/frontend
npm ci --ignore-scripts
npm run contracts
npm run typecheck
npm test
npm run contracts:check
```

`GRAPHMINE_CONTRACT_PYTHON` can select an interpreter with the agent dependencies;
otherwise generation uses the checkout's `.venv/bin/python`, then `python3`.
Schema generation does not start the runtime, source connections, workers or
native execution. `generated/api.d.ts` records the OpenAPI fingerprint and is
checked for drift in the local release gate. The pinned development dependencies
are only needed for generation/checks, not by the served application.

The generated types preserve optional API defaults. Unbounded integer fields
include `bigint`, matching `AnalyticsWire`; constrained safe integers remain
numbers. The route client checks path/query/body shapes against the generated
types, and compile-time examples reject missing approval revisions, invalid
methods, wrong query bodies and boolean graph IDs. Type checking currently
covers the shared client/transport/cancellation modules and their contract tests;
the existing view scripts remain JavaScript. Responses without an explicit API
schema remain unknown instead of being assigned invented types. Runtime input
validation and authorization remain on the server.

The release gate requires the installed frontend development dependencies and
runs contract drift, type checking and transport behavior tests through
`test_api_contracts.py`, alongside the existing Firefox navigation and recovery
checks. New module files must be loaded before `analytics-ui.js` in
`analytics.html`; syntax-check every changed script before browser verification.

## MCP

Run the stdio bridge in the agent environment:

```sh
export GRAPHMINE_API_URL=http://127.0.0.1:8000
export GRAPHMINE_API_TOKEN=your-configured-token
python -m graphmine_agent.mcp
```

The bridge uses [MCP 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)
JSON-RPC initialization, tool discovery and newline-delimited stdio messages.
The original 14 workflow tools remain available. The catalog now also discovers
data sources, builds and submits read-only database queries, follows durable
jobs, retains query snapshots, reuses datasets, enriches/expands graph inputs,
imports authorized SQLite/REST sources and exports saved data. All tools call
the same authenticated HTTP endpoints, ownership, quota, revision and approval
checks as the browser. The bridge has no alternative execution path and does not
accept arbitrary URLs, filesystem destinations or connection credentials in tool
arguments. Upload files and configure connections through the HTTP API or browser.

| Workflow | MCP tools |
| --- | --- |
| Discover a graph dataset | `discover_sources`, `database_source`, `database_datasets`, `database_schema` |
| Run and follow a database query | `query_database`, `list_database_jobs`, `database_job`, `database_job_result`, `cancel_database_job` |
| Retain and reuse query results | `save_query_snapshot`, `discard_query_snapshot`, `open_query_snapshot`, `query_table_page` |
| Reuse immutable datasets | `list_datasets`, `dataset_provenance`, `save_dataset`, `import_dataset`, `open_dataset`, `delete_dataset` |
| Fetch current SQL data into a new graph version | `file_source_schema`, `enrich_file`, `expand_file` |
| Import configured SQLite/REST data | `preview_connector`, `import_connector` |
| Export saved content | `export_query_table`, `export_workflow_result`, `export_result_csv`, `export_workflow_report` |

`query_database` requires a unique `request_key` and returns the API's durable job
immediately. Reuse that key with identical arguments after a lost acknowledgement;
different work with the same retained key returns a conflict. Poll `database_job`
until terminal, then fetch `database_job_result` within five minutes. Active jobs
survive bridge disconnects; finished delivery records are bounded, memory-only,
and expire rather than accumulating as history.
Save or open temporary graph/table snapshots before expiry. List/search saved
datasets through bounded pages, then inspect provenance or copy the exact version
into a conversation. Query, import, enrichment and expansion tools do not start
an analysis. Expert analysis still requires separate approval of the exact
reviewed workflow hash and revision. `list_database_jobs` lists active work only;
this catalog does not submit graph synchronization.

Exports preserve complete stored content without rerunning a query or algorithm.
Workflow exports require `expected_revision`. Up to 4 MiB can be embedded as an
MCP text resource (CSV/JSON) or base64 blob (report ZIP), with byte count and SHA-256.
Larger exports return an MCP resource link to the existing authenticated download
endpoint; they never embed a truncated artifact. Fetch the link using the same
GraphMine account/API authentication. Links contain no bearer token or URL
userinfo and do not grant access; normal ownership, expiry and revision checks
still apply on every download. An expired preview or changed workflow may make a
previous link unavailable. Use `query_table_page` or `result_page` to inspect large
content without downloading it. Typed JSON preserves exact integers; CSV retains
the existing spreadsheet-formula escaping.

Requests and complete serialized responses are bounded at 16 MiB; the response
check includes both text and structured content. Request IDs are limited to 1024
UTF-8 bytes. Empty HTTP 204 responses become `{ok: true}`. Network failures return
a tool error without exposing configured credentials or replaying a submission.
The local database MCP regression suite uses the real authenticated API with
isolated SQLite and saved-result fixtures; it does not require native execution.

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
