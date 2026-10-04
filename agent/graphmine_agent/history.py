"""Human-readable, append-only evidence alongside the operational database.

Snapshots are convenient current views; events retain every revision, including
failed model calls and interpretations later replaced by a follow-up.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from .models import StoredFile, new_id, utc_now

_context: ContextVar[dict[str, str] | None] = ContextVar(
    "history_context", default=None
)


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Cannot serialize {type(value).__name__}")


class HistoryStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @staticmethod
    def identifier(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("invalid history identifier")
        return value

    def session_path(self, session_id: str) -> Path:
        return self.root / self.identifier(session_id)

    @staticmethod
    def write(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(f".{path.name}.{new_id('tmp')}")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                json.dump(
                    value, stream, indent=2, ensure_ascii=False, default=_json_value
                )
                stream.write("\n")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def snapshot(self, session_id: str, relative: str, value: Any) -> None:
        # Relative names are internal, never supplied directly by an API client.
        path = self.session_path(session_id) / relative
        if not path.resolve().is_relative_to(self.session_path(session_id)):
            raise ValueError("history path escaped session")
        self.write(path, value)

    def text_snapshot(self, session_id: str, relative: str, value: str) -> Path:
        path = self.session_path(session_id) / relative
        if not path.resolve().is_relative_to(self.session_path(session_id)):
            raise ValueError("history path escaped session")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(f".{path.name}.{new_id('tmp')}")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                stream.write(value)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def record(self, session_id: str, kind: str, data: Any) -> str:
        context = _context.get() or {}
        if context.get("session_id") != session_id:
            context = {}
        identifier = new_id("event")
        now = utc_now()
        event = {
            "schema_version": "1.0.0",
            "id": identifier,
            "timestamp": now.isoformat(),
            "session_id": session_id,
            "turn_id": context.get("turn_id"),
            "job_id": context.get("job_id"),
            "type": kind,
            "data": data,
        }
        filename = now.strftime("%Y%m%dT%H%M%S.%fZ") + f"_{identifier}.json"
        self.snapshot(session_id, f"events/{filename}", event)
        if kind in {"chat.request", "chat.response", "chat.error"}:
            self.snapshot(session_id, "last_chat.json", event)
        return identifier

    def current(self, kind: str, data: Any) -> None:
        context = _context.get()
        if context:
            self.record(context["session_id"], kind, data)

    def turn_id(self) -> str | None:
        return (_context.get() or {}).get("turn_id")

    def context(self) -> dict[str, str]:
        return dict(_context.get() or {})

    def session_events(self, session_id: str) -> Iterator[dict[str, Any]]:
        for path in sorted((self.session_path(session_id) / "events").glob("*.json")):
            yield json.loads(path.read_text(encoding="utf-8"))

    def transcript(self, session_id: str) -> list[dict[str, Any]]:
        """Public conversation view; excludes model prompts and private reasoning."""
        rows = []
        results = {}
        for event in self.session_events(session_id):
            kind, data = event["type"], event["data"]
            row = {
                "id": event["id"],
                "turn_id": event.get("turn_id"),
                "created_at": event["timestamp"],
                "kind": kind,
            }
            if kind in {"chat.request", "feedback_command.request"}:
                rows.append({**row, "role": "user", "message": data["message"]})
            elif kind in {"chat.response", "feedback_command.response"}:
                rows.append({**row, "role": "assistant", **data})
            elif kind == "chat.error":
                rows.append(
                    {
                        **row,
                        "role": "assistant",
                        "message": f"Request failed: {data['message']}",
                    }
                )
            elif kind == "result.saved" and data.get("interpretation"):
                result_row = {
                    **row,
                    "role": "assistant",
                    "result_id": data["id"],
                    "message": data["interpretation"]["summary"],
                    "job_id": data["job_id"],
                }
                if data["id"] in results:
                    rows[results[data["id"]]] = result_row
                else:
                    results[data["id"]] = len(rows)
                    rows.append(result_row)
        return rows

    def feedback_context(self, session_id: str, turn_id: str | None) -> dict[str, Any]:
        deployments = []
        for event in self.session_events(session_id):
            if event["type"] == "deployment.context" and (
                not turn_id or event.get("turn_id") == turn_id
            ):
                deployments.append(event["data"])
        return {
            "transcript": self.transcript(session_id),
            "deployment": deployments[-1] if deployments else None,
            "review_status": "unreviewed",
            "automatically_used_for_training": False,
        }

    def model_reasoning(self, session_id: str) -> list[dict[str, Any]]:
        """Expose only reasoning emitted by the user's local model, never prompts.

        Some stages disable thinking and therefore have no reasoning record.
        These are unverified Qwen outputs, distinct from computed answer facts.
        """
        requests = {}
        records = []
        for event in self.session_events(session_id):
            data = event["data"]
            if event["type"] == "llm.request":
                requests[data["call_id"]] = data
            elif event["type"] == "llm.response":
                body = data.get("body")
                if isinstance(body, str):
                    try:
                        body = json.loads(body)
                    except ValueError:
                        continue
                if not isinstance(body, dict):
                    continue
                choices = body.get("choices", [])
                if (
                    not isinstance(choices, list)
                    or not choices
                    or not isinstance(choices[0], dict)
                ):
                    continue
                message = choices[0].get("message", {})
                if not isinstance(message, dict):
                    continue
                reasoning = message.get("reasoning") or message.get("reasoning_content")
                if not isinstance(reasoning, str) or not reasoning.strip():
                    continue
                request = requests.get(data.get("call_id"), {}).get("request", {})
                records.append(
                    {
                        "call_id": data.get("call_id"),
                        "turn_id": event.get("turn_id"),
                        "created_at": event["timestamp"],
                        "model": body.get("model")
                        or request.get("model")
                        or "Local model",
                        "stage": request.get("response_format", {})
                        .get("json_schema", {})
                        .get("name", "Model stage"),
                        "reasoning": reasoning,
                        "source": "local_model_response",
                        "verified_computation": False,
                    }
                )
        return records

    def last_chat(self, session_id: str) -> dict[str, Any] | None:
        path = self.session_path(session_id) / "last_chat.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    @contextmanager
    def scope(
        self,
        session_id: str,
        kind: str,
        request: Any,
        *,
        turn_id: str | None = None,
        job_id: str | None = None,
    ) -> Iterator[str]:
        parent = _context.get() or {}
        inherited = (
            parent.get("turn_id") if parent.get("session_id") == session_id else None
        )
        identifier = turn_id or inherited or new_id("turn")
        context = {"session_id": session_id, "turn_id": identifier}
        if job_id:
            context["job_id"] = job_id
        token = _context.set(context)
        try:
            if not turn_id and not inherited:
                self.snapshot(
                    session_id,
                    f"turns/{identifier}.json",
                    {
                        **context,
                        "kind": kind,
                        "created_at": utc_now().isoformat(),
                        "request": request,
                    },
                )
            self.current(f"{kind}.request", request)
            yield identifier
        except BaseException as error:
            self.current(
                f"{kind}.error", {"type": type(error).__name__, "message": str(error)}
            )
            error.history_turn_id = identifier
            raise
        finally:
            _context.reset(token)

    def file(self, record: StoredFile) -> None:
        directory = (
            self.session_path(record.session_id) / "files" / self.identifier(record.id)
        )
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        artifacts = {}
        for name, source in (
            ("original", record.source_path),
            ("canonical.json", record.canonical_path),
        ):
            if source:
                destination = directory / name
                shutil.copyfile(source, destination)
                destination.chmod(0o600)
                artifacts[name] = {
                    "path": str(
                        destination.relative_to(self.session_path(record.session_id))
                    ),
                    "sha256": self.digest(destination),
                }
        self.snapshot(
            record.session_id,
            f"files/{record.id}/metadata.json",
            {
                "file": record.model_dump(mode="json"),
                "artifacts": artifacts,
            },
        )
        self.record(record.session_id, "file.uploaded", record)

    @staticmethod
    def digest(path: Path) -> str:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def capture_workspace(self, session_id: str, job_id: str, workspace: Path) -> None:
        directory = self.session_path(session_id) / "jobs" / self.identifier(job_id)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in (
            "command.json",
            "result.json",
            "stdout.log",
            "stderr.log",
            "process.json",
            "projection.json",
            "projected-graph.json",
        ):
            source = workspace / name
            if source.is_file():
                shutil.copyfile(source, directory / name)
                (directory / name).chmod(0o600)

    def manifest(self, session_id: str) -> dict[str, Any]:
        root = self.session_path(session_id)
        files = [
            {"path": str(path.relative_to(root)), "size_bytes": path.stat().st_size}
            for path in sorted(root.rglob("*"))
            if path.is_file()
            and not path.is_symlink()
            and not path.name.startswith(".")
        ]
        return {
            "schema_version": "1.0.0",
            "session_id": session_id,
            "files": files,
            "last_chat": self.last_chat(session_id),
        }
