from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import json
import logging
import shutil
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.middleware.gzip import GZipMiddleware
from starlette.concurrency import run_in_threadpool

from . import __version__
from .account_api import AccountMiddleware, register_account_routes
from .accounts import Accounts
from .agent_service import AgentService
from .analytics import (
    AnalyticsError,
    AnalyticsService,
)
from .analytics_examples import register_example_routes
from .analytics_exports import register_export_routes
from .database_pools import DatabasePoolMiddleware, DatabasePools
from .analytics_projection import register_projection_routes
from .catalog import Catalog
from .capture import TrainingCapture, deployment_snapshot
from .config import Settings
from .connectors import register_connector_routes
from .database import Database, RecordNotFound
from .database_enrichment import register_database_enrichment_routes
from .database_queries import register_database_query_routes
from .data_sources import register_source_routes
from .database_sync import register_database_sync_routes
from .database_jobs import DatabaseJobs, register_database_job_routes
from .exploration import register_exploration_routes
from .export_streams import prepare_download
from .legacy_exports import answer_report, feedback_export, history_archive as prepare_history_archive
from .datasets import register_dataset_routes
from .workspace_recent import register_recent_routes
from .execution import GraphMineRunner
from .graph_store import GraphStore, UploadError
from .history import HistoryStore
from .identity import AccountError, current_principal
from .activity_visibility import can_read_notes, visible_event, visible_page
from .import_preview import register_import_routes
from .jobs import EventBus, JobManager
from .models import (
    ChatRequest,
    ChatResponse,
    ConversationEvent,
    ConversationEventPage,
    DomainProfile,
    ExecutionPlan,
    FeedbackCreate,
    FeedbackRecord,
    FileInfo,
    FileRole,
    InterpretRequest,
    JobRecord,
    JobStatus,
    PlanningOutcome,
    PlanRequest,
    ResultRecord,
    SessionCreate,
    SessionRecord,
    SessionUpdate,
)
from .planning import PlanValidator
from .projects import register_project_routes
from .result_views import register_result_view_routes
from .results import query_path
from .workflow_templates import register_template_routes
from .workflow_api import register_workflow_routes
from .api_errors import register_error_handlers
from .web_assets import WebAssets, WebHeaders
from .llm_power import LLMPowerRegistry, LLMPowerBusy, get_registry


@dataclass(slots=True)
class Runtime:
    settings: Settings
    catalog: Catalog
    database: Database
    graph_store: GraphStore
    validator: PlanValidator
    runner: GraphMineRunner
    events: EventBus
    jobs: JobManager
    agent: AgentService
    upload_slots: asyncio.Semaphore
    analytics: AnalyticsService
    accounts: Accounts
    database_pools: DatabasePools
    llm_power: LLMPowerRegistry
    database_jobs: DatabaseJobs | None = None


_logger = logging.getLogger(__name__)


def _active_jobs(runtime, session_id):
    return runtime.database.list_jobs(
        session_id,
        {JobStatus.queued, JobStatus.running, JobStatus.interpreting},
    )


def remove_session(runtime, session_id):
    """Delete a conversation's records, uploads, results and history."""
    session = runtime.database.get_session(session_id)
    if _active_jobs(runtime, session_id):
        raise AnalyticsError(
            "Cancel the running analysis before deleting this conversation.",
            "state_conflict",
            409,
        )
    runtime.analytics.delete_session(session_id)
    if runtime.database.capture:
        # The capture outlives the conversation; this marks where it ended.
        runtime.database.capture.record(session_id, "session.deleted", session)
    jobs = runtime.database.delete_session(session_id)
    settings = runtime.settings
    for path in (
        settings.data_root / "sessions" / session_id,
        runtime.database.history.session_path(session_id),
        *(settings.workspaces_root / job for job in jobs),
    ):
        shutil.rmtree(path, ignore_errors=True)


