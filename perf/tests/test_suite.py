from collections import Counter
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from perf.accounts import cleanup
from perf.common import append,write_json
from perf.journey import Journey,JourneyError
from perf.matrix import restored_environment,updated_environment
from perf.monitor import prometheus,provider_summary
from perf.report import SECTIONS,comparisons,generate,slope
from perf.run import validate_generation,safe_command


def fixture_run(root,test="soak"):
    root.mkdir()
    start = datetime(2026,1,1,tzinfo=timezone.utc)
    ts = lambda offset:(start+timedelta(seconds=offset)).isoformat()
    write_json(root/"config.json",{"test":test,"label":"fixture","requested_users":10})
    append(root/"shape.jsonl",{"ts":ts(0),"users":10})
    append(root/"questions.jsonl",{"question_id":"bicliques","question_instance_id":"q1","question_sent_at":ts(0),"end":ts(105),
        "outcome":"success","user_id":"u1","turn_ids":["t1"],"workflow_id":"w1","time_to_answer_ms":100000,"first_reply_ms":1000,
        "results_page_ms":[3000],"wrong_operation":False,"users":10})
    append(root/"questions.jsonl",{"question_id":"bicliques","question_instance_id":"q2","question_sent_at":ts(1),"end":ts(60),
        "outcome":"error","user_id":"u2","error_code":"concurrency_limit","error_step":"plan","message":"busy","users":10})
    event = lambda kind,**fields:append(root/"events.jsonl",{"ts":ts(10),"event":kind,"user_id":"u1","turn_id":"t1","workflow_id":"w1","request_id":"r1",**fields})
    event("turn_end",total_ms=100000)
    event("model_queue",wait_ms=40000,outcome="granted")
    event("model_call",stage="route",duration_ms=10000,prompt_tokens=200,completion_tokens=100,reasoning_tokens=80,time_to_first_token_ms=500,retries=0)
    event("job_queue",wait_ms=40000,outcome="started")
    event("job_run",operation="maximal-bicliques",device="gpu",duration_ms=5000,outcome="ok",peak_gpu_mb=20)
    event("result_view",duration_ms=2500)
    event("db",operation="BEGIN",duration_ms=250,lock_wait_ms=250)
    event("llm_wake",duration_ms=16000,trigger="request")
    event("exploration_save",payload_bytes=100,outcome="error",duration_ms=20)
    for offset,memory,preemptions in ((0,100,0),(3600,200,2)):
        append(root/"system.jsonl",{"ts":ts(offset),"vllm":{"waiting":2,"running":2,"kv_cache_percent":25,"preemptions_total":preemptions},
            "host":{"ram_used_bytes":memory*1024**2,"cpu_percent":20},"gpu":[{"index":0,"memory_used_mb":memory,"utilization_percent":80}],
            "sqlite_bytes":100,"errors":[],"processes":{"agent":{"tree_rss_bytes":memory*1024**2}}})
    return root


def test_fixture_report_every_section_all_ten_flags_and_compare(tmp_path):
    root = fixture_run(tmp_path/"run")
    baseline = fixture_run(tmp_path/"baseline")
    data = generate(root,baseline)
    markdown = (root/"report.md").read_text()
    page = (root/"report.html").read_text()
    assert all(f"{i}. {title}" in markdown and f"{i}. {title}" in page for i,title in enumerate(SECTIONS,1))
    assert len({r["message"] for r in data["flags"]}) == 10
    assert data["headline"]["question_error_percent"] == 50
    assert data["headline"]["model_queue_share_percent"] == 40
    assert data["headline"]["routing_reasoning_share_percent"] == 80
    assert data["headline"]["vllm_preemptions"] == 2
    assert data["model"][0]["completion_tokens_per_second"] == 10
    assert sum(r["milliseconds"] for r in data["breakdown"]) == 105000
    assert "<script src=" not in page and "vegaEmbed(" in page
    assert "N/A" in markdown
    rows = comparisons({"answer_p95_ms":50,"success_percent":90,"model_calls":1},{"answer_p95_ms":100,"success_percent":80,"model_calls":0})
    assert rows[0]["change_percent"] == -50 and rows[0]["assessment"] == "improved"
    assert next(r for r in rows if r["metric"] == "model_calls")["change_percent"] is None
    # Compile every embedded chart using the exact vendored JS shipped in HTML.
    import subprocess
    from perf.common import ROOT
    script = r"""
const fs=require('fs'),vm=require('vm');const context={console,structuredClone};vm.createContext(context);
for(const name of ['vega.min.js','vega-lite.min.js']) vm.runInContext(fs.readFileSync('agent/graphmine_agent/static/vendor/'+name,'utf8'),context);
const page=fs.readFileSync(process.argv[1],'utf8');let count=0;
for(const m of page.matchAll(/vegaEmbed\('#chart-\d+', (.*), \{actions: true\}\)/g)) {
 const spec=JSON.parse(m[1]);context.spec=spec;
 vm.runInContext('vega.parse(vegaLite.compile(spec).spec)',context);count++;
}
if(count<5)throw Error('Missing chart specs');
"""
    subprocess.run(["node","-e",script,str(root/"report.html")],cwd=ROOT,check=True,capture_output=True,text=True)


