"""Cooperative transaction boundaries for durable database work."""

from contextvars import ContextVar

current_database_job = ContextVar("graphmine_database_job", default=None)


def checkpoint(stage=None, completed=None, total=None, *, message=None):
    control = current_database_job.get()
    if control:
        if message is None:
            control.checkpoint(stage, completed, total)
        else:
            control.checkpoint(stage, completed, total, message=message)


def begin_commit(stage="committing"):
    """Atomically close cancellation before a transaction commit or publication."""
    control = current_database_job.get()
    if control:
        control.seal(stage)
