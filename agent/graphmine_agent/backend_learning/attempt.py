"""One killable native call, within the supervising workflow's process group."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from .hardware import process_tree


def stop_tree(pid):
    """Freeze a child before discovering/killing descendants; never signal us.

    Attempt children keep the workflow's process group, so the outer supervisor
    can also kill the whole workflow if this Python worker is interrupted.
    """
    if pid == os.getpid():
        raise ValueError("Cannot stop the supervising worker")
    frozen = set()
    while True:
        descendants = process_tree(pid) - frozen
        if not descendants:
            break
        for child in descendants:
            try:
                os.kill(child, signal.SIGSTOP)
            except ProcessLookupError:
                pass
        frozen.update(descendants)
    for child in sorted(frozen - {pid}, reverse=True):
        try:
            os.kill(child, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run(problem, graph, *, parameters=None, device="auto", backend=None, budget=None,
        gpu_device=0, allowed_backends=None, response_limit=None):
    from graphmine.contracts import Budget
    from graphmine.dispatch import implementation_hash
    from graphmine.exceptions import GraphMineError

    budget = budget or Budget()
    start = time.monotonic()
    request = dict(problem=problem, graph=graph.to_canonical() if hasattr(graph, "to_canonical") else graph,
                   parameters=parameters or {}, device=device, backend=backend or "auto", budget=asdict(budget),
                   gpu_device=gpu_device, allowed_backends=allowed_backends,
                   expected_implementation=implementation_hash(), response_limit=response_limit)
    raw = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    env = dict(os.environ)
    root = Path(__file__).resolve().parents[3]
    native_root = Path(env.get("GRAPHMINE_REPOSITORY_ROOT", str(root)))
    env["PYTHONPATH"] = os.pathsep.join((str(root / "agent"), str(native_root / "python/graphmine")))
    env["GRAPHMINE_ATTEMPT_INPUT_BYTES"] = str(len(raw))
    fds = tuple(int(value) for value in env.get("GRAPHMINE_GPU_LEASE_FDS", "").split(",") if value)
    process = subprocess.Popen([sys.executable, "-m", "graphmine_agent.backend_learning.attempt"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, pass_fds=fds)
    try:
        remaining = budget.timeout_seconds - (time.monotonic() - start) if budget.timeout_seconds is not None else None
        if remaining is not None and remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, budget.timeout_seconds)
        output, _ = process.communicate(raw, timeout=remaining)
        if response_limit is not None and len(output) > response_limit:
            error = GraphMineError("Native attempt exceeded the response byte limit")
            error.code = "resource_limit"
            raise error
        try:
            reply = json.loads(output)
        except (ValueError, TypeError) as error:
            failure = GraphMineError("Native attempt exited without a valid result")
            failure.code = "backend_failure"
            raise failure from error
        if "error" in reply:
            error = GraphMineError(reply["error"]["message"])
            error.code = reply["error"]["code"]
            raise error
        if process.returncode or not isinstance(reply.get("result"), dict):
            raise GraphMineError("Native attempt exited without a result")
        return reply["result"]
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("Native attempt exceeded its execution deadline") from error
    finally:
        if process.returncode is None:
            stop_tree(process.pid)
        process.wait()


def main():
    from graphmine.contracts import Budget
    from graphmine.dispatch import implementation_hash, run as native_run

    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    limit = None
    try:
        expected = int(os.environ["GRAPHMINE_ATTEMPT_INPUT_BYTES"])
        raw = sys.stdin.buffer.read(expected + 1)
        if len(raw) != expected:
            raise ValueError("Native attempt input length changed")
        request = json.loads(raw)
        limit = request.pop("response_limit")
        if implementation_hash() != request.pop("expected_implementation"):
            raise ValueError("Native implementation changed before execution")
        request["budget"] = Budget(**request["budget"])
        result = native_run(**request)
        reply = {"result": result}
    except BaseException as error:
        reply = {"error": {"code": getattr(error, "code", "out_of_memory" if isinstance(error, MemoryError) else "worker_failure"),
                            "message": str(error)}}
    try:
        encoded = json.dumps(reply, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if limit is not None and len(encoded.encode()) > limit:
            encoded = json.dumps({"error": {"code": "resource_limit", "message": "Native attempt exceeded the response byte limit"}})
        protocol.write(encoded + "\n")
    finally:
        protocol.close()


if __name__ == "__main__":
    main()
