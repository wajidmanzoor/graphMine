"""Home summaries are private and cheap; shortcuts preserve immutable inputs."""

import json
import sqlite3

import pytest

from graphmine_agent.datasets import DatasetLibrary
from graphmine_agent.identity import Principal, identity_scope
from graphmine_agent.query_library import QueryLibrary
from graphmine_agent.query_previews import QueryPreviews
from graphmine_agent.table_artifacts import make_table
from test_database_workspace import source, workspace  # noqa: F401
from test_datasets import library, save  # noqa: F401


def recent(client, section, headers=None, **params):
    response = client.get(f"/api/workspace/recent/{section}", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_latest_retained_dataset_per_collection_is_paged_and_private(library):
    client, _, alice, bob, _, file = library
    first = save(client, alice, file_id=file["id"])
    second = save(client, alice, file_id=file["id"], dataset_id=first["dataset_id"])
    other = save(client, alice, file_id=file["id"], name="Other graph")
    page = recent(client, "datasets", alice, limit=1)
    assert page["has_more"] and page["items"][0]["id"] == other["id"]
    page = recent(client, "datasets", alice, limit=1, offset=1)
    assert not page["has_more"] and page["items"][0]["id"] == second["id"]
    assert recent(client, "datasets", bob)["items"] == []
    client.delete(f"/api/datasets/{second['id']}", headers=alice)
    assert {item["id"] for item in recent(client, "datasets", alice)["items"]} == {first["id"], other["id"]}


def test_analysis_ownership_archive_filter_and_priority_precede_paging(library, monkeypatch):
    client, runtime, alice, bob, sessions, _ = library
    other = client.post("/api/sessions", headers=bob, json={}).json()["id"]
    client.patch(f"/api/sessions/{sessions[1]}", headers=alice, json={"archived": True})
    records = [
        ("active", sessions[0], "awaiting_review", "2026-01-01"),
        ("finished", sessions[0], "completed", "2026-03-01"),
        ("older", sessions[0], "failed", "2026-02-01"),
        ("archived", sessions[1], "running", "2026-10-01"),
        *[(f"private-{n}", other, "running", "2026-10-20") for n in range(20)],
    ]
    with sqlite3.connect(runtime.analytics.path) as db:
        for identifier, session, status, timestamp in records:
            doc = {"id": identifier, "session_id": session, "status": status, "revision": 3,
                   "updated_at": timestamp, "validation": {"plan": {"steps": [{"operation": "k-core"}]}},
                   "input_files": {"secret": "private-input"}, "error": "private-error"}
            db.execute("INSERT INTO workflows VALUES (?,?,?)", (identifier, session, json.dumps(doc)))
    monkeypatch.setattr(runtime.analytics, "_all", lambda *_: pytest.fail("Home loaded full workflows"))
    first = recent(client, "analyses", alice, limit=2)
    assert [item["id"] for item in first["items"]] == ["active", "finished"]
    assert first["has_more"] and first["items"][0]["operations"] == ["k-core"]
    second = recent(client, "analyses", alice, limit=2, offset=2)
    assert [item["id"] for item in second["items"]] == ["older"] and not second["has_more"]
    assert "private-input" not in json.dumps(first) and "private-error" not in json.dumps(first)
    assert all(item["id"].startswith("private-") for item in recent(client, "analyses", bob)["items"])
    with sqlite3.connect(runtime.analytics.path) as db:
        assert json.loads(db.execute("SELECT document FROM workflows WHERE id='active'").fetchone()[0])["status"] == "awaiting_review"


def test_saved_queries_are_summaries_without_history_or_parameters(library):
    client, runtime, alice, bob, sessions, _ = library
    with runtime.database._connect() as db:
        owner = db.execute("SELECT owner_id FROM sessions WHERE id=?", (sessions[0],)).fetchone()[0]
    with identity_scope(Principal(owner, "alice", runtime.accounts)):
        for index, kind in enumerate(["saved", "history", "saved"]):
            QueryLibrary(runtime)._put({"id": f"query-{index}", "kind": kind, "source_id": "demo", "dataset_id": "default",
                                       "name": f"Query {index}", "revision": 1, "updated_at": f"2026-10-{index+1:02d}",
                                       "query": {"statement": "RETURN $secret", "parameters": {"secret": "sensitive"}}})
    result = recent(client, "queries", alice, limit=1)
    assert result["has_more"] and result["items"][0]["id"] == "query-2"
    assert "sensitive" not in json.dumps(result) and "statement" not in json.dumps(result)
    assert [item["id"] for item in recent(client, "queries", alice, offset=1)["items"]] == ["query-0"]
    assert recent(client, "queries", bob)["items"] == []


def test_preview_is_not_a_recent_dataset_or_conversation_input(workspace, monkeypatch):
    runtime, client = workspace.runtime, workspace.client
    graph = json.loads(runtime.graph_store.execution_path(workspace.file["id"], workspace.session["id"]).read_bytes())
    preview = QueryPreviews(runtime).store(graph, name="Unsaved", kind="graph", source={"secret": "parameters"}, complete=True)
    before = len(client.get("/api/sessions").json())
    assert preview["id"] not in {item["id"] for item in recent(client, "datasets")["items"]}
    assert client.post(f"/api/datasets/{preview['id']}/conversation", json={"domain_id": "general"}).status_code == 404
    assert len(client.get("/api/sessions").json()) == before
    monkeypatch.setattr(DatasetLibrary, "get", lambda *_args, **_kw: pytest.fail("Home loaded dataset contents"))
    response = recent(client, "datasets")
    assert all(set(item) == {"id", "dataset_id", "version", "size_bytes", "name", "kind", "updated_at", "source_complete"} for item in response["items"])


def test_new_conversation_copies_exact_version_and_stays_private(library):
    client, runtime, alice, bob, sessions, file = library
    first = save(client, alice, file_id=file["id"])
    save(client, alice, file_id=file["id"], dataset_id=first["dataset_id"])
    client.delete(f"/api/sessions/{sessions[0]}", headers=alice)
    result = client.post(f"/api/datasets/{first['id']}/conversation", headers=alice, json={"domain_id": "general"})
    assert result.status_code == 201, result.text
    value = result.json(); session = value["session"]; imported = value["file"]
    assert session["title"] == first["name"] and session["domain_id"] == "general"
    assert imported["id"] != file["id"] and imported["provenance"]["version_id"] == first["id"]
    assert imported["provenance"]["sha256"] == first["sha256"] and value["kind"] == "graph"
    assert client.get(f"/api/sessions/{session['id']}/workspace", headers=bob).status_code == 404
    assert client.get(f"/api/sessions/{session['id']}/workflows", headers=alice).json() == []
    client.delete(f"/api/datasets/{first['id']}", headers=alice)
    assert client.get(f"/api/files/{imported['id']}/graph-preview", headers=alice).json()["vertex_count"] == 3


@pytest.mark.parametrize("failure,expected", [("integrity", 409), ("quota", 429), ("owner", 404), ("domain", 422)])
def test_failed_creation_leaves_no_empty_session(library, monkeypatch, failure, expected):
    client, runtime, alice, bob, _, file = library
    version = save(client, alice, file_id=file["id"])
    headers = bob if failure == "owner" else alice
    before = client.get("/api/sessions", headers=headers).json()
    if failure == "integrity":
        with runtime.database._connect() as db:
            db.execute("UPDATE dataset_versions SET content=? WHERE id=?", (b"{}", version["id"]))
    if failure == "quota":
        monkeypatch.setattr(runtime.accounts, "upload_remaining", lambda _: 0)
    result = client.post(f"/api/datasets/{version['id']}/conversation", headers=headers,
                         json={"domain_id": "missing" if failure == "domain" else "general"})
    assert result.status_code == expected, result.text
    assert client.get("/api/sessions", headers=headers).json() == before


def test_table_shortcut_retains_types_and_incomplete_scope(workspace):
    rows = [{"id": 9007199254740993, "name": "001"}]
    table = make_table(["id", "name"], rows)
    saved = DatasetLibrary(workspace.runtime).store(table, name="Accounts", kind="table", source={"query": "RETURN x"}, complete=False)
    result = workspace.client.post(f"/api/datasets/{saved['id']}/conversation", json={"domain_id": "general"})
    assert result.status_code == 201, result.text
    value = result.json()
    assert value["kind"] == "table" and value["file"]["role"] == "attachment"
    assert not value["file"]["provenance"]["source_complete"]
    path = workspace.runtime.graph_store.execution_path(value["file"]["id"], value["session"]["id"])
    assert json.loads(path.read_bytes())["rows"] == rows


@pytest.mark.parametrize("section", ["datasets", "queries", "analyses"])
def test_recent_route_requires_login_and_bounds_requests(library, section):
    client, _, alice, _, _, _ = library
    url = f"/api/workspace/recent/{section}"
    assert client.get(url).status_code == 401
    for params in ({"limit": 13}, {"offset": -1}, {"offset": 100001}):
        assert client.get(url, headers=alice, params=params).status_code == 422

