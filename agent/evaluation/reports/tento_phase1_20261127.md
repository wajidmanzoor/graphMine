# Tentō Phase 1 — source installation

2026-11-27. **Installation is implemented and verified; live acceptance remains
pending author fixes.** The user explicitly authorized Phase 1 after the Phase 0
investigation, delegating routine implementation choices. This advances the
source installation without changing the engine or relaxing the agreed provider
and data contracts. Phase 2 has not started.

## Implementation

- Added `third_party/tento` as an unmodified, detached Git submodule pinned to
  `62e124217e2c0f82e327136b5888263e95671fae`. Upstream `main` was checked and still
  matched this investigated revision.
- Added [build.sh](../../../deploy/tento/build.sh) and its
  [builder](../../../deploy/tento/build.py). They compile Tentō's own pybind
  target with explicit source paths, eight compiler jobs, an isolated build
  environment and no upstream engine download. The source pin and clean tracked
  state are checked before and after building.
- Package the compiled engine as `graphmine-tento==0.1.0+62e124217e2c`. This local
  wheel supplies `ladybug`; the optional `semantic` extra requires this exact
  distribution. Ordinary agent installation does not depend on it.
- Added a [lazy loader](../../graphmine_agent/semantic_engine.py) that verifies
  the installed distribution, source commit, native location and SHA-256. Missing
  or incompatible bindings produce the existing `AnalyticsError` HTTP 503 form.
  Importing the helper and starting GraphMine do not load Tentō. Worker and
  execution-route integration belong to Phase 2.
- Added a bounded [smoke tool](../../../deploy/tento/smoke.py) using the installed
  wheel and an in-memory database. It checks six semantic functions and
  `mock:echo`, with model credentials removed and semantic planning calls off.
  `--live` exposes the unresolved provider gate and sends no request.

Installation commands and maintenance instructions are in the
[deployment README](../../../deploy/tento/README.md). Build tools and initial
verification used disposable environments under `validation/tento-phase1-20261127/`.
After verification, the same wheel was installed into this development checkout's
own `.venv`, and its editable agent metadata was refreshed with the semantic extra.
Both installs used `--no-deps`, preserving all existing dependency versions.
No service was restarted or reconfigured; production, testing and the shared
analytics/vLLM environments were not modified.

## Verified evidence

The [machine-readable report](tento_phase1_20261127.json) records the final wheel,
native hashes, installed smoke outputs and startup results. Tested platform:
Linux x86-64, CPython 3.12.3, GCC 13.3, CMake and Ninja, with OpenSSL 3.

| Check | Result |
| --- | --- |
| Fresh source build, local wheel installation | Passed |
| Repeat source build and reinstall | Passed; no source patch applied |
| Platform/ABI tagging | Native `cp312-cp312-linux_x86_64`, not a pure-Python wheel |
| Packaged native hash | Matches the installed provenance manifest |
| License packaging | Engine license and 21 bundled notice files; debug files excluded |
| Required functions | `LLM`, `LLM_SCORE`, `LLM_AGG`, `LLM_PATH_AGG`, `LLM_SG_AGG`, `SUBGRAPH` |
| Mock call | One row, column `answer`, value `["alpha"]` serialized as a string |
| Installed agent with engine | 9 focused tests passed |
| Installed agent without engine | 8 passed; native smoke skipped as expected |
| Development installation | Same verified native hash; mock smoke and all 9 focused tests passed |
| Missing engine CLI | Exit 1, `semantic_unavailable`, actionable build/install message |
| Missing/damaged/foreign engine HTTP error | 503; no internal path or raw loader error exposed |
| System-interpreter installation attempt | Rejected before build/install |
| Live gate | Exit 2, `semantic_controls_unsupported`, zero model requests |
| Submodule tracked state and whitespace checks | Clean |

The native library hash of the final install is
`a388ba5ac37262944615148666791009050e37b11b6a442d4134c0f2cbf15c50`.
The build procedure is reproducible, but these upstream builds are not claimed
to be byte-identical: the repeat compile produced a different binary hash.
Each packaged build records its own hash, and `--install` explicitly reinstalls
the wheel even when its commit-derived version is unchanged.

## Regression status

The correctly configured full `agent/tests` and `deploy/tests` run finished with
**2,087 passed, 55 skipped, 1 failed and 4 setup errors** in 418.14 seconds. It
used the existing development native-runtime paths, four pytest workers, no
visible GPU and a disposable data root. Skips include opt-in GPU/database/browser
checks and the native smoke in the then-unmodified development virtualenv; the
native smoke passed in the dedicated environment and after development install.

Every remaining failure was rerun against the unchanged pre-Phase-1 application
at `c3dcbcf81116301b8e6d4a04ba83e65fecfa51bf`, with the same runtime configuration.
The baseline produced the same **1 failure and 4 errors**:

- `test_embedded_client_creates_and_closes_a_separate_application` asserts that
  the fixture's data directory does not exist, although setup already creates it.
- All four `test_published_yelp_query_through_app_read_path` cases fail during
  fixture setup because `neo4j_session()` reaches `access(settings)` with
  `settings=None`, before running their queries.

These existing problems are not changed by Phase 1. The full suite is therefore
not reported as green. An earlier, unconfigured attempt was interrupted after
revealing the missing analytics-interpreter path; it is not the final regression
result. Full logs, JUnit reports and the exact non-secret runtime configuration
are retained under `validation/tento-phase1-20261127/`.

## Outstanding acceptance

No real Qwen semantic request has been sent. The pinned engine cannot carry the
required thinking-off control and may retry a rejected schema without structured
output. Calling the model under those conditions would not satisfy the agreed
live smoke test. The smoke tool deliberately reports this as blocked.

The [author requests](../../../deploy/tento/AUTHOR_REQUESTS.md) remain pending:
provider controls, independently retained answers, an actual query-wide request
budget, and an approved lossless label/edge mapping. An updated author revision
must pass those checks, and its verified provider API must be added to the live
smoke. Clearing a lock-file flag alone cannot enable it. Phase 1's installation
work is ready for review; its full exit gate is not yet passed.
