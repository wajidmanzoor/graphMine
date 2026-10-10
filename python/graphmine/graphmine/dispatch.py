from __future__ import annotations

import hashlib
import importlib.metadata
import json
import time
from dataclasses import asdict
from pathlib import Path
from threading import RLock

from .contracts import Budget, WorkCounter
from .exceptions import BackendUnavailable, GraphMineError, UnsupportedOperation
from .graph import Graph
from .registry import algorithm

_backend_configuration_lock = RLock()


def implementation_hash() -> str:
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run(
    operation: str,
    graph: Graph | dict,
    *,
    parameters: dict | None = None,
    device: str = "auto",
    backend: str | None = None,
    budget: Budget | None = None,
) -> dict:
    """Run a declared library operation with explicit execution provenance.

    CPU always invokes NetworkX's own implementation. GPU requests never
    silently execute an unsupported CPU algorithm. Automatic selection may use
    CPU when the GPU capability is absent, preserving all requested parameters.
    """
    if device not in {"auto", "cpu", "gpu"}:
        raise GraphMineError("device must be auto, cpu, or gpu")
    if backend not in {None, "networkx", "cugraph"}:
        raise GraphMineError("Unknown backend")
    if (device == "cpu" and backend == "cugraph") or (
        device == "gpu" and backend == "networkx"
    ):
        raise GraphMineError("Backend conflicts with the requested device policy")
    if backend:
        device = "gpu" if backend == "cugraph" else "cpu"
    graph = graph if isinstance(graph, Graph) else Graph(graph)
    definition = algorithm(operation)
    args = definition.arguments(parameters or {})
    work = WorkCounter(budget or Budget())
    started = time.monotonic()
    selected = "networkx"
    provenance = {
        "id": "networkx",
        "device": "cpu",
        "library": definition.library,
        "version": importlib.metadata.version(definition.library),
    }
    if device != "cpu":
        from .backends import cugraph

        try:
            provenance = cugraph.prepare(operation, args, graph)
            selected = "cugraph"
        except (UnsupportedOperation, BackendUnavailable) as exc:
            if device == "gpu":
                raise
            provenance["selection_reason"] = str(exc)
    import networkx as nx

    # NetworkX 3.7 auto-configuration also redirects graph constructors and
    # internal helper calls. Explicit algorithm dispatch alone is insufficient
    # for CPU-only execution. Restore the caller's settings after each run;
    # workers use separate processes, and in-process calls share this lock.
    with (
        _backend_configuration_lock,
        nx.config.backend_priority(algos=[], generators=[], classes=[]),
    ):
        output = definition.function(graph, args, work, selected)
    work.tick(0)
    try:
        json.dumps(
            {
                "result": output.data,
                "ports": output.ports,
                "diagnostics": output.diagnostics,
            },
            allow_nan=False,
        )
    except (ValueError, TypeError) as exc:
        raise GraphMineError(
            "The algorithm returned non-finite or non-serializable results"
        ) from exc
    for port in output.ports.values():
        port.setdefault("graph_fingerprint", graph.fingerprint)
    return {
        "schema_version": "2.0.0",
        "operation": operation,
        "problem_id": definition.problem_id,
        "parameters": args,
        "requested_device": device,
        "backend": provenance,
        "implementation_sha256": implementation_hash(),
        "graph_fingerprint": graph.fingerprint,
        "complete": output.complete,
        "quality": output.quality,
        "result": output.data,
        "ports": output.ports,
        "diagnostics": output.diagnostics,
        "budget": asdict(work.budget),
        "elapsed_seconds": time.monotonic() - started,
    }
