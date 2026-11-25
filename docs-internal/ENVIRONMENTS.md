# Development, testing, and production

GraphMine and Dataset Studio live in this repository and move through the same
commits. The branch name `devlopment` intentionally follows the requested name.

| Branch | Purpose |
| --- | --- |
| `devlopment` | Make and commit changes here. |
| `testing` | The exact candidate currently being validated. |
| `production` | The version served to users. |
| `main` | The last successfully promoted version. |

All four branches start at the same baseline. Promotions use fast-forward
updates, preserving the exact tested commit. Existing feature history remains
available; model weights, user data, credentials, and virtual environments are
not committed.

## Installed host layout

The workspace root is `/home/wajid/projects/graphDatabaseAgent`.

| Environment | Code directory | Agent / Studio ports | Access |
| --- | --- | --- | --- |
| Production | `graphMine-production` | 18000 / 8877 | Existing public HTTPS routes |
| Development | `graphMine-database-cypher` | 18002 / 8879 | Loopback; SSH forwarding |
| Testing | `graphMine-testing` | 18001 / 8878 | Loopback; SSH forwarding |

`graphMine-runtime-20261125-full-gpu` is the detached native runtime for the
runnable-problem release, with 82 CPU problems and 58 admitted GPU profiles across
35 problems. All 59 GPU profiles are compiled; cuMBE is quarantined by the
correctness manifest after a reproducible intermittent counting failure.
Its verified binaries are copied
without rebuilding or patching them, and worker paths are relocated in the
correctness manifest. `deploy/snapshot-backend-runtime.py` verifies every copied
hash and supplies launchers that load the pinned library and the correct worker
ABI. `GRAPHMINE_WORKER_DIR` selects its `library/build/runtime/verified-workers`
for native workflows; `bin/graphmine` selects the separate classic CLI workers.
Keep the earlier `graphMine-runtime-20261121-unlimited-all` checkout and its
model directories for rollback to the previous production application.
The compiled CPU/GPU engine and execution evidence are promoted together with
the application. The existing
`graphMine-repo` checkout still supplies the analytics Python and vLLM
environments. Do not develop in these pinned checkouts or install packages into
their runtime environments. Native engine changes need a separately built and
verified runtime; changing an app branch alone does not replace native binaries.

The build reuses the unchanged Kokkos/KokkosKernels installation under
`graphMine-runtime-20261116-views/library/build/native-dependencies/` and the
existing research workers. Keep those pinned dependencies available. Build
settings, source hashes, device-specific admission and validation reports for
this runtime are recorded in `validation/full-gpu-release-20261125/`. Earlier
reports with retired family labels were removed at the user's request; their
original contents remain in Git history. This release retains the existing
algorithms, GPU adapters and optional biclique partition contract.

The runnable-problem release uses one shared neural encoder and one masked
backend policy, with no algorithm parameter features. The operator explicitly
requested enabling it and promoting through testing to production. Configuration
sets `GRAPHMINE_BACKEND_SELECTION=bandit` and
`GRAPHMINE_BACKEND_REQUIRE_ROLLOUT_EVIDENCE=false`; this override does not establish
paired shadow-traffic performance. The evaluation report records the measured
limits separately. Graph execution uses CPU and physical GPU 1 only; GPU 0
remains reserved for the existing model service. Paired collection is explicitly
requested with `benchmarks/full_gpu_policy.json`. The nightly backend-model timer
only fits saved observations; it never launches a benchmark sweep.

Execution allowances are six hours (`21600` seconds) for the backend attempt,
job and account job limit. Upload and analytics input byte limits are disabled.
Native feasibility, available-memory admission and backend-specific input
contracts still apply. User-selected backends and devices remain binding.

`GRAPHMINE_GOOGLE_SEARCH_ENABLED=false` is explicit in all three host
environments and is also the application default. The prototype is retained for
later development; see [Deferred Google search](DEFERRED_GOOGLE_SEARCH.md).

Each application environment has its own Python environment, data store,
accounts, captures, history, backups, Studio workspace, and login cookie names.
All three environments use the same five published, isolated read-query
datasets: Transfers demo, Yelp, MovieLens 32M, MovieLens Tag Genome and LDBC SNB
SF100 BI. Each environment reads the registry from its own checkout and keeps
application accounts, conversations and snapshots separate. The demo's optional
SQL enrichment uses `graphmine_reader`; production write credentials are not
copied into testing or development.