async def enforce_retention(runtime, *, interval=6 * 3600):
    """Delete conversations with no activity for the configured number of days.

    Conversations with running work are skipped and tried again next sweep.
    """
    while True:
        cutoff = datetime.now(UTC) - timedelta(days=runtime.settings.retention_days)
        for session_id in runtime.database.inactive_sessions(cutoff):
            try:
                remove_session(runtime, session_id)
            except (AnalyticsError, RecordNotFound):
                continue
        await asyncio.sleep(interval)


async def scheduled_backups(runtime):
    """Online snapshots, each verified before older ones are rotated away."""
    from .backup import online_snapshot, rotate_snapshots, verify_snapshot

    settings = runtime.settings
    settings.backup_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    while True:
        target = settings.backup_directory / (
            "graphmine-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        )
        try:
            await run_in_threadpool(online_snapshot, settings.data_root, target)
            await run_in_threadpool(verify_snapshot, target)
            rotate_snapshots(settings.backup_directory, settings.backup_keep)
            _logger.info("backup written to %s", target)
        except Exception:  # A failed backup must never stop the service.
            _logger.exception("scheduled backup failed")
        await asyncio.sleep(settings.backup_hours * 3600)


async def expire_query_previews(runtime, *, interval=3600):
    from .query_previews import expire_previews

    while True:
        try:
            await run_in_threadpool(expire_previews, runtime.database)
        except Exception:
            _logger.exception("query preview cleanup failed")
        await asyncio.sleep(interval)


async def expire_database_pools(runtime):
    while True:
        await asyncio.sleep(min(60, runtime.settings.database_pool_idle_seconds))
        await run_in_threadpool(runtime.database_pools.reap)


def build_runtime(settings: Settings, *, serving: bool = False) -> Runtime:
    settings.data_root.mkdir(parents=True, exist_ok=True)
    settings.workspaces_root.mkdir(parents=True, exist_ok=True)
    catalog = Catalog(settings)
    database = Database(settings.database_path, HistoryStore(settings.history_root))
    accounts = Accounts(settings, database)
    if settings.capture_enabled:
        database.capture = TrainingCapture(
            settings.capture_root,
            owner_of=database.session_owner,
            deployment=deployment_snapshot(settings),
        )
    graph_store = GraphStore(settings, database)
    validator = PlanValidator(catalog)
    runner = GraphMineRunner(settings, catalog, graph_store, validator)
    events = EventBus(database)
    jobs = JobManager(
        database,
        runner,
        events,
        summary_items=settings.result_summary_items,
        max_pending_jobs=settings.max_pending_jobs,
        accounts=accounts if settings.accounts_enabled and serving else None,
    )
    power = get_registry(settings)
    agent = AgentService(settings, catalog, database, graph_store, validator, jobs, llm_power=power)
    jobs.result_handler = agent.handle_completed_result
    runtime = Runtime(
        settings=settings,
        catalog=catalog,
        database=database,
        graph_store=graph_store,
        validator=validator,
        runner=runner,
        events=events,
        jobs=jobs,
        agent=agent,
        upload_slots=asyncio.Semaphore(settings.max_concurrent_uploads),
        analytics=AnalyticsService(settings, database, graph_store, events, llm_power=power),
        accounts=accounts,
        database_pools=DatabasePools(settings),
        llm_power=power,
    )
    runtime.database_jobs = DatabaseJobs(runtime)
    return runtime


def _runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def _authorization(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_graphmine_token: Annotated[str | None, Header()] = None,
) -> None:
    if request.url.path.startswith("/api/admin/"):
        from .account_api import administrator
        administrator()
        return
    if _runtime(request).settings.accounts_enabled:
        if current_principal.get() is None:
            raise AccountError("Please sign in to continue.", "unauthorized", 401)
        return
    expected = _runtime(request).settings.api_token
    if expected is None:
        return
    supplied = x_graphmine_token
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if supplied is None or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "a valid API token is required"},
        )


