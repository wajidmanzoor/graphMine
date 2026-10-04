from __future__ import annotations

import json

import pytest
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning.corpus import digest
from graphmine_agent.learning.finetune import (
    assistant_only_tokens,
    read_training_export,
)
from graphmine_agent.llm import ROUTING_SYSTEM_PROMPT
from graphmine_agent.models import RouteDecision


class Tokenizer:
    def apply_chat_template(self, messages, *, add_generation_prompt, **kwargs):
        value = "".join(f"<{m['role']}>{m['content']}!" for m in messages)
        if add_generation_prompt:
            value += "<assistant>"
        return list(value.encode())


def test_only_assistant_tokens_receive_loss_and_nothing_is_truncated():
    messages = [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]
    row = assistant_only_tokens(Tokenizer(), messages, 100)
    assert bytes(x for x in row["labels"] if x != -100) == b"answer!"
    assert len(row["labels"]) == len(row["input_ids"]) == len(row["attention_mask"])
    with pytest.raises(ValueError, match="no silent truncation"):
        assistant_only_tokens(Tokenizer(), messages, 10)


def test_changed_chat_template_fails_closed():
    class BadTokenizer(Tokenizer):
        def apply_chat_template(self, messages, **kwargs):
            return [len(messages), 42, 43]

    with pytest.raises(ValueError, match="prefix mismatch"):
        assistant_only_tokens(
            BadTokenizer(), [{"role": "user"}, {"role": "assistant"}], 100
        )


def make_export(root):
    row = {
        "messages": [
            {"role": "system", "content": ROUTING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "graph_metadata": {},
                        "application_preprocessing": {},
                        "pending_request": None,
                    }
                ),
            },
            {
                "role": "assistant",
                "content": RouteDecision(
                    supported=False, confidence=1, explanation="Please clarify"
                ).model_dump_json(),
            },
        ]
    }
    metadata = {"quarantine": [], "files": {}, "rows": []}
    for split, family in (("train", "random"), ("validation", "cycle_chords")):
        path = root / f"{split}.jsonl"
        path.write_text(json.dumps(row) + "\n")
        metadata["files"][split] = HistoryStore.digest(path)
        metadata["rows"].append(
            {
                "id": split,
                "stage": "RouteDecision",
                "split": split,
                "family": family,
                "row_sha256": digest(row),
            }
        )
    HistoryStore.write(root / "provenance.json", metadata)
    return metadata


def test_training_export_revalidates_saved_hashes(tmp_path):
    make_export(tmp_path)
    _, rows = read_training_export(tmp_path)
    assert set(rows) == {"train", "validation"}
    with (tmp_path / "train.jsonl").open("a") as stream:
        stream.write("{}\n")
    with pytest.raises(ValueError, match="Changed train export"):
        read_training_export(tmp_path)


@pytest.mark.parametrize("mutation", ["family", "test_row", "quarantine", "prompt"])
def test_training_export_rejects_leakage_quarantine_and_prompt_drift(
    tmp_path, mutation
):
    metadata = make_export(tmp_path)
    if mutation == "family":
        metadata["rows"][0]["family"] = "barbell"
    elif mutation == "test_row":
        metadata["rows"].append({"id": "holdout", "split": "test"})
    elif mutation == "quarantine":
        metadata["quarantine"].append({"reason": "uncertain"})
    else:
        path = tmp_path / "train.jsonl"
        row = json.loads(path.read_text())
        row["messages"][0]["content"] = "An obsolete prompt"
        path.write_text(json.dumps(row) + "\n")
        metadata["files"]["train"] = HistoryStore.digest(path)
        metadata["rows"][0]["row_sha256"] = digest(row)
    HistoryStore.write(tmp_path / "provenance.json", metadata)
    with pytest.raises(ValueError):
        read_training_export(tmp_path)
