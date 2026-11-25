# Runnable problems and shared policy evaluation

This records the initial development experiment. The later
[full-GPU release report](../validation/full-gpu-release-20261125/README.md)
records broader backend coverage and the operator-requested production rollout.
Historical measurements below are preserved.

Development implementation and measurements, 2026-11-25 UTC. Benchmark recommendation:
**keep native execution with the shared NN in shadow**. The old learned selectors
have been removed as requested. Development now explicitly enables live NN/bandit
selection as described below. That override does not establish production rollout
evidence or change the measured results in this report.

The initial experiment below used parameter features. The current schema-2 model
excludes them; its retraining and execution verification are recorded in the
final section.

## Scope and data

The final hierarchy has 14 families and 82 runnable problems. Topics provide
documentation hints; parameters remain within each executable contract. Old
workflow `operation` keys normalize to `problem`; newly written workflows use
only `problem`. Phase 1 and Phase 2 are separate commits.

The fresh paired dataset contains **192 completed timings**, 16 generated
graphs, triangle `count` and `enumerate` modes, and idle/busy CPU regimes. Sizes
are 32, 128, 512 and 2,048 vertices. Every comparison measures `cpp`, `tot` and
`wetric`, in randomized order under one analytics-GPU lease. Each regime has a
65-second warmup; busy CPU adds two workers on a 128-logical-core machine. All
original timings are retained in [paired-timings.csv](../validation/runnable-problems/paired-timings.csv);
the full aggregate contexts and manifest are in the private development store
identified by [paired-data-summary.json](../validation/runnable-problems/paired-data-summary.json).

The split holds out entire snapshot fingerprints: **13 training graphs and 3
test graphs**, including every mode/load setting for each graph on the same side.
This gives 52 training comparisons and 12 held-out comparisons. No pairs were
excluded and no held-out data entered normalization or fitting. Both encoders
trained for 2,000 epochs with seed 1729 and the same features, mask and cost loss.
Only the NN weights were published. Its vocabulary has 82 problems and 38 backend
IDs; this dataset supplies timing evidence for one problem and three backends.
Of 875 feature columns, 864 had no training variance and were dropped. The 11
retained columns and all dropped names are recorded in the linked data/model
metadata. There is one 64→32 ReLU encoder and one shared backend preference layer;
no runtime or memory regressors remain.

| Regime | Timings | Mean free-core fraction | Mean analytics-GPU utilization |
|---|---:|---:|---:|
| idle | 96 | 0.069 | 55.1% |
| busy_cpu | 96 | 0.132 | 58.6% |

Other workloads were present on the host and analytics GPU. The labels describe
our added CPU load, not an otherwise idle machine. These small graphs and limited
load variation do not establish a GPU crossover or cross-problem generalization.
The previous development runtime had no compiled GPU profiles; the new build
adds verified ToT/WeTriC triangles. Other runnable problems remain available on CPU.

## Held-out results

The ratio is selected runtime divided by the fastest measured eligible runtime.
The table integrates the exact configured softmax probabilities (temperature 1,
floor .02) within measured size ranges, and uses greedy decisions outside them.
It does not simulate a production exploration ledger. Tail times use observed
wall times. Failures would incur 10× the slowest completed paired runtime for
cost evaluation; all 192 observed attempts completed.

| Policy | Mean ratio | Median | p90 | p99 | Native–oracle gap closed | Tail seconds p90 / p99 | Failure / timeout |
|---|---:|---:|---:|---:|---:|---:|---:|
| Shared NN + bandit | 1.0047 | 1.0000 | 1.0000 | 1.0000 | 99.45% | 0.2858 / 0.3394 | 0.0% / 0.0% |
| Shared linear + bandit | 1.3132 | 1.0000 | 1.9584 | 2.1692 | 63.66% | 0.3450 / 0.3615 | 0.0% / 0.0% |
| Native ordering | 1.8618 | 1.7225 | 2.2631 | 2.6169 | 0.00% | 0.4894 / 0.4987 | 0.0% / 0.0% |
| Measured oracle | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 100.00% | 0.2858 / 0.3394 | 0.0% / 0.0% |
| Removed per-problem regressions | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

The removed-policy comparison is unavailable: the requested deletion supersedes
the original old-model rollback plan. No old-policy result is inferred. Native
ordering is the model-free fallback. The full table, including breakdowns, is in
[shared-policy-evaluation.json](../validation/runnable-problems/shared-policy-evaluation.json).

