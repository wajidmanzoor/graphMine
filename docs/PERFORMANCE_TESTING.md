# GraphMine performance testing

The suite measures complete HTTP journeys against the real Yelp source, model
server and native runtime. It starts a separate GraphMine API on loopback port
18003, using an exclusively synthetic store. It does not change production
accounts, application capacity, prompts, model weights or adapter defaults.
The model, GPUs, databases and host are shared, so their system measurements
include other activity. Run during an agreed lab window.

## Install and prepare

Use the same revision, native runtime and Python application environment as the
system being measured. Install the free load-generator dependencies separately:

```sh
python3 -m venv .venv-perf
.venv-perf/bin/pip install -e 'agent[databases,test]' -r perf/requirements.txt
```

Create a **private, mode 0600 JSON file outside Git** containing the installed
application's `GRAPHMINE_*` environment settings (or an object with an `env`
member). Include database-source configuration, model endpoint/authentication,
native runtime repository/Python paths, GPU assignments and backend policy/model
paths. For example, the structure is `{"GRAPHMINE_LLM_BASE_URL":
"http://127.0.0.1:8001/v1", "GRAPHMINE_RUNTIME_REPOSITORY": "/srv/graphmine-runtime",
...}`; supply actual installed settings, not the ellipsis. Do not copy secrets
into a PR, terminal transcript, report or public file.

The runner takes `--app-python /path/to/installed/venv/bin/python` so the measured
application retains its installed FastAPI/uvicorn/httpx versions. The Locust and
monitor processes use `.venv-perf`. An existing user systemd vLLM service is
required (`graphmine-vllm.service` by default). Normal runs do not restart it.
`nvidia-smi`, Linux `/proc`, and access to the Yelp database are required.

## Run the tests

Define task-specific shell variables (do not repurpose HOME or CODEX_HOME):

```sh
perf_env=/absolute/path/to/private-app-env.json
perf_python=/absolute/path/to/application-venv/bin/python
perf_window='Agreed lab window, date and time'
```

An optional diagnostic sends one concept and one densest-subgraph question. It is
marked **PREFLIGHT ONLY** and does not count as the required benchmark:

```sh
.venv-perf/bin/python perf/run.py benchmark --label preflight --preflight \
  --app-env "$perf_env" --app-python "$perf_python" --lab-window "$perf_window"
```

The five full shapes are:

```sh
# One user; each of the six questions five times, sequentially (30 total).
.venv-perf/bin/python perf/run.py benchmark --label baseline-benchmark \
  --app-env "$perf_env" --app-python "$perf_python" --lab-window "$perf_window"

# Ten users; ramp over 60 seconds, 20-minute generation schedule.
.venv-perf/bin/python perf/run.py load --label baseline-load \
  --app-env "$perf_env" --app-python "$perf_python" --lab-window "$perf_window"

# Only after a separately agreed stress window: 5, 10, ... 50 users, 5 min/level.
.venv-perf/bin/python perf/run.py stress --label capacity \
  --app-env "$perf_env" --app-python "$perf_python" --lab-window "$perf_window" \
  --confirm-shared-gpu

# Only after a separately agreed spike window: asleep/30 min idle, 20 users/10 s.
.venv-perf/bin/python perf/run.py spike --label cold \
  --app-env "$perf_env" --app-python "$perf_python" --lab-window "$perf_window"

# Only after a separately agreed soak window: 5 users, 2 hours.
.venv-perf/bin/python perf/run.py soak --label endurance \
  --app-env "$perf_env" --app-python "$perf_python" --lab-window "$perf_window" \
  --confirm-shared-gpu
```

**Shared-GPU rule:** agree the time with the lab before every real run. Stress
and soak additionally refuse to start without `--confirm-shared-gpu`. A benchmark
or load approval does not authorize stress, spike, soak or the five-row matrix.
This PR's requested execution is one full benchmark and one 10-user load run.

Load, spike and soak stop *starting* work at the scheduled time, then allow up to
40 minutes for existing questions to drain. This avoids hiding slow questions by
cancelling them at the boundary. Reports record both the generation schedule and
the final completion time. There are 20–60-second think times and three questions
per conversation; benchmark has no think delay. Stress stops after 50 users have
run for five minutes, or when the trailing 60-second question error rate remains
above 20% for 120 seconds. No observations means no calculated error rate.
Use one Locust process; distributed workers would reuse account assignments.

All requests go through the HTTP API. The driver uses the Yelp source's published
default query and the General graph analysis domain. `--source-id` and `--query`
can explicitly select another Yelp projection, and are recorded in config. It
does not use expected operations to force routing. It selects the first offered
option and sends the question's canned clarification. Expected operations only
score the resulting plan. A documentation answer needs no calculation. Collection
results open up to three available items; scalar results do not invent indices.

