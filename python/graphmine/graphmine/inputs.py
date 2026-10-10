"""Typed inputs for operations whose mathematical data is not an ordinary graph."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy

from .exceptions import GraphMineError
from .graph import Graph, external_id


def finite_number(value, name, *, nonnegative=False):
    if type(value) not in (int, float) or (
        type(value) is float and not math.isfinite(value)
    ):
        raise GraphMineError(f"{name} must be a finite number")
    if nonnegative and value < 0:
        raise GraphMineError(f"{name} must be nonnegative")
    return value


class _VertexInput:
    def _finish(self, data, ids):
        self._ids = tuple(external_id(v) for v in ids)
        self._indices = {v: i for i, v in enumerate(self._ids)}
        if len(self._indices) != len(self._ids):
            raise GraphMineError("Duplicate vertex/vector IDs")
        try:
            encoded = json.dumps(
                data, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise GraphMineError("Input must contain finite JSON values") from exc
        self._data = deepcopy(data)
        self._fingerprint = hashlib.sha256(encoded.encode()).hexdigest()

    @property
    def fingerprint(self):
        return self._fingerprint

    @property
    def node_ids(self):
        return self._ids

    @property
    def vertex_count(self):
        return len(self._ids)

    def vertex_id(self, index):
        return self._ids[index]

    def index(self, vertex_id):
        key = external_id(vertex_id)
        if key not in self._indices:
            raise GraphMineError(f"Unknown vertex/vector ID: {key!r}")
        return self._indices[key]

    def to_canonical(self):
        return deepcopy(self._data)


class GraphCollection:
    """Transactions with separate vertex namespaces and unique graph IDs."""

    kind = "graph_collection"

    def __init__(self, data):
        if not isinstance(data, dict) or set(data) != {"dataset_id", "graphs"}:
            raise GraphMineError("Graph collections require dataset_id and graphs")
        if not isinstance(data["dataset_id"], str) or not data["dataset_id"]:
            raise GraphMineError("dataset_id must be a nonempty string")
        if not isinstance(data["graphs"], list):
            raise GraphMineError("Collection graphs must be an array")
        self._graphs = tuple(Graph(row) for row in data["graphs"])
        ids = [row["graph"]["id"] for row in data["graphs"]]
        if len(set(ids)) != len(ids):
            raise GraphMineError("Collection graph IDs must be unique")
        if len({graph.directed for graph in self._graphs}) > 1:
            raise GraphMineError("Collection graphs must have consistent direction")
        self._data = deepcopy(data)
        self._fingerprint = hashlib.sha256(
            json.dumps(
                data, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()

    @property
    def graphs(self):
        return self._graphs

    @property
    def graph_count(self):
        return len(self._graphs)

    @property
    def fingerprint(self):
        return self._fingerprint

    def to_canonical(self):
        return deepcopy(self._data)


class FeatureVectors(_VertexInput):
    kind = "feature_vectors"

    def __init__(self, data):
        if not isinstance(data, dict) or set(data) != {
            "dataset_id",
            "dimension",
            "vectors",
        }:
            raise GraphMineError(
                "Feature vectors require dataset_id, dimension and vectors"
            )
        if not isinstance(data["dataset_id"], str) or not data["dataset_id"]:
            raise GraphMineError("dataset_id must be a nonempty string")
        dimension = data["dimension"]
        if type(dimension) is not int or dimension < 1:
            raise GraphMineError("Feature dimension must be a positive integer")
        if not isinstance(data["vectors"], list):
            raise GraphMineError("vectors must be an array")
        ids = []
        for row in data["vectors"]:
            if not isinstance(row, dict) or set(row) != {"id", "values"}:
                raise GraphMineError("Each vector needs exactly id and values")
            if not isinstance(row["values"], list) or len(row["values"]) != dimension:
                raise GraphMineError("Every vector must have exactly dimension entries")
            for value in row["values"]:
                finite_number(value, "Feature value")
            ids.append(row["id"])
        self._finish(data, ids)

    @property
    def dimension(self):
        return self._data["dimension"]


class Hypergraph(_VertexInput):
    kind = "hypergraph"

    def __init__(self, data):
        if not isinstance(data, dict) or set(data) != {
            "graph",
            "vertices",
            "hyperedges",
        }:
            raise GraphMineError(
                "Hypergraph input requires graph, vertices and hyperedges"
            )
        meta = data["graph"]
        if (
            not isinstance(meta, dict)
            or set(meta) - {"id", "attributes"}
            or not isinstance(meta.get("id"), str)
            or not meta["id"]
        ):
            raise GraphMineError(
                "Hypergraph metadata needs a nonempty id and optional attributes"
            )
        if "attributes" in meta and not isinstance(meta["attributes"], dict):
            raise GraphMineError("Hypergraph attributes must be an object")
        if not isinstance(data["vertices"], list) or not isinstance(
            data["hyperedges"], list
        ):
            raise GraphMineError("Hypergraph vertices and hyperedges must be arrays")
        ids = []
        for v in data["vertices"]:
            if (
                not isinstance(v, dict)
                or "id" not in v
                or set(v) - {"id", "weight", "attributes"}
            ):
                raise GraphMineError(
                    "Hypergraph vertices accept id, weight and attributes"
                )
            finite_number(v.get("weight", 1), "Vertex weight", nonnegative=True)
            if "attributes" in v and not isinstance(v["attributes"], dict):
                raise GraphMineError("Vertex attributes must be an object")
            ids.append(v["id"])
        self._finish(data, ids)
        seen = set()
        for edge in data["hyperedges"]:
            if (
                not isinstance(edge, dict)
                or not {"id", "vertices"} <= set(edge)
                or set(edge) - {"id", "vertices", "weight", "attributes"}
            ):
                raise GraphMineError(
                    "Hyperedges accept id, vertices, weight and attributes"
                )
            key = external_id(edge["id"])
            if key in seen:
                raise GraphMineError("Duplicate hyperedge ID")
            seen.add(key)
            if not isinstance(edge["vertices"], list) or not edge["vertices"]:
                raise GraphMineError("Every hyperedge requires a nonempty vertex array")
            vertices = [self.index(v) for v in edge["vertices"]]
            if len(set(vertices)) != len(vertices):
                raise GraphMineError("A hyperedge must not repeat a vertex")
            finite_number(edge.get("weight", 1), "Hyperedge weight", nonnegative=True)
            if "attributes" in edge and not isinstance(edge["attributes"], dict):
                raise GraphMineError("Hyperedge attributes must be an object")

    @property
    def edge_count(self):
        return len(self._data["hyperedges"])


def load_input(data, kind):
    classes = {
        "graph": Graph,
        "graph_collection": GraphCollection,
        "feature_vectors": FeatureVectors,
        "hypergraph": Hypergraph,
    }
    expected = classes[kind]
    if isinstance(data, expected):
        return data
    if isinstance(data, (Graph, GraphCollection, FeatureVectors, Hypergraph)):
        raise GraphMineError(f"This operation requires {kind} input")
    return expected(data)
