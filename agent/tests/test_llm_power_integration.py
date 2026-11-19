import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from graphmine_agent.analytics_planning import AnalyticsPlanner, AnalyticsError, PlanningRequest
from graphmine_agent.llm import OpenAICompatibleModel
from graphmine_agent.llm_power import LLMPowerRegistry, LLMPowerBusy, LLMUnavailable, server_root
from graphmine_agent.models import LLMMode
from test_llm_power import Server, manager


class Events:
    def __init__(self):
        self.rows = []

    async def publish(self, session, kind, payload):
        self.rows.append((kind, payload))


def transport_factory(monkeypatch, handler):
    original = httpx.AsyncClient
    def client(*args, **kwargs):
        if kwargs.get('transport') is None:
            kwargs['transport'] = httpx.MockTransport(handler)
        return original(*args, **kwargs)
    monkeypatch.setattr(httpx, 'AsyncClient', client)


async def test_streamed_planning_wakes_reports_progress_and_keeps_lease(settings, tmp_path, monkeypatch):
    settings = replace(settings, llm_enabled=True, llm_sleep_mode=True, llm_api_key='test-key', llm_base_url='http://model.test/v1')
    server, events = Server(), Events()
    power = manager(tmp_path, server)
    registry = LLMPowerRegistry(settings)
    registry.managers[server_root(settings.llm_base_url)] = power
    decision = {'family_id': 'dense', 'reason': 'Find dense groups.'}
    async def respond(request):
        if request.url.path == '/v1/chat/completions':
            assert power.in_flight == 1 and not power.sleeping
            assert json.loads(request.content)['stream'] is True
            with pytest.raises(LLMPowerBusy):
                await power.sleep_now()
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(decision)}, 'finish_reason': 'stop'}]})
        return await server(request)
    transport_factory(monkeypatch, respond)
    analytics = SimpleNamespace(llm_power=registry, database=SimpleNamespace(capture=None))
    planner = AnalyticsPlanner(settings, analytics, events)
    token = planner.conversation.set({'session_id': 'test', 'turn_id': 'question'})
    try:
        result = await planner._generate('family', {'question': 'Find dense groups'}, {'type': 'object'})
        assert result == decision
        states = [p['status'] for kind, p in events.rows if kind == 'workflow.planning']
        assert states == ['running', 'waking', 'running']
        assert server.count('/wake_up') == 1 and power.in_flight == 0
    finally:
        planner.conversation.reset(token)
        await registry.close()


async def test_planner_wake_timeout_keeps_message_and_retry_contract(settings, tmp_path):
    settings = replace(settings, llm_enabled=True, llm_sleep_mode=True, llm_api_key='test-key', llm_base_url='http://model.test/v1')
    server, events = Server(), Events()
    server.stuck = True
    power = manager(tmp_path, server, wake_timeout=.035)
    registry = LLMPowerRegistry(settings)
    registry.managers[server_root(settings.llm_base_url)] = power
    planner = AnalyticsPlanner(settings, SimpleNamespace(llm_power=registry, database=SimpleNamespace(capture=None)), events)
    try:
        with pytest.raises(AnalyticsError) as caught:
            await planner._generate('family', {'question': 'Find dense groups'}, {'type': 'object'})
        assert caught.value.code == 'llm_unavailable'
        assert str(caught.value) == 'The model is waking up and did not respond in time'
        await planner._publish_failure('test', 'question', PlanningRequest(message='Find dense groups'), caught.value.code, str(caught.value))
        kind, message = events.rows[-1]
        assert kind == 'workflow.chat' and message['retryable']
        assert message['message'] == str(caught.value)
    finally:
        await registry.close()


async def test_classic_transport_retry_counts_as_one_activity(settings, tmp_path, monkeypatch):
    settings = replace(settings, llm_enabled=True, llm_sleep_mode=True, llm_api_key='test-key', llm_base_url='http://model.test/v1')
    server = Server(sleeping=False)
    power = manager(tmp_path, server)
    registry = LLMPowerRegistry(settings)
    registry.managers[server_root(settings.llm_base_url)] = power
    attempts = []
    async def respond(request):
        if request.url.path == '/v1/chat/completions':
            attempts.append(power.in_flight)
            if len(attempts) == 1:
                raise httpx.ConnectError('Transient fixture connection failure', request=request)
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"value":1}'}}]})
        return await server(request)
    transport_factory(monkeypatch, respond)
    class Reply(BaseModel):
        value: int
    client = OpenAICompatibleModel(settings, power=registry)
    try:
        result = await client.generate(mode=LLMMode.planner, schema=Reply, user_payload={})
        assert result.value == 1 and attempts == [1, 1]
        assert server.count('/is_sleeping') == 1 and power.in_flight == 0
    finally:
        await client.close()
        await registry.close()


async def test_classic_optional_explanation_never_wakes(settings, tmp_path):
    settings = replace(settings, llm_enabled=True, llm_sleep_mode=True, llm_api_key='test-key', llm_base_url='http://model.test/v1')
    server = Server()
    registry = LLMPowerRegistry(settings)
    registry.managers[server_root(settings.llm_base_url)] = manager(tmp_path, server)
    client = OpenAICompatibleModel(settings, power=registry)
    class Reply(BaseModel):
        text: str
    try:
        with pytest.raises(LLMUnavailable, match='asleep'):
            await client.generate(mode=LLMMode.analyst, schema=Reply, user_payload={}, wake=False)
        assert server.count('/is_sleeping') == 1
        assert server.count('/wake_up') == server.count('/v1/models') == 0
    finally:
        await client.close()
        await registry.close()


async def test_completed_calculation_and_saved_results_do_not_wake(settings, database, graph_store, session, tmp_path, monkeypatch):
    from graphmine_agent.analytics import AnalyticsService
    from graphmine_agent.jobs import EventBus
    from test_analytics_answers import SAVED, TITLES

    settings = replace(settings, llm_enabled=True, llm_sleep_mode=True,
                       llm_api_key='test-key', llm_base_url='http://model.test/v1')
    server = Server()
    power = manager(tmp_path / 'leases', server)
    registry = LLMPowerRegistry(settings)
    registry.managers[server_root(settings.llm_base_url)] = power
    service = AnalyticsService(settings, database, graph_store, EventBus(database), llm_power=registry)
    async def capabilities():
        return {'operations': [{'id': key, 'title': value} for key, value in TITLES.items()]}
    monkeypatch.setattr(service, 'capabilities', capabilities)
    monkeypatch.setattr(service, '_saved', lambda *_args, **_kwargs: SAVED)
    try:
        assert service.result('saved') == SAVED
        assert not server.calls
        await service.events.publish(session.id, 'workflow.chat',
            {'turn_id': 'question', 'role': 'user', 'message': 'Find tight groups'})
        await service._answer({'id': 'saved', 'session_id': session.id, 'revision': 1,
                               'planning_turn_id': 'question'})
        answers = [event.payload for event in database.events(session.id) if event.type == 'workflow.answer']
        assert answers[-1]['source'] == 'facts' and not answers[-1]['pending']
        assert answers[-1]['facts'] and power.sleeping
        assert server.count('/is_sleeping') == 1
        assert server.count('/wake_up') == server.count('/v1/models') == 0
        calls = list(server.calls)
        assert service.result('saved') == SAVED and server.calls == calls
    finally:
        await service.close()
        await registry.close()
