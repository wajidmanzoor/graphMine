# Workspace improvements

Implementation follows the October 2026 application review of
`graphMine-database-cypher`. Each item is complete only when its behavior has
been verified. Existing ownership checks, typed identifiers, immutable analysis
inputs, execution evidence, approval rules, and result provenance remain required.

## Reliability and recovery

1. **Complete — conversation navigation.** Cancel superseded reads and prevent
   delayed conversation, workflow, result, or preview responses from replacing
   the current workspace. Cover navigation home and stale failures in browser tests.
2. **Complete — connection backups.** Include saved database connections in online
   backups and verify their ownership, permissions, and recovery during restore.
3. **Complete — workflow updates.** Recover polling after transient failures, show
   connection status, and reconcile when a tab becomes active.
4. **Complete — conversation discovery.** Search the complete authorized history
   on the server with pagination, including archived conversations.
5. **Complete — query preview lifecycle.** Keep immutable previews temporary until
   used or saved; expire unused previews and deduplicate content while retaining
   each snapshot's provenance.
6. **Complete — query drafts.** Autosave and restore drafts by account, connection,
   dataset, and conversation, with explicit discard controls.
7. **Complete — release coverage.** Include the database, mapping, source-picker,
   and query suites in the release gate; distinguish required local checks from
   configured live database and GPU integration checks.

## Functionality and interface

8. **Complete — guided graph builder.** Select entities, relationships, filters,
   direction, and weights with inspectable generated Cypher.
9. **Complete — query workspace.** Provide saved queries, history, parameter forms,
   schema completion, formatting, and inline query errors.
10. **Complete — complete query tables.** Preserve scalar query results as table
    artifacts with paging, sorting, CSV export, and reuse as analysis inputs.
11. **Complete — background database work.** Give queries and synchronization
    durable jobs, progress, cancellation, and recovery.
12. **Complete — exploration persistence.** Restore active graph versions,
    enrichment overlays, filters, labels, colors, and graph viewports.
13. **Complete — working layout.** Provide a dedicated data workspace with schema,
    editor, and preview panes; make mobile connection/query/preview steps clear.
14. **Complete — readability and accessibility.** Improve text and control sizing;
    verify contrast, keyboard access, zoom, and mobile layouts.
15. **Complete — returning-user home.** Show recent datasets, saved queries, and
    resumable analyses prominently.
16. **Complete — result context.** Present source/version, query scope, preview
    limits, and calculation quality together without conflating them.

## Performance

17. **Complete — connection reuse.** Reuse bounded Neo4j drivers and PostgreSQL
    pools with credential/revision invalidation and short-lived sessions.
18. **Complete — efficient paging.** Index large result access, page lightweight
    dataset summaries, and load provenance separately.
19. **Complete — incremental browser updates.** Update changed conversation turns,
    index events, load older history on demand, and preserve graph instances and
    positions when data has not changed.
20. **Complete — bounded memory and exports.** Evict result caches by bytes and
    stream or spool exports instead of retaining complete export buffers.

## Integration and maintainability

21. **Complete — independent connections.** Support Neo4j-only analysis, optional
    SQL enrichment, and consistent discovery of SQLite and REST sources.
22. **Complete — incremental synchronization.** Support keyed updates, deletions,
    synchronization history, and schema changes while preserving snapshot meaning.
23. **Complete — MCP coverage.** Expose database discovery, query snapshots,
    datasets, enrichment, and export through the existing authenticated bridge.
24. **Complete — modules and contracts.** Separate session navigation, polling,
    rendering, transport, routes, and services; generate typed client contracts
    and share cancellation and error handling.
25. **Complete — Dataset Studio integration.** Adapt current analytics schemas and
    preserve authorship, reviewed revisions, and execution evidence before export.

## Verification record

- Navigation: six delayed-response regression cases and 35 conversation/result
  recovery cases passed in Firefox; the existing 14 loading/shell cases passed.
- Backups: 27 selected backup, account and connection tests passed, including
  online/offline restore of three isolated owners and credential corruption.
- Polling: ten Firefox cases passed for network/503/429 recovery, backoff,
  manual retry, tab/network reconciliation, lost access, and navigation cleanup.
- History: 59 backend checks and 17 browser checks passed, covering complete
  title search, literal/Unicode queries, archived results, paging, ownership,
  delayed search responses, and mobile navigation.
