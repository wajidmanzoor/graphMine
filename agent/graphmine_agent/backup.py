"""Offline snapshots and staged restores. Never starts or replaces a service."""

from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from .history import HistoryStore
from .models import JobRecord, JobStatus, StoredFile, utc_now
from .ownership import StoreLock

VERSION = "graphmine-offline-backup-v1"
_TRANSIENT = {
    "agent.sqlite3",
    "agent.sqlite3-wal",
    "agent.sqlite3-shm",
    "agent.sqlite3.worker.lock",
    ".cli.lock",
}


def _inventory(root: Path) -> dict[str, dict]:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError(f"Backup requires regular files and directories: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = {
                "size_bytes": path.stat().st_size,
                "sha256": HistoryStore.digest(path),
            }
    return files


def _copy_files(source: Path, destination: Path, *, skip: set[str] | None = None):
    inventory = _inventory(source)
    for path in source.rglob("*"):
        if path.is_dir():
            (destination / path.relative_to(source)).mkdir(
                parents=True, exist_ok=True, mode=0o700
            )
    for relative in inventory:
        if relative in (skip or set()):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(source / relative, target)
        target.chmod(0o600)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)


def _readonly(path: Path):
    return closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True))


def _file_path(value: str, original: Path, restored: Path) -> Path:
    path = Path(value)
    if (
        not path.is_absolute()
        or not path.is_relative_to(original)
        or ".." in path.parts
    ):
        raise ValueError("Stored input path lies outside the original data root")
    target = restored / path.relative_to(original)
    if not target.resolve().is_relative_to(restored.resolve()):
        raise ValueError("Stored input path escapes restored data root")
    return target


def _audit(database: Path, original: Path, data: Path) -> dict:
    with _readonly(database) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Backup SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Backup SQLite foreign key check failed")
        count = 0
        for (payload,) in connection.execute("SELECT payload FROM files"):
            record = StoredFile.model_validate_json(payload)
            source = _file_path(record.source_path, original, data)
            if (
                source.stat().st_size != record.size_bytes
                or HistoryStore.digest(source) != record.sha256
            ):
                raise ValueError(f"Uploaded source integrity mismatch: {record.id}")
            if (
                record.canonical_path
                and not _file_path(record.canonical_path, original, data).is_file()
            ):
                raise ValueError(f"Missing canonical graph: {record.id}")
            count += 1
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("sessions", "jobs", "results", "feedback")
        }
        return {"files": count, **counts, "integrity": "ok"}


def snapshot_store(
    data_root: Path, destination: Path, *, history_root: Path | None = None
) -> dict:
    """API must be stopped; the cooperative lock also rejects active new workers."""
    source, destination = data_root.resolve(), destination.resolve()
    history = (history_root or source / "history").resolve()
    database = source / "agent.sqlite3"
    if not database.is_file() or not history.is_dir():
        raise ValueError("An existing database and history directory are required")
    if destination.resolve().is_relative_to(
        source
    ) or destination.resolve().is_relative_to(history):
        raise ValueError("Backup destination must be outside the source store/history")
    with StoreLock(database):
        destination.mkdir(mode=0o700)  # Deliberately refuse any existing path.
        try:
            _copy_files(source, destination / "data", skip=_TRANSIENT)
            with (
                _readonly(database) as origin,
                closing(sqlite3.connect(destination / "data/agent.sqlite3")) as target,
            ):
                origin.backup(target)
                target.execute("PRAGMA journal_mode = DELETE")
            internal = history.is_relative_to(source)
            if not internal:
                _copy_files(history, destination / "history")
            manifest = {
                "version": VERSION,
                "created_at": utc_now().isoformat(),
                "source_data_root": str(source),
                "source_history_root": str(history),
                "history_relative": str(history.relative_to(source))
                if internal
                else None,
                "files": _inventory(destination),
                "database": _audit(
                    destination / "data/agent.sqlite3", source, destination / "data"
                ),
                "scope": "Offline store snapshot with integrity hashes; hashes do not authenticate an untrusted backup. Environment secrets/model weights are not included.",
            }
            HistoryStore.write(destination / "manifest.json", manifest)
            return manifest
        except BaseException:
            shutil.rmtree(destination)
            raise


