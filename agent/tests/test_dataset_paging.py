"""Dataset lists do not parse provenance or payloads, and search all versions."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from graphmine_agent.database import Database, SCHEMA_VERSION
from test_datasets import library, save  # noqa: F401


def seed(library, count=45):
    client, runtime, alice, bob, sessions, file = library
    first = save(client, alice, file_id=file["id"])
    with runtime.database._connect() as db:
        row = db.execute("SELECT owner_id,content FROM dataset_versions WHERE id=?", (first["id"],)).fetchone()
        for i in range(count):
            item = {**first, "id": f"version-{i}", "dataset_id": f"collection-{i}", "name": f"Network {i}", "source": {"payload": "x" * 50_000}}
            if i == 0:
                item["name"] = "Straße 100%_network"
            db.execute("INSERT INTO dataset_versions VALUES (?,?,?,?,?,?,?)", (item["id"], item["dataset_id"], 1, row[0], json.dumps(item), row[1], first["size_bytes"]))
    return first


def test_light_pages_search_and_lazy_provenance_are_owner_scoped(library, monkeypatch):
    client, runtime, alice, bob, _, _ = library
    first = seed(library)
    # SQLite authorizer proves listing doesn't read the original metadata/blob.
    connect = runtime.database._connect
    @contextmanager
    def guarded():
        with connect() as db:
            db.set_authorizer(lambda action, table, column, *_: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table == "dataset_versions" else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(runtime.database, "_connect", guarded)
    path = "/api/datasets/page"
    first_page = client.get(path, headers=alice).json()
    assert len(first_page["items"]) == 20 and first_page["has_more"]
    assert len(json.dumps(first_page)) < 15000 and all("source" not in row for row in first_page["items"])
    pages = [client.get(path, headers=alice, params={"offset": offset}).json() for offset in (0, 20, 40)]
    ids = [item["id"] for page in pages for item in page["items"]]
    assert len(ids) == len(set(ids)) == 46 and ids[-1] == first["id"]
    assert not pages[-1]["has_more"]
    for query in ("STRASSE", "100%_", "graph"):
        result = client.get(path, headers=alice, params={"q": query}).json()
        assert result["items"]
    assert client.get(path, headers=alice, params={"kind": "table"}).json()["items"] == []
    assert client.get(path, headers=bob).json()["items"] == []
    assert client.get(path).status_code == 401
    for params in ({"limit": 101}, {"limit": 0}, {"offset": -1}, {"q": "x" * 201}, {"kind": "invalid"}):
        assert client.get(path, headers=alice, params=params).status_code == 422
    monkeypatch.setattr(runtime.database, "_connect", connect)
    assert client.get("/api/datasets/version-0/provenance", headers=alice).json()["source"] == {"payload": "x" * 50_000}
    assert client.get("/api/datasets/version-0/provenance", headers=bob).status_code == 404


def test_collection_picker_uses_latest_retained_version_and_migration_backfills(library):
    client, runtime, alice, _, _, file = library
    first = save(client, alice, file_id=file["id"])
    second = save(client, alice, file_id=file["id"], dataset_id=first["dataset_id"])
    path = "/api/datasets/page?latest=true"
    assert [i["id"] for i in client.get(path, headers=alice).json()["items"]] == [second["id"]]
    client.delete(f"/api/datasets/{second['id']}", headers=alice)
    assert [i["id"] for i in client.get(path, headers=alice).json()["items"]] == [first["id"]]
    with runtime.database._connect() as db:
        db.execute("DROP TRIGGER dataset_summary_insert"); db.execute("DROP TRIGGER dataset_summary_update")
        db.execute("DROP TABLE dataset_summaries"); db.execute("PRAGMA user_version=9")
    Database(runtime.database.path)
    assert client.get(path, headers=alice).json()["items"][0]["id"] == first["id"]
    third = save(client, alice, file_id=file["id"], dataset_id=first["dataset_id"])
    assert third["version"] == 3
    assert client.get(path, headers=alice).json()["items"][0]["id"] == third["id"]
    with runtime.database._connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_workflow_indexes_do_not_consume_account_storage_or_enter_backups(library, tmp_path):
    from graphmine_agent.backup import online_snapshot, restore_snapshot

    client, runtime, alice, bob, sessions, _ = library
    record = {"id": "paged-private", "session_id": sessions[0], "revision": 1, "status": "completed",
              "steps": {"rank": {"status": "completed"}}, "validation": {"plan": {"steps": [{"id": "rank"}]}}}
    service = runtime.analytics
    service._save(record)
    source = service._directory(record) / "step-rank.json"
    service._write(source, {"result": {"ports": {"scores": {"type": "vertex_scores", "value": [{"vertex": i, "score": i} for i in range(500)]}}}})
    with runtime.database._connect() as db:
        owner = db.execute("SELECT owner_id FROM sessions WHERE id=?", (sessions[0],)).fetchone()[0]
    before = runtime.accounts.storage_usage(owner)
    url = "/api/workflows/paged-private/steps/rank/ports/scores"
    assert client.get(url, headers=alice).status_code == 200
    assert client.get(url, headers=bob).status_code == 404
    assert source.with_suffix(".rows.sqlite3").is_file()
    assert runtime.accounts.storage_usage(owner) == before
    # A partially built cache must also be ignored by backup inventory/quota.
    temporary = source.with_suffix(".rows.sqlite3.12345678.tmp")
    temporary.write_bytes(b"unfinished derived cache")
    assert runtime.accounts.storage_usage(owner) == before
    manifest = online_snapshot(runtime.settings.data_root, tmp_path / "snapshot")
    assert not any(".rows.sqlite3" in name for name in manifest["files"])
    restored = restore_snapshot(tmp_path / "snapshot", tmp_path / "restored")
    assert (Path(restored["data_root"]) / "analytics/paged-private/revision-1/step-rank.json").is_file()
