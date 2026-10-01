from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .agent_service import AgentService
from .catalog import Catalog, CatalogError
from .config import Settings
from .database import Database, RecordNotFound
from .execution import GraphMineRunner
from .graph_store import GraphStore, UploadError
from .jobs import EventBus, JobManager
from .llm import LLMError
from .models import (
    ChatRequest,
    ChatResponse,
    ConversationEvent,
    DomainProfile,
    ExecutionPlan,
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


def build_runtime(settings: Settings) -> Runtime:
    settings.data_root.mkdir(parents=True, exist_ok=True)
    settings.workspaces_root.mkdir(parents=True, exist_ok=True)
    catalog = Catalog(settings)
    database = Database(settings.database_path)
    graph_store = GraphStore(settings, database)
    validator = PlanValidator(catalog)
    runner = GraphMineRunner(settings, catalog, graph_store, validator)
    events = EventBus(database)
    jobs = JobManager(
        database,
        runner,
        events,
        summary_items=settings.result_summary_items,
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
    )


def _runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def _authorization(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_graphmine_token: Annotated[str | None, Header()] = None,
) -> None:
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


async def _read_upload(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise UploadError(f"upload exceeds {limit} byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _compiled_backends(runtime: Runtime, operation_id: str) -> set[str] | None:
    capability = runtime.runner.capabilities
    return (
        runtime.runner.compiled_backends_for(operation_id)
        if capability.binary_available
        else None
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = build_runtime(configured)
        app.state.runtime = runtime
        runtime.runner.probe()
        await runtime.jobs.start()
        try:
            yield
        finally:
            await runtime.jobs.stop()
            await runtime.agent.close()

    app = FastAPI(
        title="GraphMine Agent API",
        version="0.1.0",
        description=(
            "Private-LAN orchestration API for validated GraphMine GPU algorithms, "
            "domain-aware planning, interpretation, and interactive visualizations."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-GraphMine-Token"],
    )

    @app.exception_handler(RecordNotFound)
    async def not_found_handler(
        _request: Request, error: RecordNotFound
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": str(error).strip("'")}},
        )

    @app.exception_handler(PlanValidationError)
    async def plan_error_handler(
        _request: Request, error: PlanValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_execution_plan",
                    "message": str(error),
                    "details": error.errors,
                }
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_request", "message": str(error)}},
        )

    @app.exception_handler(CatalogError)
    async def catalog_error_handler(
        _request: Request, error: CatalogError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "catalog_error", "message": str(error)}},
        )

    @app.exception_handler(LLMError)
    async def llm_error_handler(_request: Request, error: LLMError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "llm_unavailable", "message": str(error)}},
        )

    router = APIRouter(prefix="/api", dependencies=[Depends(_authorization)])

    @router.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        runtime = _runtime(request)
        capability = runtime.runner.capabilities
        llm_available = await runtime.agent.model.available()
        ready = capability.binary_available and not capability.error and llm_available
        return {
            "status": "ready" if ready else "degraded",
            "llm": {
                "enabled": runtime.settings.llm_enabled,
                "available": llm_available,
                "model": runtime.settings.llm_model,
                "base_url": runtime.settings.llm_base_url,
                "gpu_uuid": runtime.settings.llm_gpu_uuid,
            },
            "graphmine": capability.model_dump(mode="json"),
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
            SessionRecord(title=body.title, domain_id=body.domain_id)
        )

    @router.get("/sessions", response_model=list[SessionRecord])
    async def list_sessions(
        request: Request, limit: int = Query(100, ge=1, le=500)
    ) -> list[SessionRecord]:
        return _runtime(request).database.list_sessions(limit)

    @router.get("/sessions/{session_id}", response_model=SessionRecord)
    async def get_session(session_id: str, request: Request) -> SessionRecord:
        return _runtime(request).database.get_session(session_id)

    @router.post(
        "/sessions/{session_id}/files", response_model=FileInfo, status_code=201
    )
    async def upload_file(
        session_id: str,
        request: Request,
        file: Annotated[UploadFile, File()],
        role: Annotated[FileRole, Form()] = FileRole.graph,
        directed: Annotated[bool, Form()] = False,
    ) -> FileInfo:
        runtime = _runtime(request)
        runtime.database.get_session(session_id)
        content = await _read_upload(file, runtime.settings.max_upload_bytes)
        return FileInfo.from_stored(
            runtime.graph_store.ingest(
                session_id=session_id,
                role=role,
                filename=file.filename or "upload",
                content=content,
                media_type=file.content_type,
                directed=directed,
            )
        )

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
        return query_path(result.payload, path, offset=offset, limit=limit)

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
        if expected is not None and (
            supplied is None or not hmac.compare_digest(supplied, expected)
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
        app.mount("/", StaticFiles(directory=static, html=True), name="ui")
    return app


app = create_app()
