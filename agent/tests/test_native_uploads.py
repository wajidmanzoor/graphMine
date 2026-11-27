"""CPU upload integration and the separately callable native reader transport.

The app intentionally imports ordinary CSVs on CPU. Actual libcudf parsing is
covered by library/tests/test_native_ingestion.py, not by the upload endpoint.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.api import create_app
from graphmine_agent.graph_store import UploadError
from graphmine_agent.models import FileRole
from graphmine_agent.native_ingestion import IngestionError, read_delimited_graph

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
    # Managed releases use a launcher in bin/ and a separate pinned library.
    library = Path(os.environ.get("GRAPHMINE_NATIVE_LIBRARY") or binary.with_name("libgraphmine_runtime.so"))

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
                    "scope": "CPU CSV uploads, app validation and explicit native reader transport boundaries",
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


def test_upload_uses_cpu_and_preserves_original_bytes(
    graph_store, session, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Ordinary CSV uploads must not launch the native GPU reader")

    monkeypatch.setattr('graphmine_agent.native_ingestion.subprocess.Popen', forbidden)
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
    assert provenance["reader"] == "python_csv"
    assert provenance["device"] == "cpu" and provenance["complete"] is True
    assert (
        provenance["input_sha256"]
        == record.sha256
        == hashlib.sha256(content).hexdigest()
    )
    assert Path(record.source_path).read_bytes() == content


def test_upload_endpoint_returns_cpu_graph_with_explicit_columns(settings):
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
            {"id": 0, "source": "A", "target": "B", "weight": 1.5}
        ]
        assert graph["graph"]["directed"] is True
        assert graph["graph"]["attributes"]["ingestion"]["reader"] == "python_csv"


@pytest.mark.parametrize(
    "content,message",
    [
        (b"source,target\nA,B,discarded\n", "different number"),
        (b"source,target\nA\n", "different number"),
        (b"source,source\nA,B\n", "unique"),
        (b"source,target\nA,\xff\n", "UTF-8"),
    ],
)
def test_upload_rejections_leave_no_persisted_graph(
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


@pytest.fixture
def csv_path(tmp_path):
    path = tmp_path / 'records.csv'
    path.write_bytes(b'source,target\nA,B\n')
    return path


def native_read(settings, path):
    return read_delimited_graph(settings, path, directed=False, source_column=None, target_column=None)


def test_unavailable_cudf_does_not_use_a_python_reader(settings, csv_path, tmp_path):
    binary = tmp_path / 'without-cudf'
    binary.write_text(f'#!{sys.executable}\nprint(\'{{"error":{{"message":"libcudf is unavailable"}}}}\')\n')
    binary.chmod(0o700)
    with pytest.raises(IngestionError, match='libcudf'):
        native_read(replace(settings, native_runtime_binary=binary), csv_path)


def test_missing_binary_has_actionable_error(settings, csv_path, tmp_path):
    with pytest.raises(IngestionError, match="GRAPHMINE_NATIVE_BINARY"):
        native_read(replace(settings, native_runtime_binary=tmp_path / 'missing'), csv_path)


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
    settings, csv_path, tmp_path, script, limit, message
):
    binary = tmp_path / "transport-fixture"
    binary.write_text(f"#!{sys.executable}\n{script}\n")
    binary.chmod(0o700)
    with pytest.raises(IngestionError, match=message):
        native_read(replace(settings, native_runtime_binary=binary,
                            job_timeout_seconds=1, max_result_bytes=limit), csv_path)
