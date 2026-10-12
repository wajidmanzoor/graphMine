"""Isolated CPU JSON loading pressure probe; no native computation or models."""

from __future__ import annotations

import argparse
import gc
import json
import tempfile
import time
import tracemalloc
from pathlib import Path

from graphmine_agent import execution
from graphmine_agent.config import Settings
from graphmine_agent.history import HistoryStore
from graphmine_agent.models import utc_now


def profile(arguments):
    if not 1 <= arguments.padding_mib <= 128:
        raise ValueError("Choose 1..128 MiB of synthetic payload padding")
    if arguments.output.exists():
        raise FileExistsError(arguments.output)
    settings = Settings.from_env(Path(__file__).resolve().parents[2])
    # Loading needs only settings, not a runtime, native probe or graph store.
    runner = object.__new__(execution.GraphMineRunner)
    runner.settings = settings
    with tempfile.TemporaryDirectory(prefix="graphmine-result-loading-") as temporary:
        path = Path(temporary) / "result.json"
        with path.open("wb") as handle:
            handle.write(
                b'{"ok":true,"provenance":{"test_double":true},"warnings":[],"output":{"cliques":[],"returned_count":0,"complete":true},"padding":"'
            )
            for _ in range(arguments.padding_mib):
                handle.write(b"x" * 1024 * 1024)
            handle.write(b'"}\n')
        report = {
            "version": "result-loading-pressure-v1",
            "created_at": utc_now().isoformat(),
            "label": arguments.label,
            "source_bytes": path.stat().st_size,
            "source_sha256": HistoryStore.digest(path),
            "configured_result_limit_bytes": getattr(
                settings, "max_result_bytes", None
            ),
            "execution_source_sha256": HistoryStore.digest(Path(execution.__file__)),
            "profiler_sha256": HistoryStore.digest(Path(__file__)),
            "scope": "Synthetic JSON with one large diagnostic string. Legacy mode reproduces the original inline JSON-loading expression; bounded mode calls the production loader. Traced allocation/elapsed measurements include tracing overhead. No native job, model, semantic accuracy or production-scale throughput claim.",
            "model_inference": "not_run",
            "native_execution": "not_run",
        }
        gc.collect()
        tracemalloc.start()
        started = time.perf_counter()
        try:
            if hasattr(runner, "read_result"):
                report["path_taken"] = "production_result_loader"
                payload = runner.read_result(path)
            else:
                report["path_taken"] = "legacy_inline_expression"
                payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["ok"] is True
            report["outcome"] = "loaded"
        except execution.ExecutionError as error:
            report["outcome"] = "rejected"
            report["error_code"] = error.code
        finally:
            report["seconds_with_tracing"] = time.perf_counter() - started
            report["python_peak_bytes"] = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--padding-mib", type=int, default=70)
    profile(parser.parse_args())
