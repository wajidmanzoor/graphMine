"""Shared-network gradients, offline training, masked policy and execution contracts."""
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
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from graphmine_agent.backend_learning import shared, models, evaluation, policy, storage, worker
from test_backend_feasibility import GIB, candidate, hardware, memory_dir, observed_environment

IMPLEMENTATION = 'a' * 64
ADMISSION = 'b' * 64


def card(problem='triangle-counting'):
    return dict(id=problem, parameters={'mode': {'kind': 'string', 'choices': ['count', 'enumerate'], 'default': 'count'},
        'result_limit': {'kind': 'integer', 'default': None}, 'sources': {'kind': 'array'}},
        backends=[dict(id=b, device='cpu' if b == 'cpp' else 'gpu', verified=True, compiled=True) for b in ['cpp', 'gpu-first']])


def context(index=0, busy=False, problem='triangle-counting'):
    return dict(problem=problem, parameters={'mode': 'count'}, execution_isolated=True,
        graph_features=dict(n=10+index, m=20+index, average_degree=4, max_degree=8, degree_cv=.5,
            degeneracy=2, directed=False, weighted=False, bipartite_ratio=None, input_bytes=100,
            snapshot_fingerprint=hashlib.sha256(str(index).encode()).hexdigest()),
        hardware=dict(total_cores=8, free_cores=1 if busy else 8, free_ram_bytes=100*GIB,
            leased_gpu_index=1, gpus=[dict(index=0, utilization_percent=99, free_memory_bytes=0),
                                    dict(index=1, utilization_percent=0, free_memory_bytes=10*GIB)]))


def paired_rows(count=12):
    rows=[]
    for index in range(count):
        for busy in (False, True):
            row=context(index,busy)
            # CPU contention reverses the winner; every graph occurs in both regimes.
            for backend, duration in [('cpp', 1 if not busy else 8), ('gpu-first', 3)]:
                rows.append(dict(row, run_id=uuid4().hex, schema_version=5, source='benchmark', is_evaluation=False,
                    implementation_sha256=IMPLEMENTATION, chosen_backend=backend, requested_backend=backend,
                    runtime_seconds=duration, outcome='completed', candidates=[candidate(), candidate('gpu-first')],
                    eligible_backends=['cpp','gpu-first'], paired_eligible_backends=['cpp','gpu-first'], pair_context=row,
                    comparison_id=f'{index}:{busy}', load_regime='busy_cpu' if busy else 'idle', created_at=storage.utc_now()))
    return rows


@pytest.fixture(scope='module')
def fitted():
    cases,_=shared.paired_cases(paired_rows())
    training,held=shared.split_graphs(cases)
    model=shared.train(training,[card()],IMPLEMENTATION,epochs=150)
    return model,training,held


def test_shared_architecture_learns_load_reversal_and_has_no_auxiliary_heads(fitted):
    model,_,held=fitted
    assert set(model['weights']) == {'w1','b1','w2','b2','wo','bo'}
    assert np.shape(model['weights']['w2']) == (64,32)
    assert np.shape(model['weights']['wo']) == (32,2)
    assert 'heads' not in model
    for busy,expected in [(False,'cpp'),(True,'gpu-first')]:
        row=copy.deepcopy(held[0]['context']);row['hardware']['free_cores']=1 if busy else 8
        assert shared.encode(model,row).shape == (32,)
        scores=shared.preferences(model,row,['cpp','gpu-first'])
        assert max(scores,key=scores.get) == expected
    assert model['training']['losses'][-1] < model['training']['losses'][0] / 10


def test_gradients_match_independent_finite_differences(fitted):
    model,training,_=fitted
    weights={k: v.copy() for k,v in shared._weights(model).items()}
    x=shared.matrix([training[0]['context']],model)
    logits,cache=shared.forward(x,weights)
    mask=np.ones_like(logits,dtype=bool)
    costs=np.array([[0.,2.]])
    p=shared.masked_softmax(logits,mask)
    grad=p*(costs-(p*costs).sum(axis=1,keepdims=True))
    analytic=shared.backward(weights,cache,grad,'shared_nn')
    for name,index in [('bo',(0,)),('wo',(1,0)),('w2',(3,4)),('w1',(0,0))]:
        base=weights[name][index]
        def loss(delta):
            weights[name][index]=base+delta
            return float((shared.masked_softmax(shared.forward(x,weights)[0],mask)*costs).sum())
        numerical=(loss(1e-5)-loss(-1e-5))/2e-5
        weights[name][index]=base
        assert analytic[name][index] == pytest.approx(numerical,abs=1e-7)


