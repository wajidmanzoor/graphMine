from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from graphmine_agent.catalog import Catalog
from graphmine_agent.learning.business_curriculum import build_examples
from graphmine_agent.learning.business_eval import cases_for, prepare
from test_business_curriculum import source_examples


def prepared_cases(settings):
    source, graphs = source_examples()
    examples, _ = build_examples(source)
    manifest = {"examples": examples}
    return manifest, graphs, Catalog(settings)


def test_practical_evaluation_keeps_every_case_and_original_contract(settings):
    manifest, graphs, catalog = prepared_cases(settings)
    cases = cases_for(manifest, graphs, catalog, "test", [])
    expected = [row for row in manifest["examples"] if row["split"] == "test"]
    assert [row["id"] for row in cases] == [row["id"] for row in expected]
    for case, example in zip(cases, expected, strict=True):
        assert case["expected"] == example["gold_route"]
        assert case["payload"]["message"] == example["task"]["query"]
        assert case["query_seen_in_training"] is False
    # Candidate-specific training IDs do not change the frozen evaluation cases.
    training = [row for row in manifest["examples"] if row["split"] == "train"]
    assert cases == cases_for(manifest, graphs, catalog, "test", training)


@pytest.mark.parametrize(
    "mutation", ["train_split", "training_id", "training_text", "duplicate", "missing"]
)
def test_practical_evaluation_rejects_leakage_and_incomplete_identity(
    settings, mutation
):
    manifest, graphs, catalog = prepared_cases(settings)
    manifest = copy.deepcopy(manifest)
    example = next(row for row in manifest["examples"] if row["split"] == "test")
    split, rows, queries = "test", [], []
    if mutation == "train_split":
        split = "train"
    elif mutation == "training_id":
        rows = [{"id": example["id"], "split": "train"}]
    elif mutation == "training_text":
        queries = [example["task"]["query"]]
    elif mutation == "duplicate":
        manifest["examples"].append(copy.deepcopy(example))
    else:
        manifest["examples"] = [
            row for row in manifest["examples"] if row["split"] != "test"
        ]
    with pytest.raises(ValueError):
        cases_for(manifest, graphs, catalog, split, rows, queries)


def test_incomplete_training_cannot_bind_a_suite(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "run.json").write_text("{}")
    (run / "status.json").write_text(json.dumps({"phase": "training"}))
    output = tmp_path / "suite"
    with pytest.raises(ValueError, match="Finish training"):
        prepare(run, Path("unused"), output)
    assert not output.exists()
