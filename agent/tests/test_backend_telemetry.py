"""Independent feature oracles and durable, privacy-preserving terminal records."""

from __future__ import annotations

import itertools
import json
import math
import os
import threading
import sys
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from graphmine_agent.backend_learning import features, storage
from graphmine_agent.backend_learning.cli import report, run_command
from graphmine_agent.backend_learning.features import graph_features, safe_parameters
from graphmine_agent.backend_learning.hardware import PeakSampler, hardware_snapshot
from graphmine_agent.backend_learning.worker import outcome_for, run_observed


@pytest.fixture
def telemetry_dir():
    # Even test data follows the requested storage policy. It remains marked as
    # evaluation data and is outside both the checkout and /tmp.
    root = storage.DEFAULT_DATA_DIR / "evaluations" / "phase1" / uuid4().hex
    storage.prepare_directories(root, storage.DEFAULT_MODEL_DIR, Path(__file__).resolve().parents[2])
    return root


def graph(n, pairs, *, directed=False):
    return {"graph": {"id": "PRIVATE_GRAPH", "directed": directed,
                       "allows_self_loops": True, "allows_parallel_edges": True},
            "vertices": [{"id": f"PRIVATE_VERTEX_{i}", "label": "PRIVATE_LABEL",
                          "attributes": {"name": "PRIVATE_VALUE"}} for i in range(n)],
            "edges": [{"id": f"PRIVATE_EDGE_{i}", "source": f"PRIVATE_VERTEX_{u}",
                       "target": f"PRIVATE_VERTEX_{v}"} for i, (u, v) in enumerate(pairs)]}


def row(**kwargs):
    return dict(schema_version=1, run_id=str(uuid4()), created_at=storage.utc_now(),
                problem="triangle-counting", chosen_backend="cpp", outcome="completed",
                runtime_seconds=1.0, graph_features={}, is_evaluation=True, **kwargs)


def test_hand_computed_triangle_and_isolated_vertex():
    values = graph_features(graph(4, [(0, 1), (1, 2), (2, 0)]))
    assert (values["n"], values["m"], values["max_degree"], values["degeneracy"]) == (4, 3, 2, 2)
    assert values["average_degree"] == 1.5
    assert values["density"] == 0.5
    assert values["degree_gini"] == 0.25
    assert values["degree_cv"] == pytest.approx(math.sqrt(3) / 3)
    assert (values["connected_components"], values["largest_component"]) == (2, 3)
    assert "PRIVATE" not in json.dumps(values)


def test_star_shape_and_bipartite_side_counts():
    data = graph(5, [(0, i) for i in range(1, 5)])
    for i, vertex in enumerate(data["vertices"]):
        vertex["attributes"]["side"] = "left" if i == 0 else "right"
    values = graph_features(data)
    assert values["degeneracy"] == 1
    assert values["degree_gini"] == pytest.approx(0.3)
    assert values["bipartite_left"] == 1 and values["bipartite_right"] == 4
    assert values["bipartite_ratio"] == 0.25


def test_flags_do_not_change_the_simple_projection():
    data = graph(2, [(0, 1), (0, 1), (1, 0), (0, 0)], directed=True)
    data["edges"][0]["weight"] = 2.5
    values = graph_features(data)
    assert values["m"] == 4 and values["average_degree"] == 1
    assert values["degeneracy"] == 1 and values["density"] == 1
    assert all(values[k] for k in ("self_loops", "parallel_edges", "directed", "weighted"))


def test_all_four_vertex_graphs_against_subset_core_oracle():
    pairs = list(itertools.combinations(range(4), 2))
    for mask in range(1 << len(pairs)):
        edges = [edge for i, edge in enumerate(pairs) if mask & (1 << i)]
        expected = 0
        for subset_mask in range(1, 1 << 4):
            selected = {v for v in range(4) if subset_mask & (1 << v)}
            minimum_degree = min(sum(u in selected and v in selected and vertex in (u, v)
                                     for u, v in edges) for vertex in selected)
            expected = max(expected, minimum_degree)
        assert graph_features(graph(4, edges))["degeneracy"] == expected


