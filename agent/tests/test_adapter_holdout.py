from __future__ import annotations

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace

import pytest
from graphmine_agent.learning import adapter_holdout
from graphmine_agent.learning.adapter_workflows import evaluate


def manifest():
    return {
        "sources": {
            "development-source": {"split": "development"},
            "reserved-source": {"split": "holdout"},
        },
        "graphs": [
            {
                "id": "reserved-graph",
                "source_id": "reserved-source",
                "split": "holdout",
                "path": "graphs/reserved.json",
            }
        ],
        "cases": [
            {"id": "development-case", "split": "development"},
            {
                "id": "reserved-case",
                "split": "holdout",
                "source_id": "reserved-source",
                "graph_id": "reserved-graph",
                "domain": "general",
                "steps": [
                    {"query": "reserved first turn"},
                    {"query": "reserved follow-up"},
                ],
            },
        ],
    }


def test_final_selection_keeps_every_reserved_case_and_checks_source_boundaries():
    source = manifest()
    original = deepcopy(source)
    assert adapter_holdout.final_cases(source) == source["cases"][1:]
    assert source == original
    source["graphs"][0]["source_id"] = "development-source"
    with pytest.raises(ValueError, match="source boundary"):
        adapter_holdout.final_cases(source)
    with pytest.raises(ValueError, match="No reserved"):
        adapter_holdout.final_cases({**original, "cases": original["cases"][:1]})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options",
    [
        {},
        {"real_corpus": "corpus", "questions": "development-questions"},
        {"real_corpus": "corpus", "case_ids": {"subset"}},
    ],
)
async def test_final_mode_rejects_development_questions_or_a_selected_subset(
    tmp_path, options
):
    with pytest.raises(ValueError, match="Final holdout"):
        await evaluate(
            tmp_path / "unused-suite",
            tmp_path / "unused-output",
            final_holdout=True,
            **options,
        )
    assert not (tmp_path / "unused-output").exists()


@pytest.mark.asyncio
async def test_final_run_records_consumption_and_never_sends_oracle_feedback(
    monkeypatch, settings, tmp_path
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text(json.dumps(manifest()))
    report_path = tmp_path / "final.json"
    history = tmp_path / "history"
    asked = []

    @asynccontextmanager
    async def client(*args, **kwargs):
        yield object(), history

    class Terminal:
        session_id = "test-session"
        turn_id = "test-turn"

        def __init__(self, *args, **kwargs):
            self.last_outcome = {}

        async def start(self, **kwargs):
            pass

        async def load(self, path):
            assert path == corpus / "graphs/reserved.json"

        async def ask(self, query):
            before = json.loads(report_path.read_text())
            assert before["holdout_consumed_at"]
            assert before["holdout_question_turns_attempted"] == len(asked) + 1
            asked.append(query)
            return {"result": query}

        async def feedback(self, *args, **kwargs):
            raise AssertionError("Final model must not receive oracle corrections")

    monkeypatch.setattr(adapter_holdout, "agent_client", client)
    monkeypatch.setattr(adapter_holdout, "Terminal", Terminal)
    monkeypatch.setattr(
        adapter_holdout,
        "load_realworld",
        lambda _: (manifest(), {"reserved-graph": {}}),
    )
    monkeypatch.setattr(
        adapter_holdout, "restore_reused_outcome", lambda value, **_: value
    )
    monkeypatch.setattr(
        adapter_holdout,
        "check_workflow_step",
        lambda graph, task, outcome: (
            ["wrong computation"] if task["query"].endswith("turn") else []
        ),
    )
    monkeypatch.setattr(adapter_holdout, "check_presentation", lambda *args: [])
    result = await adapter_holdout.evaluate_holdout(
        replace(settings, llm_enabled=True, llm_base_url="http://127.0.0.1:8001/v1"),
        corpus=corpus,
        output=report_path,
        data_dir=tmp_path / "isolated-app",
    )
    assert asked == ["reserved first turn", "reserved follow-up"]
    assert result["total"] == result["expected_total"] == 2
    assert result["passed"] == 1 and result["workflows_passed"] == 0
    assert result["finished_at"]
    assert result["oracle_feedback_sent"] is False
    assert result["training_export_allowed"] is False
    assert json.loads(report_path.read_text()) == result
