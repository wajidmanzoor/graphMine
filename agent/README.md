# GraphMine intelligent agent

The [2026-10-04 catalog expansion](../docs/ALGORITHM_EXPANSION.md) adds all 37
problem definitions and five executable profiles (18 operations total). Expanded
routing uses the base model with explicit profile contracts; no retraining is
required by this integration. The local LLM was offline during validation, so
new natural-language accuracy is not yet measured.

This service turns the validated GraphMine library into a private-LAN research
system. A browser sends domain-specific questions and files to FastAPI. One
local Qwen deployment performs constrained routing, planning and analysis while a
deterministic orchestrator is the only component allowed to launch the
precompiled GraphMine CLI.

## User-testing pilot: business-v1-pilot.1

The GPU-host deployment is available at **http://10.33.76.25:18000** on its
private network, or **http://100.102.13.108:18000** through its existing Tailscale
connection. On the GPU host itself, use http://127.0.0.1:18000. Access uses the
existing API token: open the gear icon, enter the token, and choose **Save and
reconnect**. Leave API base URL empty when using this same-host browser UI. The
server owner can retrieve `GRAPHMINE_API_TOKEN` from the existing `agent/.env`.

This is a shared research workspace using the existing shared token; it does
not provide separate user accounts or private per-tester sessions. Give access
to the intended pilot group. The starting screen explains that conversations,
uploads, results and feedback are retained for review.

### First end-to-end test

1. Enter an optional **Session name** and **Tester alias**, then choose a domain.
   Use a stable alias rather than a real person's name when organizing trials.
2. Upload your relationship CSV or graph JSON. To try the app immediately, use
   **Download example team data** in the sidebar, then upload the downloaded CSV
   as **Main graph**. Leave **Directed** unchecked for this sample.
3. Ask an application question. For the supplied example:

   > We are planning small working groups. Find every full circle of coworkers
   > where everyone has a recorded collaboration with every other member. Keep
   > each circle at its fullest size, list the names, and describe what the
   > recorded links show.

4. Leave **Run analysis** checked to execute the validated plan. Uncheck it if
   you only want a plan preview. The activity sidebar shows request interpretation,
   plan validation, computation and answer preparation as those stages run.
   Expand **Model reasoning**, then a recorded stage, to read Qwen's reasoning
   text when that stage returns it. It appears after the stage finishes; the
   routing adapter itself runs with thinking disabled and emits no such text.
5. Click **Open results & visualizations** on the answer, or the **Results** tab.
   Results occupy their own full-width page. **Saved analyses** selects an earlier
   result. Explore the network, inspect member tables, filter rows, and use
   **Raw JSON** when you need the underlying output.
6. Use **Back to chat** for follow-up questions. **Explore next** actions can open
   a related view or return to chat with the selected follow-up question.
7. Use **Review this answer** on Results or **Give feedback** below a chat answer
   to annotate that specific result/turn. The sidebar's **Leave feedback** button
   targets the latest chat turn. Choose a feedback type, write a note, and add an
   expected answer or rating if relevant. **Corrected answer** requires the expected
   answer; **Rating** requires a score from 1 to 5.
8. **Change domain / new session** returns to the starting screen. Choose a saved
   conversation under **Continue a conversation** to resume. Reloading a chat or
   result URL restores that session; a new session starts without the previous
   session's files, messages or results.

### Commands in the browser chat

Both `/` and `\` prefixes work, including `\feedback`. These commands are
handled by the application before model dispatch. They are saved in history,
excluded from current and future model prompts, and do not launch computations.

| Command | What it saves or does | Example |
| --- | --- | --- |
| `/feedback NOTE` | An issue or observation attached to the last request | `/feedback The answer needs clearer names` |
| `/feedback NOTE \| EXPECTED` | An issue plus the expected behavior | `/feedback Missing names \| Show each coworker's name` |
| `/correct ANSWER` | A proposed correction for later review | `/correct The group should include Maya, Noah and Leah` |
| `/rate 1–5 [NOTE]` | A rating and optional explanation | `/rate 4 Useful, but the explanation is too technical` |
| `/note NOTE` | A research observation | `/note The tester understood the table before the network` |
| `/export` | Downloads this session's complete evidence archive | `/export` |
| `/status` | Shows the deployed model version and stage assignments | `/status` |
| `/help` | Lists the local commands | `/help` |

