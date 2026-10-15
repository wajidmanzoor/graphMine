"""Reusable datasets preserve lineage, ownership, versions and full saved data."""

import hashlib
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.api import create_app
from test_accounts import PASSWORD, login


@pytest.fixture
def library(settings, triangle_graph):
    with TestClient(create_app(replace(settings, accounts_enabled=True))) as client:
        runtime = client.app.state.runtime
        for user in ("alice", "bob"):
            runtime.accounts.create_user(user, PASSWORD)
        alice, bob = login(client), login(client, "bob")
        sessions = [
            client.post("/api/sessions", headers=alice, json={}).json()["id"]
            for _ in range(2)
        ]
        file = client.post(
            f"/api/sessions/{sessions[0]}/files",
            headers=alice,
            files={"file": ("triangle.json", triangle_graph)},
        ).json()
        yield client, runtime, alice, bob, sessions, file


def save(client, headers, **body):
    response = client.post(
        "/api/datasets", headers=headers, json={"name": "Team network", **body}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_copy_survives_source_and_library_deletion(library):
    client, runtime, alice, _, sessions, file = library
    version = save(client, alice, file_id=file["id"])
    assert (
        client.delete(f"/api/sessions/{sessions[0]}", headers=alice).status_code == 204
    )
    response = client.post(
        f"/api/sessions/{sessions[1]}/datasets/{version['id']}/import", headers=alice
    )
    assert response.status_code == 201, response.text
    imported = response.json()["file"]
    assert imported["id"] != file["id"]
    assert imported["provenance"]["source"]["file_id"] == file["id"]
    assert imported["provenance"]["sha256"] == version["sha256"]
    assert (
        client.delete(f"/api/datasets/{version['id']}", headers=alice).status_code
        == 204
    )
    preview = client.get(f"/api/files/{imported['id']}/graph-preview", headers=alice)
    assert preview.status_code == 200 and preview.json()["vertex_count"] == 3
    # Each new workflow can resolve the copied file without the original session.
    from graphmine_agent.analytics import InputReference

    inputs = runtime.analytics._inputs(
        sessions[1], {"main": InputReference(file_id=imported["id"])}
    )
    assert len(inputs["main"]["data"]["vertices"]) == 3
    lineage = runtime.analytics._input_provenance(
        {"main": InputReference(file_id=imported["id"])}
    )
    assert lineage["main"]["version_id"] == version["id"]


def test_versions_never_reuse_numbers_and_are_immutable(library):
    client, _, alice, _, _, file = library
    first = save(client, alice, file_id=file["id"])
    second = save(client, alice, file_id=file["id"], dataset_id=first["dataset_id"])
    assert second["version"] == 2 and first["sha256"] == second["sha256"]
    client.delete(f"/api/datasets/{second['id']}", headers=alice)
    third = save(client, alice, file_id=file["id"], dataset_id=first["dataset_id"])
    assert third["version"] == 3
    assert client.get("/api/datasets", headers=alice).json() == [third, first]


def test_datasets_cannot_cross_accounts(library):
    client, _, alice, bob, sessions, file = library
    version = save(client, alice, file_id=file["id"])
    other = client.post("/api/sessions", headers=bob, json={}).json()["id"]
    assert client.get("/api/datasets", headers=bob).json() == []
    for path, body in [
        ("/api/datasets", {"name": "stolen", "file_id": file["id"]}),
        (f"/api/sessions/{other}/datasets/{version['id']}/import", None),
        (f"/api/sessions/{sessions[1]}/datasets/{version['id']}/import", None),
    ]:
        assert client.post(path, headers=bob, json=body).status_code == 404
    assert (
        client.delete(f"/api/datasets/{version['id']}", headers=bob).status_code == 404
    )
    assert client.get("/api/datasets").status_code == 401


def test_saved_data_counts_toward_storage_and_rejects_full_accounts(
    library, monkeypatch
):
    client, runtime, alice, _, _, file = library
    version = save(client, alice, file_id=file["id"])
    user = client.get("/api/auth/me", headers=alice).json()["user"]["id"]
    usage = runtime.accounts.storage_usage(user)
    assert usage["datasets"] > version["size_bytes"]
    assert usage["used"] == usage["uploads"] + usage["results"] + usage["datasets"]
    monkeypatch.setattr(runtime.accounts, "upload_remaining", lambda _: 0)
    response = client.post(
        "/api/datasets", headers=alice, json={"name": "full", "file_id": file["id"]}
    )
    assert (
        response.status_code == 429
        and response.json()["error"]["code"] == "storage_limit"
    )
    assert len(client.get("/api/datasets", headers=alice).json()) == 1


def saved_group(runtime, session, graph):
    record = {
        "id": "derived",
        "session_id": session,
        "revision": 2,
        "status": "completed",
        "validation": {
            "workflow_hash": "a" * 64,
            "plan": {
                "steps": [
                    {
                        "id": "shrink",
                        "operation": "graph-transformation",
                        "input": {"input": "main"},
                    },
                    {
                        "id": "groups",
                        "operation": "maximal-cliques",
                        "input": {"step": "shrink", "port": "graph"},
                    },
                ]
            },
        },
        "steps": {"shrink": {"status": "completed"}, "groups": {"status": "completed"}},
    }
    runtime.analytics._save(record)
    directory = runtime.analytics._directory(record)
    runtime.analytics._write(
        directory / "step-shrink.json",
        {
            "result": {
                "ports": {"graph": {"type": "graph", "value": graph, "complete": True}}
            }
        },
    )
    runtime.analytics._write(
        directory / "step-groups.json",
        {
            "result": {
                "ports": {
                    "groups": {
                        "type": "vertex_groups",
                        "value": [{"vertices": [0, 501, "501"]}],
                        "complete": False,
                    }
                }
            }
        },
    )


def test_result_reuse_uses_full_effective_graph_and_records_incomplete_source(
    library, triangle_graph
):
    client, runtime, alice, bob, sessions, _ = library
    graph = json.loads(triangle_graph)
    graph["vertices"] = [{"id": i} for i in range(502)] + [{"id": "501"}]
    graph["edges"] = [
        {"id": "a", "source": 0, "target": 501},
        {"id": "b", "source": 501, "target": "501"},
    ]
    saved_group(runtime, sessions[0], graph)
    body = {
        "workflow_id": "derived",
        "expected_revision": 2,
        "step": "groups",
        "port": "groups",
        "group_index": 0,
    }
    assert (
        client.post(
            "/api/datasets", headers=bob, json={"name": "hidden", **body}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/datasets",
            headers=alice,
            json={"name": "stale", **body, "expected_revision": 1},
        ).status_code
        == 409
    )
    version = save(client, alice, **body)
    assert not version["source_complete"] and version["source"]["revision"] == 2
    response = client.post(
        f"/api/sessions/{sessions[1]}/datasets/{version['id']}/import", headers=alice
    )
    assert response.status_code == 201, response.text
    copied = runtime.graph_store.read_graph(response.json()["file"]["id"], sessions[1])
    assert [v["id"] for v in copied["vertices"]] == [0, 501, "501"]
    assert copied["edges"] == graph["edges"]
    with runtime.database._connect() as db:
        raw = db.execute(
            "SELECT content FROM dataset_versions WHERE id=?", (version["id"],)
        ).fetchone()[0]
    assert hashlib.sha256(raw).hexdigest() == version["sha256"]


def test_corrupted_snapshot_is_not_imported(library):
    client, runtime, alice, _, sessions, file = library
    version = save(client, alice, file_id=file["id"])
    with runtime.database._connect() as db:
        db.execute(
            "UPDATE dataset_versions SET content=? WHERE id=?", (b"{}", version["id"])
        )
    response = client.post(
        f"/api/sessions/{sessions[1]}/datasets/{version['id']}/import", headers=alice
    )
    assert response.status_code == 409
    assert client.get(f"/api/sessions/{sessions[1]}/files", headers=alice).json() == []
