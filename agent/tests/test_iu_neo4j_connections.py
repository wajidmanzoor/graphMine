"""Configured IU authentication and exact-address policy, without live connections."""

from contextlib import contextmanager
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.database_connections import ConnectionPair, load_source, network_address
from graphmine_agent.database_sources import DatabaseSource, configured, neo4j_read, neo4j_session
from graphmine_agent.neo4j_backend import IU_URI, backend_registry, get_active_neo4j, set_active_backend
from graphmine_agent.neo4j_registry import ready_datasets, sources as registry_sources
from test_benchmark_mappings import registry_setup


@pytest.fixture
def iu_settings(settings, tmp_path):
    path = tmp_path / "configured-sources.json"
    path.write_text(json.dumps([{"id": "iu-remote", "name": "IU Neo4j", "users": ["*"],
                                "neo4j_uri": IU_URI, "auth_disabled": True}]))
    path.chmod(0o600)
    value = replace(settings, accounts_enabled=True, database_sources_file=path,
                    connector_allowed_origins=(), database_credentials_file=tmp_path / "absent.env")
    set_active_backend(value, "iu-remote")
    return value


@pytest.mark.parametrize("database", ["neo4j", "yelp", "amazon", "fars20-22"])
def test_configured_iu_driver_uses_no_credentials_and_pins_only_exact_address(iu_settings, monkeypatch, database):
    from graphmine_agent.remote_neo4j import get_remote
    power = get_remote(iu_settings)
    monkeypatch.setattr(power, "tcp", lambda *_: True)
    monkeypatch.setattr(power, "verify", lambda _: True)
    calls = []
    class Driver:
        def __init__(self, uri, **options):
            calls.append((uri, options))
        @contextmanager
        def session(self, **options):
            yield options
        def close(self):
            pass
    monkeypatch.setattr("neo4j.GraphDatabase.driver", Driver)
    monkeypatch.setattr("graphmine_agent.database_sources.source_secret",
                        lambda *_: pytest.fail("An unauthenticated configured source read a password"))
    source = configured(iu_settings)[0]
    source.neo4j_database = database
    assert source.auth_disabled and source.neo4j_password_env is None
    with neo4j_session(source) as session:
        assert session == {"database": database, "default_access_mode": "READ"}
    uri, options = calls[0]
    assert uri == IU_URI and options["auth"] is None
    resolver = options["resolver"]
    assert resolver(SimpleNamespace(host="10.2.147.169", port=7689)) == [("10.2.147.169", 7689)]
    with pytest.raises(AnalyticsError, match="private database address"):
        resolver(SimpleNamespace(host="10.2.147.169", port=7687))


@pytest.mark.parametrize("host, port", [
    ("10.2.147.169", 7687), ("10.2.147.169", 7474), ("10.2.147.170", 7689),
    ("10.66.0.1", 7689), ("127.0.0.1", 7689),
])
def test_iu_allowance_does_not_allow_other_private_destinations(iu_settings, host, port):
    assert network_address(iu_settings, "10.2.147.169", 7689) == "10.2.147.169"
    with pytest.raises(AnalyticsError, match="private database address"):
        network_address(iu_settings, host, port)


def test_iu_address_requires_configured_file_and_source_access(iu_settings):
    with pytest.raises(AnalyticsError, match="private database address"):
        network_address(replace(iu_settings, database_sources_file=None), "10.2.147.169", 7689)
    data = json.loads(iu_settings.database_sources_file.read_text())
    data[0]["users"] = ["another-user"]
    iu_settings.database_sources_file.write_text(json.dumps(data))
    with pytest.raises(AnalyticsError, match="private database address"):
        network_address(iu_settings, "10.2.147.169", 7689)


@pytest.mark.parametrize("uri, flag", [
    ("bolt://10.2.147.169:7687", True), ("neo4j://10.2.147.169:7689", True),
    ("bolt://127.0.0.1:17701", True), ("bolt://10.0.0.1:7689", True),
    (IU_URI, False), (IU_URI, "true"),
])
def test_auth_disabled_is_explicit_and_limited_to_exact_iu_source(iu_settings, uri, flag):
    data = json.loads(iu_settings.database_sources_file.read_text())
    data[0].update(neo4j_uri=uri, auth_disabled=flag)
    iu_settings.database_sources_file.write_text(json.dumps(data))
    with pytest.raises(AnalyticsError, match="configuration is unavailable"):
        configured(iu_settings)


