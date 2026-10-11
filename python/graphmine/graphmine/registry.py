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
    input_validator=None,
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
            input_validator,
        )
        return function

    return decorate


def _load():
    global _loaded
    if not _loaded:
        from .algorithms import (  # noqa: F401
            alignment,
            anomalies,
            bipartite,
            centrality,
            construction,
            density,
            entity_resolution,
            enumeration,
            frequent_patterns,
            graph_comparison,
            hypergraphs,
            influence,
            layout,
            local_community,
            null_models,
            optimization,
            partitioning,
            paths,
            patterns,
            queries,
            sampling,
            similarity,
            sparsification,
            spectral,
            steiner,
            structure,
            temporal,
            topology,
            traversal,
        )

        _loaded = True


def reference_algorithm(operation: str) -> Algorithm:
    _load()
    if operation not in _algorithms:
        raise UnsupportedOperation(f"No executable integration for {operation!r}")
    return _algorithms[operation]


def reference_algorithms(*, family: str | None = None) -> list[dict]:
    _load()
    return [
        a.card()
        for a in sorted(_algorithms.values(), key=lambda a: (a.family, a.id))
        if family is None or a.family == family
    ]


def reference_families() -> list[dict]:
    values = reference_algorithms()
    return [
        {"id": name, "operation_count": sum(a["family"] == name for a in values)}
        for name in sorted({a["family"] for a in values})
    ]


class NativeAlgorithm:
    """Workflow view of the native card; the core owns argument validation."""

    def __init__(self, card):
        from .contracts import Parameter

        self._card = card
        for name in (
            "id",
            "problem_id",
            "family",
            "title",
            "description",
            "input_kind",
            "quality",
        ):
            setattr(self, name, card[name])
        self.library = "cpp"
        self.input_validator = None
        self.parameters = {
            name: Parameter(
                **{
                    key: value
                    for key, value in spec.items()
                    if key in Parameter.__dataclass_fields__
                }
            )
            for name, spec in card["parameters"].items()
        }

    def card(self):
        from copy import deepcopy

        return deepcopy(self._card)

    def arguments(self, supplied):
        from .dispatch import native_request

        return native_request(
            {"command": "validate", "operation": self.id, "parameters": supplied}
        )["parameters"]


def algorithms(*, family=None):
    from .dispatch import native_library

    return native_library().list_algorithms(family=family)


def algorithm(operation):
    for card in algorithms():
        if card["id"] == operation:
            return NativeAlgorithm(card)
    raise UnsupportedOperation(f"No native runtime integration for {operation!r}")


def families():
    from .dispatch import native_library

    return native_library().list_families()