The only measured problem is `triangle-counting`, and every held-out comparison
has **K=3**; those breakdowns equal the aggregate table. K=1 and K=2 masking are
covered by contract tests, but have no held-out timing claim here. Three held-out
graphs are too few for a reliable tail-performance or generalization conclusion.

## Routing and workflows

The same 42 authored development questions were run against the configured
Qwen/Qwen3.8-27B-FP8 model. These are regression cases, not a human-labelled
held-out benchmark. Calculation scoring has 39 unambiguous cases; three cases
expect clarification. No case was unavailable in the completed runs.

| Routing metric | Before | Final route instruction |
|---|---:|---:|
| Correct family | 42/42 | 42/42 |
| Expected calculation selected | 39/39 (100%) | 38/39 (97.44%) |
| Questions returning clarification | 2/42 (4.76%) | 4/42 (9.52%) |
| Expected ambiguous cases clarified | 2/3 | 3/3 |
| Routing model calls per question | 3 | 2 |
| Live parameter accuracy / workflow success | Not measured | Not measured |

The additional clarification was “match workers to tasks”: the model asked what
the assignment should optimize, whereas the frozen label expects bipartite
matching. The labels were not changed to improve the score. The initial revised
router selected 39/39 calculations but clarified only 1/3 ambiguous cases; the
final instruction trades one extra clarification for covering all three.

A live response also contained an unfinished question. A deterministic fallback
now supplies a complete question while preserving its offered meanings, with no
extra call. A fresh live probe verified the fix and unchanged sources:
[clarification probe](../validation/runnable-problems/routing-after-clarification-probe.json).
The “ambiguous cases clarified” metric measures intent and offered alternatives;
it is not a human rating of conversational usefulness.

Full reports: [before](../validation/runnable-problems/routing-before-awake.json),
[final instruction](../validation/runnable-problems/routing-after-final.json).
Routing implementation and configuration files stayed unchanged during the full
run; its broad checkout flag is false because unrelated integration/test work
continued. The small clarification-formatting fix followed that full run and has
its own probe. Initial authentication/sleep failures are excluded from accuracy.

## Verification and rollout

Frozen-source agent shards: 1943 passed, 59 skipped, no failures or errors.
The native build passed 61 CTest cases (15 disabled optional integrations),
178 CPU contract/migration tests and both real triangle GPU oracle tests. All 82
CPU contracts have matching admission evidence. Frontend checks passed 31 tests,
TypeScript and generated API contracts. The related lane suite verified 34 exact
reference answers; calculation-card grading now accepts one to three distinct
ranked choices. Authored planner/workflow tests check parameter preservation,
clarifications, dependent steps, legacy reads, deadlines and cancellation.

An isolated worker smoke loaded the published NN and exercised both shadow and
live-test decisions: native chose ToT, the NN chose CPU, and both returned the
same triangle count. Those rows are explicitly evaluation-only. They are not
production shadow traffic and do not train the model.

There are **zero measured production shadow rows**, and unexecuted alternatives
have no observed runtime. Shadow agreement alone cannot establish regret,
failure or timeout rates. The live gate remains closed. Broader paired coverage
and paired measurements of real traffic are still required before a production
switch; the small development result does not meet the original switch criteria.

Development uses private `backend-runs` and `backend-models` directories. Its old
history, captures and workflow artifacts were cleared. Previously shared
production logs/models were preserved and are no longer development's paths.
At evaluation completion, the configured development mode was `shadow`, with
rollout evidence required. Setting selection to `native` provides a model-free rollback.

The development checkout and private environment configuration now use this
implementation. A startup smoke through the development interpreter loaded all
82 native problems in a temporary store. The development web services retain
their existing inactive state; production and testing were not changed.

The separate `graphmine-devlopment-backend-model.timer` is enabled for 03:15 local
time daily, plus up to 15 minutes of randomized delay. It retrains offline on CPU
from development's recorded data and launches no benchmarks. The existing
production timer is unchanged. See [startup evidence](../validation/runnable-problems/development-startup.json)
and [schedule evidence](../validation/runnable-problems/development-schedule.json).

## Development live selection, 2026-11-25

