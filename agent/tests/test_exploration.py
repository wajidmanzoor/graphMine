"""Display state is private, bounded, recoverable and separate from saved evidence."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from graphmine_agent.backup import online_snapshot, restore_snapshot
from graphmine_agent.database import Database, RecordNotFound
from graphmine_agent.exploration import Exploration, SaveExploration
from graphmine_agent.identity import AccountError, Principal, identity_scope
from graphmine_agent.models import SessionRecord
from test_accounts import PASSWORD
from test_database_workspace import source, workspace  # noqa: F401


def view(file_id):
    return {"scope": {"file_id": file_id}, "layout": "circle", "filters": {"search": "Ada", "time_start": "100", "include_untimed": False},
            "viewport": {"zoom": 1.5, "pan": {"x": 50, "y": -20}, "positions": [
                {"id": 1, "x": 3, "y": 4}, {"id": "1", "x": 5, "y": 6}, {"id": 9007199254740993, "x": 7, "y": 8}]},
            "selected_vertices": [1, "1", 9007199254740993], "selected_edges": ["edge"]}


def state(workspace):
    return {"active_file_id": workspace.file["id"], "view": {"file_id": workspace.file["id"]}, "views": [view(workspace.file["id"])]}


def endpoint(workspace):
    return f"/api/sessions/{workspace.session['id']}/exploration"


def save(workspace, document=None, revision=0):
    response = workspace.client.put(endpoint(workspace), json={"expected_revision": revision, "state": document or state(workspace)})
    assert response.status_code == 200, response.text
    return response.json()


def test_preferences_preserve_exact_ids_and_survive_service_recreation(workspace):
    original = Path(workspace.runtime.database.get_file(workspace.file["id"]).source_path).read_bytes()
    fresh = workspace.client.get(endpoint(workspace))
    assert fresh.json()["state"] is None and fresh.json()["revision"] == 0
    assert len(fresh.json()["storage_key"]) == 64 and "no-store" in fresh.headers["Cache-Control"]
    saved = save(workspace)
    restored = Exploration(workspace.runtime).get(workspace.session["id"])
    assert restored["state"] == saved["state"] and restored["revision"] == 1
    assert restored["storage_key"] == fresh.json()["storage_key"]
    assert restored["state"]["views"][0]["selected_vertices"] == [1, "1", 9007199254740993]
    assert restored["state"]["views"][0]["viewport"]["positions"][2]["id"] == 9007199254740993
    assert Path(workspace.runtime.database.get_file(workspace.file["id"]).source_path).read_bytes() == original


def test_concurrent_tabs_cannot_silently_overwrite_each_other(workspace):
    save(workspace)
    left, right = state(workspace), state(workspace)
    right["views"][0]["layout"] = "grid"
    def update(document):
        return workspace.client.put(endpoint(workspace), json={"expected_revision": 1, "state": document})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(update, (left, right)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409).json()["error"]
    assert conflict["code"] == "exploration_conflict" and conflict["details"]["revision"] == 2
    winner = next(response.json() for response in responses if response.status_code == 200)
    assert workspace.client.get(endpoint(workspace)).json()["state"] == winner["state"]


@pytest.mark.parametrize("change", [
    lambda value: value["views"][0]["viewport"].update(zoom="NaN"),
    lambda value: value["views"][0]["viewport"].update(pan={"x": "Infinity", "y": 0}),
    lambda value: value["views"][0]["viewport"].update(positions=[{"id": 1, "x": 0, "y": 0}] * 501),
    lambda value: value["views"][0]["viewport"].update(positions=[{"id": 1, "x": 0, "y": 0}] * 2),
    lambda value: value["views"][0].update(selected_vertices=[True]),
    lambda value: value["views"][0].update(layout="script"),
    lambda value: value.update(views=value["views"] * 2),
])
def test_invalid_or_oversized_settings_do_not_change_saved_state(workspace, change):
    saved = save(workspace)
    invalid = state(workspace); change(invalid)
    response = workspace.client.put(endpoint(workspace), json={"expected_revision": 1, "state": invalid})
    assert response.status_code == 422
    assert workspace.client.get(endpoint(workspace)).json()["state"] == saved["state"]


def test_state_byte_budget_is_enforced(workspace):
    value = state(workspace)
    value["views"][0]["viewport"]["positions"] = [{"id": str(index) + "x" * 1500, "x": 0, "y": 0} for index in range(6000)]
    response = workspace.client.put(endpoint(workspace), json={"expected_revision": 0, "state": value})
    assert response.status_code == 413 and response.json()["error"]["code"] == "resource_limit"


def test_foreign_conversations_and_files_are_rejected(workspace):
    service = Exploration(workspace.runtime)
    accounts = SimpleNamespace(upload_remaining=lambda _: 100_000_000)
    with identity_scope(Principal("alice", "alice", accounts)):
        alice = workspace.runtime.database.create_session(SessionRecord())
        service.save(alice.id, SaveExploration(expected_revision=0, state={}))
        with pytest.raises(RecordNotFound):
            service.save(alice.id, SaveExploration(expected_revision=1, state=state(workspace)))
    with identity_scope(Principal("bob", "bob", accounts)):
        for problem in (lambda: Exploration(workspace.runtime).get(alice.id), lambda: Exploration(workspace.runtime).save(alice.id, SaveExploration(expected_revision=1, state={}))):
            with pytest.raises(RecordNotFound):
                problem()
    other = workspace.client.post("/api/sessions", json={"domain_id": "general"}).json()
    response = workspace.client.put(f"/api/sessions/{other['id']}/exploration", json={"expected_revision": 0, "state": state(workspace)})
    assert response.status_code == 404


def test_account_usage_and_conversation_deletion_include_view_state(workspace):
    accounts = workspace.runtime.accounts
    alice = accounts.create_user("alice", PASSWORD)
    with identity_scope(Principal(alice["id"], "alice", accounts)):
        session = workspace.runtime.database.create_session(SessionRecord())
        service = Exploration(workspace.runtime)
        service.save(session.id, SaveExploration(expected_revision=0, state={}))
        assert accounts.storage_usage(alice["id"])["exploration"] > 0
        workspace.runtime.database.delete_session(session.id)
        assert accounts.storage_usage(alice["id"])["exploration"] == 0
    denied = SimpleNamespace(upload_remaining=lambda _: 0)
    with identity_scope(Principal("limited", "limited", denied)):
        session = workspace.runtime.database.create_session(SessionRecord())
        with pytest.raises(AccountError, match="storage"):
            Exploration(workspace.runtime).save(session.id, SaveExploration(expected_revision=0, state={}))


def test_missing_files_and_changed_result_revisions_are_pruned_without_executing(workspace, monkeypatch):
    record = {"id": "saved", "session_id": workspace.session["id"], "revision": 1,
              "validation": {"order": ["step"], "plan": {"steps": [{"id": "step", "problem": "k-core", "input": {"input": "main"}}]}},
              "input_files": {"main": {"file_id": workspace.file["id"]}}}
    monkeypatch.setattr(workspace.runtime.analytics, "get", lambda _: deepcopy(record))
    document = state(workspace)
    scope = {"result": {"workflow_id": "saved", "revision": 1, "step": "step", "port": "out", "index": 0, "context": True}}
    document["view"] = document["views"][0]["scope"] = scope
    save(workspace, document)
    record["revision"] = 2
    recovered = workspace.client.get(endpoint(workspace)).json()
    assert recovered["warnings"] and recovered["state"]["view"] is None and recovered["state"]["views"] == []
    assert recovered["state"]["active_file_id"] == workspace.file["id"]
    assert workspace.client.put(endpoint(workspace), json={"expected_revision": 1, "state": document}).status_code == 409
    workspace.runtime.database.delete_file(workspace.file["id"])
    assert workspace.client.get(endpoint(workspace)).json()["state"]["active_file_id"] is None


def enrichments(workspace):
    graph = json.loads(workspace.runtime.graph_store.execution_path(workspace.file["id"], workspace.session["id"]).read_bytes())
    first = workspace.client.post(f"/api/files/{workspace.file['id']}/enrichments", json={"mapping": "accounts", "fields": ["risk"], "ids": [graph["vertices"][0]["id"]]})
    assert first.status_code == 201, first.text
    second = workspace.client.post(f"/api/files/{first.json()['file']['id']}/enrichments", json={"mapping": "transfers", "kind": "edges", "fields": ["reason"]})
    assert second.status_code == 201, second.text
    return first.json(), second.json()


def test_overlay_uses_saved_values_and_exact_updated_ids_without_live_sql(workspace, monkeypatch):
    first, second = enrichments(workspace)
    document = state(workspace); document["views"][0]["overlay_file_id"] = second["file"]["id"]
    document["views"][0].update(label_attribute="risk", color_attribute="risk")
    save(workspace, document)
    def unavailable(*_, **__):
        raise AssertionError("Restoring attributes must never query a live database")
    monkeypatch.setattr("graphmine_agent.database_enrichment.sql_connection", unavailable)
    workspace.config.unlink()
    response = workspace.client.post(endpoint(workspace) + "/overlay", json={"scope": document["view"], "file_id": second["file"]["id"]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["vertices"] == first["updates"] and result["edges"] == second["updates"]
    assert result["fields"] == {"vertices": ["risk"], "edges": ["reason"]}
    assert first["file"]["provenance"]["source"]["enrichment"]["updated_ids"] == [row["id"] for row in first["updates"]]
    assert workspace.client.get(endpoint(workspace)).json()["state"]["views"][0]["overlay_file_id"] == second["file"]["id"]


def test_unrelated_or_corrupt_overlay_is_not_applied(workspace):
    _, enriched = enrichments(workspace)
    response = workspace.client.post(endpoint(workspace) + "/overlay", json={"scope": {"file_id": enriched["file"]["id"]}, "file_id": workspace.file["id"]})
    assert response.status_code == 409
    file = workspace.runtime.database.get_file(enriched["file"]["id"])
    Path(file.source_path).write_bytes(b"{}")
    response = workspace.client.post(endpoint(workspace) + "/overlay", json={"scope": {"file_id": workspace.file["id"]}, "file_id": file.id})
    assert response.status_code == 409 and response.json()["error"]["code"] == "data_integrity"


def test_online_backup_restores_settings_and_attributes_with_rebased_paths(workspace, tmp_path):
    _, enriched = enrichments(workspace)
    document = state(workspace); document["views"][0]["overlay_file_id"] = enriched["file"]["id"]
    saved = save(workspace, document)
    backup = tmp_path / "exploration-backup"
    online_snapshot(workspace.runtime.settings.data_root, backup)
    report = restore_snapshot(backup, tmp_path / "exploration-restored")
    root = Path(report["data_root"])
    service = Exploration(SimpleNamespace(settings=replace(workspace.runtime.settings, data_root=root), database=Database(root / "agent.sqlite3")))
    assert service.get(workspace.session["id"])["state"] == saved["state"]
    from graphmine_agent.exploration import ReadOverlay
    value = service.overlay(workspace.session["id"], ReadOverlay(scope={"file_id": workspace.file["id"]}, file_id=enriched["file"]["id"]))
    assert value["edges"] == enriched["updates"]
