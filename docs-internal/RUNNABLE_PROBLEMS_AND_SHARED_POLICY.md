# Runnable problems and the shared backend policy

The executable hierarchy is **Family → Runnable Problem → Backend**. Every
previous runnable identifier keeps its spelling. `catalog/problems.json` maps
each runnable problem directly to one family; native cards own its parameter,
input, output and backend contract. `catalog/topics.json` contains documentation
text only. Topics can explain distinctions such as degree, betweenness and
PageRank without becoming an executable choice.

The planner makes a family call followed by a route call. The route sees all
eligible problems in that family and documentation hints. It ranks up to three
calculations; multiple problems within a calculation are required workflow
steps. Every calculation must include a problem from the selected family.
Cross-family dependencies need explicit question evidence. An unsupported route
can reject one family and retry once. Normal-mode cards use this ranking without
another sampling call, and execution waits for the user's calculation choice.

Native protocol v2 and all new workflow steps write `problem`. Workflow readers
and the native request boundary accept the old `operation` key and reject
conflicting dual keys. Canonical validation and workflow hashes use the new key.
Existing runnable IDs, mathematical definitions and backend contracts remain
unchanged. The native protocol version rejects accidentally loading an old
library with a new binding.

The development redesign removes the old linear backend selectors and policies.
Development backend data is isolated from the shared production stores. The new
shared neural policy has one 64-unit ReLU layer, one 32-unit ReLU layer,
and one backend-score output layer. Unavailable models use native feasible
backend ordering. Memory admission remains deterministic, with no auxiliary
learned memory model. The implementation, training, logging and evaluation controls are described below.

Validation distinguishes contract tests from live model quality. The final native
build passed 61 CTest cases (15 optional integrations disabled), 178 CPU contract
and migration tests, and both ToT/WeTriC GPU triangle oracle tests. Matching CPU
admission covers all 82 runnable problems. Frontend contracts and TypeScript
checks pass. See [the evaluation report](RUNNABLE_POLICY_EVALUATION.md) for paired
measurements, routing metrics and the limits of this development validation.

## Shared model and learning

The runtime has exactly one trained artifact: `shared/<version>/model.json`,
selected by `shared/current`. Its input passes through Dense(64, ReLU),
Dense(32, ReLU), then a single Dense(B) preference layer for all known backend
IDs. There are no task heads, runtime regressors, Bayesian layers, ensembles,
or learned memory estimators. The linear encoder is an offline ablation using
the same features and preference layer; its weights are not published.

Features contain log1p vertex/edge counts, average degree, log1p maximum degree,
degree CV, log1p degeneracy, directed/weighted flags and bipartite ratio;
problem one-hot indicators; free/total CPU cores from the logged one-minute load
estimate, logical cores and log1p available RAM; physical GPU 1 utilization and
log1p available VRAM; isolated execution and missing-value indicators. GPU 0 is
reserved for the LLM. Arbitrary identifiers, free text and all problem/backend
parameters are excluded, including categorical values, collection sizes and
parameter-missing indicators. The catalog's 82 problems give 112 feature columns
before constant-column removal. Adding or changing parameters cannot expand this
schema or change the NN context/scores for otherwise identical inputs.

Shared model schema 2 enforces this parameter-free feature list and rejects older
artifacts; fitting a new artifact is required. Parameters still reach execution,
native preflight, deterministic memory admission, empirical timeout/exploration
controls and privacy-safe telemetry. Benchmark comparisons still group identical
settings. Those rules may change the eligible set or sampling allowance, even
though parameters do not enter the NN. Both the NN and offline linear comparison
use the same parameter-free representation.

The normalizer is fitted only on training graphs, stored in the artifact, and
reused at inference. Features with zero variance, including their optional
missing indicators when constant, are dropped and listed in metadata. All
repetitions, parameter settings and load regimes for a snapshot fingerprint
remain on the same side of the held-out split. Neither held-out measurements
nor evaluation-tagged traffic enter fitting or normalization.

For a complete paired row, cost is measured seconds divided by the fastest
eligible cost. The full-information objective is expected regret,
`sum_b softmax(score)_b * (cost_b - 1)`. Thus a 3x slowdown has greater loss and
gradient than a near tie. Failed choices receive a configurable penalty above
the slowest completed timing. Original wall times and outcomes remain in JSONL;
tail latency uses actual observed wall times, while the cost ratio applies the
stated failure penalty. Incomplete comparisons and all-failed rows have no
measured oracle and are excluded with counts.

Online feedback is used only during offline retraining. Its additional loss is
`mean(min(1 / behavior_probability, ipw_clip) * policy_probability(chosen) * cost)`.
Only actual bandit choices with valid behavior probabilities and matching
implementation provenance qualify. Shadow proposals never supply behavior
propensities. Training uses NumPy backpropagation and Adam; requests do not train.

