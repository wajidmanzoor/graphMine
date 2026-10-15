"""Project ACLs never expand access to the private source conversation."""

import asyncio
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest
import test_datasets as dataset_fixtures
import test_workflow_templates as template_fixtures
from graphmine_agent.account_api import AccountMiddleware
from graphmine_agent.backup import online_snapshot, verify_snapshot
from graphmine_agent.history import HistoryStore

library = dataset_fixtures.library
recipes = template_fixtures.recipes


def call(client, headers, method, path, body=None, expected=200):
    response = client.request(
        method, path, headers=headers, **({"json": body} if body is not None else {})
    )
    assert response.status_code == expected, response.text
    return response.json() if response.content else None


def shared(library, role="viewer"):
    client, _, alice, _, _, file = library
    project = call(client, alice, "POST", "/api/projects", {"name": "Team review"}, 201)
    call(
        client,
        alice,
        "POST",
        f"/api/projects/{project['id']}/members",
        {"username": "bob", "role": role},
        204,
    )
    item = call(
        client,
        alice,
        "POST",
        f"/api/projects/{project['id']}/items",
        {"name": "Shared network", "file_id": file["id"]},
        201,
    )
    return project, item


@pytest.mark.parametrize("role", ["viewer", "editor"])
def test_project_roles_and_revocation_keep_private_sources_private(library, role):
    client, _, alice, bob, sessions, file = library
    project, item = shared(library, role)
    assert call(client, bob, "GET", "/api/projects")[0]["role"] == role
    assert call(client, bob, "GET", f"/api/project-items/{item['id']}")["snapshot"][
        "data"
    ]["vertices"]
    for path in (
        f"/api/sessions/{sessions[0]}",
        f"/api/files/{file['id']}/graph-preview",
    ):
        call(client, bob, "GET", path, expected=404)
    call(
        client,
        bob,
        "POST",
        f"/api/projects/{project['id']}/items",
        {"name": "Not mine", "file_id": file["id"]},
        404 if role == "editor" else 403,
    )
    call(
        client,
        bob,
        "POST",
        f"/api/project-items/{item['id']}/annotations",
        {"text": "Review this connection"},
        201 if role == "editor" else 403,
    )
    call(
        client,
        bob,
        "POST",
        f"/api/project-items/{item['id']}/views",
        {"name": "Focus", "selected": [0, "0", 9007199254740993]},
        201 if role == "editor" else 403,
    )
    call(client, bob, "POST", f"/api/project-items/{item['id']}/links", {}, 403)
    call(client, bob, "DELETE", f"/api/projects/{project['id']}", expected=403)
    bob_id = call(client, bob, "GET", "/api/auth/me")["user"]["id"]
    call(
        client,
        alice,
        "DELETE",
        f"/api/projects/{project['id']}/members/{bob_id}",
        expected=204,
    )
    call(client, bob, "GET", f"/api/project-items/{item['id']}", expected=404)
    assert call(client, bob, "GET", "/api/projects") == []


def test_shared_links_are_scoped_expiring_revocable_and_hide_discussions(library):
    client, runtime, alice, _, _, _ = library
    _, item = shared(library)
    prefix = f"/api/project-items/{item['id']}"
    call(
        client,
        alice,
        "POST",
        prefix + "/annotations",
        {"text": "Internal discussion"},
        201,
    )
    link = call(client, alice, "POST", prefix + "/links", {"days": 1}, 201)
    token = link["url"].split("#")[1]
    public = call(client, {}, "POST", "/api/shared/read", {"token": token})
    assert public["name"] == item["name"]
    assert "Internal discussion" not in json.dumps(public)
    assert not {"project_id", "notes", "links", "members"} & public.keys()
    with runtime.database._connect() as db:
        stored = db.execute("SELECT token_hash FROM project_links").fetchone()[0]
        assert stored == hashlib.sha256(token.encode()).hexdigest() and stored != token
        db.execute("UPDATE project_links SET expires_at=0")
    call(client, {}, "POST", "/api/shared/read", {"token": token}, 404)
    link = call(client, alice, "POST", prefix + "/links", {}, 201)
    call(client, alice, "DELETE", f"/api/project-links/{link['id']}", expected=204)
    call(
        client,
        {},
        "POST",
        "/api/shared/read",
        {"token": link["url"].split("#")[1]},
        404,
    )
    call(client, {}, "POST", prefix + "/annotations", {"text": "unauthorized"}, 401)


def test_project_copy_survives_source_and_project_deletion(library):
    client, _, alice, bob, sessions, _ = library
    project, item = shared(library)
    call(client, alice, "DELETE", f"/api/sessions/{sessions[0]}", expected=204)
    sid = call(client, bob, "POST", "/api/sessions", {}, 201)["id"]
    copied = call(
        client,
        bob,
        "POST",
        f"/api/sessions/{sid}/project-items/{item['id']}/import",
        expected=201,
    )
    call(client, alice, "DELETE", f"/api/projects/{project['id']}", expected=204)
    assert (
        call(client, bob, "GET", f"/api/files/{copied['file']['id']}/graph-preview")[
            "vertex_count"
        ]
        == 3
    )
    assert copied["file"]["provenance"]["project_item"] == item["id"]


