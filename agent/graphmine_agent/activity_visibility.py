"""Keep private model notes out of ordinary conversation responses."""

from .identity import current_principal


def can_read_notes():
    principal = current_principal.get()
    return bool(principal and principal.is_admin)


def visible_event(event):
    kind = event.get("type") if isinstance(event, dict) else event.type
    if can_read_notes() or kind not in {"workflow.reasoning", "workflow.reasoning.delta"}:
        return event
    payload = event["payload"] if isinstance(event, dict) else event.payload
    public = {key: value for key, value in payload.items() if key != "text"}
    return {**event, "payload": public} if isinstance(event, dict) else event.model_copy(update={"payload": public})


def visible_page(page):
    return {**page, "events": [visible_event(event) for event in page["events"]]}