def test_stress_report_and_missing_values(tmp_path):
    root = fixture_run(tmp_path/"run","stress")
    append(root/"run-events.jsonl",{"event":"breaking_point","users":10,"error_rate":.5,"ts":"2026-01-01T00:02:00+00:00"})
    data = generate(root)
    assert data["stress"] == [{"users":10,"questions":2,"p95_answer_ms":100000,"error_percent":50}]
    assert not data["trends"]
    assert slope([(0,100),(3600,110)])["percent_per_hour"] == 10
    assert slope([(0,0)])["per_hour"] is None


def test_prometheus_rate_reset_labels_and_histograms():
    text = '''# HELP example
vllm:num_requests_running{model_name="Qwen\\\"test"} 2
vllm:num_requests_waiting 3
vllm:kv_cache_usage_perc 0.25
vllm:prompt_tokens_total 10
vllm:generation_tokens_total 20
vllm:e2e_request_latency_seconds_bucket{le="+Inf"} 4
'''
    parsed = prometheus(text)
    assert parsed[0]["labels"]["model_name"] == 'Qwen"test'
    first = provider_summary(parsed)
    assert first["running"] == 2 and first["kv_cache_percent"] == 25
    assert first["prompt_tokens_per_second"] is None
    later = provider_summary(prometheus(text.replace("total 20","total 30")),first,2)
    assert later["generation_tokens_per_second"] == 5
    reset = provider_summary(prometheus(text.replace("total 20","total 1")),later,2)
    assert reset["generation_tokens_per_second"] is None


def test_matrix_env_restores_after_failure_without_losing_secrets(tmp_path):
    path = tmp_path/"model.env"
    original = b"# preserve\nKEY='private key'\nexport GRAPHMINE_LLM_MAX_NUM_SEQS=2\n"
    path.write_bytes(original); path.chmod(0o600)
    with pytest.raises(RuntimeError):
        with restored_environment(path,tmp_path/"backup") as (content,mode):
            path.write_bytes(updated_environment(content,{"GRAPHMINE_LLM_MAX_NUM_SEQS":"8"}))
            assert b"GRAPHMINE_LLM_MAX_NUM_SEQS=8" in path.read_bytes()
            raise RuntimeError("row failed")
    assert path.read_bytes() == original and path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        updated_environment(original,{"GRAPHMINE_BAD":"$(touch /tmp/no)"})
    assert safe_command(["vllm","--api-key","secret","--token=secret"]) == ["vllm","--api-key","<redacted>","--token=<redacted>"]


def test_cleanup_refuses_foreign_account_and_live_process(tmp_path):
    import os
    run = tmp_path/"run"; data = run/"private/data"; data.mkdir(parents=True)
    db = sqlite3.connect(data/"agent.sqlite3")
    db.execute("CREATE TABLE accounts(id,username)"); db.execute("CREATE TABLE sessions(id)")
    db.execute("INSERT INTO accounts VALUES ('real','person')"); db.commit(); db.close()
    manifest = {"run":str(run),"data_root":str(data),"accounts":[{"id":"test","username":"perftest01"}],"agent_pid":None}
    write_json(run/"private/accounts.json",manifest)
    with pytest.raises(ValueError,match="not created"):
        cleanup(run)
    assert data.exists()
    db = sqlite3.connect(data/"agent.sqlite3"); db.execute("DELETE FROM accounts"); db.commit(); db.close()
    write_json(run/"private/accounts.json",{**manifest,"agent_pid":os.getpid()})
    with pytest.raises(ValueError,match="Stop"):
        cleanup(run)
    write_json(run/"private/accounts.json",manifest)
    result = cleanup(run)
    assert result["data_root_removed"] and not (run/"private/accounts.json").exists()


