"""Opt-in reconciliation against disposable localhost Neo4j, without native jobs.

Set GRAPHMINE_TEST_SYNC_NEO4J=1 and GRAPHMINE_TEST_SYNC_NEO4J_URI for an isolated
server, or enable the existing disposable database integration environment.
Only random test-owned source records and fixture annotations are removed.
"""

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from neo4j import GraphDatabase

from graphmine_agent import database_sync
from graphmine_agent import database_reconciliation
from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.api import create_app
from graphmine_agent.config import Settings
from graphmine_agent.database_job_context import current_database_job
from graphmine_agent.database_jobs import WorkStopped
from graphmine_agent.database_sources import configured, secret
from graphmine_agent.datasets import DatasetLibrary
from test_database_workspace import source  # noqa: F401

pytestmark = pytest.mark.skipif(os.getenv('GRAPHMINE_TEST_SYNC_NEO4J') != '1' and os.getenv('GRAPHMINE_TEST_DATABASE_INTEGRATION') != '1', reason='requires explicit disposable Neo4j integration')


@pytest.fixture
def live_sync(source, monkeypatch):
    uri = os.getenv('GRAPHMINE_TEST_SYNC_NEO4J_URI')
    source.id = 'sync-test-' + uuid.uuid4().hex
    if uri:
        source.neo4j_uri = uri
        monkeypatch.setenv('TEST_NEO4J_PASSWORD', os.getenv('GRAPHMINE_TEST_SYNC_NEO4J_PASSWORD', 'isolated-test-only'))
    else:
        demo = next(item for item in configured(Settings.from_env()) if item.id == 'local-transfers')
        source.neo4j_uri, source.neo4j_database = demo.neo4j_uri, demo.neo4j_database
        source.neo4j_username = demo.neo4j_writer_username or demo.neo4j_username
        source.neo4j_password_env = demo.neo4j_writer_password_env or demo.neo4j_password_env
    assert urlsplit(source.neo4j_uri).hostname in {'127.0.0.1', 'localhost', '::1'}, 'Use a disposable localhost Neo4j instance'
    driver = GraphDatabase.driver(source.neo4j_uri, auth=(source.neo4j_username, secret(source.neo4j_password_env)))
    driver.verify_connectivity()
    observed = []
    original = database_sync.neo4j_session

    class Result:
        def __init__(self, result, statement): self.result, self.statement = result, statement
        def consume(self):
            summary = self.result.consume(); observed.append((self.statement, summary.counters)); return summary
        def single(self):
            value = self.result.single(); self.consume(); return value
        def __iter__(self):
            yield from self.result; self.consume()
    class Transaction:
        def __init__(self, tx): self.tx = tx
        def run(self, statement, **params): return Result(self.tx.run(statement, **params), statement)
        def commit(self): return self.tx.commit()
        def __enter__(self): self.tx.__enter__(); return self
        def __exit__(self, *args): return self.tx.__exit__(*args)
    class Session:
        def __init__(self, session): self.session = session
        def run(self, statement, **params): return Result(self.session.run(statement, **params), statement)
        def begin_transaction(self, **params): return Transaction(self.session.begin_transaction(**params))
    @contextmanager
    def observe(*args, **kwargs):
        with original(*args, **kwargs) as session: yield Session(session)
    monkeypatch.setattr(database_sync, 'neo4j_session', observe)

    def execute(statement, **params):
        with driver.session(database=source.neo4j_database) as session:
            return session.run(statement, **params).data()
    def state():
        return {'nodes': execute('MATCH (n:GraphMineEntity {gm_source:$source}) RETURN elementId(n) AS element_id, labels(n) AS labels, properties(n) AS properties ORDER BY n.gm_id', source=source.id),
                'edges': execute('MATCH (a)-[r]->(b) WHERE r.gm_source=$source RETURN elementId(r) AS element_id, type(r) AS type, properties(r) AS properties, a.gm_id AS source, b.gm_id AS target ORDER BY r.gm_id', source=source.id)}
    try:
        yield SimpleNamespace(source=source, observed=observed, execute=execute, state=state)
    finally:
        execute('MATCH (n) WHERE n.gm_source=$source OR n.gm_fixture=$source DETACH DELETE n', source=source.id)
        driver.close()


