"""Real native HTTP attempts against controlled loopback providers."""

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from semantic_provider_fixture import provider
from test_accounts import account_settings, store, PASSWORD  # noqa: F401
from test_database_workspace import source, workspace  # noqa: F401
from test_semantic_native import native_engine  # noqa: F401
from test_semantic_queries import submit
from test_database_jobs import wait_job




SCRIPT = '''
import json,sys
from graphmine_agent.semantic_engine import load_engine
engine=load_engine().module
db=engine.Database(buffer_pool_size=128*1024*1024,max_num_threads=2,backend='pybind')
c=engine.Connection(db,num_threads=2)
def run(q):
    r=c.execute(q)
    try:
        rows=[]
        while r.has_next(): rows.append(r.get_next())
        return dict(columns=r.get_column_names(),rows=rows)
    finally: r.close()
args=json.loads(sys.argv[1]); out={}
try:
    for name,value in {'llm_base_url':json.dumps(args['url']), 'llm_threads':'1', 'llm_batch_size':'1',
        'llm_max_calls':'1000000000','llm_answer_max_age':str(args.get('max_age',0)),'llm_persistent_cache':'true','semantic_selectivity_samples':'0',
        'semantic_path_decomposition':'false','semantic_join_decomposition':'false'}.items():run('CALL '+name+'='+value)
    run("CREATE MACRO qwen() AS {model:'fixture-model',temperature:0}")
    try:
        for q in args['query'] if isinstance(args['query'],list) else [args['query']]:out['result']=run(q)
    except Exception as e:out['error']=str(e)
    out['usage']=run('CALL llm_usage() RETURN *')
finally:c.close();db.close()
print(json.dumps(out))
'''


