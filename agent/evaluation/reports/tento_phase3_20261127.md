# Tentō Phase 3 — semantic engine administration

Date: 2026-11-27. Branch: `devlopment`. Base commit:
`7c214a7b7a88cf4af4f0fce9b2e19c3da0a68fbe`.

Phase 3 adds the Semantic engine page to the existing admin console at
`/admin#semantic`. Administrators can manage provider metadata and private keys,
model aliases, access, batch/call limits, timeout and shared worker capacity.
Connection checks read the provider model catalog; a separate native mock test
verifies the snapshot execution pipeline. The implementation retains the
approved Phase 2 explicit-label mapping and broad data preservation.

This is administration of the current **plain-read and explicit-mock backend**.
Live execution and independent answer caching remain unavailable. Thinking-off,
strict JSON, independent answers and a query-wide call budget still require
author fixes and acceptance verification. Live planner capacity and wake/sleep
integration must also be verified. No Tentō source was changed and no live model
completion request was sent. Phase 4 has not started.

## Implemented behavior

| Area | Result |
| --- | --- |
| Default provider | GraphMine vLLM follows the existing server base URL, base model and authentication; `qwen` remains server managed |
| Additional providers | Up to 32 providers, HTTP(S) base URLs, optional private keys, revision-checked editing/removal |
| Aliases | Up to 64 custom aliases, centrally mapped to provider/model IDs; reserved `qwen` and `mock` cannot be replaced |
| Connection test | Bounded real `GET /models`, configured-model availability and observation time; no redirects, environment proxies or completions |
| Mock pipeline test | Native `mock:echo`, expected answer `alpha`, one engine call, zero HTTP requests and zero independently retained answers |
| Access | Administrators by default; selected stable account IDs or all accounts may be enabled; plain reads retain normal snapshot access |
| Limits | Default/maximum calls, batch size, worker timeout and semantic concurrency; excessive requested call limits are clamped at execution |
| Durability | Existing validated SQLite settings overrides and Activity audit; provider/alias metadata in SQLite and credentials in separate private files |
| Live/cache controls | Server rejects live mode, answer-cache enablement and cache clearing with 503; UI marks those controls unavailable |
| Saved provenance | Settings changes affect new work; saved snapshots and their recorded effective settings remain unchanged |

Provider credentials live in `data_root/semantic-credentials`, with directory
mode 0700 and file mode 0600. Keys never appear in catalog responses, validation
errors, SQLite metadata or audit entries. Reads reject symlinked/unowned or
overly permissive credential files. Rotation writes a new private file and
retires the old one after metadata commits. Changing an endpoint requires a
replacement key or explicit key removal. A provider cannot be deleted while an
alias references it. Invalid legacy server URLs containing credentials are
redacted from the page and are not tested.

All routes use the existing active-administrator dependency and private/no-store
responses. Cookie mutations use the existing request-header protection. The
all-admin-route test checks signed-out and member rejection before body
validation. Stale settings/provider edits return 409. Provider response text is
not returned to the browser, including authentication and malformed responses.

## Execution policy

| Setting | Default | Allowed |
| --- | --- | --- |
| Model steps | Explicit mocks | Mock or disabled; live rejected |
| Semantic workers at once | 1 | 1–4 |
| Inputs per mock batch | 16 | 1–128 |
| Default call limit | 100 | 1–1,000, no greater than maximum |
| Maximum call limit | 1,000 | 1–1,000, per expression at this pin |
| Worker timeout | 120 seconds | 5–600 seconds |
| Model-step access | Administrators | Administrators, selected accounts, all accounts |
| Answer reuse | Off | Enablement rejected |
| Maximum answer age | 30 days | 1–365 days; saved but inactive |

The `GRAPHMINE_SEMANTIC_*` names are durable administrator-setting keys; this
phase does not add environment-variable parsing for them. An omitted or null
request call limit uses the current default. Actual limits are recorded in
`settings.admin_policy` alongside native effective settings.

Kernel file locks share admission across application processes using the same
data root. Both semantic jobs and admin mock tests acquire a slot; each native
worker uses one mock dispatch thread. The gate counts all four possible slots
before admitting work, so a lowered limit blocks admission while too many older
workers remain active. Waiting is cancellable and bounded by the existing model
queue timeout. Normal exit releases locks, and the kernel releases them when a
process dies. On Linux, native children receive SIGKILL when their supervising
process dies; cancellation/timeout still explicitly kill and reap the child.

Permissions are rechecked at submission, worker admission and before result
publication. Queued work therefore cannot retain revoked model-step access.
Active workers retain their captured numeric limits. Mode/access revocation
prevents publication but does not continuously interrupt the active native call.
Explicit cancellation remains available through the existing job endpoint.