def test_user_connections_cannot_opt_out_of_credentials(iu_settings):
    source = configured(iu_settings)[0]
    for password in (None, "", "user-supplied-password"):
        with pytest.raises(ValueError, match="require Neo4j credentials"):
            load_source(iu_settings, {"source": source.model_dump(), "neo4j_password": password})
    source.auth_disabled = False
    with pytest.raises(ValueError, match="credential settings are incomplete"):
        load_source(iu_settings, {"source": source.model_dump(), "neo4j_password": ""})
    with pytest.raises(ValidationError):
        ConnectionPair(name="IU", neo4j_uri=IU_URI, auth_disabled=True)
    untrusted = DatabaseSource(id="iu", name="IU", users=["*"], neo4j_uri=IU_URI, auth_disabled=True)
    with pytest.raises(AnalyticsError, match="configuration is unavailable"):
        get_active_neo4j(iu_settings, untrusted)


def test_registry_accepts_iu_without_adding_it_to_local_backend(iu_settings, tmp_path):
    settings = registry_setup(iu_settings, tmp_path / "registry", ("yelp",))
    document = json.loads(settings.neo4j_datasets_registry.read_text())
    entry = document["datasets"][0]
    entry.update(bolt_uri=IU_URI, auth_disabled=True)
    del entry["password_env"]
    settings.neo4j_datasets_registry.write_text(json.dumps(document))
    assert ready_datasets(settings)[0]["auth_disabled"] is True
    source = registry_sources(settings)[0]
    assert get_active_neo4j(settings, source).connection.auth is None
    assert backend_registry(settings)["local"].endpoints == ()
    with pytest.raises(ValueError):
        get_active_neo4j(settings, target="local", local_record=entry)


@pytest.mark.parametrize("uri", ["bolt://10.2.147.169:7687", "neo4j://10.2.147.169:7689", "bolt://10.0.0.8:7689"])
def test_registry_rejects_other_remote_destinations(iu_settings, tmp_path, uri):
    settings = registry_setup(iu_settings, tmp_path / "registry", ("yelp",))
    document = json.loads(settings.neo4j_datasets_registry.read_text())
    document["datasets"][0].update(bolt_uri=uri, auth_disabled=True)
    settings.neo4j_datasets_registry.write_text(json.dumps(document))
    with pytest.raises(AnalyticsError, match="registry is unavailable"):
        ready_datasets(settings)


def test_iu_read_helper_uses_managed_read_with_transaction_timeout(iu_settings):
    source = configured(iu_settings)[0]
    transaction = object()
    class Session:
        def execute_read(self, work):
            assert work.timeout == 7
            return work(transaction)
        def begin_transaction(self, **_):
            pytest.fail("IU must use execute_read")
    assert neo4j_read(Session(), source, lambda tx: tx, timeout=7) is transaction


def test_managed_query_retry_does_not_duplicate_collected_rows(iu_settings, monkeypatch):
    from neo4j import Record
    from graphmine_agent.database_queries import CypherRequest, execute_query
    class Result(list):
        def keys(self):
            return ["answer"]
        def consume(self):
            return SimpleNamespace(query_type="r")
    class Transaction:
        def run(self, statement, parameters):
            return Result() if statement.startswith("EXPLAIN ") else Result([Record({"answer": 1})])
    class Session:
        def execute_read(self, work):
            assert work.timeout == 5
            work(Transaction())  # Simulate a retry after the first read attempt.
            return work(Transaction())
    @contextmanager
    def session(_):
        yield Session()
    monkeypatch.setattr("graphmine_agent.database_queries.neo4j_session", session)
    _, _, sample, rows, _ = execute_query(configured(iu_settings)[0],
        CypherRequest(statement="RETURN 1 AS answer"), timeout_seconds=5)
    assert rows == 1 and sample == [{"answer": 1}]


def test_managed_schema_retry_does_not_leak_first_attempt_choices(iu_settings, monkeypatch):
    from graphmine_agent.neo4j_schema import sample_schema
    class Transaction:
        def __init__(self, label):
            self.label = label
        def run(self, statement, parameters):
            if statement.startswith("MATCH (n)"):
                return [{"labels": [self.label], "properties": ["name"]}]
            return []
    class Session:
        def execute_read(self, work):
            assert work.timeout == 10
            work(Transaction("FirstAttempt"))
            return work(Transaction("SecondAttempt"))
    @contextmanager
    def session(_):
        yield Session()
    monkeypatch.setattr("graphmine_agent.neo4j_schema.neo4j_session", session)
    result = sample_schema(configured(iu_settings)[0])
    assert [entry["label"] for entry in result["entities"]] == ["SecondAttempt"]
