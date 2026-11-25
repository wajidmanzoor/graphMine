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
from .feasibility import filter_candidates, native_choice
from .storage import DEFAULT_DATA_DIR, SCHEMA_VERSION, utc_now
from ..calculation_limits import DEFAULT_EXECUTION_TIMEOUT_SECONDS, minimum_limit, remaining_seconds


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


def _decision(problem, candidates, features, parameters, hardware, context, backend, requested, implementation):
    from . import models, policy
    from .storage import DEFAULT_MODEL_DIR

    observation = dict(problem=problem, graph_features=features, parameters=parameters, hardware=hardware,
                       execution_isolated=context.get("execution_isolated", False))
    mode = context.get("backend_selection", "native")
    model, version, allowed, warning = None, None, False, None
    configuration = dict(temperature=context.get("backend_temperature", 1.),
        floor=context.get("backend_exploration_floor", .02),
        exploration_budget=context.get("backend_exploration_budget", .10),
        exploration_enabled=context.get("backend_exploration_enabled", True))
    try:
        model_dir = context.get("backend_model_dir", str(DEFAULT_MODEL_DIR))
        model, metadata = models.load(model_dir, implementation)
        version = metadata["model_version"]
        allowed = context.get("backend_require_rollout_evidence", True) is False or models.live_permitted(
            model_dir, metadata, implementation, context.get("admission_fingerprint"), configuration=configuration)
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        if mode != "native":
            warning = "shared_model_unavailable_or_invalid"
    scope = "bandit" if mode == "bandit" and allowed else "shadow"

    def reserve(**options):
        if context.get("is_evaluation") or os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GRAPHMINE_IS_EVALUATION") == "true":
            best = options["best"]
            return dict(choice=best, probabilities={b: float(b == best) for b in options["probabilities"]},
                        allowed=False, reason="evaluation_does_not_reserve_live_budget")
        return policy.reserve_exploration(os.environ.get("GRAPHMINE_BACKEND_DATA_DIR", str(DEFAULT_DATA_DIR)),
            problem, context["decision_id"], scope, configuration["exploration_budget"], **options)
    try:
        settings = dict(configuration)
        if context.get("attempt_index", 0):
            settings["exploration_enabled"] = False
        decision = policy.decide(candidates, observation, model=model, model_version=version,
            mode=mode, live_allowed=allowed, requested_backend=backend, requested_device=requested,
            seed=context.get("backend_random_seed"), reserve=reserve, **settings)
        decision["policy_warning"] = warning or decision["policy_warning"]
    except Exception:
        # An invalid artifact cannot alter feasibility or an explicit request.
        decision = policy.decide(candidates, observation, requested_backend=backend, requested_device=requested)
        decision["policy_warning"] = "shared_policy_failed"
    decision["attempt_timeout_seconds"] = policy.timeout_seconds(
        default=context.get("backend_default_timeout_seconds", DEFAULT_EXECUTION_TIMEOUT_SECONDS))
    if context.get("attempt_index", 0):
        decision.update(reason="fallback", backend_choice_reason="fallback")
    return decision


