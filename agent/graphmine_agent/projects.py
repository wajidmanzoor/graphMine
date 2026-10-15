"""Explicit project snapshots; private conversation ownership never changes."""

import hashlib
import json
import secrets
import time
from typing import Literal

from fastapi import Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError, _json
from .database import RecordNotFound
from .datasets import DatasetLibrary, SaveDataset
from .identity import AccountError, current_principal
from .models import FileInfo, FileRole, new_id, utc_now


class Name(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        # Normalize display names only. Subclasses also contain typed entity IDs.
        return value.strip() if isinstance(value, str) else value


class Member(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64)
    role: Literal["editor", "viewer"]


class Publish(Name):
    version_id: str | None = None
    file_id: str | None = None
    workflow_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    kind: Literal["graph", "graph_collection", "feature_vectors", "hypergraph"] = (
        "graph"
    )


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=4000)


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    vertex: StrictInt | StrictStr
    x: float = Field(ge=-1e9, le=1e9)
    y: float = Field(ge=-1e9, le=1e9)


class SavedView(Name):
    layout: Literal["cose", "circle", "grid"] = "cose"
    selected: list[StrictInt | StrictStr] = Field(default_factory=list, max_length=500)
    positions: list[Position] = Field(default_factory=list, max_length=500)


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(default=7, ge=1, le=30, strict=True)


class SharedRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=40, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


def actor():
    value = current_principal.get()
    if value is None:
        raise AccountError(
            "Projects require an account. Sign in to continue.", "unauthorized", 401
        )
    return value


