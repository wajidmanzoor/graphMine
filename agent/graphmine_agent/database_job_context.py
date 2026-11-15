"""Cooperative transaction boundaries for durable database work."""

from contextvars import ContextVar

current_database_job = ContextVar("graphmine_database_job", default=None)


def checkpoint(stage=None, completed=None, total=None):
    control = current_database_job.get()
    if control:
        control.checkpoint(stage, completed, total)


def begin_commit(stage="committing"):
    """Atomically close cancellation before a transaction commit or publication."""
    control = current_database_job.get()
    if control:
        control.seal(stage)