def test_graph_holdout_and_train_only_normalization(fitted):
    model,training,held=fitted
    assert not set(model['training']['graphs']) & {c['context']['graph_features']['snapshot_fingerprint'] for c in held}
    before=copy.deepcopy(model['normalization'])
    held[0]['context']['hardware']['free_ram_bytes']=10**20
    shared.matrix([held[0]['context']],model)
    assert model['normalization'] == before
    assert 'logical_cores' in before['dropped_features']
    assert 'free_core_fraction' not in before['dropped_features']


def test_graph_problem_hardware_features_and_missing_flags():
    row=context()
    schema=shared.feature_schema([card()]);features=dict(zip([s['name'] for s in schema],shared.raw_features(row,schema)))
    assert features['gpu_utilization']==0 and features['logical_cores']==8
    assert features['bipartite_ratio:missing']==1
    assert features['problem:triangle-counting']==1
    assert len(schema)==31


def test_catalog_parameter_growth_does_not_change_feature_schema():
    original=card()
    expanded=copy.deepcopy(original)
    expanded['parameters'].update({
        'mode': {'kind': 'string', 'choices': ['count','enumerate','new-mode']},
        'new_flag': {'kind': 'boolean', 'default': True},
        'new_threshold': {'kind': 'number', 'default': .1},
        'new_collection': {'kind': 'array'},
    })
    assert shared.feature_schema([original])==shared.feature_schema([expanded])
    assert shared.feature_schema([original])==shared.feature_schema([{'id':original['id']}])


@pytest.mark.parametrize('parameters', [
    {}, {'mode':'enumerate','result_limit':10000,'sources':{'count':100}},
    {'mode':None,'result_limit':None,'new_flag':True,'new_threshold':.123},
])
def test_parameter_changes_leave_features_context_and_scores_unchanged(fitted,parameters):
    model,training,_=fitted
    original=training[0]['context']
    changed=dict(original,parameters=parameters)
    np.testing.assert_array_equal(shared.raw_features(original,model['feature_schema']),
                                  shared.raw_features(changed,model['feature_schema']))
    np.testing.assert_array_equal(shared.encode(model,original),shared.encode(model,changed))
    eligible=['cpp','gpu-first']
    assert shared.preferences(model,original,eligible)==shared.preferences(model,changed,eligible)


def test_parameter_features_and_old_artifacts_cannot_be_loaded(fitted):
    model,_,_=fitted
    legacy=copy.deepcopy(model);legacy['schema_version']=1
    with pytest.raises(ValueError,match='Unknown shared policy format'):
        shared.validate(legacy)
    invalid=copy.deepcopy(model)
    invalid['feature_schema'].append(dict(name='parameter:triangle-counting:mode',
                                          kind='category',problem='triangle-counting',parameter='mode',value='count'))
    with pytest.raises(ValueError,match='parameter-free'):
        shared.validate(invalid)


def test_loss_penalizes_slow_misses_more_than_near_ties():
    p=shared.masked_softmax(np.zeros((1,2)),np.ones((1,2),dtype=bool))
    assert float((p*np.array([[0.,2.]])).sum()) > 100*float((p*np.array([[0.,.01]])).sum())


def test_missing_pairs_and_all_failed_pairs_are_not_oracle_evidence():
    rows=paired_rows(1)
    cases,excluded=shared.paired_cases(rows[:-1])
    assert len(cases)==1 and excluded['incomplete_pairs']==1
    for row in rows: row['outcome']='timeout'
    cases,excluded=shared.paired_cases(rows)
    assert not cases and excluded['no_completed_oracle']==2


def test_timeouts_and_failures_receive_worst_cost_without_dropping_timings():
    rows=paired_rows(1);rows[0]['outcome']='timeout'
    cases,_=shared.paired_cases(rows,failure_penalty=9)
    first=next(c for c in cases if c['load_regime']=='idle')
    assert first['costs']['cpp']==9
    assert first['outcomes']['cpp']==['timeout']


def draw(**kw):
    return dict(allowed=True, choice=policy.sample(kw['probabilities'],kw['seed']), probabilities=kw['probabilities'])


