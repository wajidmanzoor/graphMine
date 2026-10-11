"""Immutable JSON input handles validated and fingerprinted by the native core."""

from copy import deepcopy

from .dispatch import native_request
from .exceptions import GraphMineError
from .graph import external_id


class _Input:
    def __init__(self, data):
        if hasattr(data, "to_canonical"):
            data = data.to_canonical()
        self._data = deepcopy(data)
        self._metadata = native_request(
            {"command": "inspect_input", "input_kind": self.kind, "input": self._data}
        )
        self._indices = {vertex: i for i, vertex in enumerate(self.node_ids)}

    @property
    def fingerprint(self):
        return self._metadata["input_fingerprint"]

    def to_canonical(self):
        return deepcopy(self._data)

    @property
    def node_ids(self):
        records = self._data.get("vertices", self._data.get("vectors", []))
        return tuple(row["id"] for row in records)

    @property
    def vertex_count(self):
        return self._metadata["vertex_count"]

    def index(self, value):
        value = external_id(value)
        try:
            return self._indices[value]
        except KeyError as exc:
            raise GraphMineError(f"Unknown vertex ID: {value!r}") from exc

    def vertex_id(self, index):
        return self.node_ids[index]


class Graph(_Input):
    kind = "graph"

    @classmethod
    def from_edges(cls, edges, *, vertices=None, directed=False):
        rows = list(edges)
        if any(len(row) not in {2, 3} for row in rows):
            raise GraphMineError(
                "Edges must be (source, target) or (source, target, weight)"
            )
        ids = (
            list(vertices)
            if vertices is not None
            else list(dict.fromkeys(external_id(v) for edge in rows for v in edge[:2]))
        )
        return cls(
            {
                "graph": {
                    "id": "graph",
                    "directed": directed,
                    "allows_self_loops": False,
                    "allows_parallel_edges": False,
                },
                "vertices": [{"id": v} for v in ids],
                "edges": [
                    dict(
                        id=i,
                        source=edge[0],
                        target=edge[1],
                        **({"weight": edge[2]} if len(edge) == 3 else {}),
                    )
                    for i, edge in enumerate(rows)
                ],
            }
        )

    @property
    def directed(self):
        return self._data["graph"]["directed"]

    @property
    def edge_count(self):
        return self._metadata["edge_count"]


class GraphCollection(_Input):
    kind = "graph_collection"

    @property
    def graph_count(self):
        return self._metadata["graph_count"]

    @property
    def graphs(self):
        return tuple(Graph(value) for value in self._data["graphs"])


class FeatureVectors(_Input):
    kind = "feature_vectors"


class Hypergraph(_Input):
    kind = "hypergraph"


def load_input(data, kind):
    types = {
        cls.kind: cls for cls in (Graph, GraphCollection, FeatureVectors, Hypergraph)
    }
    if kind not in types:
        raise GraphMineError("Unknown input kind")
    if isinstance(data, types[kind]):
        return data
    if isinstance(data, _Input):
        raise GraphMineError(f"This operation requires {kind} input")
    return types[kind](data)
