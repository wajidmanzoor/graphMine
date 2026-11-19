"""Keep private model notes out of ordinary conversation responses."""

from .identity import current_principal
from .analytics_modes import saved_mode


def can_read_notes():
    principal = current_principal.get()
    return bool(principal and principal.is_admin)


def visible_event(event):
    kind = event.get("type") if isinstance(event, dict) else event.type
    payload = event["payload"] if isinstance(event, dict) else event.payload
    public = saved_mode(payload) if kind == "workflow.chat" else payload
    if kind == "workflow.chat" and isinstance(public.get("pending_question"), dict):
        pending = saved_mode(public["pending_question"])
        if pending is not public["pending_question"]:
            public = {**public, "pending_question": pending}
    if not can_read_notes() and kind in {"workflow.reasoning", "workflow.reasoning.delta"}:
        public = {key: value for key, value in public.items() if key != "text"}
    if public is payload:
        return event
    return {**event, "payload": public} if isinstance(event, dict) else event.model_copy(update={"payload": public})


def visible_page(page):
    return {**page, "events": [visible_event(event) for event in page["events"]]}
