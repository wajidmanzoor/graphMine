from dataclasses import replace
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from graphmine_agent.activity_visibility import visible_event
from graphmine_agent.api import create_app
from graphmine_agent.identity import identity_scope
from graphmine_agent.models import ConversationEvent
from test_accounts import PASSWORD, login


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("as_dict", [False, True])
def test_working_notes_are_admin_only_without_mutating_saved_event(admin, as_dict):
    event = ConversationEvent(session_id="session", type="workflow.reasoning", payload={"turn_id": "t", "text": "private notes", "stage": "route"})
    original = event.model_dump() if as_dict else event
    with identity_scope(SimpleNamespace(is_admin=admin)):
        shown = visible_event(original)
    payload = shown["payload"] if as_dict else shown.payload
    assert ("text" in payload) is admin
    assert event.payload["text"] == "private notes"
    assert payload["turn_id"] == "t"


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("as_dict", [False, True])
def test_saved_chat_mode_is_expert_without_mutating_history(admin, as_dict):
    event = ConversationEvent(session_id="session", type="workflow.chat",
        payload={"turn_id": "t", "role": "user", "message": "Rank people", "mode": "interactive"})
    original = event.model_dump() if as_dict else event
    with identity_scope(SimpleNamespace(is_admin=admin)):
        shown = visible_event(original)
    assert (shown["payload"] if as_dict else shown.payload) == {**event.payload, "mode": "expert"}
    assert (original["payload"] if as_dict else original.payload)["mode"] == "interactive"


@pytest.mark.parametrize("admin", [False, True])
def test_api_event_pages_and_websocket_obey_note_visibility(settings, admin):
    configured = replace(settings, accounts_enabled=True, account_cookie_secure=False)
    with TestClient(create_app(configured)) as client:
        runtime = client.app.state.runtime
        runtime.accounts.create_user("alice", PASSWORD, admin=admin)
        headers = login(client)
        session = client.post("/api/sessions", headers=headers, json={"domain_id": "general"}).json()["id"]
        for kind, payload in [("workflow.chat", {"turn_id": "t", "role": "user", "message": "Rank people"}),
                              ("workflow.reasoning", {"turn_id": "t", "stage": "route", "call_id": "c", "text": "private notes"})]:
            runtime.database.add_event(ConversationEvent(session_id=session, type=kind, payload=payload))
        for path in ["events", "events?paged=true", "workspace?history_limit=30", "conversation-page"]:
            response = client.get(f"/api/sessions/{session}/{path}", headers=headers)
            assert response.status_code == 200, response.text
            assert ("private notes" in response.text) is admin
        assert client.get(f"/api/sessions/{session}/reasoning", headers=headers).status_code == (200 if admin else 403)
        with client.websocket_connect(f"/api/sessions/{session}/events/ws", headers=headers) as socket:
            socket.receive_json()
            event = socket.receive_json()
            assert ("text" in event["payload"]) is admin
