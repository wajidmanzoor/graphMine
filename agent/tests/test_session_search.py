"""Conversation discovery covers the full authorized history before pagination."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from graphmine_agent.api import create_app
from graphmine_agent.identity import Principal, identity_scope
from graphmine_agent.models import SessionRecord
from test_accounts import PASSWORD, account_settings, login


def test_search_finds_older_conversations_and_treats_titles_literally(database):
    old = database.create_session(SessionRecord(title="Straße: 100%_funded", archived=True))
    for index in range(105):
        database.create_session(SessionRecord(title=f"Recent conversation {index}"))
    database.create_session(SessionRecord(title=None))
    assert old.id not in {row.id for row in database.list_sessions()}
    for query in ("STRASSE", "100%_", "  funded  "):
        assert [row.id for row in database.list_sessions(q=query)] == [old.id]
    assert database.list_sessions(q="Straße", include_archived=False) == []
    assert database.list_sessions(q="' OR 1=1 --") == []


def test_history_can_hide_untitled_conversations_nobody_used(database):
    from graphmine_agent.models import ConversationEvent

    unused = database.create_session(SessionRecord(title=None))
    named = database.create_session(SessionRecord(title="Office study"))
    used = database.create_session(SessionRecord(title=None))
    database.add_event(ConversationEvent(
        session_id=used.id, type="workflow.chat",
        payload={"turn_id": "t1", "role": "user", "message": "Who connects the teams?"},
    ))
    assert {row.id for row in database.list_sessions(hide_empty=True)} == {named.id, used.id}
    assert unused.id in {row.id for row in database.list_sessions()}


def test_pagination_orders_equal_timestamps_without_duplicates(database):
    timestamp = datetime(2026, 10, 21, tzinfo=UTC)
    for index in range(107):
        database.create_session(SessionRecord(id=f"session-{index:03}", updated_at=timestamp))
    rows = [row.id for offset in (0, 40, 80) for row in database.list_sessions(40, offset=offset)]
    assert rows == [f"session-{index:03}" for index in range(106, -1, -1)]
    assert database.list_sessions(40, offset=107) == []


def test_search_api_filters_owners_archives_and_validates_bounds(account_settings):
    with TestClient(create_app(account_settings)) as client:
        runtime = client.app.state.runtime
        saved = {}
        for username in ("alice", "bob"):
            user = runtime.accounts.create_user(username, PASSWORD)
            with identity_scope(Principal(user["id"], username, runtime.accounts)):
                saved[username] = [runtime.database.create_session(SessionRecord(
                    title="Research archive" if archived else "Research current", archived=archived,
                )).id for archived in (True, False)]
        headers = login(client)
        rows = client.get("/api/sessions", params={"q": "research", "limit": 1}, headers=headers).json()
        assert [row["id"] for row in rows] == [saved["alice"][1]]
        rows = client.get("/api/sessions", params={"q": "research", "limit": 1, "offset": 1}, headers=headers).json()
        assert [row["id"] for row in rows] == [saved["alice"][0]]
        rows = client.get("/api/sessions", params={"q": "research", "include_archived": False}, headers=headers).json()
        assert [row["id"] for row in rows] == [saved["alice"][1]]
        for params in ({"offset": -1}, {"limit": 0}, {"limit": 501}, {"q": "a" * 201}):
            assert client.get("/api/sessions", params=params, headers=headers).status_code == 422
        assert client.get("/api/sessions?q=research").status_code == 401
