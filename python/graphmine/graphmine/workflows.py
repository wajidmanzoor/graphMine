"""Typed, declarative DAGs over registered problems. No expression evaluation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction
from graphlib import CycleError, TopologicalSorter

from ._workflow_common import (
    _NAME,
    _compatible,
    _object,
    _prepare_inputs,
    _reference_kind,
    fingerprint,
)
from .contracts import Budget
from .dispatch import execution_environment, implementation_hash, native_request, run
from .exceptions import GraphMineError
from .graph import external_id
from .native_inputs import Graph, load_input
from .registry import algorithm

def prepare_inputs(inputs):
    return _prepare_inputs(inputs, load_input)


def _reference(reference, inputs, steps):
    return _reference_kind(
        reference,
        inputs,
        steps,
        lambda problem: {
            name: port["type"]
            for name, port in algorithm(problem).card()["output_ports"].items()
        },
    )


def validate_workflow(plan, inputs):
    plan = deepcopy(plan)
    if isinstance(plan, dict) and isinstance(plan.get("steps"), list):
        for step in plan["steps"]:
            if isinstance(step, dict) and "operation" in step:
                if "problem" in step and step["problem"] != step["operation"]:
                    raise GraphMineError("Conflicting problem and operation identifiers")
                step["problem"] = step.pop("operation")
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
            {"id", "problem", "input", "parameters", "bindings", "device", "backend", "budget"},
            "step",
        )
        name = source.get("id")
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name in steps:
            raise GraphMineError("Step IDs must be valid and unique")
        if not isinstance(source.get("problem"), str):
            raise GraphMineError("Step problem must be a registered name")
        definition = algorithm(source["problem"])
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
            if key in parameters:
                normalized[key] = spec.validate(key, parameters[key])
        policy = source.get("device", device)
        if policy not in ("cpu", "gpu", "auto") or (
            device != "auto" and policy != device
        ):
            raise GraphMineError("Step device conflicts with the workflow policy")
        backend = source.get("backend", "auto")
        declared = {b["id"]: b for b in definition.card()["backends"]}
        if not isinstance(backend, str) or backend != "auto" and backend not in declared:
            raise GraphMineError("Step backend must be a declared native backend or auto")
        if backend != "auto":
            if not declared[backend]["compiled"]:
                raise GraphMineError("The requested native backend is not compiled")
            if policy != "auto" and declared[backend]["device"] != policy:
                raise GraphMineError("Step backend conflicts with the device policy")
        budget = source.get("budget", {})
        _object(budget, Budget.__dataclass_fields__, "budget")
        steps[name] = {
            "id": name,
            "problem": definition.id,
            "input": deepcopy(source.get("input")),
            "parameters": normalized,
            "bindings": deepcopy(bindings),
            "device": policy,
            "budget": asdict(Budget(**budget)),
        }
        if "backend" in source:
            steps[name]["backend"] = backend
    dependencies = {}
    for name, step in steps.items():
        definition = algorithm(step["problem"])
        if _reference(step["input"], loaded, steps) != definition.input_kind:
            raise GraphMineError(f"Input kind mismatch for {name}")
        request = {
            "command": "validate",
            "problem": definition.id,
            "parameters": step["parameters"],
            "device": step["device"],
            "partial_parameters": bool(step["bindings"]),
        }
        if "input" in step["input"]:
            request["graph"] = loaded[step["input"]["input"]].to_canonical()
        native_request(request)
        refs = [step["input"], *step["bindings"].values()]
        for key, reference in step["bindings"].items():
            kind = _reference(reference, loaded, steps)
            if not _compatible(key, definition.parameters[key], kind):
                raise GraphMineError(f"Incompatible binding for {name}.{key}")
        dependencies[name] = {r["step"] for r in refs if "step" in r}
        if step["device"] == "gpu" and any(
            definition.parameters[k].kind in {"string", "boolean"}
            for k in step["bindings"]
        ):
            raise GraphMineError("GPU variant settings must be literal")
    try:
        order = list(TopologicalSorter(dependencies).static_order())
    except CycleError as exc:
        raise GraphMineError("Workflow dependencies contain a cycle") from exc
    normalized = {"version": 1, "device": device, "steps": list(steps.values())}
    manifest = {
        key: {"kind": value.kind, "fingerprint": value.fingerprint}
        for key, value in loaded.items()
    }
    environment = execution_environment()
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
            "The selected problem variant did not produce the required port"
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

            def exact_score(row):
                if port.get("exact_score_field"):
                    exact = row[port["exact_score_field"]]
                    return Fraction(int(exact["numerator"]), int(exact["denominator"]))
                return row[field]

            rows.sort(
                key=lambda row: (
                    (-1 if selection.get("descending", True) else 1) * exact_score(row),
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
    plan,
    inputs,
    *,
    emit=None,
    resume=None,
    verified_gpu_problems=None,
    verified_backends=None,
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
                if kind == "edge_ids" and namespace != graph.fingerprint:
                    raise GraphMineError(
                        "Edge binding belongs to a different input graph; an explicit ID mapping is required"
                    )
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
            parameters = algorithm(step["problem"]).arguments(parameters)
            execution_device = step["device"]
            if (
                execution_device == "auto"
                and verified_gpu_problems is not None
                and step["problem"] not in verified_gpu_problems
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
                    "allowed_backends": None
                    if verified_backends is None
                    else verified_backends.get(step["problem"], []),
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
                    step["problem"],
                    graph,
                    parameters=parameters,
                    device=execution_device,
                    backend=step.get("backend"),
                    budget=Budget(**step["budget"]),
                    allowed_backends=None
                    if verified_backends is None
                    else verified_backends.get(step["problem"], []),
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
