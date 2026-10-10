# Dataset Studio

A small local web app for browsing, tagging and editing the GraphMine fine-tuning
datasets: planner (`RouteDecision`, `PlanDraft`, `TurnDecision`) and analyst
(`GroundedNarrative`) rows. Each example appears as a short conversation: the
user's plain-English question, any earlier clarification turns, and the expected
Qwen output JSON, which is the training target. The system prompt and the large
hidden context stay out of the way. You can open them on demand in **Model
context**.

There is no build step and no CDN. The server uses only the Python standard
library. The front end is three static files.

## Run

```bash
cd dataset-studio
./run.sh                 # opens the newest dataset, http://127.0.0.1:8877/
./run.sh --port 9000     # another port
./run.sh --dataset business-routing-data-v1
```

`run.sh` uses `../graphMine-repo/.venv/bin/python` when it exists. With that
interpreter the app imports the agent's real Pydantic models, so every edited
output is checked against the same `RouteDecision` / `PlanDraft` / `TurnDecision`
/ `GroundedNarrative` schemas the agent uses, and is re-serialized exactly as
training targets are. With plain `python3` it falls back to catalog and
structural checks. The status bar shows which mode is active.

Options: `--repo` (GraphMine repository; default `../graphMine-repo`),
`--data-root` (default `<repo>/.graphmine-learning`), `--workspace` (default
`./workspace`), `--host` (default `127.0.0.1`; there is no authentication, so
keep it local), `--port` (default `8877`).

## What you can do

