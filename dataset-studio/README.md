# Dataset Studio

A local web app for the GraphMine fine-tuning datasets. It does two jobs:

- **Review** end-to-end conversations: every training row generated for one
  question on one graph, shown in the order a live GraphMine chat happens, where
  you can review, tag, edit and delete each step.
- **Write** new conversations step by step, in a dataset of your own: write
  Understanding and Planning, run GraphMine to get the facts, then write the
  analyst answer against them. The studio replays each conversation through the
  real GraphMine agent, so every step you write gets the exact model input
  production would send and exports as a real training row.

Legacy planner steps are `RouteDecision` (**Understanding**), `PlanDraft`
(**Planning**) and `TurnDecision` (**Follow-up check**); analyst steps are
`GroundedNarrative` (**Analyst answer**). Current analytics contracts are
`AnalyticsRoute`, `AnalyticsPlan`, `AnalyticsPlanNormalized`, and
`AnalyticsAnswer`; validation uses the selected repository's production schema
builders with the example's runnable problem, input and fact context.

There is no build step and no CDN: a standard-library Python server and three
static files.

For the installed shared server, use the [environment workflow](../docs/ENVIRONMENTS.md).
It supplies separate storage and ports for production, development, and testing.
The commands below are for a standalone local instance.

## Run

```bash
cd dataset-studio
./run.sh users add NAME --admin   # once: the first admin (asks for a password)
./run.sh                          # http://127.0.0.1:8877/, then sign in
./run.sh --port 9000
./run.sh --host 0.0.0.0           # reachable from other machines
```

`run.sh` uses the containing GraphMine repository and its `.venv/bin/python`
when available. `GRAPHMINE_REPO` can select another checkout. With that interpreter the studio imports the agent, which it needs for two things:

- **Strict validation.** Edited outputs are checked against the agent's
  Pydantic models and re-serialized exactly as training targets are. Without
  the agent, browsing remains available, but unavailable or unknown schemas
  cannot be approved or exported as training rows.
- **Replay.** Writing conversations step by step needs the agent and the
  GraphMine binary (`library/build/graphmine`). The server prints whether
  replay is on, and the studio says so where it matters.

Options: `--repo` (default the containing GraphMine repository), `--data-root` (default
`<repo>/.graphmine-learning`), `--workspace` (default `./workspace`), `--host`
(default `127.0.0.1`), `--port` (default `8877`).
The default data root is created on first startup. An explicitly supplied
`--data-root` must already exist.

## Reviewed analytics workflow handoff

1. In the analytics workspace, complete a workflow, open **Review this example**,
   review its question, plan and result, and select **Download this reviewed
   workflow for Dataset Studio** before saving.
2. In Studio, open or create an authorized dataset and select **Import analytics**.
   Choose the downloaded JSON file (at most 4 MiB). Reimporting the same exchange
   returns its existing row.
3. Inspect **Review & evidence**, including the source reviewer, workflow revision,
   result hash and implementation hash. Approve the imported row locally, then
   export a new dataset version.

The handoff exports `AnalyticsPlanNormalized` rows under `sft/workflow/`. These
contain the normalized named-step workflow and a prompt derived from the reviewed
question and contracts. They are not a capture of the planner's original model
request or its positional `AnalyticsPlan` response format. Keep this adapter
separate when preparing model training. The legacy replay engine does not execute
these rows; changed plans must be executed and reviewed in the analytics workspace.

Exports preserve the full bounded result, original review, input fingerprints,
source attribution, local author/editor, reviewed revision and content hash in
`annotations.jsonl`, with per-file hashes in `manifest.json`. Unknown historical
authors remain unknown. Portable hashes verify integrity; they do not authenticate
an external file's claimed author, prove that an imported result was executed,
or check whether the upstream review was revoked after download. Local review
remains required. The HTTP export checks owner access, revision, review status,
result and implementation before downloading. It never runs a model or calculation.

