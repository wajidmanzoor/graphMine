import json

import pytest
from fastapi.testclient import TestClient
from graphmine_agent import csv_ingestion
from graphmine_agent.api import create_app
from graphmine_agent.graph_store import UploadError
from graphmine_agent.models import FileRole


def test_cpu_import_keeps_ids_quotes_attributes_and_parallel_edges(
    graph_store, session
):
    content = (
        "\ufeffemployee,partner,id,source_label,target_label,source.team,weight,timestamp,note\r\n"
        '001,9007199254740993,e1,Ava,Ben,Design,1.5,10,"hello, world"\r\n'
        '001,9007199254740993,e2,Ava,Ben,Design,2,11,"line one\nline two"\r\n'
        "001,001,e3,Ava,Ava,Design,3,12,NA\r\n"
    ).encode()
    record = graph_store.ingest(
        session_id=session.id,
        role=FileRole.graph,
        filename="network.csv",
        content=content,
        directed=True,
        source_column="employee",
        target_column="partner",
    )
    graph = graph_store.read_graph(record.id, session.id)
    assert [v["id"] for v in graph["vertices"]] == ["001", 9007199254740993]
    assert graph["vertices"][0]["attributes"] == {"team": "Design"}
    assert graph["edges"][1]["attributes"]["note"] == "line one\nline two"
    assert (
        graph["graph"]["allows_parallel_edges"] and graph["graph"]["allows_self_loops"]
    )
    assert graph["graph"]["attributes"]["ingestion"]["device"] == "cpu"
    assert graph["graph"]["attributes"]["ingestion"]["input_sha256"] == record.sha256


@pytest.mark.parametrize(
    "content",
    [
        b"source,source\na,b\n",
        b"source,target\na\n",
        b"source,target\na,b,c\n",
        b"source,target\na,\xff\n",
        b"source,target\na,\x00\n",
        b'source,target\na,"open\n',
        b'source,target\na,un"quoted\n',
        b'source,target\na,"closed"tail\n',
        b"source,target,weight\na,b,NaN\n",
        b"source,target,weight\na,b," + b"9" * 400 + b"\n",
        b"source,target\na," + b"9" * 5000 + b"\n",
        b"source,target\n,b\n",
        b"source,target,timestamp\na,b,tomorrow\n",
    ],
)
def test_invalid_csv_never_creates_a_partial_file(
    graph_store, session, database, content
):
    with pytest.raises(UploadError):
        graph_store.ingest(
            session_id=session.id,
            role=FileRole.graph,
            filename="bad.csv",
            content=content,
        )
    assert database.list_files(session.id) == []


def test_cpu_row_limit_rejects_truncation(graph_store, session, monkeypatch):
    monkeypatch.setattr(csv_ingestion, "MAX_ROWS", 1)
    with pytest.raises(UploadError, match="row"):
        graph_store.ingest(
            session_id=session.id,
            role=FileRole.graph,
            filename="big.csv",
            content=b"source,target\na,b\nb,c\n",
        )


def test_preview_checks_full_file_without_saving_then_import_matches(settings):
    headers = {"Authorization": "Bearer test-secret"}
    content = b"employee,manager,weight\n001,9007199254740993,2\na,001,3\n"
    with TestClient(create_app(settings)) as client:
        sid = client.post("/api/sessions", headers=headers, json={}).json()["id"]
        response = client.post(
            f"/api/sessions/{sid}/files/preview",
            headers=headers,
            files={"file": ("network.csv", content)},
            data={"directed": "true"},
        )
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["metadata"]["vertex_count"] == 3 and preview["row_count"] == 2
        assert preview["provenance"]["source_column"] == "employee"
        assert client.get(f"/api/sessions/{sid}/files", headers=headers).json() == []
        imported = client.post(
            f"/api/sessions/{sid}/files",
            headers=headers,
            files={"file": ("network.csv", content)},
            data={"directed": "true"},
        ).json()
        graph = client.app.state.runtime.graph_store.read_graph(imported["id"], sid)
        assert (
            graph["vertices"] == preview["vertices"]
            and graph["edges"] == preview["edges"]
        )
        assert imported["sha256"] == preview["provenance"]["input_sha256"]
        assert not list((settings.data_root / "analytics").glob("*/revision-*"))


def test_cpu_edgelist_supports_comments_and_numeric_ids(graph_store, session):
    record = graph_store.ingest(
        session_id=session.id,
        role=FileRole.graph,
        filename="network.txt",
        content=b"# comment\n0 1\n1 2\n",
    )
    graph = json.loads(graph_store.execution_path(record.id, session.id).read_text())
    assert [v["id"] for v in graph["vertices"]] == [0, 1, 2]
