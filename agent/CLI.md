# Conversational CLI and local history

Run this from the repository root on the configured GPU host:

```bash
deploy/chat.sh --domain fraud_detection \
  --graph agent/evaluation/applications/graphs/fraud_accounts.json
```

The launcher loads the existing `agent/.env`. It uses the existing language-model
endpoint and GraphMine binary. Ask a question such as:

```text
Show every group of at least three accounts where each account exchanged payments with every other account. Give the account names and explain what this says about fraud.
/feedback The explanation is too technical | Explain the account groups in ordinary investigation language
/history
/quit
```

`graphmine-agent chat` is also available directly after installing `agent`; its
configuration comes from environment variables. The shell launcher is the
convenient way to reuse this repository's `.env` configuration.

Local CLI sessions use `.graphmine-cli/` and are independent of the running API
server's sessions. The CLI runs the same FastAPI routes, agent service, plan
validator, job worker, and native algorithms inside its own process. It does not
start another language model. Only one local CLI can open a given data directory
at a time. Use `--data-dir PATH` for a separate store, or connect to the API to
share its sessions and compute queue:

```bash
deploy/chat.sh --base-url http://127.0.0.1:18000
```

The server must be restarted with this code before the remote CLI can use its
history and feedback endpoints. The local CLI works without restarting the
existing server. Independent local instances have independent compute queues;
use the shared API for simultaneous users on one compute GPU.

## Commands

| Command | Purpose |
| --- | --- |
| `/load "path with spaces.csv"` | Upload an undirected edge list or canonical graph JSON |
| `/load connections.csv --directed` | Upload a directed edge list; JSON uses its own direction flag |
| `/load events.csv --source-column sender --target-column recipient --timestamp-unit milliseconds` | Map application columns and declare timestamp units |
| `/load customers.json --role left_partition` | Upload an additional algorithm input |
| `/domains` | List available application domains |
| `/files` and `/use FILE_ID` | Inspect uploads and choose the graph to analyze |
| `/run QUESTION` | Explicitly request a new computation |
| `/plan QUESTION` | Preview the plan without executing it |
| `/explain QUESTION` | Interpret the current result |
| `/result` | Print the full structured result |
| `/view answer.html` | Save a self-contained interactive report; open it in a browser without a server |
| `/direction two-way` or `/direction preserve` | Explicitly allow or disallow an undirected analysis of directed connections |
| `/feedback` | Ask what went wrong and what the user expected |
| `/feedback WRONG \| EXPECTED` | Save both feedback fields in one line |
| `/history` | Print the history location and artifact count |
| `/history export.zip` | Export the complete session, including raw model calls |
| `/sessions`, `/resume SESSION_ID` | List or resume sessions |
| `/new DOMAIN_ID` | Create a new session |
| `/wait [JOB_ID]`, `/cancel [JOB_ID]` | Wait for or cancel an outstanding computation |
| `/help`, `/quit` | Help and exit |

In one-line feedback, type a literal `|` between the two fields. Feedback records
the session, latest turn, relevant job/result, timestamp, what went wrong, and
expected behavior. It also works for a rejected or failed request with no result.
It is saved for later review; it does not retrain the model or alter the current
analysis. Automated evaluation feedback is explicitly marked
`source: assistant_evaluation` and kept separate from the model's conversation.

