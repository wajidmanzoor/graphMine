from __future__ import annotations

from .contracts import Algorithm
from .exceptions import UnsupportedOperation

_algorithms: dict[str, Algorithm] = {}
_loaded = False


def register(
    *,
    id,
    problem_id,
    family,
    title,
    description,
    parameters=None,
    library="networkx",
    quality="exact",
    references=(),
    input_kind="graph",
):
    def decorate(function):
        if id in _algorithms:
            raise RuntimeError(f"Duplicate algorithm: {id}")
        _algorithms[id] = Algorithm(
            id,
            problem_id,
            family,
            title,
            description,
            parameters or {},
            function,
            library,
            quality,
            tuple(references),
            input_kind,
        )
        return function

    return decorate


def _load():
    global _loaded
    if not _loaded:
        from .algorithms import (  # noqa: F401
            bipartite,
            centrality,
            construction,
            density,
            enumeration,
            hypergraphs,
            local_community,
            null_models,
            optimization,
            partitioning,
            paths,
            patterns,
            sampling,
            similarity,
            spectral,
            structure,
            temporal,
            topology,
            traversal,
        )

        _loaded = True


def algorithm(operation: str) -> Algorithm:
    _load()
    if operation not in _algorithms:
        raise UnsupportedOperation(f"No executable integration for {operation!r}")
    return _algorithms[operation]


def algorithms(*, family: str | None = None) -> list[dict]:
    _load()
    return [
        a.card()
        for a in sorted(_algorithms.values(), key=lambda a: (a.family, a.id))
        if family is None or a.family == family
    ]


def families() -> list[dict]:
    values = algorithms()
    return [
        {"id": name, "operation_count": sum(a["family"] == name for a in values)}
        for name in sorted({a["family"] for a in values})
    ]
