from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import json
import sqlite3
import tempfile
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
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
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import __version__
from .account_api import AccountMiddleware, account_response, register_account_routes
from .accounts import Accounts
from .agent_service import AgentService
from .analytics import (
    AnalyticsError,
    AnalyticsService,
    WorkflowApproval,
    WorkflowRequest,
    WorkflowRevision,
)
from .analytics_examples import register_example_routes
from .analytics_planning import AnalyticsPlanner, PlanningRequest
from .analytics_projection import register_projection_routes
from .catalog import Catalog, CatalogError
from .config import Settings
from .database import Database, QueueCapacityError, RecordNotFound
from .execution import ExecutionError, GraphMineRunner
from .graph_store import GraphStore, UploadError
from .history import HistoryStore
from .identity import AccountError, current_principal
from .jobs import EventBus, JobManager
from .llm import LLMError
from .models import (
    ChatRequest,
    ChatResponse,
    ConversationEvent,
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
)
from .planning import PlanValidationError, PlanValidator
from .reporting import render_report
from .results import query_path


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


def build_runtime(settings: Settings, *, serving: bool = False) -> Runtime:
    settings.data_root.mkdir(parents=True, exist_ok=True)
    settings.workspaces_root.mkdir(parents=True, exist_ok=True)
    catalog = Catalog(settings)
    database = Database(settings.database_path, HistoryStore(settings.history_root))
    accounts = Accounts(settings, database)
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
    agent = AgentService(settings, catalog, database, graph_store, validator, jobs)
    jobs.result_handler = agent.handle_completed_result
    return Runtime(
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
        analytics=AnalyticsService(settings, database, graph_store, events),
        accounts=accounts,
    )