## Decisions, logging and execution controls

Native preflight and conservative memory admission determine the eligible set.
Explicit backend requests are retained; explicit devices restrict the set. K=1
returns the only backend with probability one. Otherwise the policy masks its
preferences and samples softmax with temperature and an exploration floor.
Exploration is permitted only within measured n/m bounds for the problem and
parameter settings. Budget checks and sampling occur under the same daily
ledger lock, so a rejected budget produces a deterministic distribution *before*
the draw. The logged probability is always from the final distribution.

Schema 5 logs problem ID, safe parameters, aggregate graph/hardware features,
eligible IDs, choice, complete distribution, exact selection probability,
feature vector, model version, native implementation hash, UTC timestamp,
runtime/outcome and per-attempt fallback identity. Shadow choice, distribution
and probability are separate fields beside the actual native behavior.

Timeouts use a configurable multiple of the slowest completed training benchmark
in the nearest log-size bin for that problem/settings, capped by the remaining
step deadline. Without measurements a configured finite default applies. A
single fallback is allowed after timeout/OOM, with fresh admission excluding the
first backend, when at least 60 seconds remain (or no total step deadline exists).
An explicitly requested backend is never replaced. Memory admission always uses
the conservative allocation estimate and current free RAM/VRAM.

Defaults: `GRAPHMINE_BACKEND_SELECTION=native`, temperature 1, floor .02, daily
exploration fraction .10, default attempt timeout 300 s, measured timeout multiple
3, IPW clip 20 and failure penalty 10. See `agent/.env.example`. `shadow` evaluates
the shared policy while executing native ordering; `bandit` requests live use.
Without a valid artifact it falls back to native ordering. Evidence-gated live
use remains off without paired shadow evidence; an explicit development
`GRAPHMINE_BACKEND_REQUIRE_ROLLOUT_EVIDENCE=false` override is available.

## Collection and operation

`tools/benchmark_backends.py --full --benchmark-id <unique-name>` admits all
eligible backends on the same graph/settings, holds the analytics GPU lease
across the pair, randomizes backend order, and collects idle and busy CPU regimes.
The configurable warmup defaults to 65 seconds to give load-average features
signal. Each attempt has a finite benchmark deadline. A bootstrap cap never
truncates a pair. Logs retain every timing; retraining rejects pairs with changed
contexts or more than .15 free-core-fraction drift. A nominal idle label does
not replace the actual hardware measurements.

`graphmine-agent backend-model train` trains the shared NN and an offline linear
ablation, writes held-out tables, and publishes one immutable shared version.
`backend-model report` reports current held-out and observed shadow evidence;
`backend-model rollback` restores the prior shared version. The existing nightly
training timer uses the new command without launching benchmarks. Set selection
to `native` for an immediate model-free rollback. Old selector files and commands
have been removed at the user's request.

Development now uses private `environments/devlopment/backend-runs` and
`backend-models` directories. Its old history/capture/workflow files were cleared;
production's shared old models and logs were preserved. Development accounts,
uploads, and database datasets were not removed. No model-quality claim is made
until matching paired measurements and real-traffic evidence exist. Ordinary
shadow logs cannot measure an unexecuted backend's runtime.

The development environment now explicitly enables
`GRAPHMINE_BACKEND_SELECTION=bandit` and
`GRAPHMINE_BACKEND_REQUIRE_ROLLOUT_EVIDENCE=false`. An automatic request executes
the shared policy's chosen eligible backend and logs its actual runtime, outcome
and final selection probability. Explicit backend requests and K=1 retain their
deterministic behavior. The production configuration is unchanged. The existing
development web services remain stopped; subsequent launches load these settings.

For eligible scores `s`, temperature `T` and exploration floor `epsilon`, the
sampling distribution is `(1-epsilon) * softmax(s/T) + epsilon/K`. The floor is a
total uniform mixture: .02 gives each of three eligible backends at least .00667
probability when sampling is permitted. Outside the measured size/settings range,
or when the daily ledger has no exploration allowance, the highest-scoring backend
has probability one. The initial empty ledger needs ten recorded application
decisions for that problem on that day before its .10 budget allows the first
exploratory choice.

Nightly training reads genuine bandit feedback alongside paired benchmarks and
excludes evaluation rows and held-out graph fingerprints. Feedback currently
requires an empirical cost scale from the problem's benchmark controls; native,
forced-only and shadow decisions do not train the bandit. The training objective
uses observed runtime divided by that recorded scale and clipped inverse
selection probability. Only the executed backend supplies an observed outcome.
New weights are fitted offline and published atomically; a request never edits
weights. See [live execution verification](../validation/runnable-problems/development-live-bandit.json).