- Previews: 51 query/dataset regressions and 66 preview/account/backup checks
  passed. Preview payloads deduplicate within an owner; promotion keeps the ID
  and provenance; failed promotion rolls back. Desktop/mobile save/discard pass.
- Drafts: ten Firefox checks passed for reload/discard, independent connection
  and dataset drafts, account/API/conversation isolation, storage failure, query
  editor behavior, and account settings.
- Combined reliability regression: 188 backend tests and 79 Firefox tests
  passed. A further 24 targeted checks passed after reserving responsive space
  for the recovery banner and moving history reads off the API event loop.
- Release gate: local/database/GPU suite selection, environment isolation,
  prerequisites and skipped-integration reporting are tested. The full gate
  stopped at preflight because `.venv-analytics/bin/python` and
  `library/build/runtime/libgraphmine_runtime.so` are absent. No live database
  or GPU work was run. Preflight also checks `GRAPHMINE_NATIVE_BINARY` (default
  `library/build/runtime/graphmine-native`), which is absent in this checkout.
- Guided builder: 58 backend query/lineage checks and 13 Firefox checks passed.
  Generated queries are scoped to the selected mapped/catalog graph, filters use
  parameters, and weight selection preserves relationship IDs and SQL lineage.
  The builder requires declared graph schema; unmapped connections retain the
  Cypher editor. Live Neo4j execution is not covered by the local fixtures.
- Query workspace: 78 final query/builder/release backend checks and eight new
  Firefox editor checks passed; the 13 existing query/builder/draft browser cases
  also passed. Another 69 checks covered accounts, query backups and schema
  compatibility. Saved queries are owner-scoped, revision-checked and included
  in quota accounting; history is bounded and does not retain result payloads.
  Browser checks cover 320-pixel layouts, exact integer parameters, invalid
  edits, formatter literal preservation, keyboard suggestions, Unicode error
  positions, history loading and stale dataset responses.
- Query tables: 72 backend checks and 19 Firefox checks passed for complete
  typed results, all-row sorted exports, owner isolation, expiry, corruption,
  backup, library reuse, mobile paging, and preserving the current graph.
  The final 15 backend and 11 Firefox checks also passed after table-only draft
  recovery and rapid schema-switching fixes. Projection tests verify the native
  adapter receives the complete table and retains provenance; native execution
  could not run because its executable is absent. The initial implementation
  read the bounded table artifact for each page; step 18 adds reusable indexes.
- Database jobs: the initial 89 backend regressions passed, followed by 72
  query/transaction/backup/release checks and 24 final job contract checks.
  Firefox passed 24 job/table/editor cases and two final HTTP compatibility and
  retry checks. Coverage includes page reload without resubmission, idempotent
  admission, queued/running cancellation, atomic commit boundaries, transient
  polling and access failures, stale responses, private results, storage quotas,
  exact table values, and disabled-owner rejection on a real app restart.
  Online backup preserves completed results; staged restore stops pending jobs.
  Failed terminal writes reconcile to an explicit interrupted state. Live Neo4j
  and PostgreSQL transactions remain unverified here; cancellation checks use
  controlled driver fixtures. Browser checks run on desktop and 320-pixel views.
- Exploration: 56 backend graph/backup checks and 80 account/storage/release
  checks passed. Firefox passed 50 graph/navigation regressions, then 27 final
  persistence/navigation/loading checks and four final overlay checks. The 17
  new persistence cases cover active inputs separate from older analysis inputs,
  typed selections, node positions, viewport resizing, table/group/time filters,
  source styles and saved overlays, result items and context on a small screen,
  unavailable browser/server storage, lost save acknowledgements, explicit tab
  conflict resolution, corrupt local recovery, removed files, changed workflow
  revisions, and stale reads during navigation. Backend checks verify private
  ownership, exact large integers, bounded settings, concurrent revisions,
  immutable enrichment ancestry/integrity, quota accounting, deletion and online
  backup recovery. Attribute restoration does not query live source databases.