def _runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def _authorization(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_graphmine_token: Annotated[str | None, Header()] = None,
) -> None:
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
        try:
            runtime.runner.probe()
            await runtime.jobs.start()
            runtime.analytics.open()
            if configured.accounts_enabled:
                # Both store locks are held and interrupted jobs are now terminal.
                with runtime.database._connect() as db:
                    db.execute("DELETE FROM account_leases WHERE kind != 'model'")
            yield
        finally:
            try:
                await runtime.analytics.close()
            finally:
                try:
                    await runtime.jobs.stop()
                finally:
                    await runtime.agent.close()

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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-GraphMine-Token",
            "X-GraphMine-Request",
        ],
    )
    register_account_routes(app)

    @app.exception_handler(AccountError)
    async def account_error_handler(_request, error):
        return account_response(error)

    @app.exception_handler(AnalyticsError)
    async def analytics_error_handler(
        _request: Request, error: AnalyticsError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={"error": {"code": error.code, "message": str(error)}},
        )

    @app.exception_handler(RecordNotFound)
    async def not_found_handler(
        _request: Request, error: RecordNotFound
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"code": "not_found", "message": str(error).strip("'")},
                "turn_id": getattr(error, "history_turn_id", None),
            },
        )

    @app.exception_handler(PlanValidationError)
    async def plan_error_handler(
        _request: Request, error: PlanValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "turn_id": getattr(error, "history_turn_id", None),
                "error": {
                    "code": "invalid_execution_plan",
                    "message": str(error),
                    "details": error.errors,
                },
            },
        )

    @app.exception_handler(QueueCapacityError)
    async def queue_capacity_handler(
        _request: Request, error: QueueCapacityError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "5"},
            content={
                "turn_id": getattr(error, "history_turn_id", None),
                "error": {
                    "code": "job_queue_full",
                    "message": str(error),
                    "details": {
                        "limit": error.limit,
                        "pending": error.pending,
                        "requested": error.requested,
                    },
                },
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "invalid_request", "message": str(error)},
                "turn_id": getattr(error, "history_turn_id", None),
            },
        )

    @app.exception_handler(CatalogError)
    async def catalog_error_handler(
        _request: Request, error: CatalogError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "catalog_error", "message": str(error)},
                "turn_id": getattr(error, "history_turn_id", None),
            },
        )

    @app.exception_handler(LLMError)
    async def llm_error_handler(_request: Request, error: LLMError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {"code": "llm_unavailable", "message": str(error)},
                "turn_id": getattr(error, "history_turn_id", None),
            },
        )

    @app.exception_handler(ExecutionError)
    async def execution_error_handler(
        _request: Request, error: ExecutionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {"code": error.code, "message": str(error)},
                "turn_id": getattr(error, "history_turn_id", None),
            },
        )

    router = APIRouter(prefix="/api", dependencies=[Depends(_authorization)])

    @app.exception_handler(sqlite3.Error)
    async def storage_error_handler(
        _request: Request, _error: sqlite3.Error
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "storage_unavailable",
                    "message": "The metadata store is unavailable. Check storage and job status before retrying.",
                }
            },
        )

    @router.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        runtime = _runtime(request)
        capability = runtime.runner.capabilities
        llm_available = await runtime.agent.model.available()
        worker = runtime.jobs.statistics()
        history = runtime.database.history.statistics()
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
            "deployment": runtime.agent.deployment_info(),
            "status": "ready" if ready else "degraded",
            "llm": {
                "enabled": runtime.settings.llm_enabled,
                "available": llm_available,
                "model": runtime.settings.llm_model,
                "base_url": runtime.settings.llm_base_url,
                "gpu_uuid": runtime.settings.llm_gpu_uuid,
            },
            "graphmine": capability.model_dump(mode="json"),
            "worker": worker,
            "history": history,
        }

    @router.get("/metrics")
    async def metrics(request: Request) -> dict[str, Any]:
        runtime = _runtime(request)
        return {
            "version": __version__,
            "database": runtime.database.statistics(),
            "worker": runtime.jobs.statistics(),
            "history": runtime.database.history.statistics(),
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
    async def list_sessions(
        request: Request, limit: int = Query(100, ge=1, le=500)
    ) -> list[SessionRecord]:
        return _runtime(request).database.list_sessions(limit)

    @router.get("/sessions/{session_id}", response_model=SessionRecord)
    async def get_session(session_id: str, request: Request) -> SessionRecord:
        return _runtime(request).database.get_session(session_id)

    @router.get("/sessions/{session_id}/workspace")
    async def session_workspace(session_id: str, request: Request):
        runtime = _runtime(request)
        database = runtime.database
        session = database.get_session(session_id)
        jobs = database.list_jobs(session_id)
        return {
            "session": session,
            "messages": database.conversation_transcript(session_id),
            "files": [
                FileInfo.from_stored(item) for item in database.list_files(session_id)
            ],
            "jobs": jobs,
            "events": database.events(session_id),
            "feedback_count": len(database.feedback(session_id)),
            "deployment": runtime.agent.deployment_info(),
        }

    @router.get("/sessions/{session_id}/feedback/export")
    async def export_feedback(session_id: str, request: Request):
        database = _runtime(request).database
        records = database.feedback(session_id)
        rows = [
            {
                "schema_version": "graphmine-feedback-v1",
                "review_status": "unreviewed",
                "automatically_used_for_training": False,
                "annotation": item.model_dump(mode="json"),
            }
            for item in records
        ]
        return Response(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": f'attachment; filename="{session_id}-feedback.jsonl"'
            },
        )

    @router.get("/sessions/{session_id}/reasoning")
    async def model_reasoning(session_id: str, request: Request):
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
        database = _runtime(request).database
        database.get_session(session_id)
        history = database.history
        history.snapshot(
            session_id,
            "conversation.json",
            database.conversation_transcript(session_id),
        )
        history.snapshot(session_id, "session.json", database.get_session(session_id))

        def chunks():
            with tempfile.TemporaryFile() as archive:
                with zipfile.ZipFile(
                    archive, "w", compression=zipfile.ZIP_DEFLATED
                ) as bundle:
                    for item in history.manifest(session_id)["files"]:
                        relative = item["path"]
                        bundle.write(
                            history.session_path(session_id) / relative,
                            f"{session_id}/{relative}",
                        )
                archive.seek(0)
                while chunk := archive.read(1024 * 1024):
                    yield chunk

        return StreamingResponse(
            chunks(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{session_id}.zip"',
            },
        )

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
        return _runtime(request).graph_store.graph_preview(
            file_id, vertex_limit=vertex_limit, edge_limit=edge_limit
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
    async def download_answer(result_id: str, request: Request) -> HTMLResponse:
        result = _runtime(request).database.get_result(result_id)
        return HTMLResponse(
            render_report(result),
            headers={
                "Content-Disposition": f'attachment; filename="{result.id}.html"',
                "X-Content-Type-Options": "nosniff",
            },
        )

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

    @router.get("/sessions/{session_id}/events", response_model=list[ConversationEvent])
    async def events(
        session_id: str, request: Request, after: int = Query(0, ge=0)
    ) -> list[ConversationEvent]:
        runtime = _runtime(request)
        runtime.database.get_session(session_id)
        return runtime.database.events(session_id, after)

    @router.get("/analytics/capabilities")
    async def analytics_capabilities(request: Request):
        return await _runtime(request).analytics.capabilities()

    @router.post("/sessions/{session_id}/workflows", status_code=201)
    async def create_workflow(session_id: str, body: WorkflowRequest, request: Request):
        return await _runtime(request).analytics.create(session_id, body)

    @router.post("/sessions/{session_id}/analytics/plan")
    async def plan_analytics(session_id: str, body: PlanningRequest, request: Request):
        runtime = _runtime(request)
        return await AnalyticsPlanner(
            runtime.settings, runtime.analytics, runtime.events
        ).plan(session_id, body)

    @router.get("/sessions/{session_id}/workflows")
    async def list_workflows(session_id: str, request: Request):
        return _runtime(request).analytics.list(session_id)

    @router.get("/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str, request: Request):
        return _runtime(request).analytics.get(workflow_id)

    @router.post("/workflows/{workflow_id}/revise")
    async def revise_workflow(
        workflow_id: str, body: WorkflowRevision, request: Request
    ):
        return await _runtime(request).analytics.revise(workflow_id, body)

    @router.post("/workflows/{workflow_id}/run", status_code=202)
    async def run_workflow(workflow_id: str, body: WorkflowApproval, request: Request):
        return await _runtime(request).analytics.start(
            workflow_id, body.workflow_hash, body.expected_revision
        )

    @router.delete("/workflows/{workflow_id}")
    async def cancel_workflow(workflow_id: str, request: Request):
        return await _runtime(request).analytics.cancel(workflow_id)

    @router.get("/workflows/{workflow_id}/result")
    async def workflow_result(workflow_id: str, request: Request):
        return _runtime(request).analytics.result(workflow_id)

    @router.get("/workflows/{workflow_id}/steps/{step}/result")
    async def workflow_step_result(workflow_id: str, step: str, request: Request):
        return _runtime(request).analytics.result(workflow_id, step=step)

    @router.get("/workflows/{workflow_id}/steps/{step}/ports/{port}")
    async def workflow_port(
        workflow_id: str,
        step: str,
        port: str,
        request: Request,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
    ):
        return _runtime(request).analytics.port_page(
            workflow_id, step, port, offset, limit
        )

    register_example_routes(router)
    register_projection_routes(router)
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
                await websocket.send_json(event.model_dump(mode="json"))
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
                await websocket.send_json(event.model_dump(mode="json"))
                last_sequence = event.sequence or last_sequence
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            runtime.events.unsubscribe(session_id, queue)

    static = Path(__file__).with_name("static")
    if static.is_dir():

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def analytics_workspace():
            return HTMLResponse((static / "analytics.html").read_text(encoding="utf-8"))

        @app.get("/classic", response_class=HTMLResponse, include_in_schema=False)
        async def classic_workspace():
            return HTMLResponse((static / "index.html").read_text(encoding="utf-8"))

        app.mount("/", StaticFiles(directory=static, html=True), name="ui")
    return app


app = create_app()
