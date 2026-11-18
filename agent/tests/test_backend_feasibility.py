"""Feasibility boundaries, independent memory-fit oracles and forced policies."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from graphmine_agent.backend_learning import memory, storage, worker
from graphmine_agent.backend_learning.feasibility import feasible, filter_candidates, legacy_choice

GIB = 1024 ** 3
IMPLEMENTATION = "a" * 64


@pytest.fixture
def memory_dir():
    root = storage.DEFAULT_DATA_DIR / "evaluations" / "phase2" / uuid4().hex
    storage.prepare_directories(root, storage.DEFAULT_MODEL_DIR, Path(__file__).resolve().parents[2])
    return root


def hardware(free_gpu=GIB, *, index=1):
    return dict(cpu_model="test-cpu", free_ram_bytes=8 * GIB, leased_gpu_index=index,
                gpus=[dict(index=0, model="test-gpu", free_memory_bytes=100 * GIB),
                      dict(index=1, uuid="GPU-test", model="test-gpu", free_memory_bytes=free_gpu)])


def candidate(name="cpp", **changes):
    return dict(dict(id=name, device="cpu" if name == "cpp" else "gpu", compiled=True, admitted=True,
                     feasible=True, infeasible_reason=None, limits={"n": 100, "m": 200},
                     predicted_peak_memory_bytes=GIB), **changes)


def features(n=10, m=20):
    return dict(n=n, m=m, input_bytes=100, input_kind="graph", directed=False, weighted=False,
                snapshot_fingerprint=hashlib.sha256(f"{n},{m}".encode()).hexdigest())


@pytest.mark.parametrize("backend,shape,machine,reason", [
    (candidate(compiled=False), features(), hardware(), "not_compiled"),
    (candidate(admitted=False), features(), hardware(), "not_admitted"),
    (candidate(feasible=False, infeasible_reason="native_unsupported"), features(), hardware(), "native_unsupported"),
    (candidate(limits={}), features(), hardware(), "native_limits_unavailable"),
    (candidate(), features(n=101), hardware(), "size_or_index_limit"),
    (candidate(), features(m=201), hardware(), "size_or_index_limit"),
    (candidate("gpu"), features(), hardware(index=0), "gpu_1_lease_required"),
    (candidate("gpu"), features(), hardware(), "predicted_memory_exceeds_free_memory"),
    (candidate("gpu"), features(), hardware(free_gpu=None), "free_memory_unavailable"),
    (candidate(predicted_peak_memory_bytes=float("nan")), features(), hardware(), "memory_prediction_unavailable"),
])
def test_rejection_boundaries_record_reason(backend, shape, machine, reason):
    assert feasible("test", backend, shape, {}, machine) == (False, reason)


def test_exact_80_percent_limit_uses_leased_gpu_and_cpu_ram():
    gpu = candidate("gpu", predicted_peak_memory_bytes=800)
    assert feasible("test", gpu, features(), {}, hardware(free_gpu=1000)) == (True, None)
    gpu["predicted_peak_memory_bytes"] = 801
    assert not feasible("test", gpu, features(), {}, hardware(free_gpu=1000))[0]
    host = hardware()
    host["free_ram_bytes"] = 1000
    assert feasible("test", candidate(predicted_peak_memory_bytes=800), features(), {}, host)[0]
    assert not feasible("test", candidate(predicted_peak_memory_bytes=801), features(), {}, host)[0]
    host["backend_memory_safety"] = 0.9
    assert feasible("test", candidate(), features(), {}, host)[1] == "invalid_memory_safety"


def samples(count=40):
    rows = []
    for i in range(count):
        shape = features(1 + i, (i * 7) % 31)
        output = 1 + (i * 11) % 17
        peak = 1024 + 30 * shape["n"] + 50 * shape["m"] + 2 * output
        rows.append(dict(schema_version=2, run_id=f"fixture-{i}", created_at=storage.utc_now(),
            operation="test", chosen_backend="cpp", candidates=[candidate()], hardware=hardware(),
            graph_features=shape, parameters={"mode": "count"}, output_estimate=output,
            peak_memory={"process_rss_bytes": peak}, implementation_sha256=IMPLEMENTATION,
            is_evaluation=False, source="benchmark", outcome="completed", censored=False))
    return rows


def prediction(directory, row):
    return memory.predict_memory("test", candidate(), row["graph_features"], row["parameters"], row["hardware"],
        output_estimate=row["output_estimate"], implementation=row["implementation_sha256"], data_dir=directory)


def test_nonnegative_fit_matches_known_coefficients_and_boundary_optimum():
    rows = samples()
    x = [memory.coordinates(r["graph_features"], r["output_estimate"]) for r in rows]
    y = [r["peak_memory"]["process_rss_bytes"] for r in rows]
    assert memory.nonnegative_fit(x, y) == pytest.approx([1024, 30, 50, 2])
    # A decreasing response cannot acquire a negative size coefficient.
    result = memory.nonnegative_fit([[1, i, 0, 0] for i in range(10)], [20 - i for i in range(10)])
    assert result == pytest.approx([15.5, 0, 0, 0])


def test_fewer_than_twenty_and_evaluation_runs_never_enable_fit(memory_dir):
    rows = samples(19)
    evaluations = [{**row, "run_id": "eval-" + row["run_id"], "is_evaluation": True} for row in samples(40)]
    models, skipped = memory.fit_models(rows + evaluations)
    profile = next(iter(models["cpp"]["profiles"].values()))
    assert profile["completed_count"] == 19 and not profile["validated"] and not skipped
    memory.save_models(memory_dir, models)
    assert prediction(memory_dir, rows[0])[0] > 512 * 1024 ** 2
    assert prediction(memory_dir, rows[0])[1] is None
    assert memory.fit_models(evaluations)[0] == {}


def test_validated_fit_is_positive_scoped_and_never_extrapolated(memory_dir):
    rows = samples()
    models, skipped = memory.fit_models(rows)
    profile = next(iter(models["cpp"]["profiles"].values()))
    assert profile["validated"] and profile["held_out_count"] == 8 and not skipped
    assert profile["coefficients"] == pytest.approx([1280, 37.5, 62.5, 2.5])
    memory.save_models(memory_dir, models)
    value, version, reason = prediction(memory_dir, rows[20])
    assert version and reason == "validated_fit"
    assert value == pytest.approx(1.25 * rows[20]["peak_memory"]["process_rss_bytes"])
    outside = copy.deepcopy(rows[20])
    outside["graph_features"]["n"] = 10 ** 6
    assert prediction(memory_dir, outside)[2] == "outside_memory_fit_range"
    changed = copy.deepcopy(rows[20])
    changed["implementation_sha256"] = "b" * 64
    assert prediction(memory_dir, changed)[2] == "unseen_memory_context"
    changed = copy.deepcopy(rows[20])
    changed["parameters"]["mode"] = "list"
    assert prediction(memory_dir, changed)[2] == "unseen_memory_context"


def test_held_out_underprediction_rejects_model():
    rows = samples()
    snapshots = sorted({r["graph_features"]["snapshot_fingerprint"] for r in rows}, key=memory._digest)
    for row in rows:
        if row["graph_features"]["snapshot_fingerprint"] == snapshots[-1]:
            row["peak_memory"]["process_rss_bytes"] *= 100
    models, _ = memory.fit_models(rows)
    profile = next(iter(models["cpp"]["profiles"].values()))
    assert not profile["validated"] and profile["validation_reason"] == "held_out_underprediction"


def test_repeated_snapshot_cannot_leak_into_validation():
    rows = [{**samples(1)[0], "run_id": f"repeat-{i}"} for i in range(25)]
    models, _ = memory.fit_models(rows)
    assert next(iter(models["cpp"]["profiles"].values()))["validation_reason"] == "insufficient_distinct_graphs"


def test_oom_is_a_memory_lower_bound_not_a_completed_training_sample(memory_dir):
    rows = samples(2)
    rows[1].update(outcome="oom", peak_memory={})
    models, _ = memory.fit_models(rows)
    profile = next(iter(models["cpp"]["profiles"].values()))
    assert profile["completed_count"] == 1 and profile["oom_count"] == 1
    memory.save_models(memory_dir, models)
    value, _, reason = prediction(memory_dir, rows[1])
    assert value == 10 * GIB and reason == "observed_oom_lower_bound"
    assert not feasible("test", candidate(predicted_peak_memory_bytes=value), features(), {}, hardware())[0]
    assert prediction(memory_dir, rows[0])[2] == "conservative_default"


def test_gpu_fits_use_gpu_peaks_and_oom_uses_only_gpu1_free_memory():
    rows = samples()
    for row in rows:
        row.update(chosen_backend="gpu", candidates=[candidate("gpu")])
        row["peak_memory"] = {"gpu_bytes": row["peak_memory"]["process_rss_bytes"],
                              "process_rss_bytes": 100 * GIB}
    failed = copy.deepcopy(rows[0])
    failed.update(run_id="oom-gpu", outcome="oom", peak_memory={})
    models, skipped = memory.fit_models(rows + [failed])
    profile = next(iter(models["gpu"]["profiles"].values()))
    assert not skipped and profile["validated"] and profile["completed_count"] == 40
    assert profile["coefficients"] == pytest.approx([1280, 37.5, 62.5, 2.5])
    assert profile["oom_floors"][0]["lower_bound_bytes"] == GIB


def test_legacy_order_preserves_native_support_and_explicit_backend():
    cards = [candidate(), candidate("first", feasible=False), candidate("second"), candidate("third")]
    assert legacy_choice(cards) == "second"
    assert legacy_choice(cards, "third") == "third"
    assert legacy_choice(cards, "first") is None


def test_corrupt_memory_model_and_superseded_training_rows_fall_back(memory_dir):
    rows = samples()
    models, _ = memory.fit_models(rows)
    memory.save_models(memory_dir, models)
    path = memory_dir / "memory_models/cpp.json"
    path.write_text('{"bad"')
    assert prediction(memory_dir, rows[20])[2] == "invalid_memory_model"
    corrections = [{**r, "run_id": "corrected-" + r["run_id"], "supersedes": r["run_id"],
                    "is_evaluation": True} for r in rows]
    models, _ = memory.fit_models(rows + corrections)
    memory.save_models(memory_dir, models)
    assert json.loads(path.read_text())["profiles"] == {}


def test_memory_exclusion_keeps_legacy_order_and_forced_backend(memory_dir):
    cards = [candidate(), candidate("gpu-first"), candidate("gpu-second")]
    result = filter_candidates("test", cards, features(), {}, hardware(free_gpu=100),
                              output_estimate=100, implementation=IMPLEMENTATION, data_dir=memory_dir)
    assert legacy_choice(result) == "cpp"
    assert legacy_choice(result, "gpu-first") is None
    assert result[1]["infeasible_reason"] == "predicted_memory_exceeds_free_memory"


def test_native_capabilities_expose_limits_without_running_cuda():
    from graphmine.dispatch import native_request

    graph = {"graph": {"id": "limits", "directed": True,
                       "allows_self_loops": False, "allows_parallel_edges": False},
             "vertices": [{"id": 0}, {"id": 1}],
             "edges": [{"id": "edge", "source": 0, "target": 1, "weight": 1}]}
    caps = native_request(dict(command="backend_capabilities", operation="max-flow-min-cut", graph=graph,
                               parameters={"source": 0, "sink": 1}, device="cpu", allowed_backends=["cpp"]))
    by_id = {c["id"]: c for c in caps["candidates"]}
    assert by_id["cpp"]["feasible"] and by_id["cpp"]["limits"]["n"] > 2 ** 31
    assert by_id["ecl-maxflow"]["limits"] == {"n": 1000000, "m": 5000000}
    assert not by_id["ecl-maxflow"]["feasible"] and not by_id["ecl-maxflow"]["admitted"]


@pytest.fixture
def observed_environment(memory_dir, monkeypatch):
    import graphmine.dispatch
    from graphmine.native_inputs import Graph

    monkeypatch.setenv("GRAPHMINE_BACKEND_DATA_DIR", str(memory_dir))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-test")
    monkeypatch.setattr(worker, "hardware_snapshot", lambda **kw: hardware(free_gpu=100))
    graph = Graph({"graph": {"id": "fixture", "directed": False,
                             "allows_self_loops": False, "allows_parallel_edges": False},
                   "vertices": [{"id": 1}, {"id": 2}], "edges": []})
    queries = []

    def preflight(query):
        queries.append(query)
        cards = [candidate(), candidate("gpu-first")]
        for card in cards:
            if query["device"] != "auto" and query["device"] != card["device"]:
                card.update(feasible=False, infeasible_reason="device_policy")
        return dict(candidates=cards, legacy_backend="gpu-first", implementation_sha256=IMPLEMENTATION)

    monkeypatch.setattr(graphmine.dispatch, "native_request", preflight)
    return graph, queries


@pytest.mark.parametrize("device,backend,expected", [
    ("auto", "auto", "cpp"), ("cpu", "auto", "cpp"), ("auto", "cpp", "cpp"),
    ("gpu", "auto", None), ("auto", "gpu-first", None), ("gpu", "cpp", None),
])
def test_worker_memory_gate_and_forced_policies(observed_environment, device, backend, expected):
    graph, queries = observed_environment
    calls, events = [], []

    def invoke(*args, **kwargs):
        calls.append(kwargs)
        return {"backend": {"id": "cpp"}}

    def execute():
        return worker.run_observed(invoke, "triangle-counting", graph,
            context={"leased_gpu_uuid": "GPU-test", "is_evaluation": True},
            step_id="count", emit=events.append, device=device, backend=backend)

    if expected:
        assert execute()["backend"]["id"] == expected
        assert calls[0]["allowed_backends"] == ["cpp"]
        assert calls[0]["backend"] == backend
    else:
        with pytest.raises(ValueError, match="No feasible"):
            execute()
        assert not calls
    rows = [e["record"] for e in events if e["event"] == "native_finished"]
    assert len(rows) == 1 and rows[0]["execution_started"] == bool(expected)
    if device != "auto" or backend != "auto":
        assert rows[0]["reason"] == "forced"
    assert queries


def test_preflight_failure_cannot_bypass_gate_even_if_logging_fails(observed_environment, monkeypatch):
    import graphmine.dispatch

    graph, _ = observed_environment

    def broken(*args, **kwargs):
        raise ValueError("preflight is unavailable")

    monkeypatch.setattr(graphmine.dispatch, "native_request", broken)
    with pytest.raises(ValueError, match="preflight is unavailable"):
        worker.run_observed(lambda *a, **k: pytest.fail("Executed without admission"), "triangle-counting", graph,
            context={}, step_id="count", emit=broken, device="cpu")


def test_expired_preflight_is_not_recorded_as_native_execution(observed_environment, monkeypatch):
    graph, _ = observed_environment
    times, events = iter([0, 61, 61]), []
    monkeypatch.setattr(worker.time, "monotonic", lambda: next(times))
    with pytest.raises(TimeoutError, match="preflight exhausted"):
        worker.run_observed(lambda *a, **k: pytest.fail("Executed after deadline"), "triangle-counting", graph,
            context={"leased_gpu_uuid": "GPU-test"}, step_id="count", emit=events.append, device="cpu")
    rows = [e["record"] for e in events if e["event"] == "native_finished"]
    assert len(rows) == 1 and rows[0]["censored"]
    assert not rows[0]["execution_started"] and rows[0]["failure_stage"] == "preflight"


def test_gpu0_is_rejected_before_any_native_cuda_preflight(observed_environment, monkeypatch):
    graph, queries = observed_environment
    monkeypatch.setattr(worker, "hardware_snapshot", lambda **kw: hardware(index=0))
    with pytest.raises(ValueError, match="physical GPU 1"):
        worker.run_observed(lambda *a, **k: pytest.fail("Ran on GPU 0"), "triangle-counting", graph,
            context={"leased_gpu_uuid": "GPU-test"}, step_id="count", emit=lambda _: None, device="gpu")
    assert not queries


def test_memory_is_rechecked_after_native_support_preflight(observed_environment, monkeypatch):
    graph, queries = observed_environment
    snapshots = iter([hardware(free_gpu=100 * GIB), hardware(free_gpu=100)])
    monkeypatch.setattr(worker, "hardware_snapshot", lambda **kw: next(snapshots))
    with pytest.raises(ValueError, match="predicted_memory_exceeds_free_memory"):
        worker.run_observed(lambda *a, **k: pytest.fail("Used stale free memory"), "triangle-counting", graph,
            context={"leased_gpu_uuid": "GPU-test"}, step_id="count", emit=lambda _: None, device="gpu")
    assert len(queries) == 1
