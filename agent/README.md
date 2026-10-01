# GraphMine intelligent agent

This service turns the validated GraphMine library into a private-LAN research
system. A browser sends domain-specific questions and files to FastAPI. One
local Qwen model performs two constrained roles—planning and analysis—while a
deterministic orchestrator is the only component allowed to launch the
precompiled GraphMine CLI.

## Runtime architecture

```text
Browser on System A
  └─ HTTP/WebSocket ──> FastAPI on GPU server
                         ├─ planner skill ──> Qwen on LLM GPU
                         ├─ validated job queue ──> GraphMine on compute GPU
                         ├─ analyst skill ──> same Qwen instance
                         └─ SQLite metadata + isolated job/file workspaces
```

The model never emits or executes shell commands. It returns an
`ExecutionPlan` JSON object. The orchestrator verifies the selected problem,
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
2. Upload a canonical graph JSON or an edge list. Auxiliary query graphs,
   motifs, dynamic updates, and bipartitions have explicit roles.
3. Ask a natural-language question. The planner retrieves the compact routing
   catalog, selects one formal problem, then retrieves only that operation's
   detailed contract.
4. Validate and queue the plan. A single worker serializes jobs on the
   dedicated GraphMine GPU.
5. Validate and summarize the structured result. The analyst explains it and
   returns a schema-constrained visualization specification.
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
cp agent/.env.example agent/.env
# Edit the token, origins, and GPU UUIDs.

deploy/start-vllm.sh   # terminal/service 1, dedicated LLM GPU
deploy/start-agent.sh  # terminal/service 2, dedicated GraphMine GPU
```

The supplied vLLM launcher uses a 32K context window and caps concurrency at 64
sequences. Qwen3.8's hybrid attention/Mamba cache must reserve a cache block for
every active sequence, so this explicit cap avoids an unsafe vLLM default on a
48 GB card. Override `GRAPHMINE_LLM_MAX_MODEL_LEN`,
`GRAPHMINE_LLM_MAX_NUM_SEQS`, or
`GRAPHMINE_LLM_GPU_MEMORY_UTILIZATION` only after measuring the target host.
Catalog routing is a bounded classification with hidden reasoning disabled,
while execution-plan construction and result analysis use medium effort. Their
separate effort and completion-token limits are configurable through the
`GRAPHMINE_LLM_*_REASONING_EFFORT` and `GRAPHMINE_LLM_*_MAX_TOKENS` settings
shown in `.env.example`.

Open `http://SERVER_LAN_IP:8000` from System A. If an API token is configured,
enter it through the gear button. The bundled frontend has no CDN dependency.
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
| `GET /api/domains` | Domain profiles shown before session creation |
| `POST /api/sessions` | Create a domain-bound research session |
| `POST /api/sessions/{id}/files` | Upload and normalize a graph or auxiliary input |
| `POST /api/sessions/{id}/plan` | Produce but do not execute a constrained plan |
| `POST /api/sessions/{id}/chat` | Plan/run or interpret a follow-up |
| `POST /api/jobs` | Queue an already structured, validated plan |
| `GET /api/jobs/{id}` | Read durable job state |
| `GET /api/results/{id}` | Read result, interpretation, and visualization plan |
| `GET /api/results/{id}/query` | Page through a bounded path in a large result |
| `WS /api/sessions/{id}/events/ws` | Stream queued/running/interpreting/completed state |

Public request/response JSON Schemas are committed under `agent/schemas` and
can be regenerated with `graphmine-agent export-schemas`.

## Domain-aware model evaluation

`evaluation/domain_query_cases.json` contains separate future-training seeds
and held-out routing cases. Both are stratified across all nine domains and all
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

## Storage and recovery

Metadata is stored in SQLite with WAL enabled. Bulk inputs, canonical graphs,
commands, logs, and result files live below the configured data root. Every
file and job has an isolated directory. Paths are resolved and checked against
the owning session/job root before use. Queued jobs survive a restart; jobs
interrupted during execution are marked failed rather than silently retried.

## GPU policy

Use UUIDs rather than device indexes. Each process receives one UUID through
`CUDA_VISIBLE_DEVICES`, so its assigned physical GPU appears internally as
device `0`. The initial production model is `Qwen/Qwen3.8-27B-FP8`, served by
vLLM with tensor parallelism 1, a 32K context, and prefix caching. Planning and
analysis are prompts/schemas on the same loaded model, not separate models.

Backend/configuration optimization is deliberately outside the current
correctness boundary. `auto` currently delegates to the native operation's
fixed correctness-aware choice. Later benchmark data can train a separate
selector stratified by domain, graph features, hardware, and operation; its
choice must still pass the same deterministic validator.