def verify_snapshot(snapshot: Path) -> dict:
    snapshot = snapshot.resolve()
    manifest = json.loads((snapshot / "manifest.json").read_text())
    if manifest.get("version") != VERSION:
        raise ValueError("Unsupported backup version")
    actual = _inventory(snapshot)
    actual.pop("manifest.json")
    if actual != manifest["files"]:
        raise ValueError("Backup inventory/hash mismatch")
    audit = _audit(
        snapshot / "data/agent.sqlite3",
        Path(manifest["source_data_root"]),
        snapshot / "data",
    )
    if audit != manifest["database"]:
        raise ValueError("Backup database inventory mismatch")
    return manifest


def restore_snapshot(snapshot: Path, destination: Path) -> dict:
    """Restore into a NEW directory. Pending work is cancelled, never replayed."""
    manifest = verify_snapshot(snapshot)
    snapshot = snapshot.resolve()
    destination = destination.resolve()
    if destination.resolve().is_relative_to(snapshot.resolve()):
        raise ValueError("Restore destination must be outside the snapshot")
    original = Path(manifest["source_data_root"])
    destination.mkdir(mode=0o700)
    try:
        _copy_files(snapshot / "data", destination / "data")
        relative = manifest["history_relative"]
        if relative is None:
            _copy_files(snapshot / "history", destination / "history")
            history = destination / "history"
        else:
            # Only use a verified member directory; a manifest cannot select an
            # arbitrary path as the restored history destination.
            history = destination / "data" / relative
            if (
                not history.resolve().is_relative_to((destination / "data").resolve())
                or not history.is_dir()
            ):
                raise ValueError("Invalid restored history location")
        data = destination / "data"
        database = data / "agent.sqlite3"
        cancelled = []
        with closing(sqlite3.connect(database)) as connection, connection:
            for identifier, payload in connection.execute(
                "SELECT id,payload FROM files"
            ).fetchall():
                record = json.loads(payload)
                for field in ("source_path", "canonical_path"):
                    if record[field]:
                        record[field] = str(_file_path(record[field], original, data))
                connection.execute(
                    "UPDATE files SET payload=? WHERE id=?",
                    (json.dumps(record), identifier),
                )
            for identifier, payload in connection.execute(
                "SELECT id,payload FROM jobs WHERE status IN ('queued','running','interpreting')"
            ).fetchall():
                job = JobRecord.model_validate_json(payload).model_copy(
                    update={
                        "status": JobStatus.cancelled,
                        "finished_at": utc_now(),
                        "error": {
                            "code": "restored_not_resumed",
                            "message": "Pending work was cancelled during offline restore; submit a new job after review.",
                        },
                    }
                )
                connection.execute(
                    "UPDATE jobs SET status=?,payload=?,updated_at=? WHERE id=?",
                    (
                        job.status.value,
                        job.model_dump_json(),
                        job.finished_at.isoformat(),
                        identifier,
                    ),
                )
                cancelled.append(identifier)
        report = {
            "version": VERSION,
            "restored_at": utc_now().isoformat(),
            "snapshot_manifest_sha256": HistoryStore.digest(snapshot / "manifest.json"),
            "data_root": str(data),
            "history_root": str(history),
            "cancelled_pending_job_ids": cancelled,
            "database": _audit(database, data, data),
            "services_started": False,
            "scope": "Staged restore. Operational file paths rebased; archived history/commands retain original provenance. No production directory or model configuration changed.",
        }
        HistoryStore.write(destination / "restore.json", report)
        return report
    except BaseException:
        shutil.rmtree(destination)
        raise
