"""Named IU databases remain distinct through the picker, schema and queries."""

from contextlib import contextmanager
from dataclasses import replace
import importlib.util
import json
from pathlib import Path

import pytest

from graphmine_agent.database_sources import configured, get_source
from graphmine_agent.neo4j_backend import IU_URI, get_active_neo4j, set_active_backend
from test_database_workspace import source, workspace  # noqa: F401
from test_iu_neo4j_connections import iu_settings  # noqa: F401

SPEC = importlib.util.spec_from_file_location("iu_discovery", Path(__file__).resolve().parents[2] / "scripts/discover_iu_neo4j.py")
discovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(discovery)


def test_curated_picker_and_api_route_each_iu_database_independently(workspace, monkeypatch):
    w = workspace
    original = json.loads(w.config.read_text())
    base = {"id": "iu-remote", "name": "Neo4j", "users": ["*"], "neo4j_uri": IU_URI, "auth_disabled": True}
    w.config.write_text(json.dumps(original + [base] + [
        {**base, "id": "iu-" + name, "name": name.title(), "neo4j_database": name,
         "users": ["someone-else"] if name == "private" else ["*"]}
        for name in ["yelp", "amazon", "private", "not-listed"]]))
    w.runtime.settings = replace(w.runtime.settings, database_dataset_allowlist=("default", "iu-remote", "iu-yelp", "iu-amazon", "iu-private"))
    set_active_backend(w.runtime.settings, "iu-remote")
    monkeypatch.setattr("socket.create_connection", lambda *_a, **_k: pytest.fail("Picker discovery connected to Neo4j"))
    inventory = w.client.get("/api/data-sources").json()
    assert inventory["dataset_picker_only"] and inventory["active_backend"] == "iu-remote"
    assert [(s["source_id"], s["name"]) for s in inventory["items"]] == [("iu-remote", "Neo4j"), ("iu-yelp", "Yelp"), ("iu-amazon", "Amazon")]
    calls = []
    def execute(source, body, limit):
        calls.append(get_active_neo4j(source=source).connection.database)
        return {"vertices": [], "edges": []}, {"vertices": {}, "edges": {}}, [], 0, None
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute)
    def schema(source):
        database = get_active_neo4j(source=source).connection.database
        return {"entities": [{"id": database, "label": database, "properties": []}], "relationships": [], "schema_scope": {}, "message": ""}
    monkeypatch.setattr("graphmine_agent.neo4j_schema.sample_schema", schema)
    fingerprints = set()
    for name in ["yelp", "amazon"]:
        prefix = "/api/database-sources/iu-" + name
        assert w.client.get(prefix + "/datasets").json()[0]["name"] == name.title()
        assert w.client.get(prefix + "/schema").json()["entities"][0]["label"] == name
        response = w.client.post(prefix + "/queries", json={"statement": "MATCH (n) RETURN n LIMIT 1", "dataset_id": "default"})
        assert response.status_code == 201, response.text
        assert calls[-1] == name
        fingerprints.add(get_source(w.runtime.settings, "iu-" + name).fingerprint())
    assert len(fingerprints) == 2
    before = len(calls)
    for name in ["private", "not-listed", "missing"]:
        assert w.client.post("/api/database-sources/iu-" + name + "/queries", json={"statement": "RETURN 1"}).status_code == 404
    assert w.client.post("/api/database-sources/iu-yelp/queries", json={"statement": "RETURN 1", "dataset_id": "amazon"}).status_code == 404
    assert len(calls) == before
    set_active_backend(w.runtime.settings, "local")
    assert w.client.get("/api/database-sources/iu-yelp/datasets").status_code == 404
    assert not w.client.get("/api/data-sources").json()["items"]


def test_discovery_uses_system_read_without_wake_and_excludes_non_data_databases(iu_settings, monkeypatch):
    class Transaction:
        def run(self, statement):
            assert statement.startswith("SHOW DATABASES") and statement.endswith("LIMIT 101")
            return [{"name": name, "type": kind, "currentStatus": status} for name, kind, status in [
                ("yelp", "standard", "online"), ("amazon", "standard", "online"),
                ("system", "system", "online"), ("offline", "standard", "offline"), ("composite", "composite", "online")]]
    class Session:
        def execute_read(self, work):
            assert work.timeout == 10
            return work(Transaction())
    @contextmanager
    def session(source, *, wake):
        assert wake is False and get_active_neo4j(source=source).connection.database == "system"
        yield Session()
    monkeypatch.setattr(discovery, "neo4j_session", session)
    assert discovery.discover(configured(iu_settings)[0]) == ["amazon", "yelp"]


def test_proposal_keeps_existing_configuration_and_stable_database_ids(iu_settings, monkeypatch):
    original = iu_settings.database_sources_file.read_bytes()
    monkeypatch.setattr(discovery, "discover", lambda _: ["amazon", "neo4j", "yelp"])
    rows, selected = discovery.proposal(iu_settings)
    assert iu_settings.database_sources_file.read_bytes() == original
    assert [(r["source_id"], r["name"]) for r in selected] == [("iu-amazon", "Amazon"), ("iu-remote", "Neo4j"), ("iu-yelp", "Yelp")]
    assert {r["neo4j_database"] for r in rows} == {"amazon", "neo4j", "yelp"}
    iu_settings.database_sources_file.write_text(json.dumps(rows))
    assert discovery.proposal(iu_settings) == (rows, selected)