def test_empty_and_structured_inputs_have_defined_features():
    empty = graph_features(graph(0, []))
    assert empty["degeneracy"] == empty["density"] == empty["degree_cv"] == empty["degree_gini"] == 0
    structured = graph_features({"vectors": [{"id": "PRIVATE", "values": [1, 2]}]}, input_kind="feature_vectors")
    assert structured["n"] == 1 and structured["degeneracy"] is None
    assert "PRIVATE" not in json.dumps(structured)


def test_redaction_includes_scalar_ids_attributes_and_nested_collections():
    values = {"source": 123456789, "sources": ["PRIVATE"], "partition": [["PRIVATE"]],
              "query_graph": graph(1, []), "attribute": "PRIVATE", "mode": "count", "k": 3}
    schemas = {"source": {"kind": "vertex_id"}, "sources": {"kind": "array"},
               "partition": {"kind": "array"}, "query_graph": {"kind": "object"},
               "attribute": {"kind": "string"}, "mode": {"kind": "string", "choices": ["count"]},
               "k": {"kind": "integer"}}
    redacted = safe_parameters(values, schemas)
    assert redacted["sources"] == {"count": 1} and redacted["partition"] == {"count": 1}
    assert redacted["source"] == {"redacted": True}
    assert redacted["mode"] == "count" and redacted["k"] == 3
    assert "PRIVATE" not in json.dumps(redacted) and "123456789" not in json.dumps(redacted)


def test_feature_cache_reuses_snapshot(telemetry_dir, monkeypatch):
    expected = graph_features(graph(3, [(0, 1), (1, 2)]))
    path = telemetry_dir / "features" / (expected["snapshot_fingerprint"] + ".json")
    path.write_text(json.dumps(expected))
    monkeypatch.setattr(features, "graph_features", lambda *a, **k: pytest.fail("recomputed cached snapshot"))
    assert features.cached_features({}, telemetry_dir, snapshot_fingerprint=expected["snapshot_fingerprint"]) == expected


def test_feature_cache_rejects_graph_contents_and_incomplete_records(telemetry_dir):
    data = graph(3, [(0, 1), (1, 2)])
    expected = graph_features(data)
    path = telemetry_dir / "features" / (expected["snapshot_fingerprint"] + ".json")
    path.write_text(json.dumps({**expected, "vertices": data["vertices"]}))
    result = features.cached_features(data, telemetry_dir, snapshot_fingerprint=expected["snapshot_fingerprint"])
    assert result == expected and "PRIVATE" not in json.dumps(result)
    features._CACHE.clear()
    path.write_text(json.dumps({k: expected[k] for k in ("feature_version", "snapshot_fingerprint", "input_kind")}))
    assert features.cached_features(data, telemetry_dir, snapshot_fingerprint=expected["snapshot_fingerprint"]) == expected


def test_concurrent_appends_and_corrections_remain_intact(telemetry_dir):
    destination = telemetry_dir / "runs/2026/11/17/runs-concurrency.jsonl"
    rows = [row() for _ in range(80)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda item: storage.append_row(destination, item), rows))
    assert len(destination.read_text().splitlines()) == 80
    assert {r["run_id"] for r in storage.read_rows(telemetry_dir)} == {r["run_id"] for r in rows}
    original = destination.read_bytes()
    correction = row(supersedes=rows[0]["run_id"])
    storage.append_row(destination, correction)
    assert destination.read_bytes().startswith(original)
    assert report(storage.read_rows(telemetry_dir))["groups"][0]["run_count"] == 80


def test_writes_are_async_and_failures_warn(telemetry_dir, monkeypatch):
    gate, entered = threading.Event(), threading.Event()

    def failing_write(*args):
        entered.set()
        gate.wait(5)
        raise OSError("disk unavailable")

    monkeypatch.setattr(storage, "append_row", failing_write)
    logger = storage.RunLog(telemetry_dir)
    assert logger.submit(row())
    assert entered.wait(1) and logger.thread.is_alive()
    gate.set()
    logger.flush()
    assert logger.warnings == ["log_write_failed"]
    logger.close()


