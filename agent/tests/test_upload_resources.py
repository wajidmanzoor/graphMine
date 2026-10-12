"""Stream integrity, resource limits and responsive API upload handling."""

from __future__ import annotations

import asyncio
import hashlib
import io
import threading
import tracemalloc
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from graphmine_agent.api import build_runtime, create_app
from graphmine_agent.graph_store import GraphStore, UploadError
from graphmine_agent.models import FileRole, SessionRecord


class ChunkSource:
    """Non-seekable input that never permits a full-buffer read."""

    def __init__(self, size):
        self.remaining = size
        self.consumed = 0

    def read(self, amount):
        assert 0 < amount <= 1024 * 1024
        data = b"x" * min(amount, self.remaining)
        self.remaining -= len(data)
        self.consumed += len(data)
        return data


def test_large_attachment_has_bounded_allocations_and_exact_source(
    settings, database, session
):
    size = 8 * 1024 * 1024
    store = GraphStore(replace(settings, max_upload_bytes=size), database)
    source = ChunkSource(size)
    tracemalloc.start()
    try:
        record = store.ingest_stream(
            session_id=session.id,
            role=FileRole.attachment,
            filename="opaque.bin",
            stream=source,
        )
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 4 * 1024 * 1024, (
        "Attachment copying must not allocate the complete file"
    )
    assert source.consumed == record.size_bytes == size
    expected = hashlib.sha256()
    for _ in range(8):
        expected.update(b"x" * 1024 * 1024)
    assert record.sha256 == expected.hexdigest()
    assert (
        store.database.history.digest(Path(record.source_path)) == expected.hexdigest()
    )
    assert database.get_file(record.id).size_bytes == size


def test_stream_limit_reads_only_one_excess_byte_and_removes_staging(
    settings, database, session
):
    store = GraphStore(replace(settings, max_upload_bytes=30), database)
    source = ChunkSource(10000)
    with pytest.raises(UploadError, match="exceeds 30 byte"):
        store.ingest_stream(
            session_id=session.id,
            role=FileRole.attachment,
            filename="too-large.bin",
            stream=source,
        )
    assert source.consumed == 31
    assert database.list_files(session.id) == []
    assert (
        list((settings.data_root / "sessions" / session.id / "files").iterdir()) == []
    )


@pytest.mark.parametrize(
    "role,filename,content,message",
    [
        (FileRole.graph, "empty.json", b"", "empty"),
        (FileRole.graph, "broken.json", b"{", "invalid JSON"),
        (FileRole.graph, "not-object.json", b"[]", "must be an object"),
        (FileRole.graph, "bad.csv", b"source,target\n\xff,b\n", "UTF-8"),
        (FileRole.graph, "bad.txt", b"\xff b\n", "UTF-8"),
        (FileRole.updates, "bad.json", b"[]", "updates input"),
        (FileRole.left_partition, "bad.json", b"{}", "left-partition input"),
    ],
)
def test_rejected_streams_preserve_caller_and_leave_no_file(
    graph_store, database, session, role, filename, content, message
):
    source = io.BytesIO(content)
    with pytest.raises(UploadError, match=message):
        graph_store.ingest_stream(
            session_id=session.id, role=role, filename=filename, stream=source
        )
    assert not source.closed
    assert database.list_files(session.id) == []
    assert (
        list(
            (
                graph_store.settings.data_root / "sessions" / session.id / "files"
            ).iterdir()
        )
        == []
    )


def test_streamed_csv_preserves_bom_unicode_and_quoted_newlines(graph_store, session):
    content = '\ufeffsource,target,source_label,note\r\n"a","b","Café","first\r\nsecond"\r\n'.encode()
    record = graph_store.ingest_stream(
        session_id=session.id,
        role=FileRole.graph,
        filename="records.csv",
        stream=io.BytesIO(content),
    )
    graph = graph_store.read_graph(record.id, session.id)
    assert graph["vertices"][0]["label"] == "Café"
    assert graph["edges"][0]["attributes"]["note"] == "first\r\nsecond"
    assert Path(record.source_path).read_bytes() == content
    assert record.sha256 == hashlib.sha256(content).hexdigest()


def test_streamed_edge_list_preserves_header_comments_weights_and_time(
    graph_store, session
):
    content = b"# comment\nsource target weight timestamp\n+1 2 1.5 10\n% another comment\n2 3 2.5 11\n"
    record = graph_store.ingest_stream(
        session_id=session.id,
        role=FileRole.graph,
        filename="records.txt",
        stream=io.BytesIO(content),
        directed=True,
    )
    graph = graph_store.read_graph(record.id, session.id)
    assert graph["edges"] == [
        {"id": 0, "source": 1, "target": 2, "weight": 1.5, "timestamp": 10},
        {"id": 1, "source": 2, "target": 3, "weight": 2.5, "timestamp": 11},
    ]
    assert (
        record.metadata.directed
        and record.metadata.has_weights
        and record.metadata.has_timestamps
    )


def test_failed_stream_read_removes_partial_source(graph_store, database, session):
    class Interrupted:
        calls = 0

        def read(self, amount):
            self.calls += 1
            if self.calls == 1:
                return b"partial"
            raise OSError("source disappeared")

    with pytest.raises(OSError, match="source disappeared"):
        graph_store.ingest_stream(
            session_id=session.id,
            role=FileRole.attachment,
            filename="broken.bin",
            stream=Interrupted(),
        )
    assert database.list_files(session.id) == []
    assert (
        list(
            (
                graph_store.settings.data_root / "sessions" / session.id / "files"
            ).iterdir()
        )
        == []
    )


@pytest.mark.parametrize("cancel_request", [0, 1, 2])
async def test_upload_work_does_not_block_requests_or_exceed_capacity(
    settings, monkeypatch, cancel_request
):
    configured = replace(settings, api_token=None, max_concurrent_uploads=1)
    runtime = build_runtime(configured)
    app = create_app(configured)
    app.state.runtime = runtime
    session = runtime.database.create_session(SessionRecord())
    original = runtime.graph_store.ingest_stream
    entered, release = threading.Event(), threading.Event()

    def stalled(**kwargs):
        entered.set()
        assert release.wait(5), "Test did not release the background upload"
        return original(**kwargs)

    monkeypatch.setattr(runtime.graph_store, "ingest_stream", stalled)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://cpu-fixture"
        ) as client:
            path = f"/api/sessions/{session.id}/files"
            first = asyncio.create_task(
                client.post(
                    path,
                    files={"file": ("first.bin", b"first")},
                    data={"role": "attachment"},
                )
            )
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                for _ in range(cancel_request):
                    first.cancel()
                    await asyncio.sleep(0.02)
                assert (
                    await asyncio.wait_for(client.get("/api/sessions"), 1)
                ).status_code == 200
                second = await asyncio.wait_for(
                    client.post(
                        path,
                        files={"file": ("second.bin", b"second")},
                        data={"role": "attachment"},
                    ),
                    1,
                )
                assert second.status_code == 429
                assert second.headers["retry-after"] == "2"
            finally:
                release.set()
                if cancel_request:
                    with pytest.raises(asyncio.CancelledError):
                        await first
                else:
                    assert (await first).status_code == 201
            third = await client.post(
                path,
                files={"file": ("third.bin", b"third")},
                data={"role": "attachment"},
            )
            assert third.status_code == 201
    finally:
        release.set()
        await runtime.agent.close()


def test_upload_concurrency_setting_must_be_positive(settings):
    with pytest.raises(ValueError, match="MAX_CONCURRENT_UPLOADS"):
        replace(settings, max_concurrent_uploads=0)
