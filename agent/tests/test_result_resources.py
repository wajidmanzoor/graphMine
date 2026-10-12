"""Bounded native-result loading and recovery through an independent next job."""

from __future__ import annotations

import json
import stat
import textwrap
import tracemalloc
from dataclasses import replace
from pathlib import Path

import pytest
from graphmine_agent.execution import ExecutionError, GraphMineRunner
from graphmine_agent.models import JobStatus
from graphmine_agent.planning import PlanValidator
from test_queue_capacity import setup_runtime, wait_for_status


def loader(settings, catalog, graph_store, *, limit=1024):
    return GraphMineRunner(
        replace(settings, max_result_bytes=limit),
        catalog,
        graph_store,
        PlanValidator(catalog),
    )


def test_oversized_result_rejected_before_allocating_and_artifact_preserved(
    settings, catalog, graph_store, tmp_path
):
    path = tmp_path / "large-result.json"
    with path.open("wb") as handle:
        handle.write(b'{"padding":"')
        for _ in range(8):
            handle.write(b"x" * 1024 * 1024)
        handle.write(b'"}')
    original = path.stat().st_size
    runner = loader(settings, catalog, graph_store)
    tracemalloc.start()
    try:
        with pytest.raises(ExecutionError) as error:
            runner.read_result(path)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert error.value.code == "result_too_large"
    assert peak < 64 * 1024
    assert path.stat().st_size == original


def test_exact_result_byte_limit_accepts_utf8_without_overallocating(
    settings, catalog, graph_store, tmp_path
):
    content = json.dumps({"text": "Café 🐱", "ok": True}, ensure_ascii=False).encode()
    path = tmp_path / "result.json"
    path.write_bytes(content)
    assert loader(settings, catalog, graph_store, limit=len(content)).read_result(
        path
    ) == {"text": "Café 🐱", "ok": True}
    with pytest.raises(ExecutionError) as error:
        loader(settings, catalog, graph_store, limit=len(content) - 1).read_result(path)
    assert error.value.code == "result_too_large"
    tracemalloc.start()
    try:
        loader(settings, catalog, graph_store, limit=64 * 1024 * 1024).read_result(path)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 256 * 1024, (
        "A small result must not allocate the entire configured maximum"
    )


@pytest.mark.parametrize(
    "content",
    [b"{", b"\xff", b"[]"],
    ids=["malformed", "invalid-utf8", "wrong-root"],
)
def test_invalid_result_has_a_structured_failure(
    settings, catalog, graph_store, tmp_path, content
):
    path = tmp_path / "result.json"
    path.write_bytes(content)
    with pytest.raises(ExecutionError) as error:
        loader(settings, catalog, graph_store, limit=10000).read_result(path)
    assert error.value.code == "invalid_result"


def test_recursive_result_has_a_structured_failure(
    settings, catalog, graph_store, tmp_path
):
    # The C JSON decoder's limit can differ from Python's recursion limit.
    for exponent in range(9, 17):
        depth = 2**exponent
        content = b'{"nested":' + b"[" * depth + b"0" + b"]" * depth + b"}"
        try:
            json.loads(content)
        except RecursionError:
            break
    else:
        pytest.skip("This decoder accepted every bounded depth probe")
    path = tmp_path / "recursive-result.json"
    path.write_bytes(content)
    with pytest.raises(ExecutionError) as error:
        loader(settings, catalog, graph_store, limit=len(content)).read_result(path)
    assert error.value.code == "invalid_result"


def test_growing_result_is_rejected_instead_of_reading_unbounded_data(
    settings, catalog, graph_store, tmp_path, monkeypatch
):
    path = tmp_path / "result.json"
    path.write_bytes(b'{"ok":true}')
    original_open = Path.open

    class GrowingFile:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def fileno(self):
            return self.handle.fileno()

        def tell(self):
            return self.handle.tell()

        def read(self, size):
            with original_open(path, "ab") as writer:
                writer.write(b" " * 2048)
            assert size == len(b'{"ok":true}') + 1
            return self.handle.read(size)

    def opened(self, mode="r", *args, **kwargs):
        handle = original_open(self, mode, *args, **kwargs)
        return GrowingFile(handle) if self == path and mode == "rb" else handle

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(ExecutionError, match="changed while"):
        loader(settings, catalog, graph_store).read_result(path)


