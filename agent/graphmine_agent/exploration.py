"""Private display preferences and immutable enrichment references, not analysis inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import Field, StrictInt, StrictStr, model_validator
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError, _json, _key
from .database import RecordNotFound
from .identity import AccountError, current_principal
from .models import StrictModel, utc_now
from .result_views import source_files

MAX_STATE_BYTES = 512 * 1024
Identifier = Annotated[str, Field(min_length=1, max_length=128)]
Coordinate = Annotated[float, Field(allow_inf_nan=False, ge=-1e9, le=1e9)]
EntityId = StrictInt | Annotated[StrictStr, Field(max_length=2048)]


class ResultScope(StrictModel):
    workflow_id: Identifier
    revision: int = Field(ge=1, strict=True)
    step: Identifier
    port: Identifier
    index: int | None = Field(default=None, ge=0, strict=True)
    context: bool = False


class ViewScope(StrictModel):
    file_id: Identifier | None = None
    result: ResultScope | None = None

    @model_validator(mode="after")
    def one_source(self):
        if bool(self.file_id) == bool(self.result):
            raise ValueError("Choose one input file or saved result view")
        return self


class Point(StrictModel):
    x: Coordinate
    y: Coordinate


class NodePosition(Point):
    id: EntityId


class Viewport(StrictModel):
    zoom: float = Field(ge=0.08, le=5, allow_inf_nan=False)
    pan: Point
    positions: list[NodePosition] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_positions(self):
        keys = [_key(position.id) for position in self.positions]
        if len(keys) != len(set(keys)):
            raise ValueError("Node positions must have distinct typed IDs")
        return self


class ViewFilters(StrictModel):
    search: str = Field(default="", max_length=2000)
    group_min: str = Field(default="", max_length=32)
    group_max: str = Field(default="", max_length=32)
    group_member: str = Field(default="", max_length=2048)
    group: str = Field(default="", max_length=2048)
    highlight_overlap: bool = False
    flow_direction: bool = True
    time_start: str | None = Field(default=None, max_length=128)
    time_end: str | None = Field(default=None, max_length=128)
    include_untimed: bool = True
    attribute_search: str = Field(default="", max_length=2000)


class GraphView(StrictModel):
    scope: ViewScope
    layout: Literal["cose", "groups", "circle", "grid", "computed"] = "cose"
    viewport: Viewport | None = None
    filters: ViewFilters = Field(default_factory=ViewFilters)
    label_attribute: str = Field(default="", max_length=256)
    color_attribute: str = Field(default="", max_length=256)
    overlay_file_id: Identifier | None = None
    selected_vertices: list[EntityId] = Field(default_factory=list, max_length=500)
    selected_edges: list[EntityId] = Field(default_factory=list, max_length=2000)


class ExplorationState(StrictModel):
    active_file_id: Identifier | None = None
    view: ViewScope | None = None
    views: list[GraphView] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def distinct_views(self):
        keys = [_json(view.scope.model_dump()) for view in self.views]
        if len(keys) != len(set(keys)):
            raise ValueError("Saved view contexts must be unique")
        return self


class SaveExploration(StrictModel):
    expected_revision: int = Field(ge=0, strict=True)
    state: ExplorationState


class ReadOverlay(StrictModel):
    scope: ViewScope
    file_id: Identifier


class Exploration:
    def __init__(self, runtime):
        self.runtime, self.database = runtime, runtime.database
        self._files, self._workflows = {}, {}

    def file(self, session_id, identifier):
        if identifier not in self._files:
            self._files[identifier] = self.database.get_file(identifier)
        file = self._files[identifier]
        if file.session_id != session_id:
            raise RecordNotFound("Exploration input not found")
        return file

    def roots(self, session_id, scope):
        if scope.file_id:
            self.file(session_id, scope.file_id)
            return {scope.file_id}
        selected = scope.result
        if selected.workflow_id not in self._workflows:
            self._workflows[selected.workflow_id] = self.runtime.analytics.get(selected.workflow_id)
        record = self._workflows[selected.workflow_id]
        if record["session_id"] != session_id:
            raise RecordNotFound("Exploration result not found")
        if record["revision"] != selected.revision:
            raise AnalyticsError("The saved result revision changed.", "revision_conflict", 409)
        if selected.step not in record["validation"]["order"]:
            raise AnalyticsError("The saved result step is unavailable.", "invalid_view", 409)
        return set(source_files(record, selected.step))

    def chain(self, session_id, scope, identifier):
        roots, chain, seen = self.roots(session_id, scope), [], set()
        file = self.file(session_id, identifier)
        while file.id not in roots:
            if file.id in seen or len(seen) >= 100:
                raise AnalyticsError("The enrichment ancestry is invalid.", "invalid_view", 409)
            seen.add(file.id); chain.append(file)
            source = file.provenance.get("source", {})
            parent = source.get("parent_file_id")
            if source.get("type") not in {"database_enrichment", "database_expansion"} or not parent:
                raise AnalyticsError("The enrichment does not belong to this saved view.", "invalid_view", 409)
            file = self.file(session_id, parent)
        if not chain:
            raise AnalyticsError("Choose an enrichment derived from this view.", "invalid_view", 409)
        return chain

    def validate(self, session_id, state, *, recover=False):
        warnings = []
        def check(action, reset):
            try:
                action(); return True
            except (RecordNotFound, AnalyticsError):
                if not recover:
                    raise
                reset(); warnings.append("Some saved exploration settings refer to unavailable files or result revisions and were not restored.")
                return False
        if state.active_file_id:
            check(lambda: self.file(session_id, state.active_file_id), lambda: setattr(state, "active_file_id", None))
        if state.view:
            check(lambda: self.roots(session_id, state.view), lambda: setattr(state, "view", None))
        valid = []
        for view in state.views:
            if not check(lambda: self.roots(session_id, view.scope), lambda: None):
                continue
            if view.overlay_file_id:
                check(lambda: self.chain(session_id, view.scope, view.overlay_file_id), lambda: setattr(view, "overlay_file_id", None))
            valid.append(view)
        state.views = valid
        return list(dict.fromkeys(warnings))

    def get(self, session_id):
        self.database.get_session(session_id)
        principal = current_principal.get()
        identity = principal.user_id if principal else self.runtime.settings.api_token or "local"
        storage_key = hashlib.sha256(_json(["exploration-v1", session_id, identity]).encode()).hexdigest()
        with self.database._connect() as db:
            row = db.execute("SELECT revision,document,updated_at FROM session_exploration WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            return {"revision": 0, "state": None, "warnings": [], "storage_key": storage_key}
        state = ExplorationState.model_validate_json(row["document"])
        warnings = self.validate(session_id, state, recover=True)
        return {"revision": row["revision"], "state": state.model_dump(), "updated_at": row["updated_at"], "warnings": warnings, "storage_key": storage_key}

    def save(self, session_id, request):
        self.database.get_session(session_id)
        self.validate(session_id, request.state)
        document = _json(request.state.model_dump())
        if len(document.encode()) > MAX_STATE_BYTES:
            raise AnalyticsError("Saved exploration exceeds its 512 KiB limit.", "resource_limit", 413)
        with self.database._lock, self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision,document FROM session_exploration WHERE session_id=?", (session_id,)).fetchone()
            revision = row["revision"] if row else 0
            if revision != request.expected_revision:
                raise AnalyticsError("Exploration changed in another tab. Reload its settings or explicitly keep this view.", "exploration_conflict", 409, details={"revision": revision})
            principal = current_principal.get()
            previous = len(row["document"].encode()) if row else 0
            if principal and len(document.encode()) - previous > principal.accounts.upload_remaining(principal.user_id):
                raise AccountError("Your storage allowance cannot save these exploration settings.", "storage_limit")
            now = utc_now().isoformat()
            db.execute("INSERT INTO session_exploration VALUES (?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET revision=excluded.revision,document=excluded.document,updated_at=excluded.updated_at",
                       (session_id, revision + 1, document, now))
        return {"revision": revision + 1, "state": request.state.model_dump(), "updated_at": now, "warnings": []}

    def overlay(self, session_id, body):
        """Read saved attributes only; no source credentials or live SQL needed."""
        self.database.get_session(session_id)
        chain = self.chain(session_id, body.scope, body.file_id)
        file = chain[0]
        path = Path(file.source_path).resolve()
        root = (self.runtime.settings.data_root / "sessions" / session_id).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise AnalyticsError("The saved enrichment file is unavailable.", "data_integrity", 409)
        if path.stat().st_size > self.runtime.settings.analytics_max_input_bytes:
            raise AnalyticsError("The saved enrichment exceeds the input byte budget.", "resource_limit")
        raw = path.read_bytes()
        if len(raw) != file.size_bytes or hashlib.sha256(raw).hexdigest() != file.sha256:
            raise AnalyticsError("The saved enrichment failed its integrity check.", "data_integrity", 409)
        graph = json.loads(raw)
        fields, selected = {"vertices": set(), "edges": set()}, {"vertices": {}, "edges": {}}
        for ancestor in reversed(chain):
            detail = ancestor.provenance.get("source", {}).get("enrichment")
            if not detail or detail.get("kind") not in fields:
                continue
            kind, names = detail["kind"], detail["fields"]
            fields[kind].update(names)
            ids = detail.get("updated_ids")
            if ids is None:
                # Older saved enrichments did not retain the fetched ID list.
                # Only recover matching mapped rows with recorded attributes.
                provenance = ancestor.provenance.get("source", {})
                links = provenance.get("lineage", {}).get(kind, {})
                missing = {_key(value) for value in detail.get("missing", [])}
                ids = [row["id"] for row in graph[kind] if _key(row["id"]) not in missing and links.get(_key(row["id"]), {}).get("mapping") == detail["mapping"]]
            for identifier in ids:
                selected[kind].setdefault(_key(identifier), set()).update(names)
        result = {"file_id": file.id, "fetched_at": file.provenance.get("source", {}).get("fetched_at"),
                  "fields": {kind: sorted(names) for kind, names in fields.items()}}
        for kind in fields:
            result[kind] = [{"id": row["id"], "attributes": {name: value for name, value in row.get("attributes", {}).items() if name in selected[kind][_key(row["id"])]}}
                            for row in graph[kind] if _key(row["id"]) in selected[kind]]
        return result


def register_exploration_routes(router):
    def response(value):
        return JSONResponse(value, headers={"Cache-Control": "private, no-store"})

    @router.get("/sessions/{session_id}/exploration")
    def get(session_id: str, request: Request):
        return response(Exploration(request.app.state.runtime).get(session_id))

    @router.put("/sessions/{session_id}/exploration")
    def save(session_id: str, body: SaveExploration, request: Request):
        return response(Exploration(request.app.state.runtime).save(session_id, body))

    @router.post("/sessions/{session_id}/exploration/overlay")
    async def overlay(session_id: str, body: ReadOverlay, request: Request):
        runtime = request.app.state.runtime
        async with runtime.upload_slots:
            return response(await run_in_threadpool(Exploration(runtime).overlay, session_id, body))
