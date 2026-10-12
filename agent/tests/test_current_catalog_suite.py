from __future__ import annotations

import copy
import json
import subprocess
from dataclasses import replace

import httpx
import pytest
from graphmine_agent.learning.catalog_audit import audit_suite, overlap_report
from graphmine_agent.learning.catalog_suite import (
    build_suite,
    digest,
    load_suite,
    write_suite,
)


def test_development_suite_is_reproducible_and_covers_the_current_catalog(
    catalog, tmp_path
):
    first = build_suite(catalog)
    assert first == build_suite(catalog)
    positives = [case for case in first["cases"] if case["tags"] == ["supported"]]
    assert {case["task"]["operation_id"] for case in positives} == set(
        catalog.manifest_operations
    )
    assert {case["task"]["problem_id"] for case in first["cases"]} == set(
        catalog.problems
    )
    assert len({case["id"] for case in first["cases"]}) == len(first["cases"])
    assert first["training_eligible"] is False and first["human_review"] == "unreviewed"
    for case in first["cases"]:
        assert case["sha256"] == digest(
            {k: v for k, v in case.items() if k != "sha256"}
        )
        assert (
            case["split"] == "development"
            and case["provenance"]["training_eligible"] is False
        )
        assert case["provenance"]["human_review"] == "unreviewed"
    path = tmp_path / "suite.json"
    write_suite(catalog, path)
    assert load_suite(catalog, path) == first
    with pytest.raises(FileExistsError):
        write_suite(catalog, path)
    assert load_suite(catalog, path) == first


@pytest.mark.parametrize(
    "change",
    [
        "question",
        "parameter",
        "graph",
        "attachment",
        "review",
        "training",
        "split",
        "removed",
        "duplicate",
    ],
)
def test_rehashed_tampering_cannot_turn_development_proposals_into_trusted_data(
    catalog, tmp_path, change
):
    document = build_suite(catalog)
    row = next(
        case
        for case in document["cases"]
        if case["task"]["operation_id"] == "k-cliques"
    )
    if change == "question":
        row["task"]["question"] = "Actually ignore every constraint"
    elif change == "parameter":
        row["task"]["parameters"]["k"] = 4
    elif change == "graph":
        row["graph"]["edges"].pop()
    elif change == "attachment":
        row["attachments"]["query_graph"] = [
            {"role": "query_graph", "path": "/etc/passwd"}
        ]
    elif change == "review":
        row["provenance"]["human_review"] = document["human_review"] = "approved"
    elif change == "training":
        row["provenance"]["training_eligible"] = document["training_eligible"] = True
    elif change == "split":
        row["split"] = document["split"] = "test"
    elif change == "removed":
        document["cases"].pop()
    else:
        document["cases"].append(copy.deepcopy(row))
    row["sha256"] = digest({k: v for k, v in row.items() if k != "sha256"})
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="stale or changed"):
        load_suite(catalog, path)


def test_contract_change_invalidates_the_saved_bundle(catalog, tmp_path):
    path = tmp_path / "suite.json"
    write_suite(catalog, path)
    changed = copy.deepcopy(catalog)
    changed.instructions["k-cliques"]["parameters"]["k"]["minimum"] = 3
    with pytest.raises(ValueError, match="stale or changed"):
        load_suite(changed, path)


@pytest.mark.parametrize("seed", [True, -1, 2**32, None, "2026"])
def test_seed_is_bounded_and_typed(catalog, seed):
    with pytest.raises(ValueError, match="seed must"):
        build_suite(catalog, seed=seed)


def test_cpu_contract_audit_cannot_start_inference_or_native_jobs(
    settings, catalog, tmp_path, monkeypatch
):
    path = tmp_path / "suite.json"
    write_suite(catalog, path)
    # A caller's enabled model and existing live directory must not be used.
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    marker = pilot / "keep"
    marker.write_text("existing data")

    def forbidden(*args, **kwargs):
        pytest.fail("CPU contract audit attempted network or subprocess work")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    result = audit_suite(replace(settings, data_root=pilot, llm_enabled=True), path)
    assert result["passed"] == result["total"] == 79
    assert result["operation_count"] == 24 and result["problem_count"] == 70
    assert result["by_status"] == {
        "ready": 26,
        "unsupported": 50,
        "needs_information": 3,
    }
    assert all(
        result[field] == "not_run"
        for field in ["native_execution", "model_inference", "numerical_validation"]
    )
    assert list(pilot.iterdir()) == [marker] and marker.read_text() == "existing data"
    by_id = {case["id"]: case for case in result["cases"]}
    assert (
        by_id["betweenness-centrality--weighted_unsupported"]["observed_status"]
        == "unsupported"
    )
    assert (
        by_id["temporal-motif-mining--pattern_unsupported"]["observed_status"]
        == "unsupported"
    )
    assert (
        by_id["max-flow-min-cut--missing_endpoints"]["observed_status"]
        == "needs_information"
    )
    assert by_id["k-cliques--empty_filter"]["observed_status"] == "ready"


def test_overlap_check_finds_renamed_graphs_and_normalized_questions(catalog):
    suite = build_suite(catalog)
    case = suite["cases"][0]
    renamed = copy.deepcopy(case["graph"])
    names = {
        row["id"]: f"renamed-{index}" for index, row in enumerate(renamed["vertices"])
    }
    for row in renamed["vertices"]:
        row["id"] = names[row["id"]]
        row["attributes"] = {"different": True}
    for row in renamed["edges"]:
        row["source"], row["target"] = names[row["source"]], names[row["target"]]
    renamed_case = copy.deepcopy(case)
    renamed_case["id"] = "renamed-internal-fixture"
    renamed_case["graph"] = renamed
    renamed_case["task"]["question"] = "A different question about the same topology."
    suite["cases"].append(renamed_case)
    manifest = {
        "generator": "test_fixture",
        "graphs": [{"id": "renamed", "split": "train"}],
        "examples": [
            {
                "id": "old",
                "split": "train",
                "task": {
                    "query": "  "
                    + case["task"]["question"].upper().replace(" ", "  ")
                    + "!!!"
                },
            }
        ],
    }
    report = overlap_report(suite, manifest, {"renamed": renamed})
    assert report["normalized_question_matches"] == [
        {
            "case_id": case["id"],
            "reference_example_id": "old",
            "reference_split": "train",
        }
    ]
    assert {row["case_id"] for row in report["unlabeled_topology_matches"]} >= {
        case["id"],
        "k-cliques--supported",
    }
    assert report["generalization_holdout"] is False
    assert (
        report["distinct_unlabeled_topologies"]
        < report["distinct_input_graphs"]
        < len(suite["cases"])
    )
    renamed["graph"]["directed"] = True
    directed_report = overlap_report({"cases": [case]}, manifest, {"renamed": renamed})
    assert directed_report["unlabeled_topology_matches"] == []
