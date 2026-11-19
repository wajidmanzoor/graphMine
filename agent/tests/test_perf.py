import asyncio
from dataclasses import replace
import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from graphmine_agent import perf
from graphmine_agent.accounts import model_post, model_stream
from graphmine_agent.api import create_app
from graphmine_agent.config import Settings
from test_accounts import login, PASSWORD


def rows(directory):
    return [json.loads(line) for p in directory.glob("events-*.jsonl") for line in p.read_text().splitlines()]


def test_off_has_no_files_headers_or_payload_change(settings,tmp_path):
    settings = replace(settings,perf_log=False,perf_directory=tmp_path/"perf")
    payload = {"reasoning_effort":"medium","thinking_token_budget":200,"chat_template_kwargs":{"x":1}}
    expected = json.loads(json.dumps(payload))
    perf.thinking(settings,"route",payload)
    assert payload == expected
    with perf.scope(settings,request_id="off"):
        for event in perf.FIELDS:
            perf.emit(event)
        with perf.model_scope("route"), perf.transport(payload) as observation:
            assert observation is None
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/build",headers={"X-Request-ID":"ignored"})
        assert response.status_code == 200
        assert "X-Request-ID" not in response.headers
    assert not settings.perf_directory.exists()


def test_all_events_have_required_fields_and_ids(settings,tmp_path):
    settings = replace(settings,perf_log=True,perf_directory=tmp_path/"perf")
    identifiers = {name:name+"-value" for name in perf.IDS}
    with perf.scope(settings,**identifiers):
        for event in perf.FIELDS:
            perf.emit(event)
    result = rows(settings.perf_directory)
    assert len(result) == len(perf.FIELDS)
    for row in result:
        assert set(perf.FIELDS[row["event"]].split()) <= row.keys()
        assert {k:row[k] for k in perf.IDS} == identifiers
        assert row["ts"].endswith("+00:00")
    assert next(settings.perf_directory.glob("*.jsonl")).stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_transport_retry_usage_ttft_and_turn_isolation(settings,tmp_path):
    settings = replace(settings,perf_log=True,perf_directory=tmp_path/"perf")
    def reply(request):
        if request.url.path == "/stream":
            body = 'data: {"choices":[{"delta":{"reasoning":"think"}}]}\n\n'
            body += 'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'
            body += 'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5,"completion_tokens_details":{"reasoning_tokens":3}}}\n\ndata: [DONE]\n\n'
            return httpx.Response(200,text=body,headers={"content-type":"text/event-stream"})
        return httpx.Response(200,json={"choices":[],"usage":{"prompt_tokens":8,"completion_tokens":4}})
    class Planner:
        def __init__(self):
            self.settings = settings
        @perf.turn
        async def plan(self,session_id,body):
            with perf.model_scope("route"):
                async with httpx.AsyncClient(base_url="http://test",transport=httpx.MockTransport(reply)) as client:
                    await model_post(client,"/post",json={"model":"planner"})
                    perf.validation_failed()
                    async def reasoning(_):
                        pass
                    await model_stream(client,"/stream",json={"model":"planner"},on_reasoning=reasoning)
            return {"status":"options","options":[{"id":"one"}]}
    async def one(identifier):
        with perf.scope(settings,request_id="request-"+identifier,user_id="user-"+identifier):
            await Planner().plan("session-"+identifier,SimpleNamespace(request_id=identifier,mode="normal"))
    await asyncio.gather(one("a"),one("b"))
    result = rows(settings.perf_directory)
    for identifier in ("a","b"):
        selected = [r for r in result if r["turn_id"] == identifier]
        assert all(r["request_id"] == "request-"+identifier and r["user_id"] == "user-"+identifier for r in selected)
        calls = [r for r in selected if r["event"] == "model_call"]
        assert len(calls) == 2 and [r["retries"] for r in calls] == [0,1]
        assert calls[0]["validation_failed"] and calls[0]["time_to_first_token_ms"] is None
        assert calls[1]["time_to_first_token_ms"] >= 0 and calls[1]["reasoning_tokens"] == 3
        assert calls[1]["stage"] == "route" and calls[1]["model"] == "planner"
        assert next(r for r in selected if r["event"] == "turn_end")["outcome"] == "choice_offered"


