from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning import business_curriculum as curriculum
from graphmine_agent.learning.business_questions import QUESTIONS, wording_issues
from graphmine_agent.learning.corpus import _graph, _tasks, digest, gold_route
from graphmine_agent.learning.finetune import read_training_export


def source_examples():
    rows, graphs = [], {}
    for split, family in (
        ("train", "random"),
        ("validation", "cycle_chords"),
        ("test", "barbell"),
    ):
        for domain_index in range(4):
            graph, vocabulary = _graph(family, 160 + domain_index, domain_index)
            graph_id = f"{family}-{domain_index}"
            graphs[graph_id] = graph
            for index, task in enumerate(_tasks(graph, vocabulary, 123)):
                rows.append(
                    {
                        "id": f"{graph_id}-q{index}",
                        "graph_id": graph_id,
                        "split": split,
                        "family": family,
                        "domain": vocabulary["domain"],
                        "task": task,
                        "gold_route": gold_route(task).model_dump(mode="json"),
                    }
                )
    return {"examples": rows}, graphs


def test_business_wording_preserves_contracts_and_keeps_split_wording_separate():
    manifest, _ = source_examples()
    original = copy.deepcopy(manifest)
    examples, omitted = curriculum.build_examples(manifest)
    assert manifest == original
    sources = {row["id"]: row for row in original["examples"]}
    for row in examples:
        source = sources[row["source_example_id"]]
        assert curriculum.semantic_contract(
            row["task"]
        ) == curriculum.semantic_contract(source["task"])
        assert row["gold_route"]["intent"]["objective"] == row["task"]["query"]
        assert row["task"]["query"] != source["task"]["query"]
        assert not wording_issues(row["task"]["query"])
    queries = [
        {row["task"]["query"] for row in examples if row["split"] == split}
        for split in ("train", "validation", "test")
    ]
    assert (
        not queries[0] & queries[1]
        and not queries[0] & queries[2]
        and not queries[1] & queries[2]
    )
    assert omitted and all(row["reason"] for row in omitted)
    broad = [row for row in examples if row["question_kind"] == "broad_business_goal"]
    assert broad and all(row["task"]["behavior"] == "clarify" for row in broad)
    assert all(
        row["gold_route"]["operation_id"] is None and row["gold_route"]["ambiguity"]
        for row in broad
    )


@pytest.mark.parametrize(
    "question",
    [
        "Please run the GPU kernel for my team",
        "Use k-core for maintenance planning",
        "For a team, repeatedly remove people with too few partners",
    ],
)
def test_implementation_language_is_rejected(question):
    assert wording_issues(question)


def test_all_authored_banks_pass_the_narrow_wording_screen():
    for kinds in QUESTIONS.values():
        for versions in kinds.values():
            assert len(versions) == len(set(versions)) == 3
            assert all(
                not wording_issues(text.format(threshold=3)) for text in versions
            )


@pytest.fixture
def built_curriculum(tmp_path, monkeypatch):
    source, graphs = source_examples()
    # Clarification cards need no fabricated native result. Native execution
    # verification is already covered by the oracle/export tests.
    source["examples"] = [
        row for row in source["examples"] if row["task"]["behavior"] == "clarify"
    ]
    corpus = tmp_path / "source"
    corpus.mkdir()
    HistoryStore.write(corpus / "manifest.json", source)
    monkeypatch.setattr(curriculum, "load_corpus", lambda _: (source, graphs))
    native = {
        "mode": "native_oracle",
        "finished_at": "2026-10-03T00:00:00Z",
        "corpus_sha256": HistoryStore.digest(corpus / "manifest.json"),
        "checker_sha256": HistoryStore.digest(
            Path(curriculum.__file__).with_name("oracles.py")
        ),
        "examples": [
            {"id": row["id"], "passed": True, "example_sha256": digest(row)}
            for row in source["examples"]
        ],
    }
    audit_path = tmp_path / "native.json"
    HistoryStore.write(audit_path, native)
    output = tmp_path / "business"
    curriculum.build(corpus, audit_path, output)
    return output, source, graphs


@pytest.mark.parametrize("mutation", ["question", "filter", "split", "audit"])
def test_changed_business_evidence_cannot_be_exported(built_curriculum, mutation):
    root, _, _ = built_curriculum
    path = root / ("audit.json" if mutation == "audit" else "manifest.json")
    data = json.loads(path.read_text())
    if mutation == "question":
        data["examples"][0]["task"]["query"] = "Use different business criteria instead"
    elif mutation == "filter":
        data["examples"][0]["task"]["filters"] = [
            {"field": "attributes.region", "value": "South"}
        ]
    elif mutation == "split":
        data["examples"][0]["split"] = "test"
    else:
        data["examples"][0]["passed"] = False
    HistoryStore.write(path, data)
    with pytest.raises(ValueError, match="changed|incomplete|failed"):
        curriculum.load(root)


def test_export_keeps_test_cards_out_and_uses_business_text(
    built_curriculum, tmp_path, monkeypatch
):
    root, _, _ = built_curriculum
    monkeypatch.setattr(curriculum, "Catalog", lambda _: None)
    monkeypatch.setattr(
        curriculum,
        "training_route_payload",
        lambda catalog, example, graph: {
            "message": example["task"]["query"],
            "graph_metadata": {},
            "application_preprocessing": {},
            "pending_request": None,
        },
    )
    output = tmp_path / "export"
    provenance = curriculum.export(root, output)
    _, rows = read_training_export(output)
    assert set(rows) == {"train", "validation"}
    assert all(
        row["split"] != "test" and row["family"] != "barbell"
        for row in provenance["rows"]
    )
    assert all(
        json.loads(row["messages"][1]["content"])["message"]
        == json.loads(row["messages"][2]["content"])["intent"]["objective"]
        for values in rows.values()
        for row in values
    )
