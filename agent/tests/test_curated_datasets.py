"""The public dataset selection also constrains direct API query routing."""

from dataclasses import replace
import json

import pytest

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.config import Settings
from graphmine_agent.database_sources import get_source, source_secret
from test_benchmark_mappings import registry_setup
from test_database_workspace import source, workspace  # noqa: F401


CHOICES = ("default", "yelp", "movielens-32m", "movielens-genome", "ldbc-snb")


def curated(workspace, tmp_path):
    settings = registry_setup(workspace.runtime.settings, tmp_path / "registry", CHOICES[1:] + ("ontime", "stackoverflow"))
    original = json.loads(workspace.config.read_text())[0]
    demo = {**original, "id": "local-transfers", "name": "Transfers demo", "neo4j_uri": "bolt://127.0.0.1:17700"}
    workspace.config.write_text(json.dumps([demo, original]))
    raw = tmp_path / 'datasets'
    for slug in CHOICES[1:] + ('ontime', 'stackoverflow', 'amazon', 'fars'):
        (raw / slug).mkdir(parents=True)
    workspace.runtime.settings = replace(settings, database_dataset_allowlist=CHOICES, benchmark_datasets_root=raw)
    return workspace.runtime.settings


def test_inventory_has_only_curated_ready_datasets_and_cannot_query_hidden_sources(workspace, tmp_path, monkeypatch):
    settings = curated(workspace, tmp_path)
    def forbidden(*args):
        pytest.fail("Curated discovery must not load managed databases or connectors")
    monkeypatch.setattr("graphmine_agent.database_connections.managed_sources", forbidden)
    monkeypatch.setattr("graphmine_agent.connectors.available", forbidden)
    inventory = workspace.client.get('/api/data-sources').json()
    ids = [item['source_id'] for item in inventory['items']]
    assert ids == ['local-transfers'] + ['benchmark-' + slug for slug in CHOICES[1:]]
    assert inventory['dataset_picker_only'] and not inventory['can_manage_imports'] and not inventory['warnings']
    assert [row['id'] for row in workspace.client.get('/api/database-sources').json()] == ids
    assert [row['id'] for row in workspace.client.get('/api/benchmark-datasets').json()] == list(CHOICES[1:])
    assert workspace.client.get('/api/benchmark-datasets/ontime/schemas/neo4j.png').status_code == 404
    for source_id in ['demo', 'benchmark-ontime', 'benchmark-stackoverflow']:
        response = workspace.client.post(f'/api/database-sources/{source_id}/queries', json={'statement': 'MATCH (n) RETURN n LIMIT 1'})
        assert response.status_code == 404
    state = settings.neo4j_instances_root / 'yelp/status.json'
    state.write_text(json.dumps({**json.loads(state.read_text()), 'status': 'paused'}))
    assert 'benchmark-yelp' not in [item['source_id'] for item in workspace.client.get('/api/data-sources').json()['items']]


def test_query_uses_selected_instance_and_rejects_mismatched_dataset(workspace, tmp_path, monkeypatch):
    settings = curated(workspace, tmp_path)
    calls = []
    def execute(source, body, limit):
        calls.append((source.id, source.neo4j_uri, body.statement))
        return {'vertices': [], 'edges': []}, {'vertices': {}, 'edges': {}}, [], 0, None
    monkeypatch.setattr('graphmine_agent.database_queries.execute_query', execute)
    statement = 'MATCH (n) RETURN n LIMIT 1'
    for dataset in CHOICES:
        source_id = 'local-transfers' if dataset == 'default' else 'benchmark-' + dataset
        response = workspace.client.post(f'/api/database-sources/{source_id}/queries', json={'statement': statement, 'dataset_id': dataset})
        assert response.status_code == 201, response.text
        assert calls[-1] == (source_id, get_source(settings, source_id).neo4j_uri, statement)
    before = len(calls)
    response = workspace.client.post('/api/database-sources/benchmark-yelp/queries', json={'statement': statement, 'dataset_id': 'ldbc-snb'})
    assert response.status_code == 404 and len(calls) == before


def test_configured_credentials_stay_private_and_are_read_from_trusted_file(workspace, tmp_path, monkeypatch):
    settings = curated(workspace, tmp_path)
    path = tmp_path / 'credentials.env'
    demo = json.loads(workspace.config.read_text())[0]
    demo.update(sql_type='postgres', sqlite_path=None, sql_dsn_env='DEMO_DSN', neo4j_password_env='DEMO_NEO_PASSWORD')
    workspace.config.write_text(json.dumps([demo]))
    path.write_text("DEMO_NEO_PASSWORD='literal $(not-a-command)'\nDEMO_DSN='postgresql://reader:private-secret@localhost:55432/demo'\n")
    path.chmod(0o600)
    settings = replace(settings, database_credentials_file=path)
    source = get_source(settings, 'local-transfers')
    monkeypatch.setenv('DEMO_NEO_PASSWORD', 'wrong-environment-secret')
    assert source_secret(source, 'DEMO_NEO_PASSWORD') == 'literal $(not-a-command)'
    public = source.public()
    assert public['connection']['sql']['username'] == 'reader'
    assert 'private-secret' not in json.dumps(public) and 'not-a-command' not in json.dumps(source.model_dump())
    path.chmod(0o644)
    with pytest.raises(AnalyticsError):
        source_secret(source, 'DEMO_NEO_PASSWORD')


def test_curated_settings_from_environment(settings, monkeypatch, tmp_path):
    monkeypatch.setenv('GRAPHMINE_DATABASE_DATASET_ALLOWLIST', ','.join(CHOICES))
    monkeypatch.setenv('GRAPHMINE_DATABASE_CREDENTIALS_FILE', str(tmp_path / 'demo.env'))
    result = Settings.from_env(settings.repository_root)
    assert result.database_dataset_allowlist == CHOICES
    assert result.database_credentials_file == tmp_path / 'demo.env'
