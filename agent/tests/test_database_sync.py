"""Keyed changes, bounded comparison and durable synchronization contracts."""

import json
import asyncio
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

import pytest

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.database_reconciliation import change_summary, plan_changes, read_state
from graphmine_agent.database_sources import sql_connection
from graphmine_agent.database_jobs import DatabaseJobs
from graphmine_agent.database_sync import mapped_records, sync_source
from test_database_workspace import source, workspace  # noqa: F401
from test_database_jobs import wait_job


def records(source, build='first'):
    with sql_connection(source) as db:
        return mapped_records(source, db, build)


def stored(nodes, edges):
    old_nodes = {row['properties']['gm_id']: {'element_id': f'n{index}', 'labels': ['GraphMineEntity', row['label']],
                 'properties': dict(reversed(list(row['properties'].items())))} for index, row in enumerate(nodes)}
    old_edges = {row['properties']['gm_id']: {'element_id': f'r{index}', 'source': row['source'], 'target': row['target'], 'type': row['type'],
                 'source_owner': row['properties']['gm_source'], 'target_owner': row['properties']['gm_source'],
                 'properties': dict(reversed(list(row['properties'].items())))} for index, row in enumerate(edges)}
    return old_nodes, old_edges


def test_unchanged_snapshot_has_no_writes_despite_property_order_and_new_read_time(source):
    previous = stored(*records(source)); original = deepcopy(previous)
    changes = plan_changes(source, *records(source, 'later'), *previous)
    summary = change_summary(source, changes, *previous)
    assert summary['changes'] == {'nodes': {'created': 0, 'updated': 0, 'deleted': 0, 'unchanged': 3},
                                  'relationships': {'created': 0, 'updated': 0, 'deleted': 0, 'unchanged': 2, 'recreated': 0}}
    assert not summary['schema_change']['changed'] and previous == original


def test_keyed_update_insert_delete_and_rewire_are_counted_independently(source):
    previous = stored(*records(source))
    with sqlite3.connect(source.sqlite_path) as db:
        db.executescript("UPDATE accounts SET name='Ada Lovelace' WHERE id=1; DELETE FROM accounts WHERE id=3; INSERT INTO accounts VALUES(4,'Dan',1,'US'); DELETE FROM transfers WHERE id=12; UPDATE transfers SET receiver=4,amount=15 WHERE id=11; INSERT INTO transfers VALUES(13,4,2,5,'new');")
    changes = plan_changes(source, *records(source, 'later'), *previous)
    summary = change_summary(source, changes, *previous)
    assert summary['changes'] == {'nodes': {'created': 1, 'updated': 1, 'deleted': 1, 'unchanged': 1},
                                  'relationships': {'created': 1, 'updated': 1, 'deleted': 1, 'unchanged': 0, 'recreated': 1}}
    assert changes['nodes']['updated'][0]['properties']['name'] == 'Ada Lovelace'
    assert not summary['schema_change']['changed']


def test_mapping_migration_removes_owned_fields_and_label_but_keeps_annotations(source):
    previous = stored(*records(source))
    for node in previous[0].values():
        node['properties']['analyst_note'] = 'Keep this'
        node['labels'].append('Reviewed')
    mapping = source.entities[0].model_copy(update={'label': 'Customer', 'graph_attributes': ['country']})
    revised = source.model_copy(update={'revision': 2, 'entities': [mapping]})
    changes = plan_changes(revised, *records(revised, 'later'), *previous)
    summary = change_summary(revised, changes, *previous)
    assert summary['schema_change']['changed'] and summary['schema_change']['previous_hashes'] == [source.fingerprint()]
    assert summary['changes']['nodes']['updated'] == 3
    for row in changes['nodes']['updated']:
        assert row['remove_label'] == 'Account' and row['label'] == 'Customer'
        assert row['properties']['analyst_note'] == 'Keep this' and 'name' not in row['properties'] and 'country' in row['properties']


def test_type_changes_are_not_hidden_by_python_numeric_equality(source):
    nodes, edges = records(source); previous = stored(nodes, edges)
    previous[0][nodes[0]['properties']['gm_id']]['properties']['name'] = True
    nodes[0]['properties']['name'] = 1
    changes = plan_changes(source, nodes, edges, *previous)
    assert len(changes['nodes']['updated']) == 1


@pytest.mark.parametrize('mode', ['rows', 'bytes', 'duplicates', 'foreign_endpoint'])
def test_existing_graph_read_fails_closed_instead_of_inferring_deletions(source, mode):
    previous = stored(*records(source)); nodes, edges = map(lambda rows: list(rows.values()), previous)
    if mode == 'duplicates': nodes.append(deepcopy(nodes[0]))
    if mode == 'foreign_endpoint': edges[0]['source_owner'] = 'another-source'
    class Transaction:
        def run(self, query, **_): return iter(nodes if query.startswith('MATCH (n:') else edges)
    with pytest.raises(AnalyticsError) as error:
        read_state(Transaction(), source.model_copy(update={'max_rows': 2}) if mode == 'rows' else source, 1 if mode == 'bytes' else source.max_bytes)
    assert error.value.code == ('resource_limit' if mode in {'rows', 'bytes'} else 'database_sync_conflict')


