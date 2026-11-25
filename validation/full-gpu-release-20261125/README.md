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

Collection, final shared-policy evaluation and the live deployment checks are
completed in the subsequent release report. This commit records the validated
build, compatibility fixes and the cuMBE quarantine before promotion.