Feedback and corrections annotate the saved conversation; they do not edit an
answer, rerun a query, or immediately train the model. Unknown prefixed commands
also stay out of the model and return local help. Use the answer-specific buttons
when reviewing an older answer instead of the latest request.

### Collecting useful improvement data

- **Download session archive** (or `/export`) saves a ZIP with the conversation,
  uploaded files, normalized inputs, plans, raw model requests/responses, native
  outputs, activity records and annotations. Keep this when reproducing an issue.
- **Export feedback for review** saves JSONL with one row per annotation. Each
  row contains its category, optional rating/correction, session/turn/result links,
  tester alias, deployed model identity, and a snapshot of the conversation at
  annotation time. File IDs link back to the accompanying session archive.
- **Download report** on Results saves an interactive HTML report that opens
  without a running server or an external CDN.

Records are marked `unreviewed` and `automatically_used_for_training: false`.
Review, redact and validate them before making a training dataset; a user's
correction is useful evidence, not automatically a correct target answer.
Automated acceptance checks use `source: assistant_evaluation` and the
`assistant-acceptance` alias, distinct from feedback collected from actual users.
The authoritative live store remains `.graphmine-v1/agent.sqlite3` with evidence
under `.graphmine-v1/history/<session_id>/`. No original sessions were moved.

### What changed and why

| Addition | Purpose |
| --- | --- |
| Business routing adapter with a visible version | Test the trained candidate and connect feedback to the actual deployment |
| Activity sidebar and expandable Qwen reasoning | Follow decisions and progress, and inspect reasoning text actually returned by the local model |
| Separate Results page and saved-result URLs | Give tables and networks enough room and make results easy to reopen |
| Feedback form and local commands | Capture issues, corrections, ratings and notes without influencing model prompts |
| Session restoration, tester aliases and exports | Support repeatable user trials and later review |
| Downloadable sample data and offline reports | Make the first trial easy and let reviewers inspect evidence independently |

The activity feed contains concise decision summaries and execution evidence.
Its separate **Model reasoning** section displays the local Qwen model's recorded
reasoning verbatim when available. This unverified model text does not certify
that a decision is correct and is separate from computed answer facts. Model
input prompts are not exposed by that display. For the historical 20-problem pilot, the business adapter handles
**analysis selection only**; planning and
answer writing use the existing FP8 model. The adapter runs in the same NF4
configuration as the controlled comparison and its weight fingerprint is checked
at startup and by the application. It never silently falls back on adapter failure. The expanded catalog explicitly
selects the base router because the frozen adapter was evaluated on the earlier
contract; status metadata reports that choice.

Known pilot limitation: some requests for every exact-size account group can be
incorrectly refused after the adapter chooses a different grouping operation.
Please record the complete question and expected behavior when this happens.
The reviewed routing score improved from 113/124 to 118/124, but overall
end-to-end improvement has not been established. The router shares the compute
GPU with native jobs; large-graph capacity and multi-user load are not certified
by the small acceptance checks. Further fine-tuning and the old evaluation queue
remain stopped.

