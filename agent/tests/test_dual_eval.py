import json
from pathlib import Path

import pytest
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning import dual_eval
from graphmine_agent.learning.catalog_replay import source_bindings
from graphmine_agent.learning.dual_eval import (
    compare,
    freeze_inputs,
    regrade,
    verify_request_reuse,
)
from graphmine_agent.models import TurnDecision


@pytest.fixture
def paired_runs(tmp_path):
    for identifier in ("first", "second"):
        HistoryStore.write(
            tmp_path / "teacher-inputs" / (identifier + ".json"),
            {
                "id": identifier,
                "split": "validation",
                "adapter": "planner",
                "schema": "TurnDecision",
                "lineage": "synthetic:held-out",
                "sha256": identifier,
                "reference_contract": {},
                "expected_action": "explain",
                "output_schema": TurnDecision.model_json_schema(),
            },
        )
    manifest = tmp_path / "selection.json"
    freeze_inputs(tmp_path, manifest)
    for model in ("base", "adapted"):
        directory = tmp_path / model
        HistoryStore.write(
            directory / "profile.json",
            {
                "manifest_sha256": HistoryStore.digest(manifest),
                "profile": {
                    "planner": model,
                    "analyst": model,
                    "endpoint": "http://same-local-service/v1",
                    "sources": source_bindings(),
                    "evaluation_code_sha256": HistoryStore.digest(
                        Path(dual_eval.__file__)
                    ),
                    "rules_sha256": HistoryStore.digest(
                        Path(dual_eval.__file__).with_name("dual_teacher.py")
                    ),
                },
            },
        )
        for identifier in ("first", "second"):
            correct = (model == "base") == (identifier == "first")
            HistoryStore.write(
                directory / "calls" / (identifier + ".json"),
                {
                    "input_sha256": identifier,
                    "elapsed_seconds": 2,
                    "status": "passed",  # Deliberately false for two calls.
                    "target": TurnDecision(
                        action="explain" if correct else "analyze",
                        request="Explain this result.",
                    ).model_dump(mode="json"),
                },
            )
    return tmp_path, manifest, tmp_path / "base", tmp_path / "adapted"


def test_comparison_recomputes_gains_and_regressions(settings, paired_runs):
    root, manifest, base, adapted = paired_runs
    report = compare(settings, root, manifest, base, adapted, root / "comparison.json")
    assert report["base_passed"] == report["adapters_passed"] == 1
    stage = report["by_stage"]["TurnDecision"]
    assert stage["corrected"] == stage["regressed"] == 1


def test_primary_comparison_rejects_missing_trials_and_changed_inputs(
    settings, paired_runs
):
    root, manifest, base, adapted = paired_runs
    path = adapted / "calls/first.json"
    previous = path.read_text()
    path.unlink()
    with pytest.raises(ValueError, match="every planned trial"):
        compare(settings, root, manifest, base, adapted, root / "missing.json")
    path.write_text(previous)
    job = root / "teacher-inputs/first.json"
    value = json.loads(job.read_text())
    value["expected_action"] = "analyze"
    HistoryStore.write(job, value)
    result = regrade(settings, root, manifest, base)
    first = next(row for row in result["rows"] if row["id"] == "first")
    assert not first["passed"] and first["error"] == "Input binding failed"


def test_transport_failure_keeps_its_actual_cause(settings, paired_runs):
    root, manifest, base, _ = paired_runs
    path = base / "calls/first.json"
    value = json.loads(path.read_text())
    value.pop("target")
    value["error"] = "HTTP 400: configured context limit exceeded"
    HistoryStore.write(path, value)
    first = regrade(settings, root, manifest, base)["rows"][0]
    assert first["error"] == value["error"]


def test_comparison_rejects_calls_from_different_decoder_sources(settings, paired_runs):
    root, manifest, base, adapted = paired_runs
    path = adapted / "profile.json"
    profile = json.loads(path.read_text())
    profile["profile"]["sources"] = {"llm.py": "old-bounded-string-decoder"}
    HistoryStore.write(path, profile)
    with pytest.raises(ValueError, match="sources changed"):
        compare(settings, root, manifest, base, adapted, root / "changed.json")


@pytest.fixture
def reused_calls(paired_runs):
    root, manifest, base, _ = paired_runs
    output = root / "reused"

    def reference(path):
        return {"path": str(path), "sha256": HistoryStore.digest(path)}

    fingerprint = {
        "manifest_sha256": HistoryStore.digest(manifest),
        "model": "base",
        "endpoint": "http://same-local-service/v1",
        "llm_sha256": source_bindings()["llm.py"],
        "rows": [
            {"id": name, "requests": {"initial": name, "repair": name + "-repair"}}
            for name in ("first", "second")
        ],
    }
    receipts = {}
    for name in ("before", "after"):
        path = root / (name + ".json")
        HistoryStore.write(path, fingerprint)
        receipts[name] = reference(path)
    receipts["source_profile"] = reference(base / "profile.json")
    receipts["calls"] = []
    for identifier in ("first", "second"):
        path = base / "calls" / (identifier + ".json")
        origin = {"id": identifier, **reference(path)}
        receipts["calls"].append(origin)
        HistoryStore.write(
            output / "calls" / path.name,
            {**json.loads(path.read_text()), "origin": origin},
        )
    HistoryStore.write(output / "request-reuse.json", receipts)
    return output, receipts


def test_equivalent_request_reuse_preserves_original_calls(reused_calls):
    output, _ = reused_calls
    digest, reused = verify_request_reuse(output)
    assert digest == HistoryStore.digest(output / "request-reuse.json")
    assert set(reused) == {"first", "second"}


@pytest.mark.parametrize("defect", ["omit", "rewrite", "different_request", "model"])
def test_request_reuse_rejects_selection_mutation_and_different_requests(
    reused_calls, defect
):
    output, receipts = reused_calls
    binding = None
    if defect == "omit":
        receipts["calls"].pop()
    elif defect == "rewrite":
        path = output / "calls/second.json"
        value = json.loads(path.read_text())
        value["target"]["action"] = "explain"
        HistoryStore.write(path, value)
    elif defect == "different_request":
        path = Path(receipts["after"]["path"])
        value = json.loads(path.read_text())
        value["rows"][0]["requests"]["repair"] = "different repair request"
        HistoryStore.write(path, value)
        receipts["after"]["sha256"] = HistoryStore.digest(path)
    else:
        source = json.loads(Path(receipts["after"]["path"]).read_text())
        binding = {
            "manifest_sha256": source["manifest_sha256"],
            "profile": {
                "planner": "another-model",
                "analyst": "another-model",
                "endpoint": source["endpoint"],
            },
        }
    HistoryStore.write(output / "request-reuse.json", receipts)
    with pytest.raises(ValueError):
        verify_request_reuse(output, binding)