The deployed browser accepts both `/feedback NOTE` and `/feedback WRONG | EXPECTED`,
and the backslash spelling `\feedback`. It also handles `/correct`, `/rate`,
`/note`, `/status`, `/export` and `/help` locally; these browser commands do not
change the terminal client's separate command syntax above. See the
[browser pilot guide](README.md#commands-in-the-browser-chat).
The structured API is `POST /api/sessions/{id}/feedback` with `what_went_wrong`,
optional `expected_behavior`, `category`, `rating`, `turn_id`, `job_id`, and
`result_id`. Retrieve records with `GET /api/sessions/{id}/feedback`, or download
the review JSONL at `GET /api/sessions/{id}/feedback/export`. Each record includes
a conversation snapshot and deployment identity when recorded for its target turn.

Ordinary follow-ups such as “Now use only 2026 collaborations” or “Which people
connect these teams?” can start a new analysis without `/run`. An uncertain
follow-up classification goes to the full planner using the original question;
it cannot independently demand unnecessary inputs. The planner receives the
previous computation's actual parameters and the latest graph-scoped pending
question, if any. A refused request is context, not an executed result. Active attribute
filters carry forward unless changed or explicitly cleared. Up to four independent
computations can answer one question; the final response combines their findings.
The CLI prints verified findings and the path to an interactive HTML report;
it does not draw interactive charts inside the terminal. `/view` refuses to
overwrite an existing file. Direction approval resets when selecting or loading
another graph, starting a session, or resuming a session.

## Application data and answers

Canonical JSON retains vertex/edge IDs, names, types, attributes, and graph
metadata. Original records remain separate from the native topology projection
and are rejoined by exact external ID after computation. Set
`graph.attributes.timestamp_unit` to `seconds` or `milliseconds` for event data;
the upload option can also declare it. Units are never guessed from magnitude.

CSV requires a header. Common endpoint headers (`source,target`, `src,dst`,
`from,to`) are recognized; otherwise use column mapping. Use `.txt` for a
headerless edge list. Recognized columns include `id`, `weight`, `timestamp`,
`source_label`, `target_label`, `source_type`, and `target_type`.
`source.department` and `target.department`, for example, become vertex
attributes; other columns become edge attributes. Conflicting descriptions of
the same entity are rejected. Numeric timestamps must be integers; preserve
calendar-date strings as attributes until an explicit conversion is supported.

For example:

```text
/load agent/evaluation/applications/graphs/workplace_projects.json
Which groups of people mainly work together, and which people connect different parts of the organization? Show their names and departments.
Now show the groups using only collaborations from 2026.
/view workplace.html
```

Reports visualize the returned answer, with every materialized group selectable,
original names/attributes available on click, attribute-based color/size controls,
and tables. Network overviews are bounded to 500 selected entities and 2,000
connections, with an explicit notice when truncated. The structured answer keeps
the materialized rows; it is not a scalable paging API yet. A saved report contains
the result and its displayed attributes, so treat it as private data.

Computed claims come from deterministic answer records. Model-proposed
implications are labeled separately and are not verified facts. Weights may be
retained for inspection without being used by an algorithm: explicitly weighted
questions are refused rather than silently answered with an unweighted result.
Unsupported calculations are reported as `unsupported` even when input data is
also missing: uploading costs cannot enable an analysis that ignores costs.
Genuine missing choices or inputs for an available calculation still receive
`needs_information`. These checks depend on the model extracting the requested
requirements; they are not a guarantee of arbitrary-language understanding.

The tested lower-latency planning profile uses
`GRAPHMINE_LLM_PLAN_REASONING_EFFORT=none`. The launcher loads `agent/.env`, so an
existing value there takes precedence over a variable set before `deploy/chat.sh`.
To test an override without editing that file:

```bash
set -a
source agent/.env
set +a
GRAPHMINE_LLM_PLAN_REASONING_EFFORT=none .venv/bin/graphmine-agent chat \
  --graph agent/evaluation/applications/graphs/workplace_projects.json
```

The running API retains its existing configuration until restarted. It does not
train models or make external teacher calls automatically.

## Files saved

Local CLI history defaults to `.graphmine-cli/history/SESSION_ID/`. Server
history defaults to `<GRAPHMINE_AGENT_DATA_ROOT>/history/SESSION_ID/`. Override
both with `GRAPHMINE_HISTORY_ROOT` if desired.

```text
SESSION_ID/
  session.json
  last_chat.json
  turns/TURN_ID.json
  events/TIMESTAMP_EVENT_ID.json
  files/FILE_ID/
    original
    canonical.json
    metadata.json
  jobs/JOB_ID/
    job.json
    inputs.json
    command.json
    process.json
    stdout.log
    stderr.log
    result.json
    projected-graph.json        # when attribute filters are applied
    projection.json            # source hash, filters, selected input counts
  results/RESULT_ID/
    result.json
    answer.json
    answer.html
    interpretation.json
    visualizations.json
  feedback/FEEDBACK_ID.json
```

`original` preserves the uploaded bytes; `metadata.json` contains the original
filename and hashes. Supporting files are saved too. `inputs.json` identifies
the plan, files, capability snapshot, and timeout; `command.json` records the
actual selected backend and arguments. A failed job still preserves any artifacts
it produced. `process.json` records the exit code, timeout, or cancellation.

Events are separate immutable JSON files so repeated interpretations and retries
remain available after the latest snapshots change. They contain user requests,
the exact model request body (system prompt, conversation, schema and generation
settings), raw provider response bodies, timing, parsed model output, validated
plans, interpretation fallbacks, result revisions, feedback, and errors. Session,
turn, job, result and model-call IDs connect the stages. Authentication headers
and API keys are not logged. Files contain the graph data and prompts you supply;
default runtime directories are ignored by Git and there is no automatic expiry.

This captures new activity after installing the change. It cannot reconstruct
raw LLM requests/responses from sessions recorded by older versions. Operational
SQLite state is retained alongside the history, so resuming a session also
requires its data directory, not just the exported history ZIP.

## Scripting and replay

```bash
deploy/chat.sh --domain bioinformatics \
  --graph agent/evaluation/applications/graphs/protein_interactions.json \
  --message 'Find the largest group where every protein interacts with every other member.' \
  --message '/feedback Explain the limitations more clearly | Distinguish physical interactions from a confirmed protein complex' \
  --json

deploy/chat.sh --session SESSION_ID
deploy/chat.sh --script questions.txt
```

`--message` can be repeated. `--script` reads one question or command per line.
`--json` emits JSONL records. Batch errors return a nonzero exit code; interactive
errors leave the prompt usable. `--timeout-seconds` bounds waiting for a queued
job, not the separate model request timeout. If the wait expires, use `/wait` or
`/cancel`. Exiting a local CLI cancels its active jobs; leaving a remote CLI does
not stop jobs on the server.

Run the live application probes with the existing deployment configuration:

```bash
set -a
source agent/.env
set +a
.venv/bin/graphmine-agent evaluate-usability \
  --output .graphmine-usability/my-run/report.json
```

This uses isolated local sessions and requires the real model and GPU runtime.
It preserves every run, checks independently specified results, and adds feedback
to failed turns. The output path must be new so previous evidence is not replaced.
Use repeated `--case-id CASE_ID` flags to replay a subset. The small synthetic
corpus covers application usability, not performance at scale or broad model
accuracy. See [the evaluation report](evaluation/APPLICATION_USABILITY_REPORT.md)
and [the improvement plan](IMPROVEMENT_PLAN.md).

## Synthetic data and learning candidates

The commands below generate data and evaluate it locally. They do **not** train
a model, upload graphs, or call a paid teacher API. Optional, explicitly enabled
teacher calls are described in the next section. Start with the same environment
setup above, then use new output paths:

```bash
.venv/bin/graphmine-agent learning generate \
  --output .graphmine-learning/my-corpus --seed 314159 --graphs-per-family 2
.venv/bin/graphmine-agent learning verify .graphmine-learning/my-corpus
.venv/bin/graphmine-agent learning audit .graphmine-learning/my-corpus \
  --output .graphmine-learning/my-native-audit.json \
  --data-dir .graphmine-learning/my-native-runtime
```

The default creates 24 graphs and 114 application questions in six domains.
Whole graph families are assigned to training, validation, or test, and exact
topology-isomorphism checks reject renamed duplicate graphs across splits.
The graphs are intentionally small: at most 12 vertices for exhaustive reference
checks and 24 events for temporal references. Generating many graphs from one
small family can exhaust distinct topologies; use a smaller count if that occurs.
This is not a large-graph benchmark.

The native audit checks actual entity memberships, counts, shortest-route
scores, surviving cores, customer/product bundles, and ordered event IDs against
independent Python references. Community checks verify coverage and the modularity
of the returned partition; they do not claim a unique best community assignment.
Ambiguous/unsupported questions have separately marked template/contract checks,
not fabricated successful algorithm runs. Reports record source/binary hashes,
commands, workspaces and failures.

Measure the real language-model agent separately:

```bash
GRAPHMINE_LLM_PLAN_REASONING_EFFORT=none .venv/bin/graphmine-agent learning evaluate \
  .graphmine-learning/my-corpus --split test \
  --output .graphmine-learning/my-heldout.json \
  --data-dir .graphmine-learning/my-heldout-runtime
```

Each question starts a fresh isolated session, passes through the normal agent,
and retains full history, model calls, answers and report artifacts. Failures
receive linked `assistant_evaluation` feedback. Use `--limit N` for a
family-interleaved subset; do not report a subset as complete-suite accuracy.
Audit/evaluation return exit code 1 when any check fails. Evaluation does not
prove explanation usefulness, visual polish, or reliability over repeated runs.
Separate runtimes have separate GPU queues; schedule this while the shared
compute GPU is idle.

Export checked intent-routing examples:

```bash
.venv/bin/graphmine-agent learning export .graphmine-learning/my-corpus \
  --audit .graphmine-learning/my-native-audit.json \
  --output .graphmine-learning/my-route-candidates
```

This writes `train.jsonl`, `validation.jsonl` and `provenance.json`.
The exporter rechecks saved native outputs, rejects stale corpus/checker hashes,
quarantines failed or unaudited examples, and never exports test examples.
These are automatically generated `RouteDecision` candidates from semantic
templates, **not teacher distillation or training-ready approval**. They do not
yet train detailed plans, interpretations, or visualization choices. Review a
sample and compare against the held-out baseline before any weight updates.

Optionally collect diverse wording from an already-running local model:

```bash
.venv/bin/graphmine-agent learning paraphrase .graphmine-learning/my-corpus \
  --count 5 --output .graphmine-learning/my-paraphrases
```

Only loopback model endpoints are accepted; redirects and environment proxies
are disabled. Runs are capped at 20 calls and use training families only. Exact
requests and raw responses are retained without authorization headers. All
proposals are marked `quarantined_unverified_paraphrase` and
`training_eligible: false`; matching JSON syntax does not prove matching meaning.
The template exporter cannot ingest these proposals; the separate reviewed
exporter below requires semantic and execution evidence. The current local Qwen
is a wording generator, not an independently stronger teacher.

All default learning artifacts live under the Git-ignored
`.graphmine-learning/`, with private JSON/export file permissions. Existing
corpora, reports and candidate directories are never overwritten. Actual training
still requires a separate decision. External teacher inference requires explicit
opt-in, a securely configured key, and a per-run budget.

The synthetic audit exposed two maximum-clique backend problems. The agent now
excludes `cuda-ms` (unreliable maximum certification) and
`maximum-clique-on-gpu` (an abort on a cycle-with-chord fixture), even if an old
benchmark policy ranks them first. It selects `gpu-maximum-clique` when available
and otherwise refuses execution. Health reports expose these exclusions.
Direct native CLI users may still explicitly invoke these backends; the corrected
CUDA-MS adapter no longer treats its relaxation mask as a certified upper bound.

## Teacher calibration and semantic review

The learning pipeline can now propose wording, independently extract its meaning,
replay it through the agent, and export only candidates passing every gate. It
does not fine-tune, upload existing histories, change the deployed model, or
restart the backend. Only the verified, seeded synthetic corpus is accepted.

First calibrate a potential reviewer on 14 known-meaning questions from training
and validation families, never the final test split:

```bash
.venv/bin/graphmine-agent learning compare-teachers .graphmine-learning/my-corpus \
  --execute --output .graphmine-learning/my-local-calibration
```

Without `--execute`, comparison is a zero-call dry run. Controls include changed
thresholds, one largest versus all tied largest groups, and seconds versus
milliseconds. Every control must match the exact semantic contract and provide
verbatim question evidence. A failed calibration returns exit code 1 and keeps
its full report. This small development check is not a general accuracy score.

The reviewer sees the candidate question and a bounded graph vocabulary/schema;
it does not see the original wording, expected operation, or oracle answer. The
checker compares its extracted quantifiers, thresholds, filters, weighting,
direction, event roles/order, and units to the source contract. Novice-language
checks flag graph-mining jargon and risky “largest” wording. These are conservative
screens, not proof that arbitrary language has exactly one meaning.

```bash
GRAPHMINE_LLM_PLAN_REASONING_EFFORT=none .venv/bin/graphmine-agent learning review-candidates \
  .graphmine-learning/my-corpus \
  --candidates .graphmine-learning/my-paraphrases/candidates.json \
  --calibration .graphmine-learning/my-local-calibration/comparison.json \
  --output .graphmine-learning/my-semantic-review \
  --data-dir .graphmine-learning/my-paraphrase-replay

.venv/bin/graphmine-agent learning export-reviewed .graphmine-learning/my-corpus \
  --candidates .graphmine-learning/my-paraphrases/candidates.json \
  --review .graphmine-learning/my-semantic-review/review.json \
  --calibration .graphmine-learning/my-local-calibration/comparison.json \
  --audit .graphmine-learning/my-native-audit.json \
  --output .graphmine-learning/my-reviewed-candidates
```

Only candidates passing the meaning/wording screen are replayed. Omit `--data-dir`
to screen without replay; those candidates cannot become export-eligible. The
reviewer must pass calibration and differ from both the wording generator and
the student. Same-server local aliases are rejected too. A distinct model ID is
necessary, not proof of independent model lineage or uncorrelated errors.

The exporter rechecks source hashes, calibration, exact blinded request/raw
response bindings, meaning, question-bound replay output, and independent native
results. It does not trust an edited pass flag. It writes `train.jsonl` and
`provenance.json`; zero eligible candidates produces an empty training file with
explicit quarantine reasons. Validation/test families never enter this export.
Accepted rows are still automatic routing candidates, not human-reviewed data
or validated interpretation/visualization targets. Review a sample before use.

Reports include `comparison.json`, `review.json`, private `calls/*.json` and
`replays/*.json`; normal replay histories live in the isolated data directory.
Source changes invalidate prior calibration/review gates. Use new directories
when rerunning; preserve the old failed evidence.

### Optional stronger teacher pilot

GPT-6.1 Sol is the provisional first pilot for cost/capability, and GPT-6 Astra a
candidate stronger reviewer. This is based on the official
[model-selection guidance](https://developers.openai.com/api/docs/guides/model-selection)
and [model comparison](https://developers.openai.com/api/docs/models/compare),
not a completed GraphMine benchmark. Model access is account-dependent and has
not been confirmed here. Codex access is not assumed to provide API credentials.

Preview the full comparison, or a cheaper single-model pilot, without a key or
any network call:

```bash
.venv/bin/graphmine-agent learning compare-teachers .graphmine-learning/my-corpus \
  --provider openai --max-output-tokens 2048 --budget-usd 5 \
  --output .graphmine-learning/my-external-comparison-plan

.venv/bin/graphmine-agent learning compare-teachers .graphmine-learning/my-corpus \
  --provider openai --model gpt-6.1-sol --max-output-tokens 2048 --budget-usd 5 \
  --output .graphmine-learning/my-sol-plan
```

For the recorded corpus, conservative reservations are $5.664336 for both models
and $0.944056 for Sol alone. The full run is therefore refused at a $5 cap before
any call. These are upper-biased application estimates, not measured charges or
a provider billing guarantee. They use full request byte length plus an input
allowance, twice the published input rate, and the full output-token limit;
reservations are never reclaimed after a failure or discounted usage. Pricing
was checked on 2026-10-03 and must be rechecked before a later pilot. A small
output-token cap can also truncate reasoning/output and fail calibration.

To execute an approved pilot, configure `OPENAI_API_KEY` securely in the process
environment, then add **both** `--execute --allow-external` and keep a finite
`--budget-usd`. Do not paste keys into chat or put them in prompts. External
requests use the fixed OpenAI Responses endpoint, strict JSON schemas,
`store: false`, no tools, no retries, no redirects and no environment proxy.
Missing/over-limit usage stops further calls; incomplete or refused responses
cannot pass. Authentication is excluded/redacted from the retained evidence.
`store: false` is not a claim of zero provider retention under all account policies.

After selecting a teacher, preview a wording-generation run:

```bash
.venv/bin/graphmine-agent learning propose-candidates .graphmine-learning/my-corpus \
  --provider openai --model gpt-6.1-sol --count 5 --budget-usd 5 \
  --output .graphmine-learning/my-teacher-proposal-plan
```

This is also dry-run by default; use a new output directory with
`--execute --allow-external` only after authorization. All generated proposals
start quarantined. `review-candidates` also accepts `--provider`, `--model`,
`--max-output-tokens`, `--allow-external`, and `--budget-usd`; unlike comparison
and proposal planning, invoking review performs model calls. Use the exact
profile from a passing calibration. Budgets are per invocation, not shared
across generation, calibration and review. No command starts weight training.

Recorded local result: the revised reader passed 9/14 calibration controls;
2/13 wording proposals passed screening and both live replays passed. All 13
remain quarantined because the reviewer was unqualified and was the same model
as generator/student. See the [checkpoint and remaining work](IMPROVEMENT_PLAN.md#semantic-review-checkpoint--2026-10-03-utc).

### Codex with a ChatGPT subscription

`--provider codex` uses the installed Codex CLI and its existing ChatGPT login,
not the OpenAI API adapter. It requires Codex CLI 0.160.0 or newer. Check the
login with `codex login status`; if needed, use `codex login` interactively.
Never copy credentials into this repository or paste them into chat.
The [official non-interactive interface](https://learn.chatgpt.com/docs/non-interactive-mode)
supports scriptable structured answers using saved authentication.

Start with reviewer calibration (omit `--execute` for a zero-call dry run):

```bash
.venv/bin/graphmine-agent learning compare-teachers .graphmine-learning/my-corpus \
  --provider codex --model gpt-6-astra --allow-codex --execute \
  --output .graphmine-learning/my-codex-calibration
```

Continue only if all 14 controls pass. Generate a small batch with a different
teacher model, then review and replay it with the calibrated profile:

```bash
.venv/bin/graphmine-agent learning propose-candidates .graphmine-learning/my-corpus \
  --provider codex --model gpt-6.1-sol --count 5 --allow-codex --execute \
  --output .graphmine-learning/my-codex-proposals

GRAPHMINE_LLM_PLAN_REASONING_EFFORT=none .venv/bin/graphmine-agent learning review-candidates \
  .graphmine-learning/my-corpus \
  --provider codex --model gpt-6-astra --allow-codex \
  --candidates .graphmine-learning/my-codex-proposals/candidates.json \
  --calibration .graphmine-learning/my-codex-calibration/comparison.json \
  --output .graphmine-learning/my-codex-review \
  --data-dir .graphmine-learning/my-codex-student-replay
```

The existing `export-reviewed` command applies the same semantic, native-audit,
student-replay and source-provenance checks to this provider. Separate sessions
are not sufficient independence: generator, reviewer and student must still
have distinct model identities, and the reviewer must qualify. This is reviewed
data preparation, not a Qwen weight update.

The adapter forces ChatGPT authentication and the built-in OpenAI provider. It
uses an allowlisted child environment without API keys, access-token overrides,
proxy/endpoint overrides or inherited shell hooks. It does not read, copy, or
log the CLI's credential store. User config is ignored; each request starts in
a new temporary directory with no repository files or reference answers.
Shell, apps, plugins, hooks, delegation and web search are disabled, and any
tool-use event makes the saved response ineligible. Runs are ephemeral and
read-only. Exact task/schema, CLI arguments/version, redacted output events,
reported token usage and failures are retained in private call artifacts.

This consumes **ChatGPT/Codex plan allowance**, subject to the account's model
access, usage limits and credit settings. A zero API-dollar reservation does
not mean unlimited or cost-free usage. `--budget-usd` is rejected for this
provider; `--allow-codex` is separate from paid-API opt-in. There is no automatic
API-key fallback or model substitution. The CLI may perform its built-in
retries within a 120-second invocation timeout; the application does not retry
failed calls, and an execution/format/usage failure stops further model calls
in that invocation.

`--max-output-tokens` is a **post-call acceptance check for Codex**, not a hard
generation cap: over-limit usage has already been consumed when reported.
Output capture is bounded to 1 MiB per stream. Each command also bounds its
number of CLI invocations (14 per calibration model, 1–20 generation calls,
up to 60 candidate reviews). The five-call example above can produce at most
15 candidates, giving at most 34 inference invocations across its three stages.
Limits are per command, not an account-wide quota. Stop and review failures
instead of increasing limits or bypassing the quality gate automatically.

Adding this provider changed the review-source fingerprint. Previous local or
API calibration/review artifacts remain historical evidence but cannot qualify
a new export without fresh runs against the current implementation.

Recorded pilot: Astra passed 14/14 calibration controls; Sol generated 10
questions in five calls; all 10 passed blinded review and live Qwen replay.
The fresh native audit passed 5/5, and export produced 10 routing candidates in
`.graphmine-learning/codex-reviewed-candidates-v1/`, with no weight training.
See the [results and limitations](IMPROVEMENT_PLAN.md#codex-subscription-teacher-pilot--2026-10-03-utc)
and [machine-readable record](evaluation/reports/codex-teacher-pilot-2026-10-03.json).

## Public real-world evaluation datasets

The real-data workflow is separate from the synthetic training exporter. It
downloads only a fixed source catalog, retains original bytes and SHA-256 hashes,
builds documented small projections, and derives application task contracts with
independent reference answers. It does not upload training data or update weights.

Current sources:

| Source | Preserved information and limits | Development use |
| --- | --- | --- |
| [SocioPatterns workplace contacts](https://sociopatterns.org/datasets/contacts-in-a-workplace/) | Anonymous IDs, departments, recorded contact duration; 2013 data, CC0. Contacts are aggregated into an explicitly static, undirected graph. | Development; 12-participant activity-biased slice. |
| [STRING v12.0](https://en.string-db.org/help/api/) | Gene names, STRING IDs, taxon and confidence channels; functional association is not proof of binding or causation. [Source license: CC BY 4.0](https://www.string-db.org/cgi/access?footer_active_subpage=licensing). | Development; 12 selected E. coli proteins, confidence at least 0.700. |
| [OpenFlights](https://openflights.org/data) | Airport names/codes, cities, coordinates and carriers; historical routes, not current schedules. Source declares ODbL/DbCL terms. | Whole-source holdout; 12 UK airports, retaining only nonstop pairs recorded in both directions. |

Raw datasets stay in the ignored private learning folder. Retain source attribution
and review the source terms before distributing derived databases or training data.
No source is relabelled as synthetic. A separate workplace fixture adds one
explicitly marked adversarial record note; the original dataset is unchanged.
These 12-node slices enable exact answer checks, not a scalability or representative
population claim. Airport holdout questions may have familiar task types: source
separation does not mean unseen mathematical operations or unknown pretraining data.

Preview the download/source plan without writes or network calls, then opt in:

```bash
.venv/bin/graphmine-agent learning prepare-real-world \
  --output .graphmine-learning/my-real-corpus

.venv/bin/graphmine-agent learning prepare-real-world \
  --output .graphmine-learning/my-real-corpus --download

.venv/bin/graphmine-agent learning verify-real-world .graphmine-learning/my-real-corpus
```

There are five source files, each capped at 4 MiB. Downloads reject redirects;
the ZIP reader reads only the expected member and never extracts paths. Rebuild
offline into a new directory with `--source-cache PATH` instead of `--download`.
This verifies the cached source URLs/hashes and preserves their retrieval dates.

Generate and screen the development questions with the existing ChatGPT login:

```bash
.venv/bin/graphmine-agent learning propose-real-world .graphmine-learning/my-real-corpus \
  --output .graphmine-learning/my-real-questions --execute --allow-codex
```

Omitting `--execute` writes a zero-model-call plan. The current corpus requires at
most 50 Codex calls: eight reviewer calibration controls, 21 Sol question-generation
calls and 21 Astra reading calls. Astra receives candidate user messages and bounded
graph context, not original task cards, reference meanings or numeric answers.
Use `--limit-cases 17` to reduce a run to 42 calls, retaining the richer workflows
and dropping four duplicate single-turn group cards. Limits apply per invocation.
All eight controls must pass before generation starts. Every generated conversation
must preserve its per-turn mathematical contract and quoted evidence; changed or
technical wording is quarantined. This uses the same allowance/authentication and
post-call token-limit boundaries described in the Codex section above.
Real-data meanings include the requested weight attribute and how it is used;
merely retaining a boolean that weights matter is not sufficient to certify a query.

Audit the native computations and run repeated local-student trials:

```bash
.venv/bin/graphmine-agent learning audit-real-world .graphmine-learning/my-real-corpus \
  --output .graphmine-learning/my-real-native.json \
  --data-dir .graphmine-learning/my-real-native-runtime

GRAPHMINE_LLM_PLAN_REASONING_EFFORT=none .venv/bin/graphmine-agent learning evaluate-real-world \
  .graphmine-learning/my-real-corpus \
  --questions .graphmine-learning/my-real-questions/questions.json --repeats 2 \
  --output .graphmine-learning/my-real-evaluation.json \
  --data-dir .graphmine-learning/my-real-evaluation-runtime
```

The evaluator recomputes screening gates from raw saved model-call evidence before
replay. Without `--questions`, it explicitly evaluates the original contract
templates instead; that is not a teacher-generated run. New isolated runtimes
preserve the live API store. Every failure gets linked evaluation feedback with
the expected contract, and normal history records retain prompts, native inputs,
outputs, interpretations and answer-view choices. Reused answers are bound to the
same session and original graph before grading.

The initial corpus contains 21 development scenarios / 27 turns, including six
analysis operations, ambiguity, unavailable weighted calculations, empty answers,
corrections, attribute-scope changes and untrusted record text. Nine airport
scenarios remain held out: these development commands have no holdout execution
switch. Reports distinguish question screening, numeric/behavioral correctness,
and future human assessment of explanation and visualization usefulness.
The synthetic `export` and `export-reviewed` commands reject these real-data
corpora; passing an evaluation is not automatic permission to train on it.

Completed example: [2026-10-03 real-world report](evaluation/reports/real-world-learning-2026-10-03.json).
It records 17/17 native checks and 38/42 student turn checks, with four workflow
failures and six additional qualitative feedback records. Two answers passed the
numeric checks while repeating a false attribute claim, so do not interpret
the pass count as explanation quality. The [improvement plan](IMPROVEMENT_PLAN.md#next-improvement-and-automated-data-plan)
prioritizes grounded claims, empty-result completion, filter/weight separation
and domain-friendly presentation before training. The original graphs, prompts,
responses, algorithm inputs/results, HTML reports, screenshots and feedback are
under `.graphmine-learning/real-world-*`; the tracked report indexes exact paths
and hashes. The nine airport scenarios remain unused by development model calls.

## Conversation regression checks

`evaluate-workflows` derives six multi-turn application workflows automatically
from the verified synthetic corpus. The default corpus supports 21 questions
across workplace, protein, account, infrastructure, retail and security data.
It checks year corrections and clearing scope, largest versus unextendable
groups, clarification replies, independent customer/product minimums, event
windows and units, unsupported requests, and continuation after a refusal.
Expected results come from the source contracts and independent reference
solvers, not from the model under test.

```bash
.venv/bin/graphmine-agent learning generate \
  --output .graphmine-learning/my-conversation-corpus --seed 271828
GRAPHMINE_LLM_PLAN_REASONING_EFFORT=none .venv/bin/graphmine-agent learning evaluate-workflows \
  .graphmine-learning/my-conversation-corpus \
  --output .graphmine-learning/my-conversation-report.json \
  --data-dir .graphmine-learning/my-conversation-runtime
```

Use `--repeats 2` or `--repeats 3` for separate fresh-session trials of every
workflow. Use repeatable `--case-id` to select `scope-corrections`,
`group-quantifiers`, `clarification-and-refusal`, `customer-bundles`, `event-window`
or `partner-threshold`. Each workflow shares conversation state across its
turns; different workflows/trials never share sessions. Failures receive linked
`assistant_evaluation` feedback without changing the next user question.
An exactly matching earlier result may be reused without a new computation.
The grader binds reuse to the same session and original graph bytes, then checks
the stored job parameters, filters, native memberships/counts and answer
attributes against the current question's independent contract. Merely saying
that an old answer applies is not enough.

The command requires the real model on a loopback endpoint and a new isolated
data directory. It does not restart the serving model, call a paid teacher,
export training rows, or update weights. Exit code 1 means at least one check
failed. The report records per-turn results, all expected contracts, source and
corpus hashes, inference settings, timings and history paths. Full raw model
calls, native inputs/outputs and HTML answers remain in the normal local history.

These are development regressions derived from training/validation graph
families. A new seed does not make those families unseen, and cases used to fix
bugs must not be reported as untouched held-out accuracy. Passing numerical and
state checks does not establish that domain users find the wording or charts
useful. Compare reports only when their `cases_sha256` and inference settings
match; preserve failed baselines instead of overwriting them. Old semantic-review
replays become stale when the production planner changes and must be rerun
before any reviewed export can qualify.

You can regrade an existing completed run without rerunning the model or
changing its original report, transcript, or feedback:

```bash
.venv/bin/graphmine-agent learning recheck-workflows \
  .graphmine-learning/my-conversation-corpus \
  --report .graphmine-learning/my-conversation-report.json \
  --output .graphmine-learning/my-conversation-recheck.json
```

Rechecking rejects changed questions/contracts and preserves the old issues
alongside the new ones, with source-report and evidence hashes. An earlier
automatic feedback record may represent a grader error; it is not silently
rewritten or promoted into a training label. Rechecking is numerical/semantic
evidence validation, not a model-generated usability judgment.

The [recorded conversation checkpoint](evaluation/reports/conversation-reliability-2026-10-03.json)
compares a 19/21 baseline with a 21/21 final replay across six workflows. Both
use the same questions and corrected grader. These inspected development cases
are not a fresh held-out accuracy measurement; see the
[remaining improvement plan](IMPROVEMENT_PLAN.md#conversation-reliability-checkpoint--2026-10-03-utc).

## Practical application-question curriculum

The separate business curriculum uses application requests about staffing,
payment review, service planning, customer campaigns, incident review and
laboratory follow-ups. Algorithm names remain in labels, not user questions.
Broad goals train domain-language clarification rather than a guessed operation.

```bash
.venv/bin/python -m graphmine_agent.learning.business_curriculum build \
  .graphmine-learning/finetune-corpus-v2 \
  --native-audit .graphmine-learning/finetune-native-v1.json \
  --output .graphmine-learning/my-business-curriculum

.venv/bin/python -m graphmine_agent.learning.business_curriculum export \
  .graphmine-learning/my-business-curriculum \
  --output .graphmine-learning/my-business-routing-data
```

Use the exported directory with the existing `finetune prepare` command below.
The recorded v1 curriculum has 180 training, 68 validation and 124 evaluation
cards, with separate wording banks and graph families. Only training/validation
rows enter the export. Saved native results are revalidated for unchanged
computation contracts; they do not independently verify the new wording's
meaning. These are authored synthetic questions, not customer data or calibrated
teacher-review results. Exclusions, source hashes, code snapshots and the audit
are preserved in the curriculum directory. Use new directories for revisions.

After a selected adapter finishes, bind the same practical evaluation cards to
that run. Use the existing `adapter_eval compare` command on the resulting suite:

```bash
.venv/bin/python -m graphmine_agent.learning.business_eval \
  .graphmine-learning/my-completed-adapter-run \
  .graphmine-learning/my-business-curriculum \
  --output .graphmine-learning/my-business-routing-suite

.venv/bin/python -m graphmine_agent.learning.business_workflows prepare \
  .graphmine-learning/my-business-curriculum \
  --output .graphmine-learning/my-business-conversations
```

The routing suite checks overlap against actual training rows and excludes
training families. Its default includes all 124 evaluation cards. The conversation
suite has nine development workflows / 21 turns over validation graphs, including
clarification, corrections, empty results and unsupported requests. It checks
native results and presentation without feeding oracle feedback into later
model turns. Numeric filter equivalence is explicit; original grader findings
are retained alongside the new grades.

After other work on the spare GPU finishes, run complete application trials
using the same CUDA/offline environment as the adapter commands below:

```bash
.venv-training/bin/python -m graphmine_agent.learning.business_workflows evaluate \
  .graphmine-learning/my-business-routing-suite \
  .graphmine-learning/my-business-conversations \
  --output .graphmine-learning/my-business-application-results \
  --arms base_nf4 adapter_nf4 serving_fp8
```

Only routing changes between the local arms; other model stages retain the
serving model. The existing `adapter_workflow_review` command summarizes finished
matched application runs. A separate serving-only reference supports the recorded
`--reference-native-gpu GPU-...` override. These commands do not consume the final
real-source holdout or deploy the adapter.

## Local Qwen adapter training

The first local pilot, `.graphmine-learning/finetune-qwen27b-v3`, completed all
48 optimizer steps on 2026-10-03 at 08:53 UTC. The final adapter has 992 finite
tensors and 496 nonzero LoRA-B tensors. It has not been deployed. See the
[fine-tuning progress log](evaluation/FINETUNING_PROGRESS.md) for completed
milestones, evaluation results, and remaining work. The original
[handoff report](evaluation/reports/real-world-fixes-finetune-2026-10-03.json)
records its earlier in-progress state. Future background training runs can use
a transient user service; the commands below inspect the original run.

```bash
.venv-training/bin/python -m graphmine_agent.learning.finetune status \
  .graphmine-learning/finetune-qwen27b-v3
journalctl --user -u graphmine-finetune-qwen27b-v3 -n 30 --no-pager
# Request a checkpointed stop; this waits for the next optimizer-step boundary.
systemctl --user stop graphmine-finetune-qwen27b-v3
```

This is a local background run, not a boot-persistent scheduled task. Its files
and checkpoints survive a process stop. The prior failed startup in `v2`
performed zero optimizer steps and is preserved in `previous-attempts.json`.

The opt-in training CLI is `python -m graphmine_agent.learning.finetune` in a
**separate training environment**. Do not install the training dependencies into
the running vLLM environment. Use `agent/training-requirements.txt`, then install
the agent package into that environment with `uv pip install --python
.venv-training/bin/python -e agent`.

The first pilot trains only `RouteDecision`: application requests, attribute
selection, empty answers, clarification and unsupported weighted computations.
Its supervision is generated from seeded task contracts and independent native
checks, **not copied teacher reasoning**. It does not train the answer generator
or teach the model to calculate algorithm results. The actual answers remain
algorithm-derived. Real-world evaluation sources and synthetic test families
are excluded. The current synthetic generator is `synthetic-v2`; preserve older
artifacts, but regenerate/audit rather than relabeling a v1 manifest as current.

```bash
.venv/bin/graphmine-agent learning generate \
  --output .graphmine-learning/new-training-corpus --seed 271828 --graphs-per-family 4
.venv/bin/graphmine-agent learning audit .graphmine-learning/new-training-corpus \
  --output .graphmine-learning/new-training-audit.json \
  --data-dir .graphmine-learning/new-training-audit-runtime
.venv/bin/graphmine-agent learning export .graphmine-learning/new-training-corpus \
  --audit .graphmine-learning/new-training-audit.json \
  --output .graphmine-learning/new-training-export
.venv-training/bin/python -m graphmine_agent.learning.finetune prepare \
  .graphmine-learning/new-training-export --checkpoint /absolute/local/Qwen/checkpoint \
  --output .graphmine-learning/new-adapter-run --gpu GPU-your-spare-device-uuid
```

Use the standard Qwen/Qwen3.8-27B checkpoint, not the serving FP8 checkpoint.
Preparation hashes model files and the checked export, verifies the current
production prompt, uses the non-thinking chat template, and masks prompt tokens
out of the training loss. It rejects overlength examples rather than truncating
the question or expected JSON. `run.json` pins the packages, base files, input
hashes, seed and hyperparameters. Preparation does **not** update weights.

```bash
# Inspect the proposed run without loading the model or training.
.venv-training/bin/python -m graphmine_agent.learning.finetune train \
  .graphmine-learning/new-adapter-run

# Explicit execution: isolate the spare GPU, never the serving model's GPU.
CUDA_VISIBLE_DEVICES=GPU-your-spare-device-uuid \
HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
.venv-training/bin/python -m graphmine_agent.learning.finetune train \
  .graphmine-learning/new-adapter-run --execute

.venv-training/bin/python -m graphmine_agent.learning.finetune status \
  .graphmine-learning/new-adapter-run
```

On this host CUDA 13 requires the existing compatibility directory in
`LD_LIBRARY_PATH` (`.cuda-compat-13-0/usr/local/cuda-13.0/compat`, use its absolute
path). The trainer checks for one explicitly selected GPU with enough free
memory. QLoRA uses NF4 double quantization, BF16 computation, rank-16 adapters,
gradient checkpointing, microbatch one and four-step accumulation. The initial
pilot runs one epoch with a 1e-4 learning rate. These are pilot settings, not an
empirically selected optimum.

`status.json` distinguishes loading, actual optimizer steps, completion and
failure; `metrics.jsonl` records loss and gradient metrics. A checkpoint is saved
after the first two optimizer steps and every twelve steps. SIGTERM/SIGINT requests
a stop and checkpoint at the next optimizer-step boundary; allow enough shutdown
time for that boundary. Resume explicitly using `train RUN --execute --resume
RUN/checkpoints/checkpoint-N`. Never launch a second copy while a job is running.
Logs, checkpoints and the final `adapter/` remain local; there is no provider
upload, API-key fallback, merge into the base model, or automatic deployment.

Before deployment compare the completed adapter against the untouched base on
numerical correctness, semantic routing, empty/unsupported cases, corrections,
grounding, presentation and latency. Preserve the untouched source holdout for
that later comparison. Falling training loss alone is not evidence of a better
agent, and this small template curriculum does not establish broad domain-user
usability.

### Compare a completed routing adapter

Install `agent/evaluation-requirements.txt` into the isolated training environment.
The evaluator loads one NF4 base and switches its adapter off/on. This holds
weights, precision, prompt, tokenizer and required-field JSON schema constant.
The optional `serving_fp8` arm calls only the loopback model endpoint and is a
separate production reference, since precision and inference engine differ.

```bash
.venv-training/bin/python -m graphmine_agent.learning.adapter_eval prepare \
  .graphmine-learning/finetune-qwen27b-v3 \
  --corpus .graphmine-learning/finetune-corpus-v2 \
  --split validation --limit 4 --output .graphmine-learning/my-adapter-smoke

CUDA_VISIBLE_DEVICES=GPU-your-spare-device-uuid \
HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
.venv-training/bin/python -m graphmine_agent.learning.adapter_eval compare \
  .graphmine-learning/my-adapter-smoke \
  --output .graphmine-learning/my-adapter-smoke-results \
  --arms base_nf4 adapter_nf4 serving_fp8 --batch-size 2
```

Set the CUDA compatibility `LD_LIBRARY_PATH` as described above on this host.
After the development smoke test, prepare `--split test` without `--limit` to
include every reserved test case. New suite/result directories preserve prior
evidence. The evaluator rejects changed model, prompt, package and suite hashes.
Each case's raw output, parsed route, semantic failures and generation timing
are retained in `calls/`. `summary.json` includes paired improvements/regressions
and counts by family, behavior and operation; `status.json` records the process
and progress. An explicit `--resume` reuses saved outputs with the same contract,
and a process lock prevents overlapping runs. Confirm the prior process is
terminal before resuming.

The score checks clarification/refusal/execution, selected problem/operation,
exact effective filters, weight requirements, direction, temporal roles/units,
and additional analyses. It reports raw routing separately from capability
refusals enforced by the application. It does not grade explanatory wording,
later executable parameters, computed answers, or end-to-end user experience.
Synthetic test graph families are held out, but question templates are shared
with training. Local timing is amortized batch generation time, not a browser
response-time measurement.

For development checks outside the training wording, freeze the challenge suite
before inspecting its model outputs:

```bash
.venv/bin/python agent/evaluation/build_adapter_challenges.py \
  .graphmine-learning/adapter-test-suite-v2 \
  --output .graphmine-learning/my-adapter-challenges
```

The same `adapter_eval compare` command accepts this suite. Its 53 questions use
validation graphs and manually specified semantics; they are development and
operation-retention checks, not an independent final holdout. Run them only after
the selected GPU is free. Existing v1 safety phrasing is adapted to the fixture
vocabulary, with the source case hash and adaptation flag preserved.

After both complete comparisons, retain strict scores and produce a separate
review that ignores temporal-only fields on static operations and records
allowed read-only inspections separately:

```bash
.venv/bin/python -m graphmine_agent.learning.adapter_review \
  .graphmine-learning/adapter-test-suite-v2 \
  .graphmine-learning/adapter-test-nf4-v2 \
  .graphmine-learning/adapter-test-fp8-v2 \
  --output agent/evaluation/reports/adapter-test-review-2026-10-03.json
```

The review verifies every response/case binding and refuses incomplete runs.
Both original and revised scores remain visible. These corrections were defined
after inspecting early test outputs; the report records that fact. Complete
application testing remains necessary for inspection follow-through, native
parameters/results, answer quality and actual response latency.

The v2 review uses the production `route_blocker`: unsupported capabilities take
priority over requests for missing inputs. For the frozen challenge suite, three
legacy requests refer to attachments that the fixtures do not supply. Record
their expected clarification separately, without changing the original suite:

```bash
.venv/bin/python -m graphmine_agent.learning.adapter_review \
  .graphmine-learning/adapter-challenge-suite-v1 \
  .graphmine-learning/adapter-challenge-fp8-v1 \
  --label-audit agent/evaluation/reports/adapter-challenge-label-audit-2026-10-03.json \
  --output agent/evaluation/reports/my-challenge-audit.json
```

The audit verifies the suite and every affected case hash, applies identical
corrections to all supplied arms, and adds `audited_summary` alongside the original
strict and application-review scores. It removes no cases. Supply the completed
NF4 result directory too for the combined comparison. These labels were audited
after inspecting reference outputs, so this remains a development evaluation.
Every v2 report saves its review-source snapshot for reproducibility.

### Test the adapter inside the complete application

`adapter_workflows` creates a fresh embedded application for each arm and reuses
the existing workflow/native-result graders. Only routing uses the local NF4
base/adapter; planning, turn resolution and answer writing remain on the serving
model. The original API and store are not modified. Wait for other jobs on the
selected GPU to finish before starting this comparison.

```bash
CUDA_VISIBLE_DEVICES=GPU-your-spare-device-uuid \
HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
.venv-training/bin/python -m graphmine_agent.learning.adapter_workflows \
  .graphmine-learning/adapter-test-suite-v2 \
  --output .graphmine-learning/my-adapter-workflow-smoke \
  --arms base_nf4 adapter_nf4 serving_fp8 --case-id scope-corrections
```

Use the CUDA compatibility `LD_LIBRARY_PATH` described above. Omit `--case-id`
for all six synthetic development workflows; `--repeats 2` repeats complete
workflows. The default local input budget is 16,384 tokens, preserving the same
last-12-message history as the serving model and rejecting overlength inputs.
The output includes `protocol.json`, live `status.json`, per-arm evaluation
reports and isolated runtime histories, and `summary.json`.

For the existing real-data development cases, pass
`--real-corpus .graphmine-learning/real-world-corpus-v5` and
`--questions .graphmine-learning/real-world-questions-v3/questions.json`.
This reuses screened questions, independent result/attribute checks and
presentation checks. It does not call the reserved OpenFlights source holdout.
The local routing model and small native jobs share the selected GPU, so this
run does not measure concurrency or production throughput.

A separate `--arms serving_fp8` reference may use
`--reference-native-gpu GPU-...` to place its tiny native jobs on another device.
The UUID is validated and recorded in `protocol.json`. This override is rejected
for matched NF4 arms, keeping their placement identical. Ensure the chosen GPU
has capacity for the native jobs, and keep reference latency separate when its
GPU sharing differs. Use separate output directories for independent arms.

After all requested arms finish, verify coverage and summarize their unchanged
workflow grades, paired outcomes, recorded latency and failed-turn stage evidence:

```bash
.venv/bin/python -m graphmine_agent.learning.adapter_workflow_review \
  .graphmine-learning/adapter-workflows-nf4-v1 \
  .graphmine-learning/adapter-workflow-fp8-v2 \
  --output agent/evaluation/reports/my-adapter-application-comparison.json
```

The review requires both matched local arms, every expected turn and matching
case/code/inference contracts. It rejects partial runs and preserves the original
grades. Failed turns include hashed model-request evidence; a routing call's
presence alone does not establish that routing caused a failure. The same review
works for complete real-data or final-source runs; retain the earlier historical
real-data FP8 reference separately rather than labeling it a fresh third arm.

After completing development and fixing the candidate adapter, use the separate
final mode to consume all reserved source cases:

```bash
CUDA_VISIBLE_DEVICES=GPU-your-spare-device-uuid \
HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
.venv-training/bin/python -m graphmine_agent.learning.adapter_workflows \
  .graphmine-learning/adapter-test-suite-v2 \
  --output .graphmine-learning/my-final-adapter-holdout \
  --arms base_nf4 adapter_nf4 serving_fp8 \
  --real-corpus .graphmine-learning/real-world-corpus-v5 --final-holdout
```

Use the CUDA compatibility library path as above. Final mode rejects development
question files and case subsets. It records holdout consumption before the first
question, checks computed results and presentation, and sends no oracle feedback
to the model. Original contract questions may share familiar task types; this is
a source holdout. If these results guide further tuning, the source is no longer
an untouched test for that later candidate. Keep every report and its enclosing
adapter/protocol hashes. The default development commands remain unchanged.
