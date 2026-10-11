"""Public execution is a JSON transport to the C++/CUDA runtime."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from .contracts import Budget
from .exceptions import GraphMineError
from .native import NativeError, NativeLibrary, library_path


@lru_cache(maxsize=4)
def _library(path):
    return NativeLibrary(path)


def native_library():
    try:
        return _library(library_path())
    except (NativeError, OSError) as exc:
        error = GraphMineError(str(exc))
        error.code = getattr(exc, "code", "backend_unavailable")
        raise error from exc


def native_request(request):
    try:
        return native_library().request(request)
    except (NativeError, ValueError, TypeError) as exc:
        error = GraphMineError(str(exc))
        error.code = getattr(exc, "code", "invalid_input")
        raise error from exc


def implementation_hash():
    return native_library().catalog()["implementation_sha256"]


def execution_environment():
    library = native_library()
    with Path(library.path).open("rb") as handle:
        binary = hashlib.file_digest(handle, "sha256").hexdigest()
    source = hashlib.sha256()
    root = Path(__file__).parent
    for name in (
        "dispatch.py",
        "native/__init__.py",
        "native_inputs.py",
        "contracts.py",
        "registry.py",
        "workflows.py",
        "worker.py",
        "evidence.py",
    ):
        source.update(name.encode())
        source.update((root / name).read_bytes())
    return {
        "native_abi": 1,
        "native_library_sha256": binary,
        "wrapper_sha256": source.hexdigest(),
        "python": sys.version,
    }


def run(
    operation,
    graph,
    *,
    parameters=None,
    device="auto",
    backend=None,
    budget=None,
    gpu_device=0,
    allowed_backends=None,
):
    """Run the declared native profile without a Python algorithm fallback."""
    if budget is not None and not isinstance(budget, Budget):
        raise GraphMineError("budget must be a Budget")
    if hasattr(graph, "to_canonical"):
        graph = graph.to_canonical()
    request = {
        "command": "run",
        "operation": operation,
        "graph": graph,
        "parameters": {} if parameters is None else parameters,
        "device": device,
        "backend": "auto" if backend is None else backend,
        "gpu_device": gpu_device,
        "budget": asdict(budget or Budget()),
    }
    if allowed_backends is not None:
        request["allowed_backends"] = allowed_backends
    return native_request(request)
