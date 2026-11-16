"""Neo4j queries and shared import discovery do not depend on SQL availability."""

import json
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from neo4j import Record

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.database import RecordNotFound
from graphmine_agent.database_connections import ConnectionPair, check_connection, delete_pair, owner_directory, save_pair
from graphmine_agent.database_datasets import datasets, selected_dataset
from graphmine_agent.database_queries import execute_query
from graphmine_agent.database_sources import DatabaseSource, get_source, sql_connection
from graphmine_agent.database_sync import sync_source
from graphmine_agent.neo4j_schema import sample_schema
from test_connectors import sources  # noqa: F401
from test_database_connections import connected, pair  # noqa: F401
from test_database_query_projection import read_transaction
from test_database_workspace import driver_path, source, workspace  # noqa: F401


def neo_body(**values):
    return ConnectionPair(name='Graph only', neo4j_uri='neo4j+s://graph.example.com', neo4j_password='graph-private', **values)


def graph_source():
    return DatabaseSource(id='graph', name='Graph only', users=['*'], neo4j_uri='neo4j+s://graph.example.com', neo4j_password_env='GRAPH_PRIVATE')


def test_neo4j_without_sql_can_be_saved_reopened_renamed_and_removed(settings, connected, monkeypatch):
    settings = replace(settings, database_sources_file=None)
    endpoints = []
    monkeypatch.setattr('graphmine_agent.database_connections.network_address', lambda _, host, port: endpoints.append((host, port)))
    saved = save_pair(settings, neo_body())
    assert endpoints == [('graph.example.com', 7687)]
    assert saved['managed'] and saved['sql_type'] is None and saved['connection']['sql'] is None
    assert saved['capabilities'] == {'cypher': True, 'sql': False, 'enrichment': False, 'expansion': False, 'sync': False}
    source = get_source(settings, saved['id'])
    assert not source._sql_credentials and source._neo4j_password == 'graph-private'
    path = owner_directory(settings) / (source.id + '.json')
    assert json.loads(path.read_text())['sql'] == {} and path.stat().st_mode & 0o077 == 0
    body = ConnectionPair(name='Renamed graph', neo4j_uri=source.neo4j_uri)
    renamed = save_pair(settings, body, source.id)
    assert renamed['mapping_hash'] == saved['mapping_hash']
    assert 'private' not in json.dumps(renamed)
    delete_pair(settings, source.id); assert not path.exists()


def test_attach_and_remove_sql_retains_graph_credentials_and_rotates_lineage(settings, pair, connected):
    settings = replace(settings, database_sources_file=None)
    saved = save_pair(settings, neo_body())
    attached = save_pair(settings, pair.model_copy(update={'neo4j_password': None}), saved['id'])
    assert attached['revision'] == 2 and attached['capabilities']['sql']
    assert get_source(settings, saved['id'])._neo4j_password == 'graph-private'
    detached = save_pair(settings, ConnectionPair(name='Graph only', neo4j_uri=pair.neo4j_uri, sql_enabled=False), saved['id'])
    assert detached['revision'] == 3 and not detached['capabilities']['sql']
    private = json.loads((owner_directory(settings) / (saved['id'] + '.json')).read_text())
    assert private['sql'] == {} and 'sql-test-secret' not in json.dumps(private)
    with pytest.raises(AnalyticsError, match='entered again'):
        save_pair(settings, pair.model_copy(update={'password': None, 'neo4j_password': None}), saved['id'])


@pytest.mark.parametrize('values', [{'host': 'server'}, {'sql_enabled': True}, {'sql_enabled': False, 'password': 'must-not-be-retained'},
                                  {'entities': [{'id': 'people', 'table': 'people', 'key': ['id'], 'label': 'Person'}]}])
def test_incomplete_or_disabled_sql_details_are_rejected(values):
    with pytest.raises(ValueError):
        neo_body(**values)


def test_health_and_default_selection_skip_sql_and_report_optional_outage(settings, monkeypatch):
    source = graph_source(); calls = []
    @contextmanager
    def neo(_):
        yield SimpleNamespace(run=lambda _: SimpleNamespace(consume=lambda: None))
    def unavailable(*_):
        calls.append(1); raise OSError('private SQL credential')
    monkeypatch.setattr('graphmine_agent.database_connections.neo4j_session', neo)
    monkeypatch.setattr('graphmine_agent.database_connections.sql_connection', unavailable)
    monkeypatch.setattr('graphmine_agent.database_sources.sql_connection', unavailable)
    health = check_connection(source)
    assert health['connected'] and health['query_available'] and not health['enrichment_available']
    assert health['sql']['configured'] is False and health['sql']['connected'] is None and not calls
    assert datasets(settings, source)[0]['id'] == 'default' and not calls
    for function in (lambda: sync_source(source), lambda: sql_connection(source).__enter__()):
        with pytest.raises(AnalyticsError) as error:
            function()
        assert error.value.code == 'sql_unavailable'
    source = DatabaseSource.model_validate({**source.model_dump(), 'sql_type': 'postgres', 'sql_dsn_env': 'SQL_PRIVATE'})
    assert selected_dataset(settings, source, 'default')['status'] == 'ready' and not calls
    health = check_connection(source)
    assert not health['connected'] and health['query_available']
    entries = datasets(settings, source)
    assert entries[0]['status'] == 'ready' and 'discovery_warning' not in entries[0]
    assert 'private SQL' not in json.dumps(entries)
    with pytest.raises(RecordNotFound):
        selected_dataset(settings, source, 'missing-catalog')