## Accounts, quotas and cleanup

`run.py` creates `perftest01` through `perftest50` and one synthetic administrator.
Their random passwords and tokens are kept only in a 0700 `private` directory,
in 0600 files. The disposable application retains production concurrency,
timeouts, storage limits and scheduling; only daily job/token quotas are raised
in the isolated store. Never point the load generator at real users' accounts.

Provisioning and cleanup can also be invoked explicitly with the prepared run's
private application environment. Provisioning refuses an existing data store:

```sh
PYTHONPATH=agent "$perf_python" perf/accounts.py create /absolute/path/to/run
.venv-perf/bin/python perf/accounts.py cleanup /absolute/path/to/run
```

For manual provisioning, prepare `<run>/private/app-env.json` with
`GRAPHMINE_AGENT_DATA_ROOT=<run>/private/data`, an external
`GRAPHMINE_BACKUP_DIR=<run>/private/backups`, and
`GRAPHMINE_BACKEND_DATA_DIR=$HOME/.local/share/graphmine-perf/<run-directory-name>`;
the runner prepares these automatically. Use a new unique run directory.

The installed backend policy and trained models are retained. The existing
backend telemetry and exploration-budget history are copied to the owned external
backend directory, because the application's storage rules reject telemetry
inside its repository. New test attempts cannot modify the live training ledger.

On completion or a caught failure, the runner stops load generation, requests
sleep through the admin API, stops its monitor/API, then deletes every synthetic
account, session, file, capture, backup and owned backend copy. It retains timing
logs and a `cleanup.json` receipt. Cleanup refuses a live owned API process,
foreign accounts, a mismatched ownership manifest or a symlinked store. If a
process does not stop, the run reports the failure and preserves data for repair.
After an abrupt machine/process kill, stop the identified test processes, then
run cleanup explicitly. Never delete or stop production stores/processes to
resolve a test cleanup failure.

## Instrumentation and settings

`GRAPHMINE_PERF_LOG=1` enables JSONL events; default is off. Default output is
`var/perf/events-YYYYMMDD.jsonl` in UTC; `GRAPHMINE_PERF_DIR` overrides it. The
runner sets a run-local server directory and merges it into `events.jsonl` after
shutdown. Off means no performance file I/O, no added response header and no
provider payload change. Request IDs are enabled with instrumentation, accepted
from a bounded safe `X-Request-ID` or generated, and returned in that header.
`X-Perf-Run-ID` joins a load run. Events always contain `ts`, `event`, `request_id`,
`turn_id`, `workflow_id`, `user_id`, `session_id` and `run_id`; unavailable or
inapplicable IDs are null (for example an unauthenticated request has no user).

| Event | Measurements |
| --- | --- |
| `http` | method, route template, status, duration_ms, response_bytes |
| `turn_start`, `turn_end` | mode, outcome, error_code, total_ms |
| `model_queue` | stage, wait_ms, granted/timeout |
| `model_call` | stage, model alias, duration_ms, time_to_first_token_ms, prompt/completion/reasoning_tokens, retries, validation_failed, thinking |
| `llm_wake`, `llm_sleep` | duration_ms, request/idle/admin trigger |
| `job_queue` | wait_ms, started/queue_timeout/queue_full |
| `job_run` | operation, device, input_vertices, input_edges, duration_ms, outcome, peak_gpu_mb |
| `result_view` | profile, duration_ms, response_bytes, vertices, edges |
| `exploration_save` | actual request payload_bytes, duration_ms, outcome |
| `db` | operation keyword, duration_ms, lock_wait_ms, only calls over 50 ms |
| `error` | error_code, where, message |

TTFT observes the first streamed reasoning/content delta. Non-streamed calls have
no client-observable TTFT. Token counts reuse provider usage, including reasoning
details when returned; the suite never tokenizes again or estimates missing
reasoning counts. Model time excludes queue/token-reservation time. Native job
measurements reuse existing per-attempt telemetry, including failures/fallbacks.
Classic worker timing reuses its existing execution measurement and includes
input preparation/loading. Peak GPU memory is null when not available.

Slow SQLite statements/cursor calls and explicit commits are timed. Known
application RLock acquisition and BEGIN IMMEDIATE/EXCLUSIVE acquisition times
are recorded as lock waits. Other SQLite busy time cannot be separated from
statement execution, so `lock_wait_ms` is null for those calls. Slow-call lock
percentiles describe recorded calls, not all fast database operations. SQL,
parameters, prompts, passwords and bearer credentials are not recorded by perf.
Error messages and local paths may still be operationally sensitive; review logs
before publishing. Logging failures must not fail application work.

