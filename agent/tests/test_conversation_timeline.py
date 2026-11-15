"""Bounded, private history pages preserve complete turns and archived evidence."""

import base64
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from graphmine_agent.conversation_timeline import conversation_page
from graphmine_agent.database import Database, SCHEMA_VERSION
from graphmine_agent.models import ConversationEvent
from test_datasets import library  # noqa: F401


def seed(database, session_id, count=100):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with database._connect() as db:
        for number in range(count):
            for role in ("user", "assistant"):
                payload = {"turn_id": f"turn-{number}", "role": role, "message": f"{role} {number}"}
                db.execute("INSERT INTO events(session_id,type,payload,created_at) VALUES (?,?,?,?)",
                           (session_id, "workflow.chat", json.dumps(payload), (start + timedelta(seconds=number * 2 + (role == "assistant"))).isoformat()))


def test_keyset_history_pages_cover_every_turn_without_full_event_reads(database, session, monkeypatch):
    seed(database, session.id, 500)
    def forbidden(*_, **__):
        raise AssertionError("A history page must not use unbounded transcript/event readers")
    monkeypatch.setattr(database, "events", forbidden)
    monkeypatch.setattr(database, "conversation_transcript", forbidden)
    first = conversation_page(database, session.id, limit=13)
    assert len(first["events"]) == 14  # Include the other half of a boundary turn.
    assert first["turn_numbers"]["turn-499"] == 500 and first["event_cursor"] == 1000
    assert len(json.dumps(first)) < 20000
    seen, page = set(), first
    while True:
        seen.update(event["sequence"] for event in page["events"])
        if not page["has_more"]:
            break
        page = conversation_page(database, session.id, before=page["next_cursor"], limit=13)
    assert seen == set(range(1, 1001))
    assert not page["next_cursor"]


def test_new_arrivals_do_not_shift_older_page_cursor(database, session):
    seed(database, session.id, 3)
    first = conversation_page(database, session.id, limit=2)
    added = database.add_event(ConversationEvent(session_id=session.id, type="workflow.chat",
                                               payload={"role": "user", "turn_id": "new", "message": "New arrival"}))
    second = conversation_page(database, session.id, before=first["next_cursor"], limit=2)
    assert {event["payload"]["turn_id"] for event in second["events"]} == {"turn-1"}
    assert database.events(session.id, after=first["event_cursor"], limit=1)[0].sequence == added.sequence


def test_reasoning_pages_keep_final_attempts_and_current_live_text(database, session):
    def event(kind, **payload):
        return database.add_event(ConversationEvent(session_id=session.id, type="workflow." + kind, payload={"turn_id": "thinking", **payload}))
    event("chat", role="user", message="Investigate")
    for part in ("First ", "attempt"):
        event("reasoning.delta", stage="plan", text=part)
    final = event("reasoning", stage="plan", text="First attempt")
    live = event("reasoning.delta", stage="plan", text="Second attempt underway")
    page = conversation_page(database, session.id)
    assert [row["sequence"] for row in page["events"]] == [1, final.sequence, live.sequence]
    event("chat", role="assistant", message="Finished")
    assert all(row["type"] != "workflow.reasoning.delta" for row in conversation_page(database, session.id)["events"])
    assert len(database.events(session.id)) == 6  # Original evidence is retained.


def test_classic_archives_are_indexed_once_and_keep_latest_result_and_legacy_boundary(database, session, monkeypatch):
    database.add_message(session.id, "user", {"message": "Before archival chat"})
    history = database.history
    history.record(session.id, "feedback_command.request", {"message": "/note retained note"})
    history.record(session.id, "feedback_command.response", {"message": "Note saved"})
    database.add_message(session.id, "assistant", {"message": "Duplicate modern message"})
    history.record(session.id, "llm.request", {"prompt": "PRIVATE_MODEL_PROMPT"})
    history.record(session.id, "result.saved", {"id": "r", "job_id": "j", "interpretation": {"summary": "Old interpretation"}})
    history.record(session.id, "result.saved", {"id": "r", "job_id": "j", "interpretation": {"summary": "New interpretation"}})
    first = conversation_page(database, session.id)
    assert [row["message"] for row in first["messages"]] == ["Before archival chat", "/note retained note", "Note saved", "New interpretation"]
    assert "PRIVATE_MODEL_PROMPT" not in json.dumps(first)
    with database._connect() as db:
        assert db.execute("SELECT count(*) FROM conversation_entries WHERE document LIKE '%PRIVATE_MODEL_PROMPT%'").fetchone()[0] == 0
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Warm history must not reread archived event payloads")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", forbidden)
        assert conversation_page(database, session.id) == first
    history.record(session.id, "feedback_command.response", {"message": "Another note"})
    assert conversation_page(database, session.id)["messages"][-1]["message"] == "Another note"


