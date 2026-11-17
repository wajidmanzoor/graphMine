"""Answer verification through the real turn flow; model/search fixtures are authored."""
from dataclasses import replace
import json

import httpx
import pytest

from graphmine_agent.answer_grounding import Evidence
from graphmine_agent.analytics import AnalyticsError
from test_analytics_lanes import SelectLane
from test_analytics_planning import ReplayPlanner, _saved_earlier, setup  # noqa: F401


def check_turn(service, session, response, *, data=False):
    turn = response['turn_id']
    sources = [source for event in service.database.events(session)
               if event.type == 'workflow.evidence' and event.payload['turn_id'] == turn
               for source in event.payload['sources']]
    ledger = Evidence(turn)
    for citation in response['answer']['citations']:
        source = next(row for row in sources if all(row.get(key) == value for key, value in citation.items()))
        ledger.record(source['tool'], [source])
    assert not ledger.check(response['answer'], turn_id=turn, data_answer=data)


@pytest.mark.parametrize('repair_works', [True, False])
async def test_router_claim_is_checked_once_repaired_and_recorded(setup, monkeypatch, repair_works):
    settings, service, events, session, body = setup
    settings = replace(settings, llm_enabled=True, llm_base_url='http://writer.test/v1')
    body.inputs = {}
    body.message = 'Explain k-core versus k-truss.'
    planner = SelectLane(settings, service, events, select=lambda _: {
        'intent': 'reply', 'source_ids': ['doc.core-truss'], 'message': 'Mallory proved k-core has 99 members.'})
    calls = []
    def response(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({
            'text': '{{doc.core-truss}}' if repair_works else 'Mallory proved k-core has 99 members.',
            'source_ids': ['doc.core-truss']})}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr('graphmine_agent.analytics_answers.httpx.AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(response), **kwargs))
    result = await planner.plan(session, body)
    assert len(planner.calls) == len(calls) == 1
    assert result['answer']['grounding'] == {'checked': True, 'attempts': 2, 'fallback': not repair_works}
    assert 'Mallory' not in result['answer']['text'] and '99' not in result['answer']['text']
    check_turn(service, session, result)
    calls_in_activity = [row for row in service.database.events(session) if row.type == 'workflow.model_call']
    assert len(calls_in_activity) == 1 and calls_in_activity[0].payload['stage'] == 'answer'
    assert service.list(session) == []


async def test_saved_explanation_reloads_evidence_for_the_current_turn(setup, monkeypatch):
    settings, service, events, session, body = setup
    planner = ReplayPlanner(settings, service, events, responses=[{
        'intent': 'explain', 'message': '{{f1}}', 'fact_ids': ['f1']}])
    _saved_earlier(service, planner, session, monkeypatch)
    body.previous_workflow_id = 'earlier'
    body.message = 'How big were the cliques?'
    result = await planner.plan(session, body)
    assert result['answer']['grounding']['fallback'] is False
    assert result['answer']['citations'][0]['ref'].startswith('workflow:earlier:revision:1:')
    check_turn(service, session, result, data=True)
    assert not any(row.type == 'workflow.model_call' for row in service.database.events(session))


async def test_picked_fact_followup_needs_no_model_even_when_enabled(setup, monkeypatch):
    settings, service, events, session, body = setup
    planner = ReplayPlanner(replace(settings, llm_enabled=True), service, events, responses=[])
    _saved_earlier(service, planner, session, monkeypatch)
    body.previous_workflow_id = 'earlier'
    body.action = {'intent': 'explain', 'fact_ids': ['f2']}
    body.message = 'What guarantees does this calculation provide?'
    monkeypatch.setattr('graphmine_agent.analytics_answers.httpx.AsyncClient',
                        lambda **_kwargs: pytest.fail('A selected computed fact needs no writer'))
    result = await planner.plan(session, body)
    assert result['lane'] == 'explain' and planner.calls == []
    assert result['answer']['grounding']['fallback'] is False
    check_turn(service, session, result, data=True)
    assert not any(row.type == 'workflow.model_call' for row in service.database.events(session))


async def test_input_counts_never_search_google_or_compose_an_answer(setup, monkeypatch):
    settings, service, events, session, body = setup
    body.message = 'Search Google: how many vertices are loaded in my graph?'
    planner = SelectLane(settings, service, events, select=lambda payload: {
        'intent': 'describe_input', 'message': '999 vertices.',
        'fact_ids': [next(row['id'] for row in payload['input_facts'] if row['property'] == 'vertices_count')]})
    async def forbidden(_question):
        pytest.fail('Data answers must not use web evidence')
    monkeypatch.setattr('graphmine_agent.google_search.search', forbidden)
    result = await planner.plan(session, body)
    assert '999' not in result['answer']['text'] and len(planner.calls) == 1
    assert result['answer']['grounding']['attempts'] == 0
    check_turn(service, session, result, data=True)


@pytest.mark.parametrize('status', ['ok', 'blocked', 'unavailable'])
async def test_explicit_general_google_search_records_only_returned_sources(setup, monkeypatch, status):
    settings, service, events, session, body = setup
    settings = replace(settings, google_search_enabled=True)
    body.message, body.inputs = 'Google k-core definition', {}
    planner = SelectLane(settings, service, events, select=lambda _: {
        'intent': 'reply', 'message': '{{doc.core-truss}}', 'source_ids': ['doc.core-truss']})
    async def search(question, *, enabled=False):
        assert enabled
        assert question == body.message  # No graph, conversation or hidden context is sent.
        return {'status': status, 'search_url': 'https://www.google.com/search?q=k-core',
                'sources': [{'id': 'web.1', 'kind': 'web', 'ref': 'https://example.org/core',
                             'text': 'A core has a specified minimum degree.'}] if status == 'ok' else []}
    monkeypatch.setattr('graphmine_agent.google_search.search', search)
    result = await planner.plan(session, body)
    assert result['lane'] == 'reply' and service.list(session) == []
    assert result['answer']['web_search']['status'] == status
    if status == 'blocked':
        assert result['answer']['text'] == "Google blocked this server's search."
    assert [row['kind'] for row in result['answer']['citations']] == (['web'] if status == 'ok' else ['fact'])
    check_turn(service, session, result)
    assert any(row.type == 'workflow.search' for row in service.database.events(session))


async def test_disabled_web_search_reports_status_without_retrieval_or_writer(setup, monkeypatch):
    settings, service, events, session, body = setup
    assert settings.google_search_enabled is False
    body.message, body.inputs = 'Search the web for the latest k-core research', {}
    planner = SelectLane(settings, service, events, select=lambda _: {
        'intent': 'reply', 'message': '{{doc.core-truss}}', 'source_ids': ['doc.core-truss']})
    def forbidden(*args, **kwargs):
        pytest.fail('Disabled search must not retrieve sources or call a writer')
    monkeypatch.setattr('graphmine_agent.google_search.httpx.AsyncClient', forbidden)
    monkeypatch.setattr('graphmine_agent.google_search._browser_search', forbidden)
    monkeypatch.setattr('graphmine_agent.analytics_planning.compose_sources', forbidden)
    result = await planner.plan(session, body)
    assert result['lane'] == 'reply' and service.list(session) == []
    assert result['answer']['text'] == 'Web search is currently disabled.'
    assert result['answer']['web_search'] == {'status': 'disabled', 'search_url': None}
    assert [row['kind'] for row in result['answer']['citations']] == ['fact']
    assert len(planner.calls) == 1
    check_turn(service, session, result)


async def test_view_count_is_cited_from_resolved_selection(setup, monkeypatch):
    settings, service, events, session, body = setup
    planner = ReplayPlanner(settings, service, events, responses=[{
        'intent': 'view', 'view': {'kind': 'show_group', 'group': 'largest'}, 'message': 'There are 99 members.'}])
    _saved_earlier(service, planner, session, monkeypatch)
    body.message, body.previous_workflow_id = 'Show the largest clique', 'earlier'
    result = await planner.plan(session, body)
    assert result['message'] == result['answer']['text'] and '3 vertices' in result['message']
    assert '99' not in result['message']
    check_turn(service, session, result, data=True)


def test_saved_result_cannot_be_cited_with_a_stale_revision(setup, monkeypatch):
    settings, service, events, _session, _body = setup
    planner = ReplayPlanner(settings, service, events, responses=[])
    def result(_workflow_id, *, expected_revision=None):
        if expected_revision is not None and expected_revision != 2:
            raise AnalyticsError('Revision changed', 'revision_conflict', 409)
        return {'steps': {'new': {'status': 'completed'}}}
    monkeypatch.setattr(service, 'result', result)
    assert planner._saved_result('w', expected_revision=1) is None
    assert planner._saved_result('w', expected_revision=2)['steps']['new']['status'] == 'completed'
