# Full GPU release validation

The full build compiles 59 GPU profiles across 36 runnable problems. Final
admission allows **58 profiles across 35 problems**, plus CPU execution for all
82 native problems. Physical GPU 1 is the analytics device; GPU 0 remains reserved
for the model service. The hierarchy is Family → Runnable Problem → Backend.

## Correctness and integration

The native checks passed 173,960 independent oracle requests, all 77 CTest cases,
175 CPU contract tests and 34 original GPU adapter tests. Broader paired collection
then found an intermittent cuMBE counting error. On the committed
[20-vertex counterexample](cumbe-counterexample.json), CPU execution and an
independent closed-neighborhood enumeration both find 26 maximal bicliques;
cuMBE alternates between completing and failing the exact materializer check.
[The reproduction](cumbe-correctness.json) records both outcomes. The correctness
manifest quarantines this exact implementation/backend pair. CPU biclique
enumeration and GPU biclique counting through `mbe-gpu` remain available.

The initial broad application run exposed 13 Dataset Studio integration failures
from old operation fields. Its catalog, replay, tagging and current training
fixtures now use runnable problem IDs. Legacy annotation metadata is normalized
on read; historical training targets and their hashes remain unchanged. Invalid
historical targets still require review against the current schema before export.
All 25 Studio checks passed after the fix. The combined latest application
results are **1,904 passed, 44 skipped, no unresolved failures**, recorded in
[verification-summary.json](verification-summary.json), with the initial
failures retained in `application.xml` and replacements in `studio.xml`.

The release also passed 374 Python binding checks, 28 saved-history checks,
35 browser checks, 31 frontend tests, TypeScript and API-contract verification.
A read-only rehearsal loaded all 32 existing production workflows and result
artifacts without modifying the original bytes. New writes use `problem`;
saved `operation` fields remain readable. Approval hashes are preserved, and
rerunning an old workflow still requires validation against the current runtime.

## Paired collection

`benchmarks/full_gpu_policy.json` collects every admitted backend on the same
generated graph and settings, under idle and added CPU-load regimes. The labels
describe the benchmark's added load; other host workloads remain present.
Measurements retain actual hardware snapshots and are split by entire graph
fingerprint for policy evaluation. Parameters do not enter the NN features.

The original collection was continued with sparser probability graphs because
the CPU independent-cascade reference enumerates live-edge states even for a
heuristic request. The 162 completed timings were reused by their original run
IDs, and the operator-cancelled attempt remains in its original log. See
[benchmark-continuation.json](benchmark-continuation.json). This changes the
training workload only. Execution allowances remain six hours and input-byte
limits remain disabled.

The completed collection and whole-graph policy comparison are reported in
[POLICY_EVALUATION.md](POLICY_EVALUATION.md), with all original timings in
[paired-timings.csv](paired-timings.csv) and the model's dropped features in
[shared-policy-evaluation.json](shared-policy-evaluation.json).

## Routing regression

The [release rerun](routing.json) completed all 42 frozen questions with unchanged
source hashes and no unavailable cases. It reproduces the previously measured
runnable-problem results:

| Metric | Previous three-call router | Full GPU release |
|---|---:|---:|
| Correct family | 42/42 | 42/42 |
| Expected calculation selected | 39/39 | 38/39 (97.44%) |
| Questions clarified | 2/42 | 4/42 (9.52%) |
| Authored ambiguous cases clarified | 2/3 | 3/3 |
| Model calls per question | 3 | 2 |

The extra clarification asks what “match workers to tasks” should optimize,
while the frozen expected answer is bipartite matching. The expected label
remains unchanged. These are authored routing regressions; parameter accuracy
and end-to-end workflow success are not inferred from the routing score.

## Testing and production acceptance

The first testing-environment pass exposed a validation-harness issue: its
scratch store was under `/tmp`, which backend persistence correctly rejects.
The controller now creates and cleans its isolated validation store under its
private state directory. Its isolation/recovery tests and all dataset-deployment
tests pass (60 checks). Two archived upstream HTML pages also contained renamed
external API terminology; their original bytes were restored so the published
source audits pass. The original failed testing report remains in the private
release directory.

Promotion uses the environment controller: the testing environment
must pass its configured application, frontend, binding and native checks on
the exact candidate commit before the production branch can advance. The
verified native runtime is a separate pinned snapshot; development rebuilds do
not replace production binaries. Each environment has its own shared model and
backend log store. Earlier production model/log stores are retained.

`deploy/validate-full-gpu-release.py` checks a running release through its actual
HTTP API and browser. It verifies the 82/35/58 capability counts, the cuMBE
quarantine, six-hour timeouts, unlimited input-byte settings and a parameter-free
NN. It runs CPU triangles, GPU triangles, GPU k-core, GPU communities and an
automatically selected triangle calculation, checking the logged model version
and exact selection probability. A legacy `operation` request must normalize to
`problem`. Evaluation-tagged runs cannot train the policy; the temporary test
account is disabled afterwards. Testing also checks a live two-call routing
question and the saved-results browser.

Controller reports and environment-specific acceptance results are saved in
`graphmine-data/environments/state/full-gpu-release-20261125/` outside Git.
`last-promotion.json` records the exact tested commit and production backup.
The earlier [42-question routing comparison](../../docs-internal/RUNNABLE_POLICY_EVALUATION.md#routing-and-workflows)
records the three-call to two-call change; the release rerun uses the same frozen
suite and is also mirrored in the private release report directory.
These authored routing regressions do not establish production workflow success
rates or paired shadow-policy performance.
