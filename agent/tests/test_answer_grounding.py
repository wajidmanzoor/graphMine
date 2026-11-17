from dataclasses import replace
import json

import httpx
import jsonschema
import pytest

from graphmine_agent.answer_grounding import Evidence, answer_schema
from graphmine_agent.analytics_answers import compose_sources, numberless_lead


def evidence(turn='now'):
    return Evidence(turn).record('native_result', [
        {'id': 'f1', 'kind': 'fact', 'ref': 'workflow:w:revision:2:f1', 'text': 'Ann has 3 connections.'},
        {'id': 'f2', 'kind': 'fact', 'ref': 'workflow:w:revision:2:f2', 'text': 'Bob has 2 connections.'},
        {'id': 'f3', 'kind': 'fact', 'ref': 'workflow:w:revision:2:f3', 'text': 'The largest group has 3 members.'},
    ])


@pytest.mark.parametrize('text', [
    'Bob has 3 connections.', 'Ann has 2 connections.', 'There are 3 groups.',
    'Ann has 3 members.', 'Ann has -3 connections.', 'Ann has 3.5 connections.',
    'Ann does not have 3 connections.', 'Ann has 3 connections because Bob trusts her.',
    'Mallory has 3 connections.', 'mallory has 3 connections.', 'ann has 3 connections.',
])
def test_checker_rejects_changed_names_numbers_units_relations_and_causes(text):
    ledger = evidence()
    assert ledger.check(ledger.answer(text, ['f1', 'f2', 'f3']), turn_id='now', data_answer=True)


def test_exact_evidence_keeps_large_numbers_unicode_names_and_source_binding():
    ledger = Evidence('t').record('input', [{'id': 'a', 'kind': 'fact', 'ref': 'input:v1',
        'text': 'Zoë has 9007199254740993 connections.'}])
    answer = ledger.facts()
    assert not ledger.check(answer, turn_id='t', data_answer=True)
    answer['text'] = answer['text'].replace('9007199254740993', '9007199254740992')
    assert ledger.check(answer, turn_id='t', data_answer=True)


@pytest.mark.parametrize('tamper', ['id', 'kind', 'ref', 'turn'])
def test_citations_must_identify_a_tool_result_from_this_turn(tamper):
    ledger = evidence()
    answer = ledger.facts(['f1'])
    if tamper != 'turn':
        answer['citations'][0][tamper] = 'invented'
    assert ledger.check(answer, turn_id='old' if tamper == 'turn' else 'now')


def test_old_revision_and_uncited_source_are_not_evidence():
    ledger = evidence()
    old = ledger.facts(['f1'])
    old['citations'][0]['ref'] = 'workflow:w:revision:1:f1'
    assert ledger.check(old, turn_id='now')
    assert ledger.check(ledger.answer('Bob has 2 connections.', ['f1']), turn_id='now')
    assert ledger.check({'text': 'Ann has 3 connections.', 'citations': []}, turn_id='now')


def test_data_answers_cannot_cite_web_even_when_text_matches():
    ledger = Evidence('t').record('google_search', [{'id': 'web.1', 'kind': 'web', 'ref': 'https://example.org', 'text': 'Ann has 3 connections.'}])
    assert not ledger.check(ledger.facts(), turn_id='t')
    assert ledger.check(ledger.facts(), turn_id='t', data_answer=True)


def test_cited_numbers_survive_and_uncited_numeric_sentences_are_removed():
    ledger = evidence()
    citations = [ledger.citation('f1')]
    assert numberless_lead('Ann has 3 connections. Bob has 99 connections.', evidence=ledger, citations=citations) == 'Ann has 3 connections.'
    assert numberless_lead('Ann has 3 connections.', evidence=ledger, citations=citations, turn_id='old') == ''


def test_model_uses_placeholders_instead_of_literal_data_or_vertex_ids():
    ledger = evidence()
    raw = ledger.answer('Here are the results.\n{{f1}}', ['f1'])
    rendered = ledger.render(raw, data_answer=True)
    assert rendered['text'] == 'Here are the results.\nAnn has 3 connections.'
    assert not ledger.check(rendered, turn_id='now', data_answer=True)
    with pytest.raises(ValueError, match='placeholders'):
        ledger.render(ledger.answer('Ann has 3 connections.', ['f1']), data_answer=True)
    with pytest.raises(ValueError, match='citation'):
        ledger.render(ledger.answer('{{f2}}', ['f1']), data_answer=True)
    with pytest.raises(ValueError, match='placeholders'):
        ledger.render(ledger.answer('Here are the tightest groups.\n{{f1}}', ['f1']), data_answer=True)