def test_real_incremental_writes_keep_keys_and_leave_unchanged_records_untouched(live_sync):
    f = live_sync; first = database_sync.sync_source(f.source); before = f.state(); f.observed.clear()
    second = database_sync.sync_source(f.source)
    assert first['changes']['nodes']['created'] == 3 and first['changes']['relationships']['created'] == 2
    assert second['changes']['nodes']['unchanged'] == 3 and second['changes']['relationships']['unchanged'] == 2
    assert second['mapped_content_sha256'] == first['mapped_content_sha256'] and f.state() == before
    assert all(not counters.contains_updates for _, counters in f.observed)
    with sqlite3.connect(f.source.sqlite_path) as db:
        db.executescript("UPDATE accounts SET name='Ada Lovelace' WHERE id=1; DELETE FROM accounts WHERE id=3; INSERT INTO accounts VALUES(4,'Dan',1,'US'); DELETE FROM transfers WHERE id=12; UPDATE transfers SET receiver=4,amount=15 WHERE id=11; INSERT INTO transfers VALUES(13,4,2,5,'new');")
    changed = database_sync.sync_source(f.source); after = f.state()
    assert changed['changes'] == {'nodes': {'created': 1, 'updated': 1, 'deleted': 1, 'unchanged': 1}, 'relationships': {'created': 1, 'updated': 1, 'deleted': 1, 'unchanged': 0, 'recreated': 1}}
    original = {row['properties']['gm_key']: row for row in before['nodes']}
    current = {row['properties']['gm_key']: row for row in after['nodes']}
    assert current['[1]']['element_id'] == original['[1]']['element_id']
    assert current['[2]'] == original['[2]'] and set(current) == {'[1]', '[2]', '[4]'}
    assert current['[1]']['properties']['gm_build'] == changed['build']
    assert all('DETACH DELETE' not in statement for statement, _ in f.observed)


def test_real_mapping_migration_removes_obsolete_fields_labels_and_relationship_types(live_sync):
    f = live_sync; database_sync.sync_source(f.source)
    f.execute("MATCH (n:GraphMineEntity {gm_source:$source}) SET n.analyst_note='retained', n:Reviewed", source=f.source.id)
    entity = f.source.entities[0].model_copy(update={'label': 'Customer', 'graph_attributes': ['country']})
    relationship = f.source.relationships[0].model_copy(update={'label': 'SENDS'})
    revised = f.source.model_copy(update={'revision': 2, 'entities': [entity], 'relationships': [relationship]})
    result = database_sync.sync_source(revised)
    assert result['schema_change']['changed'] and result['changes']['nodes']['updated'] == 3
    assert result['changes']['relationships']['recreated'] == 2
    state = f.state()
    for row in state['nodes']:
        assert set(row['labels']) == {'GraphMineEntity', 'Customer', 'Reviewed'}
        assert 'name' not in row['properties'] and row['properties']['analyst_note'] == 'retained'
    assert all(row['type'] == 'SENDS' for row in state['edges'])
    f.observed.clear(); database_sync.sync_source(revised)
    assert all(not counters.contains_updates for _, counters in f.observed)


def test_real_null_values_remove_previously_copied_properties(live_sync):
    f = live_sync; database_sync.sync_source(f.source)
    with sqlite3.connect(f.source.sqlite_path) as db:
        db.execute('UPDATE accounts SET name=NULL WHERE id=1')
        db.execute('UPDATE transfers SET amount=NULL WHERE id=11')
    result = database_sync.sync_source(f.source)
    assert result['changes']['nodes']['updated'] == result['changes']['relationships']['updated'] == 1
    state = f.state()
    assert 'name' not in next(row['properties'] for row in state['nodes'] if row['properties']['gm_key'] == '[1]')
    edge = next(row['properties'] for row in state['edges'] if row['properties']['gm_key'] == '[11]')
    assert 'amount' not in edge and 'gm_weight' not in edge
    assert database_sync.sync_source(f.source)['changes']['relationships']['unchanged'] == 2