Every example save, bulk edit, revert and export supplies the revisions shown in the UI.
A stale request returns HTTP 409 without writing. Content edits clear approval;
notes alone retain a matching review. Edits to analytics questions, plans or
context also invalidate their execution evidence. Invalid rows and stale reviews
are excluded from training export. Approved-only export is enabled by default;
analytics rows always require a current local approval. The export dialog retains
its opening revision snapshot, so changes from another tab require reopening it.

Run the isolated integration checks (requires the current checkout's test tools
and local Firefox/geckodriver for browser cases):

```bash
PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python -m pytest -q tests
```

These checks use temporary datasets and controlled saved evidence. They do not
exercise native or GPU execution or call a model. `GRAPHMINE_REPO` can select an
older checkout for legacy work; current analytics integration requires the new
`graphmine_agent.analytics_studio` module. The shared lossless JSON browser helper
is served from the selected repository.

## Sign-in, users and access

Everyone signs in. There are two roles:

| Role | Can |
| --- | --- |
| **admin** | Open every dataset; create users and admins, decide which datasets each user may open, reset passwords, disable or remove accounts (**Users and access…** in the account menu, top right) |
| **user** | Open the datasets granted to them; create their own datasets (they get access automatically) |

Anyone can create a dataset. Renaming or deleting one (**⋯** next to the picker)
is for admins and for the person who created it. Every change is recorded with
who made it: the History tab and the Changes view show it.

Each person has their own open dataset; two people working on the same dataset
see each other's changes after a refresh.

From the command line (useful for the first admin, or a forgotten password):

```bash
./run.sh users add NAME [--admin]   # asks for the password twice (or reads one line from stdin)
./run.sh users passwd NAME          # reset a password; signs that person out
./run.sh users list
./run.sh users delete NAME
```

How it is kept safe:

- **Passwords** are stored only as salted PBKDF2-SHA256 hashes (310,000
  iterations), in `workspace/auth/users.json`. The folder is readable by its
  owner only, and git ignores `workspace/`.
- **Sessions** are random tokens in an HttpOnly, SameSite=Strict cookie, valid
  for 7 days. Only their SHA-256 is saved (`workspace/auth/sessions.json`), so
  a restart keeps people signed in.
- **Logins:** five wrong passwords for one name lock it for 5 minutes. Changing
  a password, disabling or removing an account signs that person out. There is
  always at least one active admin.
- **Requests:** every data request must be JSON from a signed-in session, which
  keeps other web pages from acting for someone. The studio serves plain HTTP,
  so on an untrusted network put it behind HTTPS (for example an SSH tunnel or
  a reverse proxy).
- **Leaks:** templates and the case-graph library only draw from datasets the
  person may open.

## Your GraphMine conversations

GraphMine saves every question its users ask: the exact messages each model
call received, the raw response, the plan, the result, the answer and every
note, rating or correction (`graphmine_agent/capture.py`). Point the studio at
GraphMine's data root and each GraphMine user can review their own questions here:

```bash
GRAPHMINE_AGENT_DATA_ROOT=/data/labdata/wajid/graphmine_data/store ./run.sh
# For the rest of the group, over the network: HTTPS is required, GraphMine's certificate works
GRAPHMINE_AGENT_DATA_ROOT=... ./run.sh --host 0.0.0.0 --tls-certfile graphmine.crt --tls-keyfile graphmine.key
```

- **Sign in** with the GraphMine username and password. The studio checks them
  against GraphMine's account store read-only, on every sign-in, so a changed
  password or disabled account applies here too. A GraphMine password never
  signs in to a studio account of the same name; a studio account is linked
  only when both passwords match.
- **Only you** can open **My GraphMine conversations**. There is no admin
  override: admins cannot see, be granted or set a password for someone
  else's captured conversations.
