"""Real API lifecycle with explicitly authored model and computation fixtures."""

from __future__ import annotations

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from graphmine_agent.learning import catalog_replay as replay
from graphmine_agent.learning.catalog_suite import write_suite
from graphmine_agent.models import (
    ApplicationIntent,
    PlanConfiguration,
    PlanDraft,
    RouteDecision,
)
from graphmine_agent.terminal import ClientError, Terminal, agent_client
from test_catalog_grade import authored_output


def fixture_client(cases):
    by_question = {case["task"]["question"]: case for case in cases}

    @asynccontextmanager
    async def client(settings, **kwargs):
        async with agent_client(settings, **kwargs) as (http, history):
            runtime = http._transport.app.state.runtime
            original = runtime.agent.model.generate

            async def generate(**kwargs):
                if kwargs["schema"] not in {RouteDecision, PlanDraft}:
                    return await original(**kwargs)
                case = by_question[kwargs["user_payload"]["message"]]
                task = case["task"]
                if kwargs["schema"] is RouteDecision:
                    supported = task["expected_status"] != "unsupported"
                    return RouteDecision(
                        problem_id=task["problem_id"],
                        operation_id=task["operation_id"] if supported else None,
                        supported=supported,
                        confidence=1,
                        explanation="Authored CPU workflow fixture.",
                        intent=ApplicationIntent.model_validate(task["intent"]),
                    )
                return PlanDraft(
                    status="ready",
                    message="Authored CPU workflow fixture.",
                    plan=PlanConfiguration(
                        parameters=task["parameters"],
                        optional_outputs=task["optional_outputs"],
                    ),
                )

            async def execute(plan, workspace):
                graph = runtime.graph_store.read_graph(plan.graph_id, plan.session_id)
                case = next(
                    item
                    for item in cases
                    if item["task"]["operation_id"] == plan.operation_id
                    and item["task"]["parameters"].items() <= plan.parameters.items()
                    and item["task"]["intent"]["filters"]
                    == [
                        entry.model_dump(mode="json")
                        for entry in plan.application_intent.filters
                    ]
                    and item["graph"]["graph"]["id"] == graph["graph"]["id"]
                )
                if case["tags"] == ["empty_filter"]:
                    output = {"count": 0, "cliques": [], "complete": True}
                elif case["tags"] == ["weak_connectivity"]:
                    ids = [row["id"] for row in case["graph"]["vertices"]]
                    output = {
                        "component_assignment": [
                            {"vertex": value, "component": int(i == 4)}
                            for i, value in enumerate(ids)
                        ],
                        "components": [ids[:4], ids[4:]],
                        "component_count": 2,
                        "component_sizes": [4, 1],
                    }
                else:
                    output = authored_output(case)
                return {
                    "ok": True,
                    "output": output,
                    "statistics": {},
                    "warnings": [],
                    "provenance": {"backend": "cpu-fixture", "test_double": True},
                }, ["cpu-fixture", plan.operation_id]

            runtime.agent.model.generate = generate
            runtime.runner.execute = execute
            runtime.runner.compiled_backends_for = lambda op: set(
                runtime.catalog.operation(op).allowed_backends
            )
            yield http, history

    return client


def capture_fixture(settings, catalog, tmp_path, monkeypatch, *, case_ids=None):
    suite_path = tmp_path / "suite.json"
    suite = write_suite(catalog, suite_path)
    monkeypatch.setattr(replay, "agent_client", fixture_client(suite["cases"]))
    report = asyncio.run(
        replay._capture_suite(
            settings,
            suite_path=suite_path,
            output=tmp_path / "capture.json",
            data_dir=tmp_path / "runtime",
            label="CPU fixture, not model predictions",
            case_ids=case_ids,
        )
    )
    return report, suite


def test_full_catalog_api_lifecycle(settings, catalog, tmp_path, monkeypatch):
    report, _ = capture_fixture(settings, catalog, tmp_path, monkeypatch)
    failures = [
        (row["case_id"], row["grade"]["issues"], row["outcome"].get("error"))
        for row in report["captures"]
        if not row["grade"]["workflow_contract_passed"]
    ]
    assert failures == []
    assert report["summary"]["complete"] is True
    assert report["summary"]["workflow_contract_passes"] == 46
    assert report["summary"]["dimensions"]["numerical_checks"] == {
        "passed": 26,
        "graded": 26,
    }
    assert report["summary"]["dimensions"]["exact_numerical"] == {
        "passed": 23,
        "graded": 23,
    }
    assert report["capture_kind"] == "cpu_fixture"
    assert all(
        row["model_providers"] == ["offline_rules"] for row in report["captures"]
    )
    assert sum(len(row["jobs"]) for row in report["captures"]) == 26
    assert (
        report["profile"]["resource_limits"]["max_result_bytes"]
        == settings.max_result_bytes
    )
    for row in report["captures"]:
        if not row["jobs"]:
            continue
        path = tmp_path / "runtime" / "jobs" / row["jobs"][0]["id"] / "timings.json"
        timings = json.loads(path.read_text())
        assert timings["status"] == "completed"
        assert set(timings["stages_seconds"]) == {
            "execution",
            "result_validation",
            "result_storage",
            "interpretation_and_presentation",
        }
        assert all(value > 0 for value in timings["stages_seconds"].values())
        assert timings["total_active_seconds"] >= sum(
            timings["stages_seconds"].values()
        )


