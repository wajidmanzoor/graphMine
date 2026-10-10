"""Bounded process transport to the native cuDF reader and graph constructor."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path


class IngestionError(ValueError):
    pass


def read_delimited_graph(settings, path, *, directed, source_column, target_column):
    binary = settings.native_runtime_binary or (
        settings.repository_root / "library/build/runtime/graphmine-native"
    )
    if not binary.is_file():
        raise IngestionError(
            "cuDF ingestion requires a libcudf-enabled graphmine-native binary; "
            "set GRAPHMINE_NATIVE_BINARY to its path."
        )
    request = {
        "command": "read_graph",
        "path": str(Path(path).resolve()),
        "directed": directed,
        "id_type": "canonical",
        "gpu_device": 0,
        "max_rows": 100000,
    }
    for key, value in (
        ("source_column", source_column),
        ("target_column", target_column),
    ):
        if value is not None:
            request[key] = value
    environment = os.environ.copy()
    if settings.graph_gpu_uuid:
        environment["CUDA_VISIBLE_DEVICES"] = settings.graph_gpu_uuid
    # Keep CUDA contexts and blocking native calls out of the web process.
    # Files bound Python memory use; the native profile also bounds rows/cells.
    with tempfile.TemporaryDirectory(prefix="graphmine-ingestion-") as temporary:
        output = Path(temporary) / "output.json"
        errors = Path(temporary) / "stderr.txt"
        try:
            with output.open("wb") as stdout, errors.open("wb") as stderr:
                process = subprocess.Popen(
                    [str(binary), "request"],
                    stdin=subprocess.PIPE,
                    stdout=stdout,
                    stderr=stderr,
                    env=environment,
                    start_new_session=True,
                )
                try:
                    process.communicate(
                        json.dumps(request, allow_nan=False).encode(),
                        timeout=min(settings.job_timeout_seconds, 60),
                    )
                except subprocess.TimeoutExpired as error:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate()
                    raise IngestionError(
                        "Native cuDF ingestion exceeded its deadline"
                    ) from error
        except OSError as error:
            raise IngestionError(
                f"Cannot launch native cuDF ingestion: {error}"
            ) from error
        if output.stat().st_size > settings.max_result_bytes:
            raise IngestionError(
                "Native ingestion result exceeds the configured byte limit"
            )
        try:
            response = json.loads(output.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as error:
            raise IngestionError(
                "Native cuDF ingestion returned no valid result"
            ) from error
        if isinstance(response, dict) and isinstance(response.get("error"), dict):
            raise IngestionError(
                response["error"].get("message", "Native ingestion failed")
            )
        provenance = response.get("provenance") if isinstance(response, dict) else None
        if (
            process.returncode != 0
            or not isinstance(response, dict)
            or response.get("complete") is not True
            or not isinstance(response.get("graph"), dict)
            or not isinstance(provenance, dict)
            or provenance.get("reader") != "libcudf"
            or provenance.get("python_runtime_required") is not False
        ):
            raise IngestionError(
                "Native cuDF ingestion did not produce a complete graph"
            )
        return response["graph"]
