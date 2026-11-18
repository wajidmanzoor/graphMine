"""Independent posterior checks, held-out gates and constrained runtime choices."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from graphmine_agent.backend_learning import evaluation, linear, models, policy, storage, worker
from test_backend_feasibility import GIB, candidate, hardware, memory_dir, observed_environment  # noqa: F401

IMPLEMENTATION = "a" * 64
ADMISSION = "b" * 64


@pytest.fixture
def directories():
    name = uuid4().hex
    data = storage.DEFAULT_DATA_DIR / "evaluations/phase4" / name
    model = storage.DEFAULT_MODEL_DIR / "evaluations/phase4" / name
    storage.prepare_directories(data, model, Path(__file__).resolve().parents[2])
    return data, model


def fingerprint(name, *, held=False):
    for index in range(10000):
        value = hashlib.sha256(f"{name}:{index}".encode()).hexdigest()
        if linear.held_out(value) == held:
            return value
    raise AssertionError("Could not construct a fixture partition")


def card(operation="fixture-operation"):
    return dict(id=operation, parameters={}, backends=[
        dict(id=b, device="cpu" if b == "cpp" else "gpu", verified=True, compiled=True)
        for b in ("cpp", "gpu-first")])


def observation(backend="cpp", duration=1, *, name="fixture", n=10, held=False, **changes):
    shape = dict(n=n, m=n * 2, average_degree=4, max_degree=8, degree_cv=.5, degeneracy=2,
                 directed=False, weighted=False, bipartite_ratio=None, input_bytes=100,
                 snapshot_fingerprint=fingerprint(name, held=held), input_kind="graph")
    machine = hardware(free_gpu=100 * GIB)
    machine["gpus"][1].update(utilization_percent=0, other_processes=0)
    return dict(dict(schema_version=storage.SCHEMA_VERSION, run_id=uuid4().hex, operation="fixture-operation",
        created_at=storage.utc_now(), implementation_sha256=IMPLEMENTATION, source="benchmark", is_evaluation=False,
        graph_features=shape, hardware=machine, parameters={}, chosen_backend=backend, requested_backend=backend,
        candidates=[candidate(), candidate("gpu-first")], outcome="completed", execution_started=True,
        runtime_seconds=duration, timeout_seconds=1800, censored=False, output_estimate=100,
        peak_memory={"process_rss_bytes": 1024, "gpu_bytes": 1024}, telemetry_warnings=[],
        comparison_id=name, graph_id=name), **changes)


def fit(rows, operation="fixture-operation"):
    return linear.fit(operation, rows, ["cpp", "gpu-first"], {}, IMPLEMENTATION)


def test_posterior_matches_scalar_gaussian_conditioning_and_wide_new_head():
    rows = [observation("cpp", 1), observation("gpu-first", 4)]
    model = fit(rows)
    center = -math.log(2)
    # Constant contexts standardize to zero, leaving only the intercept. This
    # is the closed-form scalar Normal update, independent of matrix inversion.
    assert model["heads"]["cpp"]["mean"][0] == pytest.approx(center / 26)
    assert model["heads"]["cpp"]["covariance"][0][0] == pytest.approx(25 / 26)
    assert model["heads"]["gpu-first"]["mean"][0] == pytest.approx((center + 25 * -math.log(4)) / 26)
    predictions = linear.predict(model, rows[0], ["cpp", "gpu-first", "new-backend"], seed=12)
    assert predictions["new-backend"]["prior_only"]
    assert predictions["new-backend"]["reward_std"] > predictions["cpp"]["reward_std"]
    assert predictions["new-backend"]["p90_seconds"] > predictions["new-backend"]["p50_seconds"]


def test_cholesky_solves_an_independent_known_system_and_rejects_invalid_posteriors():
    assert linear.solve_spd(linear.cholesky([[4, 2], [2, 3]]), [6, 5]) == pytest.approx([1, 1])
    for matrix in ([[1, 2], [2, 1]], [[1, 0], [1, 1]], [[float("nan")]]):
        with pytest.raises(ValueError):
            linear.cholesky(matrix)


def test_timeouts_are_penalized_oom_and_evaluation_never_update_reward():
    timeout = observation(outcome="timeout", censored=True, timeout_seconds=10, runtime_seconds=10)
    assert linear.runtime_observation(timeout) == pytest.approx(-math.log(20))
    for changes in (dict(outcome="oom"), dict(is_evaluation=True), dict(execution_started=False),
                    dict(outcome="error"), dict(censored=True), dict(runtime_seconds=float("nan"))):
        assert linear.runtime_observation(observation(**changes)) is None
    records = [observation(), timeout, observation(outcome="oom"), observation(is_evaluation=True)]
    model = fit(records)
    assert model["training_rows"] == 2 and model["outcome_counts"] == {"completed": 1, "timeout": 1}


def test_held_out_repeats_and_test_rows_cannot_change_scaler_or_weights():
    training = observation("cpp", 1)
    validation = observation("gpu-first", 2, name="held", held=True)
    test = observation("gpu-first", 3, is_evaluation=True, name="evaluation")
    before = fit([training, validation, test])
    validation["runtime_seconds"] = 1e10
    validation["graph_features"]["n"] = 1e9
    validation["hardware"]["gpus"][1]["model"] = "HELD-OUT-GPU"
    test["runtime_seconds"] = 1e-9
    after = fit([training, validation, copy.deepcopy(validation), test])
    assert before == after
    assert "HELD-OUT-GPU" not in json.dumps(after["encoder"])
    assert before["training_snapshots"] == [training["graph_features"]["snapshot_fingerprint"]]


def test_context_uses_gpu1_and_aggregate_parameters_without_identifiers():
    record = observation()
    record["parameters"] = {"k": 3, "mode": "count", "sources": {"count": 2}, "source": {"redacted": True}}
    schemas = {"k": {"kind": "integer"}, "mode": {"kind": "string", "choices": ["count", "list"]},
               "sources": {"kind": "array"}, "source": {"kind": "vertex_id"}}
    encoder = linear.make_encoder([record], schemas)
    first = linear.vector(encoder, record)
    record["hardware"]["gpus"][0].update(free_memory_bytes=1, model="PRIVATE-OTHER-GPU", utilization_percent=100)
    assert linear.vector(encoder, record) == first
    record["hardware"]["gpus"][1]["free_memory_bytes"] //= 2
    assert linear.vector(encoder, record) != first
    assert "parameter:source" not in encoder["feature_names"]


@pytest.fixture
def decision_fixture(monkeypatch):
    record = observation(n=10)
    model = fit([record, observation("gpu-first", 1)])
    model["heads"]["gpu-first"].update(completed_max={"n": 100, "m": 100}, run_count=5)
    predictions = {"cpp": {"p50_seconds": 10, "p90_seconds": 15, "sampled_value": 0},
                   "gpu-first": {"p50_seconds": 11, "p90_seconds": 20, "sampled_value": 5}}
    def predict(_, __, backend_ids, **kwargs):
        return {b: predictions[b] for b in backend_ids}
    monkeypatch.setattr(policy, "predict", predict)
    def choose(**options):
        return policy.decide([candidate(), candidate("gpu-first"), candidate("infeasible", feasible=False)],
            record, model=model, mode=options.pop("mode", "bandit"), live_allowed=options.pop("live_allowed", True),
            seed=42, reserve=options.pop("reserve", lambda: {"allowed": True}), **options)
    return record, model, predictions, choose


def test_exploration_never_chooses_an_infeasible_backend(decision_fixture):
    _, _, _, choose = decision_fixture
    decision = choose()
    assert decision["chosen_backend"] == "gpu-first" and decision["reason"] == "explore"
    assert "infeasible" not in decision["predictions"]


@pytest.mark.parametrize("limit", ["kill_switch", "predicted_slowdown", "unmeasured_size", "daily_budget"])
def test_every_exploration_limit_falls_back_to_best_p50(decision_fixture, limit):
    record, model, predictions, choose = decision_fixture
    options = {}
    if limit == "kill_switch":
        options["exploration_enabled"] = False
    elif limit == "predicted_slowdown":
        predictions["gpu-first"]["p50_seconds"] = 15.01
    elif limit == "unmeasured_size":
        record["graph_features"]["m"] = 101
    else:
        options["reserve"] = lambda: {"allowed": False}
    decision = choose(**options)
    assert decision["chosen_backend"] == "cpp" and decision["reason"] == "exploit"
    assert limit in decision["exploration"]["blocked_by"]


def test_small_run_exception_requires_measured_range_and_fewer_than_five_runs(decision_fixture):
    record, model, _, choose = decision_fixture
    record["graph_features"]["n"] = 101
    head = model["heads"]["gpu-first"]
    head.update(run_count=4, benchmark_range={"n": [10, 200], "m": [10, 200]})
    assert choose()["reason"] == "explore"
    head["run_count"] = 5
    assert choose()["chosen_backend"] == "cpp"
    head.update(run_count=0, completed_max=None, benchmark_range=None)
    assert choose()["chosen_backend"] == "cpp"


def test_shadow_and_unmet_rollout_gate_preserve_native_auto_and_forced_backends(decision_fixture):
    _, _, predictions, choose = decision_fixture
    predictions["gpu-first"]["sampled_value"] = -5
    shadow = choose(mode="shadow")
    assert shadow["shadow_choice"] == "cpp" and shadow["chosen_backend"] == "gpu-first"
    assert shadow["native_backend"] == "auto"
    blocked = choose(live_allowed=False)
    assert blocked["native_backend"] == "auto" and blocked["policy_warning"] == "rollout_gate_not_met"
    forced = choose(requested_backend="cpp")
    assert forced["chosen_backend"] == forced["native_backend"] == "cpp" and forced["reason"] == "forced"


def test_thompson_choice_is_reproducible_for_fixed_seed():
    record = observation()
    model = fit([record, observation("gpu-first", 1.1)])
    options = dict(model=model, mode="bandit", live_allowed=True, seed=901, reserve=lambda: {"allowed": True})
    assert policy.decide([candidate(), candidate("gpu-first")], record, **options) == policy.decide(
        [candidate(), candidate("gpu-first")], record, **options)


@pytest.mark.parametrize("device,backend", [("cpu", "cpp"), ("gpu", "gpu-first")])
def test_forced_device_stays_forced_in_live_telemetry(device, backend):
    record = observation(backend)
    decision = policy.decide([candidate(backend)], record, model=fit([record]),
        mode="bandit", live_allowed=True, requested_device=device, seed=7)
    assert decision["chosen_backend"] == decision["native_backend"] == backend
    assert decision["reason"] == "forced" and decision["backend_choice_reason"] == "only_option"


def test_exploration_within_forced_device_still_consumes_daily_budget(directories):
    data, _ = directories
    now = datetime.now(timezone.utc)
    path = data / "runs" / now.strftime("%Y/%m/%d") / "runs-fixture.jsonl"
    for index in range(10):
        storage.append_row(path, observation(source="application", selection_mode="bandit", reason="forced",
            requested_device="gpu", decision_id=str(index), backend_choice_reason="explore" if index == 0 else "exploit"))
    result = policy.reserve_exploration(data, "fixture-operation", "next", "bandit", .1, now=now)
    assert result["limit"] == result["reserved_explorations"] == 1
    assert not result["allowed"]


def test_daily_budget_is_atomic_and_never_counts_tests_benchmarks_or_fallback_twice(directories):
    data, _ = directories
    now = datetime.now(timezone.utc)
    path = data / "runs" / now.strftime("%Y/%m/%d") / "runs-fixture.jsonl"
    records = [observation(source="application", decision_id=f"decision-{i}") for i in range(10)]
    records += [observation(source="application", decision_id="decision-0", reason="fallback")]
    records += [observation(source="application", is_evaluation=True), observation()]
    for record in records:
        storage.append_row(path, record)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: policy.reserve_exploration(data, "fixture-operation", str(i), "bandit", .1, now=now), range(4)))
    assert sum(r["allowed"] for r in results) == 1
    assert all(r["logged_decisions"] == 10 and r["limit"] == 1 for r in results)
    assert not policy.reserve_exploration(data, "fixture-operation", "unlogged-reservation", "bandit", .1, now=now)["allowed"]


def test_adaptive_timeout_obeys_minimum_job_limit_and_total_remaining_budget():
    assert policy.timeout_seconds({"p90_seconds": 1}, minimum=60, remaining=1800, cap=1800) == 60
    assert policy.timeout_seconds({"p90_seconds": 30}, minimum=60, remaining=1800, cap=1800) == 90
    assert policy.timeout_seconds({"p90_seconds": 1000}, minimum=60, remaining=1700, cap=900) == 900
    assert policy.timeout_seconds({"p90_seconds": 1}, minimum=60, remaining=20, cap=1800) == 20


def paired_data():
    rows = []
    for held, sizes in ((False, [1, 3, 7, 15, 31, 63, 127] * 4), (True, [3, 7, 15, 31, 63])):
        for index, n in enumerate(sizes):
            for backend, duration in (("cpp", n + 1), ("gpu-first", 256 / (n + 1))):
                rows.append(observation(backend, duration, name=f"{'hold' if held else 'train'}-{index}", n=n, held=held))
    for i in range(200):
        rows.append(observation("gpu-first", 16, name="shadow", n=15, source="application",
            decision_id=f"shadow-{i}", selection_mode="shadow", model_version="prior-test", shadow_choice="gpu-first"))
    return rows


def test_held_out_report_compares_three_baselines_and_requires_shadow_history():
    rows = paired_data()
    model = fit(rows)
    report = evaluation.compare(model, rows, card())
    assert report["held_out_graphs"] == 5 and report["held_out_gate_passed"] and report["live_ready"]
    assert report["metrics"]["mean_regret"] == pytest.approx(1)
    assert report["metrics"]["mean_seconds"]["selected"] < report["metrics"]["mean_seconds"]["fastest_average"]
    for record in rows:
        if record["source"] == "application":
            record["is_evaluation"] = True
    assert not evaluation.compare(model, rows, card())["live_ready"]


def test_shadow_gate_accepts_two_weeks_or_two_hundred_real_steps():
    now = datetime.now(timezone.utc)
    one = observation(source="application", selection_mode="shadow", model_version="fixture", shadow_choice="cpp",
                      created_at=(now - timedelta(days=14)).isoformat())
    assert evaluation.shadow_progress([one], one["operation"], IMPLEMENTATION, now=now)["ready"]
    one["is_evaluation"] = True
    assert not evaluation.shadow_progress([one] * 200, one["operation"], IMPLEMENTATION, now=now)["ready"]


def test_incomplete_or_missing_comparisons_never_claim_oracle_accuracy():
    rows = [observation()]
    report = evaluation.compare(fit(rows), rows, card())
    assert report["metrics"] is None and not report["live_ready"]
    assert report["skipped_comparisons"] == {"incomplete_backend_coverage": 1}


def test_version_publication_rejects_regression_and_rollback_reloads_previous(directories, monkeypatch):
    _, directory = directories
    rows, cards = paired_data(), [card()]
    first = models.train(rows, cards, model_dir=directory, implementation=IMPLEMENTATION, admission_fingerprint=ADMISSION)
    assert first["models"][0]["published"] and first["release"]["ready"]
    original, metadata = models.load(directory, cards[0]["id"], IMPLEMENTATION)
    original_version = original["model_version"]
    real_fit = linear.fit
    def regressed(*args, **kwargs):
        result = real_fit(*args, **kwargs)
        result["heads"]["cpp"]["mean"], result["heads"]["gpu-first"]["mean"] = result["heads"]["gpu-first"]["mean"], result["heads"]["cpp"]["mean"]
        return result
    with monkeypatch.context() as patch:
        patch.setattr(linear, "fit", regressed)
        second = models.train(rows, cards, model_dir=directory, implementation=IMPLEMENTATION, admission_fingerprint=ADMISSION)
        assert not second["models"][0]["published"]
        assert models.load(directory, cards[0]["id"], IMPLEMENTATION)[0]["model_version"] == original_version
    third = models.train(rows, cards, model_dir=directory, implementation=IMPLEMENTATION, admission_fingerprint=ADMISSION)
    assert third["models"][0]["published"]
    assert models.rollback(directory, cards[0]["id"])["current"] == original_version
    assert models.live_permitted(directory, cards[0]["id"], metadata, IMPLEMENTATION, ADMISSION)
    assert not models.live_permitted(directory, cards[0]["id"], metadata, IMPLEMENTATION, ADMISSION,
                                     configuration={**models.POLICY_SETTINGS, "exploration_budget": .5})
    for changed in (dict(exploration_budget=.05), dict(max_explore_ratio=1.2), dict(exploration_enabled=False)):
        assert models.live_permitted(directory, cards[0]["id"], metadata, IMPLEMENTATION, ADMISSION,
                                     configuration={**models.POLICY_SETTINGS, **changed})
    model_path = directory / cards[0]["id"] / original_version / "model.json"
    model_path.write_text(model_path.read_text() + " ")
    with pytest.raises(ValueError, match="hash changed"):
        models.load(directory, cards[0]["id"], IMPLEMENTATION)


def test_upgrade_compares_previous_weights_against_current_held_out_runs(directories):
    _, directory = directories
    rows, cards = paired_data(), [card()]
    models.train(rows, cards, model_dir=directory, implementation=IMPLEMENTATION, admission_fingerprint=ADMISSION)
    upgraded = "c" * 64
    for row in rows:
        row["implementation_sha256"] = upgraded
    result = models.train(rows, cards, model_dir=directory, implementation=upgraded, admission_fingerprint=ADMISSION)
    assert result["models"][0]["published"]
    assert result["models"][0]["publication_reason"] == "held_out_nonregression"
    assert models.load(directory, cards[0]["id"], upgraded)[0]["implementation_sha256"] == upgraded


@pytest.mark.parametrize("difference", [None, "runtime", "dependencies", "workers", "profile", "recipe"])
def test_benchmark_compatibility_accepts_only_cli_dispatcher_changes(directories, difference):
    from graphmine_agent.backend_learning.compatibility import benchmark_compatibility, CLI
    data, _ = directories
    prior = dict(implementation_sha256=IMPLEMENTATION, sources={CLI: "old-cli", "runtime.cpp": "same"},
        binary_sha256="old-binary", profiles={"fixture-operation": {"profile_sha256": "same", "backends": {"cpp": []}}},
        workers={"/verified/worker": "same"}, dependencies={"dependency": "same"}, isolated_build_recipes={})
    current = copy.deepcopy(prior)
    current.update(implementation_sha256="c" * 64, binary_sha256="new-binary")
    current["sources"][CLI] = "new-cli"
    if difference == "runtime":
        current["sources"]["runtime.cpp"] = "changed"
    elif difference in ("dependencies", "workers"):
        current[difference][next(iter(current[difference]))] = "changed"
    elif difference == "profile":
        current["profiles"]["fixture-operation"]["profile_sha256"] = "changed"
    elif difference == "recipe":
        current["isolated_build_recipes"]["recipe"] = "changed"
    path = data / "fixture-evidence.json"
    path.write_text(json.dumps({"builds": [prior, current]}))
    proof = benchmark_compatibility(path, "c" * 64)
    assert bool(proof) == (difference is None)
    if proof:
        original = observation()
        before = copy.deepcopy(original)
        accepted, skipped = models.admissible_rows([original, observation(source="application")], [card()], "c" * 64, proof)
        assert len(accepted) == 1 and skipped == 0
        assert original == before
        assert accepted[0]["observed_implementation_sha256"] == IMPLEMENTATION
        fitted = linear.fit(original["operation"], accepted, ["cpp", "gpu-first"], {}, "c" * 64)
        assert fitted["observed_implementations"] == {IMPLEMENTATION: 1}


def test_release_is_closed_when_another_operation_pointer_changes(directories):
    _, directory = directories
    rows, cards = paired_data(), [card(), card("another-operation")]
    rows += [dict(row, operation="another-operation", run_id=uuid4().hex) for row in rows]
    models.train(rows, cards, model_dir=directory, implementation=IMPLEMENTATION, admission_fingerprint=ADMISSION)
    _, metadata = models.load(directory, cards[0]["id"], IMPLEMENTATION)
    assert models.live_permitted(directory, cards[0]["id"], metadata, IMPLEMENTATION, ADMISSION)
    models.atomic_text(directory / "another-operation/current", "changed-version")
    assert not models.live_permitted(directory, cards[0]["id"], metadata, IMPLEMENTATION, ADMISSION)


def test_async_oom_updates_feasibility_but_evaluation_does_not(directories):
    from graphmine_agent.backend_learning import memory
    data, _ = directories
    item = observation("gpu-first", outcome="oom", source="application")
    log = storage.RunLog(data)
    try:
        log.submit(dict(item, is_evaluation=True))
        log.flush()
        assert not (data / "memory_models/gpu-first.json").exists()
        item["run_id"] = uuid4().hex
        log.submit(item)
        log.flush()
        model = json.loads((data / "memory_models/gpu-first.json").read_text())
        assert sum(p["oom_count"] for p in model["profiles"].values()) == 1
        prediction = memory.predict_memory(item["operation"], item["candidates"][1], item["graph_features"],
            item["parameters"], item["hardware"], output_estimate=item["output_estimate"],
            implementation=IMPLEMENTATION, data_dir=data)
        assert prediction[0] > item["hardware"]["gpus"][1]["free_memory_bytes"]
        fitted, _ = memory.rebuild(data)
        assert sum(p["oom_count"] for p in fitted["gpu-first"]["profiles"].values()) == 1
    finally:
        log.close()


def test_isolated_native_attempt_respects_cpu_backend_and_result_limit(monkeypatch):
    from graphmine.contracts import Budget
    from graphmine.exceptions import GraphMineError
    from graphmine_agent.backend_learning.attempt import run
    from test_backend_telemetry import graph
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    result = run("triangle-counting", graph(3, [(0, 1), (1, 2), (0, 2)]), device="cpu",
                 backend="cpp", allowed_backends=["cpp"], budget=Budget(timeout_seconds=10))
    assert result["backend"]["id"] == "cpp" and result["result"]["count"] == 1
    with pytest.raises(GraphMineError, match="response byte limit"):
        run("triangle-counting", graph(3, [(0, 1), (1, 2), (0, 2)]), device="cpu",
            backend="cpp", budget=Budget(timeout_seconds=10), response_limit=16)


def test_attempt_hard_timeout_kills_child_and_grandchild(directories, monkeypatch):
    from graphmine.contracts import Budget
    from graphmine_agent.backend_learning import attempt
    from test_backend_telemetry import graph
    data, _ = directories
    identity = data / "descendants.json"
    native_popen = subprocess.Popen
    child = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"
    script = ("import subprocess,sys,os,json,time;from pathlib import Path;"
              f"p=subprocess.Popen([sys.executable,'-c',{child!r}]);"
              f"Path({str(identity)!r}).write_text(json.dumps([os.getpid(),p.pid]));"
              "sys.stdin.buffer.read();time.sleep(30)")
    def launch(_args, **kwargs):
        return native_popen([sys.executable, "-c", script], **kwargs)
    monkeypatch.setattr(attempt.subprocess, "Popen", launch)
    start = time.monotonic()
    with pytest.raises(TimeoutError, match="deadline"):
        attempt.run("triangle-counting", graph(1, []), device="cpu", budget=Budget(timeout_seconds=1))
    assert time.monotonic() - start < 5
    for pid in json.loads(identity.read_text()):
        deadline = time.monotonic() + 2
        while True:
            try:
                status = Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].strip()
            except FileNotFoundError:
                break
            if status.startswith("Z"):
                break
            assert time.monotonic() < deadline, "A timed-out attempt left a live descendant"
            time.sleep(.02)


def test_workflow_forced_backend_validation_hash_and_native_propagation(monkeypatch):
    from graphmine import workflows, evidence
    from graphmine.exceptions import GraphMineError
    from graphmine_agent.analytics_scheduler import execution_admission
    from test_backend_telemetry import graph
    plan = dict(version=1, device="cpu", steps=[dict(id="count", operation="triangle-counting", input={"input": "main"})])
    inputs = {"main": {"kind": "graph", "data": graph(3, [(0, 1), (1, 2), (0, 2)])}}
    implicit = workflows.validate_workflow(plan, inputs)
    assert "backend" not in implicit["plan"]["steps"][0]
    plan["steps"][0]["backend"] = "cpp"
    explicit = workflows.validate_workflow(plan, inputs)
    assert explicit["workflow_hash"] != implicit["workflow_hash"]
    calls = []
    original = workflows.run
    def invoke(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(workflows, "run", invoke)
    workflows.execute_workflow(plan, inputs)
    assert calls[0]["backend"] == "cpp" and calls[0]["device"] == "cpu"
    caps = {"operations": [dict(id="triangle-counting", verified_backends=[], execution={"cpu": True, "gpu": True})]}
    with pytest.raises(GraphMineError, match="requested backend"):
        evidence.require_workflow_evidence(explicit, caps)
    compiled_gpu = next(b["id"] for b in workflows.algorithm("triangle-counting").card()["backends"]
                        if b["compiled"] and b["device"] == "gpu")
    plan["steps"][0]["backend"] = compiled_gpu
    with pytest.raises(GraphMineError, match="conflicts"):
        workflows.validate_workflow(plan, inputs)
    plan["device"] = "auto"
    checked = workflows.validate_workflow(plan, inputs)
    cards = [dict(id="triangle-counting", backends=[dict(id=compiled_gpu, device="gpu", verified=True,
        verified_devices=["GPU-B"])], execution={"cpu": True, "gpu": True})]
    assert execution_admission(checked["plan"], cards) == ("gpu", {"GPU-B"})
    checked["plan"]["steps"][0]["backend"] = "cpp"
    assert execution_admission(checked["plan"], cards) == ("cpu", set())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,forced", [("shadow", "auto"), ("bandit", "auto"), ("shadow", "cpp")])
async def test_real_shadow_and_gated_bandit_keep_legacy_backend(
    directories, settings, database, graph_store, mode, forced
):
    from graphmine.dispatch import implementation_hash
    from graphmine_agent.analytics import AnalyticsService
    from graphmine_agent.backend_learning.hardware import hardware_snapshot
    from graphmine_agent.backend_learning.model_cli import native_context
    from graphmine_agent.jobs import EventBus
    from test_backend_telemetry import graph
    uuid = os.environ.get("GRAPHMINE_TELEMETRY_TEST_GPU_UUID")
    if not uuid:
        pytest.skip("Set GRAPHMINE_TELEMETRY_TEST_GPU_UUID to physical GPU 1")
    assert hardware_snapshot(leased_gpu_uuid=uuid)["leased_gpu_index"] == 1
    data, directory = directories
    settings = replace(settings, backend_data_dir=data, backend_model_dir=directory,
        backend_selection=mode, backend_exploration_enabled=False, llm_enabled=False,
        graph_gpu_uuid=None, analytics_gpu_uuids=(uuid,), job_timeout_seconds=60)
    # Use synthetic timing fixtures only inside this isolated evaluation root.
    # The real executed rows below are explicitly marked evaluation.
    before = {key: os.environ.get(key) for key in ("CUDA_VISIBLE_DEVICES", "GRAPHMINE_NATIVE_LIBRARY")}
    try:
        cards, implementation, admission = native_context(settings, data)
    finally:
        for key, value in before.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
    selected = next(c for c in cards if c["id"] == "triangle-counting")
    backends = [b for b in selected["backends"] if b["verified"]]
    legacy = next(b["id"] for b in backends if b["device"] == "gpu")
    rows = []
    for backend in backends:
        row = observation(backend["id"], .01 if backend["id"] == "cpp" else 100,
                          operation=selected["id"], implementation_sha256=implementation)
        row["candidates"] = [{**b, "admitted": True} for b in backends]
        rows.append(row)
    trained = models.train(rows, [selected], model_dir=directory, implementation=implementation, admission_fingerprint=admission)
    assert not trained["release"]["ready"]
    service = AnalyticsService(settings, database, graph_store, EventBus(database))
    plan = dict(version=1, device="auto", steps=[dict(id="count", operation="triangle-counting", backend=forced,
                                                   input={"input": "main"})])
    inputs = {"main": {"kind": "graph", "data": graph(3, [(0, 1), (1, 2), (0, 2)])}}
    try:
        checked = await service._call(dict(command="validate", plan=plan, inputs=inputs))
        async with service.scheduler.reserve("gpu" if forced == "auto" else "cpu", 1024 ** 3,
                timeout=10, allowed_gpu_uuids={uuid}) as lease:
            result = await service._call(dict(command="run", plan=plan, inputs=inputs,
                expected_hash=checked["workflow_hash"], telemetry={"is_evaluation": True}), lease=lease)
        assert result["status"] == "completed"
        actual = result["steps"]["count"]["result"]["backend"]
        assert actual["id"] == (legacy if forced == "auto" else forced)
        service.run_log.flush()
        records = list(storage.read_rows(data))
        assert len(records) == 1
        row = records[0]
        assert row["is_evaluation"] and row["model_version"] and row["execution_isolated"]
        assert row["prediction_error"] is not None
        assert row["chosen_backend"] == actual["id"]
        if forced == "auto":
            assert actual["hardware"]["uuid"] == uuid
            assert row["shadow_choice"] == "cpp" and row["selection_mode"] == "shadow"
        else:
            assert actual["device"] == "cpu" and row["requested_backend"] == "cpp"
        assert not evaluation.shadow_progress(records, selected["id"], implementation_hash())["ready"]
    finally:
        await service.close()


@pytest.fixture
def bandit_worker(observed_environment, monkeypatch):
    graph, _ = observed_environment
    monkeypatch.setattr(worker, "hardware_snapshot", lambda **k: hardware(free_gpu=100 * GIB))
    rows = [observation("cpp", 10, operation="triangle-counting", n=2),
            observation("gpu-first", .1, operation="triangle-counting", n=2)]
    model = fit(rows, operation="triangle-counting")
    monkeypatch.setattr(models, "load", lambda *a, **k: (model, {"model_version": "fixture"}))
    monkeypatch.setattr(models, "live_permitted", lambda *a, **k: True)
    return graph


@pytest.mark.parametrize("failure", [TimeoutError, MemoryError])
def test_fallback_runs_once_on_a_different_feasible_backend_and_logs_both(bandit_worker, failure):
    from graphmine.contracts import Budget
    calls, events = [], []
    def invoke(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise failure("out of memory" if failure is MemoryError else "timed out")
        return {"backend": {"id": kwargs["backend"]}}
    result = worker.run_observed(invoke, "triangle-counting", bandit_worker, context={
        "backend_selection": "bandit", "leased_gpu_uuid": "GPU-test", "backend_exploration_enabled": False},
        step_id="count", emit=events.append, budget=Budget(timeout_seconds=1800), device="auto")
    rows = [e["record"] for e in events if e["event"] == "native_finished"]
    assert [c["backend"] for c in calls] == ["gpu-first", "cpp"]
    assert result["backend"]["id"] == "cpp" and len(rows) == 2
    assert rows[1]["reason"] == "fallback" and len(rows[1]["fallback_chain"]) == 2
    assert rows[0]["decision_id"] == rows[1]["decision_id"]
    assert len({r["run_id"] for r in rows}) == 2


def test_second_failure_never_retries_again_and_forced_backend_never_changes(bandit_worker):
    from graphmine.contracts import Budget
    for backend, expected in (("auto", 2), ("gpu-first", 1)):
        calls = []
        def invoke(*args, **kwargs):
            calls.append(kwargs["backend"])
            raise MemoryError("out of memory")
        with pytest.raises(MemoryError):
            worker.run_observed(invoke, "triangle-counting", bandit_worker, context={
                "backend_selection": "bandit", "leased_gpu_uuid": "GPU-test", "backend_exploration_enabled": False},
                step_id="count", emit=lambda _: None, budget=Budget(timeout_seconds=1800), device="auto", backend=backend)
        assert len(calls) == expected and len(set(calls)) == expected


def test_fallback_needs_sixty_seconds_remaining(bandit_worker):
    from graphmine.contracts import Budget
    events, calls = [], []
    def invoke(*args, **kwargs):
        calls.append(kwargs)
        raise MemoryError("out of memory")
    with pytest.raises(TimeoutError, match="fewer than 60"):
        worker.run_observed(invoke, "triangle-counting", bandit_worker, context={
            "backend_selection": "bandit", "leased_gpu_uuid": "GPU-test", "backend_exploration_enabled": False},
            step_id="count", emit=events.append, budget=Budget(timeout_seconds=30), device="auto")
    row = next(e["record"] for e in events if e["event"] == "native_finished")
    assert len(calls) == 1 and row["fallback_skipped"] == "fewer_than_60_seconds_remain"


def test_forced_gpu_fallback_never_uses_cpu(bandit_worker):
    from graphmine.contracts import Budget
    calls = []
    def invoke(*args, **kwargs):
        calls.append(kwargs)
        raise MemoryError("out of memory")
    with pytest.raises(ValueError, match="No feasible"):
        worker.run_observed(invoke, "triangle-counting", bandit_worker, context={
            "backend_selection": "bandit", "leased_gpu_uuid": "GPU-test", "backend_exploration_enabled": False},
            step_id="count", emit=lambda _: None, budget=Budget(timeout_seconds=1800), device="gpu")
    assert len(calls) == 1 and calls[0]["backend"] == "gpu-first"