class Projects:
    def __init__(self, runtime):
        self.runtime, self.db = runtime, runtime.database

    def access(self, db, project_id, *, write=False, owner=False):
        user = actor()
        row = db.execute(
            "SELECT p.*,m.role FROM projects p LEFT JOIN project_members m ON m.project_id=p.id AND m.user_id=? WHERE p.id=?",
            (user.user_id, project_id),
        ).fetchone()
        if row is None or row["owner_id"] != user.user_id and row["role"] is None:
            raise RecordNotFound("Project not found")
        project = dict(row)
        project["role"] = "owner" if row["owner_id"] == user.user_id else row["role"]
        if (
            owner
            and project["role"] != "owner"
            or write
            and project["role"] == "viewer"
        ):
            raise AccountError(
                "Your project role does not allow this change.", "forbidden", 403
            )
        return project

    def list(self):
        user = actor()
        with self.db._connect() as db:
            rows = db.execute(
                "SELECT p.*,CASE WHEN p.owner_id=? THEN 'owner' ELSE m.role END AS role FROM projects p "
                "LEFT JOIN project_members m ON m.project_id=p.id AND m.user_id=? WHERE p.owner_id=? OR m.user_id=? ORDER BY p.created_at DESC",
                (user.user_id,) * 4,
            )
            return [dict(row) for row in rows]

    def create(self, body):
        user = actor()
        project = {
            "id": new_id("project"),
            "owner_id": user.user_id,
            "name": body.name,
            "created_at": utc_now().isoformat(),
        }
        with self.db._lock, self.db._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT count(*) FROM projects WHERE owner_id=?", (user.user_id,)
                ).fetchone()[0]
                >= 50
            ):
                raise AnalyticsError(
                    "Remove an unused project before creating another (limit 50).",
                    "resource_limit",
                )
            db.execute("INSERT INTO projects VALUES (?,?,?,?)", tuple(project.values()))
        return {**project, "role": "owner"}

    def get(self, project_id):
        with self.db._connect() as db:
            project = self.access(db, project_id)
            project["members"] = [
                dict(row)
                for row in db.execute(
                    "SELECT a.username,m.user_id,m.role FROM project_members m JOIN accounts a ON a.id=m.user_id WHERE m.project_id=? ORDER BY a.username",
                    (project_id,),
                )
            ]
            project["items"] = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT metadata FROM project_items WHERE project_id=? ORDER BY rowid DESC",
                    (project_id,),
                )
            ]
            return project

    def member(self, project_id, body):
        with self.db._lock, self.db._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            project = self.access(db, project_id, owner=True)
            user = db.execute(
                "SELECT id FROM accounts WHERE username=? AND disabled=0",
                (self.runtime.accounts.username(body.username),),
            ).fetchone()
            if user is None:
                raise RecordNotFound("Active account not found")
            if user[0] == project["owner_id"]:
                raise AnalyticsError("The project owner retains ownership.")
            db.execute(
                "INSERT INTO project_members VALUES (?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role",
                (project_id, user[0], body.role),
            )

    def remove_member(self, project_id, user_id):
        with self.db._lock, self.db._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.access(db, project_id, owner=True)
            db.execute(
                "DELETE FROM project_members WHERE project_id=? AND user_id=?",
                (project_id, user_id),
            )

    def delete(self, project_id):
        with self.db._lock, self.db._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.access(db, project_id, owner=True)
            db.execute("DELETE FROM projects WHERE id=?", (project_id,))

    def space(self, owner_id, needed):
        if needed > self.runtime.accounts.upload_remaining(owner_id):
            raise AccountError(
                "The project owner's storage allowance is full.", "storage_limit"
            )

    def publish(self, project_id, body):
        with self.db._connect() as db:
            self.access(db, project_id, write=True)
        if sum(bool(v) for v in (body.version_id, body.file_id, body.workflow_id)) != 1:
            raise AnalyticsError("Choose exactly one dataset version, input or result.")
        if body.workflow_id:
            service = self.runtime.analytics
            record = service.get(body.workflow_id)
            if body.expected_revision != record["revision"]:
                raise AnalyticsError(
                    "Reload the result before sharing it.", "revision_conflict", 409
                )
            value = {
                "kind": "workflow",
                "plan": record["validation"]["plan"],
                "result": service._saved(record["id"]),
                "inputs": json.loads(
                    (service._directory(record) / "inputs.json").read_bytes()
                ),
            }
            provenance = {
                "workflow_id": record["id"],
                "revision": record["revision"],
                "workflow_hash": record["validation"]["workflow_hash"],
                "input_provenance": record.get("input_provenance", {}),
            }
        elif body.version_id:
            metadata, raw = DatasetLibrary(self.runtime).get(
                body.version_id, content=True
            )
            if hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
                raise AnalyticsError(
                    "The dataset failed its integrity check.", "data_integrity", 409
                )
            value = {"kind": metadata["kind"], "data": json.loads(raw)}
            provenance = metadata
        else:
            data, kind, provenance, _ = DatasetLibrary(self.runtime)._source(
                SaveDataset(name=body.name, file_id=body.file_id, kind=body.kind)
            )
            if kind == "graph":
                self.runtime.graph_store._validate_graph(data)
            value = {"kind": kind, "data": data}
        raw = _json(value).encode()
        if len(raw) > 32 * 1024 * 1024:
            raise AnalyticsError(
                "Project snapshots are limited to 32 MiB. Save a smaller graph or result.",
                "resource_limit",
            )
        metadata = {
            "id": new_id("shared"),
            "project_id": project_id,
            "name": body.name,
            "kind": value["kind"],
            "created_at": utc_now().isoformat(),
            "source": provenance,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }
        encoded = _json(metadata)
        with self.db._lock, self.db._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            project = self.access(db, project_id, write=True)
            self.space(project["owner_id"], len(raw) + len(encoded.encode()))
            db.execute(
                "INSERT INTO project_items VALUES (?,?,?,?,?)",
                (metadata["id"], project_id, encoded, raw, len(raw)),
            )
        return metadata

    @staticmethod
    def decode(row):
        metadata = json.loads(row["metadata"])
        if hashlib.sha256(row["content"]).hexdigest() != metadata["sha256"]:
            raise AnalyticsError(
                "The shared snapshot failed its integrity check.", "data_integrity", 409
            )
        return {**metadata, "snapshot": json.loads(row["content"])}

    def item(self, item_id):
        with self.db._connect() as db:
            row = db.execute(
                "SELECT * FROM project_items WHERE id=?", (item_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFound("Shared item not found")
            project = self.access(db, row["project_id"])
            item = self.decode(row)
            item["role"] = project["role"]
            item["notes"] = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT document FROM project_notes WHERE item_id=? ORDER BY rowid",
                    (item_id,),
                )
            ]
            item["links"] = (
                [
                    dict(row)
                    for row in db.execute(
                        "SELECT id,expires_at,created_at FROM project_links WHERE item_id=?",
                        (item_id,),
                    )
                ]
                if project["role"] == "owner"
                else []
            )
            return item

    def item_access(self, db, item_id, **permissions):
        row = db.execute(
            "SELECT project_id FROM project_items WHERE id=?", (item_id,)
        ).fetchone()
        if row is None:
            raise RecordNotFound("Shared item not found")
        return self.access(db, row[0], **permissions)

    def delete_item(self, item_id):
        with self.db._lock, self.db._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.item_access(db, item_id, owner=True)
            db.execute("DELETE FROM project_items WHERE id=?", (item_id,))

    def note(self, item_id, body, kind):
        user = actor()
        document = {
            "id": new_id("note"),
            "author_id": user.user_id,
            "author": user.username,
            "kind": kind,
            "created_at": utc_now().isoformat(),
            **body.model_dump(mode="json"),
        }
        raw = _json(document)
        with self.db._lock, self.db._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            project = self.item_access(db, item_id, write=True)
            self.space(project["owner_id"], len(raw.encode()))
            db.execute(
                "INSERT INTO project_notes VALUES (?,?,?,?,?)",
                (document["id"], item_id, user.user_id, kind, raw),
            )
        return document

    def delete_note(self, note_id):
        with self.db._lock, self.db._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT item_id,author_id FROM project_notes WHERE id=?", (note_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFound("Note not found")
            project = self.item_access(db, row[0], write=True)
            if actor().user_id != row[1] and project["role"] != "owner":
                raise AccountError(
                    "Only the author or project owner can remove this note.",
                    "forbidden",
                    403,
                )
            db.execute("DELETE FROM project_notes WHERE id=?", (note_id,))

    def link(self, item_id, body):
        token = secrets.token_urlsafe(32)
        record = {
            "id": new_id("link"),
            "expires_at": time.time() + body.days * 86400,
            "created_at": utc_now().isoformat(),
        }
        with self.db._lock, self.db._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.item_access(db, item_id, owner=True)
            db.execute("DELETE FROM project_links WHERE expires_at<=?", (time.time(),))
            if (
                db.execute(
                    "SELECT count(*) FROM project_links WHERE item_id=?", (item_id,)
                ).fetchone()[0]
                >= 20
            ):
                raise AnalyticsError(
                    "Revoke an unused link before creating another (limit 20).",
                    "resource_limit",
                )
            db.execute(
                "INSERT INTO project_links VALUES (?,?,?,?,?)",
                (
                    record["id"],
                    item_id,
                    hashlib.sha256(token.encode()).hexdigest(),
                    record["expires_at"],
                    record["created_at"],
                ),
            )
        return {**record, "url": "/shared.html#" + token}

    def revoke(self, link_id):
        with self.db._lock, self.db._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT item_id FROM project_links WHERE id=?", (link_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFound("Link not found")
            self.item_access(db, row[0], owner=True)
            db.execute("DELETE FROM project_links WHERE id=?", (link_id,))

    def shared(self, token):
        with self.db._connect() as db:
            row = db.execute(
                "SELECT i.* FROM project_links l JOIN project_items i ON i.id=l.item_id JOIN projects p ON p.id=i.project_id "
                "JOIN accounts a ON a.id=p.owner_id WHERE l.token_hash=? AND l.expires_at>? AND a.disabled=0",
                (hashlib.sha256(token.encode()).hexdigest(), time.time()),
            ).fetchone()
            if row is None:
                raise RecordNotFound("This link is invalid, expired or revoked.")
            item = self.decode(row)
            # Discussion and membership never accompany a public link.
            return {
                key: item[key]
                for key in ("name", "kind", "created_at", "sha256", "snapshot")
            }

    def import_item(self, item_id, session_id):
        self.db.get_session(session_id)
        item = self.item(item_id)
        if item["kind"] == "workflow":
            raise AnalyticsError(
                "Save a graph as a project input to reuse it in a calculation."
            )
        record = self.runtime.graph_store.ingest(
            session_id=session_id,
            role=FileRole.graph if item["kind"] == "graph" else FileRole.attachment,
            filename=item["name"] + ".json",
            content=_json(item["snapshot"]["data"]).encode(),
            provenance={
                "project_item": item_id,
                "project_id": item["project_id"],
                "sha256": item["sha256"],
                "kind": item["kind"],
            },
        )
        return {"file": FileInfo.from_stored(record), "kind": item["kind"]}