- **One conversation per question**, in the order GraphMine ran it:
  Analytics routing → Analytics planning → GraphMine runs → Analytics answer.
  The **From GraphMine** card shows the data it ran on, what was computed, the
  answer the person saw and their feedback. Filter by **User feedback**
  (corrections, low ratings) to review the questions that went wrong first.
- **Each step is one training row**: the system and user messages exactly as
  GraphMine sent them, and the model's raw output (for plans, the positional
  format the model emits) as the target. **Edit output** changes only the target.
  An edit is checked against the contract GraphMine held the model to, so a
  plan naming an unknown problem or missing argument cannot be approved.
- **Edits flow forward.** A step's input came from the steps before it, so
  editing an earlier step holds back the later ones from training export.
  Delete them, or revert the edit.
- **New questions appear** on your next request. Captures are append-only, so
  your reviews and edits are kept; the studio copies them into its workspace
  (`workspace/graphmine-captures/`, owner-only) and keeps edits in the journal.

## Conversations

The list shows **Conversations** by default (switch to **Rows** for one entry
per training row). A conversation reads like the chat:

1. User question → **Understanding** → **Planning**
2. If Understanding asks for more information: the question GraphMine shows the
   user → the user's reply → **Understanding** → **Planning**
3. A boxed *retry after a failed attempt*, if the pipeline made one
4. ⚙ GraphMine runs the plan → **Analyst answer**
5. Boxed alternatives: *other requests to the analyst*, then *follow-up
   messages*, each one Follow-up check → (Understanding → Planning →) Analyst answer

A user message appears only when it changes. Earlier turns are context, not
trained: the question GraphMine asks and GraphMine's replies are shared by the
steps after them, so **Edit** on one of them updates every copy.

How steps are placed:

- **Clarifications.** The pipeline stores one clarification as two cases
  (`-business-ambiguous` + `-business-resolved`, or `-clarification-first` +
  `-clarification-reply`). The studio joins them by the exact opening question
  on the same graph source.
- **Follow-ups.** A step is a follow-up when its history already holds a
  finished answer, or when it is a Follow-up check. Earlier turns alone do not
  decide it, because production also sends the planner's messages as history to
  the main analyst answer.

**Progress.** Each conversation has one status, shown on its header and as a
filter:

| Status | Meaning |
| --- | --- |
| Needs understanding / Needs planning | That step is missing |
| Ready to run | The plan is ready; GraphMine has not run it in the studio yet |
| Needs analyst answer | GraphMine has run (or, for data that cannot be replayed, the plan is ready) |
| Waiting for the user's reply | The last step asks the user for information |
| Refused | The agent refuses (unsupported request or plan) |
| Complete | The conversation has its analyst answer |

A stage only counts when the dataset has that kind of step at all. For example,
a routing-only dataset is complete after Understanding. A dataset made in the
studio expects every stage. The end of the main path shows the matching
**Next** card, described below.

Each step has its own review buttons, **Edit output**, **Delete** (restorable
until export) or **Discard** (steps written here), and **Details →** with its
model input, diff and history. Tags, review and labels at the top apply to every
step. Editing the question (`q`) updates it in every step that uses that
wording. **Duplicate** (`c`) copies a whole conversation; original steps keep
their model context, so the copy is a good start for a variation.

## Writing conversations step by step

1. **＋ New empty dataset…** at the bottom of the dataset picker creates and
   opens a dataset of your own. **⋯** next to the picker renames, describes or
   deletes it.
2. **＋ Add** (`n`) opens the builder:
   - Choose the **graph and domain**: a graph already in the dataset, a small
     graph from the pipeline's *case library*, or an upload (a GraphMine `.json`
     graph or a `.csv`/`.tsv` edge list, accepted only if the agent's own
     ingestion reads it).
   - Write the question. **Show model input** displays what the agent sends for
     Understanding before you write it.
   - Fill in as many steps as you like. A step left empty is skipped, and
     **Load template** copies a real output, from this dataset or another.
