# Tentō Phase 5 — cross-feature checks and live prerequisites

Date: 2026-11-27. Branch: `devlopment`. Base commit: `5a5d5e2f`.

Cross-feature checks now verify the runnable mock and structural integration. **Phase 5 live
acceptance remains blocked and the overall integration is not complete.** No
local-Qwen completion or W1–W24 workload was executed. The
[machine-readable workload inventory](tento_phase5_20261127.json) records every
workload separately, including missing prerequisites and unmeasured quality,
usage and duration. Zero provider requests does not mean a completed workload.

## New cross-feature evidence

Eight new checks cover the real native refinement/solver chain, three supervised
worker failures, expiration of a queued parent, concurrent provider credential
isolation and two workload-inventory cases.

The movie/review fixture starts with two movies, four reviews and four edges.
Explicit `mock:echo` evaluates a fixture sentiment field and keeps three negative
review labels. The resulting five-vertex, three-edge snapshot is saved and
attached to chat through the real APIs. The native CPU densest-subgraph solver
selects `movie-a`, `r1`, `r2`, with density **2/3**. Enumeration of all 31 nonempty
vertex subsets independently confirms this optimum. The result records
`native_exact_maximum_weight_closure`, exact rational arithmetic, `optimal: true`
and `quality: exact`, even when the requested option is `approximate`.

The recorded input identifies the derived snapshot and its hash, with simulation
provenance kept separate from solver quality. A subsequent plain refinement
retains that simulated ancestry. The original saved snapshot remains byte-for-byte
unchanged, and no database-source refresh occurs. This is a synthetic-data mock
acceptance flow, not a live sentiment-quality measurement or a real Neo4j read.

The final acceptance rerun retained these disposable evidence identifiers:

| Artifact | Identifier / SHA-256 |
| --- | --- |
| Original version | `dataset_version_4b2031c18bdb4d358fc7bc8ae26389e8` |
| Original hash | `28dc0551e553f63145d8bbffe3dcfd9819138a21f7d77568cd9f847af37b8877` |
| Refined version | `dataset_version_a26fec00322d4a8294eaf0c302aa846d` |
| Refined hash | `bb170a12dee5aa795c5d076da6bbde0cd9eff2f3d60fcc09cf26fa643a0e8bac` |
| Solver workflow, revision 1 | `e2a35eff-ed3f-4c98-88d8-36410b22f2f0` |

`validation/tento-phase5-20261127/mock-movie-flow.json`, beside the checkout,
retains the complete synthetic graphs, version metadata and native result.
These IDs belong to a disposable test application; they are not deployed links.

Timeout, explicit cancellation and an unexpected child exit are tested through
the actual job API and real subprocess supervisor. Each child writes an
incomplete artifact before failing. The parent kills/reaps the process, publishes
no preview, preserves the base, and an explicit retry produces exactly one new
version. An expired queued parent stays leased until completion, then becomes
eligible for cleanup without deleting the output.

Two administrators test two provider catalogs simultaneously against a local
fixture. Both requests overlap, use their own configured synthetic credentials,
and omit keys from API results and public metadata. This verifies catalog
credential isolation only; simultaneous live inference remains gated. The
fixture respects the existing one-mutation-per-account limit.

## Verification

The focused set passes **36 checks**, including all **8 new checks**. Four Yelp
integration cases skip because the configured local instance is offline.

| Check | Result |
| --- | --- |
| Full `agent/tests deploy/tests -n 4 --dist=loadfile` | **2,229 passed**, 53 skipped, no failures/errors; 434.99 seconds |
| Final native acceptance and strengthened store-isolation check | **6 passed**; 14.92 seconds |
| Isolated PostgreSQL connection/pool integration | **7 passed**; 2.08 seconds |
| Final cross-feature browser regression | **85 passed**, 4 prerequisite skips, no failures; 179.49 seconds |
| Desktop/mobile readability after final layout correction | **2 passed**; 15.74 seconds; screenshots reviewed |
| Frontend | Types, **35 unit tests** and contracts for **181 API paths** pass |
| Existing pinned-engine probe | All **8 diagnostic groups completed**; live blockers reproduced |
| Installed-wheel live smoke | Mock passes; live gate exits **2**, zero real provider requests |

The full run's 53 skips retain the existing GPU and external-service gates.
Seven of those SQL tests were subsequently run successfully against their own
temporary PostgreSQL server on a private Unix socket. The configured Yelp
instance is offline and the disposable Neo4j demo remains opt-in. Existing
FastAPI deprecation and asynchronous capability-loader teardown warnings remain;
they do not change the test pass/failure counts.

Two previous full-suite fixture defects were repaired without weakening their
purpose: embedded-client isolation now checks the original store's bytes remain
unchanged, since setup legitimately creates its backend-selection file; the
Yelp source now carries isolated backend settings when opening a session.

