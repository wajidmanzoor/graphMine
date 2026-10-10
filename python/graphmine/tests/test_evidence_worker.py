"""Evidence rejection tests use explicitly synthetic files, never release reports."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from graphmine import Graph, list_algorithms
from graphmine.evidence import verify_report
from graphmine.exceptions import GraphMineError
from graphmine.worker import handle
from graphmine.workflows import validate_workflow


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def synthetic_report(tmp_path):
    library = tmp_path / "python/graphmine"
    (library / "tests").mkdir(parents=True)
    (tmp_path / "problems").mkdir()
    (library / "tests/test_synthetic.py").write_text("# Synthetic verifier fixture\n")
    (library / "pyproject.toml").write_text("# Synthetic verifier fixture\n")
    xml, meta = tmp_path / "report.xml", tmp_path / "metadata.json"
    xml.write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0" /></testsuites>'
    )
    metadata = {
        "source_files": {
            "tests/test_synthetic.py": sha(library / "tests/test_synthetic.py")
        },
        "contracts": {
            "python/graphmine/pyproject.toml": sha(library / "pyproject.toml")
        },
        "packages": {},
        "sources_unchanged_during_run": True,
        "contracts_unchanged_during_run": True,
        "python": sys.version,
        "device": "cpu",
        "cuda_visible_devices": "",
        "test_modules": ["tests/test_synthetic.py"],
        "collected_test_count": 1,
    }
    meta.write_text(json.dumps(metadata))
    report = {
        "id": "synthetic-verifier-fixture",
        "report": "report.xml",
        "metadata": "metadata.json",
        "report_sha256": sha(xml),
        "metadata_sha256": sha(meta),
    }
    return tmp_path, report


def test_verifier_rereads_artifacts_and_sources(synthetic_report):
    root, report = synthetic_report
    assert verify_report(root, report)["status"] == "passed"
    (root / "python/graphmine/tests/test_synthetic.py").write_text("# changed\n")
    assert verify_report(root, report)["status"] == "unverified"


@pytest.mark.parametrize(
    "field,value",
    [
        ("sources_unchanged_during_run", False),
        ("contracts_unchanged_during_run", False),
        ("python", "0.0"),
        ("packages", {"networkx": "0.0"}),
        ("test_modules", []),
        ("cuda_visible_devices", "0"),
        ("collected_test_count", 5),
        ("device", "invented"),
    ],
)
def test_verifier_rejects_incomplete_or_changed_environments(
    synthetic_report, field, value
):
    root, report = synthetic_report
    path = root / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata[field] = value
    path.write_text(json.dumps(metadata))
    report["metadata_sha256"] = sha(path)
    assert verify_report(root, report)["status"] == "unverified"


@pytest.mark.parametrize(
    "alteration",
    [
        "xml_bytes",
        "metadata_bytes",
        "skipped",
        "new_source",
        "new_contract",
        "path_escape",
    ],
)
def test_verifier_rejects_artifact_changes(synthetic_report, alteration):
    root, report = synthetic_report
    if alteration == "xml_bytes":
        (root / "report.xml").write_text("tampered")
    elif alteration == "metadata_bytes":
        (root / "metadata.json").write_text("{}")
    elif alteration == "skipped":
        path = root / "report.xml"
        path.write_text(path.read_text().replace('skipped="0"', 'skipped="1"'))
        report["report_sha256"] = sha(path)
    elif alteration == "new_source":
        (root / "python/graphmine/new.py").write_text("# new\n")
    elif alteration == "new_contract":
        (root / "problems/new_input.schema.json").write_text("{}")
    else:
        report["report"] = "../report.xml"
    assert verify_report(root, report)["status"] == "unverified"


def test_worker_enforces_evidence_and_review_hash(monkeypatch):
    monkeypatch.setenv("GRAPHMINE_REPOSITORY_ROOT", "/synthetic-worker-test")
    cards = [
        {**card, "execution": {"cpu": False, "gpu": False}}
        for card in list_algorithms()
    ]
    monkeypatch.setattr(
        "graphmine.worker.capabilities", lambda root: {"operations": cards}
    )
    graph = Graph.from_edges([(0, 1), (1, 2), (2, 0)])
    inputs = {"g": {"kind": "graph", "data": graph.to_canonical()}}
    plan = {
        "version": 1,
        "device": "cpu",
        "steps": [
            {"id": "count", "operation": "triangle-counting", "input": {"input": "g"}}
        ],
    }
    request = {"command": "run", "plan": plan, "inputs": inputs}
    with pytest.raises(GraphMineError, match="evidence"):
        handle(request, lambda event: None)
    for card in cards:
        card["execution"]["cpu"] = True  # synthetic protocol test only
    with pytest.raises(GraphMineError, match="reviewed workflow"):
        handle(request, lambda event: None)
    request["expected_hash"] = validate_workflow(plan, inputs)["workflow_hash"]
    result = handle(request, lambda event: None)
    assert result["steps"]["count"]["result"]["ports"]["count"]["value"] == 1
    with pytest.raises(GraphMineError, match="request"):
        handle({"command": "run", "code": "print(1)"}, lambda event: None)


def test_real_worker_protocol_rejects_unknown_command():
    root = Path(__file__).resolve().parents[3]
    env = {
        **os.environ,
        "GRAPHMINE_REPOSITORY_ROOT": str(root),
        "CUDA_VISIBLE_DEVICES": "",
    }
    completed = subprocess.run(
        [sys.executable, "-m", "graphmine.worker"],
        input=json.dumps({"command": "execute_python"}),
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=20,
    )
    assert completed.returncode == 2
    event = json.loads(completed.stdout)
    assert event["event"] == "error"
    assert "Unknown worker command" in event["error"]["message"]
