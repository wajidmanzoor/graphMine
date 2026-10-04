from __future__ import annotations

import copy
from contextlib import asynccontextmanager

import pytest
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning import business_workflows as business
from graphmine_agent.learning.business_curriculum import build_examples
from graphmine_agent.learning.business_questions import wording_issues
from graphmine_agent.learning.corpus import _graph, _tasks, digest, gold_route
from test_business_curriculum import source_examples


@pytest.fixture
def practical_source(tmp_path, monkeypatch):
    source, graphs = source_examples()
    for family in ("retail_nested", "events_cycle"):
        graph, vocabulary = _graph(family, 105, 0)
        graph_id = family + "-test"
        graphs[graph_id] = graph
        for index, task in enumerate(_tasks(graph, vocabulary, 105)):
            source["examples"].append(
                {
                    "id": f"{graph_id}-q{index}",
                    "graph_id": graph_id,
                    "split": "validation",
                    "family": family,
                    "domain": vocabulary["domain"],
                    "task": task,
                    "gold_route": gold_route(task).model_dump(mode="json"),
                }
            )
    source["graphs"] = [
        {"id": graph_id, "path": f"graphs/{graph_id}.json"} for graph_id in graphs
    ]
    corpus = tmp_path / "source"
    HistoryStore.write(corpus / "manifest.json", source)
    examples, _ = build_examples(source)
    manifest = {
        "examples": examples,
        "source_corpus": str(corpus.resolve()),
        "source_corpus_sha256": HistoryStore.digest(corpus / "manifest.json"),
    }
    curriculum = tmp_path / "curriculum"
    HistoryStore.write(curriculum / "manifest.json", manifest)
    monkeypatch.setattr(business, "load", lambda _: (manifest, graphs))
    monkeypatch.setattr(business, "load_corpus", lambda _: (source, graphs))
    return curriculum, corpus


def test_practical_workflows_cover_domains_and_keep_validation_boundaries(
    practical_source,
):
    curriculum, _ = practical_source
    cases = business.build_cases(curriculum)
    assert len(cases) == 9 and sum(len(c["steps"]) for c in cases) == 21
    assert len({c["domain"] for c in cases}) == 6
    assert {c["family"] for c in cases} <= {
        "cycle_chords",
        "retail_nested",
        "events_cycle",
    }
    assert all(not wording_issues(s["query"]) for c in cases for s in c["steps"])
    assert any(s["task"]["behavior"] == "clarify" for c in cases for s in c["steps"])
    assert any(
        s["task"]["behavior"] == "unsupported" for c in cases for s in c["steps"]
    )


@pytest.mark.parametrize(
    "left,right,equivalent",
    [
        (0, 0.0, True),
        (-0.0, 0, True),
        (0.999, 0.999, True),
        (0, "0", False),
        (1, True, False),
        (10**35 + 1, 10**35 + 2, False),
    ],
)
def test_numeric_filter_equivalence_is_precise_and_preserves_scalar_kinds(
    left, right, equivalent
):
    def filters(value):
        return [
            {
                "target": "edges",
                "field": "attributes.score",
                "operator": "eq",
                "value": value,
            }
        ]

    assert (
        business.normalized_filters(filters(left))
        == business.normalized_filters(filters(right))
    ) is equivalent
    changed = filters(right)
    changed[0]["field"] = "attributes.ascore"
    assert business.normalized_filters(filters(left)) != business.normalized_filters(
        changed
    )
    changed = filters(right)
    changed[0]["operator"] = "gte"
    assert business.normalized_filters(filters(left)) != business.normalized_filters(
        changed
    )


def test_numeric_correction_cannot_hide_other_failures(monkeypatch):
    original = ["Requested attribute scope changed", "incorrect native result"]
    monkeypatch.setattr(
        business.workflows, "check_workflow_step", lambda *args: list(original)
    )
    monkeypatch.setattr(business, "check_presentation", lambda *args: ["missing names"])
    expected = [
        {"target": "edges", "field": "attributes.score", "operator": "eq", "value": 0}
    ]
    actual = copy.deepcopy(expected)
    actual[0]["value"] = 0.0
    issues, retained, correction = business.grade_step(
        {},
        {"filters": expected},
        {"job": {"plan": {"application_intent": {"filters": actual}}}},
    )
    assert issues == ["incorrect native result", "missing names"]
    assert retained == original and correction is True


def test_frozen_conversation_questions_cannot_be_changed(practical_source, tmp_path):
    curriculum, _ = practical_source
    directory = tmp_path / "suite"
    suite = business.prepare(curriculum, directory)
    assert business.read(directory) == suite
    suite["cases"][0]["steps"][0]["query"] = "A different business objective"
    suite["cases_sha256"] = digest(suite["cases"])
    HistoryStore.write(directory / "suite.json", suite)
    with pytest.raises(ValueError, match="changed"):
        business.read(directory)


@pytest.mark.asyncio
async def test_failures_never_send_oracle_feedback(
    practical_source, tmp_path, monkeypatch, settings
):
    curriculum, corpus = practical_source
    suite = business.prepare(curriculum, tmp_path / "suite")
    suite["cases"] = [suite["cases"][0]]
    suite["cases"][0]["steps"] = suite["cases"][0]["steps"][:2]
    asked = []

    @asynccontextmanager
    async def client(*args, **kwargs):
        yield object(), tmp_path / "history"

    class Terminal:
        session_id, turn_id, last_outcome = "session", "turn", {}

        def __init__(self, *args, **kwargs):
            pass

        async def start(self, **kwargs):
            pass

        async def load(self, path):
            pass

        async def ask(self, query):
            asked.append(query)
            return {"reply_number": len(asked)}

        async def feedback(self, *args, **kwargs):
            raise AssertionError(
                "Oracle feedback must not enter business conversations"
            )

    monkeypatch.setattr(business, "Terminal", Terminal)
    monkeypatch.setattr(business.workflows, "agent_client", client)
    monkeypatch.setattr(
        business.workflows, "restore_reused_outcome", lambda value, **kwargs: value
    )
    monkeypatch.setattr(
        business,
        "grade_step",
        lambda graph, task, outcome: (
            (["wrong computation"], ["wrong computation"], False)
            if outcome["reply_number"] == 1
            else ([], [], False)
        ),
    )
    report = await business.evaluate_cases(
        settings,
        case_suite=suite,
        corpus=corpus,
        output=tmp_path / "report.json",
        data_dir=tmp_path / "runtime",
    )
    assert len(asked) == report["total"] == report["expected_total"] == 2
    assert report["passed"] == 1 and report["workflows_passed"] == 0
    assert report["oracle_feedback_sent"] is False and report["finished_at"]
    assert not any("feedback_id" in s for t in report["trials"] for s in t["steps"])
