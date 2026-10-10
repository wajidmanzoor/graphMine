"""Upload integration with the real native cuDF reader; bounded transport errors."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.api import create_app
from graphmine_agent.graph_store import GraphStore, UploadError
from graphmine_agent.models import FileRole

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session", autouse=True)
def evidence(request):
    files = sorted((ROOT / "agent/graphmine_agent").rglob("*.py"))
    files += [Path(__file__), ROOT / "agent/tests/conftest.py"]
    files += [
        ROOT / name
        for name in (
            "graphmine_catalog.json",
            "graphmine_manifest.json",
            "agent/program_instructions.json",
            "agent/domain_profiles.json",
            "problems/graph_input.schema.json",
        )
    ]
    for item in request.session.items:
        files.append(item.path)
    binary = Path(os.environ["GRAPHMINE_NATIVE_BINARY"])
    library = binary.parent / "libgraphmine_runtime.so"

    def snapshot():
        return {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(files))
        }

    before = snapshot()
    binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    library_hash = hashlib.sha256(library.read_bytes()).hexdigest()
    yield
    unchanged = (
        before == snapshot()
        and binary_hash == hashlib.sha256(binary.read_bytes()).hexdigest()
        and library_hash == hashlib.sha256(library.read_bytes()).hexdigest()
    )
    if report := getattr(request.config.option, "xmlpath", None):
        Path(str(report) + ".metadata.json").write_text(
            json.dumps(
                {
                    "scope": "Native cuDF uploads, app validation and transport boundaries; algorithm worker migration remains open",
                    "source_files": before,
                    "sources_unchanged_during_run": unchanged,
                    "native_binary": str(binary),
                    "native_binary_sha256": binary_hash,
                    "native_library": str(library),
                    "native_library_sha256": library_hash,
                    "gpu_uuid": os.environ.get("GRAPHMINE_TEST_GRAPH_GPU_UUID"),
                    "collected_test_count": len(request.session.items),
                },
                indent=2,
            )
            + "\n"
        )
    assert unchanged


def test_upload_uses_cudf_and_preserves_original_bytes(
    graph_store, session, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Python CSV parsing must not handle uploaded data")

    monkeypatch.setattr(csv, "reader", forbidden)
    monkeypatch.setattr(csv, "DictReader", forbidden)
    content = b'source,target,source_label,amount,note\n001,2,Ava,9007199254740993,"first\nsecond"\n'
    record = graph_store.ingest(
        session_id=session.id,
        role=FileRole.graph,
        filename="records.csv",
        content=content,
    )
    graph = graph_store.read_graph(record.id, session.id)
    assert graph["vertices"][0] == {"id": "001", "label": "Ava"}
    assert graph["edges"][0]["attributes"] == {
        "amount": 9007199254740993,
        "note": "first\nsecond",
    }
    provenance = graph["graph"]["attributes"]["ingestion"]
    assert provenance["reader"] == "libcudf"
    assert provenance["construction"] == "native-canonical-v1"
    assert (
        provenance["input_sha256"]
        == record.sha256
        == hashlib.sha256(content).hexdigest()
    )
    assert provenance["python_runtime_required"] is False
    assert Path(record.source_path).read_bytes() == content


def test_upload_endpoint_returns_graph_constructed_by_cpp(settings):
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": "Bearer test-secret"}
        session = client.post("/api/sessions", headers=headers, json={}).json()["id"]
        response = client.post(
            f"/api/sessions/{session}/files",
            headers=headers,
            files={
                "file": (
                    "mapped.csv",
                    b"sender,recipient,weight\nA,B,1.5\n",
                    "text/csv",
                )
            },
            data={
                "source_column": "sender",
                "target_column": "recipient",
                "directed": "true",
            },
        )
        assert response.status_code == 201, response.text
        record = response.json()
        preview = client.get(
            f"/api/files/{record['id']}/graph-preview", headers=headers
        )
        assert preview.status_code == 200, preview.text
        graph = preview.json()
        assert graph["edges"] == [
            {"id": 1, "source": "A", "target": "B", "weight": 1.5}
        ]
        assert graph["graph"]["directed"] is True
        assert graph["graph"]["attributes"]["ingestion"]["reader"] == "libcudf"


@pytest.mark.parametrize(
    "content,message",
    [
        (b"source,target\nA,B,discarded\n", "different number"),
        (b"source,target\nA\n", "different number"),
        (b"source,source\nA,B\n", "unique"),
        (b"source,target\nA,\xff\n", "UTF-8"),
    ],
)
def test_native_rejections_leave_no_persisted_graph(
    graph_store, database, session, content, message
):
    with pytest.raises(UploadError, match=message):
        graph_store.ingest(
            session_id=session.id,
            role=FileRole.graph,
            filename="bad.csv",
            content=content,
        )
    assert database.list_files(session.id) == []
    assert not list(graph_store.settings.data_root.rglob("source/*"))


def test_unavailable_cudf_does_not_use_a_python_reader(settings, database, session):
    store = GraphStore(
        replace(
            settings,
            native_runtime_binary=Path("/tmp/graphmine-native-cpu/graphmine-native"),
        ),
        database,
    )
    with pytest.raises(UploadError, match="libcudf"):
        store.ingest(
            session_id=session.id,
            role=FileRole.graph,
            filename="records.csv",
            content=b"source,target\nA,B\n",
        )
    assert database.list_files(session.id) == []


def test_missing_binary_has_actionable_error(settings, database, session, tmp_path):
    store = GraphStore(
        replace(settings, native_runtime_binary=tmp_path / "missing"), database
    )
    with pytest.raises(UploadError, match="GRAPHMINE_NATIVE_BINARY"):
        store.ingest(
            session_id=session.id,
            role=FileRole.graph,
            filename="records.csv",
            content=b"source,target\nA,B\n",
        )


@pytest.mark.parametrize(
    "script,limit,message",
    [
        ("import time; time.sleep(5)", 1000, "deadline"),
        ("print('x' * 1000)", 20, "byte limit"),
        ("print('invalid-json')", 1000, "valid result"),
        (
            'print(\'{"complete":true,"graph":{},"provenance":"bad"}\')',
            1000,
            "complete graph",
        ),
    ],
)
def test_native_transport_bounds(
    settings, database, session, tmp_path, script, limit, message
):
    binary = tmp_path / "transport-fixture"
    binary.write_text(f"#!{sys.executable}\n{script}\n")
    binary.chmod(0o700)
    store = GraphStore(
        replace(
            settings,
            native_runtime_binary=binary,
            job_timeout_seconds=1,
            max_result_bytes=limit,
        ),
        database,
    )
    with pytest.raises(UploadError, match=message):
        store.ingest(
            session_id=session.id,
            role=FileRole.graph,
            filename="records.csv",
            content=b"source,target\nA,B\n",
        )
    assert database.list_files(session.id) == []