def native(url, query, *, cache=None, limit=10, reuse=True, admission=None, started=False, max_age=0):
    env = {key: value for key, value in os.environ.items() if not key.startswith(('GRAPHMINE_TENTO_', 'OPENROUTER_', 'LLM_API_'))}
    env.update(GRAPHMINE_TENTO_STRICT="1", GRAPHMINE_TENTO_REQUEST_LIMIT=str(limit),
               LLM_API_KEY="synthetic-native-key", GRAPHMINE_TENTO_REUSE="1" if reuse else "0")
    if cache:
        env['GRAPHMINE_TENTO_ANSWER_STORE'] = str(cache)
    if admission:
        env["GRAPHMINE_TENTO_ADMISSION"] = admission
    if started:
        return subprocess.Popen([sys.executable, "-c", SCRIPT, json.dumps({"url": url, "query": query})],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    child = subprocess.run([sys.executable, '-c', SCRIPT, json.dumps({'url': url, 'query': query, 'max_age': max_age})],
                           env=env, capture_output=True, text=True, timeout=20)
    assert child.returncode == 0, child.stderr
    value = json.loads(child.stdout)
    value['usage'] = dict(zip(value['usage']['columns'], value['usage']['rows'][0]))
    return value


QUERY = "UNWIND ['one','two'] AS text RETURN llm('qwen','Classify {{text}} {answer STRING}')"


def test_native_live_controls_and_fresh_process_answer_reuse(native_engine, tmp_path):
    with provider() as (url, calls):
        cache = tmp_path / 'answers'
        first = native(url, QUERY, cache=cache)
        assert 'error' not in first and first['usage']['http_requests'] == 2
        assert first['usage']['completed_rows'] == 2
        assert cache.stat().st_mode & 0o777 == 0o600
        for call in calls:
            assert call['body']['chat_template_kwargs'] == {'enable_thinking': False}
            assert call['body']['response_format']['json_schema']['strict'] is True
            assert call['authorization'] == 'Bearer synthetic-native-key'
        second = native(url, QUERY, cache=cache)
        assert second['result'] == first['result'] and second['usage']['stored_hits'] == 2
        assert second['usage']['http_requests'] == 0 and len(calls) == 2
        native(url, QUERY, cache=cache, reuse=False)
        assert len(calls) == 4
        native(url, QUERY.replace("'two'", "'changed'"), cache=cache)
        assert len(calls) == 5


@pytest.mark.parametrize('status,query,error', [
    (400, QUERY, 'graphmine_schema_rejected'),
    (503, QUERY, 'graphmine_request_limit'),
    (200, "RETURN llm('qwen','First {answer STRING}'), llm('qwen','Second {answer STRING}')", 'graphmine_request_limit'),
])
def test_native_total_budget_and_schema_rejection_do_not_retry_unconstrained(native_engine, status, query, error):
    with provider(status) as (url, calls):
        value = native(url, query, limit=1)
        assert error in value['error']
        assert len(calls) == value['usage']['http_requests'] == 1
        assert 'response_format' in calls[0]['body']


def test_completed_batch_survives_later_budget_failure(native_engine, tmp_path):
    with provider() as (url, calls):
        cache = tmp_path / 'answers'
        stopped = native(url, QUERY, limit=1, cache=cache)
        assert 'graphmine_request_limit' in stopped['error'] and len(calls) == 1
        retry = native(url, QUERY, limit=1, cache=cache)
        assert 'error' not in retry
        assert retry['usage']['stored_hits'] == 1 and len(calls) == 2


def test_live_job_uses_parent_admission_retains_answers_and_records_real_provenance(workspace, native_engine):
    from graphmine_agent import admin_settings
    from graphmine_agent.query_previews import QueryPreviews
    with provider() as (url, calls):
        runtime = workspace.runtime
        runtime.settings = replace(runtime.settings, semantic_mode='live', semantic_cache_enabled=True,
                                   llm_base_url=url, llm_model='fixture-model', llm_api_key='synthetic-job-key')
        base = workspace.snapshot['dataset']['id']
        previews = QueryPreviews(runtime)
        original = previews.get(base, content=True)
        statement = "MATCH(n:Vertex) WHERE llm('qwen','Select {{n.name}} {keep BOOLEAN}') RETURN n"
        first = submit(workspace, statement=statement, model='qwen', call_limit=5, reuse_answers=True)
        wait_job(workspace.client, first['id'])
        result = workspace.client.get(f"/api/database-jobs/{first['id']}/result").json()
        saved = result['dataset']['source']
        assert saved['model_dependent_input'] and not saved['simulation']
        assert saved['settings']['query_wide_call_limit_supported']
        assert saved['settings']['thinking'] == 'off' and saved['settings']['strict_json']
        assert saved['usage']['http_requests'] == 1 and len(calls) == 1
        assert calls[0]['authorization'] == 'Bearer synthetic-job-key'
        assert 'synthetic-job-key' not in json.dumps(result)
        assert saved['settings']['answers_retained'] == 2
        retry = submit(workspace, key='live-reuse', statement=statement, model='qwen', reuse_answers=True)
        wait_job(workspace.client, retry['id'])
        reused = workspace.client.get(f"/api/database-jobs/{retry['id']}/result").json()
        assert reused['usage']['stored_hits'] == 2 and len(calls) == 1
        assert previews.get(base, content=True) == original


def test_completed_answers_survive_hard_process_cancellation(native_engine, tmp_path):
    blocked, release = threading.Event(), threading.Event()
    def response(number):
        if number == 2:
            blocked.set()
            release.wait(10)
        return 200
    with provider(response) as (url, calls):
        cache = tmp_path / 'answers'
        process = native(url, QUERY, cache=cache, started=True)
        try:
            assert blocked.wait(10)
            process.kill()
            process.communicate(timeout=5)
        finally:
            if process.poll() is None:
                process.kill(); process.communicate(timeout=5)
            release.set()
        retry = native(url, QUERY, cache=cache)
        assert 'error' not in retry and retry['usage']['stored_hits'] == 1
        assert retry['usage']['http_requests'] == 1 and len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('limit,expected', [(10000, 240), (1000, 0)])
async def test_native_admission_uses_real_account_token_reservations(native_engine, account_settings, tmp_path, limit, expected):
    from types import SimpleNamespace
    from graphmine_agent.identity import Principal, identity_scope
    from graphmine_agent.semantic_admission import Admission
    configured = replace(account_settings, account_daily_tokens=limit, server_daily_tokens=limit)
    accounts, database = store(configured)
    accounts.create_user('alice', PASSWORD)
    with provider() as (url, calls):
        runtime = SimpleNamespace(settings=configured, llm_power=None)
        gate = Admission(runtime, {'base_url': url}, ['fixture-model'], 'synthetic-native-key')
        path = str(tmp_path / 'admission.sock')
        with identity_scope(Principal('alice', 'alice', accounts)):
            await gate.start(path)
            try:
                result = await asyncio.to_thread(native, url, QUERY, admission=path)
            finally:
                await gate.close()
        assert accounts.usage('alice')['tokens_used'] == expected
        if expected:
            assert 'error' not in result and gate.error is None
            assert len(calls) == 2 and gate.usage['http_requests'] == 2
        else:
            assert 'graphmine_admission_denied' in result['error']
            assert not calls and gate.error.code == 'daily_tokens_limit'


def test_answer_cache_is_account_scoped_and_clear_waits_for_workers(workspace):
    from graphmine_agent.identity import Principal, identity_scope
    from graphmine_agent.semantic_cache import lease, clear
    from graphmine_agent.errors import AnalyticsError
    paths = []
    for user in ('alice','bob'):
        with identity_scope(Principal(user, user, workspace.runtime.accounts)):
            with lease(workspace.runtime) as path:
                paths.append(path)
                assert path.parent.stat().st_mode & 0o777 == 0o700
                with pytest.raises(AnalyticsError, match='in use'):
                    clear(workspace.runtime)
    assert paths[0] != paths[1]
    assert clear(workspace.runtime) == {'cleared_answers': 0}


def test_blank_local_model_key_matches_the_vllm_launcher(settings, monkeypatch):
    from graphmine_agent.config import Settings
    monkeypatch.setenv('GRAPHMINE_LLM_API_KEY', '')
    assert Settings.from_env(settings.repository_root).llm_api_key == 'local-graphmine'


def test_usage_observation_cannot_reset_total_request_budget(native_engine):
    with provider() as (url, calls):
        value = native(url, ["RETURN llm('qwen','First {answer STRING}')",
                            'CALL llm_usage() RETURN *',
                            "RETURN llm('qwen','Second {answer STRING}')"], limit=1)
        assert 'graphmine_request_limit' in value['error']
        assert len(calls) == 1 and value['usage']['http_requests'] == 0


def test_expired_answers_and_changed_prompt_miss_durable_cache(native_engine, tmp_path):
    with provider() as (url, calls):
        cache = tmp_path / 'answers'
        native(url, QUERY, cache=cache)
        rows = []
        for line in cache.read_text().splitlines():
            parts = line.split('\t', 3)
            if len(parts) == 4 and len(parts[0]) == 32 and parts[1].isdigit():
                parts[1] = '0'
            rows.append('\t'.join(parts))
        cache.write_text('\n'.join(rows)+'\n')
        expired = native(url, QUERY, cache=cache, max_age=86400)
        assert expired['usage']['stored_hits'] == 0 and len(calls) == 4
        changed = native(url, QUERY.replace('Classify','Describe'), cache=cache)
        assert changed['usage']['stored_hits'] == 0 and len(calls) == 6


def test_parent_settlement_failure_never_publishes_native_result(workspace, native_engine):
    with provider(usage='invalid provider usage') as (url, calls):
        workspace.runtime.settings = replace(workspace.runtime.settings, semantic_mode='live',
                                             llm_base_url=url, llm_model='fixture-model')
        job = submit(workspace, model='qwen', statement="RETURN llm('qwen','Classify {answer STRING}') AS answer")
        failed = wait_job(workspace.client, job['id'], 'failed')
        assert failed['error']['code'] == 'semantic_admission' and len(calls) == 1
        assert workspace.client.get(f"/api/database-jobs/{job['id']}/result").status_code == 409