def test_masking_single_choice_forcing_and_unknown_backend(fitted):
    model,training,_=fitted;row=training[0]['context']
    candidates=[candidate(),candidate('gpu-first'),candidate('unseen',feasible=False)]
    result=policy.decide(candidates,row,model=model,mode='bandit',live_allowed=True,reserve=draw,seed=1)
    assert set(result['probabilities'])=={'cpp','gpu-first'}
    assert sum(result['probabilities'].values())==pytest.approx(1)
    assert result['selection_probability']==result['probabilities'][result['chosen_backend']]
    for options in [dict(requested_backend='cpp'),dict(requested_device='cpu')]:
        forced=policy.decide(candidates,row,model=model,mode='bandit',live_allowed=True,**options)
        assert forced['chosen_backend']=='cpp' and forced['selection_probability']==1
    single=policy.decide([candidate()],row,model=None,mode='bandit',live_allowed=True)
    assert single['selection_probability']==1 and not single['policy_warning']
    with pytest.raises(ValueError,match='Unknown'):
        shared.preferences(model,row,['unknown'])


def test_shadow_propensity_is_separate_from_actual_behavior(fitted):
    model,training,_=fitted
    result=policy.decide([candidate(),candidate('gpu-first')],training[0]['context'],model=model,
        mode='shadow',reserve=draw,seed=5)
    assert result['chosen_backend']=='gpu-first' and result['selection_probability']==1
    assert result['shadow_probability']==result['shadow_probabilities'][result['shadow_choice']]


def test_unmeasured_size_disables_softmax_before_sampling(fitted):
    model,training,_=fitted;row=copy.deepcopy(training[0]['context']);row['graph_features']['n']=100000
    result=policy.decide([candidate(),candidate('gpu-first')],row,model=model,
        mode='bandit',live_allowed=True,reserve=lambda **k: pytest.fail('Unmeasured exploration'))
    assert result['selection_probability']==1
    assert 'unmeasured_size_or_parameters' in result['exploration']['blocked_by']


def test_budget_exhaustion_changes_every_propensity_and_reservation_is_atomic(tmp_path):
    now=datetime(2026,11,24,tzinfo=timezone.utc)
    log=tmp_path/'runs/2026/11/24/runs-test.jsonl'
    for i in range(10):
        storage.append_row(log,dict(run_id=str(i),decision_id=str(i),problem='triangle-counting',
            source='application',is_evaluation=False,selection_mode='native'))
    def choose(i):
        return policy.reserve_exploration(tmp_path,'triangle-counting',str(i+20),'bandit',.1,
            probabilities={'cpp':0.,'gpu-first':1.},best='cpp',seed=i,now=now)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(choose,range(10)))
    assert sum(r['choice']=='gpu-first' for r in results)==1
    assert all(r['probabilities'][r['choice']]==1 for r in results)
    final=policy.reserve_exploration(tmp_path,'triangle-counting','last','bandit',.1,
        probabilities={'cpp':.8,'gpu-first':.2},best='cpp',seed=1,now=now)
    assert final['choice']=='cpp' and final['probabilities']['cpp']==1


def test_empirical_timeout_nearest_range_and_deadline(fitted):
    model,training,_=fitted;row=training[0]['context']
    assert policy.timeout_seconds(model,row,remaining=2)==2
    assert policy.timeout_seconds(model,row,remaining=None,multiple=3)>0
    assert policy.timeout_seconds(None,row,remaining=900,default=42)==42


def test_published_shared_artifact_integrity_and_no_per_problem_directories(tmp_path):
    rows=paired_rows()
    metadata=models.train(rows,[card()],model_dir=tmp_path,implementation=IMPLEMENTATION,
        admission_fingerprint=ADMISSION,options={'epochs':80})
    model,loaded=models.load(tmp_path,IMPLEMENTATION)
    assert loaded==metadata and set(p.name for p in tmp_path.iterdir())=={'.publication.lock','shared'}
    assert model['architecture']=='shared_nn' and not metadata['comparison']['live_ready']
    assert {'shared_nn','shared_linear','native','oracle'}==set(metadata['comparison']['policies'])
    with pytest.raises(ValueError,match='another implementation'):
        models.load(tmp_path,'c'*64)
    artifact=tmp_path/'shared'/model['model_version']/'model.json'
    value=json.loads(artifact.read_text());value['weights']['bo'][0]+=1;artifact.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='hash changed'):
        models.load(tmp_path)