def test_archive_deletion_reveals_previous_result_version(database, session):
    history = database.history
    history.record(session.id, "result.saved", {"id": "r", "job_id": "j", "interpretation": {"summary": "First"}})
    latest = history.record(session.id, "result.saved", {"id": "r", "job_id": "j", "interpretation": {"summary": "Latest"}})
    assert conversation_page(database, session.id)["messages"][-1]["message"] == "Latest"
    next((history.session_path(session.id) / "events").glob(f"*{latest}.json")).unlink()
    assert conversation_page(database, session.id)["messages"][-1]["message"] == "First"


def test_schema_10_migration_backfills_stable_turn_numbers(database, session):
    seed(database, session.id, 4)
    with database._connect() as db:
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'conversation_%'").fetchall():
            db.execute('DROP TRIGGER "' + row[0] + '"')
        for table in ("conversation_entries", "conversation_archive_files", "conversation_archive_state", "conversation_turns"):
            db.execute("DROP TABLE " + table)
        db.execute("PRAGMA user_version=10")
    restored = Database(database.path)
    page = conversation_page(restored, session.id)
    assert page["turn_numbers"] == {f"turn-{i}": i + 1 for i in range(4)}
    with restored._connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_workspace_pages_and_event_polling_are_bounded_and_private(library, monkeypatch):
    client, runtime, alice, bob, sessions, _ = library
    sid = sessions[0]; seed(runtime.database, sid, 40)
    def forbidden(*_, **__):
        raise AssertionError("Paged workspace must not load complete history or feedback records")
    monkeypatch.setattr(runtime.database, "conversation_transcript", forbidden)
    monkeypatch.setattr(runtime.database, "feedback", forbidden)
    response = client.get(f"/api/sessions/{sid}/workspace?history_limit=6", headers=alice)
    assert response.status_code == 200, response.text
    page = response.json()
    assert len(page["events"]) == 6 and page["timeline"]["has_more"]
    assert page["timeline"]["event_cursor"] == 80
    base = f"/api/sessions/{sid}/events"
    batch = client.get(base, headers=alice, params={"paged": "true", "limit": 3}).json()
    assert len(batch["events"]) == 3 and batch["has_more"] and batch["last_sequence"] == 3
    assert batch["turn_numbers"] == {"turn-0": 1, "turn-1": 2}
    assert len(client.get(base, headers=alice, params={"limit": 5}).json()) == 5
    assert len(client.get(base, headers=alice).json()) == 80
    for path in (f"/api/sessions/{sid}/workspace?history_limit=3", f"/api/sessions/{sid}/conversation-page", base + "?paged=true"):
        assert client.get(path, headers=bob).status_code == 404
        assert client.get(path).status_code == 401
    for params in ({"limit": 0}, {"limit": 101}, {"before": "invalid"}, {"before": base64.urlsafe_b64encode(json.dumps(["x", 2, 10**100, "y"]).encode()).decode()}):
        assert client.get(f"/api/sessions/{sid}/conversation-page", headers=alice, params=params).status_code == 422


def test_evaluation_messages_never_enter_public_history(database, session):
    seed(database, session.id, 1)
    database.add_event(ConversationEvent(session_id=session.id, type="workflow.chat", payload={"turn_id": "hidden", "evaluation_id": "eval", "role": "user", "message": "Hidden evaluation"}))
    page = conversation_page(database, session.id)
    assert len(page["events"]) == 2 and "hidden" not in page["turn_numbers"]