def test_actual_query_projection_and_chat_work_without_sql(workspace, source, monkeypatch):
    graph_only = DatabaseSource.model_validate({**source.model_dump(), 'sql_type': None, 'sql_dsn_env': None, 'sqlite_path': None, 'entities': [], 'relationships': []})
    workspace.config.write_text(json.dumps([graph_only.model_dump()]))
    path = driver_path(source)
    for item in [*path.nodes, *path.relationships]:
        for key in list(item._properties):
            if key.startswith('gm_'):
                del item._properties[key]
    read_transaction(monkeypatch, [Record({'p': path})])
    monkeypatch.setattr('graphmine_agent.database_queries.execute_query', execute_query)
    def forbidden(*_):
        raise AssertionError('A direct Neo4j query must never open SQL')
    monkeypatch.setattr('graphmine_agent.database_sources.sql_connection', forbidden)
    monkeypatch.setattr('graphmine_agent.database_enrichment.sql_connection', forbidden)
    response = workspace.client.post('/api/database-sources/demo/queries', json={'statement': 'MATCH p=()-[]->() RETURN p', 'dataset_id': 'default'})
    assert response.status_code == 201, response.text
    snapshot = response.json()['dataset']
    assert snapshot['source']['database_source']['capabilities']['sql'] is False
    opened = workspace.client.post(f"/api/database-query-snapshots/{snapshot['id']}/chat", json={})
    assert opened.status_code == 201, opened.text
    file = opened.json()['file']
    graph = workspace.runtime.graph_store.read_graph(file['id'], opened.json()['session']['id'])
    assert len(graph['vertices']) == 2 and len(graph['edges']) == 1
    enriched = workspace.client.post(f"/api/files/{file['id']}/enrichments", json={'mapping': 'accounts', 'fields': ['risk']})
    assert enriched.status_code == 409 and enriched.json()['error']['code'] == 'sql_unavailable'


def test_sync_without_sql_is_rejected_before_queue_admission(workspace):
    workspace.config.write_text(json.dumps([{**graph_source().model_dump(), 'id': 'demo'}]))
    before = workspace.client.get('/api/database-jobs').json()
    response = workspace.client.post('/api/database-sources/demo/sync', headers={'Prefer': 'respond-async'})
    assert response.status_code == 409 and response.json()['error']['code'] == 'sql_unavailable'
    assert workspace.client.get('/api/database-jobs').json() == before


def test_inventory_unifies_owned_sources_without_fetching_or_leaking_configuration(sources, monkeypatch, tmp_path):
    client, runtime, alice, bob, _, _, database = sources
    config = tmp_path / 'neo.json'
    config.write_text(json.dumps([{**graph_source().model_dump(), 'id': 'ledger', 'users': ['alice']}]))
    config.chmod(0o600)
    runtime.settings = replace(runtime.settings, database_sources_file=config)
    def forbidden(*_):
        raise AssertionError('Discovery must read metadata only')
    monkeypatch.setattr('graphmine_agent.connectors.fetch', forbidden)
    response = client.get('/api/data-sources', headers=alice)
    assert response.status_code == 200
    value = response.json()
    assert {item['id'] for item in value['items']} == {'database:ledger', 'connector:ledger'}
    assert value['can_manage_imports'] and not value['warnings']
    assert str(database) not in response.text and 'GRAPH_PRIVATE' not in response.text
    assert client.get('/api/data-sources', headers=bob).json()['items'] == []
    assert client.get('/api/data-sources').status_code == 401
    config.chmod(0o644)
    partial = client.get('/api/data-sources', headers=alice).json()
    assert [item['id'] for item in partial['items']] == ['connector:ledger']
    assert partial['warnings'][0]['provider'] == 'database'


def test_saved_connector_graph_can_start_a_conversation_after_source_removal(sources):
    client, runtime, alice, bob, config, _, _ = sources
    checked = client.post('/api/connectors/ledger/preview', headers=alice).json()
    saved = client.post('/api/connectors/ledger/import', headers=alice, json={'name': 'Retained graph', 'expected_sha256': checked['sha256']}).json()
    config.write_text('[]')
    route = f"/api/datasets/{saved['id']}/chat"
    assert client.post(route, headers=bob, json={}).status_code == 404
    assert client.post(route, headers=alice, json={'domain_id': 'absent'}).status_code == 422
    response = client.post(route, headers=alice, json={})
    assert response.status_code == 201, response.text
    value = response.json()
    assert value['session']['title'] == 'Retained graph'
    graph = runtime.graph_store.read_graph(value['file']['id'], value['session']['id'])
    assert [vertex['id'] for vertex in graph['vertices']] == ['001', '1', 1, 9007199254740993]
    assert value['file']['provenance']['source']['connector_id'] == 'ledger'


