"""Verified benchmarks use separate instances and never acquire SQL lineage."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json

import pytest
from neo4j.graph import Graph, Node

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.benchmark_mappings import resolve_source
from graphmine_agent.database import RecordNotFound
from graphmine_agent.database_datasets import datasets
from graphmine_agent.database_queries import GraphCollector
from graphmine_agent.database_sources import get_source, neo4j_session
from graphmine_agent.identity import current_principal
from graphmine_agent.neo4j_registry import password, ready_datasets, sources as registry_sources
from test_connectors import sources  # noqa: F401
from test_database_workspace import source, workspace  # noqa: F401


def registry_setup(settings, directory, slugs=("yelp", "movielens-32m")):
    directory.mkdir(parents=True, exist_ok=True)
    root, registry, credentials = directory / "instances", directory / "registry.json", directory / "demo.env"
    entries, secrets = [], []
    for index, slug in enumerate(slugs, 1):
        env = "GRAPHMINE_NEO4J_" + slug.upper().replace("-", "_") + "_PASSWORD"
        entries.append({"id": slug, "name": slug, "bolt_uri": f"bolt://127.0.0.1:{17700+index}",
                        "password_env": env, "workload_url": f"https://pgraphbenchweb.vercel.app/workloads/{slug}-neo4j.html",
                        "default_query": "MATCH (n) RETURN n LIMIT 20", "memory": {"heap_gib": 4}})
        secrets.append(env + "=private-test-" + slug)
        home = root / slug
        home.mkdir(parents=True)
        hashes = {"load/001.cypher": "a" * 64}
        report = {"id": slug, "passed": True, "script_hashes": hashes}
        payload = json.dumps(report)
        (home / "verify_report.json").write_text(payload)
        (home / "status.json").write_text(json.dumps({"id": slug, "status": "ready", "phase": "ready",
            "verify_report_sha256": hashlib.sha256(payload.encode()).hexdigest(), "script_hashes": hashes,
            "load_finished_at": "2026-11-15T00:00:00+00:00", "verified_at": "2026-11-15T00:01:00+00:00", "load_seconds": 60,
            "counts": {"nodes": {"User": 1}, "relationships": {}, "total_nodes": 1, "total_relationships": 0}}))
    registry.write_text(json.dumps({"version": 1, "datasets": entries}))
    credentials.write_text("\n".join(secrets) + "\n")
    credentials.chmod(0o600)
    return replace(settings, neo4j_datasets_registry=registry, neo4j_instances_root=root,
                   neo4j_datasets_password_file=credentials)


def test_registry_requires_ready_state_and_matching_successful_report(settings, tmp_path):
    settings = registry_setup(settings, tmp_path / "registry")
    assert len(ready_datasets(settings)) == 2
    path = settings.neo4j_instances_root / "yelp/status.json"
    state = json.loads(path.read_text())
    path.write_text(json.dumps({**state, "status": "loading"}))
    assert [d["id"] for d in ready_datasets(settings)] == ["movielens-32m"]
    path.write_text(json.dumps(state))
    (path.parent / "verify_report.json").write_text('{"id":"yelp","passed":false}')
    assert [d["id"] for d in ready_datasets(settings)] == ["movielens-32m"]


def test_each_instance_has_its_own_connection_and_identity_without_sql(settings, tmp_path):
    settings = registry_setup(settings, tmp_path / "registry")
    first, second = registry_sources(settings)
    assert first.neo4j_uri != second.neo4j_uri
    assert first.fingerprint() != second.fingerprint()
    identities = []
    for source in [first, second]:
        assert not source.entities and not source.relationships and source.sql_type is None
        assert source.capabilities()["enrichment"] is False
        assert datasets(settings, source)[0]["graph_label"] is None
        collector = GraphCollector(source, 100_000)
        identities.append(collector.node(Node(Graph(), "same-element-id", 1, {"User"}, {"name": "Ada"})))
        assert collector.lineage == {"vertices": {}, "edges": {}}
        with pytest.raises(AnalyticsError, match="read queries only"):
            with neo4j_session(source, write=True):
                pytest.fail("No writer should be opened")
    assert identities[0] != identities[1]
    with pytest.raises(RecordNotFound):
        resolve_source(settings, first, "movielens-32m")
    assert "private-test" not in json.dumps([s.public() for s in [first, second]])


def test_password_file_is_private_and_values_are_not_evaluated(settings, tmp_path):
    settings = registry_setup(settings, tmp_path / "registry", ("yelp",))
    path = settings.neo4j_datasets_password_file
    path.write_text("GRAPHMINE_NEO4J_YELP_PASSWORD='literal $(not-a-command)'\n")
    assert password(path, "GRAPHMINE_NEO4J_YELP_PASSWORD") == "literal $(not-a-command)"
    path.chmod(0o644)
    with pytest.raises(AnalyticsError) as error:
        password(path, "GRAPHMINE_NEO4J_YELP_PASSWORD")
    assert "not-a-command" not in str(error.value)


def test_snapshot_provenance_and_enrichment_capabilities(workspace, tmp_path, monkeypatch):
    workspace.runtime.settings = registry_setup(workspace.runtime.settings, tmp_path / "registry")
    def execute(source, body, limit):
        collector = GraphCollector(source, limit)
        collector.node(Node(Graph(), "n1", 1, {"User"}, {"name": "Ada"}))
        return collector.graph(), collector.lineage, [], 1, None
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute)
    response = workspace.client.post("/api/database-sources/benchmark-yelp/queries", json={
        "statement": "MATCH (start:User) RETURN start", "dataset_id": "yelp"})
    assert response.status_code == 201, response.text
    snapshot = response.json()["dataset"]
    provenance = snapshot["source"]
    assert provenance["database_dataset"]["id"] == "yelp"
    assert provenance["database_dataset"]["script_hashes"] == {"load/001.cypher": "a" * 64}
    assert provenance["database_dataset"]["load_seconds"] == 60
    assert not provenance["database_source"]["capabilities"]["enrichment"]
    opened = workspace.client.post(f"/api/database-query-snapshots/{snapshot['id']}/chat", json={})
    assert opened.status_code == 201, opened.text
    result = workspace.client.post(f"/api/files/{opened.json()['file']['id']}/enrichments", json={
        "mapping": "accounts", "fields": ["risk"]})
    assert result.status_code == 409 and result.json()["error"]["code"] == "sql_unavailable"
    result = workspace.client.post(f"/api/files/{opened.json()['file']['id']}/expansions", json={"mapping": "unavailable"})
    assert result.status_code == 409 and result.json()["error"]["code"] == "sql_unavailable"
    assert get_source(workspace.runtime.settings, "demo").capabilities()["enrichment"] is True


def test_two_users_select_different_instances_and_cannot_open_each_others_results(sources, tmp_path, monkeypatch):
    client, runtime, alice, bob, *_ = sources
    runtime.settings = registry_setup(runtime.settings, tmp_path / "registry")
    calls = []
    def execute(source, body, limit):
        calls.append((current_principal.get().username, source.neo4j_uri))
        collector = GraphCollector(source, limit)
        collector.node(Node(Graph(), "n1", 1, {"User"}, {"dataset": source._catalog["id"]}))
        return collector.graph(), collector.lineage, [], 1, None
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute)
    def query(slug, headers):
        return client.post(f"/api/database-sources/benchmark-{slug}/queries", headers=headers,
                           json={"statement": "MATCH (n:User) RETURN n", "dataset_id": slug})
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(query, "yelp", alice)
        second = pool.submit(query, "movielens-32m", bob)
        a, b = first.result(), second.result()
    assert a.status_code == b.status_code == 201, (a.text, b.text)
    assert sorted(calls) == [("alice", "bolt://127.0.0.1:17701"), ("bob", "bolt://127.0.0.1:17702")]
    assert a.json()["graph"]["vertices"][0]["id"] != b.json()["graph"]["vertices"][0]["id"]
    response = client.post(f"/api/database-query-snapshots/{b.json()['dataset']['id']}/chat", headers=alice, json={})
    assert response.status_code == 404
