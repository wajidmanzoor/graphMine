# GraphMine and Dataset Studio integration plan

Saved: 2026-10-15. Status: planned for later implementation.

Connect GraphMine's saved conversations, feedback and notes to the existing
Dataset Studio. People should also be able to author complete conversations
there. Reviewers correct and approve examples, which can then enter a versioned
dataset for training later. Review and export do not start training or replace
the running model.

The central requirement is to distinguish who authored each piece, its role in
the conversation, the model's actual input and output, and what the application
displayed to the user.

## Existing foundations

GraphMine already saves conversation turns, feedback, corrections, ratings,
notes and workflow results. Feedback is linked to its source conversation and
turn. Workflow example approval currently supports planning hints; it is not a
complete training approval and export workflow.

The separate `dataset-studio` application already supports conversation and
step review, manual authoring, editing, notes, tags, review states, user access,
change history, replay and versioned exports. Extend that application.

Studio currently replays the older `RouteDecision`, `PlanDraft`, `TurnDecision`
and `GroundedNarrative` flow. Its export offers an optional approved-only filter,
and validation errors can become export warnings. The existing trainer does
not directly consume Studio's export manifest. These are integration gaps to
address before training from current application conversations.

## Conversation sources and authorship

Support captured GraphMine conversations, entirely human-authored Studio
conversations, and edited or mixed conversations. Preserve the original source
and each revision rather than overwriting the original conversation.

Record these dimensions independently for every message or step:

| Dimension | Information to preserve |
| --- | --- |
| Conversation role | User, assistant, system or tool, where applicable |
| Author | Human account, model and adapter version, application code or execution tool |
| Origin | Captured session, Studio authoring, imported record, or a revision of an earlier item |
| Presentation | Shown in chat, shown in a result or status component, or internal only |
| Training use | Input context, proposed target, evidence, or review annotation |
| Source links | Conversation, turn, workflow, dataset, execution and parent revision identifiers |
| Review | Decision, reviewer, time and the exact content revision approved |

An assistant role does not establish model authorship. For example, a person
writing both sides of a conversation produces an assistant answer labeled
**Role: Assistant; Author: Human; Source: Studio; Status: Unreviewed**.
Replaying that answer through GraphMine retains its human authorship. Unknown
authorship in older imports stays explicitly unknown.

| Content | Intended handling |
| --- | --- |
| User question or follow-up | Model input; distinguish live user input from an authored example |
| Original model output | Preserve the actual output and model identity for review |
| Corrected or ideal answer or plan | Human-authored proposed target, linked to any original output |
| Computed graph results | Execution evidence with input and result provenance |
| App text, charts and status messages | Display content linked to the model, tool and template components that produced it |
| Feedback, notes and review decisions | Review metadata, outside training targets |

Keep raw model output separate from displayed content. If the app combines
model text, computed facts and a template, preserve those component links and
the relevant application version. Distinguish a captured display from a preview
reconstructed later. Manually entered result claims are unverified until checked
against the relevant data and execution.

## Studio integration and review

Add a GraphMine conversations source in Studio. Make saved conversations
browsable and prioritize turns with feedback, corrections or low ratings.
Bring existing records into the same flow. Stable source IDs must prevent
duplicate imports, and refreshes must preserve Studio edits and reviews.
Respect conversation ownership and Studio dataset access when importing.

Use three linked views:

- **Conversation preview:** what the user saw or what an authored conversation
  would display, clearly labeled as captured or reconstructed.
- **Model steps:** the exact inputs and outputs for each step, with authorship
  badges such as Model generated, Human authored and Human edited.
- **Review:** feedback, notes, corrections, evidence checks and approval history.

Retain Studio's existing `unreviewed`, `needs_fix`, `approved` and `rejected`
states. Review is available for individual steps and whole conversations.
Whole-conversation approval applies only to the exact eligible step revisions
reviewed. A complaint or rating identifies a candidate; it is not itself a
correct target answer.