- Data workspace: 36 query/job/table cases and 51 navigation/editor/connection
  cases passed, followed by 38 final Firefox checks and five release-discovery
  checks. The 15 new layout cases cover three desktop panes, schema search,
  keyboard steps, preserved drafts and previews, direct routes and reloads,
  returning to the original saved result, resizing with editor focus, 320×640
  action visibility, missing datasets, background discovery, file imports and
  delayed responses after navigation. Desktop, 320-pixel and 768-pixel renders
  were inspected. This step uses controlled local source responses; it does not
  claim live Neo4j/PostgreSQL or native/GPU execution coverage.
- Readability and accessibility: 83 distinct Firefox cases passed across the
  final targeted runs, plus five release-discovery checks. The 14 new
  accessibility cases cover rendered text contrast and size, desktop/mobile
  control targets, keyboard focus, drawer background isolation and restoration,
  location-point activation, real 200%/400% browser zoom, 320×256 reflow,
  reduced motion, forced colors and signed-in settings. Existing regressions
  cover queries, builders, tables, exploration persistence, commands, navigation,
  connections, accounts and project workflows. Account checks now set actual
  320/390-pixel viewports rather than relying on the browser's minimum window
  size. Desktop and mobile chat/Data renders were inspected. Tests use local
  fixtures and isolated accounts, without live database or native/GPU execution.
- Returning-user home: 51 backend checks and 73 distinct Firefox cases passed
  across the final targeted runs. The 13 new backend cases verify private,
  bounded summaries, ownership and archive filtering before pagination, active
  analysis priority, latest retained dataset versions, preview exclusion, exact
  copied inputs, typed tables, integrity/quota rollback and authentication.
  The 19 new browser cases cover desktop/320-pixel layouts and contrast, empty
  home, paging, independent retries, exact analysis links without approval,
  dataset/domain selection, saved-table column selection, recoverable first-read
  failures, saved-query source/dataset selection, draft preservation, mobile
  routes and reloads, removed or moved queries and stale navigation responses.
  Existing Data, query, draft, navigation, accessibility, library and account
  regressions passed. Home works while native capability discovery is pending.
  Desktop/mobile renders were inspected; syntax, whitespace and release-suite
  discovery checks passed. These checks use isolated local fixtures, without
  live source queries, model calls or native/GPU execution.
- Result context: 84 backend checks and 103 distinct Firefox cases passed across
  the final targeted runs. The 17 new backend cases cover immutable input
  descriptors, exact identifiers, missing source uploads, primary graph counts,
  preview limits, ownership before revision checks and concurrent revision
  changes. The 31 new browser cases cover desktop/320-pixel readability,
  independent source/output completeness and quality, derived/bound inputs,
  reused table/result ancestry, unknown historical metadata, expansion and
  overlays, intentional group/flow/time filters, paged tables and invalid
  filters, failed/stale reads, pending native discovery, and revision-pinned
  JSON/CSV/report downloads. Navigation, conversation graphs, exploration,
  recovery and accessibility regressions also passed. Export checks retain
  reproducibility, exact large identifiers and spreadsheet escaping. Desktop
  and mobile renders were inspected; JavaScript syntax, whitespace and release
  discovery checks passed. These are local fixture and stored-artifact checks;
  live source databases, model calls and native/GPU execution were not run.
- Connection reuse: 238 distinct local backend checks, six Firefox cases and
  six tests against an isolated PostgreSQL 16 cluster passed across the final
  targeted runs. The 26 pool cases cover driver/session reuse, separate owners
  and reader/writer credentials, credential/revision/endpoint invalidation,
  idle/LRU eviction, global capacity including resources still closing, bounded
  queues, cancellation, timeouts, stale source files, failed edits, managed DNS
  checks and captured resolver identity, lazy real-driver construction, request
  lifecycle and operator bounds. A durable-job regression checks runtime pool
  propagation. PostgreSQL checks exercise actual backend reuse (30 sequential
  reads within the configured connection cap), read-only repeatable-read
  transactions, snapshot renewal, session and named-cursor cleanup, timeout and
  dead-socket recovery, failed acquisition retirement, credential generation
  changes and shutdown closure. PostgreSQL reset completes before a connection
  returns to its pool. The temporary server used a private Unix socket and was
  removed afterwards. Account, backup, query, dataset, mapping and release
  discovery regressions passed; Python parsing and whitespace checks passed.
  The database extra now includes `psycopg-pool`. Live Neo4j, configured source
  databases, model calls and native/GPU calculations were not run.