def _run_attempt(run, problem, graph, *, context, step_id, emit, started, **kwargs):
    """One start/finish pair around exactly one real native problem call."""
    from graphmine.dispatch import native_request, native_library
    from graphmine.contracts import Budget
    from graphmine.exceptions import GraphMineError, ResourceLimit
    from graphmine.registry import algorithm

    row = None

    def event(value):
        try:
            emit(value)
        except Exception:
            print("backend telemetry: event_delivery_failed", file=sys.stderr)

    data = graph.to_canonical() if hasattr(graph, "to_canonical") else graph
    definition = algorithm(problem)
    budget_object = kwargs.get("budget") or Budget()
    budget_object = replace(budget_object, timeout_seconds=minimum_limit(
        budget_object.timeout_seconds, context.get("job_timeout_seconds")))
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
    # Forecast allocation without turning this estimate into a result limit.
    output_estimate = budget["max_output_items"]
    if output_estimate is None:
        output_estimate = max(100000, features.get("n") or 0, features.get("m") or 0)
    caps, preparation_error, warnings, decision = {}, None, [], {}
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
        query = dict(command="backend_capabilities", problem=problem, graph=data,
                     parameters=kwargs.get("parameters") or {}, device=execution_device,
                     backend=backend, gpu_device=kwargs.get("gpu_device", 0), budget=budget)
        if kwargs.get("allowed_backends") is not None:
            query["allowed_backends"] = kwargs["allowed_backends"]
        caps = native_request(query)
        # Support checks can take time and initialize a CUDA context. Admission
        # uses a fresh snapshot after them, immediately before choosing a backend.
        hardware = hardware_snapshot(leased_gpu_uuid=context.get("leased_gpu_uuid"))
        hardware["backend_memory_safety"] = context.get("backend_memory_safety", 0.8)
        caps["candidates"] = filter_candidates(problem, caps["candidates"], features, parameters, hardware,
            output_estimate=output_estimate, implementation=caps["implementation_sha256"], data_dir=data_dir)
        for candidate in caps["candidates"]:
            if candidate["id"] in context.get("attempted_backends", []):
                candidate.update(feasible=False, infeasible_reason="already_attempted_in_this_step")
        caps["native_rule_backend"] = native_choice(caps["candidates"], backend)
        if caps["native_rule_backend"] is None:
            reasons = sorted({c["infeasible_reason"] for c in caps["candidates"]
                              if c["infeasible_reason"] and (backend == "auto" or c["id"] == backend)})
            raise ResourceLimit("No feasible admitted backend: " + "; ".join(reasons or ["backend_not_declared"]))
        # Keep native auto ordering, restricted to the feasible set. An explicit
        # backend is unchanged and cannot silently fall back to another one.
        kwargs["allowed_backends"] = [c["id"] for c in caps["candidates"] if c["feasible"]]
        kwargs["device"] = execution_device
        decision = _decision(problem, caps["candidates"], features, parameters, hardware, context,
                             backend, requested, caps["implementation_sha256"])
        kwargs["backend"] = decision["native_backend"]
    except Exception as exc:
        preparation_error = exc
        if not caps:
            warnings.append("native_preflight_failed")
    try:
        if not caps:
            card = next(c for c in native_library().catalog()["problems"] if c["id"] == problem)
            admitted = kwargs.get("allowed_backends")
            caps = dict(candidates=[dict(id=c["id"], device=c["device"], compiled=c["compiled"],
                        admitted=admitted is None or c["id"] in admitted,
                        feasible=False, infeasible_reason="preflight_unavailable") for c in card["backends"]],
                        native_rule_backend=None)
        row = dict(schema_version=SCHEMA_VERSION, run_id=str(uuid4()),
                   workflow_id=context.get("workflow_id"), step_id=step_id, created_at=utc_now(),
                   problem=problem, topic_id=definition.topic_id, family=definition.family,
                   parameters=parameters,
                   requested_device=requested, requested_backend=backend, candidates=caps["candidates"],
                   chosen_backend=decision.get("chosen_backend", caps.get("native_rule_backend")),
                   reason=decision.get("reason", "forced" if requested != "auto" or backend != "auto" else "native_rule"),
                   policy_version="shared-nn-softmax-v1" if decision.get("model_version") else "native-rule-v1",
                   model_version=decision.get("model_version"),
                   eligible_backends=decision.get("eligible_backends", []),
                   selection_probability=decision.get("selection_probability"),
                   probabilities=decision.get("probabilities", {}),
                   context_features=decision.get("context_features"),
                   cost_scale_seconds=decision.get("cost_scale_seconds"),
                   failure_cost=decision.get("failure_cost"), hardware=hardware,
                   graph_features=features, outcome=None, error_code=None, runtime_seconds=None,
                   native_elapsed_seconds=None, native_compute_seconds=None, preparation_seconds=None,
                   timeout_seconds=budget_object.timeout_seconds,
                   censored=False, peak_memory=dict(gpu_bytes=None, process_rss_bytes=process_rss(os.getpid()),
                                                    sample_interval_seconds=0.1),
                   output_size=None, output_estimate=output_estimate, output_limit_items=budget["max_output_items"],
                   fallback_chain=context.get("fallback_chain", []),
                   decision_id=context["decision_id"], attempt_index=context.get("attempt_index", 0),
                   execution_isolated=context.get("execution_isolated", False),
                   selection_mode=decision.get("selection_mode", context.get("backend_selection", "native")),
                   requested_selection_mode=context.get("backend_selection", "native"),
                   rollout_evidence_required=context.get("backend_require_rollout_evidence", True),
                   shadow_choice=decision.get("shadow_choice"), shadow_reason=decision.get("shadow_reason"),
                   shadow_probability=decision.get("shadow_probability"),
                   shadow_probabilities=decision.get("shadow_probabilities"),
                   backend_choice_reason=decision.get("backend_choice_reason"),
                   selection_seed=decision.get("selection_seed"), exploration=decision.get("exploration", {}),
                   policy_warning=decision.get("policy_warning"),
                   selector_active=(backend == "auto" and len(decision.get("eligible_backends", [])) > 1),
                   step_timeout_seconds=context["step_timeout_seconds"],
                   execution_started=preparation_error is None,
                   failure_stage="preflight" if preparation_error else None,
                   is_evaluation=bool(context.get("is_evaluation") or os.environ.get("PYTEST_CURRENT_TEST")
                                      or os.environ.get("GRAPHMINE_IS_EVALUATION") == "true"),
                   source=context.get("source", "application"),
                   implementation_sha256=caps.get("implementation_sha256"),
                   telemetry_warnings=warnings + hardware.get("warnings", []))
    except Exception:
        # Logging failures must not bypass admission or replace native results.
        event({"event": "telemetry_warning", "code": "telemetry_prepare_failed"})
    result, error = None, None
    try:
        if preparation_error is not None:
            raise preparation_error
        now = time.monotonic()
        remaining = remaining_seconds(context["step_deadline"], now)
        if remaining is not None and remaining <= 0:
            if row is not None:
                row.update(execution_started=False, failure_stage="preflight")
            raise TimeoutError("Native preflight exhausted the step execution deadline")
        # Benchmarks measure the configured benchmark deadline; application
        # requests use empirical controls even when the overall step is unbounded.
        if context.get("source", "application") != "benchmark":
            remaining = minimum_limit(remaining, decision.get("attempt_timeout_seconds"))
        kwargs["budget"] = replace(budget_object, timeout_seconds=remaining)
        if row is not None:
            row["timeout_seconds"] = remaining
            event({"event": "native_started", "record": dict(row)})
        result = run(problem, graph, **kwargs)
        return result
    except BaseException as exc:
        error = exc
        raise
    finally:
        if row is not None:
            try:
                outcome, code = outcome_for(error)
                ended = time.monotonic()
                row.update(outcome=outcome, error_code=code, censored=outcome == "timeout",
                           runtime_seconds=ended - started)
                row["peak_memory"] = merge_peaks(row["peak_memory"], {"process_rss_bytes": process_rss(os.getpid())})
                if result is not None:
                    row.update(chosen_backend=result.get("backend", {}).get("id"),
                               native_elapsed_seconds=result.get("elapsed_seconds"),
                               native_compute_seconds=result.get("compute_seconds"),
                               output_size=output_size(result))
                    if row['chosen_backend'] != decision.get('chosen_backend'):
                        row.update(selection_probability=None, probabilities={}, policy_warning='backend_contract_violation')
                    # Only report a separate transfer/preparation measurement
                    # when the native runtime actually provides one.
                    row["preparation_seconds"] = result.get("preparation_seconds")
                row["fallback_chain"] = [*context.get("fallback_chain", []), dict(run_id=row["run_id"],
                    backend=row["chosen_backend"], outcome=outcome, runtime_seconds=row["runtime_seconds"])]
                row["fallback_eligible"] = (row["selector_active"] and not row["attempt_index"]
                    and outcome in {"timeout", "oom"} and row["execution_started"])
                if row["fallback_eligible"] and context["step_deadline"] is not None and context["step_deadline"] - ended < 60:
                    row.update(fallback_eligible=False, fallback_skipped="fewer_than_60_seconds_remain")
                event({"event": "native_finished", "record": row})
            except Exception:
                event({"event": "telemetry_warning", "code": "telemetry_finalize_failed"})


