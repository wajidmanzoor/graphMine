"""Connection pairs persist privately and never leak credentials or cross accounts."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from graphmine_agent.api import create_app
from graphmine_agent.database import RecordNotFound
from graphmine_agent.database_connections import ConnectionPair, owner_directory, save_pair
from graphmine_agent.database_sources import available, get_source
from graphmine_agent.identity import current_principal


@pytest.fixture
def settings(settings):
    return replace(settings, database_sources_file=None)


@pytest.fixture
def pair():
    return ConnectionPair(
        name="Remote research", host="database.example.com", database="research",
        username="reader", password="sql-test-secret",
        neo4j_uri="neo4j+s://graph.example.com", neo4j_password="graph-test-secret",
    )


@pytest.fixture
def connected(monkeypatch):
    monkeypatch.setattr("graphmine_agent.database_connections.network_address", lambda *args: "203.0.113.1")
    monkeypatch.setattr("graphmine_agent.database_connections.check_connection", lambda source: {
        "connected": True, "sql": {"connected": True}, "neo4j": {"connected": True}
    })


def test_saved_pair_is_private_and_survives_reload(settings, pair, connected):
    result = save_pair(settings, pair)
    identifier = result["id"]
    path = owner_directory(settings) / f"{identifier}.json"
    assert path.stat().st_mode & 0o077 == 0
    assert result["managed"] is True
    assert result["connection"]["sql"]["database"] == "research"
    assert "secret" not in json.dumps(result)
    restored = get_source(settings, identifier)
    assert restored._sql_credentials["password"] == "sql-test-secret"
    assert restored._neo4j_password == "graph-test-secret"
    assert "secret" not in restored.model_dump_json()
    assert "secret" not in repr(restored)


def test_connection_ownership(settings, pair, connected):
    alice = current_principal.set(SimpleNamespace(user_id="alice", username="alice"))
    try:
        saved = save_pair(settings, pair)
        assert get_source(settings, saved["id"]).name == pair.name
    finally:
        current_principal.reset(alice)
    bob = current_principal.set(SimpleNamespace(user_id="bob", username="bob"))
    try:
        assert available(settings) == []
        with pytest.raises(RecordNotFound):
            get_source(settings, saved["id"])
    finally:
        current_principal.reset(bob)


def test_edit_keeps_password_only_for_same_endpoint(settings, pair, connected):
    result = save_pair(settings, pair)
    body = pair.model_copy(update={"name": "Renamed", "password": None, "neo4j_password": None})
    updated = save_pair(settings, body, result["id"])
    assert updated["revision"] == result["revision"]
    assert updated["mapping_hash"] == result["mapping_hash"]
    assert get_source(settings, result["id"])._neo4j_password == "graph-test-secret"
    from graphmine_agent.analytics import AnalyticsError
    with pytest.raises(AnalyticsError, match="entered again"):
        save_pair(settings, body.model_copy(update={"host": "different.example.com"}), result["id"])


def test_mapping_edit_invalidates_lineage_but_password_rotation_does_not(settings, pair, connected):
    saved = save_pair(settings, pair)
    from pydantic import SecretStr
    rotated = save_pair(settings, pair.model_copy(update={"password": SecretStr("rotated")}), saved["id"])
    assert rotated["mapping_hash"] == saved["mapping_hash"]
    changed = ConnectionPair.model_validate({**pair.model_dump(), "entities": [
        {"id": "people", "table": "people", "key": ["id"], "label": "Person", "attributes": ["name"]}
    ]})
    updated = save_pair(settings, changed, saved["id"])
    assert updated["revision"] == 2
    assert updated["mapping_hash"] != saved["mapping_hash"]


def test_failed_connection_is_not_saved(settings, pair, monkeypatch, connected):
    monkeypatch.setattr("graphmine_agent.database_connections.check_connection", lambda source: {
        "connected": False, "sql": {"connected": True}, "neo4j": {"connected": False}
    })
    from graphmine_agent.analytics import AnalyticsError
    with pytest.raises(AnalyticsError, match="neo4j"):
        save_pair(settings, pair)
    assert not owner_directory(settings).exists()


def test_ipv6_connection_can_be_reopened_and_edited(settings, pair, connected):
    pair = pair.model_copy(update={"neo4j_uri": "bolt://[2001:db8::1]:7687"})
    result = save_pair(settings, pair)
    body = ConnectionPair.model_validate({
        **pair.model_dump(), "name": "Renamed IPv6 database",
        "neo4j_uri": result["connection"]["neo4j"]["uri"],
        "password": None, "neo4j_password": None,
    })
    saved = save_pair(settings, body, result["id"])
    assert saved["connection"]["neo4j"]["uri"] == pair.neo4j_uri


def test_account_database_connections_require_allowed_private_endpoints(settings, monkeypatch):
    from dataclasses import replace
    from graphmine_agent.analytics import AnalyticsError
    from graphmine_agent.database_connections import network_address

    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [
        (2, 1, 6, "", ("10.20.30.40", args[1])),
    ])
    restricted = replace(settings, accounts_enabled=True, database_sources_file=None,
                         connector_allowed_origins=())
    with pytest.raises(AnalyticsError, match="private database address"):
        network_address(restricted, "research.internal", 5432)
    allowed = replace(restricted, connector_allowed_origins=("postgres://research.internal:5432",))
    assert network_address(allowed, "research.internal", 5432) == "10.20.30.40"
    with pytest.raises(AnalyticsError, match="private database address"):
        network_address(allowed, "research.internal", 7687)


def test_pair_routes_preserve_authentication_and_redact(settings, pair, connected):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/database-sources").status_code == 401
        client.headers["Authorization"] = "Bearer test-secret"
        body = {**pair.model_dump(exclude={"password", "neo4j_password"}), "password": "sql-test-secret", "neo4j_password": "graph-test-secret"}
        result = client.post("/api/database-sources", json=body)
        assert result.status_code == 201, result.text
        identifier = result.json()["id"]
        for path in ("/api/database-sources", f"/api/database-sources/{identifier}", f"/api/database-sources/{identifier}/settings"):
            response = client.get(path)
            assert response.status_code == 200
            assert "secret" not in response.text
        response = client.post(f"/api/database-sources/{identifier}/status")
        assert response.json()["connected"] is True
        assert client.post("/api/database-sources/missing/status").status_code == 404
        invalid = client.post("/api/database-sources", json={**body, "neo4j_uri": "https://invalid"})
        assert invalid.status_code == 422
        assert "sql-test-secret" not in invalid.text and "graph-test-secret" not in invalid.text
        invalid = client.post("/api/database-sources", json={**body, "entities": [
            {"id": "people", "table": "people", "key": ["not a column"], "label": "Person"}
        ]})
        assert invalid.status_code == 422
        assert "sql-test-secret" not in invalid.text and "graph-test-secret" not in invalid.text
        assert client.delete(f"/api/database-sources/{identifier}").status_code == 200
        assert client.get(f"/api/database-sources/{identifier}/settings").status_code == 404


@pytest.mark.parametrize("uri", ["https://graph.example.com", "bolt://user:secret@graph.example.com", "bolt://graph.example.com/path", "bolt://graph.example.com:99999"])
def test_invalid_neo4j_endpoints(pair, uri):
    with pytest.raises(ValueError):
        ConnectionPair.model_validate({**pair.model_dump(), "neo4j_uri": uri})