- Efficient paging: 188 distinct backend checks and 38 distinct Firefox cases
  passed across the final targeted runs. Stored workflow summaries, output
  pages, group selection/memberships and complete query table pages now use
  persistent row indexes. Tests verify exact typed IDs and large integers,
  stable ascending/descending ties, missing values, full-scope filters, lazy
  construction and concurrent readers, warm reads without source parsing,
  source changes, revision/owner checks, corruption, expiry/promotion/deletion,
  schema migration, backups and storage accounting. Dataset lists use bounded
  summaries, server search and separate on-demand provenance. Browser coverage
  includes desktop/320-pixel paging and collection selection, stale responses,
  retries, nested table cleanup, imports and returning-user home. Mobile and
  desktop renders were inspected; the chosen collection's full name remains
  visible when its select control clips it. JavaScript syntax, Python parsing,
  whitespace and release discovery checks passed.
  A local synthetic 100,000-row, three-column artifact took 1.821 seconds to
  index and used 64.2 MiB on disk. Warm last-page, descending-sort, exact-search
  and substring-search requests measured 4.81, 3.79, 0.34 and 29.24 ms respectively.
  These timings are observations, not production guarantees. Substring search
  and deep offsets still scan index entries; full exports and graph inputs may
  read complete source artifacts. First construction still parses the source;
  cache memory and export buffering remain step 20. No native/GPU, model or live
  source database execution was run for this step.

- Incremental updates: 149 distinct available backend checks and 74 distinct
  Firefox cases passed across the final targeted runs. Indexed conversation
  pages preserve stable question numbers, complete boundary turns, classic
  history, manual analysis cards and saved answer facts. Tests cover schema
  migration, ownership, invalid cursors, archive changes, lightweight workflow
  summaries, bounded event batches and query work as history grows. Redundant
  reasoning chunks are omitted from display pages; original evidence remains
  intact. Browser checks cover unchanged DOM/focus/disclosures, desktop and
  320-pixel history paging, scroll and keyboard-focus preservation, retries,
  stale navigation responses, backlog catch-up and exact large sequence IDs.
  Graph refreshes retain instances, viewport, positions and subscriptions for
  unchanged topology/scope while refreshing attributes and removing obsolete
  filter styles. Existing exploration, navigation, commands, conversation and
  polling regressions pass. Desktop/mobile renders were inspected; Python,
  JavaScript, whitespace and release-discovery checks passed.
  A synthetic 10,000-question, 40,000-event conversation returned 45 display
  events (11,690 response bytes) for its newest 30 entries. Fifteen warm reads
  measured a median 2.46 ms and maximum 2.62 ms locally. These timings are
  observations, not production guarantees. First access to classic archives
  still indexes their files; the lightweight analysis selector still reads the
  full catalog. An expanded native-dependent run remains unverified: 45 tests
  reported the missing analytics environment and one planner-start check timed
  out. Available checks were rerun separately. Native artifacts and the analytics
  environment remain absent; no live source, model or native/GPU work was run.

- Bounded memory and exports: 201 distinct backend checks and 31 Firefox cases
  passed across the final targeted runs, with no skipped cases. Parsed-result
  retention now has a configurable 64 MiB allocation estimate and eight-entry
  LRU cap; oversized entries bypass retention and cold cache reads serialize.
  Tests cover eviction, disabled retention, same-size replacement, removal
  during parsing, concurrent readers and caller-owned result copies.
  Workflow/table JSON and CSV, report ZIPs, classic HTML, feedback JSONL and
  history archives use private prepared files, bounded transfer chunks and a
  shared configurable download admission limit. Checks cover transfer and
  preparation cancellation, late-worker cleanup, send failures, byte budgets,
  source changes, owner/revision enforcement, exact types and large integers,
  spreadsheet escaping, complete sorted tables and deterministic report hashes.
  HTML evidence snapshots write incrementally; history archives retain original
  evidence and exclude derived row indexes. An obsolete CSV test was corrected
  to check the existing CPU reader's inferred mapping and rejection of invalid
  explicit columns. Import, storage-failure, backup and ownership checks pass.
  Browser checks cover unchanged JSON bytes, completed and partial downloads,
  revision conflicts, filenames, query tables, commands and offline HTML charts,
  linking, scope and pagination. Release discovery, Python/JavaScript syntax and
  whitespace checks passed.
  Warm JSON, CSV and report exports of 12,000 rows (over 3 MB of source data)
  stayed below 2 MiB of additional traced Python allocations in the regression
  cases. A 20,000-row standalone HTML report stayed below 4 MiB. These are local
  fixture measurements, not whole-process memory guarantees: cold index builds,
  source parsing, large individual rows/strings and archive source views still
  need working memory. Temporary disk use is proportional to admitted exports.
  Native/GPU, live database and model execution were not run; the full release
  gate remains unverified without the native artifacts and analytics environment.

