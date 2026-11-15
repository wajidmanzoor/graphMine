# Latter plans

## Dataset Studio: an edit layer over original GraphMine conversations

Recorded: 2026-11-15. Status: planned; not implemented.

### User's design

GraphMine should remain the source of the original conversations. Dataset
Studio should read those conversations directly and save a separate layer of
edits and reviews, without keeping another permanent copy of the conversation
content.

- Read the original captures from
  `/data/labdata/wajid/graphmine_data/store/captures/`.
- Identify each source conversation and model call using stable account,
  session, turn, and capture IDs.
- Save only references, changed fields, review decisions, annotations, and
  revision metadata in Studio's edit layer.
- Combine the original capture with the latest edits when displaying an
  example. Preserve the original GraphMine capture.
- Generate complete training examples only when the user requests an export.
  Routine browsing and review should not create duplicate `train.jsonl` files.
- Allow new GraphMine captures to appear without losing existing reviews or
  edits. Keep account ownership checks on both source captures and edits.

The intended flow is:

```text
Original GraphMine capture + Studio references and edits -> review view
Original GraphMine capture + Studio references and edits -> requested export
```

### Difference from the current implementation

Studio currently materializes model inputs and outputs into local training
files under `workspace/graphmine-captures/`, with indexes and schemas. Its
`journal.jsonl` then overlays those local rows. The planned design replaces
that persistent copy with references to the original captures.

Relevant implementation: `dataset-studio/studio_captures.py` and
`dataset-studio/studio.py`.

### Storage location

Keep growing Studio data outside the code checkout, under a dedicated folder:

```text
/data/labdata/wajid/graphmine_data/dataset-studio/
  workspace/  # Source references, edit journals, reviews, indexes, login state
  datasets/   # Examples and graph files created or uploaded directly in Studio
  exports/    # Complete training files generated on request
```

Use configurable storage paths. Journals, exports, uploaded graphs, and replay
results should all live on the data disk. Small rebuildable indexes may be
cached, but should avoid duplicating full conversation payloads. Studio-created
examples need their own stored content because no original GraphMine capture
exists for them.

### Migration and verification

- Preserve existing edits, reviews, source IDs, ownership, and Studio-created
  examples while converting the current materialized rows to references.
- Verify that the reconstructed review view and exported examples preserve the
  same inputs, outputs, and annotations before removing the redundant copies.
- Handle a missing or changed source explicitly; do not silently discard edits
  or associate them with a different conversation.
- If journals become large, consider snapshots or compaction with an explicit
  history-retention policy. Moving the files alone does not reduce journal size
  or replay cost.