@pytest.mark.parametrize("location", ["/tmp/backend-data", str(Path(__file__).resolve().parents[2] / "bad-data")])
def test_storage_rejects_repo_and_tmp(location):
    with pytest.raises(ValueError, match="outside the repository and /tmp"):
        storage.prepare_directories(location, storage.DEFAULT_MODEL_DIR, Path(__file__).resolve().parents[2])


def test_unwritable_storage_fails_at_startup():
    with pytest.raises(ValueError, match="backend_data_dir is not writable"):
        storage.prepare_directories("/proc/graphmine-backend-unwritable", storage.DEFAULT_MODEL_DIR, "/unrelated")


def test_report_counts_failures_without_treating_timeouts_as_completed():
    rows = [row() for _ in range(4)]
    rows[1]["runtime_seconds"] = 3
    rows[2].update(outcome="timeout", runtime_seconds=1800, censored=True)
    rows[3].update(outcome="oom", runtime_seconds=0.1)
    summary = report(rows)["groups"][0]
    assert summary["median_seconds"] == 2 and summary["p90_seconds"] == pytest.approx(2.8)
    assert summary["failure_rate"] == 0.5 and summary["timeout_count"] == summary["oom_count"] == 1


@pytest.mark.parametrize("error,expected", [(None, "completed"), (TimeoutError(), "timeout"),
                                          (MemoryError(), "oom"), (RuntimeError("bad input"), "error")])
def test_outcome_classification(error, expected):
    assert outcome_for(error)[0] == expected


def test_native_deadline_is_censored_but_invalid_timeout_parameter_is_not():
    from graphmine.exceptions import GraphMineError

    deadline = GraphMineError("Native computation deadline exceeded")
    deadline.code = "resource_limit"
    assert outcome_for(deadline)[0] == "timeout"
    invalid = GraphMineError("timeout_seconds must be finite and positive")
    assert outcome_for(invalid)[0] == "error"


def test_real_native_timeout_emits_censored_terminal_row(telemetry_dir, monkeypatch):
    from graphmine.dispatch import run
    from graphmine.native_inputs import Graph
    from graphmine.contracts import Budget
    from graphmine.exceptions import GraphMineError

    monkeypatch.setenv("GRAPHMINE_BACKEND_DATA_DIR", str(telemetry_dir))
    events = []
    with pytest.raises(GraphMineError, match="deadline exceeded"):
        run_observed(run, "triangle-counting", Graph(graph(3, [(0, 1), (1, 2), (0, 2)])),
                     context={"is_evaluation": True}, step_id="deadline", emit=events.append,
                     device="cpu", budget=Budget(timeout_seconds=1e-9))
    rows = [e["record"] for e in events if e["event"] == "native_finished"]
    assert len(rows) == 1 and rows[0]["outcome"] == "timeout" and rows[0]["censored"]
    assert rows[0]["runtime_seconds"] >= rows[0]["timeout_seconds"]


