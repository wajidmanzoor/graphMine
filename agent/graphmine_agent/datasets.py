"""Immutable, private input snapshots shared across a user's conversations."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError, _json, _key
from .database import RecordNotFound
from .identity import AccountError, current_principal
from .models import FileInfo, FileRole, new_id, utc_now


class SaveDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    dataset_id: str | None = None
    file_id: str | None = None
    kind: Literal["graph", "graph_collection", "feature_vectors", "hypergraph"] = (
        "graph"
    )
    workflow_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    step: str | None = None
    port: str | None = None
    group_index: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def source(self):
        if bool(self.file_id) == bool(self.workflow_id):
            raise ValueError("Choose exactly one uploaded file or saved result")
        if self.workflow_id:
            if not self.step or not self.port or self.expected_revision is None:
                raise ValueError("A result needs its revision, step and port")
        elif any(
            v is not None
            for v in (self.expected_revision, self.step, self.port, self.group_index)
        ):
            raise ValueError("Result selection cannot accompany an uploaded file")
        if not self.name.strip():
            raise ValueError("A dataset needs a name")
        return self


def _owner():
    principal = current_principal.get()
    return principal.user_id if principal else None


class DatasetLibrary:
    def __init__(self, runtime):
        self.runtime = runtime
        self.database = runtime.database

    def list(self):
        with self.database._connect() as db:
            rows = db.execute(
                "SELECT metadata FROM dataset_versions WHERE owner_id IS ? ORDER BY rowid DESC",
                (_owner(),),
            )
            return [json.loads(row[0]) for row in rows]

    def get(self, version_id, *, content=False):
        with self.database._connect() as db:
            row = db.execute(
                "SELECT metadata"
                + (", content" if content else "")
                + " FROM dataset_versions WHERE id=? AND owner_id IS ?",
                (version_id, _owner()),
            ).fetchone()
        if row is None:
            raise RecordNotFound("Dataset version not found")
        metadata = json.loads(row[0])
        return (metadata, row[1]) if content else metadata

    def _step_input(self, record, step):
        """Use the actual step input, including graphs produced by earlier steps."""
        definition = next(
            s for s in record["validation"]["plan"]["steps"] if s["id"] == step
        )
        ref = definition["input"]
        service = self.runtime.analytics
        if "input" in ref:
            value = json.loads(
                (service._directory(record) / "inputs.json").read_text()
            )[ref["input"]]
            if value["kind"] == "graph":
                return value["data"]
        else:
            port = service._saved(record["id"], step=ref["step"])["result"]["ports"][
                ref["port"]
            ]
            if port["type"] == "graph":
                return port["value"]
            selection = ref.get("select", {})
            if (
                port["type"] == "pattern_collection"
                and selection.get("kind") == "pattern_graph"
            ):
                return port["value"][selection["index"]]["pattern"]
        raise AnalyticsError("The selected result has no reusable graph input")

    def _source(self, body):
        if body.file_id:
            file = self.database.get_file(body.file_id)
            path = self.runtime.graph_store.execution_path(file.id, file.session_id)
            if path.stat().st_size > self.runtime.settings.analytics_max_input_bytes:
                raise AnalyticsError(
                    "Dataset exceeds the input byte budget", "resource_limit"
                )
            try:
                value = json.loads(path.read_bytes())
            except (ValueError, UnicodeError) as exc:
                raise AnalyticsError(
                    "Save a canonical JSON input, or import the CSV as a graph first"
                ) from exc
            return (
                value,
                body.kind,
                {
                    "type": "upload",
                    "session_id": file.session_id,
                    "file_id": file.id,
                    "filename": file.original_name,
                    "upload_sha256": file.sha256,
                    "parent": file.provenance,
                },
                True,
            )
        service = self.runtime.analytics
        record = service.get(body.workflow_id)
        if record["revision"] != body.expected_revision:
            raise AnalyticsError(
                "This analysis changed. Reload its results before saving.",
                "revision_conflict",
                409,
            )
        saved = service._saved(record["id"], step=body.step)
        output = saved.get("result", {}).get("ports", {}).get(body.port)
        if output is None:
            raise RecordNotFound("Result port not found")
        value = output["value"]
        source = {
            "type": "result",
            "session_id": record["session_id"],
            "workflow_id": record["id"],
            "revision": record["revision"],
            "workflow_hash": record["validation"].get("workflow_hash"),
            "step": body.step,
            "port": body.port,
            "output_sha256": hashlib.sha256(_json(output).encode()).hexdigest(),
            "plan": record["validation"]["plan"],
            "input_provenance": record.get("input_provenance", {}),
        }
        if body.group_index is not None:
            if output["type"] != "vertex_groups" or body.group_index >= len(value):
                raise AnalyticsError("Choose a saved group from this result")
            members = {_key(v) for v in value[body.group_index]["vertices"]}
            graph = self._step_input(record, body.step)
            value = copy.deepcopy(graph)
            value["vertices"] = [
                v for v in graph["vertices"] if _key(v["id"]) in members
            ]
            if len(value["vertices"]) != len(members):
                raise AnalyticsError(
                    "Some group members are missing from its saved input graph"
                )
            value["edges"] = [
                e
                for e in graph["edges"]
                if _key(e["source"]) in members and _key(e["target"]) in members
            ]
            source["group_index"] = body.group_index
            source["selection"] = "induced_graph"
        elif output["type"] != "graph":
            raise AnalyticsError(
                "Select a graph output or a group to save as a reusable input"
            )
        return value, "graph", source, output.get("complete") is True

    def save(self, body):
        value, kind, source, complete = self._source(body)
        return self.store(
            value,
            name=body.name,
            kind=kind,
            source=source,
            complete=complete,
            dataset_id=body.dataset_id,
        )

    def store(self, value, *, name, kind, source, complete, dataset_id=None):
        """Persist a server-validated snapshot from an upload, result or connector."""
        if kind == "graph":
            self.runtime.graph_store._validate_graph(value)
        elif not isinstance(value, (list, dict)):
            raise AnalyticsError("Reusable inputs must be structured JSON")
        raw = _json(value).encode()
        if len(raw) > self.runtime.settings.analytics_max_input_bytes:
            raise AnalyticsError(
                "Dataset exceeds the input byte budget", "resource_limit"
            )
        metadata = {
            "id": new_id("dataset_version"),
            "dataset_id": dataset_id or new_id("dataset"),
            "name": name.strip(),
            "kind": kind,
            "version": 1,
            "created_at": utc_now().isoformat(),
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "source": source,
            "source_complete": complete,
        }
        # Version numbers and storage admission are serialized with metadata writes.
        with self.database._lock, self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if dataset_id:
                previous = db.execute(
                    "SELECT kind,last_version FROM dataset_catalog WHERE id=? AND owner_id IS ?",
                    (dataset_id, _owner()),
                ).fetchone()
                if previous is None:
                    raise RecordNotFound("Dataset not found")
                if previous[0] != kind:
                    raise AnalyticsError(
                        "A new version must keep the dataset's input kind"
                    )
                metadata["version"] = previous[1] + 1
            principal = current_principal.get()
            serialized = _json(metadata)
            if principal and len(raw) + len(
                serialized.encode()
            ) > principal.accounts.upload_remaining(principal.user_id):
                raise AccountError(
                    "Your storage allowance is full. Remove unused dataset versions or files.",
                    "storage_limit",
                )
            db.execute(
                "INSERT INTO dataset_versions VALUES (?,?,?,?,?,?,?)",
                (
                    metadata["id"],
                    metadata["dataset_id"],
                    metadata["version"],
                    _owner(),
                    serialized,
                    raw,
                    len(raw),
                ),
            )
            db.execute(
                "INSERT INTO dataset_catalog VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET last_version=excluded.last_version",
                (metadata["dataset_id"], _owner(), kind, metadata["version"]),
            )
        return metadata

    def import_into(self, version_id, session_id):
        self.database.get_session(session_id)
        metadata, raw = self.get(version_id, content=True)
        if hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
            raise AnalyticsError(
                "The saved dataset failed its integrity check", "data_integrity", 409
            )
        record = self.runtime.graph_store.ingest(
            session_id=session_id,
            role=FileRole.graph if metadata["kind"] == "graph" else FileRole.attachment,
            filename=f"{metadata['name']}-v{metadata['version']}.json",
            content=raw,
            media_type="application/json",
            provenance={
                "dataset_id": metadata["dataset_id"],
                "version_id": version_id,
                "version": metadata["version"],
                "sha256": metadata["sha256"],
                "kind": metadata["kind"],
                "source": metadata["source"],
                "source_complete": metadata["source_complete"],
            },
        )
        return {"file": FileInfo.from_stored(record), "kind": metadata["kind"]}

    def delete(self, version_id):
        self.get(version_id)
        with self.database._lock, self.database._connect() as db:
            db.execute(
                "DELETE FROM dataset_versions WHERE id=? AND owner_id IS ?",
                (version_id, _owner()),
            )


def register_dataset_routes(router):
    @router.get("/datasets")
    def datasets(request: Request):
        return DatasetLibrary(request.app.state.runtime).list()

    @router.post("/datasets", status_code=201)
    async def save_dataset(body: SaveDataset, request: Request):
        runtime = request.app.state.runtime
        async with runtime.analytics.edit_lock:
            return await run_in_threadpool(DatasetLibrary(runtime).save, body)

    @router.post("/sessions/{session_id}/datasets/{version_id}/import", status_code=201)
    def import_dataset(session_id: str, version_id: str, request: Request):
        return DatasetLibrary(request.app.state.runtime).import_into(
            version_id, session_id
        )

    @router.delete("/datasets/{version_id}", status_code=204)
    def delete_dataset(version_id: str, request: Request):
        DatasetLibrary(request.app.state.runtime).delete(version_id)