def test_stderr_tail_does_not_load_the_full_log(tmp_path):
    path = tmp_path / "stderr.log"
    suffix = "🐱" * 8000
    with path.open("wb") as handle:
        for _ in range(4):
            handle.write(b"x" * 1024 * 1024)
        handle.write(suffix.encode())
    tracemalloc.start()
    try:
        assert GraphMineRunner.stderr_tail(path) == suffix
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 256 * 1024


async def test_oversized_job_fails_explicitly_and_next_independent_job_completes(
    settings, triangle_graph, tmp_path
):
    binary = tmp_path / "sized-result-fixture"
    binary.write_text(
        textwrap.dedent("""\
        #!/usr/bin/env python3
        import json
        import sys
        from pathlib import Path
        if sys.argv[1] == "list":
            print(json.dumps({"library_version": "1.0.0", "operation_count": 1, "validated_backend_count": 1, "compiled_backend_count": 1, "operations": [{"id": "maximal-cliques", "backends": [{"id": "rdmce", "compiled": True, "validated": True}]}]}))
        elif sys.argv[1] == "run":
            output = Path(sys.argv[sys.argv.index("--output") + 1])
            payload = {"ok": True, "provenance": {"backend": "rdmce", "test_double": True}, "warnings": [], "output": {"cliques": [[0,1,2]], "returned_count": 1, "complete": True}}
            if "--minimum-clique-size" in sys.argv and sys.argv[sys.argv.index("--minimum-clique-size") + 1] == "2":
                payload["padding"] = "x" * 4096
            output.write_text(json.dumps(payload))
        else:
            raise SystemExit(2)
    """)
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    runtime, plan = setup_runtime(
        replace(settings, graphmine_binary=binary, max_result_bytes=1024),
        triangle_graph,
    )
    runtime.jobs.result_handler = None
    first = await runtime.jobs.enqueue(
        plan.model_copy(update={"parameters": {"minimum_clique_size": 2}})
    )
    second = await runtime.jobs.enqueue(
        plan.model_copy(update={"parameters": {"minimum_clique_size": 3}})
    )
    try:
        await runtime.jobs.start()
        await wait_for_status(runtime.database, [first.id], status=JobStatus.failed)
        await wait_for_status(runtime.database, [second.id])
        failed = runtime.database.get_job(first.id)
        assert failed.error["code"] == "result_too_large"
        assert failed.result_id is None
        artifact = runtime.settings.workspaces_root / first.id / "result.json"
        assert artifact.stat().st_size > runtime.settings.max_result_bytes
        assert runtime.database.get_job(second.id).result_id
        for job, expected in ((first, "failed"), (second, "completed")):
            timings_path = runtime.settings.workspaces_root / job.id / "timings.json"
            timings = json.loads(timings_path.read_text())
            assert timings["job_id"] == job.id and timings["status"] == expected
            assert timings["queue_wait_seconds"] >= 0
            assert timings["total_active_seconds"] >= sum(
                timings["stages_seconds"].values()
            )
            assert timings["stages_seconds"]["execution"] > 0
            archived = (
                runtime.database.history.session_path(plan.session_id)
                / "jobs"
                / job.id
                / "timings.json"
            )
            assert json.loads(archived.read_text()) == timings
        assert (
            "result_validation"
            not in json.loads(
                (
                    runtime.settings.workspaces_root / first.id / "timings.json"
                ).read_text()
            )["stages_seconds"]
        )
        assert "result_storage" in timings["stages_seconds"]
    finally:
        await runtime.jobs.stop()
        await runtime.agent.close()


def test_result_limit_setting_must_be_positive(settings):
    with pytest.raises(ValueError, match="MAX_RESULT_BYTES"):
        replace(settings, max_result_bytes=0)