@pytest.mark.parametrize("outcome", ["completed", "timeout", "oom"])
def test_every_native_attempt_emits_one_terminal_row(telemetry_dir, monkeypatch, outcome):
    from graphmine.dispatch import run
    from graphmine.native_inputs import Graph
    from graphmine.contracts import Budget

    monkeypatch.setenv("GRAPHMINE_BACKEND_DATA_DIR", str(telemetry_dir))
    native_graph = Graph(graph(3, [(0, 1), (1, 2), (0, 2)]))
    events = []

    def invoke(*args, **kwargs):
        if outcome == "timeout":
            raise TimeoutError("execution deadline")
        if outcome == "oom":
            raise MemoryError("PRIVATE graph allocation failed")
        return run(*args, **kwargs)

    def observed():
        return run_observed(invoke, "triangle-counting", native_graph, context={"is_evaluation": True},
                            step_id="count", emit=events.append, device="cpu", parameters={"mode": "count"},
                            budget=Budget(), allowed_backends=["cpp"])

    if outcome == "completed":
        assert observed()["backend"]["id"] == "cpp"
    else:
        with pytest.raises(TimeoutError if outcome == "timeout" else MemoryError):
            observed()
    terminal = [e["record"] for e in events if e["event"] == "native_finished"]
    assert len(terminal) == 1
    item = terminal[0]
    assert item["outcome"] == outcome and item["censored"] == (outcome == "timeout")
    assert item["chosen_backend"] == "cpp" and item["reason"] == "forced"
    assert item["is_evaluation"] and item["policy_version"] == "native-rule-v1"
    assert "PRIVATE" not in json.dumps(item)
    logger = storage.RunLog(telemetry_dir)
    logger.submit(item)
    logger.flush()
    logger.close()
    assert len(list(storage.read_rows(telemetry_dir))) == 1


def test_native_candidates_match_cpu_policy_and_admission():
    from graphmine.dispatch import native_request

    caps = native_request(dict(command="backend_capabilities", problem="triangle-counting",
                               graph=graph(3, [(0, 1), (1, 2), (0, 2)]), device="cpu", allowed_backends=["cpp"]))
    assert caps["legacy_backend"] == "cpp"
    assert sum(c["feasible"] for c in caps["candidates"]) == 1
    assert all(not c["admitted"] for c in caps["candidates"] if c["id"] != "cpp")


def test_multistep_workflow_logs_only_executed_steps(telemetry_dir, monkeypatch):
    import graphmine.workflows as workflows
    from graphmine_agent.backend_learning.worker import install

    monkeypatch.setenv("GRAPHMINE_BACKEND_DATA_DIR", str(telemetry_dir))
    monkeypatch.setenv("GRAPHMINE_BACKEND_RUN_CONTEXT", json.dumps({"is_evaluation": True}))
    original_execute, original_run = workflows.execute_workflow, workflows.run
    plan = {"version": 1, "device": "cpu", "steps": [
        {"id": name, "problem": "triangle-counting", "input": {"input": "g"}}
        for name in ("first", "second")]}
    inputs = {"g": {"kind": "graph", "data": graph(3, [(0, 1), (1, 2), (0, 2)])}}
    events = []
    try:
        install()
        result = workflows.execute_workflow(plan, inputs, emit=events.append)
        rows = [e["record"] for e in events if e["event"] == "native_finished"]
        assert [r["step_id"] for r in rows] == ["first", "second"]
        assert all(r["outcome"] == "completed" for r in rows)
        events.clear()
        resumed = workflows.execute_workflow(plan, inputs, emit=events.append, resume=result["steps"])
        assert all(r["reused"] for r in resumed["steps"].values())
        assert not any(e["event"].startswith("native_") for e in events)
    finally:
        workflows.execute_workflow, workflows.run = original_execute, original_run


def test_logging_delivery_failure_preserves_native_result(telemetry_dir, monkeypatch):
    from graphmine.dispatch import run
    from graphmine.native_inputs import Graph

    monkeypatch.setenv("GRAPHMINE_BACKEND_DATA_DIR", str(telemetry_dir))

    def failure(event):
        raise OSError("telemetry transport unavailable")

    result = run_observed(run, "triangle-counting", Graph(graph(3, [(0, 1), (1, 2), (0, 2)])),
                          context={"is_evaluation": True}, step_id="count", emit=failure, device="cpu")
    assert result["backend"]["id"] == "cpp"


