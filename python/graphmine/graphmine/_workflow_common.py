"""Shared workflow structure checks for native and reference execution."""

import hashlib
import json
import re

from .exceptions import GraphMineError

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")

_VERTEX_ARRAYS = {
    "vertices",
    "vertices_or_seeds",
    "origins",
    "destinations",
    "sinks",
    "seed_vertices",
    "sources",
    "start_vertices",
    "seeds",
    "required_vertices",
    "left_partition",
    "right_partition",
}

_GRAPH_ARGUMENTS = {"query_graph", "other_graph"}


def fingerprint(value):
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (TypeError, ValueError) as exc:
        raise GraphMineError("Workflow values must be finite JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _object(value, fields, name):
    if not isinstance(value, dict) or set(value) - set(fields):
        raise GraphMineError(f"Invalid {name} fields")


def _prepare_inputs(inputs, load_input):
    if not isinstance(inputs, dict):
        raise GraphMineError("Workflow inputs must be an object")
    result = {}
    for name, value in inputs.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise GraphMineError("Invalid workflow input alias")
        _object(value, {"kind", "data"}, "workflow input")
        if set(value) != {"kind", "data"}:
            raise GraphMineError("Every workflow input needs kind and data")
        if value["kind"] not in (
            "graph",
            "graph_collection",
            "feature_vectors",
            "hypergraph",
        ):
            raise GraphMineError("Unknown workflow input kind")
        result[name] = load_input(value["data"], value["kind"])
    return result


def _compatible(name, parameter, kind):
    if kind == "edge_ids":
        return parameter.kind == "array" and name == "edge_ids"
    if kind == "vertex_set":
        return parameter.kind == "array" and name in _VERTEX_ARRAYS
    if kind == "vertex_id":
        return parameter.kind == "vertex_id" and name != "anchor_edge"
    if kind == "graph":
        return parameter.kind == "object" and name in _GRAPH_ARGUMENTS
    if kind == "scalar":
        return parameter.kind in {"integer", "number"}
    if kind == "vertex_group_arrays":
        return parameter.kind == "array" and name in {"groups", "partition"}
    return False


def _reference_kind(reference, inputs, steps, port_types):
    _object(reference, {"input", "step", "port", "select"}, "reference")
    if "input" in reference:
        if (
            set(reference) != {"input"}
            or not isinstance(reference["input"], str)
            or reference["input"] not in inputs
        ):
            raise GraphMineError("Unknown or malformed workflow input reference")
        return inputs[reference["input"]].kind
    if (
        not {"step", "port"} <= set(reference)
        or not isinstance(reference["step"], str)
        or reference["step"] not in steps
    ):
        raise GraphMineError("Unknown workflow step reference")
    ports = port_types(steps[reference["step"]]["problem"])
    if not isinstance(reference["port"], str) or reference["port"] not in ports:
        raise GraphMineError("Unknown output port in workflow reference")
    kind = ports[reference["port"]]
    selection = reference.get("select")
    if selection is None:
        return kind
    _object(selection, {"kind", "k", "index", "descending"}, "selection")
    method = selection.get("kind")
    if method == "pattern_graph" and kind == "pattern_collection":
        if (
            set(selection) != {"kind", "index"}
            or type(selection["index"]) is not int
            or selection["index"] < 0
        ):
            raise GraphMineError(
                "Pattern selection requires a nonnegative integer index"
            )
        return "graph"
    if method in ("top_vertices", "top_vertex") and kind == "vertex_scores":
        expected = {"kind", "descending"} | (
            {"k"} if method == "top_vertices" else set()
        )
        if (
            set(selection) - expected
            or type(selection.get("descending", True)) is not bool
        ):
            raise GraphMineError("Invalid score selection")
        if method == "top_vertices" and (
            type(selection.get("k")) is not int or selection["k"] < 1
        ):
            raise GraphMineError("top_vertices requires a positive integer k")
        return "vertex_set" if method == "top_vertices" else "vertex_id"
    if method in ("group_vertices", "vertex") and kind == (
        "vertex_groups" if method == "group_vertices" else "vertex_set"
    ):
        if (
            set(selection) != {"kind", "index"}
            or type(selection["index"]) is not int
            or selection["index"] < 0
        ):
            raise GraphMineError(
                "Indexed selection requires a nonnegative integer index"
            )
        return "vertex_set" if method == "group_vertices" else "vertex_id"
    if (
        method in ("flatten_groups", "groups")
        and kind == "vertex_groups"
        and set(selection) == {"kind"}
    ):
        return "vertex_set" if method == "flatten_groups" else "vertex_group_arrays"
    raise GraphMineError("Selection is incompatible with its source port")