def register_project_routes(router, app):
    def service(request):
        return Projects(request.app.state.runtime)

    @router.get("/projects")
    def list_projects(request: Request):
        return service(request).list()

    @router.post("/projects", status_code=201)
    def create_project(body: Name, request: Request):
        return service(request).create(body)

    @router.get("/projects/{project_id}")
    def get_project(project_id: str, request: Request):
        return service(request).get(project_id)

    @router.delete("/projects/{project_id}", status_code=204)
    def delete_project(project_id: str, request: Request):
        service(request).delete(project_id)

    @router.post("/projects/{project_id}/members", status_code=204)
    def add_member(project_id: str, body: Member, request: Request):
        service(request).member(project_id, body)

    @router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
    def remove_member(project_id: str, user_id: str, request: Request):
        service(request).remove_member(project_id, user_id)

    @router.post("/projects/{project_id}/items", status_code=201)
    async def publish(project_id: str, body: Publish, request: Request):
        async with request.app.state.runtime.analytics.edit_lock:
            return await run_in_threadpool(service(request).publish, project_id, body)

    @router.get("/project-items/{item_id}")
    def get_item(item_id: str, request: Request):
        return service(request).item(item_id)

    @router.delete("/project-items/{item_id}", status_code=204)
    def delete_item(item_id: str, request: Request):
        service(request).delete_item(item_id)

    @router.post("/project-items/{item_id}/annotations", status_code=201)
    def annotate(item_id: str, body: Annotation, request: Request):
        return service(request).note(item_id, body, "annotation")

    @router.post("/project-items/{item_id}/views", status_code=201)
    def view(item_id: str, body: SavedView, request: Request):
        return service(request).note(item_id, body, "view")

    @router.delete("/project-notes/{note_id}", status_code=204)
    def delete_note(note_id: str, request: Request):
        service(request).delete_note(note_id)

    @router.post("/project-items/{item_id}/links", status_code=201)
    def create_link(item_id: str, body: LinkRequest, request: Request):
        return service(request).link(item_id, body)

    @router.delete("/project-links/{link_id}", status_code=204)
    def revoke_link(link_id: str, request: Request):
        service(request).revoke(link_id)

    @router.post(
        "/sessions/{session_id}/project-items/{item_id}/import", status_code=201
    )
    def import_item(session_id: str, item_id: str, request: Request):
        return service(request).import_item(item_id, session_id)

    @app.post("/api/shared/read")
    async def shared_read(body: SharedRead, request: Request, response: Response):
        runtime = request.app.state.runtime
        if runtime.upload_slots.locked():
            raise AccountError("Shared previews are busy. Retry shortly.", "busy", 429)
        response.headers.update(
            {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
        )
        async with runtime.upload_slots:
            return await run_in_threadpool(service(request).shared, body.token)
