"""Owner-scoped database progress on the existing event bus."""

from .identity import current_principal


def topic():
    principal = current_principal.get()
    return "database:" + (principal.user_id if principal else "local")


def publish(runtime, payload):
    runtime.events.notify(topic(), "database.power", payload)
