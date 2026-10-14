"""Request identity, also explicitly propagated into durable background jobs."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    accounts: Any
    session_hash: str | None = None
    is_admin: bool = False


current_principal: ContextVar[Principal | None] = ContextVar(
    "graphmine_principal", default=None
)


@contextmanager
def identity_scope(principal):
    token = current_principal.set(principal)
    try:
        yield
    finally:
        current_principal.reset(token)


class AccountError(Exception):
    def __init__(
        self, message, code="account_error", status=429, retry_after=0, details=None
    ):
        super().__init__(message)
        self.code, self.status = code, status
        self.retry_after = max(0, int(retry_after))
        self.details = details