- Independent connections: 218 backend checks and 92 distinct current Firefox
  cases passed across the final targeted runs, with no skipped or unresolved
  cases. Neo4j-only connections save, reopen, rotate credentials, and restore
  from online/offline backups. Adding/removing SQL updates lineage and removes
  detached SQL credentials; existing configured connections retain compatibility.
  Default graph queries never open SQL, and SQL discovery failures leave them
  available with a warning. Unsupported enrichment and synchronization report
  explicit capability errors; invalid sync requests never enter the job queue.
  The unmapped graph builder uses bounded read-only Neo4j schema samples, reports
  their incompleteness and rejects row/byte overruns without partial choices.
  The unified inventory enforces ownership, namespaces source IDs and retains
  available providers when another provider fails. SQLite and REST can be added,
  mapped, previewed, saved and opened in current or new conversations. Imports
  retain exact identifier types, check preview fingerprints, distinguish source
  scope from display limits and remain usable after their connector is removed.
  Failed new-conversation imports roll back their session and files. Credential
  validation errors omit supplied secrets. Browser checks cover delayed discovery
  permissions, source removal, draft/editor recovery, result capabilities and
  existing navigation. Import controls exclude Cypher tools; narrow-screen labels
  wrap, and graph layout begins only after the preview pane is visible. Desktop
  and 320-pixel screenshots were inspected. Python/JavaScript syntax, whitespace
  and release-suite discovery passed. Verification used local contract fixtures,
  SQLite and isolated HTTP servers; live Neo4j/PostgreSQL, native/GPU and model
  execution were not run. The full release gate still requires the missing native
  artifacts and analytics environment.

- Incremental synchronization: 191 distinct local backend checks, 13 real Neo4j
  checks, seven temporary PostgreSQL checks and 28 Firefox cases passed. The
  Neo4j suite used an isolated Community 5.26.32 instance and SQLite inputs;
  PostgreSQL checks created and removed their own private Unix-socket cluster.
  Stable keys now drive inserts, updates and deletions, with zero graph writes
  on an unchanged snapshot. Live tests verify preserved physical IDs, null
  removal, mapping/label/type changes, legacy adoption, empty-source deletion,
  foreign relationship protection, concurrent-edit rejection, cancellation and
  pre-commit mapping-change rollback. Saved graph bytes and provenance remain
  unchanged across source refreshes and can still open in a new conversation.
  Missing mapped SQL columns, including enrichment-only fields, fail before
  opening the graph writer; qualified column references avoid SQLite's literal
  fallback. PostgreSQL checks verify the same schema contract and pool recovery.
  All API synchronization requests use the durable queue, including synchronous
  waiters, with per-source serialization, idempotency, private persisted summaries,
  error status and job references. Cancelling a waiter leaves server work running.
  Firefox checks cover count breakdowns, mapping notices, history filtering,
  reload without resubmission, explicit failures versus no-change success,
  cancellation boundaries and the existing responsive Data layout. Desktop and
  320-pixel screenshots were inspected; syntax, whitespace and release discovery
  passed. Fifteen optional seeded-demo browser cases were skipped and are not
  counted as passes. Native/GPU and model execution, and the full release gate,
  remain unverified without the missing native artifacts and analytics environment.
  Graph writes are incremental, but deletion detection still reads complete
  bounded SQL and managed-graph snapshots. The standalone CLI does not use the
  workspace job ledger and must run exclusively for its source.