def _websocket_credentials(
    websocket: WebSocket, query_token: str | None
) -> tuple[str | None, str | None]:
    """Read browser-safe token auth without putting secrets in the URL."""

    offered = [
        item.strip()
        for item in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if item.strip()
    ]
    supplied = query_token
    bearer = websocket.headers.get("authorization", "")
    if bearer.lower().startswith("bearer "):
        supplied = bearer[7:].strip()
    for protocol in offered:
        if not protocol.startswith("graphmine.token."):
            continue
        encoded = protocol.removeprefix("graphmine.token.")
        try:
            padding = "=" * (-len(encoded) % 4)
            supplied = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            supplied = None
        break
    accepted_protocol = "graphmine" if "graphmine" in offered else None
    return supplied, accepted_protocol


def _compiled_backends(runtime: Runtime, operation_id: str) -> set[str] | None:
    runtime.runner.require_ready()
    return runtime.runner.compiled_backends_for(operation_id)


async def _ingest_upload(store: GraphStore, **kwargs):
    # Python cannot interrupt an in-progress parser thread. Keep its upload
    # handle and capacity slot alive until it finishes, even if the request is
    # cancelled; then propagate cancellation instead of claiming a response.
    worker = asyncio.create_task(run_in_threadpool(store.ingest_stream, **kwargs))
    cancelled = False
    try:
        while True:
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
                if worker.done():
                    return worker.result()
    finally:
        if cancelled:
            raise asyncio.CancelledError


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = build_runtime(configured, serving=True)
        app.state.runtime = runtime
        from .admin_lifecycle import cleanup as recover_admin_cleanup
        await run_in_threadpool(recover_admin_cleanup, runtime)
        retention = backups = previews = pools = None
        try:
            runtime.runner.probe()
            await runtime.jobs.start()
            runtime.analytics.open()
            runtime.database.close_unanswered_planning()
            if configured.llm_enabled and not runtime.llm_power.shared:
                runtime.llm_power.start()
            previews = asyncio.create_task(expire_query_previews(runtime))
            pools = asyncio.create_task(expire_database_pools(runtime))
            retention = (
                asyncio.create_task(enforce_retention(runtime))
                if configured.retention_days
                else None
            )
            backups = (
                asyncio.create_task(scheduled_backups(runtime))
                if configured.backup_directory
                else None
            )
            if configured.accounts_enabled:
                # Both store locks are held and interrupted jobs are now terminal.
                with runtime.database._connect() as db:
                    db.execute("DELETE FROM account_leases WHERE kind != 'model'")
            await runtime.database_jobs.start()
            yield
        finally:
            for task in (retention, backups, previews, pools):
                if task:
                    task.cancel()
            await asyncio.gather(*(task for task in (retention, backups, previews, pools) if task), return_exceptions=True)
            try:
                await runtime.database_jobs.stop()
            finally:
                try:
                    await runtime.analytics.close()
                finally:
                    try:
                        await runtime.jobs.stop()
                    finally:
                        try:
                            await runtime.agent.close()
                        finally:
                            try:
                                await run_in_threadpool(runtime.database_pools.close)
                            finally:
                                if not runtime.llm_power.shared:
                                    await runtime.llm_power.close()

    app = FastAPI(
        title="GraphMine Agent API",
        version=__version__,
        description=(
            "Private-LAN orchestration API for validated GraphMine GPU algorithms, "
            "domain-aware planning, interpretation, and interactive visualizations."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(AccountMiddleware)
    app.add_middleware(DatabasePoolMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-GraphMine-Token",
            "X-GraphMine-Request",
            "Prefer",
            "Idempotency-Key",
        ],
        expose_headers=["Location", "Retry-After"],
    )
    register_account_routes(app)
    from .admin_api import register_admin_routes
    from .admin_telemetry import OperationalMiddleware
    register_admin_routes(app)
    app.add_middleware(OperationalMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)
    app.add_middleware(WebHeaders, allowed_origins=configured.allowed_origins)

    register_error_handlers(app)

    router = APIRouter(prefix="/api", dependencies=[Depends(_authorization)])

    from .account_api import administrator

    @router.get("/admin/llm/power", dependencies=[Depends(administrator)])
    async def llm_power_status(request: Request):
        from .account_api import administrator
        administrator()
        return await _runtime(request).llm_power.for_url().refresh_status()

    @router.post("/admin/llm/power/sleep", dependencies=[Depends(administrator)])
    async def llm_power_sleep(request: Request):
        from .account_api import administrator
        administrator()
        try:
            manager = _runtime(request).llm_power.for_url()
            before = await manager.refresh_status()
            after = await manager.sleep_now()
            with _runtime(request).database._connect() as db:
                _runtime(request).accounts._audit(db, "model.sleep", "model", before=before, after=after)
            return after
        except LLMPowerBusy as error:
            raise AnalyticsError(str(error), "llm_busy", 409) from error

    @router.post("/admin/llm/power/wake", dependencies=[Depends(administrator)])
    async def llm_power_wake(request: Request):
        from .account_api import administrator
        administrator()
        manager = _runtime(request).llm_power.for_url()
        before = await manager.refresh_status()
        after = await manager.wake_now()
        with _runtime(request).database._connect() as db:
            _runtime(request).accounts._audit(db, "model.wake", "model", before=before, after=after)
        return after

    @router.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        runtime = _runtime(request)
        capability = runtime.runner.capabilities
        llm_available = await runtime.agent.model.available()
        worker = runtime.jobs.statistics()
        history = runtime.database.history.statistics()
        analytics = await runtime.analytics.health()
        ready = (
            capability.binary_available
            and not capability.error
            and capability.library_version == __version__
            and llm_available
            and worker["worker_running"]
            and not worker["error"]
            and history["status"] == "ok"
        )
        return {
            "version": __version__,
            "build_id": request.app.state.build_id,
            "deployment": runtime.agent.deployment_info(),
            "status": "ready" if ready else "degraded",
            "llm": {
                "enabled": runtime.settings.llm_enabled,
                "available": llm_available,
                "model": runtime.settings.llm_model,
                "base_url": runtime.settings.llm_base_url,
                "gpu_uuid": runtime.settings.llm_gpu_uuid,
                "power": runtime.llm_power.for_url().status(),
            },
            "graphmine": capability.model_dump(mode="json"),
            "worker": worker,
            "history": history,
            # The default workspace's engine; "status" above keeps describing
            # the classic runner, which the classic page waits for.
            "analytics_status": "ready"
            if analytics["native"]["admitted_operations"] > 0 and llm_available
            else "degraded",
            "analytics": analytics,
        }

    @router.get("/metrics")
    async def metrics(request: Request) -> dict[str, Any]:
        runtime = _runtime(request)
        return {
            "version": __version__,
            "database": runtime.database.statistics(),
            "worker": runtime.jobs.statistics(),
            "history": runtime.database.history.statistics(),
            "capture": (
                runtime.database.capture.statistics()
                if runtime.database.capture
                else {"status": "disabled"}
            ),
            "analytics": runtime.analytics.metrics(
                runtime.database.recent_payloads(
                    "workflow.diagnostics", datetime.now(UTC) - timedelta(days=1)
                )
            ),
        }

    @router.get("/domains", response_model=list[DomainProfile])
    async def domains(request: Request) -> list[DomainProfile]:
        return list(_runtime(request).catalog.domains.values())

    @router.get("/operations")
    async def operations(request: Request) -> list[dict[str, Any]]:
        runtime = _runtime(request)
        return [
            {
                "id": operation_id,
                "problem_id": runtime.catalog.instructions[operation_id]["problem_id"],
                "name": runtime.catalog.problem(
                    runtime.catalog.instructions[operation_id]["problem_id"]
                )["spec"]["name"],
                "backends": runtime.catalog.manifest_operations[operation_id][
                    "backends"
                ],
                "default_backend": runtime.catalog.instructions[operation_id][
                    "default_backend"
                ],
            }
            for operation_id in sorted(runtime.catalog.instructions)
        ]

    @router.get("/capabilities")
    async def capabilities(request: Request, refresh: bool = False) -> dict[str, Any]:
        runtime = _runtime(request)
        report = runtime.runner.probe() if refresh else runtime.runner.capabilities
        return report.model_dump(mode="json")

    @router.post("/sessions", response_model=SessionRecord, status_code=201)
    async def create_session(body: SessionCreate, request: Request) -> SessionRecord:
        runtime = _runtime(request)
        runtime.catalog.domain(body.domain_id)
        return runtime.database.create_session(
            SessionRecord(
                title=body.title,
                domain_id=body.domain_id,
                participant_id=body.participant_id,
            )
        )

    @router.get("/sessions", response_model=list[SessionRecord])
    def list_sessions(
        request: Request, limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0), q: str = Query("", max_length=200),
        include_archived: bool = True, hide_empty: bool = False,
    ) -> list[SessionRecord]:
        return _runtime(request).database.list_sessions(
            limit, offset=offset, q=q, include_archived=include_archived,
            hide_empty=hide_empty,
        )

    @router.patch("/sessions/{session_id}", response_model=SessionRecord)
    async def update_session(
        session_id: str, body: SessionUpdate, request: Request
    ) -> SessionRecord:
        return _runtime(request).database.update_session(
            session_id, body.model_dump(exclude_unset=True)
        )

    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str, request: Request) -> Response:
        """Delete a conversation with its uploads, results and history."""
        remove_session(_runtime(request), session_id)
        return Response(status_code=204)

    @router.delete("/files/{file_id}", status_code=204)
    async def delete_file(file_id: str, request: Request) -> Response:
        runtime = _runtime(request)
        record = runtime.database.get_file(file_id)
        if file_id in runtime.analytics.active_inputs(record.session_id) or (
            _active_jobs(runtime, record.session_id)
        ):
            raise AnalyticsError(
                "This file is used by an analysis that is still running.",
                "state_conflict",
                409,
            )
        runtime.database.delete_file(file_id)
        shutil.rmtree(
            runtime.settings.data_root
            / "sessions"
            / record.session_id
            / "files"
            / file_id,
            ignore_errors=True,
        )
        return Response(status_code=204)

    @router.get("/sessions/{session_id}", response_model=SessionRecord)
    async def get_session(session_id: str, request: Request) -> SessionRecord:
        return _runtime(request).database.get_session(session_id)

    @router.get("/sessions/{session_id}/workspace")
    def session_workspace(session_id: str, request: Request, history_limit: int | None = Query(None, ge=1, le=100)):
        runtime = _runtime(request)
        database = runtime.database
        session = database.get_session(session_id)
        jobs = database.list_jobs(session_id, limit=history_limit + 1 if history_limit is not None else None)
        timeline = None
        if history_limit is not None:
            from .conversation_timeline import conversation_page

            timeline = conversation_page(database, session_id, limit=history_limit, analytics=runtime.analytics)
        return {
            "session": session,
            "messages": timeline["messages"] if timeline else database.conversation_transcript(session_id),
            "files": [
                FileInfo.from_stored(item) for item in database.list_files(session_id)
            ],
            "jobs": jobs[-history_limit:] if history_limit else jobs,
            "jobs_truncated": bool(history_limit and len(jobs) > history_limit),
            "events": [visible_event(event) for event in (timeline["events"] if timeline else database.events(session_id))],
            "timeline": {key: value for key, value in timeline.items() if key not in {"messages", "events"}} if timeline else None,
            "feedback_count": database.feedback_count(session_id),
            "deployment": runtime.agent.deployment_info(),
        }

    @router.get("/sessions/{session_id}/conversation-page")
    def conversation_page_route(session_id: str, request: Request, before: str | None = Query(None, max_length=2048),
                                limit: int = Query(30, ge=1, le=100)):
        from .conversation_timeline import conversation_page

        runtime = _runtime(request)
        return visible_page(conversation_page(runtime.database, session_id, before=before, limit=limit, analytics=runtime.analytics))

    @router.get("/sessions/{session_id}/feedback/export")
    async def export_feedback(session_id: str, request: Request):
        runtime = _runtime(request)
        return await prepare_download(runtime.analytics, feedback_export, runtime, session_id,
                                      filename=f"{session_id}-feedback.jsonl", media_type="application/x-ndjson")

    @router.get("/sessions/{session_id}/reasoning")
    async def model_reasoning(session_id: str, request: Request):
        if not can_read_notes():
            raise AccountError("Model working notes are available to administrators only.", "forbidden", 403)
        database = _runtime(request).database
        database.get_session(session_id)
        return database.history.model_reasoning(session_id)

    @router.post(
        "/sessions/{session_id}/feedback",
        response_model=FeedbackRecord,
        status_code=201,
    )
    async def add_feedback(
        session_id: str, body: FeedbackCreate, request: Request
    ) -> FeedbackRecord:
        return _runtime(request).database.add_feedback(session_id, body)

    @router.get("/sessions/{session_id}/feedback", response_model=list[FeedbackRecord])
    async def feedback(session_id: str, request: Request) -> list[FeedbackRecord]:
        return _runtime(request).database.feedback(session_id)

    @router.get("/sessions/{session_id}/history")
    async def history(session_id: str, request: Request) -> dict[str, Any]:
        database = _runtime(request).database
        database.get_session(session_id)
        return database.history.manifest(session_id)

    @router.get("/sessions/{session_id}/history/archive")
    async def history_archive(session_id: str, request: Request) -> StreamingResponse:
        runtime = _runtime(request)
        async with runtime.analytics.edit_lock:
            return await prepare_download(runtime.analytics, prepare_history_archive, runtime, session_id,
                                          filename=f"{session_id}.zip", media_type="application/zip")

    @router.post(
        "/sessions/{session_id}/files", response_model=FileInfo, status_code=201
    )
    async def upload_file(
        session_id: str,
        request: Request,
        file: Annotated[UploadFile, File()],
        role: Annotated[FileRole, Form()] = FileRole.graph,
        directed: Annotated[bool, Form()] = False,
        source_column: Annotated[str | None, Form()] = None,
        target_column: Annotated[str | None, Form()] = None,
        timestamp_unit: Annotated[str | None, Form()] = None,
    ) -> FileInfo:
        runtime = _runtime(request)
        runtime.database.get_session(session_id)
        if file.size is not None and file.size > runtime.settings.max_upload_bytes:
            raise UploadError(
                f"upload exceeds {runtime.settings.max_upload_bytes} byte limit"
            )
        if runtime.upload_slots.locked():
            raise HTTPException(
                status_code=429,
                detail="Uploads are busy. Please retry shortly.",
                headers={"Retry-After": "2"},
            )
        async with runtime.upload_slots:
            record = await _ingest_upload(
                runtime.graph_store,
                session_id=session_id,
                role=role,
                filename=file.filename or "upload",
                stream=file.file,
                media_type=file.content_type,
                directed=directed,
                source_column=source_column,
                target_column=target_column,
                timestamp_unit=timestamp_unit,
            )
        return FileInfo.from_stored(record)

    @router.get("/sessions/{session_id}/files", response_model=list[FileInfo])
    async def list_files(session_id: str, request: Request) -> list[FileInfo]:
        return [
            FileInfo.from_stored(item)
            for item in _runtime(request).database.list_files(session_id)
        ]

    @router.get("/files/{file_id}/graph-preview")
    async def graph_preview(
        file_id: str,
        request: Request,
        vertex_limit: int = Query(500, ge=1, le=2_000),
        edge_limit: int = Query(2_000, ge=1, le=10_000),
    ) -> dict[str, Any]:
        # Parsing a large upload must not stall every other request.
        return await run_in_threadpool(
            _runtime(request).graph_store.graph_preview,
            file_id,
            vertex_limit=vertex_limit,
            edge_limit=edge_limit,
        )

    @router.post("/sessions/{session_id}/plan", response_model=PlanningOutcome)
    async def create_plan(
        session_id: str, body: PlanRequest, request: Request
    ) -> PlanningOutcome:
        return await _runtime(request).agent.plan(session_id, body)

    @router.post("/jobs", response_model=JobRecord, status_code=202)
    async def create_job(body: ExecutionPlan, request: Request) -> JobRecord:
        runtime = _runtime(request)
        runtime.database.get_session(body.session_id)
        normalized = runtime.validator.validate(
            body,
            compiled_backends=_compiled_backends(runtime, body.operation_id),
            for_execution=True,
        )
        if runtime.database.get_file(normalized.graph_id).role != FileRole.graph:
            raise UploadError("graph_id must identify a main graph file")
        runtime.graph_store.execution_path(normalized.graph_id, normalized.session_id)
        return await runtime.jobs.enqueue(normalized)

    @router.get("/jobs", response_model=list[JobRecord])
    async def list_jobs(
        request: Request,
        session_id: str | None = None,
        status_filter: Annotated[list[JobStatus] | None, Query(alias="status")] = None,
    ) -> list[JobRecord]:
        runtime = _runtime(request)
        if session_id:
            runtime.database.get_session(session_id)
        return runtime.database.list_jobs(
            session_id=session_id,
            statuses=set(status_filter) if status_filter else None,
        )

    @router.get("/jobs/{job_id}", response_model=JobRecord)
    async def get_job(job_id: str, request: Request) -> JobRecord:
        return _runtime(request).database.get_job(job_id)

    @router.delete("/jobs/{job_id}", response_model=JobRecord)
    async def cancel_job(job_id: str, request: Request) -> JobRecord:
        return await _runtime(request).jobs.cancel(job_id)

    @router.get("/results/{result_id}", response_model=ResultRecord)
    async def get_result(result_id: str, request: Request) -> ResultRecord:
        return _runtime(request).database.get_result(result_id)

    @router.get("/results/{result_id}/query")
    async def inspect_result(
        result_id: str,
        request: Request,
        path: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=10_000),
    ) -> Any:
        result = _runtime(request).database.get_result(result_id)
        return query_path(
            {**result.payload, "answer": result.answer},
            path,
            offset=offset,
            limit=limit,
        )

    @router.get("/results/{result_id}/report", response_class=HTMLResponse)
    async def download_answer(result_id: str, request: Request) -> StreamingResponse:
        runtime = _runtime(request)
        return await prepare_download(runtime.analytics, answer_report, runtime, result_id,
                                      filename=f"{result_id}.html", media_type="text/html")

    @router.post("/results/{result_id}/interpret", response_model=ResultRecord)
    async def interpret_result(
        result_id: str, body: InterpretRequest, request: Request
    ) -> ResultRecord:
        return await _runtime(request).agent.interpret(
            result_id, user_message=body.message
        )

    @router.post("/sessions/{session_id}/chat", response_model=ChatResponse)
    async def chat(
        session_id: str, body: ChatRequest, request: Request
    ) -> ChatResponse:
        return await _runtime(request).agent.chat(session_id, body)

    @router.get("/sessions/{session_id}/events", response_model=list[ConversationEvent] | ConversationEventPage)
    def events(
        session_id: str, request: Request, after: int = Query(0, ge=0, le=9223372036854775807), limit: int | None = Query(None, ge=1, le=1000), paged: bool = False
    ) -> list[ConversationEvent] | ConversationEventPage:
        runtime = _runtime(request)
        runtime.database.get_session(session_id)
        if not paged:
            return [visible_event(event) for event in runtime.database.events(session_id, after, limit=limit)]
        size = limit or 500
        rows = runtime.database.events(session_id, after, limit=size + 1)
        chosen = rows[:size]
        turns = list({row.payload["turn_id"] for row in chosen if row.payload.get("turn_id")})
        numbers = {}
        if turns:
            with runtime.database._connect() as db:
                for offset in range(0, len(turns), 400):
                    chunk = turns[offset:offset + 400]
                    numbers.update(db.execute(f"SELECT turn_id,number FROM conversation_turns WHERE session_id=? AND turn_id IN ({','.join('?' for _ in chunk)})", [session_id, *chunk]).fetchall())
        return ConversationEventPage(events=[visible_event(event) for event in chosen], after=after, last_sequence=chosen[-1].sequence if chosen else after,
                                     has_more=len(rows) > size, turn_numbers=numbers)

    register_workflow_routes(router)

    register_example_routes(router)
    register_dataset_routes(router)
    register_recent_routes(router)
    register_database_query_routes(router)
    register_source_routes(router)
    register_database_sync_routes(router)
    register_database_job_routes(router)
    register_exploration_routes(router)
    register_database_enrichment_routes(router)
    register_result_view_routes(router)
    register_import_routes(router)
    register_template_routes(router)
    register_export_routes(router)
    register_projection_routes(router)
    register_project_routes(router, app)
    register_connector_routes(router)
    app.include_router(router)

    @app.websocket("/api/sessions/{session_id}/events/ws")
    async def event_stream(
        websocket: WebSocket,
        session_id: str,
        after: int = Query(0, ge=0),
        token: str | None = Query(default=None),
    ) -> None:
        runtime: Runtime = websocket.app.state.runtime
        expected = runtime.settings.api_token
        supplied, accepted_protocol = _websocket_credentials(websocket, token)
        if (
            not runtime.settings.accounts_enabled
            and expected is not None
            and (supplied is None or not hmac.compare_digest(supplied, expected))
        ):
            await websocket.close(code=4401, reason="invalid API token")
            return
        try:
            runtime.database.get_session(session_id)
        except RecordNotFound:
            await websocket.close(code=4404, reason="unknown session")
            return
        await websocket.accept(subprotocol=accepted_protocol)
        queue = runtime.events.subscribe(session_id)
        last_sequence = after
        try:
            for event in runtime.database.events(session_id, after):
                await websocket.send_json(visible_event(event).model_dump(mode="json"))
                last_sequence = max(last_sequence, event.sequence or 0)
            while True:
                principal = current_principal.get()
                if principal and not principal.accounts.session_active(principal):
                    await websocket.close(code=4401, reason="Sign in again.")
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                except TimeoutError:
                    await websocket.send_json({"type": "heartbeat"})
                    continue
                if event.sequence and event.sequence <= last_sequence:
                    continue
                await websocket.send_json(visible_event(event).model_dump(mode="json"))
                last_sequence = event.sequence or last_sequence
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            runtime.events.unsubscribe(session_id, queue)

    static = Path(__file__).with_name("static")
    if static.is_dir():
        assets = WebAssets(static)
        app.state.build_id = assets.build_id

        @app.get("/api/build")
        async def build_info() -> dict[str, str]:
            return {"build_id": assets.build_id, "version": __version__}

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def analytics_workspace():
            return HTMLResponse(assets.pages["analytics.html"], headers={"Cache-Control": "no-cache"})

        @app.get("/classic", response_class=HTMLResponse, include_in_schema=False)
        async def classic_workspace():
            return HTMLResponse(assets.pages["index.html"], headers={"Cache-Control": "no-cache"})

        @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
        async def admin_console():
            return HTMLResponse(assets.files["admin.html"], headers={"Cache-Control": "no-store"})

        app.mount("/", assets, name="ui")
    return app


app = create_app()