@pytest.mark.parametrize('invalid', ['column', 'endpoint', 'read_budget'])
def test_real_invalid_source_and_incomplete_comparison_leave_previous_graph_intact(live_sync, invalid):
    f = live_sync; database_sync.sync_source(f.source); before = f.state()
    with sqlite3.connect(f.source.sqlite_path) as db:
        if invalid == 'column': db.execute('ALTER TABLE accounts RENAME COLUMN name TO absent')
        elif invalid == 'endpoint': db.execute('UPDATE transfers SET receiver=999 WHERE id=11')
        else: db.executescript('DELETE FROM transfers; DELETE FROM accounts;')
    source = f.source.model_copy(update={'max_rows': 1}) if invalid == 'read_budget' else f.source
    with pytest.raises(AnalyticsError) as error: database_sync.sync_source(source)
    assert error.value.code == {'column': 'database_schema', 'endpoint': 'database_mapping', 'read_budget': 'resource_limit'}[invalid]
    assert f.state() == before


def test_real_node_deletion_preserves_foreign_relationships_by_rolling_back(live_sync):
    f = live_sync; database_sync.sync_source(f.source)
    f.execute("MATCH (n:GraphMineEntity {gm_source:$source, gm_key:'[3]'}) CREATE (o:FixtureOutside {gm_fixture:$source}) CREATE (o)-[:ANNOTATES]->(n)", source=f.source.id)
    before = f.state()
    with sqlite3.connect(f.source.sqlite_path) as db: db.executescript('DELETE FROM transfers WHERE id=12; DELETE FROM accounts WHERE id=3;')
    with pytest.raises(AnalyticsError) as error: database_sync.sync_source(f.source)
    assert error.value.code == 'database_sync_conflict' and f.state() == before
    assert f.execute('MATCH (o:FixtureOutside {gm_fixture:$source})-[r]->() RETURN count(r) AS total', source=f.source.id)[0]['total'] == 1


def test_real_empty_source_removes_only_its_own_managed_graph(live_sync):
    f = live_sync; database_sync.sync_source(f.source)
    f.execute('CREATE (n:GraphMineEntity {gm_source:$other, gm_id:$other, gm_fixture:$source, note:"keep"})', source=f.source.id, other=f.source.id+'-other')
    with sqlite3.connect(f.source.sqlite_path) as db: db.executescript('DELETE FROM transfers; DELETE FROM accounts;')
    result = database_sync.sync_source(f.source)
    assert result['changes']['nodes']['deleted'] == 3 and result['changes']['relationships']['deleted'] == 2
    assert f.state() == {'nodes': [], 'edges': []}
    assert f.execute('MATCH (n {gm_fixture:$source}) RETURN n.note AS note', source=f.source.id) == [{'note': 'keep'}]


def test_real_legacy_records_gain_property_ownership_without_changing_ids(live_sync):
    f = live_sync; database_sync.sync_source(f.source)
    f.execute('MATCH (n:GraphMineEntity {gm_source:$source}) REMOVE n.gm_fields,n.gm_label', source=f.source.id)
    f.execute('MATCH ()-[r]->() WHERE r.gm_source=$source REMOVE r.gm_fields,r.gm_label', source=f.source.id)
    before = f.state(); result = database_sync.sync_source(f.source); after = f.state()
    assert result['changes']['nodes']['updated'] == 3 and result['changes']['relationships']['updated'] == 2
    assert [row['element_id'] for row in before['nodes']] == [row['element_id'] for row in after['nodes']]
    assert [row['element_id'] for row in before['edges']] == [row['element_id'] for row in after['edges']]
    assert database_sync.sync_source(f.source)['changes']['nodes']['unchanged'] == 3


def test_real_concurrent_graph_edit_is_not_overwritten(live_sync, monkeypatch):
    f = live_sync; database_sync.sync_source(f.source)
    with sqlite3.connect(f.source.sqlite_path) as db: db.execute("UPDATE accounts SET name='SQL change' WHERE id=1")
    original = database_reconciliation.plan_changes
    def changed(*args):
        f.execute("MATCH (n:GraphMineEntity {gm_source:$source, gm_key:'[1]'}) SET n.name='Concurrent graph edit'", source=f.source.id)
        return original(*args)
    monkeypatch.setattr(database_reconciliation, 'plan_changes', changed)
    with pytest.raises(AnalyticsError) as error: database_sync.sync_source(f.source)
    assert error.value.code == 'database_sync_conflict'
    assert next(row['properties']['name'] for row in f.state()['nodes'] if row['properties']['gm_key'] == '[1]') == 'Concurrent graph edit'