@pytest.mark.parametrize('column', ['name', 'risk'])
def test_missing_sql_column_fails_before_opening_neo4j(source, monkeypatch, column):
    with sqlite3.connect(source.sqlite_path) as db:
        db.execute(f'ALTER TABLE accounts RENAME COLUMN {column} TO renamed')
    def forbidden(*_, **__): raise AssertionError('Graph must remain untouched after SQL schema failure')
    monkeypatch.setattr('graphmine_agent.database_sync.neo4j_session', forbidden)
    with pytest.raises(AnalyticsError) as error:
        sync_source(source)
    assert error.value.code == 'database_schema' and error.value.status == 409


def test_sync_without_mappings_is_rejected_before_queue_or_graph_changes(workspace, source):
    source = source.model_copy(update={'entities': [], 'relationships': []})
    workspace.config.write_text(json.dumps([source.model_dump()]))
    response = workspace.client.post('/api/database-sources/demo/sync')
    assert response.status_code == 409 and response.json()['error']['code'] == 'database_mapping'
    assert not workspace.client.get('/api/database-jobs?kind=sync').json()['items']


def test_synchronous_sync_has_private_durable_filterable_idempotent_history(workspace, monkeypatch):
    summary = {'source_id': 'demo', 'nodes': 3, 'relationships': 2, 'changes': {'nodes': {'created': 1, 'updated': 1, 'deleted': 0, 'unchanged': 1}},
               'schema_change': {'changed': False}, 'mapped_content_sha256': 'a'*64}
    calls = []
    def synchronize(*_): calls.append(True); return summary
    monkeypatch.setattr('graphmine_agent.database_sync.sync_source', synchronize)
    response = workspace.client.post('/api/database-sources/demo/sync', headers={'Idempotency-Key': 'synchronous-sync'})
    assert response.status_code == 200, response.text
    saved = response.json(); assert saved['changes'] == summary['changes'] and saved['job_id']
    assert 'no-store' in response.headers['cache-control']
    assert workspace.client.post('/api/database-sources/demo/sync', headers={'Idempotency-Key': 'synchronous-sync'}).json() == saved
    assert len(calls) == 1
    history = workspace.client.get('/api/database-jobs?kind=sync&source_id=demo').json()['items']
    assert len(history) == 1 and history[0]['synchronization'] == summary
    assert 'owner_id' not in history[0] and 'source_fingerprint' not in history[0]
    assert DatabaseJobs(workspace.runtime).get(saved['job_id'])['synchronization'] == summary
    assert not workspace.client.get('/api/database-jobs?kind=query').json()['items']
    assert workspace.client.get('/api/database-jobs?kind=invalid').status_code == 422


def test_sync_failure_survives_synchronous_response_and_history(workspace, monkeypatch):
    def synchronize(*_): raise AnalyticsError('Review the changed table mapping.', 'database_schema', 409)
    monkeypatch.setattr('graphmine_agent.database_sync.sync_source', synchronize)
    response = workspace.client.post('/api/database-sources/demo/sync')
    assert response.status_code == 409 and response.json()['error']['code'] == 'database_schema'
    history = workspace.client.get('/api/database-jobs?kind=sync').json()['items']
    assert history[0]['status'] == 'failed' and history[0]['error']['code'] == 'database_schema'
    assert response.json()['error']['details']['job_id'] == history[0]['id']


def test_sync_request_without_async_preference_serializes_with_existing_background_work(workspace, monkeypatch):
    started, release = Event(), Event(); calls = []
    def synchronize(*_):
        calls.append(len(calls) + 1)
        if len(calls) == 1: started.set(); assert release.wait(8)
        return {'nodes': 3, 'relationships': 2}
    monkeypatch.setattr('graphmine_agent.database_sync.sync_source', synchronize)
    first = workspace.client.post('/api/database-sources/demo/sync', headers={'Prefer': 'respond-async'}).json()['job']
    assert started.wait(3)
    with ThreadPoolExecutor(max_workers=1) as executor:
        second = executor.submit(workspace.client.post, '/api/database-sources/demo/sync')
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                history = workspace.client.get('/api/database-jobs?kind=sync').json()['items']
                if len(history) == 2: break
                time.sleep(0.01)
            assert sorted(row['status'] for row in history) == ['queued', 'running'] and calls == [1]
        finally: release.set()
        assert second.result(timeout=5).status_code == 200
    assert wait_job(workspace.client, first['id'])['status'] == 'completed' and calls == [1, 2]


def test_cancelling_a_synchronous_waiter_does_not_cancel_durable_sync(workspace, monkeypatch):
    started, release = Event(), Event()
    def synchronize(*_):
        started.set(); assert release.wait(8); return {'nodes': 3, 'relationships': 2}
    monkeypatch.setattr('graphmine_agent.database_sync.sync_source', synchronize)
    identifier = workspace.client.post('/api/database-sources/demo/sync', headers={'Prefer': 'respond-async'}).json()['job']['id']
    assert started.wait(3)
    async def abandon():
        waiting = asyncio.create_task(workspace.runtime.database_jobs.wait(identifier))
        await asyncio.sleep(0.02); waiting.cancel()
        with pytest.raises(asyncio.CancelledError): await waiting
    try:
        asyncio.run(abandon())
        assert workspace.client.get(f'/api/database-jobs/{identifier}').json()['status'] == 'running'
    finally: release.set()
    assert wait_job(workspace.client, identifier)['status'] == 'completed'