def test_generation_rejects_short_run_and_incomplete_benchmark(tmp_path):
    append(tmp_path/"shape.jsonl",{"users":10,"elapsed_seconds":1198})
    append(tmp_path/"questions.jsonl",{"question_id":"concept","question_sent_at":"now"})
    append(tmp_path/"system.jsonl",{"ts":"now"})
    validate_generation(tmp_path,{"test":"load","requested_users":10,"duration_seconds":1200,"locust_exit_code":1})
    with pytest.raises(RuntimeError,match="duration"):
        validate_generation(tmp_path,{"test":"load","requested_users":10,"duration_seconds":1500,"locust_exit_code":0})
    with pytest.raises(RuntimeError,match="six questions"):
        validate_generation(tmp_path,{"test":"benchmark","locust_exit_code":0})


class Immediate:
    def __init__(self,fn,*args,**kwargs):
        self.value = fn(*args,**kwargs)
    def ready(self): return True
    def get(self): return self.value


@pytest.mark.parametrize("count",[0,1,5])
def test_http_journey_choices_clarification_and_result_items(count):
    calls=[]; plans=iter([
        {"status":"needs_information","pending_question":{"id":"clarify1"},"message":"clarify"},
        {"status":"options","turn_id":"options1","options":[{"id":"opaque1","title":"First choice","operations":["correct"],"parameters":{}}]},
        {"status":"ready","turn_id":"ready1","plan":{"steps":[{"operation":"correct"}]}}])
    def request(method,path,*,step,**kwargs):
        calls.append((method,path,step,kwargs))
        if step == "plan": return next(plans)
        if step == "create_workflow": return {"id":"workflow1","status":"completed"}
        if step == "poll_conversation": return {"events":[{"type":"workflow.answer","payload":{"workflow_id":"workflow1","pending":False}}]}
        if step == "result_summary": return {"steps":{"s1":{"result":{"ports":{"p1":{}}}}}}
        if step in {"result_view","result_item"}: return {"item_count":count}
        raise AssertionError(step)
    journey = Journey(request,sleep=lambda _:None)
    journey.session_id="session1"; journey.inputs={"main":{}}
    state={}
    journey.ask({"text":"question","clarification":"clarification","expected_operations":["correct"]},state,spawn=Immediate)
    submitted=[c[3]["json"] for c in calls if c[2] == "plan"]
    assert submitted[1]["clarification_id"] == "clarify1"
    assert submitted[2]["option_id"] == "opaque1" and submitted[2]["option_turn_id"] == "options1"
    assert state["wrong_operation"] is False and state["result_items_seen"] == min(3,count)
    assert state["time_to_answer_ms"] >= state["first_reply_ms"]


def test_shapes_and_sustained_stress_cutoff_in_separate_process(tmp_path):
    import subprocess,os
    from perf.common import ROOT
    write_json(tmp_path/"private/locust.json",{"test":"load","host":"http://test","run_id":"test","accounts":[]})
    script = '''import time
import perf.locustfile as m
from perf.common import append,timestamp
s=m.GraphMineShape();elapsed=[0];s.get_run_time=lambda:elapsed[0];s.get_current_user_count=lambda:10
assert s.tick()==(10,10/60)
elapsed[0]=1200;assert s.tick() is None
m.CONFIG['test']='spike';elapsed[0]=0;assert s.tick()==(20,2)
elapsed[0]=600;assert s.tick() is None
m.CONFIG['test']='soak';elapsed[0]=0;assert s.tick()==(5,1)
elapsed[0]=7200;assert s.tick() is None
m.CONFIG['test']='stress';elapsed[0]=0;assert s.tick()==(5,1)
elapsed[0]=300;assert s.tick()==(10,1)
elapsed[0]=2700;assert s.tick()==(50,1)
elapsed[0]=3000;assert s.tick() is None
append(m.RUN/'questions.jsonl',{'end':timestamp(),'outcome':'error'})
elapsed[0]=0;assert s.tick()==(5,1)
elapsed[0]=119;assert s.tick() is not None
elapsed[0]=120;assert s.tick() is None
m.CONFIG['test']='benchmark';m.DONE=False;assert s.tick()==(1,1)
m.DONE=True;assert s.tick() is None
'''
    subprocess.run([os.sys.executable,"-c",script],cwd=ROOT,env={**os.environ,"GRAPHMINE_PERF_RUN_DIR":str(tmp_path)},check=True,capture_output=True,text=True)


