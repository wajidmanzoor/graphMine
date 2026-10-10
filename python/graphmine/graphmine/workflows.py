"""Typed, declarative DAGs over registered operations. No expression evaluation."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
from copy import deepcopy
from dataclasses import asdict
from graphlib import CycleError, TopologicalSorter

from .contracts import Budget
from .dispatch import implementation_hash, run
from .exceptions import GraphMineError
from .graph import Graph, external_id
from .inputs import load_input
from .ports import OUTPUT_PORTS
from .registry import algorithm

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


def prepare_inputs(inputs):
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


def _reference(reference, inputs, steps):
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
    ports = OUTPUT_PORTS.get(steps[reference["step"]]["operation"], {})
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


def _compatible(name, parameter, kind):
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


def validate_workflow(plan, inputs):
    fingerprint(plan)
    loaded = prepare_inputs(inputs)
    _object(plan, {"version", "device", "steps"}, "workflow")
    if plan.get("version") != 1 or type(plan.get("version")) is not int:
        raise GraphMineError("Workflow version must be 1")
    device = plan.get("device", "auto")
    if device not in ("cpu", "gpu", "auto"):
        raise GraphMineError("Workflow device must be cpu, gpu or auto")
    if not isinstance(plan.get("steps"), list) or not 1 <= len(plan["steps"]) <= 64:
        raise GraphMineError("A workflow needs 1 to 64 steps")
    steps = {}
    for source in plan["steps"]:
        _object(
            source,
            {"id", "operation", "input", "parameters", "bindings", "device", "budget"},
            "step",
        )
        name = source.get("id")
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name in steps:
            raise GraphMineError("Step IDs must be valid and unique")
        if not isinstance(source.get("operation"), str):
            raise GraphMineError("Step operation must be a registered name")
        definition = algorithm(source["operation"])
        parameters, bindings = source.get("parameters", {}), source.get("bindings", {})
        _object(parameters, definition.parameters, "parameters")
        _object(bindings, definition.parameters, "bindings")
        if set(parameters) & set(bindings):
            raise GraphMineError("A parameter cannot have both a literal and a binding")
        normalized = {}
        for key, spec in definition.parameters.items():
            if key in bindings:
                continue
            if key not in parameters and spec.required:
                raise GraphMineError(f"Missing {key} in {name}")
            normalized[key] = spec.validate(key, parameters.get(key, spec.default))
        policy = source.get("device", device)
        if policy not in ("cpu", "gpu", "auto") or (
            device != "auto" and policy != device
        ):
            raise GraphMineError("Step device conflicts with the workflow policy")
        budget = source.get("budget", {})
        _object(budget, Budget.__dataclass_fields__, "budget")
        steps[name] = {
            "id": name,
            "operation": definition.id,
            "input": deepcopy(source.get("input")),
            "parameters": normalized,
            "bindings": deepcopy(bindings),
            "device": policy,
            "budget": asdict(Budget(**budget)),
        }
    dependencies = {}
    for name, step in steps.items():
        definition = algorithm(step["operation"])
        if _reference(step["input"], loaded, steps) != definition.input_kind:
            raise GraphMineError(f"Input kind mismatch for {name}")
        refs = [step["input"], *step["bindings"].values()]
        for key, reference in step["bindings"].items():
            kind = _reference(reference, loaded, steps)
            if not _compatible(key, definition.parameters[key], kind):
                raise GraphMineError(f"Incompatible binding for {name}.{key}")
        dependencies[name] = {r["step"] for r in refs if "step" in r}
        if step["device"] == "gpu":
            from .backends.cugraph import supports

            # Capability predicates inspect literal variant settings only.
            if any(
                definition.parameters[k].kind in {"string", "boolean"}
                for k in step["bindings"]
            ):
                raise GraphMineError("GPU variant settings must be literal")
            supported, reason = supports(definition.id, step["parameters"])
            if not supported:
                raise GraphMineError(reason)
    try:
        order = list(TopologicalSorter(dependencies).static_order())
    except CycleError as exc:
        raise GraphMineError("Workflow dependencies contain a cycle") from exc
    normalized = {"version": 1, "device": device, "steps": list(steps.values())}
    manifest = {
        key: {"kind": value.kind, "fingerprint": value.fingerprint}
        for key, value in loaded.items()
    }
    environment = {}
    for package in (
        "networkx",
        "numpy",
        "scipy",
        "cvxpy",
        "clarabel",
        "gudhi",
        "rapidfuzz",
        "igraph",
        "cugraph-cu12",
        "nx-cugraph-cu12",
        "cupy-cuda12x",
    ):
        try:
            environment[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            environment[package] = None
    implementation = implementation_hash()
    signature = fingerprint(
        {
            "plan": normalized,
            "inputs": manifest,
            "implementation": implementation,
            "environment": environment,
        }
    )
    return {
        "plan": normalized,
        "order": order,
        "inputs": manifest,
        "workflow_hash": signature,
        "implementation_sha256": implementation,
        "environment": environment,
    }


def _resolve(reference, inputs, results):
    if "input" in reference:
        value = inputs[reference["input"]]
        return value.to_canonical(), value.kind, value.fingerprint
    source = results[reference["step"]]
    if source["status"] != "completed":
        raise GraphMineError("A required predecessor did not complete")
    port = source["result"]["ports"].get(reference["port"])
    if port is None:
        raise GraphMineError(
            "The selected operation variant did not produce the required port"
        )
    if not port["complete"]:
        raise GraphMineError(
            "An incomplete or count-only collection cannot supply this workflow input"
        )
    value, kind = deepcopy(port["value"]), port["type"]
    namespace = port.get("graph_fingerprint", port.get("input_fingerprint"))
    selection = reference.get("select")
    if selection:
        method = selection["kind"]
        if method == "pattern_graph":
            if selection["index"] >= len(value):
                raise GraphMineError("Workflow selection index is out of range")
            value = value[selection["index"]]["pattern"]
            kind, namespace = "graph", Graph(value).fingerprint
        elif method in ("top_vertices", "top_vertex"):
            field = port.get("score_field", "score")
            rows = [row for row in value if row.get(field) is not None]
            rows.sort(
                key=lambda row: (
                    (-1 if selection.get("descending", True) else 1) * row[field],
                    0 if type(row["vertex"]) is int else 1,
                    row["vertex"],
                )
            )
            if method == "top_vertex":
                if not rows:
                    raise GraphMineError("No scored vertex is available for top_vertex")
                value, kind = rows[0]["vertex"], "vertex_id"
            else:
                value, kind = (
                    [row["vertex"] for row in rows[: selection["k"]]],
                    "vertex_set",
                )
        elif method in ("group_vertices", "vertex"):
            if selection["index"] >= len(value):
                raise GraphMineError("Workflow selection index is out of range")
            value = (
                value[selection["index"]]["vertices"]
                if method == "group_vertices"
                else value[selection["index"]]
            )
            kind = "vertex_set" if method == "group_vertices" else "vertex_id"
        elif method == "flatten_groups":
            value = list(
                dict.fromkeys(external_id(v) for row in value for v in row["vertices"])
            )
            kind = "vertex_set"
        else:
            value, kind = [row["vertices"] for row in value], "vertex_group_arrays"
    return value, kind, namespace


def execute_workflow(
    plan, inputs, *, emit=None, resume=None, verified_gpu_operations=None
):
    """Execute a checked DAG; resume records must come from trusted local storage.

    Result hashes detect corruption, not a malicious cache writer. Web clients
    must not supply resume records. Each dependency is still resolved and checked.
    """
    checked = validate_workflow(plan, inputs)
    loaded = prepare_inputs(inputs)
    steps = {step["id"]: step for step in checked["plan"]["steps"]}
    results = {}
    resumed = resume if isinstance(resume, dict) else {}
    for name in checked["order"]:
        step = steps[name]
        refs = [step["input"], *step["bindings"].values()]
        blocked = [
            r["step"]
            for r in refs
            if "step" in r and results[r["step"]]["status"] != "completed"
        ]
        if blocked:
            results[name] = {
                "status": "blocked",
                "error": {
                    "code": "dependency_failed",
                    "message": "Required steps did not complete",
                    "steps": sorted(set(blocked)),
                },
            }
            if emit:
                emit({"event": "step_finished", "step": name, "record": results[name]})
            continue
        if emit:
            emit({"event": "step_started", "step": name})
        try:
            value, kind, _ = _resolve(step["input"], loaded, results)
            graph = load_input(value, kind)
            parameters = deepcopy(step["parameters"])
            for key, reference in step["bindings"].items():
                value, kind, namespace = _resolve(reference, loaded, results)
                if kind in {"vertex_set", "vertex_id", "vertex_group_arrays"}:
                    if namespace != graph.fingerprint:
                        raise GraphMineError(
                            "Vertex binding belongs to a different input graph; an explicit ID mapping is required"
                        )
                    vertices = (
                        [value]
                        if kind == "vertex_id"
                        else [v for group in value for v in group]
                        if kind == "vertex_group_arrays"
                        else value
                    )
                    for vertex in vertices:
                        graph.index(vertex)
                parameters[key] = value
            parameters = algorithm(step["operation"]).arguments(parameters)
            execution_device = step["device"]
            if (
                execution_device == "auto"
                and verified_gpu_operations is not None
                and step["operation"] not in verified_gpu_operations
            ):
                execution_device = "cpu"
            key = fingerprint(
                {
                    "step": step,
                    "parameters": parameters,
                    "input": graph.fingerprint,
                    "implementation": checked["implementation_sha256"],
                    "environment": checked["environment"],
                    "execution_device": execution_device,
                }
            )
            cached = resumed.get(name, {})
            if (
                isinstance(cached, dict)
                and cached.get("status") == "completed"
                and cached.get("cache_key") == key
                and isinstance(cached.get("result"), dict)
                and cached.get("result_sha256") == fingerprint(cached["result"])
            ):
                result = deepcopy(cached["result"])
                reused = True
            else:
                result = run(
                    step["operation"],
                    graph,
                    parameters=parameters,
                    device=execution_device,
                    budget=Budget(**step["budget"]),
                )
                reused = False
            results[name] = {
                "status": "completed",
                "cache_key": key,
                "result_sha256": fingerprint(result),
                "reused": reused,
                "execution_device_policy": execution_device,
                "result": result,
            }
        except GraphMineError as exc:
            results[name] = {
                "status": "failed",
                "error": {"code": exc.code, "message": str(exc)},
            }
        if emit:
            emit({"event": "step_finished", "step": name, "record": results[name]})
    success = all(row["status"] == "completed" for row in results.values())
    return {
        **checked,
        "status": "completed" if success else "failed",
        "complete": success
        and all(row["result"]["complete"] for row in results.values()),
        "steps": results,
    }
