from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from .models import (
    ConversationEvent,
    JobRecord,
    JobStatus,
    ResultRecord,
    SessionRecord,
    StoredFile,
    utc_now,
)


class RecordNotFound(KeyError):
    pass


class Database:
    """Small durable metadata store; bulk graph/results remain in workspaces."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  id TEXT PRIMARY KEY,
                  payload TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS files (
                  id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  role TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS files_session_idx ON files(session_id);
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  status TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_session_idx ON jobs(session_id);
                CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status);
                CREATE TABLE IF NOT EXISTS results (
                  id TEXT PRIMARY KEY,
                  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  payload TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS results_session_idx ON results(session_id);
                CREATE TABLE IF NOT EXISTS messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  role TEXT NOT NULL,
                  mode TEXT,
                  payload TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS messages_session_idx ON messages(session_id, id);
                CREATE TABLE IF NOT EXISTS events (
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  job_id TEXT,
                  type TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_session_idx ON events(session_id, sequence);
                """
            )

    @staticmethod
    def _json(model: Any) -> str:
        if hasattr(model, "model_dump"):
            model = model.model_dump(mode="json")
        return json.dumps(model, ensure_ascii=False, separators=(",", ":"))

    def create_session(self, session: SessionRecord) -> SessionRecord:
        payload = self._json(session)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions(id,payload,created_at,updated_at) VALUES(?,?,?,?)",
                (
                    session.id,
                    payload,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
        return session

    def get_session(self, session_id: str) -> SessionRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        if row is None:
            raise RecordNotFound(f"unknown session: {session_id}")
        return SessionRecord.model_validate_json(row["payload"])

    def list_sessions(self, limit: int = 100) -> list[SessionRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [SessionRecord.model_validate_json(row["payload"]) for row in rows]

    def touch_session(self, session_id: str) -> None:
        session = self.get_session(session_id)
        updated = session.model_copy(update={"updated_at": utc_now()})
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET payload=?,updated_at=? WHERE id=?",
                (self._json(updated), updated.updated_at.isoformat(), session_id),
            )

    def add_file(self, record: StoredFile) -> StoredFile:
        self.get_session(record.session_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO files(id,session_id,role,payload,created_at) VALUES(?,?,?,?,?)",
                (
                    record.id,
                    record.session_id,
                    record.role.value,
                    self._json(record),
                    record.created_at.isoformat(),
                ),
            )
        self.touch_session(record.session_id)
        return record

    def get_file(self, file_id: str) -> StoredFile:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM files WHERE id=?", (file_id,)
            ).fetchone()
        if row is None:
            raise RecordNotFound(f"unknown file: {file_id}")
        return StoredFile.model_validate_json(row["payload"])

    def list_files(self, session_id: str) -> list[StoredFile]:
        self.get_session(session_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM files WHERE session_id=? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        return [StoredFile.model_validate_json(row["payload"]) for row in rows]

    def save_job(self, job: JobRecord) -> JobRecord:
        now = utc_now().isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs(id,session_id,status,payload,created_at,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  status=excluded.status,payload=excluded.payload,updated_at=excluded.updated_at
                """,
                (
                    job.id,
                    job.session_id,
                    job.status.value,
                    self._json(job),
                    job.created_at.isoformat(),
                    now,
                ),
            )
        self.touch_session(job.session_id)
        return job

    def get_job(self, job_id: str) -> JobRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        if row is None:
            raise RecordNotFound(f"unknown job: {job_id}")
        return JobRecord.model_validate_json(row["payload"])

    def list_jobs(
        self, session_id: str | None = None, statuses: set[JobStatus] | None = None
    ) -> list[JobRecord]:
        clauses: list[str] = []
        arguments: list[Any] = []
        if session_id:
            clauses.append("session_id=?")
            arguments.append(session_id)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            arguments.extend(item.value for item in statuses)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM jobs{where} ORDER BY created_at", arguments
            ).fetchall()
        return [JobRecord.model_validate_json(row["payload"]) for row in rows]

    def save_result(self, result: ResultRecord) -> ResultRecord:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO results(id,job_id,session_id,payload,created_at) VALUES(?,?,?,?,?)",
                (
                    result.id,
                    result.job_id,
                    result.session_id,
                    self._json(result),
                    result.created_at.isoformat(),
                ),
            )
        return result

    def update_result(self, result: ResultRecord) -> ResultRecord:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE results SET payload=? WHERE id=?",
                (self._json(result), result.id),
            )
        if cursor.rowcount == 0:
            raise RecordNotFound(f"unknown result: {result.id}")
        return result

    def get_result(self, result_id: str) -> ResultRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM results WHERE id=?", (result_id,)
            ).fetchone()
        if row is None:
            raise RecordNotFound(f"unknown result: {result_id}")
        return ResultRecord.model_validate_json(row["payload"])

    def latest_result(self, session_id: str) -> ResultRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM results WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return None if row is None else ResultRecord.model_validate_json(row["payload"])

    def add_message(
        self,
        session_id: str,
        role: str,
        payload: dict[str, Any],
        mode: str | None = None,
    ) -> None:
        self.get_session(session_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO messages(session_id,role,mode,payload,created_at) VALUES(?,?,?,?,?)",
                (session_id, role, mode, self._json(payload), utc_now().isoformat()),
            )
        self.touch_session(session_id)

    def messages(self, session_id: str, limit: int = 40) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role,mode,payload,created_at FROM messages
                WHERE session_id=? ORDER BY id DESC LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [
            {
                "role": row["role"],
                "mode": row["mode"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"],
            }
            for row in reversed(rows)
        ]

    def add_event(self, event: ConversationEvent) -> ConversationEvent:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO events(session_id,job_id,type,payload,created_at) VALUES(?,?,?,?,?)",
                (
                    event.session_id,
                    event.job_id,
                    event.type,
                    self._json(event.payload),
                    event.created_at.isoformat(),
                ),
            )
        return event.model_copy(update={"sequence": int(cursor.lastrowid)})

    def events(self, session_id: str, after: int = 0) -> list[ConversationEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence,session_id,job_id,type,payload,created_at
                FROM events WHERE session_id=? AND sequence>?
                ORDER BY sequence
                """,
                (session_id, after),
            ).fetchall()
        return [
            ConversationEvent(
                sequence=row["sequence"],
                session_id=row["session_id"],
                job_id=row["job_id"],
                type=row["type"],
                payload=json.loads(row["payload"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def mark_interrupted_jobs_failed(self) -> int:
        jobs = self.list_jobs(statuses={JobStatus.running, JobStatus.interpreting})
        for job in jobs:
            failed = job.model_copy(
                update={
                    "status": JobStatus.failed,
                    "finished_at": utc_now(),
                    "error": {
                        "code": "server_restarted",
                        "message": "the agent server restarted while this job was active",
                    },
                }
            )
            self.save_job(failed)
        return len(jobs)