def test_create_all_accounts_and_remove_every_owned_file(tmp_path,monkeypatch):
    from graphmine_agent.config import Settings
    import perf.accounts as accounts
    from perf.common import ROOT
    run=tmp_path/"run"; backend=tmp_path/"backend"
    monkeypatch.setattr(accounts,"backend_directory",lambda _:backend)
    settings=replace(Settings.from_env(ROOT),data_root=run/"private/data",backend_data_dir=backend,
                     account_daily_tokens=100000000,server_daily_tokens=10000000000,backup_directory=run/"private/backups")
    manifest=accounts.create(run,settings)
    assert len(manifest["accounts"]) == 51
    assert {a["username"] for a in manifest["accounts"]} == {*(f"perftest{i:02d}" for i in range(1,51)),"perftest_admin"}
    assert len({a["password"] for a in manifest["accounts"]}) == 51
    (run/"private/data/owned-file").write_text("sample")
    (backend/"owned-result").write_text("sample")
    receipt=accounts.cleanup(run)
    assert receipt["accounts_deleted"]==51 and not backend.exists() and not settings.data_root.exists()


@pytest.mark.parametrize("fail_row",[None,1])
def test_matrix_restarts_each_row_and_restores_service_after_failure(tmp_path,monkeypatch,fail_row):
    import perf.matrix as matrix
    import perf.run as runner
    model_env=tmp_path/"model.env"; original=b"GRAPHMINE_LLM_MAX_NUM_SEQS=2\nPRIVATE=secret\n"
    model_env.write_bytes(original);model_env.chmod(0o600)
    args=SimpleNamespace(output=tmp_path/"runs",label="matrix-test",vllm_env_file=model_env,app_python=Path("unused"))
    monkeypatch.setattr(runner,"app_environment",lambda *_:{})
    monkeypatch.setattr(runner,"settings_snapshot",lambda *_:{"settings":{"llm_base_url":"http://localhost/v1","llm_api_key":"secret"}})
    restarts=[];sleeps=[];calls=[]
    monkeypatch.setattr(matrix,"restart",lambda *_:restarts.append(model_env.read_bytes()))
    monkeypatch.setattr(matrix,"restore_sleep",lambda *_:sleeps.append(True))
    def one(args,*,overrides,matrix_row):
        calls.append((overrides,matrix_row))
        if len(calls)-1==fail_row:
            raise RuntimeError("injected load failure")
        return fixture_run(args.output/args.label,"load")
    monkeypatch.setattr(runner,"run_one",one)
    if fail_row is None:
        matrix.run_matrix(args)
        assert len(calls)==5 and len(restarts)==6
        assert b"GRAPHMINE_LLM_MAX_NUM_SEQS=8" in restarts[1]
        assert restarts[2]==original
        assert list(args.output.glob("*/report.html"))
    else:
        with pytest.raises(RuntimeError,match="injected"):
            matrix.run_matrix(args)
        assert len(restarts)==3
    assert model_env.read_bytes()==original and restarts[-1]==original and sleeps==[True]
    record=json.loads(next(args.output.glob("*/matrix.json")).read_text())
    assert record["restored"]
    assert not list(args.output.glob("*/private/vllm-env.original"))


def test_failed_native_step_preserves_application_error_code():
    def request(method,path,*,step,**kwargs):
        if step=="plan":
            return {"status":"ready","message":"ready","turn_id":"t","plan":{"steps":[{"operation":"maximal-bicliques"}]}}
        if step=="create_workflow":
            return {"id":"w","status":"failed","steps":{"answer":{"error":{"code":"resource_limit","message":"Native candidate budget exceeded"}}}}
        raise AssertionError("Failed calculation must not request a result view")
    journey=Journey(request);journey.session_id="s";journey.inputs={"main":{}}
    with pytest.raises(JourneyError,match="Native candidate budget exceeded") as caught:
        journey.ask({"text":"question","expected_operations":["maximal-bicliques"]},{},spawn=Immediate)
    assert caught.value.code=="resource_limit" and caught.value.step=="calculation"


@pytest.mark.parametrize("kind,text",[("input","Use main."),("direction","Use an undirected copy for this analysis."),("sides","Use User vertices on the left and Business vertices on the right.")])
def test_canned_clarifications_resolve_the_specific_gap(kind,text):
    calls=[]
    def request(method,path,*,step,**kwargs):
        calls.append(kwargs["json"])
        if len(calls)==1:
            return {"status":"needs_information","message":"choose","pending_question":{"id":"gap","kind":kind}}
        assert kwargs["json"]["message"]==text and kwargs["json"]["clarification_id"]=="gap"
        return {"status":"answered","message":"done"}
    journey=Journey(request);journey.session_id="s";journey.inputs={"main":{}}
    journey.ask({"text":"question","clarification":"generic","sides_clarification":"Use User vertices on the left and Business vertices on the right.","expected_operations":[]},{},spawn=Immediate)