3. The conversation builds automatically. Every step gets its model input, and
   a **Next** card at the end shows what comes next with that step's real input:
   - **Next: Planning.** Write it in place.
   - **Next: run GraphMine.** Runs the plan; results are cached by plan and graph.
   - **Next: Analyst answer.** Shows the computed facts to cite.
   - **Next: the user's reply.** Shows the question GraphMine asks, derived
     from the Understanding output.
4. **+ Add steps** adds missing steps or follow-up messages to an existing
   conversation.

Text the agent derives is never typed in: the clarification question shown to
the user, the analyst's request (the objective from Understanding) and
GraphMine's replies all come from the agent when the conversation builds.

The **Model inputs** card on each conversation shows the graph, domain and build
status, offers **Build** / **Run GraphMine**, and lists what the agent reported.
Examples: "With this output the agent does not ask the user anything",
"Not reached", or "The agent rejects this answer: it cites facts that are not
in the computed result". A conversation containing steps written here rebuilds
after every content edit. If it changed since its last build, its steps say
*out of date* until the next build.

The same works in pipeline datasets: a step you add to a recorded conversation
is replayed on that case's own graph.

### How a replay works

`studio_engine.py` creates a throwaway agent session on the conversation's
graph and domain. It drives the agent's own planning, chat and interpretation
code with a *forcing model*: at each model call, the forcing model records the
exact messages production would send (system prompt, the last 12 conversation
messages, user payload) and returns the output written in the studio. Ready
plans pass the agent's execution check and run with the GraphMine binary.

Consequences:

- **Downstream inputs follow your outputs**, the way they would follow a
  perfect model's.
- **A missing output stops that branch.** Its input is still recorded, which is
  what the Next card shows.
- **Repeated calls.** When the agent asks a stage again (a scope review or a
  repair), only the first input is the training input.
- **History.** The analyst and follow-up steps include the conversation history
  production sends. Rows recorded by the learning pipeline omit it.

## Browse, coverage and changes

| View | Features |
| --- | --- |
| **Browse** | Filters with live counts: model, split, stage, expected outcome, single/multi-turn, asks for more info, progress, family, topic, problem, implementation, review, labels, validation, changes, tag source, variant, graph source. Sort by file order, question, problem, issues, recently edited or output length. In Conversations mode a count is a number of conversations. |
| **Step details** | One step: earlier turns, the final user message and the highlighted training target. Tabs: *Model context* (the payload, system prompt and, for steps written here, the replayed history and whether it is current), *Diff vs original*, *History*. |
| **Tag** | Topic (documentation), runnable problem and implementation (auto-detected; manual overrides are marked and **Reset to auto** clears them), review state, labels and notes. |
| **Bulk** | Select conversations or rows to set tags, review state or split, add a label, delete or restore. |
| **Coverage** | Stat tiles, a problem × stage heatmap over all catalog problems, examples per implementation, most reused questions, graph sources and their splits. |
| **Changes** | Every pending change; open or undo each one. |
| **Export** | Writes a new dataset version (below). |

Light and dark themes follow the OS, or toggle with ◐. The layout works down
to phone width.

### Search syntax

Free text matches the question, turns, output JSON, notes, labels, tags and ID.
Field filters match by substring and can be combined; prefix one with `-` to
exclude it:

```
op:k-core  problem:clique  impl:gleiden  stage:PlanDraft  split:validation
model:analyst  review:needs_fix  label:checked  status:needs_information
progress:ready  progress:"needs analyst"  progress:waiting  kind:new
lineage:email-eu-core  variant:custom_chart  id:dual-0004
has:clarify  has:turns  has:errors  has:warnings  has:notes  has:manual  has:edits
-split:train   "exact phrase"
```

### Keyboard