def test_host_metrics_and_process_peak_are_aggregates():
    values = hardware_snapshot()
    assert values["total_cores"] >= 1 and values["free_ram_bytes"] > 0
    sampler = PeakSampler(os.getpid())
    result = sampler.finish()
    assert result["process_rss_bytes"] > 0 and result["gpu_bytes"] is None
    assert "pid" not in values


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["completed", "oom", "hard_timeout"])
async def test_supervisor_writes_one_row_even_after_worker_is_killed(
    settings, database, graph_store, telemetry_dir, tmp_path, terminal
):
    from graphmine_agent.analytics import AnalyticsError, AnalyticsService
    from graphmine_agent.jobs import EventBus

    item = row()
    item.update(outcome=None, hardware={"leased_gpu_index": None}, telemetry_warnings=[],
                timeout_seconds=1, censored=False, peak_memory={},
                candidates=[{"id": "declared-profile", "compiled": False,
                             "admitted": False, "feasible": False, "infeasible_reason": "not_compiled"}] * 20)
    script = tmp_path / "isolated-worker"
    script.write_text(f"#!{sys.executable}\n" +
                      "import json,sys,time\n"
                      "sys.stdin.buffer.read()\n" +
                      f"row=json.loads({json.dumps(item)!r})\n" +
                      "print(json.dumps({'event':'native_started','record':row}),flush=True)\n" +
                      ("time.sleep(20)\n" if terminal == "hard_timeout" else
                       f"row.update(outcome={terminal!r},runtime_seconds=0.01)\n"
                       "print(json.dumps({'event':'native_finished','record':row}),flush=True)\n"
                       "print(json.dumps({'event':'complete','result':{}}),flush=True)\n"))
    script.chmod(0o700)
    settings = replace(settings, analytics_python=script, job_timeout_seconds=1,
                       backend_data_dir=telemetry_dir, backend_model_dir=storage.DEFAULT_MODEL_DIR,
                       max_result_bytes=500)
    service = AnalyticsService(settings, database, graph_store, EventBus(database))
    try:
        request = {"command": "run", "plan": {"device": "cpu"}}
        if terminal == "hard_timeout":
            with pytest.raises(AnalyticsError, match="deadline"):
                await service._call(request)
        else:
            assert await service._call(request) == {}
        service.run_log.flush()
        records = list(storage.read_rows(telemetry_dir))
        assert len(records) == 1
        assert records[0]["outcome"] == ("timeout" if terminal == "hard_timeout" else terminal)
        assert records[0]["censored"] == (terminal == "hard_timeout")
        if terminal == "hard_timeout":
            assert records[0]["peak_memory"]["process_rss_bytes"] > 0
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["preflight", "step_timeout", "duplicate"])
async def test_supervisor_preflight_terminal_and_independent_step_deadline(
    settings, database, graph_store, telemetry_dir, terminal
):
    from graphmine_agent.analytics import AnalyticsError, AnalyticsService
    from graphmine_agent.jobs import EventBus
    item = row()
    item.update(outcome="error", execution_started=False, hardware={"leased_gpu_index": None},
                telemetry_warnings=[], timeout_seconds=.2, censored=False, peak_memory={})
    script = telemetry_dir / "fault-worker"
    started = "print(json.dumps({'event':'step_started','step':'count'}),flush=True)\n"
    native_start = "print(json.dumps({'event':'native_started','record':row}),flush=True)\n"
    native_finish = "print(json.dumps({'event':'native_finished','record':row}),flush=True)\n"
    script.write_text(f"#!{sys.executable}\nimport json,sys,time\nsys.stdin.buffer.read()\n" +
        f"row=json.loads({json.dumps(item)!r})\n" +
        (started + native_start + "time.sleep(20)\n" if terminal == "step_timeout" else
         native_finish * (2 if terminal == "duplicate" else 1) +
         "print(json.dumps({'event':'complete','result':{}}),flush=True)\n"))
    script.chmod(0o700)
    settings = replace(settings, analytics_python=script, job_timeout_seconds=10,
        backend_data_dir=telemetry_dir, backend_model_dir=storage.DEFAULT_MODEL_DIR)
    service = AnalyticsService(settings, database, graph_store, EventBus(database))
    try:
        request = dict(command="run", plan=dict(device="cpu", steps=[dict(id="count", budget={"timeout_seconds": .2})]))
        if terminal == "preflight":
            assert await service._call(request) == {}
        else:
            with pytest.raises(AnalyticsError, match="deadline" if terminal == "step_timeout" else "Duplicate"):
                await service._call(request)
        service.run_log.flush()
        records = list(storage.read_rows(telemetry_dir))
        assert len(records) == 1
        assert records[0]["outcome"] == ("timeout" if terminal == "step_timeout" else "error")
        if terminal == "step_timeout":
            assert records[0]["runtime_seconds"] < 5 and records[0]["censored"]
            assert len(records[0]["fallback_chain"]) == 1
    finally:
        await service.close()