The page warns when semantic concurrency is greater than or equal to configured
`GRAPHMINE_LLM_MAX_NUM_SEQS`. Shared vLLM/planner capacity is not raised. Mocks
send no provider traffic; the locks constrain mock worker processes, not a
verified live-provider request budget. Future live support must enter the
existing planner admission and model wake/sleep lifecycle as well.

## Verification

The final full run against a stable source tree completed in 415.005 seconds:
**2,201 passed, 56 skipped, one known baseline failure and four known baseline
setup errors**. No new implementation failures remain. All 21 new nonbrowser
checks passed in that run; both new browser scenarios passed separately, for
23 new Phase 3 checks in total. Source fingerprint checks passed.

Additional evidence:

- All 92 Phase 2 backend checks passed against the admin integration.
- Browser acceptance: 3 passed in 10.306 seconds, including the existing capacity
  settings flow and both new semantic admin scenarios.
- Supervision/admission: 2 passed in 1.771 seconds, verifying an external process
  waits under a lowered worker limit and a supervised child stops when its
  parent is killed.
- Queue access and provenance: a real queued native run rejects revoked access;
  an allowed request for 99 calls is clamped to 3, uses batch size 2, and leaves
  the base and previously saved result unchanged after later settings changes.
- JavaScript syntax checking, generated API contracts, TypeScript checking and
  the existing transport checks passed. The contracts include 180 API paths.

The first broad run reported 2,199 passed, 56 skipped, one failure and six errors.
Four errors and the failure match the documented baseline. Two additional
teardown errors correctly detected source edits made during that run; the final
run held the source tree steady and those errors are resolved. The initial new supervision fixture patched
the wrong import location; correcting the fixture produced the passing direct
supervision test. Earlier browser checks led to clearer select labels and a
success-message color fix; the final browser run passed with no page errors.

Known baseline cases are recorded in the
[Phase 1 report](tento_phase1_20261127.md):

- `test_adapter_workflows.py::test_embedded_client_creates_and_closes_a_separate_application`
  expects the temporary data root to be absent after application setup created it.
- Four `test_yelp_instance_integration.py::test_published_yelp_query_through_app_read_path`
  cases (`Q01`, `Q02`, `Q08`, `Q24`) call the session fixture without settings and
  fail at `settings.data_root` before querying.

Tests use disposable application data, temporary accounts, synthetic keys and
loopback model-catalog servers. Browser checks cover creation/removal, settings
review and persistence, secret cleanup on Escape, member rejection, native mock
results, desktop and a 390-pixel mobile viewport with no overall page overflow.
Provider tables use the existing horizontal scrolling on narrow screens.
Playwright Chromium was installed only in the evidence directory; no shared
service, deployment, vLLM configuration or production account was changed.

Local evidence is under `validation/tento-phase3-20261127` beside the checkout:
test logs/JUnit files, the isolated validation runner, and
`screenshots/semantic-desktop.png` and `screenshots/semantic-mobile.png`.

Reproduction from a configured development checkout:

```bash
.venv/bin/python -m pytest agent/tests deploy/tests -n 4 --dist=loadfile -q
PLAYWRIGHT_BROWSERS_PATH=/path/to/installed/playwright/browsers \
  .venv/bin/python -m pytest agent/tests/test_admin_semantic_browser.py \
  agent/tests/test_admin_manage_browser.py -q
node --check agent/graphmine_agent/static/admin-semantic.js
```

Use the development native/runtime paths required by the existing suite and an
isolated `GRAPHMINE_AGENT_DATA_ROOT`. The archived `run_tests.py` supplies only
the nonsecret development runtime path settings and disables GPU selection.
Broad-suite browser/GPU/benchmark skips are separate from the explicit browser
acceptance run.

## Engine and remaining gates

The unchanged pin is `62e124217e2c0f82e327136b5888263e95671fae`, distribution
`graphmine-tento==0.1.0+62e124217e2c`, native SHA-256
`a388ba5ac37262944615148666791009050e37b11b6a442d4134c0f2cbf15c50`.
The admin status reads package metadata without importing the native engine;
actual execution still verifies the pinned binary in the disposable child.

The author dependencies remain in [AUTHOR_REQUESTS.md](../../../deploy/tento/AUTHOR_REQUESTS.md).
Changing admin flags or adding aliases cannot bypass them. Answer-cache controls,
estimates and judgment inspection must use verified engine support before being
enabled. Phase 4 is the next separately approved scope: snapshot refinement,
progress and provenance in the existing main workspace.
