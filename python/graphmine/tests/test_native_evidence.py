"""Synthetic verifier fixtures never authorize a production native profile."""

import json
from copy import deepcopy

import pytest
from graphmine.evidence import capabilities, profile_hash, sha


@pytest.fixture
def gate(tmp_path, monkeypatch):
    (tmp_path / "library/runtime").mkdir(parents=True)
    (tmp_path / "catalog").mkdir()
    source = tmp_path / "library/runtime/synthetic.cpp"
    source.write_text("// synthetic verifier source\n")
    binary = tmp_path / "synthetic.so"
    binary.write_bytes(b"synthetic library fixture")
    dependency = tmp_path / "synthetic-dependency.so"
    dependency.write_bytes(b"synthetic dependency fixture")
    implementation = "e" * 64
    card = {
        "id": "synthetic-profile",
        "backends": [{"id": "cpp", "device": "cpu", "compiled": True}],
        "family": "synthetic",
    }
    catalog = {
        "operations": [card],
        "families": [{"id": "synthetic"}],
        "implementation_sha256": implementation,
    }

    class Library:
        path = str(binary)

        def catalog(self):
            return deepcopy(catalog)

    monkeypatch.setattr("graphmine.evidence.native_library", lambda: Library())
    monkeypatch.setattr(
        "graphmine.evidence.execution_environment", lambda: {"synthetic": True}
    )
    monkeypatch.setattr(
        "graphmine.evidence.subprocess.check_output",
        lambda *args, **kwargs: f"libsynthetic => {dependency} (0x123)\n",
    )
    report = tmp_path / "synthetic-report.xml"
    report.write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0" /></testsuites>'
    )
    metadata_path = tmp_path / "synthetic-metadata.json"
    metadata = {
        "implementation_sha256": implementation,
        "native_library_sha256": sha(binary),
        "sources_unchanged_during_run": True,
        "build_unchanged_during_run": True,
        "source_files": {"library/runtime/synthetic.cpp": sha(source)},
        "device": "cpu",
        "cuda_visible_devices": "",
        "collected_test_count": 1,
    }
    metadata_path.write_text(json.dumps(metadata))
    row = {
        "id": "synthetic-only",
        "report": report.name,
        "metadata": metadata_path.name,
        "format": "junit",
        "passed": 1,
        "device": "cpu",
        "artifacts": {report.name: sha(report), metadata_path.name: sha(metadata_path)},
    }
    build = {
        "implementation_sha256": implementation,
        "binary_sha256": sha(binary),
        "sources": {"library/runtime/synthetic.cpp": sha(source)},
        "dependencies": {str(dependency): sha(dependency)},
        "profiles": {
            "synthetic-profile": {
                "profile_sha256": profile_hash(card),
                "backends": {"cpp": ["synthetic-only"]},
            }
        },
        "reports": [row],
    }
    inventory = {"builds": [build], "known_failures": []}

    def save():
        (tmp_path / "catalog/native_execution_evidence.json").write_text(
            json.dumps(inventory)
        )

    save()
    return tmp_path, inventory, metadata, save


def test_synthetic_native_gate_requires_every_artifact(gate):
    root, _, _, _ = gate
    card = capabilities(root)["operations"][0]
    assert card["execution"] == {"cpu": True, "gpu": False}
    assert card["verified_backends"] == ["cpp"]
    (root / "synthetic-report.xml").write_text("changed")
    assert not capabilities(root)["operations"][0]["execution"]["cpu"]


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "new_source",
        "binary",
        "dependency",
        "profile",
        "known_failure",
        "missing_metadata_hash",
        "wrong_report_binary",
        "changed_sources",
        "changed_build",
        "visible_cuda",
        "wrong_count",
        "skipped",
        "missing_report",
        "outside_path",
    ],
)
def test_native_gate_rejects_stale_or_incomplete_evidence(gate, mutation):
    root, inventory, metadata, save = gate
    build = inventory["builds"][0]
    row = build["reports"][0]
    if mutation == "source":
        (root / "library/runtime/synthetic.cpp").write_text("// changed")
    elif mutation == "new_source":
        (root / "library/runtime/new.cpp").write_text("// added")
    elif mutation == "binary":
        (root / "synthetic.so").write_bytes(b"changed")
    elif mutation == "dependency":
        (root / "synthetic-dependency.so").write_bytes(b"changed")
    elif mutation == "profile":
        build["profiles"]["synthetic-profile"]["profile_sha256"] = "stale"
    elif mutation == "known_failure":
        inventory["known_failures"] = [
            {"operation": "synthetic-profile", "backend": "cpp"}
        ]
    elif mutation == "missing_metadata_hash":
        row["artifacts"].pop(row["metadata"])
    elif mutation in {
        "wrong_report_binary",
        "changed_sources",
        "changed_build",
        "visible_cuda",
        "wrong_count",
    }:
        field, value = {
            "wrong_report_binary": ("native_library_sha256", "stale"),
            "changed_sources": ("sources_unchanged_during_run", False),
            "changed_build": ("build_unchanged_during_run", False),
            "visible_cuda": ("cuda_visible_devices", "0"),
            "wrong_count": ("collected_test_count", 2),
        }[mutation]
        metadata[field] = value
        path = root / row["metadata"]
        path.write_text(json.dumps(metadata))
        row["artifacts"][row["metadata"]] = sha(path)
    elif mutation == "skipped":
        path = root / row["report"]
        path.write_text(path.read_text().replace('skipped="0"', 'skipped="1"'))
        row["artifacts"][row["report"]] = sha(path)
    elif mutation == "missing_report":
        (root / row["report"]).unlink()
    else:
        row["report"] = "../outside.xml"
    save()
    assert not capabilities(root)["operations"][0]["execution"]["cpu"]
