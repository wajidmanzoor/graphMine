"""The evidence hash cache reuses a hash only while the file is untouched."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from graphmine_agent.analytics import AnalyticsService
from graphmine_agent.evidence_cache import install
from graphmine_agent.jobs import EventBus


def library():
    """The library's per-check hasher, as graphmine.evidence defines it."""
    hashed = []

    class FileHashes:
        def __init__(self):
            self.values, self.paths = {}, {}

        @staticmethod
        def identity(path):
            info = path.stat()
            return (
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )

        def __call__(self, path):
            path = Path(path)
            before = self.identity(path)
            previous = self.values.get(path)
            if previous is not None and previous[0] == before:
                return previous[1]
            hashed.append(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.values[path] = before, digest
            return digest

    return SimpleNamespace(_FileHashes=FileHashes), hashed


def worker(store):
    """One worker process: a fresh library module with the cache installed."""
    evidence, hashed = library()
    _, save = install(evidence, store)
    return evidence, hashed, save


def test_unchanged_files_are_hashed_once_across_workers(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text("<testsuite tests='1'/>")
    store = tmp_path / "cache" / "hashes.json"
    first, hashed, save = worker(store)
    digest = first._FileHashes()(report)
    save()
    assert hashed == [report] and store.is_file()
    assert oct(store.parent.stat().st_mode & 0o777) == "0o700"
    second, hashed, _ = worker(store)
    assert second._FileHashes()(report) == digest
    assert hashed == []


def test_any_write_is_hashed_again_even_with_the_old_size_and_time(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text("passed")
    store = tmp_path / "hashes.json"
    first, _, save = worker(store)
    first._FileHashes()(report)
    save()
    info = report.stat()
    report.write_text("failed")  # Same size.
    os.utime(report, ns=(info.st_atime_ns, info.st_mtime_ns))  # Same mtime.
    second, hashed, _ = worker(store)
    assert second._FileHashes()(report) == hashlib.sha256(b"failed").hexdigest()
    assert hashed == [report]


def test_a_damaged_cache_is_ignored(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text("passed")
    store = tmp_path / "hashes.json"
    for damaged in ("not json", json.dumps([1, 2]), json.dumps({str(report): [1]})):
        store.write_text(damaged)
        evidence, hashed, _ = worker(store)
        assert evidence._FileHashes()(report) == hashlib.sha256(b"passed").hexdigest()
        assert hashed == [report]


def test_replacing_a_file_invalidates_its_remembered_hash(tmp_path):
    report, replacement = tmp_path / "report.xml", tmp_path / "replacement.xml"
    report.write_text("passed")
    first, _, save = worker(tmp_path / "hashes.json")
    first._FileHashes()(report)
    save()
    info = report.stat()
    replacement.write_text("failed")
    os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns))
    replacement.replace(report)
    second, hashed, _ = worker(tmp_path / "hashes.json")
    assert second._FileHashes()(report) == hashlib.sha256(b"failed").hexdigest()
    assert hashed == [report]


async def test_native_workers_reuse_hashes_but_reject_changed_sources(
    settings, database, graph_store, tmp_path
):
    # Copy the source/report inventory to an isolated repository. Editing it
    # cannot change real builds, production sources or their evidence.
    source, repository = settings.repository_root, tmp_path / "repository"
    manifest = source / "catalog/native_execution_evidence.json"
    inventory = json.loads(manifest.read_text())
    paths = {"catalog/native_execution_evidence.json"}
    for build in inventory["builds"]:
        paths.update(build["sources"])
        for report in build["reports"]:
            paths.update(report["artifacts"])
            metadata = source / report["metadata"]
            if metadata.is_file():
                paths.update(json.loads(metadata.read_text())["source_files"])
    for name in paths:
        original, target = source / name, repository / name
        if original.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
    service = AnalyticsService(
        replace(
            settings,
            repository_root=repository,
            analytics_python=source / ".venv-analytics/bin/python",
        ),
        database,
        graph_store,
        EventBus(database),
    )
    first = await service._call({"command": "capabilities"})
    assert any(card["execution"]["cpu"] for card in first["operations"])
    cache = service.root / "cache/evidence-hashes.json"
    before = cache.stat().st_mtime_ns
    assert cache.stat().st_mode & 0o077 == 0
    second = await service._call({"command": "capabilities"})
    assert second == first
    assert cache.stat().st_mtime_ns == before  # The second worker only read it.
    changed = next((repository / "library/runtime").rglob("*.cpp"))
    stat = changed.stat()
    original = changed.read_bytes()
    changed.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    os.utime(changed, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    rejected = await service._call({"command": "capabilities"})
    assert rejected["verification_issues"]
    assert not any(any(card["execution"].values()) for card in rejected["operations"])