- MCP coverage: 90 distinct backend checks passed across the final targeted
  runs, including the real stdio initialization/catalog exchange. The 43-tool
  catalog preserves the original workflow tools and adds authorized source/schema
  discovery, inspectable graph-query generation, idempotent durable queries, job
  recovery/cancellation, immutable graph/table snapshots, dataset paging/reuse,
  SQL enrichment/expansion, connector imports and complete saved-data exports.
  Tests use the real authenticated HTTP application with isolated SQLite,
  controlled query results and saved-result fixtures. They verify cross-account
  rejection and token revocation, exact large identifiers and scalar types,
  snapshot immutability, mapping/revision conflicts, rejected write queries,
  preview fingerprints, empty-response handling and preserved report evidence.
  Small CSV/JSON/ZIP exports embed exact content and hashes; larger artifacts
  return authenticated links without bearer tokens or URL credentials, close
  their streams and never embed partial content. Response limits include text
  and structured copies; invalid paths, oversized IDs and unsupported arguments
  fail before HTTP work. Network errors do not echo configured credentials.
  Python syntax, whitespace and release-suite discovery passed. No UI assets
  changed in this step. Native calculations, live source queries and external
  model clients were not executed; the full native-dependent MCP workflow and
  release suites still require the missing analytics environment and artifacts.

- Modules and contracts: 137 backend checks, 77 Firefox checks and ten Node
  transport checks passed. Generated contracts cover 116 API paths; TypeScript
  checks verify route parameters, request bodies, response types and lossless
  identifiers. Contract drift and JavaScript syntax checks passed. Navigation,
  polling, transport and basic rendering now have explicit module boundaries;
  workflow routes and API error handlers are separate from application setup.
  Existing specialized views remain JavaScript; type checking currently covers
  the shared asynchronous transport/client layer. Browser coverage includes
  accounts, home, loading, navigation races, polling recovery, jobs and tables.

- Dataset Studio: 86 workspace backend regressions, 17 Studio integration checks
  (including three Firefox flows), two workspace handoff browser checks and ten
  Node transport checks passed. Contracts regenerate without drift for 117 API
  paths and type checking passes. The authenticated handoff rejects stale,
  revoked, incomplete, foreign-owner and evaluation evidence; it rechecks review
  state after capability loading and rejects oversized results before parsing.
  Studio preserves exact large identifiers, source attribution, local authorship,
  content-bound reviews and execution evidence across export/import cycles.
  Stale saves and exports fail without writing; semantic edits clear approval
  and changed analytics targets require fresh execution evidence. Legacy rows,
  first startup, private dataset access, export checksums and download retries
  are covered. Desktop and exact 320-pixel layouts were inspected; review controls
  and target headings now wrap inside the narrow detail pane. The handoff uses
  a separate normalized-workflow adapter with derived context, not a claimed
  capture of the original planner request. Portable hashes establish integrity,
  not signed authorship, fresh execution or continuing upstream approval after
  download. Tests use temporary datasets and controlled saved execution evidence;
  they do not run native calculations, GPU work or model calls. The full release
  gate still needs the missing analytics environment and native artifacts noted
  above. Changes in this step span this checkout and sibling `dataset-studio`.

Schema 11 adds indexed public conversation entries and stable question numbers
to schema 10's transactional dataset summaries and table content change tokens,
private conversation exploration settings, durable database
jobs, reusable typed tables, temporary previews, saved queries and bounded
history, and refuses older application versions. Each
conversation retains up to 32 view contexts within 512 KiB; settings are included
in backups and deleted with the conversation. Existing saved
dataset rows remain unchanged. Drafts live in the
browser; unsaved preview content expires after 24 hours and is cleaned hourly.

The review baseline passed 254 backend tests and 19 browser tests. A native
workflow test could not execute because this checkout lacked its configured
analytics Python environment. Live database, GPU, and model evaluations require
their respective configured environments and are not implied by browser fixtures.

## October 22 review fixes

The follow-up fixes separate count-only results from retained groups, prevent mode
buttons from submitting drafts, keep account SQLite waits off the event loop, and
remove duplicated native arrays from summary headers. Result context starts with
a compact source/quality summary; its full provenance remains available through
Show details. Regression checks cover cancellation while a lease is being acquired.

The server snapshots the UI at startup and serves content-hashed bundles with
compression and immutable caching. The graph renderer loads when a graph is
opened. `/api/build` and the page metadata identify the same application build;
open tabs offer a reload after an upgrade, without discarding drafts automatically.
API responses use private, no-store caching. Security headers include CSP, frame
protection, MIME checking and a same-origin referrer policy. Legacy Vega charts
retain an eval exception only on the classic page, and API documentation retains
its CDN/inline initializer exception.