def test_dataset_chat_rolls_back_new_conversation_after_partial_import(sources, monkeypatch):
    from graphmine_agent.datasets import DatasetLibrary

    client, runtime, alice, _, _, _, _ = sources
    preview = client.post('/api/connectors/ledger/preview', headers=alice).json()
    saved = client.post('/api/connectors/ledger/import', headers=alice, json={'name': 'Graph', 'expected_sha256': preview['sha256']}).json()
    before = client.get('/api/sessions', headers=alice).json()
    original = DatasetLibrary.import_into
    created = []
    def interrupted(self, version_id, session_id):
        original(self, version_id, session_id)
        created.append(session_id)
        raise AnalyticsError('Import interrupted', 'test_interruption', 503)
    monkeypatch.setattr(DatasetLibrary, 'import_into', interrupted)
    response = client.post(f"/api/datasets/{saved['id']}/chat", headers=alice, json={})
    assert response.status_code == 503
    assert client.get('/api/sessions', headers=alice).json() == before and len(created) == 1
    assert not (runtime.settings.data_root / 'sessions' / created[0]).exists()
    assert client.get('/api/datasets', headers=alice).json()[0]['id'] == saved['id']


@pytest.mark.parametrize('method', ['post', 'put'])
def test_connection_validation_does_not_echo_credentials(sources, method):
    client, _, alice, _, _, _, _ = sources
    secret = 'never-return-this-token-' * 250
    path = '/api/connectors' + ('/absent' if method == 'put' else '')
    response = getattr(client, method)(path, headers=alice, json={'name': 'API', 'type': 'rest', 'url': 'https://example.com', 'bearer_token': secret})
    assert response.status_code == 422 and response.json()['error']['code'] == 'connector_settings'
    assert 'never-return-this-token' not in response.text and 'input' not in response.json()['error']


def test_neo4j_schema_is_bounded_read_only_and_excludes_private_properties(monkeypatch):
    source = graph_source(); calls = []; rolled_back = []
    class Transaction:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def run(self, statement, params):
            calls.append((statement, params))
            return [{'labels': ['Person`X'], 'properties': ['name', 'odd`property', 'gm_private']}] if statement.startswith('MATCH (n)') else [
                {'source_labels': ['Person`X'], 'target_labels': ['Person`X'], 'relationship': 'KNOWS', 'properties': ['weight']}]
        def rollback(self): rolled_back.append(True)
    @contextmanager
    def session(_):
        yield SimpleNamespace(begin_transaction=lambda **_: Transaction())
    monkeypatch.setattr('graphmine_agent.neo4j_schema.neo4j_session', session)
    schema = {**sample_schema(source), 'source_id': source.id, 'dataset_id': 'default', 'graph_label': None, 'max_rows': source.max_rows}
    assert len(calls) == 2 and all(params == {'limit': 500} for _, params in calls) and rolled_back
    assert schema['schema_scope']['complete'] is False and 'bounded' in schema['message']
    assert 'gm_private' not in str(schema)
    assert schema['entities'][0]['label'] == 'Person`X'
    assert 'odd`property' in {item['name'] for item in schema['entities'][0]['properties']}



@pytest.mark.parametrize('failure', ['node_rows', 'relationship_rows', 'bytes', 'driver'])
def test_schema_discovery_limits_and_failures_do_not_return_partial_choices(monkeypatch, failure):
    source = graph_source().model_copy(update={'max_rows': 1, 'max_bytes': 1024})
    closed = []
    class Transaction:
        def __enter__(self): return self
        def __exit__(self, kind, *_): closed.append(kind)
        def run(self, statement, params):
            if failure == 'driver': raise OSError('private database credential')
            if statement.startswith('MATCH (n)'):
                row = {'labels': ['Person'], 'properties': ['private' * 200] if failure == 'bytes' else ['name']}
                return [row] * (2 if failure == 'node_rows' else 1)
            row = {'source_labels': ['Person'], 'target_labels': ['Person'], 'relationship': 'KNOWS', 'properties': []}
            return [row] * (2 if failure == 'relationship_rows' else 1)
        def rollback(self): pass
    @contextmanager
    def session(_):
        yield SimpleNamespace(begin_transaction=lambda **_: Transaction())
    monkeypatch.setattr('graphmine_agent.neo4j_schema.neo4j_session', session)
    with pytest.raises(AnalyticsError) as error:
        sample_schema(source)
    assert error.value.code == ('database_schema' if failure == 'driver' else 'resource_limit')
    assert 'private' not in str(error.value) and closed and closed[0] is not None
