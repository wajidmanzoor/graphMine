"""Resource lifetimes, bounds, credentials and identity across concurrent work."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.api import create_app
from graphmine_agent.database_connections import delete_pair, save_pair
from graphmine_agent.database_job_context import current_database_job
from graphmine_agent.database_jobs import WorkStopped
from graphmine_agent.database_pools import DatabasePools, current_database_pools, pool_scope
from graphmine_agent.database_sources import DatabaseSource, configured, get_source, neo4j_session, sql_connection
from graphmine_agent.identity import current_principal, identity_scope
from test_database_connections import pair  # noqa: F401


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setenv("POOL_READER", "reader-secret")
    monkeypatch.setenv("POOL_WRITER", "writer-secret")
    return DatabaseSource(id="source", name="Research", users=["*"], sql_dsn_env="POOL_SQL",
                          neo4j_uri="bolt://graph.example", neo4j_username="reader", neo4j_password_env="POOL_READER",
                          neo4j_writer_username="writer", neo4j_writer_password_env="POOL_WRITER")


@pytest.fixture
def pools(settings):
    value = DatabasePools(replace(settings, database_pool_limit=3, database_pool_size=2))
    with pool_scope(value):
        yield value
    value.close()


@pytest.fixture
def drivers(monkeypatch):
    import neo4j
    made = []

    class Driver:
        def __init__(self, uri, **options):
            self.uri, self.options = uri, options
            self.closed = False
            self.sessions = []
            made.append(self)

        @contextmanager
        def session(self, **options):
            assert not self.closed
            session = SimpleNamespace(options=options, closed=False, driver=self)
            self.sessions.append(session)
            try:
                yield session
            finally:
                session.closed = True

        def close(self):
            assert all(session.closed for session in self.sessions)
            self.closed = True

    monkeypatch.setattr(neo4j.GraphDatabase, "driver", Driver)
    return made


def test_reuse_keeps_sessions_and_reader_writer_credentials_separate(source, pools, drivers):
    with neo4j_session(source) as first:
        assert not first.closed
    with neo4j_session(source) as second:
        assert first.closed and first is not second and first.driver is second.driver
    with neo4j_session(source, write=True) as writer:
        assert writer.driver is not first.driver
        assert writer.options["default_access_mode"] == "WRITE"
    assert first.options == {"database": "neo4j", "default_access_mode": "READ"}
    assert [d.options["auth"] for d in drivers] == [("reader", "reader-secret"), ("writer", "writer-secret")]
    assert all(d.options["max_connection_pool_size"] == 2 for d in drivers)
    assert all(not d.closed for d in drivers)
    assert "secret" not in repr(pools._entries)
    pools.close()
    assert all(d.closed for d in drivers)


@pytest.mark.parametrize("change", ["password", "revision", "database", "uri"])
def test_changes_replace_idle_resources(source, pools, drivers, monkeypatch, change):
    with neo4j_session(source):
        pass
    if change == "password":
        monkeypatch.setenv("POOL_READER", "new-secret")
    else:
        field, value = {"revision": ("revision", 2), "database": ("neo4j_database", "other"), "uri": ("neo4j_uri", "bolt://other.example")}[change]
        source = source.model_copy(update={field: value})
    with neo4j_session(source):
        assert drivers[0].closed
    assert len(drivers) == 2


def test_rotation_drains_active_sessions_and_does_not_exceed_global_limit(source, pools, drivers, monkeypatch):
    pools.limit = 1
    with neo4j_session(source) as first:
        monkeypatch.setenv("POOL_READER", "rotated")
        with pytest.raises(AnalyticsError) as error:
            with neo4j_session(source):
                pytest.fail("Exceeded the resource cap")
        assert error.value.code == "database_busy"
        assert not first.driver.closed
    assert first.driver.closed
    with neo4j_session(source):
        pass
    assert len(drivers) == 2


def test_owner_isolation_and_lru_eviction(source, pools, drivers):
    pools.limit = 2
    for user in ("alice", "bob", "alice", "carol"):
        with identity_scope(SimpleNamespace(user_id=user, username=user)), neo4j_session(source):
            pass
    assert len(drivers) == 3
    assert not drivers[0].closed and drivers[1].closed and not drivers[2].closed


def test_expired_idle_resources_are_reaped(source, pools, drivers, monkeypatch):
    with neo4j_session(source):
        pass
    now = __import__("time").monotonic()
    monkeypatch.setattr("graphmine_agent.database_pools.time.monotonic", lambda: now + pools.idle_seconds + 1)
    pools.reap()
    assert drivers[0].closed and not pools._entries


@pytest.mark.parametrize("ending", ["release", "cancel", "shutdown"])
def test_waiting_borrow_is_bounded_cancellable_and_wakes_on_shutdown(source, pools, drivers, ending):
    pools.size = 1
    waiting, cancel = threading.Event(), threading.Event()

    def checkpoint(*args):
        waiting.set()
        if cancel.is_set():
            raise WorkStopped()

    def borrower():
        token = current_database_job.set(SimpleNamespace(checkpoint=checkpoint))
        try:
            with pool_scope(pools), neo4j_session(source) as session:
                return session.driver
        finally:
            current_database_job.reset(token)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with neo4j_session(source) as first:
            future = executor.submit(borrower)
            assert waiting.wait(2)
            if ending == "cancel":
                cancel.set()
                with pytest.raises(WorkStopped):
                    future.result(timeout=2)
            elif ending == "shutdown":
                pools.close()
                with pytest.raises(AnalyticsError):
                    future.result(timeout=2)
            assert not first.driver.closed
        if ending == "release":
            assert future.result(timeout=2) is first.driver
    assert len(drivers) == 1


def test_wait_timeout_and_factory_failure_leave_capacity_recoverable(source, pools, drivers):
    pools.size = 1; pools.wait_seconds = .02
    with neo4j_session(source):
        with pytest.raises(AnalyticsError, match="Timed out"):
            with neo4j_session(source):
                pass
    def broken():
        raise ValueError("Bad driver configuration")
    with pytest.raises(ValueError):
        with pools.lease(source, "broken", [], broken):
            pass
    with neo4j_session(source):
        pass
    assert len(drivers) == 1


def test_wait_queue_has_a_finite_limit(source, pools, drivers):
    pools.size = 1
    ready = threading.Event()
    calls = 0
    def checkpoint(*_):
        nonlocal calls
        calls += 1
        if calls >= 3:
            ready.set()
    def wait():
        token = current_database_job.set(SimpleNamespace(checkpoint=checkpoint))
        try:
            with pool_scope(pools), neo4j_session(source):
                pass
        finally:
            current_database_job.reset(token)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with neo4j_session(source):
            future = executor.submit(wait)
            assert ready.wait(2)
            with pytest.raises(AnalyticsError, match="queue is full"):
                with neo4j_session(source):
                    pass
        future.result(timeout=2)
    assert len(drivers) == 1


def test_closing_resources_keep_their_budget_slot(source, pools, drivers):
    pools.limit = 1
    with neo4j_session(source):
        pass
    closing, release, borrowing = threading.Event(), threading.Event(), threading.Event()
    original = drivers[0].close
    def close():
        closing.set()
        assert release.wait(3)
        original()
    drivers[0].close = close
    def borrow():
        def checkpoint(*_):
            borrowing.set()
        token = current_database_job.set(SimpleNamespace(checkpoint=checkpoint))
        try:
            with pool_scope(pools), neo4j_session(source):
                assert drivers[0].closed
        finally:
            current_database_job.reset(token)
    with ThreadPoolExecutor(max_workers=2) as executor:
        retired = executor.submit(pools.invalidate, source.id)
        assert closing.wait(2)
        waiting = executor.submit(borrow)
        try:
            assert borrowing.wait(2)
            assert len(drivers) == 1 and not waiting.done()
        finally:
            release.set()
        retired.result(timeout=3); waiting.result(timeout=3)
    assert len(drivers) == 2


def test_standalone_calls_close_resources_immediately(source, drivers):
    with neo4j_session(source):
        pass
    assert drivers[0].closed
    assert current_database_pools.get() is None


def test_managed_resolver_keeps_owner_and_rechecks_policy(source, pools, drivers, settings, monkeypatch):
    source._network_settings = settings
    calls = []
    def address(settings, host, port):
        calls.append((current_principal.get().user_id, host, port))
        if host == "forbidden.internal":
            raise AnalyticsError("Private database address blocked")
        return "203.0.113.1"
    monkeypatch.setattr("graphmine_agent.database_connections.network_address", address)
    with identity_scope(SimpleNamespace(user_id="alice", username="alice")):
        with neo4j_session(source):
            pass
        with neo4j_session(source):
            pass
    with ThreadPoolExecutor(max_workers=1) as executor:
        resolver = drivers[0].options["resolver"]
        assert executor.submit(resolver, SimpleNamespace(host="cluster.example", port=7687)).result() == [("203.0.113.1", 7687)]
        with pytest.raises(AnalyticsError):
            executor.submit(resolver, SimpleNamespace(host="forbidden.internal", port=7687)).result()
    assert calls == [("alice", "graph.example", 7687)] * 2 + [("alice", "cluster.example", 7687), ("alice", "forbidden.internal", 7687)]


def test_managed_postgres_rechecks_and_pins_dns_before_reuse(source, pools, settings, monkeypatch):
    import psycopg_pool
    address = "203.0.113.1"
    calls, made = [], []
    def resolve(settings, host, port):
        calls.append((host, port))
        return address
    monkeypatch.setattr("graphmine_agent.database_connections.network_address", resolve)
    source._network_settings = settings
    source._sql_credentials = dict(host="database.example", port=5432, database="research", username="reader", password="private", sslmode="verify-full")
    class Connection:
        def execute(self, *args):
            pass
        def rollback(self):
            pass
    class Pool:
        check_connection = staticmethod(lambda _: None)
        def __init__(self, **options):
            self.options, self.closed = options, False
            self.db = Connection(); made.append(self)
        def getconn(self, **options):
            return self.db
        def putconn(self, db):
            pass
        def close(self):
            self.closed = True
    monkeypatch.setattr(psycopg_pool, "ConnectionPool", Pool)
    for _ in range(2):
        with sql_connection(source):
            pass
    assert len(made) == 1
    assert made[0].options["kwargs"]["host"] == "database.example"
    assert made[0].options["kwargs"]["hostaddr"] == "203.0.113.1"
    address = "203.0.113.2"
    with sql_connection(source):
        pass
    assert made[0].closed and made[1].options["kwargs"]["hostaddr"] == address
    assert calls == [("database.example", 5432)] * 3


def test_source_file_edits_and_deletions_fence_stale_handles(source, pools, drivers, settings, tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps([source.model_dump()])); path.chmod(0o600)
    settings = replace(settings, database_sources_file=path)
    stale = configured(settings)[0]
    with neo4j_session(stale):
        pass
    replacement = tmp_path / "replacement"
    replacement.write_text(json.dumps([source.model_copy(update={"revision": 2}).model_dump()])); replacement.chmod(0o600)
    replacement.replace(path)
    with pytest.raises(AnalyticsError, match="changed"):
        with neo4j_session(stale):
            pass
    fresh = configured(settings)[0]
    with neo4j_session(fresh):
        assert drivers[0].closed
    path.unlink()
    with pytest.raises(AnalyticsError, match="changed"):
        with neo4j_session(fresh):
            pass


def test_only_successful_saved_edits_retire_pools(settings, pair, pools, drivers, monkeypatch):
    monkeypatch.setattr("graphmine_agent.database_connections.network_address", lambda *args: "203.0.113.1")
    healthy = True
    def health(source):
        assert current_database_pools.get() is None
        return {"connected": healthy, "sql": {"connected": healthy}, "neo4j": {"connected": healthy}}
    monkeypatch.setattr("graphmine_agent.database_connections.check_connection", health)
    result = save_pair(settings, pair)
    source = get_source(settings, result["id"])
    with neo4j_session(source):
        pass
    healthy = False
    with pytest.raises(AnalyticsError):
        save_pair(settings, pair.model_copy(update={"neo4j_password": SecretStr("invalid")}), source.id)
    assert not drivers[0].closed
    healthy = True
    changed = save_pair(settings, pair.model_copy(update={"neo4j_password": SecretStr("valid-rotation")}), source.id)
    assert changed["mapping_hash"] == result["mapping_hash"]
    assert drivers[0].closed
    with neo4j_session(get_source(settings, source.id)):
        pass
    delete_pair(settings, source.id)
    assert drivers[1].closed


def test_request_scope_and_lifespan_reuse_then_close(source, settings, drivers, monkeypatch, tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps([source.model_dump()])); path.chmod(0o600)
    app = create_app(replace(settings, database_sources_file=path))
    def probe(source):
        assert current_database_pools.get() is app.state.runtime.database_pools
        with neo4j_session(source):
            return {"ok": True}
    monkeypatch.setattr("graphmine_agent.database_connections.check_connection", probe)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer test-secret"
        assert client.post("/api/database-sources/source/status").status_code == 200
        assert client.post("/api/database-sources/source/status").status_code == 200
        assert len(drivers) == 1 and not drivers[0].closed
    assert drivers[0].closed and app.state.runtime.database_pools._closed


def test_installed_neo4j_driver_accepts_pool_options_without_eager_network(source, pools, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Lazy driver construction must not resolve network addresses")
    monkeypatch.setattr("socket.getaddrinfo", unexpected)
    with neo4j_session(source) as first:
        assert not first.closed()
    with neo4j_session(source) as second:
        assert first.closed() and first is not second
    assert len(pools._entries) == 1


def test_environment_pool_settings(settings, monkeypatch):
    from graphmine_agent.config import Settings
    for suffix, value in (("LIMIT", 7), ("SIZE", 3), ("WAIT_SECONDS", 8), ("IDLE_SECONDS", 90)):
        monkeypatch.setenv("GRAPHMINE_DATABASE_POOL_" + suffix, str(value))
    loaded = Settings.from_env(settings.repository_root)
    assert (loaded.database_pool_limit, loaded.database_pool_size, loaded.database_pool_wait_seconds, loaded.database_pool_idle_seconds) == (7, 3, 8, 90)


@pytest.mark.parametrize("field,value", [("database_pool_limit", 0), ("database_pool_size", 33),
                                         ("database_pool_wait_seconds", 121), ("database_pool_idle_seconds", 0)])
def test_pool_settings_have_operator_bounds(settings, field, value):
    with pytest.raises(ValueError, match=field):
        replace(settings, **{field: value})