A small set of explicit standalone triangle-count and maximum-clique questions
can bypass model routing and planning. Native verification and input validation
remain mandatory; ambiguous, contextual, filtered and unsupported requests use
the full planner. Scalar-only answers use computed facts directly. This does not
change the cost of complex model-planned questions or exact combinatorial searches.

Strict JavaScript checks now include rendering and conversation history as well
as transport/client infrastructure and update notifications. Conversation history
uses the generated API client. Remaining feature modules can be migrated in
small increments; the entire legacy UI is not yet statically typed.

### Reproducible local operation

Use Python 3.12 and the tested dependency constraints:

```sh
uv pip install --python .venv/bin/python -c agent/requirements.lock -e 'agent[test,databases]'
cd agent/frontend
npm ci
npm run build
npm run contracts:check
npm run typecheck
npm test
```

When the application is in a worktree, set `GRAPHMINE_RUNTIME_REPOSITORY` to the
checkout containing the verified native build and its source/report inventory.
Application catalogues, prompts and UI stay rooted in the application checkout.
Native workers, evidence, default binaries and the default analytics interpreter
use the runtime checkout. Explicit `GRAPHMINE_ANALYTICS_PYTHON`,
`GRAPHMINE_NATIVE_BINARY` and `GRAPHMINE_NATIVE_LIBRARY` still take precedence.
The release gate supports this arrangement and installs wheels under the same
constraints. `/api/health` exposes the application build ID and, after verification,
the native implementation hash.

Finish edits and tests before restarting the service. Take a verified store backup,
check that no work is running, restart the existing process manager service, then
compare `/api/build` with the HTML metadata and exercise a known-answer workflow.
Do not copy fresh static files into a process that imported older backend code.

### Validation and deployment record

The final application runs under the existing `graphmine-agent.service` user
service at `https://10.33.76.25:18000/`, with account authentication enabled.
The same service serves the frontend and backend. Existing accounts and saved
data were preserved. A verified 3,068-file snapshot was taken before deployment
under `.database-workspace/backups/before-review-fixes-20261022T214023Z`.

- Backend: 1,408 cases in the full run. After targeted reruns, 1,351 distinct
  cases passed, 49 were skipped, and eight legacy `test_native_uploads.py` cases
  still failed. All eight failures were reproduced against the untouched source
  snapshot from before these fixes. They assert the older direct cuDF/native
  ingestion path; the existing GraphStore uses the CSV ingestion path instead.
  The full backend suite is therefore not green.
- Browser: all 282 scenarios passed across the full Firefox run and targeted
  reruns. The full run initially passed 275; the remaining seven passed in
  targeted reruns. Assertions were updated where needed for lazy graph loading
  and collapsed details.
  The final 11-case run also covered mobile source previews, graph selections,
  comparison costs, result context, background jobs, and table imports.
- Frontend: build, generated contracts for 118 API paths, strict type checks,
  and all ten Node tests passed. Final asset and concurrency regressions passed.
- Clean installation: the final wheel passed eight smoke checks, including CPU
  native execution, packaged assets, reproducible exports, read-only database
  import, authentication, and a bounded 64-request concurrent HTTP exercise.
- Real integrations: isolated triangle-count and maximum-clique workflows
  completed with correct answers using the configured native runtime. Read-only
  Neo4j queries preserved large identifiers and imported graph results. Desktop
  and 390-pixel result screens were inspected. GPU execution and live database
  synchronization were not exercised in this follow-up.

Local measurements show the first page transferring about 193 KB in 11 resource
requests, compared with 1.08 MB in 54 requests during review. A 10,000-group
summary with one requested row decreased from 596,051 to 497 bytes. With a real
SQLite write lock held for two seconds, a 50 ms event-loop heartbeat completed
in 51 ms, compared with about 2,038 ms before the fix. The small known-answer
triangle and maximum-clique workflows completed in 7.76 and 5.88 seconds.
These are local checks on small inputs, not capacity or large-graph benchmarks.

Result headlines now appear before evidence controls on narrow screens. The
graph appears before its detailed controls, and full source information remains
available through Show details. Saved results keep their complete artifacts;
bounded summaries and collapsed details do not remove evidence.

Detailed logs, screenshots, comparison snapshots, and machine-readable results
for this run are in `/tmp/graphmine-fixes-20261022/`.