def test_project_storage_is_charged_to_owner_and_failed_writes_are_atomic(
    library, monkeypatch
):
    client, runtime, alice, bob, _, _ = library
    _, item = shared(library, "editor")
    uid = call(client, alice, "GET", "/api/auth/me")["user"]["id"]
    usage = runtime.accounts.storage_usage(uid)
    assert usage["shared"] > item["size_bytes"]
    monkeypatch.setattr(runtime.accounts, "upload_remaining", lambda _: 0)
    call(
        client,
        bob,
        "POST",
        f"/api/project-items/{item['id']}/annotations",
        {"text": "No room"},
        429,
    )
    assert call(client, alice, "GET", f"/api/project-items/{item['id']}")["notes"] == []


def test_workflow_sharing_is_revision_checked_and_includes_exact_snapshot(recipes):
    client, runtime, alice, bob, sid, file, record, result = recipes
    graph = runtime.graph_store.read_graph(file["id"], sid)
    runtime.analytics._write(
        runtime.analytics._directory(record) / "inputs.json",
        {"main": {"kind": "graph", "data": graph}},
    )
    project = call(client, alice, "POST", "/api/projects", {"name": "Findings"}, 201)
    path = f"/api/projects/{project['id']}/items"
    call(
        client,
        alice,
        "POST",
        path,
        {"name": "Result", "workflow_id": record["id"], "expected_revision": 2},
        409,
    )
    item = call(
        client,
        alice,
        "POST",
        path,
        {"name": "Result", "workflow_id": record["id"], "expected_revision": 1},
        201,
    )
    value = call(client, alice, "GET", f"/api/project-items/{item['id']}")
    assert value["snapshot"]["result"] == result
    assert value["snapshot"]["inputs"]["main"]["data"] == graph
    call(client, bob, "GET", f"/api/project-items/{item['id']}", expected=404)


def test_disabling_owner_invalidates_public_links(library):
    client, runtime, alice, _, _, _ = library
    _, item = shared(library)
    link = call(
        client, alice, "POST", f"/api/project-items/{item['id']}/links", {}, 201
    )
    runtime.accounts.disable("alice")
    call(
        client,
        {},
        "POST",
        "/api/shared/read",
        {"token": link["url"].split("#")[1]},
        404,
    )


def test_project_snapshot_backup_detects_corrupt_content(library, tmp_path):
    _, runtime, _, _, _, _ = library
    shared(library)
    snapshot = tmp_path / "project-backup"
    manifest = online_snapshot(runtime.settings.data_root, snapshot)
    assert verify_snapshot(snapshot) == manifest
    database = snapshot / "data/agent.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("UPDATE project_items SET content=?", (b"{}",))
    manifest["files"]["data/agent.sqlite3"] = {
        "sha256": HistoryStore.digest(database),
        "size_bytes": database.stat().st_size,
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="integrity mismatch"):
        verify_snapshot(snapshot)


async def test_public_share_admission_is_held_until_response_finishes():
    started, release = asyncio.Event(), asyncio.Event()
    active = 0

    async def application(scope, receive, send):
        nonlocal active
        active += 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        if active == 2:
            started.set()
        await release.wait()
        await send({"type": "http.response.body", "body": b"last", "more_body": False})

    middleware = AccountMiddleware(application)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/shared/read",
        "app": SimpleNamespace(
            state=SimpleNamespace(
                runtime=SimpleNamespace(
                    settings=SimpleNamespace(accounts_enabled=False)
                )
            )
        ),
    }

    async def receive():
        return {"type": "http.request", "body": b""}

    messages = []

    async def send(message):
        messages.append(message)

    first = [asyncio.create_task(middleware(scope, receive, send)) for _ in range(2)]
    try:
        await asyncio.wait_for(started.wait(), 2)
        await middleware(scope, receive, send)
        assert [
            message["status"]
            for message in messages
            if message["type"] == "http.response.start"
        ] == [200, 200, 429]
    finally:
        release.set()
        await asyncio.gather(*first)
    await middleware(scope, receive, send)
    assert [
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    ][-1] == 200


def test_saved_view_roundtrip_keeps_whitespace_and_integer_ids_distinct(library):
    client, _, alice, _, sessions, _ = library
    graph = {
        "graph": {
            "id": "typed",
            "directed": False,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [{"id": " 1 "}, {"id": "1"}, {"id": 1}],
        "edges": [
            {"id": 0, "source": " 1 ", "target": "1"},
            {"id": 1, "source": "1", "target": 1},
        ],
    }
    uploaded = client.post(
        f"/api/sessions/{sessions[1]}/files",
        headers=alice,
        files={"file": ("typed.json", json.dumps(graph))},
    ).json()
    project = call(client, alice, "POST", "/api/projects", {"name": "Typed IDs"}, 201)
    item = call(
        client,
        alice,
        "POST",
        f"/api/projects/{project['id']}/items",
        {"name": "Typed graph", "file_id": uploaded["id"]},
        201,
    )
    view = {
        "name": "  Focus  ",
        "selected": [" 1 ", "1", 1],
        "positions": [{"vertex": " 1 ", "x": 10, "y": 20}],
    }
    call(client, alice, "POST", f"/api/project-items/{item['id']}/views", view, 201)
    saved = call(client, alice, "GET", f"/api/project-items/{item['id']}")["notes"][0]
    assert saved["name"] == "Focus"
    assert (
        saved["selected"] == view["selected"]
        and saved["positions"] == view["positions"]
    )