def test_export_filters_and_report_artifact(telemetry_dir, capsys):
    from argparse import Namespace

    logger = storage.RunLog(telemetry_dir)
    logger.submit(row())
    logger.flush()
    logger.close()
    args = Namespace(data_dir=telemetry_dir, since="2020-01-01", problem="triangle-counting",
                     backend_runs_command="export")
    assert run_command(args) == 0
    exported = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(exported) == 1 and exported[0]["is_evaluation"]
    args.problem = "missing-problem"
    run_command(args)
    assert not capsys.readouterr().out
    args.problem, args.backend_runs_command = None, "report"
    before = dict(os.environ)
    run_command(args)
    assert dict(os.environ) == before
    summary = json.loads(capsys.readouterr().out)
    assert summary["groups"][0]["run_count"] == 1
    assert len(list((telemetry_dir / "reports").glob("*-backend-report.json"))) == 1


@pytest.mark.asyncio
async def test_real_gpu1_worker_records_executed_backend_and_physical_lease(
    settings, database, graph_store, telemetry_dir
):
    from graphmine_agent.analytics import AnalyticsService
    from graphmine_agent.analytics_scheduler import Lease
    from graphmine_agent.jobs import EventBus

    uuid = os.environ.get("GRAPHMINE_TELEMETRY_TEST_GPU_UUID")
    if not uuid:
        pytest.skip("Set GRAPHMINE_TELEMETRY_TEST_GPU_UUID to physical GPU 1")
    inventory = hardware_snapshot(leased_gpu_uuid=uuid)
    assert inventory["leased_gpu_index"] == 1, "This test must never execute on GPU 0"
    service = AnalyticsService(replace(settings, backend_data_dir=telemetry_dir, backend_selection="native",
                                       job_timeout_seconds=60), database, graph_store, EventBus(database))
    plan = {"version": 1, "device": "auto", "steps": [
        {"id": "triangles", "problem": "triangle-counting", "input": {"input": "g"}}]}
    inputs = {"g": {"kind": "graph", "data": graph(3, [(0, 1), (1, 2), (0, 2)])}}
    try:
        checked = await service._call({"command": "validate", "plan": plan, "inputs": inputs})
        result = await service._call({"command": "run", "plan": plan, "inputs": inputs,
                                      "expected_hash": checked["workflow_hash"],
                                      "telemetry": {"is_evaluation": True}},
                                     lease=Lease("evaluation", "gpu", uuid, 1, 1))
        assert result["status"] == "completed"
        backend = result["steps"]["triangles"]["result"]["backend"]
        assert backend["device"] == "gpu" and backend["hardware"]["uuid"] == uuid
        service.run_log.flush()
        rows = list(storage.read_rows(telemetry_dir))
        assert len(rows) == 1
        item = rows[0]
        assert item["chosen_backend"] == backend["id"]
        assert item["hardware"]["leased_gpu_index"] == 1
        assert len(item["hardware"]["gpus"]) >= 2
        assert item["reason"] == "native_rule" and item["is_evaluation"]
        assert item["selection_mode"] == "native" and item["selection_probability"] == 1.0
        assert item["peak_memory"]["gpu_bytes"] is not None
        assert not item["telemetry_warnings"]
    finally:
        await service.close()
