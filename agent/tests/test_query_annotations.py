"""One query selects real graph records and annotates them via native HTTP."""
from dataclasses import replace
import json

import pytest
from neo4j import Record

from graphmine_agent.database_queries import CypherRequest, execute_query
from graphmine_agent.errors import AnalyticsError
from graphmine_agent.query_annotations import compile_annotations
from graphmine_agent.query_previews import QueryPreviews
from semantic_provider_fixture import provider
from test_database_workspace import source, workspace, driver_path  # noqa: F401
from test_database_query_projection import read_transaction
from test_database_jobs import wait_job
from test_semantic_native import native_engine  # noqa: F401

QUERY = """MATCH (r:Account)-[e:TRANSFER]->(b:Account)
WHERE r.name IS NOT NULL
SET r.summary = llm('qwen', 'Describe {{r.name}} {answer STRING}')
RETURN r, e, b
LIMIT 10"""


def test_compiler_preserves_selection_and_does_not_send_set_or_model_to_source():
    plan = compile_annotations(QUERY, {'qwen'})
    assert "SET" not in plan.statement and 'llm(' not in plan.statement
    assert "MATCH (r:Account)-[e:TRANSFER]->(b:Account)" in plan.statement
    assert 'WHERE r.name IS NOT NULL' in plan.statement
    assert 'RETURN r, e, b, (r.name) AS __gm_input_0_0\nLIMIT 10' in plan.statement
    assert plan.assignments[0].model == 'qwen'
    assert '{{gm_input_0}}' in plan.assignments[0].expression


@pytest.mark.parametrize('query', [
    QUERY.replace("'qwen'", "'mock'"), QUERY.replace("'qwen'", "'missing'"),
    QUERY.replace('RETURN r, e, b', 'RETURN e, b'),
    QUERY.replace('RETURN r, e, b', 'RETURN DISTINCT r, e, b'),
    QUERY.replace('LIMIT 10', 'ORDER BY r.summary LIMIT 10'),
    QUERY.replace('LIMIT 10', 'DELETE b'),
    QUERY.replace('r.summary', 'r.neo4j_labels'),
    QUERY.replace('RETURN r, e, b', 'SET b.foo=1 RETURN r,e,b'),
    "MATCH (n) RETURN llm('qwen','Hi')",
    QUERY.replace('r.name}}', 'llm(\"qwen\",\"x\")}}'),
    QUERY.replace('RETURN r, e, b', 'RETURN r,r AS again,e,b'),
    QUERY.replace('RETURN r, e, b', 'RETURN r,e AS r,b'),
    QUERY + '; CREATE (x)',
])
def test_invalid_or_ambiguous_annotations_are_rejected(query):
    with pytest.raises(AnalyticsError): compile_annotations(query, {'qwen'})


def test_quoted_targets_prompt_parameters_and_explicit_aliases():
    query = "MATCH (`review`) WITH `review`, $topic AS topic SET `review`.`ai summary`=llm('qwen','{{coalesce(review.text, topic)}} {answer STRING}') RETURN `review` AS result LIMIT $limit;"
    plan = compile_annotations(query, {'qwen'})
    assert plan.assignments[0].property == 'ai summary'
    assert plan.assignments[0].column == 'result'
    assert '(coalesce(review.text, topic)) AS __gm_input_0_0' in plan.statement
    assert plan.statement.endswith('LIMIT $limit')


def source_records(source, monkeypatch, two=False):
    path = driver_path(source); a,b = path.nodes; e = path.relationships[0]
    records = [Record({'r':a,'e':e,'b':b,'__gm_input_0_0':'Ada'})]
    if two: records[0] = Record({**dict(records[0]), '__gm_input_1_0': 10})
    tx = read_transaction(monkeypatch, records)
    monkeypatch.setattr('graphmine_agent.database_queries.execute_query', execute_query)
    return tx


def test_captured_rows_keep_real_graph_identity_and_detect_conflicting_inputs(source, monkeypatch):
    path = driver_path(source); a,b = path.nodes; e = path.relationships[0]
    record = {'r':a, 'e':e, 'b':b, '__gm_input_0_0':'Ada'}
    read_transaction(monkeypatch, [Record(record), Record(record)])
    plan = compile_annotations(QUERY, {'qwen'})
    graph, _, sample, count, _ = execute_query(source, CypherRequest(statement=plan.statement), 100000, annotations=plan)
    assert count == 2 and len(graph['vertices']) == 2 and len(graph['edges']) == 1
    assert len(plan.assignments[0].rows) == 1 and '__gm_input_0_0' not in sample[0]
    read_transaction(monkeypatch, [Record(record), Record({**record,'__gm_input_0_0':'Ben'})])
    with pytest.raises(AnalyticsError, match='Multiple rows'):
        execute_query(source, CypherRequest(statement=plan.statement), 100000, annotations=plan)


