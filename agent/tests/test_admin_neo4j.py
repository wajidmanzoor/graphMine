"""Real admin authorization/audit with fake service controls and read verification."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import secrets
import threading
import time
from types import SimpleNamespace
from dataclasses import replace

import pytest

from graphmine_agent.admin_neo4j import BackendSwitch
from graphmine_agent.datasets import DatasetLibrary
from graphmine_agent.errors import AnalyticsError
from graphmine_agent.neo4j_access import admission, session, switching
from graphmine_agent.neo4j_backend import active_backend_id, set_active_backend
from test_admin_console import console  # noqa: F401
from test_accounts import login


@pytest.fixture
def control(console, monkeypatch):
    client, accounts, admin, _ = console
    runtime, calls = client.app.state.runtime, []
    class Local:
        active = True
        fail_park = fail_restore = False
        def status(self):
            return {"rss_bytes": 1000 if self.active else 0, "units": [{"unit": "graphmine-neo4j-demo.service",
                "active": "active" if self.active else "inactive", "enabled": "enabled" if self.active else "disabled", "rss_bytes": 1000 if self.active else 0}]}
        def activate(self):
            calls.append("local.activate"); self.active = True
        def park(self):
            calls.append("local.park"); self.active = False
            if self.fail_park:
                raise RuntimeError("Failed park")
        def restore(self, before):
            calls.append("local.restore")
            if self.fail_restore:
                raise RuntimeError("Failed restore")
            self.active = before["units"][0]["active"] == "active"
    local = Local()
    @contextmanager
    def request():
        calls.append("remote.awake")
        yield
    monkeypatch.setattr("graphmine_agent.admin_neo4j.LocalNeo4j", lambda _: local)
    monkeypatch.setattr(runtime.remote_neo4j, "request", request)
    monkeypatch.setattr(runtime.remote_neo4j, "release", lambda: calls.append("remote.release"))
    monkeypatch.setattr(runtime.remote_neo4j, "status", lambda: {"vpn_reachable": True, "is_up": True,
        "started_by_graphmine": False, "last_used": None})
    monkeypatch.setattr(runtime.remote_neo4j, "ssh", lambda _: pytest.fail("Switch must not issue a remote stop"))
    monkeypatch.setattr(BackendSwitch, "_verify", lambda _, target: calls.append("verify." + target))
    monkeypatch.setattr(runtime.database_jobs, "_claim", lambda: None)
    return SimpleNamespace(client=client, accounts=accounts, admin=admin, runtime=runtime, calls=calls, local=local)


def post(p, target, force=False):
    return p.client.post("/api/admin/neo4j/switch", headers=p.admin, json={"target": target, "force": force})


def job(p, identifier="pending", *, status="queued", cancellable=True):
    value = {"id": identifier, "owner_id": "another-owner", "source_id": "demo", "kind": "query",
             "status": status, "cancellable": cancellable, "created_at": "2026-01-01", "updated_at": "2026-01-01",
             "result": None, "progress": {}, "error": None}
    with p.runtime.database._connect() as db:
        db.execute("INSERT INTO database_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)", (identifier, value["owner_id"], "demo", "query", status,
            json.dumps(value), None, "hash", 100, value["created_at"], value["updated_at"]))
    return value


def test_switch_both_ways_verifies_drains_releases_and_audits(control):
    p = control
    source = SimpleNamespace(id="demo", revision=1, _config_stamp=None)
    pool = SimpleNamespace(close=lambda: p.calls.append("pool.close"))
    with p.runtime.database_pools.lease(source, "neo4j-read", ["local"], lambda: pool):
        pass
    response = post(p, "iu-remote")
    assert response.status_code == 200, response.text
    assert response.json() == {"active_backend": "iu-remote", "changed": True}
    assert p.calls == ["remote.awake", "verify.iu-remote", "pool.close", "local.park"]
    assert not p.local.active and not p.runtime.database_pools._closed
    response = post(p, "local")
    assert response.status_code == 200, response.text
    assert p.calls[-3:] == ["local.activate", "verify.local", "remote.release"]
    assert p.local.active and active_backend_id(p.runtime.settings) == "local"
    with p.runtime.database._connect() as db:
        rows = db.execute('SELECT actor,"before","after" FROM admin_activity WHERE action=\'neo4j.switch\' ORDER BY rowid').fetchall()
    assert len(rows) == 2 and all(row[0] == "owner" for row in rows)
    assert json.loads(rows[0][1])["active_backend"] == "local"
    assert json.loads(rows[0][2])["result"] == "completed"
    events = p.client.get("/api/database-progress", headers=p.admin).json()["events"]
    assert [event["payload"]["phase"] for event in events if event["type"] == "database.switch"][-1] == "completed"


def test_pending_jobs_refuse_switch_and_force_cancels_other_owners(control):
    p = control
    job(p)
    response = post(p, "iu-remote")
    assert response.status_code == 409 and response.json()["error"]["code"] == "database_jobs_busy"
    assert not p.calls and active_backend_id(p.runtime.settings) == "local"
    assert post(p, "iu-remote", True).status_code == 200
    assert not BackendSwitch(p.runtime).jobs()
    with p.runtime.database._connect() as db:
        rows = db.execute('SELECT "after" FROM admin_activity WHERE action=\'neo4j.switch\' ORDER BY rowid').fetchall()
    assert [json.loads(row[0])["result"] for row in rows] == ["failed", "completed"]
    assert json.loads(rows[-1][0])["force"] is True


def test_force_waits_for_actual_cancellation_and_does_not_interrupt_commit(control, monkeypatch):
    p = control
    value = job(p, status="running")
    controller = BackendSwitch(p.runtime)
    controller.drain_seconds = .05
    with pytest.raises(AnalyticsError) as error:
        controller.switch("iu-remote", force=True)
    assert error.value.code == "database_jobs_busy" and not p.calls
    assert controller.jobs()[0]["status"] == "cancelling"
    p.runtime.database_jobs._change(value["id"], lambda row: row.update(status="cancelled"))
    job(p, identifier="committing", status="running", cancellable=False)
    with pytest.raises(AnalyticsError, match="not finished cancelling"):
        controller.switch("iu-remote", force=True)
    assert controller.jobs()[0]["status"] == "running" and not p.calls


@pytest.mark.parametrize("previous,target", [("local", "iu-remote"), ("iu-remote", "local")])
def test_target_failure_preserves_previous_selection_and_services(control, monkeypatch, previous, target, caplog):
    p = control
    set_active_backend(p.runtime.settings, previous)
    p.local.active = previous == "local"
    sensitive = secrets.token_urlsafe(32)
    def fail(*_):
        raise RuntimeError(sensitive)
    monkeypatch.setattr(BackendSwitch, "_verify", fail)
    response = post(p, target)
    assert response.status_code == 503
    assert active_backend_id(p.runtime.settings) == previous
    assert p.local.active == (previous == "local")
    assert sensitive not in response.text + caplog.text
    with p.runtime.database._connect() as db:
        log = db.execute('SELECT "after" FROM admin_activity WHERE action=\'neo4j.switch\'').fetchone()[0]
    assert sensitive not in log and json.loads(log)["result"] == "failed"


def test_failure_after_selection_rolls_back_and_reports_failed_recovery(control):
    p = control
    p.local.fail_park = True
    response = post(p, "iu-remote")
    assert response.status_code == 503 and active_backend_id(p.runtime.settings) == "local" and p.local.active
    assert p.calls[-2:] == ["local.restore", "remote.release"]
    p.local.fail_restore = True
    response = post(p, "iu-remote")
    assert response.status_code == 503 and response.json()["error"]["code"] == "database_rollback_incomplete"
    assert active_backend_id(p.runtime.settings) == "local"


def test_status_and_noop_never_wake_and_member_is_denied(control):
    p = control
    response = p.client.get("/api/admin/neo4j", headers=p.admin)
    assert response.status_code == 200, response.text
    assert response.json()["local"]["rss_bytes"] == 1000
    assert set(response.json()["record_counts"]) == {"local", "iu-remote"}
    assert post(p, "local").json()["changed"] is False and not p.calls
    member = login(p.client, "member")
    assert p.client.get("/api/admin/neo4j", headers=member).status_code == 403
    assert p.client.post("/api/admin/neo4j/switch", headers=member, json={"target": "iu-remote"}).status_code == 403
    assert not p.calls


def test_switch_blocks_new_admission_and_waits_for_live_sessions(control):
    p = control
    entered, release = threading.Event(), threading.Event()
    def live():
        with session(p.runtime.settings):
            entered.set()
            assert release.wait(3)
    with ThreadPoolExecutor(max_workers=2) as workers:
        operation = workers.submit(live)
        assert entered.wait(1)
        switch = workers.submit(BackendSwitch(p.runtime).switch, "iu-remote")
        deadline = time.monotonic() + 1
        while not switching(p.runtime.settings) and time.monotonic() < deadline:
            time.sleep(.01)
        try:
            assert switching(p.runtime.settings) and not p.calls
            with pytest.raises(AnalyticsError) as error:
                with session(p.runtime.settings):
                    pytest.fail("Admitted a new session during a switch")
            assert error.value.code == "database_switching"
            with pytest.raises(AnalyticsError):
                p.runtime.database_jobs.enqueue("query", "missing")
        finally:
            release.set()
        operation.result(2)
        assert switch.result(3)["active_backend"] == "iu-remote"


def test_another_switch_is_rejected_and_recorded(control):
    p = control
    with admission(p.runtime.settings, switching=True):
        response = post(p, "iu-remote")
    assert response.status_code == 409 and not p.calls
    with p.runtime.database._connect() as db:
        record = json.loads(db.execute('SELECT "after" FROM admin_activity WHERE action=\'neo4j.switch\'').fetchone()[0])
    assert record["error"] == "database_switching"


def test_switch_preserves_local_services_used_by_another_running_environment(control, tmp_path):
    from graphmine_agent.ownership import StoreLock
    p = control
    other = replace(p.runtime.settings, data_root=tmp_path / "other-environment")
    set_active_backend(other, "local")
    remote = p.runtime.remote_neo4j
    state = remote._load()
    state["stores"].append(str(other.database_path))
    remote._save(state)
    with StoreLock(other.database_path):
        response = post(p, "iu-remote")
        assert response.status_code == 409 and response.json()["error"]["code"] == "database_local_in_use"
        assert p.local.active and not p.calls
    assert post(p, "iu-remote").status_code == 200


def test_counts_classify_legacy_neo4j_provenance_and_exclude_uploads(control, triangle_graph):
    p = control
    library = DatasetLibrary(p.runtime)
    for source in ({"type": "database_query"}, {"type": "database_query", "backend_id": "iu-remote"}, {"type": "upload"}):
        library.store(json.loads(triangle_graph), name="Example", kind="graph", source=source, complete=True)
    with p.runtime.database._connect() as db:
        db.execute("CREATE TABLE query_library (id TEXT PRIMARY KEY)")
        db.executemany("INSERT INTO query_library VALUES (?)", [("first",), ("second",)])
    response = p.client.get("/api/admin/neo4j", headers=p.admin)
    assert response.status_code == 200, response.text
    counts = response.json()["record_counts"]
    assert counts["local"]["snapshots"] == counts["iu-remote"]["snapshots"] == 1
    assert counts["local"]["saved_queries"] == 2


def test_read_verification_uses_execute_read_and_none_auth(control, monkeypatch):
    p = control
    calls = []
    class Driver:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def session(self, **kwargs):
            assert kwargs["default_access_mode"] == "READ"
            return self
        def execute_read(self, read):
            assert read.timeout == 5
            return read(self)
        def run(self, query):
            assert query == "RETURN 1 AS connected"
            return SimpleNamespace(single=lambda **_: {"connected": 1})
    monkeypatch.setattr("neo4j.GraphDatabase.driver", lambda uri, **kwargs: calls.append((uri, kwargs)) or Driver())
    def address(_, host, port):
        assert (host, port) == ("10.2.147.169", 7689)
        return host
    monkeypatch.setattr("graphmine_agent.database_connections.network_address", address)
    # Fixture replaces the class method; call the unpatched module implementation below.
    from graphmine_agent.admin_neo4j import BackendSwitch as Controller
    verifier = _read_verify
    verifier(Controller(p.runtime), "iu-remote")
    assert calls[0][0] == "bolt://10.2.147.169:7689" and calls[0][1]["auth"] is None


_read_verify = BackendSwitch._verify