See [pilot operations and rollback](../deploy/README.md#business-adapter-user-testing-pilot)
and the [progress record](evaluation/FINETUNING_PROGRESS.md).

## Runtime architecture

For terminal use, run `deploy/chat.sh` from the repository root. The
[conversational CLI guide](CLI.md) covers uploads, session resume, `/feedback`,
local history, and the live application-language evaluation.

Use `graphmine-agent learning --help` for seeded synthetic graphs, independent
native-result audits, held-out live evaluation, and gated training-candidate
exports. See the [learning workflow](CLI.md#synthetic-data-and-learning-candidates)
and [next-phase findings](IMPROVEMENT_PLAN.md#automated-data-checkpoint--2026-10-03-utc).
No model training or external teacher calls are enabled automatically.

```text
Browser on System A
  └─ HTTP/WebSocket ──> FastAPI on GPU server
                         ├─ optional business routing adapter ──> local NF4 endpoint
                         ├─ planner skill ──> Qwen on LLM GPU
                         ├─ validated job queue ──> GraphMine on compute GPU
                         ├─ analyst skill ──> same Qwen instance
                         └─ SQLite metadata + isolated job/file workspaces
```

The model never emits or executes shell commands. It returns a typed intent and
`PlanDraft` (`ready`, `needs_information`, or `unsupported`); only a ready draft
can become an `ExecutionPlan`. The orchestrator verifies the selected problem,
operation, compiled backend, semantic parameters, optional outputs, auxiliary
file roles, session ownership, paths, and limits before constructing an
argument vector. The CLI is executed without a shell.

## Domain-first workflow

Each session starts with one of nine domain profiles: general graph analysis,
fraud, bioinformatics, cybersecurity, social networks, recommendation and
e-commerce, knowledge graphs, communications/infrastructure, or
transportation/mobility. The profile contributes vocabulary, common research
questions, relevant formal problems, and visualization preferences. It cannot
change a problem definition or make an unsupported problem runnable.

The request lifecycle is:

1. Choose a domain and create a session.
2. Upload canonical graph JSON, attributed relationship CSV, or a text edge list.
   Original names and attributes are retained. CSV columns and timestamp units
   can be mapped explicitly. Supporting files have explicit roles; unambiguous
   customer/product partitions can be derived from typed records.
3. Ask a natural-language question. The planner receives bounded graph context,
   can inspect selected records, and selects a primary computation plus up to
   three independent supporting computations. Detailed generation schemas use
   only the selected operation's executable contract.
4. Validate all steps before queueing any. Filters produce a recorded projection
   without changing the original graph. A single worker serializes jobs on the
   configured GraphMine GPU (shared with the routing adapter in the user pilot).
5. Join results to original records and materialize deterministic answer facts.
   The analyst selects facts and tested views; model implications are separated
   from verified findings. Each result saves an offline interactive HTML report.
6. Explore the generated view or ask a follow-up. Interpretation-only
   follow-ups reuse the current result; computation-changing requests return
   to the planner.

## Install and run

Build the CLI once, then install the service:

```bash
cmake -S library -B library/build -DCMAKE_BUILD_TYPE=Release
cmake --build library/build --parallel --target graphmine_cli

python3 -m venv .venv
.venv/bin/pip install -e 'agent[test]'
deploy/setup-vllm.sh
deploy/configure-v1.sh --origin http://GPU_SERVER_LAN_IP:8000

deploy/start-vllm.sh   # terminal/service 1, dedicated LLM GPU
deploy/start-agent.sh  # terminal/service 2, dedicated GraphMine GPU
```

The generated `agent/.env` uses stable GPU UUIDs, creates a random 256-bit API
token with mode `0600`, and points `auto` execution at the checked-in,
correctness-gated backend policy. Use `--port` when port 8000 is already in
use. The file is ignored by Git.

The supplied vLLM launcher uses a 32K context window and caps concurrency at 64
sequences. Qwen3.8's hybrid attention/Mamba cache must reserve a cache block for
every active sequence, so this explicit cap avoids an unsafe vLLM default on a
48 GB card. Override `GRAPHMINE_LLM_MAX_MODEL_LEN`,
`GRAPHMINE_LLM_MAX_NUM_SEQS`, or
`GRAPHMINE_LLM_GPU_MEMORY_UTILIZATION` only after measuring the target host.
Catalog routing is a bounded classification with reasoning disabled by default.
Plan construction defaults to medium effort; the domain-first evaluation also
tests `none`. Verified-fact/view selection uses `none`, since arithmetic and
source joins are performed by the application. Configurable stage limits use the
`GRAPHMINE_LLM_*_REASONING_EFFORT` and `GRAPHMINE_LLM_*_MAX_TOKENS` settings
shown in `.env.example`.

Open `http://SERVER_LAN_IP:8000` from System A. If an API token is configured,
enter it through the gear button. The bundled frontend has no CDN dependency.
Its editable source is `graphmine_agent/static/index.html`,
`graphmine_agent/static/app.js`, and `graphmine_agent/static/styles.css`; these
files are packaged with the Python service and served from `/` by FastAPI.
The pinned Cytoscape distribution is bundled under `static/vendor`, including its
license. To rebuild that bundle, run `npm ci && npm run build` in `agent/frontend`.
The browser carries WebSocket credentials in an encoded subprotocol header, so
the token is not copied into access-log URLs. Plain HTTP still exposes traffic
to other devices able to observe the network; use a trusted LAN or terminate
TLS at a reverse proxy when the network is not fully trusted.

The pinned vLLM wheel uses CUDA 13.0. If the host driver exposes only CUDA
12.x, `setup-vllm.sh` installs NVIDIA's signed, checksum-verified forward-
compatibility userspace into the repository (without changing the kernel
driver or requiring root). A native driver upgrade remains the preferred
long-term deployment when administrator access is available.

For deterministic development or API tests without loading the model:

```bash
GRAPHMINE_LLM_ENABLED=false .venv/bin/graphmine-agent serve
```

For a persistent server, the supplied systemd units expect the prepared
repository at `/opt/graphmine`, a `graphmine` service account, and the edited
environment file at `/etc/graphmine/graphmine.env`:

```bash
sudo install -m 0644 deploy/graphmine-vllm.service deploy/graphmine-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now graphmine-vllm.service graphmine-agent.service
sudo systemctl status graphmine-vllm.service graphmine-agent.service
```

The API unit orders itself after and pulls in the vLLM unit. Readiness remains
`degraded` until model loading finishes; use authenticated `GET /api/health`
as the deployment readiness probe.

## API surface

FastAPI publishes OpenAPI at `/docs` and these principal routes:

| Route | Purpose |
|---|---|
| `GET /api/health` | Versioned readiness for Qwen, GraphMine, GPU, and policy |
| `GET /api/capabilities` | Compiled backend and selector-policy inventory |
| `GET /api/metrics` | Authenticated durable-state and worker counters |
| `GET /api/domains` | Domain profiles shown before session creation |
| `POST /api/sessions` | Create a domain-bound research session |
| `POST /api/sessions/{id}/files` | Upload and normalize a graph or auxiliary input |
| `POST /api/sessions/{id}/plan` | Produce but do not execute a constrained plan |
| `POST /api/sessions/{id}/chat` | Plan/run or interpret a follow-up |
| `POST /api/jobs` | Queue an already structured, validated plan |
| `GET /api/jobs/{id}` | Read durable job state |
| `GET /api/results/{id}` | Read result, interpretation, and visualization plan |
| `GET /api/results/{id}/query` | Page through a bounded path in a large result |
| `GET /api/results/{id}/report` | Download a self-contained interactive answer |
| `POST /api/sessions/{id}/feedback` | Save what went wrong and expected behavior |
| `GET /api/sessions/{id}/history` | Inspect saved trace/artifact inventory |
| `WS /api/sessions/{id}/events/ws` | Stream queued/running/interpreting/completed state |

Public request/response JSON Schemas are committed under `agent/schemas` and
can be regenerated with `graphmine-agent export-schemas`.

## Domain-aware model evaluation

`evaluation/domain_query_cases.json` contains separate future-training seeds
and held-out routing cases. Both are stratified across the original nine domains and
13 operations; held-out cases must never be included in fine-tuning. Evaluate
the configured Qwen endpoint with:

```bash
.venv/bin/graphmine-agent evaluate-routing \
  --split held_out_evaluation \
  --output routing-report.json

.venv/bin/graphmine-agent evaluate-planning \
  --split held_out_evaluation \
  --concurrency 2 \
  --output planning-report.json
```

The routing report checks formal problem/operation selection. The planning
report then fixes that operation and checks exact parameters, optional outputs,
auxiliary-file roles, missing inputs, and the backend allowlist through the
same validator used by the API. Both reports include corpus hashes, generation
settings, latency, raw constrained output, and overall/per-domain accuracy.
Use repeatable `--case-id CASE_ID` flags for focused debugging. Later training
and backend-selection experiments should always retain the domain slices, so
an aggregate score cannot hide a regression in fraud, biology, security, or
any other application area.

The checked-in Qwen baseline passed all 13 held-out routes and all 13 held-out
execution plans:

- [`evaluation/reports/qwen3.8-27b-fp8-held-out.json`](evaluation/reports/qwen3.8-27b-fp8-held-out.json)
- [`evaluation/reports/qwen3.8-27b-fp8-held-out-planning.json`](evaluation/reports/qwen3.8-27b-fp8-held-out-planning.json)

Treat this small curated set as a regression gate, not as a general
model-quality claim; expand it with paraphrases, ambiguity, unsupported
intents, adversarial requests, and multi-turn cases before fine-tuning.

The V1 matrix expands that gate to every combination of nine domains and
thirteen operations (117 supported requests), plus two paraphrases for each of
the eight deliberately unsupported formal problems and four ambiguous
requests. Run its three slices with:

```bash
.venv/bin/graphmine-agent evaluate-routing \
  --cases agent/evaluation/v1_query_cases.json \
  --split v1_matrix_evaluation --concurrency 8 \
  --output agent/evaluation/reports/qwen3.8-27b-fp8-v1-matrix-routing.json

.venv/bin/graphmine-agent evaluate-routing \
  --cases agent/evaluation/v1_query_cases.json \
  --split v1_routing_safety_evaluation --concurrency 8 \
  --output agent/evaluation/reports/qwen3.8-27b-fp8-v1-routing-safety.json

.venv/bin/graphmine-agent evaluate-planning \
  --cases agent/evaluation/v1_query_cases.json \
  --split v1_matrix_evaluation --concurrency 8 \
  --output agent/evaluation/reports/qwen3.8-27b-fp8-v1-matrix-planning.json
```

The V1 gate is exact on this curated corpus: every case in each slice must
pass, every report must carry the current corpus SHA-256, and no domain may
hide an aggregate regression. This is reproducible regression coverage for
the specified queries, not a claim about arbitrary natural language.

The GraphMine 1.0.0 release snapshot, validated on 2026-10-01 with
Qwen/Qwen3.8-27B-FP8 and two RTX 6000 Ada GPUs, passed all three gates:

- [routing](evaluation/reports/qwen3.8-27b-fp8-v1-matrix-routing.json):
  117/117 supported domain/operation cases;
- [routing safety](evaluation/reports/qwen3.8-27b-fp8-v1-routing-safety.json):
  20/20 unsupported or ambiguous cases;
- [execution planning](evaluation/reports/qwen3.8-27b-fp8-v1-matrix-planning.json):
  117/117 complete operation contracts.

All reports use corpus SHA-256
`11b3bb847f13142cc24ad34e38f2608881c9f9cecc61d6b3e159af4560928640`.

## Correctness-gated backend selection

`auto` first consults `agent/backend_policy.json`. The selector uses a coarse,
deterministic graph-feature bucket and considers only backends that are both
validated by the catalog and compiled into the current binary. It validates a
candidate against the complete plan contract before selecting it. A missing,
invalid, incompatible, or stale policy cannot expand authority: execution
falls back to the native correctness-aware `auto` path.

Regenerate the policy only from a report in which every timing record first
passed its exact-result gate:

```bash
.venv/bin/graphmine-agent benchmark benchmarks/v1-smoke.json \
  --warmups 1 --repetitions 3 \
  --output benchmark-results/v1-smoke.json
.venv/bin/graphmine-agent train-selector benchmark-results/v1-smoke.json \
  --output agent/backend_policy.json
.venv/bin/graphmine-agent evaluate-selector benchmark-results/v1-smoke.json \
  --policy agent/backend_policy.json
```

The committed smoke policy exercises the selection plumbing and supplies
conservative defaults. It is not evidence of the fastest backend on large or
structurally different graphs; use disjoint graph families for any
research-quality training/evaluation claim.

The checked-in [RTX 6000 Ada benchmark summary](../benchmarks/reports/v1-smoke-rtx6000-ada.json)
records 69/69 correctness-gated timing records, all 23 compiled backends and
the original 13 operations, plus a 14/14 in-sample selector smoke evaluation.

## Storage and recovery

Metadata is stored in SQLite with WAL enabled. Bulk inputs, canonical graphs,
commands, logs, and result files live below the configured data root. Every
file and job has an isolated directory. Paths are resolved and checked against
the owning session/job root before use. Queued jobs survive a restart; jobs
interrupted during execution are marked failed rather than silently retried.
Authenticated `GET /api/metrics` reports bounded database counts, job-status
counts, queue depth, active job IDs, and worker state without returning stored
payloads. Back up the entire data root while the API is stopped; the exact
stop/archive/restore procedure is in `deploy/README.md`.

## GPU policy

Use UUIDs rather than device indexes. Each process receives one UUID through
`CUDA_VISIBLE_DEVICES`, so its assigned physical GPU appears internally as
device `0`. The initial production model is `Qwen/Qwen3.8-27B-FP8`, served by
vLLM with tensor parallelism 1, a 32K context, and prefix caching. Planning and
analysis are prompts/schemas on the same loaded model, not separate models.

The benchmark-derived selector is an optimization inside the correctness
boundary, never a replacement for it. Explicit user backend requests remain
explicit, and the policy cannot select an uncompiled, unvalidated, or
plan-incompatible backend.