Development now uses `GRAPHMINE_BACKEND_SELECTION=bandit` with the explicitly
authorized `GRAPHMINE_BACKEND_REQUIRE_ROLLOUT_EVIDENCE=false` override. Production
and testing configuration entries were compared and left unchanged. The nightly
trainer reads the development store; live application choices with valid
propensities, matching implementation provenance and benchmark cost scales are
eligible for its clipped inverse-propensity objective.

A real supervised worker loaded the configured shared model, admitted `cpp`,
`tot` and `wetric`, chose `cpp` and executed it successfully in 0.2631 seconds,
returning the independently known count of four triangles. Its exact logged
selection probability was one because exploration was disabled for the unmeasured
input range. The worker recorded the runtime, cost scale and terminal outcome
without changing model weights. This verification is marked evaluation-only and
excluded from training. See [the execution record](../validation/runnable-problems/development-live-bandit.json).

All 26 shared-policy tests passed, including feedback changing learned weights,
clipped probability correction, shadow exclusion, eligibility masking, explicit
requests, daily-budget concurrency, hard timeouts and the single fallback attempt.
The development web services remain in their existing stopped state; their next
launch uses the live selector configuration.

## Parameter-free model, 2026-11-25

The encoder now uses graph features, problem identity, hardware state and the
isolated-run flag, with missing indicators for aggregate measurements. Numeric,
boolean, categorical, collection-size and missing-value features derived from
parameters are all excluded. The schema shrank from 875 to 112 columns. Nine
columns vary in the existing paired training data, yielding a 9→64→32→38 network
with 3,974 learned weights and biases. The output remains one shared backend
preference layer. Model schema 2 validates the exact permitted feature list and
rejects schema-1 artifacts, including the previously active model.

Version `20261125t055931.857267z-20452552d0f7` was trained for 2,000 epochs using the
same 192 measurements, 52 training comparisons and three held-out graphs. It is
published as development's current model with live `bandit` selection retained.
The mean held-out runtime ratio remains 1.0047; median, p90 and p99 are 1.0,
with zero measured failures or timeouts. These are the same small triangle-only
test cases, so this does not establish broader performance equivalence. Full
results are in [the new model metadata](../validation/runnable-problems/shared-policy-no-parameters.json)
and [the before/after summary](../validation/runnable-problems/no-parameter-features-summary.json).

All 108 targeted policy, telemetry, feasibility and benchmark tests passed; one
optional GPU telemetry test was skipped. Two additional real supervised worker
checks admitted all three triangle backends and executed the NN's selected `cpp`
backend. Count mode returned four triangles; enumeration with `result_limit=2`
returned the same total count and exactly two groups. The loaded model produced
identical 32-dimensional contexts and backend scores when only parameters changed.
These verification rows are evaluation-only and cannot enter training.

Parameters remain in native requests, feasibility/memory checks, telemetry,
benchmark grouping and empirical timeout/exploration controls. Consequently,
parameter changes can still affect eligibility or sampling allowance while the
NN scores remain parameter-independent. Nightly retraining uses the new schema.

## Execution limits follow-up (2026-11-25)

Development now uses 21,600 seconds (six hours) for backend attempts, workflows
and account calculations. Benchmark timings no longer shorten attempts. Fixed
input byte caps are disabled, including the native parser's 64 MiB ceiling;
memory admission, storage quotas and configured source row budgets remain.

The verified runtime was rebuilt with the previous development build's Ada CUDA
targets. A fresh paired collection completed all 192 measurements on 16 synthetic
graphs. Model `20261125t070655.721137z-7f48923fc36a` retains the shared NN, schema 2,
112 raw features, nine varying features and no parameter features. On the three
held-out graphs, its mean selected/oracle runtime ratio is 1.007157; median, p90
and p99 are 1.0, with no measured failures or timeouts. This remains a triangle-only
K=3 evaluation. Development retains its requested live `bandit` configuration.

All 1,958 agent cases passed across the completed regression batches; 55 optional
checks were skipped. Native and frontend checks passed. Two actual supervised
worker runs used the current NN, returned the correct count/enumeration results,
and logged the six-hour allowance. Production/testing configuration is unchanged.
Development web services were already stopped; the configuration applies on their
next start. See the [execution-limit validation report](../validation/execution-limits-20261125/README.md)
for exact build options, model metadata, test reports and retained diagnostics.
