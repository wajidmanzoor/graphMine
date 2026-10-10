"""One request per isolated process. Protocol output is bounded by the parent."""

from __future__ import annotations

import contextlib
import json
import os
import sys

from .evidence import capabilities, require_workflow_evidence
from .exceptions import GraphMineError, ResourceLimit
from .workflows import execute_workflow, validate_workflow


def handle(request, emit):
    if not isinstance(request, dict) or set(request) - {
        "command",
        "plan",
        "inputs",
        "resume",
        "expected_hash",
    }:
        raise GraphMineError("Invalid worker request")
    command = request.get("command")
    root = os.environ.get("GRAPHMINE_REPOSITORY_ROOT")
    if not root:
        raise GraphMineError("The worker requires a configured repository root")
    caps = capabilities(root)
    if command == "capabilities":
        return caps
    if command not in ("validate", "run"):
        raise GraphMineError("Unknown worker command")
    checked = validate_workflow(request.get("plan"), request.get("inputs"))
    require_workflow_evidence(checked, caps)
    # Auto must not use GPU code lacking current GPU oracle evidence.
    gpu_verified = {
        card["id"] for card in caps["operations"] if card["execution"]["gpu"]
    }
    if command == "validate":
        return checked
    if request.get("expected_hash") != checked["workflow_hash"]:
        raise GraphMineError(
            "The reviewed workflow changed; validate and review it again"
        )
    return execute_workflow(
        request["plan"],
        request["inputs"],
        emit=emit,
        resume=request.get("resume"),
        verified_gpu_operations=gpu_verified,
    )


def main():
    # A dedicated fd survives redirection of native-library stdout. Library
    # diagnostics go to stderr and cannot corrupt the NDJSON event stream.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

    def emit(value):
        protocol.write(json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n")

    try:
        limit = int(
            os.environ.get("GRAPHMINE_WORKER_INPUT_BYTES", str(64 * 1024 * 1024))
        )
        raw = sys.stdin.buffer.read(limit + 1)
        if len(raw) > limit:
            raise ResourceLimit("Workflow input exceeds the worker byte budget")
        with contextlib.redirect_stdout(sys.stderr):
            result = handle(json.loads(raw), emit)
        emit({"event": "complete", "result": result})
    except (GraphMineError, ValueError, TypeError) as exc:
        emit(
            {
                "event": "error",
                "error": {
                    "code": getattr(exc, "code", "invalid_input"),
                    "message": str(exc),
                },
            }
        )
        return 2
    except Exception as exc:  # noqa: BLE001 - process boundary must emit a terminal failure
        print(f"Worker failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        emit(
            {
                "event": "error",
                "error": {
                    "code": "worker_failure",
                    "message": "The library worker failed; no successful result was recorded",
                },
            }
        )
        return 3
    finally:
        protocol.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