def test_http_correlation_admin_snapshot_and_raw_request_bytes(settings,tmp_path):
    settings = replace(settings,perf_log=True,perf_directory=tmp_path/"perf",accounts_enabled=True,account_cookie_secure=False)
    app = create_app(settings)
    from fastapi import Request
    @app.post("/api/perf-test/{identifier}")
    async def observe(identifier:str,request:Request):
        await request.body()
        return {"received":request.scope["perf_context"]["request_bytes"]}
    app.router.routes.insert(0,app.router.routes.pop())
    with TestClient(app) as client:
        runtime = client.app.state.runtime
        runtime.accounts.create_user("admin",PASSWORD,admin=True)
        runtime.accounts.create_user("member",PASSWORD)
        assert client.get("/api/admin/perf/snapshot").status_code == 401
        member = login(client,"member")
        assert client.get("/api/admin/perf/snapshot",headers=member).status_code == 403
        admin = login(client,"admin")
        response = client.get("/api/admin/perf/snapshot",headers={**admin,"X-Request-ID":"snapshot-id"})
        assert response.status_code == 200, response.text
        assert response.headers["X-Request-ID"] == "snapshot-id"
        assert response.json()["model"] == {"waiting":0,"running":0}
        response = client.post("/api/perf-test/private-name",content=b'{ "a" : 1 }',headers={**admin,"Content-Type":"application/json"})
        assert response.json() == {"received":11}
    result = rows(settings.perf_directory)
    event = next(r for r in result if r["event"] == "http" and r["request_id"] == "snapshot-id")
    assert event["user_id"] and event["route"] == "/api/admin/perf/snapshot"
    assert any(r.get("route") == "/api/perf-test/{identifier}" for r in result)
    assert "private-name" not in json.dumps(result)
    assert any(r["event"] == "http" and r.get("route") == "/api/auth/login" and r["user_id"] for r in result)


def test_sqlite_lock_wait_and_cursor_are_observed_without_sql(settings,tmp_path):
    settings = replace(settings,perf_log=True,perf_directory=tmp_path/"perf")
    path = tmp_path/"locked.sqlite"
    first = sqlite3.connect(path,check_same_thread=False)
    first.execute("CREATE TABLE secrets(value)")
    first.execute("BEGIN IMMEDIATE")
    release = threading.Timer(.12,first.commit)
    release.start()
    with perf.scope(settings,request_id="locked"):
        with perf.connect(path,timeout=2) as second:
            second.cursor().execute("BEGIN IMMEDIATE")
            second.execute("INSERT INTO secrets VALUES ('private')")
    release.join(); first.close(); second.close()
    result = rows(settings.perf_directory)
    assert len(result) == 1
    assert result[0]["operation"] == "BEGIN" and result[0]["lock_wait_ms"] >= 50
    assert "private" not in json.dumps(result) and "secrets" not in json.dumps(result)


def test_settings_defaults_and_explicit_thinking_override(settings,monkeypatch):
    assert settings.model_queue_seconds == 60 and settings.llm_thinking_stages is None
    with pytest.raises(ValueError):
        replace(settings,model_queue_seconds=float("nan"))
    with pytest.raises(ValueError):
        replace(settings,llm_thinking_stages=("typo",))
    changed = replace(settings,llm_thinking_stages=("analyst",))
    route = {"reasoning_effort":"medium","thinking_token_budget":200}
    perf.thinking(changed,"route",route)
    assert route == {"reasoning_effort":"none","chat_template_kwargs":{"enable_thinking":False}}
    analyst = {"reasoning_effort":"medium"}
    perf.thinking(changed,"analyst",analyst)
    assert analyst == {"reasoning_effort":"medium"}
