"""Persistent selection, endpoint identity, and resolver-only URI access."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import logging
from pathlib import Path
import re
import secrets
import subprocess

import pytest

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.database import RecordNotFound
from graphmine_agent.database_sources import DatabaseSource, neo4j_session
from graphmine_agent.neo4j_backend import (
    IU_URI, active_backend_id, backend_registry, get_active_neo4j, local_browser_endpoints, set_active_backend,
)


@pytest.fixture
def backend_settings(settings, tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"version": 1, "datasets": [
        {"id": "yelp", "bolt_uri": "bolt://127.0.0.1:17701", "password_env": "TEST_LOCAL_PASSWORD"},
        {"id": "movielens-32m", "bolt_uri": "bolt://127.0.0.1:17702", "password_env": "TEST_LOCAL_PASSWORD"},
    ]}))
    return replace(settings, data_root=tmp_path / "new-store", neo4j_datasets_registry=registry,
                   neo4j_datasets_password_file=None)


def test_exactly_two_backends_remote_default_is_private_and_has_no_network_side_effects(backend_settings, monkeypatch):
    monkeypatch.setattr("socket.create_connection", lambda *_a, **_k: pytest.fail("Discovery attempted a connection"))
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("Discovery started a process"))
    assert set(backend_registry(backend_settings)) == {"local", "iu-remote"}
    backend = get_active_neo4j(backend_settings)
    assert backend.id == "iu-remote" and len(backend.endpoints) == 1
    assert backend.connection.uri == "bolt://10.2.147.169:7689"
    assert backend.connection.auth is None
    state = backend_settings.data_root / "neo4j_backend.json"
    assert json.loads(state.read_text()) == {"version": 1, "active_backend": "iu-remote"}
    assert state.stat().st_mode & 0o777 == 0o600


def test_concurrent_initialization_and_atomic_switches(backend_settings):
    with ThreadPoolExecutor(max_workers=12) as pool:
        assert set(pool.map(lambda _: active_backend_id(backend_settings), range(48))) == {"iu-remote"}
        def update(index):
            set_active_backend(backend_settings, "local" if index % 2 else "iu-remote")
            # An unlocked reader must still see complete valid JSON.
            return json.loads((backend_settings.data_root / "neo4j_backend.json").read_text())["active_backend"]
        assert set(pool.map(update, range(96))) <= {"local", "iu-remote"}
    set_active_backend(backend_settings, "local")
    assert get_active_neo4j(backend_settings).id == "local"
    assert active_backend_id(replace(backend_settings)) == "local"


def test_local_maintenance_is_explicit_and_cannot_retarget_the_application(backend_settings, monkeypatch):
    monkeypatch.setenv("TEST_LOCAL_PASSWORD", "local-test-password")
    assert active_backend_id(backend_settings) == "iu-remote"
    local = get_active_neo4j(backend_settings, target="local")
    assert [item.address for item in local.endpoints] == [("127.0.0.1", 17701), ("127.0.0.1", 17702)]
    assert all(item.auth == ("neo4j", "local-test-password") for item in local.endpoints)
    assert "local-test-password" not in repr(local)
    assert active_backend_id(backend_settings) == "iu-remote"
    with pytest.raises(ValueError):
        get_active_neo4j(backend_settings, target="unexpected")
    with pytest.raises(ValueError):
        set_active_backend(backend_settings, "unexpected")


def test_old_local_mapping_is_never_silently_applied_to_remote(backend_settings):
    source = DatabaseSource(id="demo", name="Demo", users=["*"], neo4j_uri="bolt://127.0.0.1:17700", neo4j_password_env="LOCAL")
    for write in (False, True):
        with pytest.raises(RecordNotFound, match="not found"):
            get_active_neo4j(backend_settings, source, write=write)
    set_active_backend(backend_settings, "local")
    assert get_active_neo4j(backend_settings, source).connection.uri == source.neo4j_uri


@pytest.mark.parametrize("uri", ["bolt://10.0.0.9:7687", "neo4j://127.0.0.1:17701", "bolt://127.0.0.1:17701/", IU_URI])
def test_local_registry_cannot_escape_local_endpoints(backend_settings, uri):
    backend_settings.neo4j_datasets_registry.write_text(json.dumps({"version": 1, "datasets": [{"id": "x", "bolt_uri": uri}]}))
    with pytest.raises(AnalyticsError):
        backend_registry(backend_settings)


def test_bad_state_never_falls_back_or_logs_secrets(backend_settings, monkeypatch, caplog, capsys):
    private_key = secrets.token_urlsafe(32)
    ssh_password = secrets.token_urlsafe(32)
    monkeypatch.setenv("GRAPHMINE_IU_SSH_PASSWORD", ssh_password)
    active_backend_id(backend_settings)
    path = backend_settings.data_root / "neo4j_backend.json"
    path.write_text(json.dumps({"active_backend": private_key, "password": ssh_password}))
    with caplog.at_level(logging.DEBUG), pytest.raises(AnalyticsError) as caught:
        get_active_neo4j(backend_settings)
    captured = capsys.readouterr()
    logged = caplog.text + str(caught.value) + captured.out + captured.err
    assert private_key not in logged and ssh_password not in logged
    assert json.loads(path.read_text())["active_backend"] == private_key


def test_state_symlink_cannot_read_or_overwrite_other_files(backend_settings, tmp_path):
    backend_settings.data_root.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("keep")
    (backend_settings.data_root / "neo4j_backend.json").symlink_to(victim)
    with pytest.raises(AnalyticsError):
        active_backend_id(backend_settings)
    assert victim.read_text() == "keep"


def test_application_driver_uses_resolved_direct_endpoint_and_no_auth(backend_settings, monkeypatch):
    from contextlib import contextmanager
    made = []
    class Driver:
        def __init__(self, uri, **options):
            made.append((uri, options))
        @contextmanager
        def session(self, **options):
            yield options
        def close(self):
            pass
    monkeypatch.setattr("neo4j.GraphDatabase.driver", Driver)
    source = DatabaseSource(id="iu-remote", name="IU", users=["*"], neo4j_uri=IU_URI, neo4j_password_env="UNUSED")
    source._backend_settings = backend_settings
    with neo4j_session(source) as session:
        assert session["default_access_mode"] == "READ"
    assert made[0][0] == IU_URI and made[0][1]["auth"] is None


def test_local_browser_does_not_bypass_active_selection(backend_settings):
    with pytest.raises(RecordNotFound):
        local_browser_endpoints(backend_settings)
    set_active_backend(backend_settings, "local")
    assert local_browser_endpoints(backend_settings) == ("http://127.0.0.1:17474", "ws://127.0.0.1:17687")


def test_remote_connector_uses_direct_bolt_and_managed_read_transaction(backend_settings, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from graphmine_agent.connectors import Connector, neo4j_rows
    events = []
    class Driver:
        def __init__(self, uri, **options):
            events.append((uri, options))
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        @contextmanager
        def session(self, **options):
            assert options == {"database": "neo4j", "default_access_mode": "READ"}
            yield self
        def execute_read(self, function):
            assert function.timeout == 30
            events.append("execute_read")
            return function(self)
        def run(self, query, parameters):
            assert query.startswith("MATCH") and parameters["limit"] > 0
            return [{"source": "a", "target": "b", "relationship": "R", "relationship_id": "r"}]
    monkeypatch.setattr("neo4j.GraphDatabase.driver", Driver)
    monkeypatch.setattr("graphmine_agent.connectors.rest_bytes", lambda *_a, **_k: pytest.fail("IU must use direct Bolt"))
    connector = Connector(id="iu", name="IU", type="neo4j", users=["*"], url="http://10.2.147.169:7474")
    rows = neo4j_rows(SimpleNamespace(settings=backend_settings), connector, 4096)
    assert rows[0]["source"] == "a"
    assert events[0][0] == IU_URI and events[0][1]["auth"] is None
    assert events[1] == "execute_read"


def test_browser_proxy_refuses_inactive_backend_before_any_http_request(backend_settings, monkeypatch):
    from fastapi.testclient import TestClient
    from graphmine_agent import neo4j_browser
    monkeypatch.setattr(neo4j_browser, "cli_settings", lambda _: backend_settings)
    with TestClient(neo4j_browser.app, base_url=neo4j_browser.ORIGIN) as client:
        response = client.get("/", headers={"Host": neo4j_browser.AUTHORITY})
        assert response.status_code == 503
        assert "active backend" in response.text
        assert client.get("/", headers={"Host": "untrusted.example"}).status_code == 400


def test_grep_no_runtime_module_reads_neo4j_uri_outside_resolver():
    root = Path(__file__).resolve().parents[2]
    # Equivalent to grep -nE over runtime Python sources. Declarations and
    # fixture values are not URI reads; source.attribute and record[key] are.
    pattern = re.compile(r'\.neo4j_uri\b|\[\s*[\"\x27](?:neo4j_uri|bolt_uri)[\"\x27]\s*\]')
    offenders = []
    for folder in (root / "agent/graphmine_agent", root / "deploy"):
        for path in folder.rglob("*.py"):
            if "tests" in path.parts or path.name == "neo4j_backend.py":
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(root)}:{number}")
    assert not offenders, "Direct Neo4j URI reads outside resolver: " + ", ".join(offenders)
