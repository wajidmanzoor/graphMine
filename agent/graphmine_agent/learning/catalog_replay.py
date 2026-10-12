"""Capture and regrade complete, isolated current-catalog development workflows."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

import httpx

from ..analysis import prepare_analysis, validate_statement, validate_vega_spec
from ..answers import build_answer
from ..catalog import Catalog
from ..history import HistoryStore
from ..models import ExecutionPlan, GroundedStatement, utc_now
from ..terminal import ClientError, Terminal, agent_client
from ..visualization import answer_visualizations, sanitize_visualizations
from .catalog_grade import grade_output
from .catalog_suite import digest, load_suite
from .teacher import local_endpoint

VERSION = "current-catalog-workflow-v1"
MAX_REPORT_BYTES = 32 * 1024 * 1024
DIMENSIONS = (
    "input_binding",
    "status",
    "initial_routing",
    "planning",
    "execution",
    "numerical_checks",
    "exact_numerical",
    "grounding",
    "presentation",
)
FALLBACK_NOTICE = "The language model was unavailable or returned an invalid response. These findings and views are computed directly from the result and original data."
SOURCE_FILES = (
    "api.py",
    "config.py",
    "history.py",
    "database.py",
    "ownership.py",
    "agent_service.py",
    "llm.py",
    "models.py",
    "planning.py",
    "profiles.py",
    "graph_store.py",
    "graph_context.py",
    "execution.py",
    "jobs.py",
    "answers.py",
    "analysis.py",
    "presentation.py",
    "visualization.py",
    "terminal.py",
    "learning/catalog_replay.py",
    "learning/catalog_compare.py",
    "learning/catalog_grade.py",
    "learning/catalog_reference.py",
    "learning/oracles.py",
)


def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def source_bindings():
    root = Path(__file__).parent.parent
    return {name: HistoryStore.digest(root / name) for name in SOURCE_FILES}


def run_profile(settings):
    return {
        "base_model": settings.llm_model,
        "planner_model": settings.llm_planner_model or settings.llm_model,
        "analyst_model": settings.llm_analyst_model or settings.llm_model,
        "dual_adapters_active": settings.dual_adapters_active,
        "routing_model": settings.active_routing_model,
        "routing_adapter_active": settings.routing_adapter_active,
        "routing_adapter_sha256": settings.llm_route_adapter_sha256,
        "routing_contract": settings.routing_contract_version,
        "deployment_version": settings.deployment_version,
        "model_weights_verified_by_harness": False,
        "gpu_assignment": {
            "llm_gpu_uuid": settings.llm_gpu_uuid,
            "graph_gpu_uuid": settings.graph_gpu_uuid,
            "allow_shared_gpu": settings.allow_shared_gpu,
        },
        "resource_limits": {
            name: getattr(settings, name)
            for name in (
                "max_upload_bytes",
                "max_concurrent_uploads",
                "max_pending_jobs",
                "max_result_bytes",
                "job_timeout_seconds",
            )
        },
        "decoding": {
            name: getattr(settings, name)
            for name in (
                "llm_route_reasoning_effort",
                "llm_plan_reasoning_effort",
                "llm_analyst_reasoning_effort",
                "llm_route_max_tokens",
                "llm_plan_max_tokens",
                "llm_analyst_max_tokens",
            )
        },
        "native_binary_sha256": HistoryStore.digest(settings.graphmine_binary)
        if settings.graphmine_binary.is_file()
        else None,
    }


def _intent_issues(expected, actual):
    issues = []
    if Counter(map(digest, actual.get("filters", []))) != Counter(
        map(digest, expected["filters"])
    ):
        issues.append("The selected record filters changed")
    for name in (
        "requires_edge_weights",
        "requires_direction",
        "weight_attribute",
        "pattern_vertex_count",
        "pattern_edges",
        "time_unit",
        "time_window",
    ):
        if (
            actual.get(
                name,
                []
                if name == "pattern_edges"
                else False
                if name.startswith("requires_")
                else None,
            )
            != expected[name]
        ):
            issues.append(
                f"Intent annotation {name} differs from the proposed contract"
            )
    if (
        expected.get("weight_usage") == "path_length"
        and actual.get("weight_usage") != "path_length"
    ):
        issues.append("Requested path-cost meaning was lost")
    return issues


def grade_capture(catalog, case, capture):
    """Recompute grades; saved pass flags never constitute evidence."""
    dimensions = dict.fromkeys(DIMENSIONS)
    issues = {}

    def check(name, failures):
        failures = list(failures)
        dimensions[name] = not failures
        if failures:
            issues[name] = failures

    task = case["task"]
    response = capture.get("outcome", {}).get("response") or {}
    jobs = capture.get("jobs", [])
    result = capture.get("outcome", {}).get("result") or {}
    uploaded = capture.get("inputs", {})
    graph_file = uploaded.get("graph") or {}
    binding_errors = []
    if capture.get("outcome", {}).get("query") != task["question"]:
        binding_errors.append("The submitted question differs from the frozen case")
    if (
        graph_file.get("sha256") != hashlib.sha256(encoded(case["graph"])).hexdigest()
        or graph_file.get("role") != "graph"
    ):
        binding_errors.append("Uploaded graph does not match the frozen case bytes")
    if graph_file.get("session_id") != capture.get("session_id"):
        binding_errors.append("Uploaded graph belongs to another session")
    expected_names = set(case["attachments"])
    if set(uploaded.get("auxiliary", {})) != expected_names:
        binding_errors.append("The attached input roles changed")
    for name, expected in case["attachments"].items():
        actual = uploaded.get("auxiliary", {}).get(name, [])
        if len(actual) != len(expected) or any(
            row.get("sha256") != hashlib.sha256(encoded(wanted["content"])).hexdigest()
            or row.get("role") != wanted["role"]
            or row.get("session_id") != capture.get("session_id")
            for row, wanted in zip(actual, expected)
        ):
            binding_errors.append(
                f"Attached input {name} does not match the frozen case"
            )
    check("input_binding", binding_errors)
    status_errors = []
    if response.get("planning_status") != task["expected_status"]:
        status_errors.append(
            f"Expected {task['expected_status']}, got {response.get('planning_status')}"
        )
    if capture.get("outcome", {}).get("error"):
        status_errors.append(capture["outcome"]["error"])
    check("status", status_errors)
    routes = capture.get("routes", [])
    if routes:
        route = routes[0]
        errors = []
        if route.get("problem_id") != task["problem_id"]:
            errors.append("Wrong initial problem identity")
        if task["expected_status"] == "ready" and (
            route.get("operation_id") != task["operation_id"]
            or not route.get("supported")
        ):
            errors.append("Wrong initial executable operation")
        errors.extend(_intent_issues(task["intent"], route.get("intent") or {}))
        check("initial_routing", errors)
    else:
        check("initial_routing", ["No parsed initial routing response was captured"])
    if task["expected_status"] != "ready":
        check(
            "execution",
            ["A non-executable case created jobs or a result"]
            if jobs or response.get("job_id") or response.get("job_ids") or result
            else [],
        )
        plan_errors = (
            ["A non-ready response carried a plan"] if response.get("plan") else []
        )
        final_route = routes[-1] if routes else {}
        if final_route.get("problem_id") != task["problem_id"] or (
            final_route.get("operation_id") not in {None, task["operation_id"]}
        ):
            plan_errors.append("The refusal or clarification concerns another problem")
        plan_errors.extend(
            _intent_issues(task["intent"], final_route.get("intent") or {})
        )
        check("planning", plan_errors)
        return _grade_result(dimensions, issues)
    plan_data = (
        jobs[0].get("plan", {}) if len(jobs) == 1 else response.get("plan") or {}
    )
    plan_errors = []
    if (
        plan_data.get("operation_id") != task["operation_id"]
        or plan_data.get("problem_id") != task["problem_id"]
    ):
        plan_errors.append("The final plan chooses a different computation")
    if plan_data.get("graph_id") != graph_file.get("id") or plan_data.get(
        "session_id"
    ) != capture.get("session_id"):
        plan_errors.append("The final plan uses a different dataset or session")
    for name, value in task["parameters"].items():
        if plan_data.get("parameters", {}).get(name) != value:
            plan_errors.append(f"Semantic parameter {name} changed")
    if not set(task["optional_outputs"]) <= set(plan_data.get("optional_outputs", [])):
        plan_errors.append("Requested output selection is incomplete")
    plan_errors.extend(
        _intent_issues(task["intent"], plan_data.get("application_intent") or {})
    )
    for name, files in uploaded.get("auxiliary", {}).items():
        if Counter(plan_data.get("auxiliary_inputs", {}).get(name, [])) != Counter(
            row["id"] for row in files
        ):
            plan_errors.append(f"The plan uses different {name} inputs")
    check("planning", plan_errors)
    execution_errors = []
    if len(jobs) != 1 or jobs[0].get("status") != "completed":
        execution_errors.append("Expected exactly one completed computation")
    elif result.get("job_id") != jobs[0].get("id") or jobs[0].get(
        "result_id"
    ) != result.get("id"):
        execution_errors.append("Result/job binding is broken")
    if (
        result.get("session_id") != capture.get("session_id")
        or result.get("operation_id") != task["operation_id"]
    ):
        execution_errors.append("Result belongs to another session or operation")
    if len(jobs) == 1 and response.get("job_id") != jobs[0].get("id"):
        execution_errors.append("The reply points to a different job")
    check("execution", execution_errors)
    if execution_errors:
        return _grade_result(dimensions, issues)
    numerical = grade_output(catalog, case, result.get("payload", {}).get("output"))
    check("numerical_checks", numerical["issues"])
    if numerical["verification_scope"] == "exact_enumeration":
        dimensions["exact_numerical"] = numerical["numerical_accuracy_certified"]
    try:
        expected_answer = build_answer(
            case["graph"],
            ExecutionPlan.model_validate(plan_data),
            result["payload"],
            source_hash=graph_file["sha256"],
        )
        if "analysis_datasets" in result.get("answer", {}):
            prepare_analysis(expected_answer)
        if result.get("interpretation_source") == "fallback":
            expected_answer["limitations"].append(FALLBACK_NOTICE)
        check(
            "grounding",
            ["Materialized answer differs from recomputed source-bound facts"]
            if result.get("answer") != expected_answer
            else [],
        )
        interpretation = result.get("interpretation") or {}
        facts = {row["statement"] for row in expected_answer["facts"]}
        presentation_errors = []
        explained = set()
        facts_by_id = {row["id"]: row for row in expected_answer["facts"]}
        for statement in interpretation.get("explanation", []):
            value = GroundedStatement.model_validate(statement)
            validate_statement(value, facts_by_id)
            explained.add(value.text)
        if (
            interpretation.get("summary") not in facts | explained
            or not set(interpretation.get("findings", [])) <= facts
        ):
            presentation_errors.append("Displayed findings are not computed facts")
        if interpretation.get("limitations") != expected_answer["limitations"]:
            presentation_errors.append(
                "Displayed limitations differ from computed scope"
            )
        expected_views = sanitize_visualizations(
            answer_visualizations(expected_answer),
            {"answer": expected_answer, **result["payload"]},
        )
        actual_views = interpretation.get("visualizations", [])
        expected_by_id = {
            view.id: view.model_dump(mode="json") for view in expected_views
        }
        actual_by_id = {view["id"]: view for view in actual_views}
        if len(actual_by_id) != len(actual_views) or any(
            actual_by_id.get(key) != value for key, value in expected_by_id.items()
        ):
            presentation_errors.append(
                "Required deterministic views are missing or changed"
            )
        for key, view in actual_by_id.items():
            if key in expected_by_id:
                continue
            if (
                view.get("type") != "vega_lite"
                or not view.get("evidence_ids")
                or not set(view["evidence_ids"]) <= facts_by_id.keys()
            ):
                raise ValueError("Unknown or ungrounded custom view")
            spec = dict(view["vega_lite"])
            bound = spec.pop("datasets", None)
            used = validate_vega_spec(
                spec, expected_answer.get("analysis_datasets", {})
            )
            if bound != {
                name: expected_answer["analysis_datasets"][name]["rows"]
                for name in used
            }:
                raise ValueError("Custom visualization data differs from computed rows")
        check("presentation", presentation_errors)
    except (KeyError, TypeError, ValueError) as error:
        check("grounding", [f"Cannot recompute materialized answer: {error}"])
        check("presentation", ["No verifiable presentation"])
    return _grade_result(dimensions, issues, numerical)


def _grade_result(dimensions, issues, numerical=None):
    required = [
        value
        for name, value in dimensions.items()
        if name not in {"initial_routing", "exact_numerical"} and value is not None
    ]
    return {
        "dimensions": dimensions,
        "issues": issues,
        "workflow_contract_passed": bool(required) and all(required),
        "numerical": numerical,
        "scope": "Match to unreviewed development contracts; numerical check scope is explicit. This is not human usefulness or generalization accuracy.",
    }


def summarize_report(report):
    expected = len(report["case_ids"]) * report["repeats"]
    rows = report["captures"]
    summary = {
        "expected_trials": expected,
        "captured_trials": len(rows),
        "complete": len(rows) == expected and bool(report.get("finished_at")),
        "workflow_contract_passes": sum(
            row["grade"]["workflow_contract_passed"] for row in rows
        ),
        "missing_trials": expected - len(rows),
        "dimensions": {},
        "by_operation": {},
    }
    for name in DIMENSIONS:
        values = [
            row["grade"]["dimensions"][name]
            for row in rows
            if row["grade"]["dimensions"][name] is not None
        ]
        summary["dimensions"][name] = {"passed": sum(values), "graded": len(values)}
    for row in rows:
        group = summary["by_operation"].setdefault(
            row["operation_id"] or row["problem_id"], {"passed": 0, "captured": 0}
        )
        group["captured"] += 1
        group["passed"] += int(row["grade"]["workflow_contract_passed"])
    return summary


async def evaluate_suite(
    settings, *, suite_path, output, data_dir, label, case_ids=None, repeats=1
):
    if not settings.llm_enabled:
        raise ValueError(
            "Live current-catalog evaluation requires a configured language model"
        )
    local_endpoint(settings.llm_base_url)
    if settings.routing_adapter_active:
        local_endpoint(settings.llm_route_base_url)
    return await _capture_suite(
        settings,
        suite_path=suite_path,
        output=output,
        data_dir=data_dir,
        label=label,
        case_ids=case_ids,
        repeats=repeats,
        capture_kind="live_agent",
    )


async def _capture_suite(
    settings,
    *,
    suite_path,
    output,
    data_dir,
    label,
    case_ids=None,
    repeats=1,
    capture_kind="cpu_fixture",
):
    """Shared capture path; the public CLI only exposes live_agent mode."""
    if type(repeats) is not int or not 1 <= repeats <= 3:
        raise ValueError("Choose one to three trials per case")
    if not isinstance(label, str) or not label.strip() or len(label) > 100:
        raise ValueError("Provide a configuration label of 1 to 100 characters")
    if capture_kind not in {"live_agent", "cpu_fixture"}:
        raise ValueError("Unknown capture kind")
    if (
        output.exists()
        or data_dir.exists()
        or data_dir.resolve().is_relative_to(settings.data_root.resolve())
    ):
        raise ValueError(
            "Use a new report and runtime directory outside the pilot data root"
        )
    catalog = Catalog(settings)
    suite = load_suite(catalog, suite_path)
    known = {case["id"] for case in suite["cases"]}
    if case_ids is not None and (
        not case_ids or len(set(case_ids)) != len(case_ids) or set(case_ids) - known
    ):
        raise ValueError("Select at least one known case ID")
    cases = [
        case for case in suite["cases"] if case_ids is None or case["id"] in case_ids
    ]
    report = {
        "version": VERSION,
        "label": label,
        "capture_kind": capture_kind,
        "started_at": utc_now().isoformat(),
        "finished_at": None,
        "suite_sha256": digest(suite),
        "catalog_sha256": suite["catalog_sha256"],
        "case_ids": [case["id"] for case in cases],
        "repeats": repeats,
        "profile": run_profile(settings),
        "source_sha256": source_bindings(),
        "label_source": suite["label_source"],
        "human_review": "unreviewed",
        "training_eligible": False,
        "captures": [],
    }

    def save():
        report["summary"] = summarize_report(report)
        HistoryStore.write(output, report)

    data_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8"):
        pass
    save()
    async with agent_client(
        replace(settings, history_directory=None), data_dir=data_dir
    ) as (client, history):
        for trial in range(1, repeats + 1):
            for case in cases:
                terminal = Terminal(
                    client,
                    history_root=history,
                    output=lambda _: None,
                    timeout_seconds=settings.job_timeout_seconds + 60,
                )
                await terminal.start(
                    domain_id=case["domain_id"],
                    title=f"Catalog development: {case['id']} trial {trial}",
                )
                input_root = data_dir / "fixture-inputs" / case["id"] / str(trial)
                input_root.mkdir(parents=True)

                async def upload(
                    content, role, name, *, input_root=input_root, terminal=terminal
                ):
                    path = input_root / f"{name}.json"
                    path.write_bytes(encoded(content))
                    return await terminal.load(path, role=role)

                inputs = {
                    "graph": await upload(case["graph"], "graph", "dataset"),
                    "auxiliary": {},
                }
                for name, attachments in case["attachments"].items():
                    inputs["auxiliary"][name] = [
                        await upload(item["content"], item["role"], f"{name}-{i}")
                        for i, item in enumerate(attachments)
                    ]
                started = time.monotonic()
                try:
                    outcome = await terminal.ask(case["task"]["question"])
                except (ClientError, httpx.HTTPError) as error:
                    outcome = {**terminal.last_outcome, "error": str(error)}
                jobs = await terminal.request(
                    "GET", "/api/jobs", params={"session_id": terminal.session_id}
                )
                active = [
                    job
                    for job in jobs
                    if job["status"] in {"queued", "running", "interpreting"}
                ]
                if active:
                    for job in active:
                        await terminal.request("DELETE", f"/api/jobs/{job['id']}")
                    outcome["error"] = outcome.get(
                        "error",
                        "Evaluation ended with unfinished jobs; cancellation requested",
                    )
                events = list(HistoryStore(history).session_events(terminal.session_id))
                capture = {
                    "case_id": case["id"],
                    "case_sha256": case["sha256"],
                    "trial": trial,
                    "operation_id": case["task"]["operation_id"],
                    "problem_id": case["task"]["problem_id"],
                    "session_id": terminal.session_id,
                    "inputs": inputs,
                    "outcome": outcome,
                    "jobs": jobs,
                    "routes": [
                        event["data"]["value"]
                        for event in events
                        if event["type"] == "model.parsed"
                        and event["data"]["schema"] == "RouteDecision"
                    ],
                    "model_providers": sorted(
                        {
                            event["data"]["provider"]
                            for event in events
                            if event["type"] == "model.input"
                        }
                    ),
                    "latency_seconds": time.monotonic() - started,
                    "interpretation_source": (outcome.get("result") or {}).get(
                        "interpretation_source"
                    ),
                }
                capture["evidence_sha256"] = digest(capture)
                capture["grade"] = grade_capture(catalog, case, capture)
                report["captures"].append(capture)
                save()
    report["finished_at"] = utc_now().isoformat()
    save()
    return report