The initial browser run reproduced exactly the 17 result-context failures
recorded in Phase 4. Fixtures now use the visible surrounding-graph checkbox,
group buttons and Download menu. Persistence and report-image cases receive
the current native view metadata, including workflow identity and labels.
Report tests verify the revision in the POST body and the image read, while
CSV/JSON tests retain the revision query parameter. Conflict handling, immutable
download names and exact JSON bytes remain asserted. All 17 baseline browser
failures are resolved. Compact result text now uses the existing 14-pixel
workspace token. A conflicting stylesheet selector was corrected so narrow
result cards use one column. Desktop/mobile contrast and reflow assertions are
retained. No API execution behavior or Tentō source was changed.

The evidence directory contains test commands, logs, JUnit XML, mock-flow data,
the native smoke result and the eight-group engine probe. `run_tests.py` supplies
only the required native runtime paths, an isolated application data root, and
the existing local browser binaries. The semantic extra is the installed
source-built wheel. Ordinary provider credentials are not forwarded to workers.

## Live gate recheck

The configured Git remote's `main` was checked and still points to
`62e124217e2c0f82e327136b5888263e95671fae`. The GitHub connector returned 404 for
the private repository; read-only SSH Git access supplied the remote check.
The submodule remains unchanged. The installed native SHA-256 is
`a388ba5ac37262944615148666791009050e37b11b6a442d4134c0f2cbf15c50`.
The engine's reported version is not used as proof of source identity.

All eight existing diagnostic groups completed against that pin. They reproduce
the unsupported contracts; their completion is not a passed feasibility gate:

- The provider rejects thinking-control alias fields and omits thinking-off
  controls from the request.
- A schema-rejection response can trigger a request without the required JSON
  schema. The request limit is per expression and does not bound every HTTP retry.
- A fresh memory-database worker repeats previously completed answers.
- Default planning can call the model. Counters reset on reads and selected
  input rows are not completed judgments.

The installed-wheel live smoke passes its mock stage and then exits **2**, with
`semantic_controls_unsupported` and zero real provider requests. The probes use
explicit mocks and synthetic loopback HTTP fixtures. No shared vLLM settings,
planner capacity, services or author communications were changed.

## W1–W24 measurement prerequisites

Configured target: **`Qwen/Qwen3.8-27B-FP8`**. Its actually loaded model revision
and effective inference settings are unverified because no live completion was
made. Requested policy remains thinking off, strict JSON and temperature zero.

The unchanged paper runner defines `r_qwen` against the remote REALLMS service;
it has no alias for this local model. Its default list omits W22–W24. After an
author-supported local adapter is available, all 24 IDs must be named explicitly.
The current inventory never invokes that runner or substitutes a remote model.

The documented data root `/home/wajid/lbug_data` lacks all eight required database
files and the applicable quality exports/references. Presence checks concern
that configured location; they do not prove the data is absent everywhere.

| Workloads | Required database | Paper quality measures |
| --- | --- | --- |
| W1–W3, W5–W9, W11 | `semantic_movies.lbdb` | Sentiment/genre/year accuracy, count error, ranking accuracy, rating/review F1; W6 unscored |
| W4, W15–W17, W20–W21 | `ldbc.lbdb` | Reference precision, path-state F1, structural predicate and company/member accuracy; W17/W20 unscored |
| W10 | `flights_country.lbdb` | Airport-country pair F1 |
| W12–W13 | `flights.lbdb` | Reference end-airport and reachable-airport F1 |
| W14, W18 | `flights_code.lbdb` | Route F1 and airport-country accuracy |
| W19 | `kg.lbdb` | No score in the systems table |
| W22–W23 | `ecomm_sf500.lbdb` | Description-image and image-pair F1 |
| W24 | `vg100.lbdb` | No systems-table score; annotated-object recall is a separate optional ablation metric |

W22's vector extension is also absent at the runner's expected build path.
W22–W24 image assets and local-model image-input support remain unverified. W24
explicitly enables answer reuse within its fresh copied database; this differs
from the default workload cache-off setting and must remain visible in a future
measurement report. Missing references prevent quality scoring, while unscored
workloads must not be assigned invented metrics.

## Required to finish Phase 5

Obtain and review the author's fixes for the
[recorded contracts](../../../deploy/tento/AUTHOR_REQUESTS.md), then rebuild and
recheck them. Verify local-Qwen controls and shared planner admission; provide the
workload databases, truth exports and required image/vector assets; implement the
verified local runner configuration without patching the submodule. Then run the
real Neo4j → Qwen negative-review refinement → saved input → densest-subgraph flow
and W1–W24 measurements. This report does not waive those exit requirements.

Reproduction commands and the distinction between mock execution and live
acceptance are in the [Tentō guide](../../../deploy/tento/README.md).