`/` search · `j`/`k` or arrows: conversations (rows in Rows mode) · `[`/`]`
steps · `x` select · `e` edit the focused output · `q` edit the question · `c`
duplicate the conversation · `n` add a conversation · `1`–`4` review ·
`Del` delete/restore · `Ctrl+S` save · `Esc` cancel or leave step details ·
`g` coverage · `?` help.

## Where data goes

Pipeline datasets are never modified. The studio keeps everything for them in
`workspace/<dataset>/`: the edit journal, conversation settings for steps
added there, replay files and exports.

A dataset made in the studio keeps everything in its own folder,
`<data root>/studio-datasets/<name>/`:

| Path | Contents |
| --- | --- |
| `studio-dataset.json` | Name, description, creation time |
| `journal.jsonl` | Every step, as the complete state after each change |
| `conversations.json` | Each conversation's graph and domain |
| `graphs/` | Graphs used by its conversations (library copies and uploads) |
| `engine/context/` | The last build of each conversation: every step's model input, the next steps' inputs, the facts, the agent's reports |
| `engine/runs/` | Cached GraphMine results, keyed by plan, graph and binary |
| `exports/` | Exports |

Deleting a studio-made dataset moves its folder to `studio-datasets/.deleted/`;
move it back to restore it.

**Export** writes `<exports>/<name>/`:

| File | Contents |
| --- | --- |
| `sft/<planner\|analyst\|workflow>/<split>.jsonl` | Standard chat `messages` rows. Unchanged message content is preserved. Edited legacy outputs use canonical serialization, and question edits also update exact copies inside the hidden payload. Steps written here, once their conversation's build is current, are the replayed messages plus the output. Normalized analytics workflows use the separate `workflow` adapter. |
| `sft-index.jsonl` | Row identity, file, row number, `row_sha256`, source graph, `conversation`, `origin` (original / annotated / edited / clone / studio-replay) and the source row's hash |
| `annotations.jsonl` | Tags, review state, labels, notes, authorship, reviewed content/revision, analytics execution evidence and prior Studio attribution retained across export/import cycles |
| `needs-context.jsonl` | Steps written here without a current model input, with the `reason` (not built, not reached by the last build, changed after it) and their `conversation` |
| `changes.jsonl` | The full edit journal |
| `manifest.json` | Base dataset, options, counts, warnings, and SHA-256 plus size of every file |

Options: leave out rejected steps and approved-only (both enabled by default). Deleted steps
are never exported. The export dialog shows beforehand how many written steps
become training rows.

**Training with an export:** `agent/graphmine_agent/learning/dual_finetune.py`
checks its own `provenance.json` format and does not read this export
directly. Pass the export through the learning pipeline (or add a reader for
this manifest) instead of hand-writing a provenance file.

## Notes and limits

- **Detected datasets:** any folder under the data root (depth ≤ 3) with
  `sft-index.jsonl` + `sft/` (reusable layout), `provenance.json` +
  `train.jsonl` (older flat layout), or `studio-dataset.json` (made in the
  studio). Model, runtime and hidden folders are skipped.
- **Names:** the picker shows names and groups from `dataset-names.json`, keyed
  by path. Folders are never renamed, so journals and training paths stay valid.
  Restart after editing that file. Datasets made in the studio carry their own
  name.
- **Replay coverage:** recorded flat datasets (no cases) cannot be replayed;
  their steps keep their recorded inputs. The Next card covers the main path.
  For a follow-up, use **+ Add steps**; the follow-up's inputs appear in its
  steps' *Model context* after a build.
- **Multi-step plans:** a plan with supporting analyses runs every step; a
  follow-up that plans again uses its first plan.
- **Open dataset:** each person has their own; all of one person's tabs share it.
- **Splits:** "This question text also appears in another split" is
  informational. The held-out unit is the graph source, and a step written here
  takes its conversation's graph as its source.
- **Annotations:** labels, review state and tags are annotations. Training rows
  change only when the question, turns, output or split change.