def test_feedback_uses_exact_propensity_and_ignores_shadow(fitted):
    _,training,_=fitted
    online=dict(context(),source='application',is_evaluation=False,implementation_sha256=IMPLEMENTATION,
        selection_mode='bandit',selection_probability=.001,chosen_backend='cpp',eligible_backends=['cpp','gpu-first'],
        runtime_seconds=30.,outcome='completed',cost_scale_seconds=1.)
    a=shared.train(training,[card()],IMPLEMENTATION,feedback=[online],epochs=10,ipw_clip=2)
    b=shared.train(training,[card()],IMPLEMENTATION,feedback=[dict(online,selection_probability=.5)],epochs=10,ipw_clip=2)
    assert a['weights']==b['weights'] and a['training']['feedback_rows']==1
    c=shared.train(training,[card()],IMPLEMENTATION,feedback=[dict(online,selection_mode='shadow')],epochs=10)
    assert c['training']['feedback_rows']==0 and c['weights']!=a['weights']


def test_shadow_without_counterfactuals_never_reports_oracle_performance(fitted):
    model,_,_=fitted
    report=evaluation.shadow_report([],model)
    assert report['metrics'] is None and not report['live_ready']


@pytest.fixture
def directories(memory_dir):
    return memory_dir, memory_dir/'shared-model-fixture'


@pytest.fixture
def bandit_worker(observed_environment,monkeypatch):
    graph,_=observed_environment
    monkeypatch.setattr(worker,'hardware_snapshot',lambda **k: hardware(free_gpu=100*GIB))
    # With no published artifact the native ordering remains available.
    monkeypatch.setattr(models,'load',lambda *a,**k: (_ for _ in ()).throw(FileNotFoundError()))
    return graph
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
            except (FileNotFoundError, ProcessLookupError):
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
    plan = dict(version=1, device="cpu", steps=[dict(id="count", problem="triangle-counting", input={"input": "main"})])
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
    caps = {"problems": [dict(id="triangle-counting", verified_backends=[], execution={"cpu": True, "gpu": True})]}
    with pytest.raises(GraphMineError, match="requested backend"):
        evidence.require_workflow_evidence(explicit, caps)
    compiled_gpu = next((b["id"] for b in workflows.algorithm("triangle-counting").card()["backends"]
                        if b["compiled"] and b["device"] == "gpu"), None)
    if compiled_gpu is None:
        return  # CPU contract above still executes; GPU integration requires a GPU build.
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

@pytest.mark.parametrize("failure", [TimeoutError, MemoryError])
@pytest.mark.parametrize("timeout", [None, 1800])
def test_fallback_runs_once_on_a_different_feasible_backend_and_logs_both(bandit_worker, failure, timeout):
    from graphmine.contracts import Budget
    calls, events = [], []
    def invoke(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise failure("out of memory" if failure is MemoryError else "timed out")
        return {"backend": {"id": kwargs["backend"]}}
    result = worker.run_observed(invoke, "triangle-counting", bandit_worker, context={
        "backend_selection": "bandit", "leased_gpu_uuid": "GPU-test", "backend_exploration_enabled": False},
        step_id="count", emit=events.append, budget=Budget(timeout_seconds=timeout), device="auto")
    rows = [e["record"] for e in events if e["event"] == "native_finished"]
    assert [c["backend"] for c in calls] == ["gpu-first", "cpp"]
    assert result["backend"]["id"] == "cpp" and len(rows) == 2
    assert rows[1]["reason"] == "fallback" and len(rows[1]["fallback_chain"]) == 2
    assert rows[0]["decision_id"] == rows[1]["decision_id"]
    assert len({r["run_id"] for r in rows}) == 2
    if timeout is None:
        assert all(call["budget"].timeout_seconds == 300 for call in calls)
        assert all(row["step_timeout_seconds"] is None and row["timeout_seconds"] == 300 for row in rows)

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
    with pytest.raises(MemoryError):
        worker.run_observed(invoke, "triangle-counting", bandit_worker, context={
            "backend_selection": "bandit", "leased_gpu_uuid": "GPU-test", "backend_exploration_enabled": False},
            step_id="count", emit=lambda _: None, budget=Budget(timeout_seconds=1800), device="gpu")
    assert len(calls) == 1 and calls[0]["backend"] == "gpu-first"

def test_native_reference_uses_preflight_order_not_randomized_collection_order():
    rows = paired_rows(1)
    for row in rows:
        row['paired_eligible_backends'] = ['gpu-second', 'cpp', 'gpu-first']
        row['candidates'].append(candidate('gpu-second'))
    extra = [dict(row, run_id=uuid4().hex, chosen_backend='gpu-second', requested_backend='gpu-second')
             for row in rows if row['chosen_backend'] == 'gpu-first']
    cases, excluded = shared.paired_cases(rows + extra)
    assert not excluded
    assert {case['native_backend'] for case in cases} == {'gpu-first'}
