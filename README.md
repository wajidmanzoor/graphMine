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

Planner steps are `RouteDecision` (**Understanding**), `PlanDraft`
(**Planning**) and `TurnDecision` (**Follow-up check**); analyst steps are
`GroundedNarrative` (**Analyst answer**). The labels are the agent's own.

There is no build step and no CDN: a standard-library Python server and three
static files.

## Run

```bash
cd dataset-studio
./run.sh                     # http://127.0.0.1:8877/
./run.sh --port 9000
./run.sh --dataset business-routing-data-v1
./run.sh --host 0.0.0.0      # reachable from other machines: prints a link with an access token
```

`run.sh` uses `../graphMine-repo/.venv/bin/python` when it exists. With that
interpreter the studio imports the agent, which it needs for two things:

- **Strict validation.** Edited outputs are checked against the agent's
  Pydantic models and re-serialized exactly as training targets are. Without
  the agent, only catalog and structural checks run.
- **Replay.** Writing conversations step by step needs the agent and the
  GraphMine binary (`library/build/graphmine`). The server prints whether
  replay is on, and the studio says so where it matters.

Options: `--repo` (default `../graphMine-repo`), `--data-root` (default
`<repo>/.graphmine-learning`), `--workspace` (default `./workspace`), `--host`
(default `127.0.0.1`), `--port` (default `8877`), `--token`, `--no-token`.

**Access token.** On any host other than localhost, every data request needs a
token. It is generated once, kept in `workspace/.studio-token` (so bookmarked
links keep working) and printed as part of the link at startup. Opening that
link stores the token in the browser. Pass `--token` to choose one, or
`--no-token` to serve without one (anyone on the network could then edit).

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
| **Browse** | Filters with live counts: model, split, stage, expected outcome, single/multi-turn, asks for more info, progress, problem, operation, implementation, review, labels, validation, changes, tag source, variant, graph source. Sort by file order, question, problem, issues, recently edited or output length. In Conversations mode a count is a number of conversations. |
| **Step details** | One step: earlier turns, the final user message and the highlighted training target. Tabs: *Model context* (the payload, system prompt and, for steps written here, the replayed history and whether it is current), *Diff vs original*, *History*. |
| **Tag** | Problem, operation and implementation (auto-detected; manual overrides are marked and **Reset to auto** clears them), review state, labels and notes. |
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
| `sft/<planner\|analyst>/<split>.jsonl` | Standard chat `messages` rows. Unchanged rows are byte-identical to the source. Edited outputs use the canonical serialization (`model_dump_json` in strict mode), and question edits also update exact copies inside the hidden payload. Steps written here, once their conversation's build is current, are the replayed messages plus the output. |
| `sft-index.jsonl` | Row identity, file, row number, `row_sha256`, source graph, `conversation`, `origin` (original / annotated / edited / clone / studio-replay) and the source row's hash |
| `annotations.jsonl` | Tags, review state, labels and notes for every exported step |
| `needs-context.jsonl` | Steps written here without a current model input, with the `reason` (not built, not reached by the last build, changed after it) and their `conversation` |
| `changes.jsonl` | The full edit journal |
| `manifest.json` | Base dataset, options, counts, warnings, and SHA-256 plus size of every file |

Options: leave out rejected steps (default) and approved-only. Deleted steps
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
- **Server-wide state:** the open dataset is shared; switching it in one tab
  switches it for every tab.
- **Splits:** "This question text also appears in another split" is
  informational. The held-out unit is the graph source, and a step written here
  takes its conversation's graph as its source.
- **Annotations:** labels, review state and tags are annotations. Training rows
  change only when the question, turns, output or split change.
