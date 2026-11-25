"""Durable offline collection, bounded warm starts, and independent lifecycle checks."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from graphmine_agent.backend_learning import benchmark as bench
from graphmine_agent.backend_learning import benchmark_graphs as graphs
from graphmine_agent.backend_learning import benchmark_profiles as profiles
from graphmine_agent.backend_learning import storage
from graphmine_agent.backend_learning.leases import GPULock

ROOT = Path(__file__).resolve().parents[2]
IMPLEMENTATION = "a" * 64


@pytest.fixture
def data_dir():
    root = storage.DEFAULT_DATA_DIR / "evaluations/phase3" / uuid4().hex
    storage.prepare_directories(root, storage.DEFAULT_MODEL_DIR, ROOT)
    return root


def spec(**changes):
    return dict(dict(id="fixture", source="generated", generator="erdos_renyi", n=20,
                     average_degree=4, seed=100, tags=["general"]), **changes)


def row(**changes):
    return dict(dict(schema_version=storage.SCHEMA_VERSION, run_id=uuid4().hex, created_at=storage.utc_now(),
        problem="triangle-counting", requested_backend="cpp", chosen_backend="cpp", graph_id="fixture",
        benchmark_attempt_key=uuid4().hex, comparison_id="comparison", source="benchmark", is_evaluation=True,
        implementation_sha256=IMPLEMENTATION, outcome="completed", runtime_seconds=0.1,
        timeout_seconds=10, censored=False, peak_memory={"gpu_bytes": None, "process_rss_bytes": None},
        telemetry_warnings=[]), **changes)


def job(record, **changes):
    return dict(dict(run_id=record["run_id"], benchmark_attempt_key=record["benchmark_attempt_key"],
                     repository_root=str(ROOT), gpu_uuid=None, budget={"timeout_seconds": 10}), **changes)


@pytest.mark.parametrize("family", ["erdos_renyi", "power_law", "planted_dense"])
def test_generated_snapshots_are_deterministic_simple_and_seeded(family):
    definition = spec(generator=family)
    first = graphs.generate(definition)
    assert first == graphs.generate(definition)
    assert first != graphs.generate({**definition, "seed": 101})
    pairs = [(e["source"], e["target"]) for e in first["edges"]]
    assert len(set(pairs)) == len(pairs) and all(0 <= a < b < 20 for a, b in pairs)
    if family == "power_law":
        assert len(pairs) == 2 + (20 - 3) * 2
    if family == "planted_dense":
        assert all((a, b) in pairs for a in range(8) for b in range(a + 1, 8))


def test_generated_probability_extremes_and_typed_inputs():
    assert graphs.generate(spec(probability=0))["edges"] == []
    assert len(graphs.generate(spec(n=6, probability=1, directed=True))["edges"]) == 30
    bipartite = graphs.generate(spec(n=6, probability=1, bipartite=True, weights="integer"))
    assert len(bipartite["edges"]) == 9
    assert all(e["source"] < 3 <= e["target"] and 1 <= e["weight"] <= 9 for e in bipartite["edges"])
    dag = graphs.generate(spec(n=6, probability=1, directed=True, acyclic=True, timestamps=True))
    assert len(dag["edges"]) == 15 and all(e["source"] < e["target"] for e in dag["edges"])
    assert [e["timestamp"] for e in dag["edges"]] == list(range(15))
    temporal = graphs.generate(spec(generator="planted_dense", directed=True, timestamps=True))
    assert [(e["source"], e["target"], e["timestamp"]) for e in temporal["edges"][:3]] == [
        (0, 1, 0), (1, 2, 1), (0, 2, 2)]
    with pytest.raises(ValueError, match="density"):
        graphs.generate(spec(n=100000, probability=1))


def test_default_graph_grid_and_small_initial_selection():
    config = profiles.load_config(ROOT / "benchmarks/backend_selection.json")
    expanded = profiles.expand_graphs(config)
    assert len(expanded) == 60 and sum(s["source"] == "neo4j" for s in expanded) == 16
    assert config["bootstrap_examples_per_problem"] == config["repeats"] == 3
    assert config["timeout_seconds"] == 1800
    assert config["max_output_items"] is None
    assert config["max_candidates"] is None
    cards = [dict(id=op) for op in config["problems"]]
    selected = profiles.select_graphs(config, cards)
    assert len(selected) == 36 and all(len(choices) == 1 for choices in selected.values())
    assert {s[0]["dataset"] for s in selected.values() if s[0]["source"] == "neo4j"} == {
        "yelp", "movielens-32m", "movielens-genome", "ldbc-snb"}
    assert len(profiles.parameter_grid(config["problems"]["k-cliques"])) == 3


def test_saved_graph_resume_checks_source_configuration_and_exact_content(data_dir, monkeypatch):
    path, metadata = graphs.prepare_graph(data_dir, spec(), None)
    monkeypatch.setattr(graphs, "generate", lambda _: pytest.fail("Regenerated a saved snapshot"))
    assert graphs.prepare_graph(data_dir, spec(), None) == (path, metadata)
    with pytest.raises(ValueError, match="changed"):
        graphs.prepare_graph(data_dir, spec(seed=101), None)
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="changed"):
        graphs.prepare_graph(data_dir, spec(), None)


def test_attempt_identity_covers_input_parameters_budget_implementation_and_repetition():
    base = [IMPLEMENTATION, "triangle-counting", "cpp", "b" * 64, {"mode": "count"}, {"timeout_seconds": 1800}, 0]
    original = profiles.attempt_keys(*base)
    assert original == profiles.attempt_keys(*base)
    for index, value in enumerate(["c" * 64, "k-cliques", "tot", "d" * 64, {"mode": "list"}, {"timeout_seconds": 20}, 1]):
        changed = copy.deepcopy(base)
        changed[index] = value
        result = profiles.attempt_keys(*changed)
        assert result[-1] != original[-1]
        if index in {2, 6}:
            assert result[0] == original[0]


def test_registered_extract_is_bounded_read_only_and_anonymous(monkeypatch):
    from graphmine_agent.analytics import AnalyticsError
    source = SimpleNamespace(_catalog={"id": "demo", "load_finished_at": "fixed"}, max_bytes=65536, timeout_seconds=30)
    monkeypatch.setattr("graphmine_agent.neo4j_registry.sources", lambda _: [source])
    raw = {"vertices": [{"id": "private-a", "attributes": {"name": "secret"}}, {"id": "private-b"}],
           "edges": [{"source": "private-a", "target": "private-b", "weight": 123},
                     {"source": "private-b", "target": "private-a"}, {"source": "private-a", "target": "private-a"}]}
    calls = []

    def execute(selected, body, **options):
        calls.append((selected, body, options))
        return raw, {}, [], 3, None

    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute)
    definition = dict(id="extract", dataset="demo", query="MATCH p=()-[]->() RETURN p LIMIT $edge_limit",
                      parameters={"edge_limit": 3})
    result, provenance = graphs.extract(definition, None)
    assert result == graphs.canonical("extract", 2, {(0, 1)})
    assert "private" not in json.dumps(result) and "secret" not in json.dumps(result)
    assert calls[0][2] == {"byte_limit": 65536, "timeout_seconds": 30}
    assert provenance["parameters"] == {"edge_limit": 3}
    with pytest.raises(AnalyticsError):
        graphs.extract({**definition, "query": "CREATE (n) RETURN n"}, None)
    assert len(calls) == 1
    with pytest.raises(ValueError, match="verified and ready"):
        graphs.extract({**definition, "dataset": "unknown"}, None)


def test_gpu_lease_survives_parent_release_until_child_exits(data_dir):
    lock = GPULock.acquire(data_dir)
    assert lock is not None and GPULock.acquire(data_dir) is None
    assert GPULock.acquire(data_dir / "another-root") is None
    process = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"],
                               stdin=subprocess.PIPE, pass_fds=(lock.fd,))
    try:
        lock.close()
        assert GPULock.acquire(data_dir) is None
    finally:
        process.communicate(timeout=5)
    available = GPULock.acquire(data_dir)
    assert available is not None
    available.close()


@pytest.mark.asyncio
async def test_app_scheduler_observes_external_benchmark_lease(settings, data_dir):
    from test_analytics_scheduler import scheduler
    from graphmine_agent.analytics_scheduler import AdmissionError

    service = scheduler(replace(settings, backend_data_dir=data_dir))
    lock = GPULock.acquire(data_dir)
    try:
        async with service.reserve("auto", 1024, timeout=1) as leased:
            assert leased.device == "cpu" and service.worker_fds(leased) == ()
        with pytest.raises(AdmissionError, match="waiting"):
            async with service.reserve("gpu", 1024, timeout=0.02):
                pytest.fail("Overlapped a benchmark on GPU 1")
    finally:
        lock.close()
    async with service.reserve("gpu", 1024, timeout=1) as leased:
        assert len(service.worker_fds(leased)) == 1


@pytest.mark.asyncio
async def test_hard_timeout_kills_descendants_and_recovery_logs_once(data_dir):
    record = row(outcome=None, timeout_seconds=0.6)
    pid_path = data_dir / "descendant.pid"
    script = """import json, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
