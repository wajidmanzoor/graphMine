"""User actions wake IU; discovery and health checks never do (no live I/O)."""

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from graphmine_agent.api import create_app
from graphmine_agent.database_job_context import current_database_job
from graphmine_agent.database_jobs import JobControl
from graphmine_agent.database_progress import publish, topic
from graphmine_agent.identity import Principal, identity_scope
from graphmine_agent.jobs import EventBus
from graphmine_agent.remote_neo4j import WAKE_MESSAGE, get_remote
from test_iu_neo4j_connections import iu_settings  # noqa: F401


@pytest.fixture
def remote_app(iu_settings, monkeypatch):
    class Result:
        def consume(self):
            return SimpleNamespace(query_type="r")
    class Session:
        def execute_read(self, work):
            return work(self)
        def run(self, *_):
            return Result()
    class Driver:
        @contextmanager
        def session(self, **_):
            yield Session()
        def close(self):
            pass
    monkeypatch.setattr("neo4j.GraphDatabase.driver", lambda *_, **__: Driver())
    settings = replace(iu_settings, accounts_enabled=False)
    power = get_remote(settings)
    app = create_app(settings)
    monkeypatch.setattr(power, "ssh", lambda *_: pytest.fail("No real SSH"))
    monkeypatch.setattr(power, "tcp", lambda *_: False)
    monkeypatch.setattr(power, "reachable", lambda: True)
    yield app, power


def test_startup_metadata_capabilities_and_health_never_wake(remote_app, monkeypatch):
    app, power = remote_app
    monkeypatch.setattr(power, "ensure_awake", lambda: pytest.fail("Passive request woke the database"))
    with TestClient(app, headers={"Authorization": "Bearer test-secret"}) as client:
        for path in ("/", "/api/database-sources", "/api/database-sources/iu-remote/settings",
                     "/api/database-sources/iu-remote/datasets", "/api/capabilities"):
            response = client.get(path)
            assert response.status_code == 200, (path, response.text)
        assert client.post("/api/database-sources/iu-remote/status").status_code == 200
        assert power._load()["last_used"] is None
        assert power._load()["leases"] == {}
        assert power._task is None


def test_explicit_open_tracks_activity_and_publishes_progress(remote_app, monkeypatch):
    app, power = remote_app
    calls = []
    def awake():
        assert len(power._load()["leases"]) == 1
        calls.append(1)
        power._emit("waking", WAKE_MESSAGE)
    monkeypatch.setattr(power, "ensure_awake", awake)
    with TestClient(app, headers={"Authorization": "Bearer test-secret"}) as client:
        response = client.post("/api/database-sources/iu-remote/open")
        assert response.status_code == 200, response.text
        assert response.json()["query_available"]
        events = client.get("/api/database-progress").json()["events"]
        assert events[-1]["payload"]["message"] == WAKE_MESSAGE
        assert calls == [1] and power._load()["last_used"] is not None
        assert power._load()["leases"] == {}
    assert power._task is None and power.publish is None


def test_open_offline_with_flag_off_returns_clear_error_without_ssh(remote_app):
    app, power = remote_app
    with TestClient(app, headers={"Authorization": "Bearer test-secret"}) as client:
        response = client.post("/api/database-sources/iu-remote/open")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "database_autowake_disabled"
        assert power._load()["leases"] == {}


def test_progress_is_owner_scoped_persistent_and_bounded(database):
    runtime = SimpleNamespace(events=EventBus(database))
    owner = Principal("first", "first", None)
    with identity_scope(owner):
        for i in range(105):
            publish(runtime, {"message": WAKE_MESSAGE, "index": i})
        # A different worker sees the same retained progress.
        recovered = EventBus(database).notifications(topic())
        assert len(recovered["events"]) == 100 and recovered["after"] == 105
        assert recovered["events"][0]["payload"]["index"] == 5
        assert runtime.events.notifications(topic(), 105)["events"] == []
    with identity_scope(Principal("second", "second", None)):
        assert runtime.events.notifications(topic())["events"] == []
    assert runtime.events.notifications(topic())["events"] == []


def test_wake_progress_reaches_durable_job_control(settings):
    job = {"id": "test-job", "status": "running"}
    control = JobControl(SimpleNamespace(_change=lambda _, update: update(job)), job)
    token = current_database_job.set(control)
    try:
        get_remote(settings)._emit("waking", WAKE_MESSAGE)
    finally:
        current_database_job.reset(token)
    assert job["progress"]["message"] == WAKE_MESSAGE
    assert job["progress"]["stage"] == "waking"