| View | Features |
| --- | --- |
| **Browse** | Faceted filters with live counts: model, split, stage, expected outcome (ready / needs information / clarify / unsupported …), single vs multi-turn, *asks for more info*, analyst answer (has / missing, per conversation), problem (grouped by category), operation, implementation, review state, labels, validation, change type, tag source, variant, graph source. Search with field syntax (below). Sort by file order, question, problem, issues, recently edited or output length. The list shows **Conversations** by default: one entry per question on one graph, holding every stage generated for it (understanding, planning, analyst answers, follow-up branches, retries). Facet counts then count conversations. Switch to **Rows** for one entry per training row. Entries load 150 at a time as you scroll. |
| **Conversation** | The whole case as one thread, in the order GraphMine produces it in a live chat. Stages use the agent's own names: **Understanding** (`RouteDecision`), **Planning** (`PlanDraft`), **Analyst answer** (`GroundedNarrative`) and **Follow-up check** (`TurnDecision`). The thread runs: the question → Understanding → Planning; if Qwen asked for clarification, its question → the user's reply → Understanding → Planning; a boxed *retry after a failed attempt*, if any; ⚙ GraphMine runs the plan → Analyst answer. Then come boxed alternatives: *other requests to the analyst*, and *follow-up messages* (each one is Follow-up check → Analyst answer for the same message). A user message appears only when it changes. The pipeline stores a clarification as two cases (`-business-ambiguous` + `-business-resolved`, or `-clarification-first` + `-clarification-reply`). The Studio joins them into one conversation by matching the exact opening question on the same graph source. Each step is still its own training target: it has its own review buttons, inline **Edit output**, and **Details →** for model context, diff, history, notes, clone and delete. Tags, review and labels at the top apply to every step. Editing the question (`q`) updates it in every step that uses that exact wording, including earlier-turn context. |
| **Step details** | One training row, as in Rows mode. Chat-style thread: earlier turns (context, not trained), the final user message, and the highlighted **training target**. Outputs show as a collapsible tree or highlighted JSON. Tabs for *Model context* (task, graph, selected operation, intent, the analyst's computed facts, system prompt, full payload), *Diff vs original* and *History*. Links jump to the other stages of the same case. |
| **Tag** | Problem (all 37 catalog problems; ⊘ = no validated backend), operation (filtered by problem) and implementation (that operation's validated backends with capabilities). Tags are auto-detected from the source case and the backend the reference run actually used. Manual overrides are marked, and **Reset to auto** clears them. Review state: unreviewed / approved / needs fix / rejected. Free-form labels and reviewer notes. |
| **Edit** | Question (`q`), earlier turns (add or remove clarification pairs), expected output (`e`) in a JSON editor with live parsing and server-side schema validation. A target that fails validation needs explicit confirmation before saving. |
| **Add** | **Clone** (`c`) copies an existing example *with its full model context*, then you edit the question and output; the clone exports as a complete training row. **Add** (`n`) builds a whole conversation from scratch, laid out in chat order: the question; optionally Understanding asking for more information, Qwen's clarification question and the user's reply; Understanding; Planning; the request to the analyst and the Analyst answer; and any number of follow-ups (message → Follow-up check → Analyst answer). Each Qwen output has a JSON editor with live validation and **Load template**; a step left empty is skipped. The steps share one conversation id. They have no model context, so they go to `needs-context.jsonl`. **+ Add steps** in a conversation (or **+ Add analyst answer** on its *missing* placeholder) opens the same builder for that conversation, offering only the steps it lacks plus follow-ups. New steps join that conversation and use its split and tags. |
| **Delete / revert** | Soft delete (restorable until export), revert an edited row, discard an added row. |
| **Bulk** | Select conversations or rows (`x` or checkboxes, or select all visible; a conversation selects all its steps) to set problem, operation, implementation, review state or split, add a label, delete or restore. |
| **Coverage** | Stat tiles (examples, distinct questions, review progress, clarification rows, validation, pending changes), a problem × stage heatmap over all 37 problems with hover details and click-through, examples per implementation (validated backends with zero examples included), most reused questions, graph sources and their splits. Optionally limited to the current filters. |
| **Changes** | Every pending change with time, kind and changed fields; open or undo each one. |
| **Export** | Writes a new dataset version (see below). |
| **New dataset** | **＋ New empty dataset…** at the bottom of the dataset picker asks for a name and an optional description, then creates the dataset and opens it, ready for **Add**. **Load template** copies from the open dataset when it has a matching step, otherwise from the other datasets (the toast names the source). |

Light and dark themes follow the OS, or toggle with the ◐ button. The layout
works down to phone width.

### Search syntax

Free text matches the question, turns, output JSON, notes, labels, tags and ID.
Field filters match by substring and can be combined; prefix one with `-` to
exclude it:

```
op:k-core  problem:clique  impl:gleiden  stage:PlanDraft  split:validation
model:analyst  review:needs_fix  label:checked  status:needs_information
lineage:email-eu-core  kind:edited  variant:custom_chart  id:dual-0004
has:clarify  has:turns  has:errors  has:warnings  has:notes  has:manual  has:edits
answer:missing  has:answer  -has:answer   (conversations with / without an analyst answer)
-split:train   "exact phrase"
```

### Keyboard

`/` search · `j`/`k` or arrows to move between conversations (rows in Rows mode) ·
`[`/`]` previous/next step in a conversation · `x` select · `e` edit the focused
step's output · `q` edit question · `c` clone · `n` add · `1`–`4` review the
focused step · `Del` delete/restore · `Ctrl+S` save editor · `Esc` cancel or leave
step details · `g` coverage · `?` help.

Conversations are only a view. Export still writes every step as a separate
training row, exactly as before.

## Where changes go

The source dataset is never modified. Each change is appended to
`workspace/<dataset>/journal.jsonl` as the complete new state of that example,
so the history is replayable and nothing is lost when the app restarts. An
index cache (`index-cache.json`) is rebuilt automatically when source files
change.

**Export** writes `workspace/<dataset>/exports/<name>/`:

| File | Contents |
| --- | --- |
| `sft/<planner\|analyst>/<split>.jsonl` | Standard chat `messages` rows. Unchanged rows are **byte-identical** to the source. Edited outputs use the canonical compact serialization (`model_dump_json` in strict mode). Question edits also update exact copies of the old text inside the hidden payload (for example `application_intent.objective`). |
| `sft-index.jsonl` | Row identity, file, row number, canonical `row_sha256`, source graph, `origin` (original / annotated / edited / clone) and the source row's hash |
| `annotations.jsonl` | Effective, auto and manual tags, review state, labels and notes for every exported example |
| `needs-context.jsonl` | Steps added from scratch (question, turns, expected output, tags), in chat order, each with its `conversation` id, for the data pipeline to complete with real context. A step added to an original conversation carries that conversation's case id. |
| `changes.jsonl` | The full edit journal |
| `manifest.json` | Base dataset, base manifest hash, options, counts, warnings, and SHA-256 plus size of every file |

Options: leave out rejected examples (default on) and approved-only.
Deleted examples are never exported.

**Training with an export:** `agent/graphmine_agent/learning/dual_finetune.py`
verifies its own `provenance.json` format and implementation fingerprint. It
does not read this export directly. Pass the export through the learning
pipeline (or add a reader for this manifest) instead of hand-writing a
provenance file.

## Notes and limits

- Detected datasets: any folder under the data root (depth ≤ 3) with
  `sft-index.jsonl` + `sft/` (current reusable layout) or `provenance.json` +
  `train.jsonl` (older flat layout), or a `studio-dataset.json` marker (made
  empty in the studio). Large model and runtime folders are skipped.
- Datasets made in the studio: the folder is `<data root>/studio-datasets/<name>/`
  and holds only the marker (name, description, creation time). Like edits to
  any dataset, its conversations live in `workspace/<dataset>/journal.jsonl`, so
  keep the workspace. Every step has no model context, so an export writes
  them all to `needs-context.jsonl`. To remove such a dataset, delete both its
  folder and its workspace folder, then restart the Studio.
- Dataset names: the picker shows the name and group from `dataset-names.json`,
  keyed by the dataset's path under the data root. The path and a description
  appear in the tooltip. A dataset without an entry shows its path. Folders are
  never renamed, so workspaces and training paths stay valid. Restart the
  Studio after editing the file.
- The open dataset is server-wide: switching it in one browser tab switches it
  for every tab.
- "This question text also appears in another split" is informational. In the
  current data the held-out unit is the graph source, and template questions
  are reused across sources.
- Labels, review state and tags are annotations. Training rows only change
  when you edit the question, turns, output or split.