`GRAPHMINE_DATABASE_DATASET_ALLOWLIST` selects those five entries and enables
the single dataset picker. `GRAPHMINE_DATABASE_CREDENTIALS_FILE` and
`GRAPHMINE_NEO4J_DATASETS_PASSWORD_FILE` reference the private, owner-only
`.database-workspace/demo.env`. No credentials are stored in Git. A registry
entry is queryable only after its dataset verification passes. See
[Database workspace](DATABASE_CYPHER_WORKSPACE.md#benchmark-datasets-and-schemas)
for ports, storage, loading gates, paused OnTime and deferred Stack Overflow.

Production keeps its existing `/data/labdata/wajid/graphmine_data/store` data.
Studio's production workspace and dataset root are under
`/data/labdata/wajid/graphmine_data/dataset-studio/`. Development and testing data
are under `graphmine_data/environments/devlopment/` and
`graphmine_data/environments/testing/`. Raw benchmark downloads remain on the data disk. Development backend logs and
models use private `backend-runs` and `backend-models` directories under its
environment root. Testing and production use their own directories of the same
names under their environment roots, seeded with the release's shared model and
paired training rows. The previous shared production model/log directories are
retained for rollback. Saved workflows and result artifacts are read through a
compatibility adapter; their original bytes and approval hashes are preserved.

Private host configuration, the installed controller, and deployment state live
under `graphmine-data/environments/`, outside the Git checkout. The installed
command is:

```sh
/home/wajid/projects/graphDatabaseAgent/graphmine-data/environments/gm-env status
```

For the shorter commands below, define a shell alias:

```sh
alias gm-env=/home/wajid/projects/graphDatabaseAgent/graphmine-data/environments/gm-env
```

Each checkout also needs its locked Node dependencies in both `agent/frontend`
and `agent/visualization` (`npm ci` in each directory). The visualization
dependencies are needed by the running application as well as tests.

The controller routes cuFile driver logs into each environment's data root via
`CUFILE_LOGFILE_PATH`, and into the isolated scratch store during verification.
GPU table loading therefore does not modify a code checkout.

The configuration selects exact code, Python, service, and storage paths.
`deploy/environments.py` validates that writable paths, ports, and services do
not overlap. A developer shell cannot override its GraphMine storage settings.

## Workflow

### Model sleep and wake

The model process can release its GPU allocations while GraphMine is idle.
Configure the same values in the model and agent environment files:

| Setting | Default | Meaning |
| --- | --- | --- |
| `GRAPHMINE_LLM_SLEEP_MODE` | `1` | Enable automatic wake and idle sleep. Set `0` to retain the original always-awake vLLM command. |
| `GRAPHMINE_LLM_SLEEP_LEVEL` | `1` | Only level 1 is supported; other values are rejected. |
| `GRAPHMINE_LLM_IDLE_SLEEP_MINUTES` | `20` | Idle interval after the last request or evaluation finishes. |
| `GRAPHMINE_LLM_HOST` | `127.0.0.1` | Sleep mode refuses any other bind address. |
| `GRAPHMINE_LLM_WEIGHT_BYTES` | measured | Optional positive model-weight byte count instead of summing the active cached safetensors snapshot. |
| `GRAPHMINE_LLM_POWER_LEASE_DIR` | runtime directory | Optional shared directory for request leases; use the same absolute path in agents, evaluations and SSH commands. |

Level 1 offloads weights to CPU RAM and discards the KV cache. Before enabling
it, the launcher reads `/proc/meminfo` and requires `MemAvailable` to be at least
1.25 times the model's weight size. If RAM is insufficient or the weight size
cannot be determined, it warns and launches without sleep mode. No model files
are downloaded by this check. The LoRA adapters and existing launch flags are
preserved. See the [vLLM sleep-mode documentation](https://docs.vllm.ai/en/v0.30.0/features/sleep_mode/).

The agent owns one power manager per distinct model server, including a separate
analytics router when configured. Each model request wakes its server if needed;
streaming responses and retries keep a request lease until they finish. Learning
runs acquire a lease on their first local model use and retain it for the whole
run. Native-only audits and external-provider runs do not wake local vLLM.
Process leases also prevent an agent from sleeping during an SSH evaluation.
They live under `XDG_RUNTIME_DIR/graphmine-llm-power` when available, otherwise
under `HF_HOME` (or `~/.cache/huggingface`). System services without a user runtime
directory should set a shared writable path such as
`/var/lib/graphmine/llm-power`; do not put it in a systemd-private `/tmp`.

Every 60 seconds the agent checks for 20 minutes of inactivity and zero active
leases. It requests level-1 sleep with `mode=wait`, so vLLM can drain any remaining
work. Failed sleep attempts are logged and retried the next minute. Servers that
return 404 for `/is_sleeping` are treated as unsupported and rechecked after ten
minutes. A wake has a 120-second deadline, includes a successful `/v1/models`
check, and reports its elapsed time in the agent log.

Administrators can use Settings → Manage users → Model, or the authenticated
`GET /api/admin/llm/power` and `POST /api/admin/llm/power/{sleep,wake}` routes.
Over SSH, `GRAPHMINE_ENV_FILE=/path/to/model.env deploy/vllm-power.sh status`
shows the current state; replace `status` with `sleep` or `wake` to control it.
The script reads the same environment file as the launcher and sends its API key
without putting the key in a command argument. It only contacts
`http://127.0.0.1:8001` and respects active GraphMine request leases.

Chat displays “Waking the model…” while waiting. A wake timeout keeps the question
retryable. Opening saved results does not wake the model; optional prose after
an already-chosen calculation only uses an already-awake model, with the computed
facts available immediately. Health checks and power-status reads also never wake
the model.

`VLLM_SERVER_DEV_MODE=1` is set only when the launcher enables sleep. Keep these
development endpoints on loopback; public Cloudflare routes remain exclusively
on the existing application ports 18000 and 8877. No systemd-unit, tunnel,
database-service or account changes are required.

### Promoting application changes

1. Work in `graphMine-database-cypher` on `devlopment`; Studio code is its
   `dataset-studio/` subdirectory. Commit your changes and push `devlopment`.
2. Use `gm-env start-dev` for private UI development and `gm-env stop-dev` when
   finished. Development disables live model calls and hides GPUs by default.
3. Schedule downtime for users, then run `gm-env begin-testing --commit devlopment`.
   The controller checks for clean checkouts and active work, advances testing,
   stops the production and development apps, and starts the testing apps.
   Production URLs are unavailable during this interval.
4. Exercise the private testing apps. They use the existing vLLM server and
   model weights with separate application data. Run `gm-env verify-testing` to
   execute the configured automated checks. A failed check prevents promotion.
5. After the candidate passes both automated checks and your manual acceptance,
   run `gm-env promote --push`. It backs up production application and Studio
   data, stops testing, advances production to the exact verified commit,
   starts production, checks HTTP health, advances `main`, and atomically pushes
   the four environment branches.
6. If testing fails, use `gm-env cancel-testing` to stop testing and resume the
   unchanged production release.

The controller never stops the vLLM, PostgreSQL, or Neo4j services. The model
stays loaded in GPU memory throughout ordinary app testing and deployment. A
machine reboot is unnecessary. Changes to inference dependencies, weights, or
the native runtime need their own maintenance procedure.

Testing is private by default. For example, forward ports 18001 and 8878 over
SSH and open the forwarded localhost URLs. The production Cloudflare routes
continue to target ports 18000 and 8877; they are never redirected to test data.

## Private environment sign-in

Development and testing have separate accounts and initially contain no users.
Create an administrator in each environment before signing into its private UI
(the command prompts for a password). Dataset Studio accepts that environment's
GraphMine accounts.

```sh
cd /home/wajid/projects/graphDatabaseAgent/graphMine-database-cypher
GRAPHMINE_AGENT_DATA_ROOT=/data/labdata/wajid/graphmine_data/environments/devlopment/store \
  .venv/bin/python -m graphmine_agent accounts create wajid --admin

cd /home/wajid/projects/graphDatabaseAgent/graphMine-testing
GRAPHMINE_AGENT_DATA_ROOT=/data/labdata/wajid/graphmine_data/environments/testing/store \
  .venv/bin/python -m graphmine_agent accounts create wajid --admin
```

Production accounts and existing Studio sign-ins are preserved.

## Database changes and recovery

Validate schema changes against disposable data before promotion. Code rollback
alone may not be compatible with a migrated production database. If production
startup fails after promotion, the controller retains the previous commit and
backup location in its testing-session record and does not overwrite live data
automatically. Review compatibility and writes before restoring a backup.

The installed controller is a separate copy so editing its source cannot change
an in-progress deployment. Deploy controller updates deliberately after their
tests pass. Host environment files contain credentials and stay outside Git.

The future Studio design that reads original captures and stores edits by
reference is recorded in `latter plans.md`; this environment setup does not
implement that separate feature.

## Validation and opt-in checks

The earlier native-upload test mismatch was resolved during Phase 5: ordinary
CSV uploads use the existing CPU ingestion path, while explicit native-reader
transport failures retain separate coverage. Current application, browser,
library, live-model and native runtime evidence is recorded in
`validation/phase5-production/` and `validation/phase5-runtime-release/`.

The deployment gate runs the controller, account, capture, backup/recovery,
Studio exchange, Dataset Studio, database-source, grounding, clarification,
options, partition, disabled-search, result-view and frontend checks. Frontend
tests, TypeScript and API contracts must pass. Physical-GPU application and
disposable-database integration tests require their separate opt-in setup;
their skips are reported explicitly. The pinned native runtime has separate
CPU and physical-GPU oracle evidence, including device-specific admission.