`GET /api/admin/perf/snapshot` requires an administrator and reports model/job
waiting and running counts, active authenticated login sessions, and planning
leases. The monitor samples this, `/metrics`, both GPUs, host CPU/RAM/swap/disk
and agent/vLLM process RSS every two seconds. Sampling failures are recorded as
missing data, never substituted with zero. Process-tree RSS can count shared
pages twice. Prometheus histogram deltas and counter resets remain explicit.

The only new model/capacity controls have defaults matching existing behavior:

| Setting | Default | Optional experiment |
| --- | --- | --- |
| `GRAPHMINE_MODEL_QUEUE_SECONDS` | `60` | `180` |
| `GRAPHMINE_LLM_THINKING_STAGES` | unset, preserve existing payloads | `analyst` disables thinking on every other stage |
| `GRAPHMINE_PERF_LOG` | `0` | `1` enables observations |
| `GRAPHMINE_PERF_DIR` | repository `var/perf` | run-local output |

Allowed thinking-stage names are family, problem, route, clarify, candidates,
plan and analyst. An empty explicit list disables thinking everywhere. Included
stages preserve their existing behavior; they are not forced to enable thinking.

## Read and compare reports

```sh
.venv-perf/bin/python perf/report.py var/perf/RUN
.venv-perf/bin/python perf/report.py var/perf/NEW --compare var/perf/BASELINE
```

`report.md`, standalone `report.html` (vendored Vega/Vega-Lite/Vega-Embed and
licenses, no CDN), and `summary.json` are generated. Open HTML locally for the
stacked timing split, model queues/cache/token rates and system time series.
All eleven requested report sections are present. Non-stress/non-soak runs say
those analyses are inapplicable. The timing split is joined by user/turn/workflow
and spans question sent through opening results; its residual includes wake,
polling, bookkeeping and any overlap. Negative residuals are not hidden.

Percentiles use nearest observed ranks. N/A means missing measurement, not zero.
Failed/cancelled questions count in the error rate and are excluded from final
answer latency. Busy and wrong-operation percentages use all question attempts;
routing coverage is shown. Server errors may be recovered or duplicate client
HTTP failures, so the report separates those counts. Flags quote the measured
threshold evidence and suggest investigations, not automatic capacity changes.
Soak slope extrapolations are labelled as such. Compare shows every headline
metric, percentage change and green/red assessment; exposure counts are neutral
and a zero baseline yields an undefined percentage. Different shapes, projections
or shared activity are not controlled comparisons.

Before each run `config.json` records commit/dirty state, resolved capacity
settings, original baseline, isolated quota overrides, model/adapter aliases,
redacted vLLM command, GPUs, free RAM and application package versions.
`steps.jsonl`, `questions.jsonl`, `events.jsonl`, `system.jsonl`, `shape.jsonl`,
`datasets.jsonl` and `run-events.jsonl` retain the observed evidence.

## Configuration matrix (a later scheduled experiment)

`perf/matrix.yaml` defines baseline, concurrency 8, routing thinking off, both,
and model queue 180 seconds. The matrix restarts vLLM between rows and starts a
fresh disposable API/store for each load test. This **restarts the shared model
service**, so schedule a window that permits those restarts. It verifies health
before each row, restores the original environment bytes/settings even after a
caught failure, restarts to the original configuration and requests sleep using
the app's cross-process power leases. SIGINT/SIGTERM restore; SIGKILL/power loss
cannot run cleanup, so a private original environment backup remains for recovery.

```sh
.venv-perf/bin/python perf/run.py load --matrix --label next-iteration \
  --app-env "$perf_env" --app-python "$perf_python" --lab-window "$perf_window" \
  --vllm-env-file /absolute/path/to/the/actual/model.env
```

The specified environment file must be the one sourced by the configured vLLM
service. `deploy/start-vllm.sh` already supports `GRAPHMINE_LLM_MAX_NUM_SEQS`.
Per-row reports compare against baseline; the matrix directory also gets one
combined comparison report. No matrix row changes the committed defaults.

## Tests

```sh
PYTHONPATH=.:agent:python/graphmine .venv-perf/bin/python -m pytest perf/tests -q
PYTHONPATH=agent:python/graphmine "$perf_python" -m pytest agent/tests/test_perf.py -q
```

Use the repository's test environment when the production environment does not
include pytest, and set its installed native runtime paths for broader analytics
regressions. Tests cover disabled logging, correlated concurrent events,
streaming/provider usage, admin-only snapshots, SQLite lock contention, protocol
choices/clarification/results, private-store cleanup guards, failed-run validation,
environment restoration, and fixture reports triggering all ten flags.