def test_one_query_annotates_nodes_and_edges_with_fresh_real_http(workspace, source, monkeypatch, native_engine):
    source_records(source, monkeypatch, two=True)
    query = QUERY.replace('\nRETURN', ", e.summary = llm('qwen', 'Describe {{e.amount}} {answer STRING}')\nRETURN")
    with provider() as (url, calls):
        workspace.runtime.settings = replace(workspace.runtime.settings, semantic_mode='live', llm_base_url=url, llm_model='fixture-model')
        for _ in range(2):
            response = workspace.client.post('/api/database-sources/demo/queries', json={'statement':query, 'call_limit':2})
            assert response.status_code == 201, response.text
            result = response.json()
            graph = json.loads(QueryPreviews(workspace.runtime).get(result['dataset']['id'], content=True)[1])
            assert graph['vertices'][0]['attributes']['summary'] == 'negative'
            assert graph['edges'][0]['attributes']['summary'] == 'negative'
            assert result['usage']['http_requests'] == 2
            assert result['dataset']['source']['effective_call_limit'] == 2
            assert result['dataset']['source']['query'] == query
            assert result['dataset']['source']['model_dependent_input']
            assert result['dataset']['source']['simulation'] is False
        assert len(calls) == 4
        assert all(call['body']['model'] == 'fixture-model' for call in calls)
        assert all(call['body']['response_format']['json_schema']['strict'] is True for call in calls)
        assert 'summary' not in driver_path(source).nodes[0]


def test_total_budget_failure_and_provider_failure_publish_nothing(workspace, source, monkeypatch, native_engine):
    source_records(source, monkeypatch, two=True)
    query = QUERY.replace('\nRETURN', ", e.summary = llm('qwen', 'Describe {{e.amount}} {answer STRING}')\nRETURN")
    with provider() as (url, calls):
        workspace.runtime.settings = replace(workspace.runtime.settings, semantic_mode='live', llm_base_url=url, llm_model='fixture-model')
        response = workspace.client.post('/api/database-sources/demo/queries', json={'statement':query, 'call_limit':1})
        assert response.status_code == 422, response.text
        assert response.json()['error']['code'] == 'semantic_call_limit' and len(calls) == 1
        assert response.json()['error']['details']['usage']['http_requests'] == 1
    with provider(400) as (url, calls):
        workspace.runtime.settings = replace(workspace.runtime.settings, llm_base_url=url)
        response = workspace.client.post('/api/database-sources/demo/queries', json={'statement':QUERY})
        assert response.status_code == 502, response.text
        assert response.json()['error']['code'] == 'semantic_structured_output' and len(calls) == 1


def test_async_annotations_and_model_catalog(workspace, source, monkeypatch, native_engine):
    source_records(source, monkeypatch)
    with provider() as (url, calls):
        workspace.runtime.settings = replace(workspace.runtime.settings, semantic_mode='live', llm_base_url=url, llm_model='fixture-model')
        info = workspace.client.get('/api/query-models')
        assert info.status_code == 200 and info.json()['available']
        assert all(item['alias'] != 'mock' for item in info.json()['models'])
        assert info.json()['reuse_answers'] is False
        response = workspace.client.post('/api/database-sources/demo/queries', headers={'Prefer':'respond-async'}, json={'statement':QUERY})
        assert response.status_code == 202, response.text
        job = wait_job(workspace.client, response.json()['job']['id'])
        result = workspace.client.get('/api/database-jobs/' + job['id'] + '/result')
        assert result.status_code == 200, result.text
        assert result.json()['usage']['http_requests'] == 1 and len(calls) == 1


def test_query_alias_selects_custom_model_without_separate_model_parameter(workspace, source, monkeypatch, native_engine):
    from graphmine_agent.semantic_providers import save_alias, AliasInput
    source_records(source, monkeypatch)
    with provider() as (url, calls):
        workspace.runtime.settings = replace(workspace.runtime.settings, llm_base_url=url, llm_model='primary-model')
        save_alias(workspace.runtime, AliasInput(alias='other', provider_id='graphmine', model_id='other-model'))
        response = workspace.client.post('/api/database-sources/demo/queries', json={'statement': QUERY.replace("'qwen'", "'other'")})
        assert response.status_code == 201, response.text
        assert calls[0]['body']['model'] == 'other-model'
        assert response.json()['dataset']['source']['steps'][0]['model_alias'] == 'other'


def test_empty_selection_makes_no_model_requests(workspace, source, monkeypatch, native_engine):
    read_transaction(monkeypatch, [], columns=['r','e','b','__gm_input_0_0'])
    monkeypatch.setattr('graphmine_agent.database_queries.execute_query', execute_query)
    with provider() as (url, calls):
        workspace.runtime.settings = replace(workspace.runtime.settings, llm_base_url=url, llm_model='fixture-model')
        response = workspace.client.post('/api/database-sources/demo/queries', json={'statement': QUERY})
        assert response.status_code == 201, response.text
        assert response.json()['vertex_count'] == 0 and calls == []