def test_page_and_turn_query_plans_use_indexes(database, session):
    with database._connect() as db:
        plan = db.execute("EXPLAIN QUERY PLAN SELECT * FROM conversation_entries WHERE session_id=? ORDER BY created_at DESC,lane DESC,ordinal DESC,id DESC LIMIT 30", (session.id,)).fetchall()
        assert "conversation_entry_page" in str([tuple(row) for row in plan])
        plan = db.execute("EXPLAIN QUERY PLAN SELECT * FROM events WHERE session_id=? AND json_extract(payload,'$.turn_id')=? ORDER BY sequence", (session.id, "turn")).fetchall()
        assert "events_turn" in str([tuple(row) for row in plan])


def test_manual_analyses_share_history_pages_and_retain_answer_facts(library):
    client, runtime, alice, bob, sessions, _ = library
    sid = sessions[0]
    seed(runtime.database, sid, 2)
    for i in range(10):
        runtime.analytics._save({"id": f"manual-{i}", "session_id": sid, "revision": 1,
            "created_at": f"2026-02-01T00:00:{i:02d}+00:00", "status": "completed",
            "planning_turn_id": None, "input_files": {}, "input_provenance": {"huge": "x" * 100000},
            "validation": {"plan": {"steps": []}, "order": [], "inputs": {"large": list(range(1000))}}, "steps": {}})
    runtime.database.add_event(ConversationEvent(session_id=sid, type="workflow.answer",
        payload={"workflow_id": "manual-9", "revision": 1, "turn_id": None, "facts": [{"statement": "Exact saved fact"}]}))
    base = f"/api/sessions/{sid}"
    first = client.get(base + "/conversation-page?limit=3", headers=alice).json()
    assert first["manual_workflow_ids"] == ["manual-7", "manual-8", "manual-9"]
    assert first["events"][0]["payload"]["facts"][0]["statement"] == "Exact saved fact"
    assert not first["messages"] and first["has_more"]
    manual, events, page = set(), set(), first
    while True:
        manual.update(page["manual_workflow_ids"])
        events.update(row["sequence"] for row in page["events"])
        if not page["has_more"]:
            break
        page = client.get(base + "/conversation-page", headers=alice, params={"limit": 3, "before": page["next_cursor"]}).json()
    assert manual == {f"manual-{i}" for i in range(10)} and events == set(range(1, 6))
    response = client.get(base + "/workflows?summary=true", headers=alice)
    assert len(response.content) < 5000
    assert len(response.json()) == 10 and all("input_provenance" not in record and "inputs" not in record["validation"] for record in response.json())
    assert client.get("/api/workflows/manual-9", headers=alice).json()["input_provenance"]["huge"] == "x" * 100000
    assert client.get(base + "/workflows?summary=true", headers=bob).status_code == 404


def test_workflow_summary_backfill_updates_and_deletion(library):
    from graphmine_agent.workflow_index import initialize

    client, runtime, alice, _, sessions, _ = library
    record = {"id": "summary", "session_id": sessions[0], "revision": 1, "status": "completed",
              "created_at": "2026-01-01", "validation": {"inputs": {"secret": [1, 2]}}}
    runtime.analytics._save(record)
    with closing(sqlite3.connect(runtime.analytics.path)) as db, db:
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'workflow_summary_%'").fetchall():
            db.execute('DROP TRIGGER "' + row[0] + '"')
        db.execute("DROP TABLE workflow_summaries")
        initialize(db)
    path = f"/api/sessions/{sessions[0]}/workflows?summary=true"
    assert client.get(path, headers=alice).json()[0]["validation"] == {}
    runtime.analytics._save({**record, "revision": 2})
    assert client.get(path, headers=alice).json()[0]["revision"] == 2
    with closing(sqlite3.connect(runtime.analytics.path)) as db, db:
        db.execute("DELETE FROM workflows WHERE id='summary'")
    assert client.get(path, headers=alice).json() == []


def test_warm_page_query_work_does_not_grow_with_complete_conversation(database, session, monkeypatch):
    seed(database, session.id, 20)
    conversation_page(database, session.id)
    connect, operations = database._connect, [0]
    def tick():
        operations[0] += 100
        return 0
    @contextmanager
    def measured():
        with connect() as db:
            db.set_progress_handler(tick, 100)
            yield db
    monkeypatch.setattr(database, "_connect", measured)
    conversation_page(database, session.id)
    small = operations[0]
    seed(database, session.id, 2000)
    operations[0] = 0
    page = conversation_page(database, session.id)
    assert len(page["events"]) == 30
    assert operations[0] <= small * 3 + 500  # Index depth may grow; a full-log scan cannot.
