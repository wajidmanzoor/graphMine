"""Preview storage is temporary, private, deduplicated, and quota-accounted."""

import hashlib
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.analytics import AnalyticsError, _json
from graphmine_agent.api import create_app
from graphmine_agent.backup import online_snapshot, restore_snapshot, verify_snapshot
from graphmine_agent.database import Database, RecordNotFound
from graphmine_agent.datasets import DatasetLibrary
from graphmine_agent.identity import AccountError, Principal, identity_scope
from graphmine_agent.query_previews import PREVIEW_SECONDS, QueryPreviews, expire_previews
from test_accounts import PASSWORD, account_settings
from test_database_workspace import source, workspace


def query(workspace, statement="MATCH p=()-[]->() RETURN p"):
    response = workspace.client.post("/api/database-sources/demo/queries", json={"statement": statement})
    assert response.status_code == 201, response.text
    return response.json()["dataset"]


def stored_graph(workspace):
    return json.loads(workspace.runtime.graph_store.execution_path(workspace.file["id"], workspace.session["id"]).read_bytes())


def test_repeated_previews_share_content_without_filling_the_library(workspace):
    first = query(workspace)
    second = query(workspace, "MATCH p=()-[]->() RETURN p LIMIT 1")
    assert first["temporary"] and second["temporary"] and first["id"] != second["id"]
    assert first["sha256"] == second["sha256"]
    assert first["source"]["query"] != second["source"]["query"]
    assert len(DatasetLibrary(workspace.runtime).list()) == 1  # fixture's used graph
    with workspace.runtime.database._connect() as db:
        assert db.execute("SELECT count(*) FROM query_previews").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM query_preview_blobs").fetchone()[0] == 1


def test_saving_and_importing_keep_the_same_snapshot_without_rerunning(workspace):
    preview = query(workspace)
    path = f"/api/database-query-snapshots/{preview['id']}"
    response = workspace.client.post(path + "/save")
    assert response.status_code == 200, response.text
    expected = {key: value for key, value in preview.items() if key not in {"temporary", "expires_at"}}
    assert response.json() == expected
    service = QueryPreviews(workspace.runtime)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(service.promote, [preview["id"]] * 2)) == [expected] * 2
    assert workspace.client.delete(path).status_code == 204  # never deletes saved content
    imported = workspace.client.post(f"/api/sessions/{workspace.session['id']}/datasets/{preview['id']}/import")
    assert imported.status_code == 201, imported.text
    assert imported.json()["file"]["provenance"]["version_id"] == preview["id"]
    assert len(workspace.calls) == 2
    assert len(DatasetLibrary(workspace.runtime).list()) == 2


def test_expiration_and_discard_release_only_unreferenced_preview_content(workspace):
    now = [time.time()]
    service = QueryPreviews(workspace.runtime, clock=lambda: now[0])
    options = dict(name="Preview", kind="graph", source={"query": "RETURN n"}, complete=True)
    first = service.store(stored_graph(workspace), **options)
    now[0] += 100
    second = service.store(stored_graph(workspace), **options)
    now[0] += PREVIEW_SECONDS - 100
    with pytest.raises(AnalyticsError, match="expired"):
        service.promote(first["id"])
    assert expire_previews(workspace.runtime.database, now[0]) == 1
    assert service.get(second["id"]) == second
    with workspace.runtime.database._connect() as db:
        assert db.execute("SELECT count(*) FROM query_preview_blobs").fetchone()[0] == 1
    service.discard(second["id"])
    with workspace.runtime.database._connect() as db:
        assert db.execute("SELECT count(*) FROM query_preview_blobs").fetchone()[0] == 0
    assert len(DatasetLibrary(workspace.runtime).list()) == 1


def test_preview_access_and_content_sharing_stay_with_the_owner(workspace):
    accounts = SimpleNamespace(upload_remaining=lambda _: 100_000_000)
    service = QueryPreviews(workspace.runtime)
    options = dict(name="Private", kind="graph", source={}, complete=True)
    graph = stored_graph(workspace)
    with identity_scope(Principal("alice", "alice", accounts)):
        first = service.store(graph, **options)
    with identity_scope(Principal("bob", "bob", accounts)):
        for action in (service.get, service.promote):
            with pytest.raises(RecordNotFound):
                action(first["id"])
        service.discard(first["id"])
        # Do not use another account's content-addressed storage as a side channel.
        second = service.store(graph, **options)
    with identity_scope(Principal("alice", "alice", accounts)):
        assert service.get(first["id"]) == first
    assert first["sha256"] == second["sha256"]
    with workspace.runtime.database._connect() as db:
        assert db.execute("SELECT count(*) FROM query_preview_blobs").fetchone()[0] == 2


def test_storage_counts_shared_content_once_and_promotion_credits_released_bytes(account_settings, triangle_graph):
    with TestClient(create_app(account_settings)) as client:
        runtime = client.app.state.runtime
        accounts = runtime.accounts
        user = accounts.create_user("alice", PASSWORD)
        with identity_scope(Principal(user["id"], "alice", accounts)):
            service = QueryPreviews(runtime)
            options = dict(name="Triangle", kind="graph", source={}, complete=True)
            first = service.store(json.loads(triangle_graph), **options)
            before = accounts.storage_usage(user["id"])
            second = service.store(json.loads(triangle_graph), **options)
            after = accounts.storage_usage(user["id"])
            assert before["used"] == before["previews"] > first["size_bytes"]
            assert after["previews"] - before["previews"] == len(_json(second).encode())
            service.discard(second["id"])
            accounts.settings = replace(accounts.settings, account_storage_bytes=before["used"])
            service.promote(first["id"])
            usage = accounts.storage_usage(user["id"])
            assert usage["previews"] == 0 and 0 < usage["datasets"] <= usage["limit"]


def test_failed_promotion_rolls_back_the_preview_and_its_shared_content(workspace):
    remaining = [100_000_000]
    accounts = SimpleNamespace(upload_remaining=lambda _: remaining[0])
    graph = stored_graph(workspace)
    graph["vertices"][0]["attributes"] = {"text": "x" * 6000}
    with identity_scope(Principal("alice", "alice", accounts)):
        service = QueryPreviews(workspace.runtime)
        options = dict(name="Larger preview", kind="graph", source={}, complete=True)
        first = service.store(graph, **options)
        service.store(graph, **options)
        remaining[0] = 0
        with pytest.raises(AccountError, match="storage allowance"):
            service.promote(first["id"])
        assert service.get(first["id"]) == first
        assert service.library.list() == []
        with pytest.raises(AccountError):
            service.store(graph, **options)


def test_preview_backup_restores_and_audits_deduplicated_content(workspace, tmp_path):
    preview = query(workspace)
    backup = tmp_path / "backup"
    online_snapshot(workspace.runtime.settings.data_root, backup)
    restored = restore_snapshot(backup, tmp_path / "restore")
    runtime = SimpleNamespace(database=Database(Path(restored["data_root"]) / "agent.sqlite3"))
    assert QueryPreviews(runtime).get(preview["id"]) == preview
    database = backup / "data/agent.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("UPDATE query_preview_blobs SET content=?", (b"corrupted",))
    manifest = json.loads((backup / "manifest.json").read_text())
    manifest["files"]["data/agent.sqlite3"] = {"sha256": hashlib.sha256(database.read_bytes()).hexdigest(), "size_bytes": database.stat().st_size}
    (backup / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Query preview content integrity"):
        verify_snapshot(backup)
