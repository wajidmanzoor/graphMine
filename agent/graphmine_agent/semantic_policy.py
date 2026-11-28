"""Current admin policy and process-shared admission for disposable workers."""

from contextlib import contextmanager
import fcntl
import time

from . import admin_settings
from .database_job_context import checkpoint
from .errors import AnalyticsError
from .identity import AccountError, current_principal
from .semantic_providers import catalog
from .semantic_validation import validate_semantic
from .semantic_worker import check_request

MAX_SLOTS = 4


def allowed(settings):
    principal = current_principal.get()
    return (not settings.accounts_enabled or principal is not None and
            (principal.is_admin or settings.semantic_access == "all" or
             settings.semantic_access == "selected" and principal.user_id in settings.semantic_accounts))


def execution_policy(runtime, body):
    settings = admin_settings.load(runtime.settings, runtime.database)
    aliases = {item["alias"] for item in catalog(runtime)["aliases"]} | {"mock:echo"}
    if body["model"] not in aliases - {"mock:echo"}:
        raise AnalyticsError("Choose a configured semantic model alias.", "semantic_alias")
    steps = validate_semantic(body["statement"], aliases=aliases)
    if steps:
        if not allowed(settings):
            raise AccountError("This account cannot run semantic model steps.", "semantic_access", 403)
        if settings.semantic_mode == "disabled":
            raise AnalyticsError("Semantic model steps are disabled by the administrator.", "semantic_disabled", 503)
        if body["model"] != "mock" and settings.semantic_mode != "live":
            raise AnalyticsError("Live model steps are disabled by the administrator.", "semantic_live_disabled", 503)
    check_request(body, allowed_aliases=aliases)
    if body.get("reuse_answers") and not settings.semantic_cache_enabled:
        raise AnalyticsError("Saved-answer reuse is disabled by the administrator.", "semantic_cache_disabled", 503)
    return {"call_limit": min(body.get("call_limit") or settings.semantic_default_call_limit, settings.semantic_max_calls),
            "batch_size": min(body.get("batch_size") or settings.semantic_batch_size, settings.semantic_batch_size),
            "timeout_seconds": min(body.get("timeout_seconds") or settings.semantic_timeout_seconds, settings.semantic_timeout_seconds),
            "max_concurrent_requests": settings.semantic_max_concurrent_requests,
            "queue_seconds": settings.model_queue_seconds, "mode": settings.semantic_mode,
            "cache_enabled": bool(steps) and settings.semantic_cache_enabled,
            "cache_max_age_seconds": settings.semantic_cache_max_age_days * 86400,
            "thinking": "off", "strict_json": True, "temperature": 0}


@contextmanager
def slot(runtime, body):
    """Kernel locks coordinate jobs/admin tests across processes and release on exit.

    Lock the gate while checking every slot, so lowering the configured limit
    admits no new worker until the total falls below the new ceiling.
    """
    directory = runtime.settings.data_root / "semantic-slots"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    started, held = time.monotonic(), None
    try:
        while held is None:
            checkpoint("waiting_for_semantic_slot")
            policy = execution_policy(runtime, body)
            free = []
            with (directory / "gate.lock").open("a+b") as gate:
                fcntl.flock(gate, fcntl.LOCK_EX)
                try:
                    for number in range(MAX_SLOTS):
                        stream = (directory / f"{number}.lock").open("a+b")
                        try:
                            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            free.append(stream)
                        except BlockingIOError:
                            stream.close()
                    if MAX_SLOTS - len(free) < policy["max_concurrent_requests"]:
                        held = free.pop(0)
                finally:
                    for stream in free:
                        stream.close()
            if held is None:
                if time.monotonic() - started >= policy["queue_seconds"]:
                    raise AnalyticsError("Semantic workers are busy. Retry after current work finishes.", "semantic_busy", 429)
                time.sleep(0.1)
        yield policy
    finally:
        if held is not None:
            held.close()
