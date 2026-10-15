"""Offline recovery and rollback rehearsals use only disposable fixture stores."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from graphmine_agent.api import build_runtime
from graphmine_agent.backup import restore_snapshot, snapshot_store, verify_snapshot
from graphmine_agent.database import Database
from graphmine_agent.datasets import DatasetLibrary, SaveDataset
from graphmine_agent.history import HistoryStore
from graphmine_agent.models import JobRecord, JobStatus
from test_queue_capacity import setup_runtime, wait_for_status


@pytest.mark.parametrize("external_history", [False, True])
async def test_backup_restore_and_rollback_preserve_inputs_and_computed_answers(
    settings, triangle_graph, tmp_path, external_history
):
    configured = replace(
        settings,
        history_directory=tmp_path / "external-history" if external_history else None,
    )
    runtime, plan = setup_runtime(configured, triangle_graph)
    runtime.runner.probe()
    snapshot = tmp_path / "backup"
    try:
        completed = await runtime.jobs.enqueue(plan)
        await runtime.jobs.start()
        await wait_for_status(runtime.database, [completed.id])
        await runtime.jobs.stop()
        saved_job = runtime.database.get_job(completed.id)
        result = runtime.database.get_result(saved_job.result_id)
        pending = [
            runtime.database.save_job(
                JobRecord(session_id=plan.session_id, plan=plan, status=status)
            )
            for status in (JobStatus.queued, JobStatus.running, JobStatus.interpreting)
        ]
        original_db = HistoryStore.digest(settings.database_path)
        source_file = runtime.database.get_file(plan.graph_id)
        manifest = snapshot_store(
            settings.data_root, snapshot, history_root=configured.history_root
        )
        assert verify_snapshot(snapshot) == manifest
        assert manifest["database"] == {
            "files": 1,
            "sessions": 1,
            "jobs": 4,
            "results": 1,
            "feedback": 0,
            "integrity": "ok",
        }
        restored = restore_snapshot(snapshot, tmp_path / "staging")
        database = Database(
            Path(restored["data_root"]) / "agent.sqlite3",
            HistoryStore(Path(restored["history_root"])),
        )
        assert database.get_result(result.id) == result
        assert database.get_job(completed.id) == saved_job
        file = database.get_file(plan.graph_id)
        assert Path(file.source_path).is_relative_to(tmp_path / "staging/data")
        assert Path(file.source_path).read_bytes() == triangle_graph
        assert json.loads(Path(file.canonical_path).read_text())["vertices"]
        for job in pending:
            assert database.get_job(job.id).status == JobStatus.cancelled
            assert database.get_job(job.id).error["code"] == "restored_not_resumed"
        assert not restored["services_started"]
        assert HistoryStore.digest(settings.database_path) == original_db
        assert Path(source_file.source_path).read_bytes() == triangle_graph
        # A local post-restore change is reversible by staging the intact backup
        # again. Neither restore overwrites the source or a previous restore.
        changed = result.model_copy(update={"summary": {"fixture_edit": True}})
        database.update_result(changed)
        rollback = restore_snapshot(snapshot, tmp_path / "rollback")
        rolled = Database(
            Path(rollback["data_root"]) / "agent.sqlite3",
            HistoryStore(Path(rollback["history_root"])),
        )
        assert rolled.get_result(result.id) == result
        assert database.get_result(result.id) == changed
        assert verify_snapshot(snapshot) == manifest
    finally:
        await runtime.jobs.stop()
        await runtime.agent.close()


async def test_backup_refuses_active_worker_and_existing_destination(
    settings, triangle_graph, tmp_path
):
    runtime, plan = setup_runtime(settings, triangle_graph)
    destination = tmp_path / "backup"
    try:
        await runtime.jobs.start()
        with pytest.raises(RuntimeError, match="already owned"):
            snapshot_store(settings.data_root, destination)
        assert not destination.exists()
        await runtime.jobs.stop()
        snapshot_store(settings.data_root, destination)
        with pytest.raises(FileExistsError):
            snapshot_store(settings.data_root, destination)
        with pytest.raises(FileExistsError):
            restore_snapshot(destination, settings.data_root)
        assert runtime.database.get_file(plan.graph_id)
        with pytest.raises(ValueError, match="outside"):
            snapshot_store(settings.data_root, settings.data_root / "nested")
    finally:
        await runtime.jobs.stop()
        await runtime.agent.close()


@pytest.mark.parametrize(
    "corruption", ["artifact", "missing", "extra", "symlink", "database"]
)
async def test_restore_rejects_corrupt_or_incomplete_snapshot(
    settings, triangle_graph, tmp_path, corruption
):
    runtime, plan = setup_runtime(settings, triangle_graph)
    snapshot = tmp_path / "backup"
    destination = tmp_path / "restore"
    try:
        snapshot_store(settings.data_root, snapshot)
        manifest = verify_snapshot(snapshot)
        record = runtime.database.get_file(plan.graph_id)
        source = (
            snapshot / "data" / Path(record.source_path).relative_to(settings.data_root)
        )
        if corruption == "artifact":
            source.write_bytes(b"corrupt")
        elif corruption == "missing":
            source.unlink()
        elif corruption == "extra":
            (snapshot / "extra").write_text("unexpected")
        elif corruption == "symlink":
            source.unlink()
            source.symlink_to(record.source_path)
        else:
            # Checksums alone are insufficient; verify the SQLite structure too.
            database = snapshot / "data/agent.sqlite3"
            database.write_bytes(b"invalid SQLite")
            manifest["files"]["data/agent.sqlite3"] = {
                "sha256": HistoryStore.digest(database),
                "size_bytes": database.stat().st_size,
            }
            (snapshot / "manifest.json").write_text(json.dumps(manifest))
        with pytest.raises((ValueError, sqlite3.DatabaseError)):
            restore_snapshot(snapshot, destination)
        assert not destination.exists()
    finally:
        await runtime.agent.close()


async def test_backup_preserves_empty_history_directory(settings, tmp_path):
    runtime = build_runtime(settings)
    try:
        snapshot_store(settings.data_root, tmp_path / "backup")
        restored = restore_snapshot(tmp_path / "backup", tmp_path / "staging")
        assert Path(restored["history_root"]).is_dir()
        assert restored["database"]["sessions"] == 0
    finally:
        await runtime.agent.close()


async def test_backup_restores_saved_datasets_and_rejects_corrupt_content(
    settings, triangle_graph, tmp_path
):
    runtime, plan = setup_runtime(settings, triangle_graph)
    try:
        library = DatasetLibrary(runtime)
        version = library.save(
            SaveDataset(name="Reusable triangle", file_id=plan.graph_id)
        )
        snapshot = tmp_path / "backup"
        snapshot_store(settings.data_root, snapshot)
        restored = restore_snapshot(snapshot, tmp_path / "restored")
        with sqlite3.connect(Path(restored["data_root"]) / "agent.sqlite3") as db:
            metadata, content = db.execute(
                "SELECT metadata,content FROM dataset_versions WHERE id=?",
                (version["id"],),
            ).fetchone()
            assert json.loads(metadata) == version
            assert json.loads(content)["vertices"]
        database = snapshot / "data/agent.sqlite3"
        with sqlite3.connect(database) as db:
            db.execute("UPDATE dataset_versions SET content=?", (b"{}",))
        # Even when the file inventory matches, the embedded content must match
        # its independently recorded dataset fingerprint and size.
        manifest = json.loads((snapshot / "manifest.json").read_text())
        manifest["files"]["data/agent.sqlite3"] = {
            "sha256": HistoryStore.digest(database),
            "size_bytes": database.stat().st_size,
        }
        (snapshot / "manifest.json").write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="Saved dataset integrity"):
            verify_snapshot(snapshot)
    finally:
        await runtime.agent.close()
