"""Semantic engine administration; unsupported live/cache contracts fail closed."""

from importlib import metadata
import json

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from . import admin_settings, semantic_providers
from .errors import AnalyticsError
from .semantic_engine import engine_lock
from .semantic_policy import slot
from .semantic_worker import run_worker


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict
    expected: dict
    confirm: bool = Field(strict=True)


class DeleteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    confirm: bool = Field(strict=True)


async def validated(request, model):
    raw = await request.body()
    if len(raw) > 32 * 1024:
        raise AnalyticsError("Semantic configuration exceeds its request budget.", "resource_limit")
    try:
        return model.model_validate(json.loads(raw))
    except (ValueError, TypeError, ValidationError):
        # Includes invalid JSON/types, URLs and keys. Never return the request,
        # validation input/context or provider credentials in an error.
        raise AnalyticsError("Invalid semantic configuration. Check the fields and their limits; use a base URL without credentials or query parameters.", "semantic_settings", 422) from None


def snapshot(runtime):
    settings = admin_settings.load(runtime.settings, runtime.database)
    lock = engine_lock()
    try:
        installed = metadata.version(lock["distribution"])
    except metadata.PackageNotFoundError:
        installed = None
    with runtime.database._connect() as db:
        users = [dict(row) for row in db.execute("SELECT id,username,role,disabled FROM accounts ORDER BY username")]
    warning = settings.semantic_max_concurrent_requests >= runtime.settings.llm_max_num_seqs
    return {
        **semantic_providers.catalog(runtime), "values": admin_settings.values(settings, admin_settings.SEMANTIC_KEYS),
        "accounts": users, "engine": {"commit": lock["commit"], "installed_version": installed,
            "expected_version": lock["version"], "installed": installed == lock["version"]},
        "requirements": {"thinking": "off", "strict_json": True, "temperature": 0},
        "capabilities": {"live": False, "cache": False, "judgments": False, "estimates": False,
                         "blockers": lock["live_blockers"] + lock["integration_blockers"]},
        "cache": {"retained_answers": 0, "clear_available": False, "reason": "An independent answer store is not available in this Tentō revision."},
        "concurrency": {"configured_vllm_limit": runtime.settings.llm_max_num_seqs, "warning": warning,
            "message": "Semantic concurrency meets or exceeds the configured vLLM request limit. Leave capacity for planner work." if warning else None,
            "policy": "One dispatch thread per worker; a shared lock limits all semantic jobs and mock tests. Mocks send no provider requests. Live execution remains blocked until shared planner admission is integrated and verified."},
    }


def save_settings(runtime, body):
    if not body.confirm:
        raise ValueError("Confirm the semantic settings.")
    admin_settings.save(runtime, body.values, keys=admin_settings.SEMANTIC_KEYS, target="semantic", expected=body.expected)
    return snapshot(runtime)


def mock_test(runtime):
    body = {"statement": "MATCH(n:Vertex) RETURN llm('mock','Echo {{n.text}} {answer STRING}') AS answer",
            "model": "mock", "call_limit": 1, "projection": "elements", "reuse_answers": False}
    graph = {"graph": {"id": "admin-semantic-test", "directed": True, "allows_self_loops": False, "allows_parallel_edges": False}, "vertices": [{"id": "test", "attributes": {"text": "alpha"}}], "edges": []}
    with slot(runtime, body) as policy:
        policy = {**policy, "timeout_seconds": min(30, policy["timeout_seconds"])}
        result = run_worker(graph, body, execution=policy, timeout=policy["timeout_seconds"])
    if result["row_count"] != 1 or result["usage"].get("calls") != 1 or result["effective_settings"]["http_requests"] != 0:
        raise AnalyticsError("The semantic mock did not pass its expected contract.", "semantic_mock_failed", 502)
    answer = result["value"]["rows"][0]["answer"]
    if json.loads(answer) != ["alpha"]:
        raise AnalyticsError("The semantic mock returned an unexpected answer.", "semantic_mock_failed", 502)
    report = {"passed": True, "simulated": True, "http_requests": 0, "usage": result["usage"], "engine": result["engine"],
              "settings": result["effective_settings"]}
    with runtime.database._connect() as db:
        runtime.accounts._audit(db, "semantic.mock.tested", "semantic", before={}, after=report)
    return report


def register(router):
    from .database_jobs import private_response

    async def perform(request, function, *args):
        return private_response(await run_in_threadpool(function, request.app.state.runtime, *args))

    @router.get("/semantic")
    async def status(request: Request):
        return await perform(request, snapshot)

    @router.patch("/semantic/settings")
    async def settings(request: Request):
        return await perform(request, save_settings, await validated(request, SettingsInput))

    @router.post("/semantic/providers", status_code=201)
    async def create_provider(request: Request):
        result = await run_in_threadpool(semantic_providers.save_provider, request.app.state.runtime,
                                         await validated(request, semantic_providers.ProviderInput))
        response = private_response(result)
        response.status_code = 201
        return response

    @router.put("/semantic/providers/{identifier}")
    async def update_provider(identifier: str, request: Request):
        return await perform(request, semantic_providers.save_provider, await validated(request, semantic_providers.ProviderInput), identifier)

    @router.delete("/semantic/providers/{identifier}")
    async def remove_provider(identifier: str, request: Request):
        body = await validated(request, DeleteInput)
        if not body.confirm:
            raise ValueError("Confirm provider removal.")
        return await perform(request, semantic_providers.delete_provider, identifier, body.expected_revision)

    @router.post("/semantic/providers/{identifier}/test")
    async def test_connection(identifier: str, request: Request):
        runtime = request.app.state.runtime
        async with runtime.upload_slots:
            return await perform(request, semantic_providers.connection_test, identifier)

    @router.put("/semantic/aliases")
    async def alias(request: Request):
        return await perform(request, semantic_providers.save_alias, await validated(request, semantic_providers.AliasInput))

    @router.delete("/semantic/aliases/{identifier}")
    async def remove_alias(identifier: str, request: Request):
        body = await validated(request, DeleteInput)
        if not body.confirm:
            raise ValueError("Confirm alias removal.")
        return await perform(request, semantic_providers.delete_alias, identifier, body.expected_revision)

    @router.post("/semantic/test-mock")
    async def test_mock(request: Request):
        async with request.app.state.runtime.upload_slots:
            return await perform(request, mock_test)

    @router.post("/semantic/cache/clear")
    async def clear_cache(request: Request):
        raise AnalyticsError("No independent answer store exists in this Tentō revision; saved graph provenance is unchanged.", "semantic_cache_unsupported", 503)