def run_observed(run, problem, graph, *, context, step_id, emit, **kwargs):
    from graphmine.contracts import Budget

    started = time.monotonic()
    budget = kwargs.get("budget") or Budget()
    limit = minimum_limit(budget.timeout_seconds, context.get("job_timeout_seconds"))
    context = dict(context, decision_id=str(uuid4()), step_timeout_seconds=limit,
                   step_deadline=started + limit if limit is not None else None, attempt_index=0)
    last = None

    def event(value):
        nonlocal last
        if value.get("event") == "native_finished":
            last = value["record"]
        emit(value)

    try:
        return _run_attempt(run, problem, graph, context=context, step_id=step_id, emit=event,
                            started=started, **kwargs)
    except Exception as error:
        if last is None or not last.get("fallback_eligible"):
            if last and last.get("fallback_skipped"):
                raise TimeoutError("The step has fewer than 60 seconds left; no fallback can fit within its deadline") from error
            raise
        remaining = remaining_seconds(context["step_deadline"])
        if remaining is not None and remaining < 60:
            raise TimeoutError("The step has fewer than 60 seconds left; fallback was skipped") from error
        context.update(attempt_index=1, attempted_backends=[last["chosen_backend"]], fallback_chain=last["fallback_chain"])
        kwargs["budget"] = replace(budget, timeout_seconds=remaining)
        # Exactly one retry. Its failure propagates; it cannot enter this block
        # again, and native preflight excludes the first backend explicitly.
        return _run_attempt(run, problem, graph, context=context, step_id=step_id, emit=event,
                            started=time.monotonic(), **kwargs)