def test_real_cancellation_after_writes_rolls_back_every_change(live_sync):
    f = live_sync; database_sync.sync_source(f.source); before = f.state(); f.observed.clear()
    with sqlite3.connect(f.source.sqlite_path) as db: db.execute("UPDATE accounts SET name='Changed' WHERE id=1")
    class Control:
        def checkpoint(self, stage=None, *_):
            if stage == 'writing' and any(counters.contains_updates for _, counters in f.observed): raise WorkStopped()
        def seal(self, _): self.checkpoint('writing')
    token = current_database_job.set(Control())
    try:
        with pytest.raises(WorkStopped): database_sync.sync_source(f.source)
    finally: current_database_job.reset(token)
    assert any(counters.contains_updates for _, counters in f.observed) and f.state() == before


def test_real_synchronization_history_preserves_saved_graphs_across_data_and_mapping_changes(live_sync, settings, tmp_path):
    f = live_sync; config = tmp_path/'sources.json'; config.write_text(json.dumps([f.source.model_dump()])); config.chmod(0o600)
    with TestClient(create_app(replace(settings, database_sources_file=config))) as client:
        client.headers['Authorization'] = 'Bearer test-secret'
        path = '/api/database-sources/' + f.source.id
        first = client.post(path+'/sync'); assert first.status_code == 200, first.text
        query = client.post(path+'/queries', json={'statement': 'MATCH p=(a:GraphMineEntity {gm_source:$source})-[r]->(b) RETURN p', 'parameters': {'source': f.source.id}})
        assert query.status_code == 201, query.text
        identifier = query.json()['dataset']['id']
        assert client.post(f'/api/database-query-snapshots/{identifier}/save').status_code == 200
        library = DatasetLibrary(client.app.state.runtime); metadata, original = library.get(identifier, content=True)
        with sqlite3.connect(f.source.sqlite_path) as db: db.execute("UPDATE accounts SET name='Updated Ada' WHERE id=1")
        second = client.post(path+'/sync'); assert second.status_code == 200, second.text
        assert second.json()['changes']['nodes']['updated'] == 1
        revised = f.source.model_copy(update={'revision': 2, 'entities': [f.source.entities[0].model_copy(update={'label': 'Customer'})]})
        config.write_text(json.dumps([revised.model_dump()]))
        third = client.post(path+'/sync'); assert third.status_code == 200, third.text
        assert third.json()['schema_change']['changed']
        assert library.get(identifier, content=True) == (metadata, original)
        opened = client.post(f'/api/datasets/{identifier}/chat', json={})
        assert opened.status_code == 201, opened.text
        value = opened.json(); graph = client.app.state.runtime.graph_store.read_graph(value['file']['id'], value['session']['id'])
        assert graph == json.loads(original)
        history = client.get('/api/database-jobs', params={'source_id': f.source.id, 'kind': 'sync'}).json()['items']
        assert len(history) == 3 and all(row['status'] == 'completed' and row['synchronization']['mapped_content_sha256'] for row in history)


def test_real_mapping_change_during_sync_rolls_back_before_commit(live_sync, settings, tmp_path, monkeypatch):
    f = live_sync; database_sync.sync_source(f.source); before = f.state()
    config = tmp_path/'sources.json'; config.write_text(json.dumps([f.source.model_dump()])); config.chmod(0o600)
    with sqlite3.connect(f.source.sqlite_path) as db: db.execute("UPDATE accounts SET name='Not committed' WHERE id=1")
    original = database_sync.begin_commit
    def changed():
        config.write_text(json.dumps([f.source.model_copy(update={'revision': 2}).model_dump()]))
        original()
    monkeypatch.setattr(database_sync, 'begin_commit', changed)
    with TestClient(create_app(replace(settings, database_sources_file=config))) as client:
        client.headers['Authorization'] = 'Bearer test-secret'
        response = client.post('/api/database-sources/'+f.source.id+'/sync')
        assert response.status_code == 409 and response.json()['error']['code'] == 'source_changed'
        assert f.state() == before
