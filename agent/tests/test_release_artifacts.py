from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

from graphmine_agent import __version__


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _json(relative: str) -> dict:
    return json.loads((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))


def _sha256(relative: str) -> str:
    return hashlib.sha256((REPOSITORY_ROOT / relative).read_bytes()).hexdigest()


def test_v1_version_is_consistent_across_release_contracts() -> None:
    assert __version__ == "1.0.0"
    assert (REPOSITORY_ROOT / "VERSION").read_text(encoding="utf-8").strip() == __version__
    pyproject = tomllib.loads(
        (REPOSITORY_ROOT / "agent" / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert pyproject["project"]["version"] == __version__
    for relative in (
        "graphmine_manifest.json",
        "graphmine_catalog.json",
        "library/manifests/graphmine_manifest.json",
        "library/manifests/graphmine_catalog.json",
    ):
        assert _json(relative)["library_version"] == __version__
    assert "project(GraphMine VERSION 1.0.0" in (
        REPOSITORY_ROOT / "library" / "CMakeLists.txt"
    ).read_text(encoding="utf-8")


def test_v1_qwen_reports_match_current_corpus_and_pass_exact_gate() -> None:
    corpus_hash = _sha256("agent/evaluation/v1_query_cases.json")
    expected = {
        "agent/evaluation/reports/qwen3.8-27b-fp8-v1-matrix-routing.json": 117,
        "agent/evaluation/reports/qwen3.8-27b-fp8-v1-routing-safety.json": 20,
        "agent/evaluation/reports/qwen3.8-27b-fp8-v1-matrix-planning.json": 117,
    }
    for relative, total in expected.items():
        report = _json(relative)
        assert report["cases_sha256"] == corpus_hash
        assert report["model"] == "Qwen/Qwen3.8-27B-FP8"
        assert report["total"] == total
        assert report["passed"] == total
        assert report["accuracy"] == 1.0
        assert len(report["cases"]) == total
        assert all(case["passed"] for case in report["cases"])
        assert all(
            group["passed"] == group["total"]
            for group in report["by_domain"].values()
        )


def test_v1_benchmark_summary_and_policy_are_hash_linked() -> None:
    summary = _json("benchmarks/reports/v1-smoke-rtx6000-ada.json")
    assert summary["correct_records"] == summary["total_records"] == 69
    assert summary["compiled_backends_exercised"] == 23
    assert summary["operations_exercised"] == 13
    assert summary["policy_evaluation"] == {
        "evaluated_cases": 14,
        "oracle_matches": 14,
        "median_regret_ratio": 1.0,
        "maximum_regret_ratio": 1.0,
        "note": "This is an in-sample smoke evaluation, not a generalization claim.",
    }
    assert summary["sha256"]["manifest"] == _sha256("benchmarks/v1-smoke.json")
    assert summary["sha256"]["backend_policy"] == _sha256(
        "agent/backend_policy.json"
    )
    policy = _json("agent/backend_policy.json")
    assert policy["schema_version"] == "1.0.0"
    assert len(policy["operations"]) == 13
