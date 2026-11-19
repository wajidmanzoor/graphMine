# Baseline measurements — November 18, 2026 lab window

Both required server runs completed: a sequential 30-question benchmark and a
10-user load test with a 60-second ramp and 20-minute generation schedule. The
load test then allowed existing questions to finish. Timestamps in the evidence
use UTC (November 19); the approved lab window was November 18 in New York.

| Measurement | Benchmark | 10-user load |
| --- | ---: | ---: |
| Journey attempts | 30 | 65 |
| Questions actually submitted | 30 | 51 |
| Completed responses | 15 | 16 |
| Users with completed responses | 1 | 9 |
| Failed journeys | 15 (50.00%) | 49 (75.38%) |
| Busy / concurrency failures | 0 | 27 (41.54%) |
| Routing mismatches | 0 / 25 checked | 1 / 32 checked |
| Answer latency p50 | 75.92 s | 248.26 s |
| Answer latency p95 | 82.98 s | 316.44 s |
| First-reply latency p95 | 54.00 s | 191.27 s |
| Result-view latency p95 | 622.82 ms | 761.62 ms |
| Model queue share of answered latency | 0.05% | 69.05% |
| Routing reasoning-token share | 68.31% | 71.63% |
| Calculation queue wait p95 | 2.59 s | 2.79 s |
| Recorded monitor errors | 0 | 0 |

Answer percentiles include completed responses only; failures remain in the
error rate. Fourteen load attempts failed during dataset/session preparation,
before a question could be submitted. One completed load response gave only a
documentation answer to a densest-subgraph calculation request, so it is also
counted as a routing mismatch. Completion does not imply routing correctness.

## Reports and evidence

- Benchmark: [Markdown](benchmark/report.md), [standalone HTML](benchmark/report.html),
  [summary JSON](benchmark/summary.json), [config](benchmark/config.json),
  [cleanup receipt](benchmark/cleanup.json), [SHA-256 manifest](benchmark/SHA256.json).
- Load and comparison with the benchmark: [Markdown](load/report.md),
  [standalone HTML](load/report.html), [summary JSON](load/summary.json),
  [config](load/config.json), [cleanup receipt](load/cleanup.json),
  [SHA-256 manifest](load/SHA256.json).

Download an HTML file and open it locally for the interactive Vega-Lite charts.
The scripts and licenses are embedded; there is no CDN dependency. Each report
directory also contains compressed question, HTTP-step, server-event, system,
load-shape, dataset and lifecycle JSONL evidence. Credentials, private environment
files, captures, graph files and backend training history are excluded.

The benchmark ran from clean commit `bf7efa88708b111b2d1dace7e47107232fea7dde`.
The load ran from clean commit `27179494f778e2a2c8c9621e27d71ad8869b234a`.
The application code is identical between those commits. The latter adds a test
driver recovery fix and its regression test: retry session creation after a busy
rejection instead of attempting a question without a valid session. An earlier,
interrupted diagnostic load attempt is excluded from these measurements.

## What the measurements support

Model admission and repeated routing calls are the first performance targets.
Under load, model queue waits account for 69.05% of answered latency, and there
are 26 concurrency-limit failures plus one busy database-query rejection.
The 26 admission failures split equally between session creation and planning.
There were no recorded model queue timeouts; increasing the timeout alone would
not address the observed admission rejections. Routing reasoning accounts for
71.63% of reported routing completion tokens across 228 covered calls.

Functional failures also need separate investigation. The benchmark records ten
native candidate-budget failures and five planner failures with provider HTTP
400 responses. The load records 16 native candidate-budget failures, five
clarification loops, one planner failure and one documentation-only routing
mismatch. The evidence does not establish the cause of the provider HTTP 400s.
Use the request, turn and workflow IDs in the reports to trace those failures.

Calculation queue p95 stayed below three seconds in both runs; result views
stayed below one second at p95. The load's observed model wake took 1.767 seconds.
The provider recorded no preemptions. Provider waiting requests with low KV-cache
usage trigger the requested concurrency flag, but provider/GPU/host measurements
include other activity on this shared server. The application traces identify
this run. The proposed configuration matrix remains a later experiment, not a
measured improvement or a production change.

## Scope, validity and cleanup

Both runs use the same read-only Yelp User–Business projection: 989 vertices,
1,000 edges, fingerprint
`52e718b73fd680a607915e644284f811fd790db36bdb5a21a801f13e1e57c449`.
The exact Cypher query is in both configs. Results describe this projection,
question mix and shared-server window, not the entire Yelp database. The
benchmark uses five fixed rounds; load uses weighted questions and think times.
Their comparison is descriptive, not a controlled configuration experiment.

The benchmark covers all six questions five times with one user. The load shape
lasts 1,200.35 seconds, with all 1,135 recorded steady-period samples showing ten
users. It finishes at 04:06:41 UTC after draining existing questions. No question
was interrupted, and no invalid-session requests remain in the final load run.
All expected answered turns have matching server observations (41/41 benchmark,
46/46 load). Missing measurements stay N/A: neither journey exercises exploration
saves, and only one slow database call in the load exposes a separable lock wait.

Both cleanup receipts confirm removal of all 51 synthetic accounts, credentials,
sessions and owned data; owned external backend copies were also removed. Each
run requested and confirmed model sleep. Production application, model and
Dataset Studio services retained their original process IDs. Capacity, prompts,
model behavior and trained models were unchanged. Only daily quotas in the
disposable stores were raised.

Stress, spike, soak and the configuration matrix were not run.

Validation passed: all 18 performance-suite tests; 28 focused instrumentation,
queue and API checks; 186 planning/account/power regressions; result-view,
exploration, database and contract regressions; TypeScript checks; and 31
frontend tests. Packaged reports regenerate byte-for-byte from the compressed
evidence, all eleven sections are present, and the embedded charts compile with
the vendored Vega-Lite scripts.

To verify the packaged evidence and regenerate the reports into a temporary
directory, run from the repository root:

```sh
perf_copy=$(mktemp -d)
cp -R perf/reports/2026-11-19-baseline/benchmark "$perf_copy/benchmark"
cp -R perf/reports/2026-11-19-baseline/load "$perf_copy/load"
python3 - "$perf_copy" <<'PY'
import gzip, hashlib, json, sys
from pathlib import Path
for run in Path(sys.argv[1]).iterdir():
    manifest = json.loads((run / 'SHA256.json').read_text())
    for name, digest in manifest.items():
        assert hashlib.sha256((run / name).read_bytes()).hexdigest() == digest
    for path in run.glob('*.jsonl.gz'):
        path.with_suffix('').write_bytes(gzip.decompress(path.read_bytes()))
PY
.venv-perf/bin/python perf/report.py "$perf_copy/benchmark"
.venv-perf/bin/python perf/report.py "$perf_copy/load" --compare "$perf_copy/benchmark"
```

Suite setup, all test shapes and interpretation details:
[Performance testing guide](../../../docs/PERFORMANCE_TESTING.md).