def test_introduction_and_lowercase_facts_have_separate_claim_boundaries():
    ledger = Evidence('t').record('facts', [{'id': 'f1', 'kind': 'fact', 'ref': 'workflow:w:f1', 'text': 'found 2 groups.'}])
    answer = ledger.render(ledger.answer('Here are the results. {{f1}}', ['f1']), data_answer=True)
    assert answer['text'] == 'Here are the results.\nfound 2 groups.'
    assert not ledger.check(answer, turn_id='t', data_answer=True)


def test_data_generation_schema_disallows_literal_ids_and_unknown_placeholders():
    schema = answer_schema(evidence(), data_answer=True)
    validator = jsonschema.Draft202012Validator(schema)
    for text in ['{{f1}}', 'Here are the results. {{f1}}\n{{f2}}']:
        validator.validate({'text': text, 'source_ids': ['f1', 'f2']})
    for text in ['Ann has 3 connections.', 'Vertices: 1, 2, 3.', '{{invented}}', '{{f1}} because Ann is central.']:
        with pytest.raises(jsonschema.ValidationError):
            validator.validate({'text': text, 'source_ids': ['f1']})


@pytest.mark.parametrize('repair_works', [False, True])
async def test_one_repair_then_checked_answer_or_bare_facts(settings, monkeypatch, repair_works):
    ledger, calls, observed = evidence(), [], []
    responses = [{'text': 'Mallory has 99 connections.', 'source_ids': ['f1']},
                 {'text': '{{f1}}' if repair_works else 'Bob has 3 connections.', 'source_ids': ['f1']}]
    def reply(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(responses.pop(0))}}],
                                       'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})
    original = httpx.AsyncClient
    monkeypatch.setattr('graphmine_agent.analytics_answers.httpx.AsyncClient', lambda **kw: original(transport=httpx.MockTransport(reply), **kw))
    answer = await compose_sources(replace(settings, llm_enabled=True), 'Who has most connections?', ledger,
                                   data_answer=True, default_ids=['f1'], on_call=lambda **row: observed.append(row))
    assert len(calls) == len(observed) == 2
    assert 'failed verification' in calls[1]['messages'][-1]['content']
    assert answer['text'] == 'Ann has 3 connections.'
    assert answer['source'] == ('model' if repair_works else 'facts')
    assert answer['grounding']['fallback'] is not repair_works
    assert [row['outcome'] for row in observed] == ['grounding_failed', 'ok' if repair_works else 'grounding_failed']
    assert not ledger.check(answer, turn_id='now', data_answer=True)


async def test_router_draft_counts_as_first_attempt_and_network_failure_is_not_retried(settings, monkeypatch):
    calls = []
    def offline(request):
        calls.append(request)
        raise httpx.ConnectError('offline')
    original = httpx.AsyncClient
    monkeypatch.setattr('graphmine_agent.analytics_answers.httpx.AsyncClient', lambda **kw: original(transport=httpx.MockTransport(offline), **kw))
    ledger = evidence()
    answer = await compose_sources(replace(settings, llm_enabled=True), 'Question', ledger,
        first=ledger.answer('Invented answer.', ['f1']), default_ids=['f1'])
    assert len(calls) == 1 and answer['source'] == 'facts'
    assert answer['grounding']['attempts'] == 2


async def test_qwen_generation_omits_unique_items_but_application_rejects_duplicates(settings, monkeypatch):
    ledger, calls = evidence(), []
    def reply(request):
        payload = json.loads(request.content)
        assert 'uniqueItems' not in payload['response_format']['json_schema']['schema']['properties']['source_ids']
        calls.append(payload)
        data = {'text': '{{f1}}', 'source_ids': ['f1', 'f1'] if len(calls) == 1 else ['f1']}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(data)}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr('graphmine_agent.analytics_answers.httpx.AsyncClient', lambda **kw: original(transport=httpx.MockTransport(reply), **kw))
    answer = await compose_sources(replace(settings, llm_enabled=True), 'Who has most connections?', ledger, data_answer=True)
    assert len(calls) == 2 and answer['source'] == 'model'
    assert answer['grounding'] == {'checked': True, 'attempts': 2, 'fallback': False}
    assert answer['citations'] == [ledger.citation('f1')]