Allow a person to write a complete conversation, including user questions,
assistant answers and follow-ups. Preserve who supplied each part. Missing
model inputs or execution evidence keep affected steps pending. Rebuild inputs
through the current GraphMine pipeline as necessary, without presenting a
replay as an actual model prediction.

Content edits invalidate approval for the changed target and any downstream
steps whose inputs or evidence changed. Preserve prior decisions in the audit
history. Changing a review note alone should not invalidate unrelated content.

## Dataset export and training

A training export must require approved, valid examples with current inputs.
Treat validation errors, missing context and stale replay results as blockers
for the affected examples. Keep incomplete examples available for further
review rather than silently treating them as training rows.

Export only context available at the relevant point in the conversation and
the approved target for that step. Reviewer notes and later corrections must
not leak into earlier model inputs. App status messages and presentation
wrappers are not model targets; app-derived content can appear as context only
where the real pipeline would provide it.

Build immutable dataset versions with manifests linking each row to its source,
authorship, reviewed revision and evidence. Separate planner and analyst
targets using the current runtime formats. Deduplicate examples, keep related
conversations and source graphs together when assigning training and validation
splits, and preserve held-out evaluation exclusions.

Add a trainer reader for Studio's manifest and enforce the same eligibility
checks at training ingestion. Later training runs should record the dataset
version, base model, adapter lineage, configuration and evaluation results.
Training and promotion of an adapter remain separate explicit actions.

## Storage

Keep conversation data, Studio records and training datasets under
`/data/labdata/wajid/graphmine_data`. Keep model weights and adapters under
`/data/labdata/wajid/graphmine-models`.

The application currently uses `graphmine_data/store`. Proposed additional
locations are `graphmine_data/dataset-studio/workspace` for Studio state and
`graphmine_data/datasets` for authored datasets and versioned exports. Preserve
existing Studio users, journals and references during any move. Legacy datasets
under `graphmine-models/learning` must remain accessible until their data and
references have been migrated and verified.

## Implementation order

1. Define message and step provenance, revision links, and approval rules.
   Preserve unknown provenance in older records.
2. Connect saved GraphMine conversations and annotations to Studio, including
   existing data, access checks and imports that can safely be repeated.
3. Extend the existing authoring and review views with origin labels and the
   distinction between captured display, replay and actual model output.
4. Add replay and validation support for the current native analytics pipeline,
   including downstream invalidation when content changes.
5. Produce approved-only, validated dataset versions and verify their manifests.
6. Connect the trainer later, then evaluate adapters before any promotion.

The first usable release should complete collection, human authoring, review
and valid dataset export. Training controls can follow.

## Acceptance checks

- A live question with feedback appears once in Studio with the correct turn,
  original answer, notes and results; refreshing preserves review edits.
- A fully human-authored conversation retains human authorship on both user
  and assistant turns, including after replay and export.
- A corrected model answer preserves the original model output, editor identity,
  correction and approval revision.
- App-derived messages and computed results remain distinguishable from model
  output and human-authored targets in both the UI and exports.
- Editing an earlier question, plan or result invalidates affected downstream
  inputs and approvals until rebuilt and reviewed.
- Unreviewed, rejected, invalid, stale and evaluation-only records cannot enter
  training through either export or trainer ingestion.
- Users can access only authorized source conversations and Studio datasets.
- Every exported row is traceable to its reviewed revision, and an authored
  conversation can qualify through the same review process as a captured one.

## Code entry points

- [Conversation and feedback storage](../agent/graphmine_agent/database.py)
- [Conversation and feedback API](../agent/graphmine_agent/api.py)
- [Current workflow example review](../agent/graphmine_agent/analytics_examples.py)
- [Current analytics planning](../agent/graphmine_agent/analytics_planning.py)
- [Existing trainer](../agent/graphmine_agent/learning/dual_finetune.py)
- Studio is the sibling application at `../dataset-studio` relative to the
  repository root. Its entry points are `README.md`, `studio.py`,
  `studio_engine.py`, `static/app.js` and `static/index.html`.
