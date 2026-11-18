"""Enforce preflight admission and instrument isolated native workflow calls.

Terminal rows travel to the supervising agent, whose asynchronous writer survives
a killed native process. The supervisor synthesizes a terminal row if necessary.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import asdict, replace
from uuid import uuid4

from .features import cached_features, safe_parameters
from .hardware import hardware_snapshot, merge_peaks, process_rss
from .feasibility import filter_candidates, legacy_choice
from .storage import DEFAULT_DATA_DIR, SCHEMA_VERSION, utc_now


def outcome_for(error=None, *, timed_out=False):
    if timed_out:
        return "timeout", "timeout"
    if error is None:
        return "completed", None
    code = getattr(error, "code", type(error).__name__)
    message = str(error).lower()
    if isinstance(error, (TimeoutError,)) or code in {"timeout", "deadline_exceeded"} or any(
        text in message for text in ("timed out", "deadline exceeded", "timeout exceeded", "execution deadline")
    ):
        return "timeout", code
    if isinstance(error, MemoryError) or code in {"oom", "out_of_memory"} or any(
        text in message for text in ("out of memory", "allocation failed", "bad_alloc", "memory allocation", "memoryallocation")
    ):
        return "oom", code
    if code == "unsupported_input":
        return "unsupported_input", code
    return "error", code


def output_size(result):
    if not isinstance(result, dict):
        return None
    data = result.get("result", {})
    for key in ("returned_count", "output_count", "community_count", "count"):
        value = data.get(key)
        if type(value) is int and value >= 0:
            return value
    sizes = [len(port["value"]) for port in result.get("ports", {}).values()
             if isinstance(port, dict) and isinstance(port.get("value"), list)]
    return max(sizes) if sizes else None


def run_observed(run, operation, graph, *, context, step_id, emit, **kwargs):
    """One start/finish pair around exactly one real native operation call."""
    from graphmine.dispatch import native_request, native_library
    from graphmine.contracts import Budget
    from graphmine.exceptions import GraphMineError, ResourceLimit
    from graphmine.registry import algorithm

    started, row = time.monotonic(), None

    def event(value):
        try:
            emit(value)
        except Exception:
            print("backend telemetry: event_delivery_failed", file=sys.stderr)

    data = graph.to_canonical() if hasattr(graph, "to_canonical") else graph
    definition = algorithm(operation)
    budget_object = kwargs.get("budget") or Budget()
    budget_object = replace(budget_object, timeout_seconds=min(
        budget_object.timeout_seconds, context.get("job_timeout_seconds", 1800), 1800))
    kwargs["budget"] = budget_object
    budget = asdict(budget_object)
    requested = context.get("requested_device", kwargs.get("device", "auto"))
    backend = kwargs.get("backend") or "auto"
    parameters = safe_parameters(kwargs.get("parameters") or {}, definition.parameters)
    hardware = hardware_snapshot(leased_gpu_uuid=context.get("leased_gpu_uuid"))
    hardware["backend_memory_safety"] = context.get("backend_memory_safety", 0.8)
    data_dir = os.environ.get("GRAPHMINE_BACKEND_DATA_DIR", str(DEFAULT_DATA_DIR))
    fingerprint = getattr(graph, "fingerprint", None)
    try:
        features = cached_features(data, data_dir, snapshot_fingerprint=fingerprint,
                                   input_kind=definition.input_kind) if fingerprint else None
    except Exception:
        features = None  # A damaged feature cache cannot prevent an admitted run.
    if features is None:
        from .features import graph_features
        features = graph_features(data, input_kind=definition.input_kind)
    caps, preparation_error, warnings = {}, None, []
    try:
        # The worker's logical device 0 must map to the physical GPU 1 lease.
        # Without that mapping an automatic request may still use CPU, but must
        # not initialize CUDA while asking the native API about candidates.
        gpu_allowed = (hardware.get("leased_gpu_index") == 1
                       and os.environ.get("CUDA_VISIBLE_DEVICES") in {context.get("leased_gpu_uuid"), "1"}
                       and kwargs.get("gpu_device", 0) == 0)
        execution_device = kwargs.get("device", "auto")
        if not gpu_allowed and execution_device == "gpu":
            raise GraphMineError("A verified lease on physical GPU 1 is required")
        if not gpu_allowed and backend not in {"auto", "cpp"}:
            raise GraphMineError("The requested backend requires a verified lease on physical GPU 1")
        if not gpu_allowed or backend == "cpp":
            execution_device = "cpu" if execution_device == "auto" else execution_device
        query = dict(command="backend_capabilities", operation=operation, graph=data,
                     parameters=kwargs.get("parameters") or {}, device=execution_device,
                     backend=backend, gpu_device=kwargs.get("gpu_device", 0), budget=budget)
        if kwargs.get("allowed_backends") is not None:
            query["allowed_backends"] = kwargs["allowed_backends"]
        caps = native_request(query)
        caps["candidates"] = filter_candidates(operation, caps["candidates"], features, parameters, hardware,
            output_estimate=budget["max_output_items"], implementation=caps["implementation_sha256"], data_dir=data_dir)
        caps["legacy_backend"] = legacy_choice(caps["candidates"], backend)
        if caps["legacy_backend"] is None:
            reasons = sorted({c["infeasible_reason"] for c in caps["candidates"]
                              if c["infeasible_reason"] and (backend == "auto" or c["id"] == backend)})
            raise ResourceLimit("No feasible admitted backend: " + "; ".join(reasons or ["backend_not_declared"]))
        # Keep native auto ordering, restricted to the feasible set. An explicit
        # backend is unchanged and cannot silently fall back to another one.
        kwargs["allowed_backends"] = [c["id"] for c in caps["candidates"] if c["feasible"]]
        kwargs["device"] = execution_device
    except Exception as exc:
        preparation_error = exc
        if not caps:
            warnings.append("native_preflight_failed")
    try:
        if not caps:
            card = next(c for c in native_library().catalog()["operations"] if c["id"] == operation)
            admitted = kwargs.get("allowed_backends")
            caps = dict(candidates=[dict(id=c["id"], device=c["device"], compiled=c["compiled"],
                        admitted=admitted is None or c["id"] in admitted,
                        feasible=False, infeasible_reason="preflight_unavailable") for c in card["backends"]],
                        legacy_backend=None)
        row = dict(schema_version=SCHEMA_VERSION, run_id=str(uuid4()),
                   workflow_id=context.get("workflow_id"), step_id=step_id, created_at=utc_now(),
                   operation=operation, problem_id=definition.problem_id, family=definition.family,
                   parameters=parameters,
                   requested_device=requested, requested_backend=backend, candidates=caps["candidates"],
                   chosen_backend=caps.get("legacy_backend"),
                   reason="forced" if requested != "auto" or backend != "auto" else "legacy_auto",
                   policy_version="feasibility-v1", model_version=None,
                   predictions={c["id"]: dict(p50_seconds=None, p90_seconds=None, sampled_value=None,
                                peak_memory_bytes=c["predicted_peak_memory_bytes"],
                                memory_model_version=c["memory_model_version"])
                                for c in caps["candidates"] if c["feasible"]}, hardware=hardware,
                   graph_features=features, outcome=None, error_code=None, runtime_seconds=None,
                   native_elapsed_seconds=None, native_compute_seconds=None, preparation_seconds=None,
                   timeout_seconds=min(budget.get("timeout_seconds", 60), context.get("job_timeout_seconds", 1800)),
                   censored=False, peak_memory=dict(gpu_bytes=None, process_rss_bytes=process_rss(os.getpid()),
                                                    sample_interval_seconds=0.1),
                   output_size=None, output_estimate=budget["max_output_items"], fallback_chain=[],
                   execution_started=preparation_error is None,
                   failure_stage="preflight" if preparation_error else None,
                   is_evaluation=bool(context.get("is_evaluation") or os.environ.get("PYTEST_CURRENT_TEST")
                                      or os.environ.get("GRAPHMINE_IS_EVALUATION") == "true"),
                   source=context.get("source", "application"), prediction_error=None,
                   implementation_sha256=caps.get("implementation_sha256"),
                   telemetry_warnings=warnings + hardware.get("warnings", []))
        if preparation_error is None:
            event({"event": "native_started", "record": dict(row)})
    except Exception:
        # Logging failures must not bypass admission or replace native results.
        event({"event": "telemetry_warning", "code": "telemetry_prepare_failed"})
    result, error = None, None
    try:
        if preparation_error is not None:
            raise preparation_error
        remaining = budget_object.timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            if row is not None:
                row.update(execution_started=False, failure_stage="preflight")
            raise TimeoutError("Native preflight exhausted the step execution deadline")
        kwargs["budget"] = replace(budget_object, timeout_seconds=remaining)
        result = run(operation, graph, **kwargs)
        return result
    except BaseException as exc:
        error = exc
        raise
    finally:
        if row is not None:
            try:
                outcome, code = outcome_for(error)
                row.update(outcome=outcome, error_code=code, censored=outcome == "timeout",
                           runtime_seconds=time.monotonic() - started)
                row["peak_memory"] = merge_peaks(row["peak_memory"], {"process_rss_bytes": process_rss(os.getpid())})
                if result is not None:
                    row.update(chosen_backend=result.get("backend", {}).get("id"),
                               native_elapsed_seconds=result.get("elapsed_seconds"),
                               native_compute_seconds=result.get("compute_seconds"),
                               output_size=output_size(result))
                    # Only report a separate transfer/preparation measurement
                    # when the native runtime actually provides one.
                    row["preparation_seconds"] = result.get("preparation_seconds")
                event({"event": "native_finished", "record": row})
            except Exception:
                event({"event": "telemetry_warning", "code": "telemetry_finalize_failed"})


def install():
    """Called once by the agent bootstrap, before graphmine.worker imports."""
    import json
    import graphmine.workflows as workflows

    original_execute, original_run = workflows.execute_workflow, workflows.run
    context = json.loads(os.environ.get("GRAPHMINE_BACKEND_RUN_CONTEXT", "{}"))

    def execute(plan, inputs, *, emit=None, **kwargs):
        current = None
        steps = {s["id"]: s for s in plan.get("steps", [])}

        def event(value):
            nonlocal current
            if value.get("event") == "step_started":
                current = value["step"]
            if emit:
                emit(value)

        def observed(operation, graph, **run_kwargs):
            step = steps.get(current, {})
            return run_observed(original_run, operation, graph, context={
                **context, "requested_device": step.get("device", plan.get("device", "auto"))},
                step_id=current, emit=event, **run_kwargs)

        workflows.run = observed
        try:
            return original_execute(plan, inputs, emit=event, **kwargs)
        finally:
            workflows.run = original_run

    workflows.execute_workflow = execute
