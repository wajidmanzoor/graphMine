from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any

from .exceptions import GraphMineError


def external_id(value: Any) -> str | int:
    # bool and float collide with integer keys in Python; neither is an ID.
    if type(value) not in (str, int) or value == "":
        raise GraphMineError("Vertex and edge IDs must be nonempty strings or integers")
    return value


class Graph:
    """Canonical graph with lossless external IDs and explicit normalization.

    Algorithms use dense integer indices. Results are converted to original IDs
    at the boundary, including the distinct IDs 0 and "0" and large integers.
    The canonical input is retained independently of any algorithm projection.
    """

    def __init__(self, data: dict[str, Any]):
        if not isinstance(data, dict):
            raise GraphMineError("Graph input must be an object")
        if set(data) - {"graph", "vertices", "edges"}:
            raise GraphMineError("Unknown canonical graph fields")
        meta = data.get("graph")
        if not isinstance(meta, dict) or type(meta.get("directed")) is not bool:
            raise GraphMineError("graph.directed must explicitly be true or false")
        if not {"id", "directed", "allows_self_loops", "allows_parallel_edges"} <= set(
            meta
        ):
            raise GraphMineError(
                "Graph metadata needs id, directed, allows_self_loops and allows_parallel_edges"
            )
        if set(meta) - {
            "id",
            "directed",
            "allows_self_loops",
            "allows_parallel_edges",
            "attributes",
        }:
            raise GraphMineError("Unknown graph metadata fields")
        if not isinstance(meta["id"], str) or not meta["id"]:
            raise GraphMineError("graph.id must be a nonempty string")
        if any(
            type(meta[name]) is not bool
            for name in ("allows_self_loops", "allows_parallel_edges")
        ):
            raise GraphMineError(
                "Self-loop and parallel-edge policies must be booleans"
            )
        if "attributes" in meta and not isinstance(meta["attributes"], dict):
            raise GraphMineError("Graph attributes must be an object")
        if not isinstance(data.get("vertices"), list) or not isinstance(
            data.get("edges"), list
        ):
            raise GraphMineError("vertices and edges must be arrays")
        self._data = deepcopy(data)
        self._ids: list[str | int] = []
        self._indices: dict[str | int, int] = {}
        for vertex in self._data["vertices"]:
            if not isinstance(vertex, dict) or "id" not in vertex:
                raise GraphMineError("Every vertex needs an ID")
            if set(vertex) - {"id", "label", "type", "attributes"}:
                raise GraphMineError(
                    "Unknown vertex fields; put domain values in attributes"
                )
            if any(
                name in vertex and not isinstance(vertex[name], str)
                for name in ("label", "type")
            ) or (
                "attributes" in vertex and not isinstance(vertex["attributes"], dict)
            ):
                raise GraphMineError(
                    "Vertex label/type must be strings and attributes an object"
                )
            key = external_id(vertex["id"])
            if key in self._indices:
                raise GraphMineError(f"Duplicate vertex ID: {key!r}")
            self._indices[key] = len(self._ids)
            self._ids.append(key)
        edge_ids = set()
        seen = set()
        for edge in self._data["edges"]:
            if not isinstance(edge, dict) or not {"id", "source", "target"} <= set(
                edge
            ):
                raise GraphMineError("Every edge needs id, source, and target")
            if set(edge) - {
                "id",
                "source",
                "target",
                "weight",
                "timestamp",
                "type",
                "attributes",
            }:
                raise GraphMineError(
                    "Unknown edge fields; put domain values in attributes"
                )
            if ("type" in edge and not isinstance(edge["type"], str)) or (
                "attributes" in edge and not isinstance(edge["attributes"], dict)
            ):
                raise GraphMineError(
                    "Edge type must be a string and attributes an object"
                )
            if "timestamp" in edge and type(edge["timestamp"]) not in (str, int):
                raise GraphMineError(
                    "Timestamp must be a date-time string or integer epoch"
                )
            key = external_id(edge["id"])
            if key in edge_ids:
                raise GraphMineError(f"Duplicate edge ID: {key!r}")
            edge_ids.add(key)
            u, v = self.index(edge["source"]), self.index(edge["target"])
            if u == v and not meta.get("allows_self_loops", False):
                raise GraphMineError("Self-loop contradicts graph.allows_self_loops")
            pair = (u, v) if self.directed else tuple(sorted((u, v)))
            if pair in seen and not meta.get("allows_parallel_edges", False):
                raise GraphMineError(
                    "Parallel edges contradict graph.allows_parallel_edges"
                )
            seen.add(pair)
            if "weight" in edge:
                weight = edge["weight"]
                if type(weight) not in (int, float) or (
                    type(weight) is float and not math.isfinite(weight)
                ):
                    raise GraphMineError("Edge weights must be finite numbers")
        try:
            encoded = json.dumps(
                self._data, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise GraphMineError("Graph attributes must be finite JSON values") from exc
        self._fingerprint = hashlib.sha256(encoded.encode()).hexdigest()

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def directed(self) -> bool:
        return self._data["graph"]["directed"]

    @property
    def node_ids(self) -> tuple[str | int, ...]:
        return tuple(self._ids)

    @property
    def vertex_count(self) -> int:
        return len(self._ids)

    @property
    def edge_count(self) -> int:
        return len(self._data["edges"])

    def index(self, vertex_id: str | int) -> int:
        key = external_id(vertex_id)
        if key not in self._indices:
            raise GraphMineError(f"Unknown vertex ID: {key!r}")
        return self._indices[key]

    def vertex_id(self, index: int) -> str | int:
        return self._ids[index]

    def to_canonical(self) -> dict[str, Any]:
        return deepcopy(self._data)

    def to_networkx(
        self,
        *,
        direction: str = "preserve",
        parallel_edges: str = "reject",
        self_loops: str = "reject",
        weighted: bool = False,
        nonnegative: bool = False,
    ):
        import networkx as nx

        if direction not in {
            "preserve",
            "undirected",
            "require_undirected",
            "require_directed",
        }:
            raise GraphMineError("Unknown direction policy")
        if parallel_edges not in {"reject", "collapse", "sum", "min", "max"}:
            raise GraphMineError("Unknown parallel-edge policy")
        if self_loops not in {"reject", "drop", "keep"}:
            raise GraphMineError("Unknown self-loop policy")
        if direction == "require_undirected" and self.directed:
            raise GraphMineError(
                "This operation requires an undirected graph; project explicitly first"
            )
        if direction == "require_directed" and not self.directed:
            raise GraphMineError("This operation requires a directed graph")
        directed = self.directed and direction != "undirected"
        graph = (
            nx.DiGraph(backend="networkx") if directed else nx.Graph(backend="networkx")
        )
        for i, vertex in enumerate(self._data["vertices"]):
            graph.add_node(
                i, **deepcopy({k: v for k, v in vertex.items() if k != "id"})
            )
        for edge in self._data["edges"]:
            u, v = self.index(edge["source"]), self.index(edge["target"])
            weight = edge.get("weight", 1) if weighted else 1
            if nonnegative and weight < 0:
                raise GraphMineError("This operation requires nonnegative edge weights")
            if u == v:
                if self_loops == "reject":
                    raise GraphMineError("This operation does not accept self-loops")
                if self_loops == "drop":
                    continue
            if graph.has_edge(u, v):
                if parallel_edges == "reject":
                    raise GraphMineError(
                        "This operation needs an explicit parallel-edge aggregation"
                    )
                old = graph[u][v]["weight"]
                if parallel_edges == "sum":
                    graph[u][v]["weight"] = old + weight
                elif parallel_edges == "min":
                    graph[u][v]["weight"] = min(old, weight)
                elif parallel_edges == "max":
                    graph[u][v]["weight"] = max(old, weight)
                if type(graph[u][v]["weight"]) is float and not math.isfinite(
                    graph[u][v]["weight"]
                ):
                    raise GraphMineError("Aggregated edge weight overflowed")
            else:
                attrs = deepcopy(
                    {
                        k: v
                        for k, v in edge.items()
                        if k not in {"source", "target", "weight"}
                    }
                )
                graph.add_edge(u, v, **attrs, weight=weight)
        return graph

    def induced_subgraph(self, vertices: list[str | int]) -> Graph:
        indices = {self.index(v) for v in vertices}
        data = self.to_canonical()
        data["vertices"] = [v for i, v in enumerate(data["vertices"]) if i in indices]
        data["edges"] = [
            e
            for e in data["edges"]
            if self.index(e["source"]) in indices and self.index(e["target"]) in indices
        ]
        return Graph(data)

    @classmethod
    def from_edges(cls, edges, *, vertices=None, directed=False) -> Graph:
        rows = list(edges)
        if any(len(row) not in {2, 3} for row in rows):
            raise GraphMineError(
                "Edges must be (source, target) or (source, target, weight)"
            )
        ids = (
            list(vertices)
            if vertices is not None
            else list(dict.fromkeys(v for e in rows for v in e[:2]))
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
                        source=e[0],
                        target=e[1],
                        **({"weight": e[2]} if len(e) == 3 else {}),
                    )
                    for i, e in enumerate(rows)
                ],
            }
        )