def install():
    """Called once by the agent bootstrap, before graphmine.worker imports."""
    import json
    import graphmine.workflows as workflows

    original_execute, original_run = workflows.execute_workflow, workflows.run
    context = json.loads(os.environ.get("GRAPHMINE_BACKEND_RUN_CONTEXT", "{}"))
    import hashlib
    from pathlib import Path

    try:
        context["admission_fingerprint"] = hashlib.sha256(
            (Path(os.environ.get("GRAPHMINE_REPOSITORY_ROOT", str(Path(__file__).resolve().parents[3]))) /
             "catalog/native_execution_evidence.json").read_bytes()).hexdigest()
    except OSError:
        # The worker's mandatory evidence gate returns its precise rejection
        # before any step runs. An absent fingerprint can never enable live mode.
        context["admission_fingerprint"] = None

    def execute(plan, inputs, *, emit=None, **kwargs):
        current = None
        steps = {s["id"]: s for s in plan.get("steps", [])}

        def event(value):
            nonlocal current
            if value.get("event") == "step_started":
                current = value["step"]
            if emit:
                emit(value)

        def observed(problem, graph, **run_kwargs):
            from graphmine.exceptions import GraphMineError
            from .attempt import run as isolated_run

            step = steps.get(current, {})
            def invoke(*args, **options):
                return isolated_run(*args, response_limit=context.get("max_result_bytes"), **options)

            try:
                return run_observed(invoke, problem, graph, context={
                    **context, "requested_device": step.get("device", plan.get("device", "auto"))},
                    step_id=current, emit=event, **run_kwargs)
            except (TimeoutError, MemoryError) as error:
                failure = GraphMineError(str(error))
                failure.code = "timeout" if isinstance(error, TimeoutError) else "out_of_memory"
                raise failure from error

        workflows.run = observed
        try:
            return original_execute(plan, inputs, emit=event, **kwargs)
        finally:
            workflows.run = original_run

    workflows.execute_workflow = execute
