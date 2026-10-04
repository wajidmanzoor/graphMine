from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

import httpx
import pytest
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning import corpus, oracles, teacher
from graphmine_agent.learning.pipeline import (
    audit_native,
    check_agent_outcome,
    choose_examples,
    export_candidates,
)


@pytest.fixture
def synthetic(tmp_path):
    root = tmp_path / "corpus"
    manifest = corpus.generate_corpus(root, graphs_per_family=1)
    checked, graphs = corpus.load_corpus(root)
    assert checked == manifest
    return root, manifest, graphs


def graph(pairs, *, n=4, directed=False):
    return {
        "graph": {"directed": directed},
        "vertices": [{"id": i, "label": f"Entity {i}"} for i in range(n)],
        "edges": [
            {"id": str(i), "source": a, "target": b} for i, (a, b) in enumerate(pairs)
        ],
    }


def task(operation, **parameters):
    return {"behavior": "execute", "operation_id": operation, "parameters": parameters}


def test_generation_reproducible_bounded_and_split_safe(synthetic, tmp_path):
    root, manifest, graphs = synthetic
    repeated = corpus.generate_corpus(tmp_path / "copy", graphs_per_family=1)
    assert repeated == manifest
    assert len(graphs) == 12 and len(manifest["examples"]) == 99
    assert {row["domain"] for row in manifest["examples"]} >= {
        "social_networks",
        "bioinformatics",
        "fraud_detection",
        "cybersecurity",
        "recommendation_ecommerce",
    }
    assert (
        max(len(value["vertices"]) for value in graphs.values()) <= oracles.MAX_VERTICES
    )
    train = choose_examples(manifest, "train")
    held_out = choose_examples(manifest, "test")
    assert not {row["family"] for row in train} & {row["family"] for row in held_out}
    assert (root / "manifest.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="already exists"):
        corpus.generate_corpus(root)
    with pytest.raises(ValueError, match="positive"):
        choose_examples(manifest, "test", 0)


def test_default_generator_covers_all_six_application_domains(tmp_path):
    manifest = corpus.generate_corpus(tmp_path / "full")
    assert len({row["domain"] for row in manifest["examples"]}) == 6


@pytest.mark.parametrize(
    "mutation", ["query", "label", "split", "identifier", "domain"]
)
def test_corpus_rejects_changed_semantics_or_metadata(synthetic, mutation):
    root, manifest, _ = synthetic
    item = manifest["examples"][0]
    if mutation == "query":
        item["task"]["query"] = "Do something entirely different"
    elif mutation == "label":
        item["gold_route"]["supported"] = False
    elif mutation == "split":
        item["split"] = "test"
    elif mutation == "identifier":
        item["id"] = "../escape"
    else:
        item["domain"] = "wrong"
    HistoryStore.write(root / "manifest.json", manifest)
    with pytest.raises(ValueError):
        corpus.load_corpus(root)


def test_corpus_hash_and_seed_checks(synthetic):
    root, manifest, graphs = synthetic
    record = manifest["graphs"][0]
    changed = copy.deepcopy(graphs[record["id"]])
    changed["vertices"][0]["label"] = "Changed"
    HistoryStore.write(root / record["path"], changed)
    with pytest.raises(ValueError, match="content changed"):
        corpus.load_corpus(root)
    record["sha256"] = HistoryStore.digest(root / record["path"])
    HistoryStore.write(root / "manifest.json", manifest)
    with pytest.raises(ValueError, match="seeded"):
        corpus.load_corpus(root)


def test_isomorphism_ignores_names_but_not_direction_or_structure():
    star = graph([(0, 1), (0, 2), (0, 3)])
    renamed = copy.deepcopy(star)
    mapping = {0: "center", 1: "other-3", 2: "other-1", 3: "other-2"}
    for row in renamed["vertices"]:
        row["id"] = mapping[row["id"]]
    renamed["vertices"].reverse()
    for edge in renamed["edges"]:
        edge["source"], edge["target"] = (
            mapping[edge["source"]],
            mapping[edge["target"]],
        )
    assert oracles.isomorphic(star, renamed)
    assert not oracles.isomorphic(star, graph([(0, 1), (1, 2), (2, 3)]))
    renamed["graph"]["directed"] = True
    assert not oracles.isomorphic(star, renamed)


def test_oracles_check_membership_counts_and_empty_results():
    data = graph([(0, 1), (0, 2), (1, 2), (2, 3)])
    request = task("maximal-cliques", minimum_clique_size=3)
    output = {"cliques": [[0, 1, 2]], "returned_count": 1, "complete": True}
    assert oracles.verify_output(data, request, output) == []
    assert oracles.verify_output(data, request, {**output, "cliques": [[0, 1, 3]]})
    assert oracles.verify_output(data, request, {**output, "returned_count": 8})
    assert oracles.verify_output(data, request, {**output, "complete": False})
    assert oracles.expected_answer(data, task("k-core", requested_k=2))["vertices"] == [
        0,
        1,
        2,
    ]
    assert (
        oracles.expected_answer(data, task("k-core", requested_k=3))["vertices"] == []
    )
    assert oracles.verify_output(
        data, task("k-core", requested_k=2), {"requested_core_vertices": [0, 1, 2, 2]}
    )
    data["edges"][0]["attributes"] = {"year": 2026}
    projected = oracles.selected_graph(
        data,
        [
            {
                "target": "edges",
                "field": "attributes.year",
                "operator": "eq",
                "value": 2026,
            }
        ],
    )
    assert len(projected["edges"]) == 1


def test_shortest_path_reference_splits_equal_routes():
    diamond = graph([(0, 1), (0, 2), (1, 3), (2, 3)])
    answer = oracles.expected_answer(diamond, task("betweenness-centrality"))
    assert [row["score"] for row in answer["scores"]] == [1, 1, 1, 1]
    star = graph([(0, 1), (0, 2), (0, 3)])
    answer = oracles.expected_answer(star, task("betweenness-centrality"))
    assert [row["score"] for row in answer["scores"]] == [6, 0, 0, 0]


def test_temporal_reference_checks_actual_event_order_and_window():
    data = graph([(0, 1), (1, 2), (0, 2)], n=3, directed=True)
    for row, timestamp in zip(data["edges"], [10, 20, 30], strict=True):
        row["timestamp"] = timestamp
    request = task("temporal-motif-mining", max_time_span=20)
    assert oracles.expected_answer(data, request) == {
        "event_ids": [["0", "1", "2"]],
        "count": 1,
    }
    assert (
        oracles.expected_answer(data, task("temporal-motif-mining", max_time_span=19))[
            "count"
        ]
        == 0
    )
    output = {
        "count": 1,
        "instances_complete": True,
        "instances": [{"edges_in_temporal_order": ["0", "1", "2"]}],
    }
    assert not oracles.verify_output(data, request, output)
    output["instances"][0]["edges_in_temporal_order"].reverse()
    assert oracles.verify_output(data, request, output)


def test_partition_checker_does_not_claim_unique_best_community():
    data = graph([(0, 1), (2, 3)])
    output = {
        "assignment_by_vertex": [{"vertex": i, "community": i // 2} for i in range(4)],
        "community_count": 2,
        "modularity": 0.5,
    }
    assert not oracles.verify_output(data, task("community-detection"), output)
    output["modularity"] = 0.9
    assert oracles.verify_output(data, task("community-detection"), output)


def audit_fixture(root, manifest):
    rows = []
    for split in ("train", "validation", "test"):
        example = next(
            row
            for row in manifest["examples"]
            if row["split"] == split
            and row["task"]["operation_id"] == "maximal-cliques"
        )
        expected = example["task"]["oracle"]
        rows.append(
            {
                "id": example["id"],
                "example_sha256": corpus.digest(example),
                "passed": True,
                "verification": "independent_native_result_check",
                "payload": {
                    "ok": True,
                    "output": {
                        "cliques": expected["groups"],
                        "returned_count": expected["count"],
                        "complete": True,
                    },
                },
            }
        )
    report = {
        "mode": "native_oracle",
        "finished_at": "completed",
        "corpus_sha256": HistoryStore.digest(root / "manifest.json"),
        "checker_sha256": HistoryStore.digest(Path(oracles.__file__)),
        "examples": rows,
    }
    path = root.parent / "audit.json"
    HistoryStore.write(path, report)
    return path, report


def test_export_quarantines_missing_records_and_excludes_test(
    synthetic, settings, tmp_path
):
    root, manifest, _ = synthetic
    audit, _ = audit_fixture(root, manifest)
    destination = tmp_path / "export"
    report = export_candidates(
        settings, corpus=root, audit=audit, destination=destination
    )
    assert Counter(row["split"] for row in report["rows"]) == {
        "train": 1,
        "validation": 1,
    }
    assert report["training_started"] is False and report["teacher_model"] is None
    assert report["quarantine"]
    assert not (destination / "test.jsonl").exists()
    exported = json.loads((destination / "train.jsonl").read_text())
    assert len(exported["messages"]) == 3
    from graphmine_agent.llm import ROUTING_SYSTEM_PROMPT
    from graphmine_agent.planning import APPLICATION_PREPROCESSING

    assert exported["messages"][0]["content"] == ROUTING_SYSTEM_PROMPT
    route_payload = json.loads(exported["messages"][1]["content"])
    assert route_payload["application_preprocessing"] == APPLICATION_PREPROCESSING
    assert route_payload["pending_request"] is None
    assert route_payload["graph_metadata"]["has_weights"] is False
    assert "oracle" not in json.loads(exported["messages"][1]["content"])
    assert (destination / "train.jsonl").stat().st_mode & 0o777 == 0o600


def test_export_rechecks_saved_outputs_instead_of_trusting_pass_flag(
    synthetic, settings, tmp_path
):
    root, manifest, _ = synthetic
    audit, saved = audit_fixture(root, manifest)
    saved["examples"][0]["payload"]["output"]["returned_count"] = 999
    HistoryStore.write(audit, saved)
    report = export_candidates(
        settings, corpus=root, audit=audit, destination=tmp_path / "export"
    )
    assert len(report["rows"]) == 1
    assert any("revalidation" in row["reason"] for row in report["quarantine"])
    saved["checker_sha256"] = "stale"
    HistoryStore.write(audit, saved)
    with pytest.raises(ValueError, match="checker changed"):
        export_candidates(
            settings, corpus=root, audit=audit, destination=tmp_path / "stale"
        )


async def test_audit_refuses_existing_runtime(synthetic, settings, tmp_path):
    root, _, _ = synthetic
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    with pytest.raises(ValueError, match="isolated"):
        await audit_native(
            settings, corpus=root, output=tmp_path / "audit.json", data_dir=occupied
        )


async def test_native_audit_saves_failure_feedback_and_workspace(
    synthetic, settings, tmp_path
):
    root, _, _ = synthetic
    report = await audit_native(
        settings,
        corpus=root,
        output=tmp_path / "failed.json",
        data_dir=tmp_path / "audit-runtime",
        limit=1,
    )
    assert report["total"] == 1 and report["passed"] == 0
    row = report["examples"][0]
    assert row["feedback_id"] and row["turn_id"]
    feedback = (
        tmp_path
        / "audit-runtime"
        / "history"
        / row["session_id"]
        / "feedback"
        / f"{row['feedback_id']}.json"
    )
    assert json.loads(feedback.read_text())["source"] == "assistant_evaluation"
    assert Path(row["workspace"]).is_dir()


def test_live_checker_rejects_wrong_scope_even_when_numbers_coincide():
    data = graph([(0, 1), (0, 2), (1, 2)])
    request = task("maximal-cliques", minimum_clique_size=3)
    outcome = {
        "job": {
            "status": "completed",
            "plan": {"parameters": {"minimum_clique_size": 3}},
        },
        "result": {
            "operation_id": "maximal-cliques",
            "payload": {
                "output": {
                    "cliques": [[0, 1, 2]],
                    "returned_count": 1,
                    "complete": True,
                }
            },
            "answer": {
                "rows": data["vertices"],
                "facts": ["computed"],
                "provenance": {"input_edges": 3},
            },
            "interpretation": {"visualizations": ["table"]},
        },
    }
    assert not check_agent_outcome(data, request, outcome)
    outcome["job"]["plan"]["parameters"]["minimum_clique_size"] = 2
    assert "Semantic parameter minimum_clique_size changed" in check_agent_outcome(
        data, request, outcome
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/v1",
        "http://localhost.evil/v1",
        "http://user:secret@localhost/v1",
        "file:///tmp/model",
        "http://127.0.0.1/v1?secret=key",
    ],
)
def test_local_teacher_rejects_remote_or_credential_urls(url):
    with pytest.raises(ValueError, match="local-only"):
        teacher.local_endpoint(url)


async def test_teacher_proposals_are_quarantined_and_keep_raw_calls(
    synthetic, settings, tmp_path, monkeypatch
):
    root, _, _ = synthetic
    real_client = httpx.AsyncClient
    calls = []

    def reply(request):
        body = json.loads(request.content)
        calls.append(body)
        assert "oracle" not in body["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "queries": [
                                        "A different application question to be checked."
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(
        teacher.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(reply), **kwargs),
    )
    result = await teacher.generate_teacher_candidates(
        settings, corpus=root, destination=tmp_path / "teacher", count=1
    )
    assert len(calls) == 1 and len(result["candidates"]) == 1
    assert result["candidates"][0]["training_eligible"] is False
    assert result["candidates"][0]["status"].startswith("quarantined")
    assert "raw_response" in result["calls"][0]
    assert settings.llm_api_key not in json.dumps(result)


async def test_teacher_does_not_follow_redirect(
    synthetic, settings, tmp_path, monkeypatch
):
    root, _, _ = synthetic
    real_client = httpx.AsyncClient
    requests = []

    def redirect(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://external.invalid/"})

    monkeypatch.setattr(
        teacher.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(redirect), **kwargs),
    )
    result = await teacher.generate_teacher_candidates(
        settings, corpus=root, destination=tmp_path / "teacher", count=1
    )
    assert len(requests) == 1 and result["calls"][0]["status"] == "failed"
    assert not result["candidates"]
