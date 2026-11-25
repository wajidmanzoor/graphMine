#!/usr/bin/env python3
"""Measure frozen, assistant-labelled lane cases through the normal agent path.

This is a development regression baseline, not a human-labelled accuracy study.
Labels never enter model requests. Each case has its own session and makes one
attempt; product retries remain visible. Results are checkpointed after each case.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "python/graphmine"))
from graphmine_agent.llm_power import model_run_scope
LANES = {"reply", "describe_input", "explain", "view", "lookup",
         "needs_information", "options", "calculate", "unsupported"}
SUITE = ROOT / "agent/evaluation/lanes/questions.json"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(path)


def load_suite(path):
    suite = json.loads(path.read_text())
    graphs = {}
    for name, fixture in suite["fixtures"].items():
        source = (path.parent / fixture["path"]).resolve()
        if not source.is_relative_to(path.parent.resolve()):
            raise ValueError("Fixture must be inside the suite directory")
        if file_digest(source) != fixture["sha256"]:
            raise ValueError(f"Fixture changed: {name}")
        graph = json.loads(source.read_text())
        if fixture.get("undirected_projection"):
            graph["graph"]["directed"] = False
        if fixture.get("side_types"):
            for vertex in graph["vertices"]:
                vertex.setdefault("attributes", {})["side"] = fixture["side_types"][vertex["type"]]
        graphs[name] = graph
    cases = suite["cases"]
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Case IDs must be unique")
    if {c["expected"]["lane"] for c in cases} != LANES:
        raise ValueError("Question set must cover all nine requested lanes")
    for case in cases:
        if case["fixture"] not in graphs or not case["question"].strip():
            raise ValueError(f"Invalid case: {case['id']}")
        if case["expected"]["lane"] in {"view", "explain"} and not case.get("previous"):
            raise ValueError("Saved-result lanes need a real previous workflow")
        if case["expected"]["lane"] == "calculate" and not case.get("selected_option"):
            raise ValueError("Calculate cases must represent an explicitly picked card")
    return suite, graphs


def identities(values):
    return {digest(value) for value in values}


def check_port(check, result):
    """Compare actual complete ports with answers fixed before the model run."""
    port = (result.get("ports") or {}).get(check["port"])
    if not port or port.get("complete") is not True:
        return False
    value, expected = port["value"], check["value"]
    kind = check["kind"]
    if kind == "equal":
        return digest(value) == digest(expected)
    if kind == "set":
        return identities(value) == identities(expected)
    if kind == "groups":
        return {frozenset(identities(g["vertices"])) for g in value} == {
            frozenset(identities(g)) for g in expected}
    if kind == "bicliques":
        def pairs(rows):
            return {frozenset((frozenset(identities(row["left_vertices"])),
                               frozenset(identities(row["right_vertices"])))) for row in rows}
        return pairs(value) == pairs(expected)
    if kind == "argmax":
        field = port.get("score_field", "score")
        best = max(row[field] for row in value)
        return identities(row["vertex"] for row in value if row[field] == best) == identities(expected)
    if kind == "scores":
        field = port.get("score_field", "score")
        actual = {digest(row["vertex"]): row[field] for row in value}
        want = {digest(row["vertex"]): row["score"] for row in expected}
        return actual.keys() == want.keys() and all(
            math.isclose(actual[key], want[key], abs_tol=1e-7, rel_tol=1e-7) for key in want)
    raise ValueError(f"Unknown oracle kind: {kind}")


def check_results(checks, saved):
    by_problem = defaultdict(list)
    for step in saved.get("steps", {}).values():
        result = step.get("result") or {}
        if step.get("status") == "completed":
            by_problem[result.get("problem")].append(result)
    return [{"problem": check["problem"], "port": check["port"],
             "passed": any(check_port(check, result) for result in by_problem[check["problem"]])}
            for check in checks]


class Measurements:
    """Use the existing capture callbacks, retaining only call metrics, never prompts.

    The other capture hooks deliberately do nothing: this isolated evaluation is
    not a source of training examples or permanent user captures.
    """
    def __init__(self):
        self.calls = defaultdict(list)

    def model_call(self, session_id, *, stage, request, response, output, outcome,
                   seconds, turn_id=None, **kwargs):
        body = response or {}
        choices = body.get("choices") or [{}]
        row = {"stage": stage, "model": request.get("model"),
               "samples": request.get("n", 1),
               "seconds": round(seconds, 3), "outcome": outcome,
               "finish_reason": choices[0].get("finish_reason"),
               "usage": body.get("usage"), "turn_id": turn_id}
        if stage == "route" and isinstance(output, dict):
            row["intent"] = output.get("intent")
            row["problems"] = output.get("problems", [])
        self.calls[session_id].append(row)

    def event(self, *args, **kwargs):
        pass

    workflow = dataset = result = event


def usage_totals(calls):
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    known = {key: sum((row.get("usage") or {}).get(key, 0) or 0 for row in calls) for key in keys}
    missing = sum(not isinstance(row.get("usage"), dict) or
                  any(not isinstance(row["usage"].get(key), int) for key in keys) for row in calls)
    return {"model_calls": len(calls), "model_samples": sum(row.get("samples", 1) for row in calls), "by_stage": dict(Counter(row["stage"] for row in calls)),
            "tokens": known if not missing else {key: None for key in keys},
            "known_tokens": known, "calls_missing_usage": missing}


def observed_lane(response, calls):
    if response.get("lane") in LANES:
        return response["lane"]
    status = response.get("status")
    if status in LANES:
        return status
    if status == "ready":
        return "calculate"
    if status == "answered" and response.get("answer", {}).get("workflow_id"):
        return "explain"
    routes = [row.get("intent") for row in calls if row["stage"] == "route"]
    return routes[-1] if routes else "unclassified"


def observed_problems(response, calls):
    plan = response.get("plan") or {}
    if plan.get("steps"):
        return [step["problem"] for step in plan["steps"]]
    options = response.get("options") or []
    if options:
        first = options[0]
        return first.get("problems") or ([first["problem"]] if first.get("problem") else [])
    routes = [row for row in calls if row["stage"] == "route"]
    return routes[-1].get("problems", []) if routes else []


def grade(case, response, calls, saved=None, error=None):
    expected = case["expected"]
    lane = observed_lane(response, calls)
    problems = observed_problems(response, calls)
    choices = expected.get("problems")
    problem_match = choices is None or any(sorted(problems) == sorted(choice) for choice in choices)
    checks = check_results(case.get("checks", []), saved or {})
    completed = bool(saved and saved.get("status") == "completed" and saved.get("complete") is True)
    no_run = saved is None
    target, status = expected["lane"], response.get("status")
    if target in {"calculate", "lookup"}:
        behavior = completed and all(row["passed"] for row in checks)
    elif target == "options":
        options = response.get("options") or []
        candidates = [digest({k: option.get(k) for k in ("problem", "problems", "parameters")})
                      for option in options]
        behavior = no_run and 1 <= len(options) <= 3 and len(set(candidates)) == len(options) and not response.get("plan")
    elif target == "view":
        view = response.get("view") or {}
        behavior = no_run and all(view.get(key) == value for key, value in expected["view"].items())
    elif target == "explain":
        facts = (response.get("answer") or {}).get("facts", [])
        text = " ".join(fact.get("statement", "") for fact in facts)
        behavior = no_run and bool(facts) and all(re.search(pattern, text, re.I) for pattern in expected["fact_patterns"])
    elif target == "reply":
        answer = response.get("answer") or response
        behavior = no_run and bool(answer.get("citations")) and not response.get("plan")
    elif target == "describe_input":
        answer = response.get("answer") or {}
        facts = answer.get("facts", [])
        # Expected property/value pairs are frozen; prose alone is not graded as
        # verified data. Later lanes can emit them alongside their display text.
        behavior = no_run and any(fact.get("property") == expected["property"] and
                                 digest(fact.get("value")) == digest(expected["value"]) for fact in facts)
    else:
        behavior = no_run and status == target and not response.get("plan") and bool(response.get("message"))
    return {"lane_chosen": lane, "problems": problems,
            "lane_match": lane == target, "problem_match": problem_match,
            "behavior_match": bool(behavior), "execution_completed": completed,
            "result_checks": checks,
            "success": not error and lane == target and problem_match and bool(behavior)}


def check_grounding(response, events, lane):
    """Audit displayed answers against evidence events, independently of flags."""
    from graphmine_agent.answer_grounding import Evidence
    required = lane in {'reply', 'describe_input', 'explain', 'view', 'lookup', 'calculate'}
    turn = response.get('turn_id')
    current = [event for event in events if event.payload.get('turn_id') == turn]
    sources = [source for event in current if event.type == 'workflow.evidence' for source in event.payload.get('sources', [])]
    answers = [response['answer']] if response.get('answer') else []
    final = [event.payload for event in current if event.type == 'workflow.answer']
    if final:
        answers.append(final[-1])
    errors = ['No grounded answer was returned.'] if required and not answers else []
    for answer in answers:
        ledger = Evidence(turn)
        for citation in answer.get('citations', []):
            source = next((row for row in sources if row.get('turn_id') == turn and
                           all(row.get(key) == citation.get(key) for key in ('id', 'kind', 'ref'))), None)
            if source:
                ledger.record(source['tool'], [source])
        errors.extend(ledger.check(answer, turn_id=turn, data_answer=lane != 'reply'))
    return {'required': required, 'answers_checked': len(answers), 'passed': not errors,
            'errors': errors, 'fallback': any(answer.get('grounding', {}).get('fallback') for answer in answers),
            'attempts': sum(answer.get('grounding', {}).get('attempts', 0) for answer in answers)}


def summarize(rows):
    by_lane = {}
    for lane in sorted(LANES):
        cases = [row for row in rows if row["expected_lane"] == lane]
        if cases:
            by_lane[lane] = {"cases": len(cases), "successes": sum(row["success"] for row in cases),
                             "lane_matches": sum(row["lane_match"] for row in cases),
                             "model_calls": sum(row["model_calls"] for row in cases),
                             "median_seconds": round(statistics.median(row["seconds"] for row in cases), 3)}
    calls = [call for row in rows for call in row["calls"]]
    grounded = [row['grounding'] for row in rows if row.get('grounding', {}).get('required')]
    return {"cases": len(rows), "successes": sum(row["success"] for row in rows),
            "grounding": {'required': len(grounded), 'passed': sum(row['passed'] for row in grounded),
                          'fallbacks': sum(row['fallback'] for row in grounded)},
            "lane_matches": sum(row["lane_match"] for row in rows),
            "seconds": round(sum(row["seconds"] for row in rows), 3),
            **usage_totals(calls), "by_lane": by_lane}


def one_step(spec):
    return {"version": 1, "device": "cpu", "steps": [{
        "id": "answer", "problem": spec["problem"], "input": {"input": "main"},
        "parameters": spec.get("parameters", {}), "bindings": {}}]}


def verify_oracles(suite, graphs, native_path):
    from graphmine.native import NativeLibrary
    native = NativeLibrary(native_path)
    rows = []
    for case in suite["cases"]:
        spec = case.get("reference") or case.get("previous")
        if not spec:
            continue
        graph = graphs[case["fixture"]]
        native.validate(spec["problem"], graph, parameters=spec.get("parameters", {}), device="cpu")
        result = native.run(spec["problem"], graph, parameters=spec.get("parameters", {}), device="cpu")
        checks = case.get("checks") or case.get("previous_checks") or []
        valid = [check_port(check, result) for check in checks]
        if not checks or not all(valid):
            raise ValueError(f"Frozen reference answer failed: {case['id']}: {valid}")
        rows.append({"id": case["id"], "problem": spec["problem"], "checks": valid})
    return {"suite_sha256": digest(suite), "implementation_sha256": native.catalog()["implementation_sha256"],
            "passed": len(rows), "cases": rows}


async def finish(service, workflow):
    if workflow["status"] == "awaiting_review":
        workflow = await service.start(workflow["id"], workflow["validation"]["workflow_hash"], workflow["revision"])
    task = service.tasks.get(workflow["id"])
    if task:
        await task
    # Serial cases: all currently scheduled answer tasks belong to this case.
    await asyncio.gather(*list(service.answer_tasks))
    return service.result(workflow["id"])


@model_run_scope
async def evaluate(settings, suite, graphs, report, output):
    from graphmine_agent.analytics import AnalyticsService, WorkflowRequest
    from graphmine_agent.analytics_planning import AnalyticsPlanner, PlanningRequest
    from graphmine_agent.database import Database
    from graphmine_agent.graph_store import GraphStore
    from graphmine_agent.jobs import EventBus
    from graphmine_agent.models import FileRole, SessionRecord

    database = Database(settings.database_path)
    measurements = Measurements()
    database.capture = measurements
    store = GraphStore(settings, database)
    events = EventBus(database)
    service = AnalyticsService(settings, database, store, events)
    planner = AnalyticsPlanner(settings, service, events)
    service.open()
    try:
        caps = await service.capabilities()
        report["native_implementation_sha256"] = caps["implementation_sha256"]
        for case in suite["cases"]:
            # Setup is outside the measured turn; previous answers are genuine
            # validated native results, never model-authored fixture prose.
            setup_started = time.monotonic()
            session = database.create_session(SessionRecord(domain_id="general", title=case["id"]))
            graph = graphs[case["fixture"]]
            uploaded = store.ingest(session_id=session.id, role=FileRole.graph,
                                    filename=case["fixture"] + ".json", content=json.dumps(graph).encode())
            inputs = {"main": {"file_id": uploaded.id, "kind": "graph"}}
            previous = None
            if case.get("previous"):
                previous = await service.create(session.id, WorkflowRequest(
                    mode="normal", plan=one_step(case["previous"]), inputs=inputs,
                    evaluation_id=suite["version"] + "/setup/" + case["id"]))
                saved_previous = await finish(service, previous)
                assert all(row["passed"] for row in check_results(case["previous_checks"], saved_previous))
            setup_seconds = time.monotonic() - setup_started
            request = {"message": case["question"], "inputs": inputs, "device": "cpu", "mode": "normal"}
            if previous:
                request["previous_workflow_id"] = previous["id"]
            if case.get("selected_option"):
                request.update(case["selected_option"])
            response, saved, error = {}, None, None
            started = time.monotonic()
            started_at = datetime.now(UTC).isoformat()
            try:
                # Do not set PlanningRequest.evaluation_id: it disables existing
                # direct shortcuts and conversation handling. Isolation provides
                # the evaluation boundary without changing application behavior.
                async with asyncio.timeout(480):
                    response = await planner.plan(session.id, PlanningRequest(**request))
                    if response.get("status") == "ready":
                        workflow = await service.create(session.id, WorkflowRequest(
                            mode="normal", plan=response["plan"], inputs=response.get("inputs", inputs),
                            planning_turn_id=response["turn_id"], evaluation_id=suite["version"] + "/" + case["id"]))
                        saved = await finish(service, workflow)
            except Exception as exc:
                error = {"type": type(exc).__name__, "code": getattr(exc, "code", None), "message": str(exc)[:2000]}
            seconds = time.monotonic() - started
            calls = measurements.calls[session.id]
            row = {"id": case["id"], "question": case["question"], "fixture": case["fixture"],
                   "expected_lane": case["expected"]["lane"], "started_at": started_at,
                   "seconds": round(seconds, 3), "setup_seconds": round(setup_seconds, 3),
                   "status": response.get("status", "failed"), "calls": calls,
                   **usage_totals(calls), **grade(case, response, calls, saved, error),
                   "response": response, "error": error,
                   "grounding": check_grounding(response, database.events(session.id), observed_lane(response, calls)),
                   "workflow_status": saved.get("status") if saved else None,
                   "result_sha256": digest(saved) if saved else None}
            report["cases"].append(row)
            report["summary"] = summarize(report["cases"])
            write_json(output, report)
            print(json.dumps({key: row[key] for key in ("id", "expected_lane", "lane_chosen", "status", "success", "model_calls", "seconds")}), flush=True)
    finally:
        await service.close()


def source_files(suite_path):
    paths = [Path(__file__), suite_path, *sorted((ROOT / "agent/graphmine_agent").rglob("*.py")),
             *sorted((ROOT / "python/graphmine/graphmine").rglob("*.py")),
             ROOT / "catalog/native_execution_evidence.json", ROOT / "catalog/problem_requirements.json",
             ROOT / "catalog/agent_concepts.json", ROOT / "catalog/vague_terms.json"]
    calibration = ROOT / "catalog/option_calibration.json"
    if calibration.exists():
        paths.append(calibration)
    return {str(path.relative_to(ROOT)): file_digest(path) for path in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=SUITE)
    parser.add_argument("--output", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-oracles", action="store_true")
    action.add_argument("--live", action="store_true", help="Call the configured model using an isolated temporary store")
    args = parser.parse_args()
    args.suite = args.suite.resolve()
    if args.output.exists():
        parser.error("Output already exists; use a new path to preserve the earlier measurement")
    from graphmine_agent.config import Settings
    suite, graphs = load_suite(args.suite)
    settings = Settings.from_env(ROOT)
    oracles = verify_oracles(suite, graphs, settings.native_runtime_library)
    if args.check_oracles:
        write_json(args.output, oracles)
        return 0
    before = source_files(args.suite)
    report = {"version": "lane-baseline-v1", "status": "running", "created_at": datetime.now(UTC).isoformat(),
              "scope": suite["scope"], "suite_sha256": digest(suite), "source_files": before,
              "oracle_verification": oracles, "cases": [], "serial_requests": True,
              "measurement_notes": [
                  "One attempt per question, including product retries and answer composition; fixture setup is timed separately.",
                  "Real current lanes are recorded without translating calculation into lookup or options.",
                  "Selected-card request fields are sent unchanged; an unsupported request contract counts as a failure.",
                  "Data answers require structured evidence; prose semantics and general explanation quality are not human-reviewed.",
                  "Phase 5 grounding separately verifies final answer text against tool-evidence events from the same turn, without trusting checked flags.",
                  "No production writes, training captures, or persistent development configuration changes.",
                  "Observed timings include local server/cache conditions and are not controlled performance benchmarks."],
              "model": {"router": settings.analytics_router_model or settings.llm_model, "planner": settings.analytics_planner_model or settings.llm_model,
                        "answer": settings.analytics_answer_model or settings.llm_model,
                        "reasoning_effort": settings.analytics_reasoning_effort,
                        "route_thinking_token_budget": settings.analytics_route_thinking_token_budget,
                        "plan_thinking_token_budget": settings.analytics_thinking_token_budget,
                        "max_completion_tokens": settings.llm_plan_max_tokens,
                        "direct_plans": settings.analytics_direct_plans, "temperature": 0, "seed": 0,
                        "options": {"max_ranked_calculations": 3,
                                    "transport": "ranking from the route call; no separate option-sampling request"}}}
    write_json(args.output, report)
    with tempfile.TemporaryDirectory(prefix="graphmine-lane-baseline-") as directory:
        isolated = replace(settings, data_root=Path(directory), history_directory=None,
                           backup_directory=None, capture_enabled=False, accounts_enabled=False,
                           llm_enabled=True, analytics_gpu_uuids=(), job_timeout_seconds=90)
        try:
            asyncio.run(evaluate(isolated, suite, graphs, report, args.output))
        finally:
            report["sources_unchanged_during_run"] = before == source_files(args.suite)
            report["fixtures_unchanged_during_run"] = all(digest(graphs[name]) == digest(graph)
                for name, graph in load_suite(args.suite)[1].items())
            report["status"] = "completed" if len(report["cases"]) == len(suite["cases"]) else "interrupted"
            report["finished_at"] = datetime.now(UTC).isoformat()
            write_json(args.output, report)
    assert report["sources_unchanged_during_run"] and report["fixtures_unchanged_during_run"]
    print(json.dumps(report["summary"]), flush=True)
    # A baseline can be successfully measured while the product fails cases.
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