def test_capture_detects_input_plan_and_prose_changes(
    settings, catalog, tmp_path, monkeypatch
):
    from graphmine_agent.learning.catalog_suite import build_suite

    case = next(
        case
        for case in build_suite(catalog)["cases"]
        if case["task"]["operation_id"] == "k-cliques"
    )
    report, _ = capture_fixture(
        settings, catalog, tmp_path, monkeypatch, case_ids=[case["id"]]
    )
    row = report["captures"][0]
    changed = copy.deepcopy(row)
    changed["inputs"]["graph"]["sha256"] = "wrong"
    assert (
        replay.grade_capture(catalog, case, changed)["dimensions"]["input_binding"]
        is False
    )
    changed = copy.deepcopy(row)
    changed["jobs"][0]["plan"]["parameters"]["k"] = 4
    assert (
        replay.grade_capture(catalog, case, changed)["dimensions"]["planning"] is False
    )
    changed = copy.deepcopy(row)
    changed["outcome"]["result"]["interpretation"]["summary"] = (
        "These entities committed fraud."
    )
    grade = replay.grade_capture(catalog, case, changed)
    assert grade["dimensions"]["presentation"] is False
    assert grade["dimensions"]["numerical_checks"] is True


def test_nonready_case_checks_jobs_even_when_reply_omits_them(
    settings, catalog, tmp_path, monkeypatch
):
    from graphmine_agent.learning.catalog_suite import build_suite

    case = next(
        case
        for case in build_suite(catalog)["cases"]
        if case["task"]["expected_status"] == "unsupported"
    )
    report, _ = capture_fixture(
        settings, catalog, tmp_path, monkeypatch, case_ids=[case["id"]]
    )
    row = report["captures"][0]
    unrelated = copy.deepcopy(row)
    unrelated["routes"][-1]["problem_id"] = "unrelated-problem"
    grade = replay.grade_capture(catalog, case, unrelated)
    assert grade["dimensions"]["status"] is True
    assert grade["workflow_contract_passed"] is False
    row["jobs"] = [{"id": "unexpected", "status": "queued"}]
    assert replay.grade_capture(catalog, case, row)["dimensions"]["execution"] is False


def test_public_live_capture_requires_model_before_writes(settings, tmp_path):
    with pytest.raises(ValueError, match="requires a configured language model"):
        asyncio.run(
            replay.evaluate_suite(
                settings,
                suite_path=tmp_path / "missing-suite.json",
                output=tmp_path / "report.json",
                data_dir=tmp_path / "runtime",
                label="disabled",
            )
        )
    assert not (tmp_path / "runtime").exists()
    assert not (tmp_path / "report.json").exists()


def test_live_capture_rejects_external_endpoint_before_writes(settings, tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        asyncio.run(
            replay.evaluate_suite(
                replace(
                    settings,
                    llm_enabled=True,
                    llm_base_url="https://external.invalid/v1",
                ),
                suite_path=tmp_path / "missing-suite.json",
                output=tmp_path / "report.json",
                data_dir=tmp_path / "runtime",
                label="external",
            )
        )
    assert not (tmp_path / "report.json").exists()


def test_interrupted_wait_cancels_actual_job_and_saves_failure(
    settings, catalog, tmp_path, monkeypatch
):
    from graphmine_agent.learning.catalog_suite import build_suite

    cancelled = []
    request = Terminal.request

    async def interrupted(*args, **kwargs):
        raise ClientError("Authored interrupted-wait fixture")

    async def pending_execution(*args, **kwargs):
        await asyncio.Future()

    async def tracked_request(self, method, path, **kwargs):
        if method == "POST" and path.endswith("/chat"):
            self.client._transport.app.state.runtime.runner.execute = pending_execution
        response = await request(self, method, path, **kwargs)
        if method == "DELETE":
            cancelled.append(response)
        return response

    monkeypatch.setattr(Terminal, "wait", interrupted)
    monkeypatch.setattr(Terminal, "request", tracked_request)
    case_id = build_suite(catalog)["cases"][0]["id"]
    report, _ = capture_fixture(
        settings, catalog, tmp_path, monkeypatch, case_ids=[case_id]
    )
    assert len(cancelled) == 1
    assert cancelled[0]["status"] == "cancelled"
    assert report["summary"]["complete"] is True
    assert report["summary"]["workflow_contract_passes"] == 0
    assert (
        report["captures"][0]["outcome"]["error"] == "Authored interrupted-wait fixture"
    )