Path(sys.argv[2]).write_text(str(child.pid))
print(json.dumps({'event':'native_started','record':json.loads(sys.argv[1])}), flush=True)
time.sleep(30)
"""
    result = await bench.run_attempt(job(record, budget={"timeout_seconds": 0.6}), record, data_dir,
        python=sys.executable, library=ROOT / "library/build/runtime/libgraphmine_runtime.so",
        command=[sys.executable, "-c", script, json.dumps(record), str(pid_path)])
    assert result["outcome"] == "timeout" and result["censored"] and result["runtime_seconds"] >= 0.6
    assert bench.process_identity(int(pid_path.read_text())) is None
    logger = storage.RunLog(data_dir, destination=data_dir / "runs.jsonl")
    try:
        await bench.recover(data_dir, logger)
        await bench.recover(data_dir, logger)
        assert len(bench.recorded_rows(data_dir)) == 1
    finally:
        logger.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["sampler", "journal"])
async def test_observation_failure_preserves_native_completion(data_dir, monkeypatch, failure):
    record = row()
    if failure == "sampler":
        def broken(*args):
            raise OSError("unavailable")
        monkeypatch.setattr(bench, "PeakSampler", broken)
    else:
        original = bench.atomic_json
        def failing_after_start(path, value):
            if Path(path).name == "terminal.json" or Path(path).name == "state.json" and value["process"]:
                raise OSError("disk full")
            return original(path, value)
        monkeypatch.setattr(bench, "atomic_json", failing_after_start)
    script = "import json,sys; r=json.loads(sys.argv[1]); print(json.dumps({'event':'native_started','record':r})); print(json.dumps({'event':'native_finished','record':r})); print('discard-sensitive-diagnostics',file=sys.stderr)"
    result = await bench.run_attempt(job(record), record, data_dir, python=sys.executable, library="unused",
                                    command=[sys.executable, "-c", script, json.dumps(record)])
    assert result["outcome"] == "completed" and result["runtime_seconds"] == 0.1
    assert result["telemetry_warnings"] and result["worker_diagnostic_bytes"] > 0
    assert "sensitive" not in json.dumps(result)


@pytest.mark.asyncio
async def test_recovery_waits_for_live_worker_instead_of_restarting(data_dir):
    record = row(outcome=None)
    directory = data_dir / "attempts" / record["benchmark_attempt_key"]
    directory.mkdir(parents=True)
    completed = {**record, "outcome": "completed"}
    with bench.exclusive(directory / "worker.lock") as fd:
        process = await asyncio.create_subprocess_exec(sys.executable, "-c",
            "import sys,time; from pathlib import Path; time.sleep(.3); Path(sys.argv[1]).write_text(sys.argv[2])",
            str(directory / "terminal.json"), json.dumps(completed), pass_fds=(fd,), start_new_session=True)
    storage.atomic_json(directory / "state.json", dict(record=record, process=bench.process_identity(process.pid), status="running"))
    logger = storage.RunLog(data_dir, destination=data_dir / "runs.jsonl")
    try:
        recovery = asyncio.create_task(bench.recover(data_dir, logger))
        await asyncio.sleep(0.05)
        assert not recovery.done() and not (data_dir / "runs.jsonl").exists()
        assert (await recovery)[0]["outcome"] == "completed"
        await process.wait()
    finally:
        logger.close()
        if process.returncode is None:
            process.kill()
            await process.wait()


def test_bootstrap_quota_includes_unfinished_claims_and_excludes_other_contexts(data_dir):
    rows = [row(), row(), row(is_evaluation=False), row(implementation_sha256="b" * 64), row(source="application")]
    directory = data_dir / "benchmarks/first"
    for record in rows:
        storage.append_row(directory / "runs.jsonl", record)
    for record in [rows[0], row(outcome=None)]:
        storage.atomic_json(data_dir / "benchmarks/second/attempts" / record["benchmark_attempt_key"] / "state.json",
                            dict(record=record, process=None, status="starting"))
    assert bench.bootstrap_totals(data_dir, IMPLEMENTATION, True) == {"triangle-counting": 3}


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_count", [2, 5])
async def test_collection_caps_per_problem_across_graphs_and_ids_and_full_is_explicit(data_dir, monkeypatch, backend_count):
    import graphmine.dispatch
    from graphmine import evidence
    from graphmine_agent import evidence_cache

    # collect is a CLI entry point that configures its process environment.
    # Restore both variables before later application verification snapshots.
    for name in ("GRAPHMINE_NATIVE_LIBRARY", "CUDA_VISIBLE_DEVICES"):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    ids = ["cpp", *[f"test-gpu-{i}" for i in range(backend_count - 1)]]
    card = dict(id="breadth-first-search", topic_id="test", family="traversal", backends=[
        dict(id=b, device="cpu" if b == "cpp" else "gpu", compiled=True, verified=True,
             verified_devices=["GPU-test"]) for b in ids])
    monkeypatch.setattr(evidence_cache, "install", lambda *a: None)
    monkeypatch.setattr(evidence, "capabilities", lambda *a: {"problems": [card]})
    monkeypatch.setattr(graphmine.dispatch, "implementation_hash", lambda: IMPLEMENTATION)
    monkeypatch.setattr(bench, "hardware_snapshot", lambda **k: {"gpus": [{"index": 1, "uuid": "GPU-test"}], "warnings": []})
    definitions = [spec(id="first"), spec(id="second", seed=200)]
    monkeypatch.setattr(bench, "select_graphs", lambda *a, **k: {card["id"]: definitions})
    executions = []
    async def execute(job, record, directory, **kwargs):
        executions.append(job)
        return {**record, "outcome": "completed", "runtime_seconds": 0.1}
    monkeypatch.setattr(bench, "run_attempt", execute)
    from graphmine_agent.backend_learning import paired
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def no_load(regime, **kw):
        yield
    async def admit(job, *args, **kwargs):
        from graphmine_agent.backend_learning.features import graph_features
        graph = json.loads(Path(job['graph_path']).read_text())
        return dict(eligible=list(ids), context=dict(problem=job['problem'], parameters={},
            graph_features=graph_features(graph), hardware={}, execution_isolated=True))
    monkeypatch.setattr(paired, 'cpu_load', no_load)
    monkeypatch.setattr(paired, 'admit_pair', admit)
    args = SimpleNamespace(load_regimes='idle,busy_cpu', busy_cpu_workers=1, load_warmup_seconds=0,
        registry=None, instances=None, password_file=None, data_dir=data_dir,
        model_dir=storage.DEFAULT_MODEL_DIR, native_library=Path(os.environ.get("GRAPHMINE_NATIVE_LIBRARY")
            or ROOT / "library/build/runtime/libgraphmine_runtime.so"),
        config=ROOT / "benchmarks/backend_selection.json", examples_per_problem=None, is_evaluation=True,
        full=False, benchmark_id="initial", problems=None, python=None)
    initial = 2 if backend_count == 2 else 0
    assert await bench.collect(args) == 0 and len(executions) == initial
    if initial:
        assert {j['backend'] for j in executions} == set(ids)
        assert all(j['graph_id'] == 'first' for j in executions)
    assert await bench.collect(args) == 0 and len(executions) == initial
    args.benchmark_id = 'another'
    assert await bench.collect(args) == 0 and len(executions) == initial
    args.benchmark_id, args.full = 'explicit-full', True
    assert await bench.collect(args) == 0
    assert len(executions) == initial + 2 * 2 * backend_count * 3
    assert all(j['is_evaluation'] for j in executions)
    groups = {}
    for j in executions:
        groups.setdefault(j['comparison_id'], []).append(j)
    assert all({j['backend'] for j in group} == set(ids) for group in groups.values())
    assert {j['load_regime'] for j in executions} == {'idle', 'busy_cpu'}
    assert any(group[0]['backend'] != 'cpp' for group in groups.values())


def test_summary_uses_identical_completed_comparisons_and_reports_missing_coverage():
    rows = [row(runtime_seconds=1), row(runtime_seconds=3), row(runtime_seconds=5),
            row(outcome="timeout", runtime_seconds=1800, censored=True),
            row(requested_backend="gpu", runtime_seconds=2),
            row(requested_backend="gpu", outcome="oom", runtime_seconds=.01)]
    summary = bench.summarize(rows, [dict(id="triangle-counting", backends=[
        dict(id=b, verified=True) for b in ("cpp", "gpu", "unmeasured")])])
    comparison = summary["comparisons"][0]
    assert comparison["fastest_observed_backends"] == ["gpu"] and not comparison["complete_backend_coverage"]
    assert comparison["backends"][0]["median_seconds"] == 3
    assert comparison["backends"][0]["spread_seconds"] == 4
    assert summary["per_problem"]["triangle-counting"] == {"completed": 4, "timeout": 1, "oom": 1}
