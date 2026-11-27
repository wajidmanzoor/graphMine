# Tentō Phase 4 — snapshot refinement workspace

Date: 2026-11-27. Branch: `devlopment`. Base commit: `8403dbc2`.

Phase 4 connects the approved plain-read/explicit-mock snapshot backend to the
existing JavaScript workspace. A complete database graph preview offers
**Refine with model**; saved conversation inputs also expose refinement in their
source details. Successful runs create distinct immutable graph/table versions
that use the existing save, discard, export and chat attachment paths.

## Implemented behavior

- Actual snapshot schema, original labels, safe table/property aliases and
  version/hash; one `Vertex` table and explicit label helpers.
- Plain reads and explicit mock selection, administrator-approved alias
  metadata, per-expression call limits, projection, direction and edge weights.
  Live aliases and answer reuse are disabled with current capability explanations.
- Formatting, schema suggestions, typed/JSON parameters, semantic highlighting,
  policy checks and extracted model-step prompts/types. Native syntax is checked
  when running; inspection does not execute queries or reserve jobs.
- Eleven schema-based template types: plain read, extraction, filtering,
  ranking, group summary, subgraph input/aggregation, path aggregation,
  path-step conditions, consecutive steps and carried state. Relationship
  templates appear only when a corresponding table exists.
- Snapshot/conversation/identity-scoped drafts. Input edits invalidate the
  executable result selection; late submission and job responses cannot replace
  a newly opened context.
- Existing durable job monitoring/cancellation, observed usage and elapsed time,
  failure guidance and native parser-position navigation. Match counts and
  completed judgments remain explicitly unavailable; no synthetic counters.
- New graph preview or complete paged scalar table; bounded row samples are
  distinct from complete saved output. Model usage distinguishes simulation,
  provider HTTP requests, engine calls, selected inputs, cache hits and retained
  answers. Limits are explicitly per expression, not query-wide.
- Revision-specific semantic ancestry in Result context, with calculation
  quality kept separate from simulated/model-dependent input. Rerun opens the
  recorded parent/query/parameters/direction without saved-answer reuse and
  requires a fresh run. Current permission/limit policy applies.
- Keyboard-accessible controls, Escape/Close, Ctrl/Cmd+Enter and Ctrl+Space,
  responsive schema/query/preview navigation, visible focus and contrasting
  text. No new framework or design runtime.

## Verification

All **25 new Phase 4 checks pass**: one inspection/API test, eleven native
template tests, twelve refinement browser scenarios and one recorded-provenance
browser scenario. Local evidence is stored beside the checkout under
`validation/tento-phase4-20261127`; `summary.json` indexes the JUnit results.

| Check | Result |
| --- | --- |
| Final full `agent/tests deploy/tests -n 4 --dist=loadfile` | 2,220 passed, 49 skipped, one known baseline failure and four known baseline fixture errors; 427.96 seconds |
| Focused backend/worker/editor | 113 passed |
| Browser-generated templates on the pinned native engine | 11 passed; mock execution with zero provider HTTP requests |
| Refinement browser acceptance | 12 passed; 76.53 seconds; real native mocks and API save/chat operations |
| Recorded semantic ancestry and rerun context | 1 passed, including records without newer optional provenance fields |
| Existing browser regression | 42 passed; 17 existing result-context failures reproduced against baseline `8403dbc2` |
| Frontend | Type checks and all 35 existing tests passed; syntax checks passed; contracts match all 181 API paths |

The final full run held the source tree stable and introduced no new failures.
Its one failure and four fixture errors match the [Phase 1](tento_phase1_20261127.md)
and [Phase 3](tento_phase3_20261127.md) baseline findings: the embedded-client test
expects a data root that setup has already created, and four Yelp fixtures call
the session helper without settings. Optional GPU and disposable external-service
checks remain skipped under their existing prerequisite gates.

The existing browser run initially had one additional failure in the new
semantic-provenance case. It exposed unsupported `undefined` values when older
records omit new fields. The renderer now records missing fields as null, and
the targeted scenario passes. The other 17 failures reproduce using the exact
committed baseline static assets, extracted into a separate validation directory:
two older typography audits, two exploration-persistence checks and thirteen
interactions with collapsed result controls. No baseline-only failures appeared.

New browser acceptance covers snapshot schema/templates, real native execution,
immutable parent hashes, requested direction, graph save/chat attachment,
recorded reruns, complete scalar tables, draft isolation/restoration, input and
invalid-parameter invalidation, keyboard shortcuts/focus containment, 390-pixel
reflow, text contrast of at least 4.5:1, member restrictions, syntax positioning,
failure usage, cancellation and late-response isolation. Controlled job responses
exercise unavailable live-server failure states without issuing live calls.
Desktop/mobile screenshots are in `screenshots/refinement-desktop.png` and
`screenshots/refinement-mobile.png`. No page errors were reported.

Initial native probes caught prompt-placeholder restrictions and an untyped
empty relationship list. Templates now bind arbitrary property expressions to
variables before interpolation and construct subgraphs from typed paths. The
first browser fixture used an invalid authentication-bypass configuration and
an evaluation-string wait disallowed by CSP; both fixtures were corrected.

Reproduction uses the configured native runtime paths, a disposable
`GRAPHMINE_AGENT_DATA_ROOT`, the source-built semantic extra, Firefox for existing
browser checks, and Playwright Chromium for the new flow. `run_tests.py` records
the nonsecret runtime-path setup and selects an isolated data directory. New
browser tests share the established disposable account/application fixtures;
use `PYTHONPATH=.:agent:agent/tests` from the checkout when running them directly.

```bash
.venv/bin/python -m pytest agent/tests deploy/tests -n 4 --dist=loadfile -q
PYTHONPATH=.:agent:agent/tests PLAYWRIGHT_BROWSERS_PATH=/path/to/browsers \
  .venv/bin/python -m pytest agent/browser_tests/test_semantic_refinement.py -q
```

## Remaining live acceptance gates

Tentō's source remains unchanged at
`62e124217e2c0f82e327136b5888263e95671fae`. No live model completion requests,
planner capacity changes, deployments or author messages were made. Thinking
off, strict JSON, independently retained answers, a total query budget and
live-provider scheduling still need author fixes and verification. Estimates
and per-row judgment inspection remain unsupported.

Phase 5 live measurement (Qwen movie/review refinement, downstream densest
subgraph and W1–W24) has not been started. Mock browser acceptance does not
establish those live contracts. See [AUTHOR_REQUESTS.md](../../../deploy/tento/AUTHOR_REQUESTS.md).
