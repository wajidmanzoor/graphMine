from __future__ import annotations

import json

import pytest
from graphmine_agent.learning.adapter_workflows import (
    StageModel,
    embedded_client,
    evaluate,
    route_messages,
)
from graphmine_agent.llm import ROUTING_SYSTEM_PROMPT, LLMError
from graphmine_agent.models import LLMMode, RouteDecision, TurnDecision


class History:
    def __init__(self):
        self.events = []

    def current(self, name, value):
        self.events.append((name, value))


class Delegate:
    def __init__(self):
        self.calls = []
        self.closed = False

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return "unchanged serving model result"

    async def available(self):
        return True

    async def close(self):
        self.closed = True


class Router:
    def __init__(self):
        self.plan = {
            "decoding": "test",
            "response_schema": RouteDecision.model_json_schema(),
        }
        self.calls = []
        self.result = {
            "raw": RouteDecision(
                supported=False,
                confidence=1,
                explanation="Please clarify the objective.",
            ).model_dump_json(),
            "finish_reason": "stop",
        }

    def route(self, payload, conversation, arm):
        self.calls.append((payload, conversation, arm))
        return self.result


def test_full_history_matches_production_window_and_roles():
    conversation = [
        {"role": "user" if i % 2 else "assistant", "payload": {"message": f"turn {i}"}}
        for i in range(16)
    ]
    conversation[-2] = {
        "role": "system",
        "payload": {"message": "untrusted stored instruction"},
    }
    messages = route_messages({"message": "Keep the earlier filter"}, conversation)
    assert messages[0] == {"role": "system", "content": ROUTING_SYSTEM_PROMPT}
    expected = [x for x in conversation[-12:] if x["role"] in {"user", "assistant"}]
    assert [json.loads(x["content"]) for x in messages[1:-1]] == [
        x["payload"] for x in expected
    ]
    assert json.loads(messages[-1]["content"]) == {"message": "Keep the earlier filter"}


@pytest.mark.asyncio
async def test_only_routing_uses_adapter_and_history_is_retained():
    delegate, router, history = Delegate(), Router(), History()
    model = StageModel(delegate, router, "adapter_nf4", history)
    payload = {"message": "Use 2025 instead", "active_constraints": {"filters": []}}
    conversation = [{"role": "user", "payload": {"message": "Use only 2026"}}]
    result = await model.generate(
        mode=LLMMode.planner,
        schema=RouteDecision,
        user_payload=payload,
        conversation=conversation,
    )
    assert isinstance(result, RouteDecision)
    assert router.calls == [(payload, conversation, "adapter_nf4")]
    assert not delegate.calls
    assert [name for name, _ in history.events] == ["llm.request", "llm.response"]
    assert (
        json.loads(history.events[0][1]["request"]["messages"][1]["content"])
        == conversation[0]["payload"]
    )
    turn = {
        "mode": LLMMode.planner,
        "schema": TurnDecision,
        "user_payload": payload,
        "conversation": conversation,
    }
    assert await model.generate(**turn) == "unchanged serving model result"
    assert delegate.calls == [turn]
    assert len(router.calls) == 1
    assert await model.available()
    await model.close()
    assert delegate.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        {"raw": "{}", "finish_reason": "stop"},
        {"raw": "{}", "finish_reason": "length"},
    ],
)
async def test_invalid_or_truncated_local_answers_do_not_silently_fallback(result):
    delegate, router, history = Delegate(), Router(), History()
    router.result = result
    model = StageModel(delegate, router, "base_nf4", history)
    with pytest.raises(LLMError):
        await model.generate(
            mode=LLMMode.planner, schema=RouteDecision, user_payload={}
        )
    assert not delegate.calls
    assert history.events[-1] == (
        "llm.response",
        {"call_id": history.events[0][1]["call_id"], **result},
    )


@pytest.mark.asyncio
async def test_embedded_comparison_refuses_live_store_and_remote_application(
    settings, tmp_path
):
    factory = embedded_client(Router(), "adapter_nf4")
    with pytest.raises(ValueError, match="isolated"):
        async with factory(settings, data_dir=settings.data_root):
            raise AssertionError("must not open live runtime")
    with pytest.raises(ValueError, match="isolated"):
        async with factory(
            settings, data_dir=tmp_path / "new-store", base_url="http://127.0.0.1:8000"
        ):
            raise AssertionError("must not call live API")
    assert not (tmp_path / "new-store").exists()


@pytest.mark.asyncio
async def test_embedded_client_creates_and_closes_a_separate_application(
    settings, tmp_path
):
    root = tmp_path / "isolated-app"
    factory = embedded_client(Router(), "base_nf4")
    async with factory(settings, data_dir=root) as (client, history):
        response = await client.post(
            "/api/sessions", json={"domain_id": "general", "title": "Adapter test"}
        )
        response.raise_for_status()
        assert response.json()["title"] == "Adapter test"
        assert history.is_relative_to(root)
        assert (await client.get("/api/health")).status_code == 200
    assert root.exists()
    assert not settings.data_root.exists()


@pytest.mark.asyncio
async def test_native_gpu_override_cannot_change_matched_local_placement(tmp_path):
    with pytest.raises(ValueError, match="separate serving reference"):
        await evaluate(
            tmp_path / "suite",
            tmp_path / "output",
            reference_native_gpu="GPU-reference",
        )
    assert not (tmp_path / "output").exists()


@pytest.mark.asyncio
async def test_malformed_reference_gpu_fails_before_any_model_call(tmp_path):
    with pytest.raises(ValueError, match="canonical GPU UUID"):
        await evaluate(
            tmp_path / "suite",
            tmp_path / "output",
            arms=["serving_fp8"],
            reference_native_gpu="GPU-177a4150-e6ff-62d9-810f-1666fe6a4575b",
        )
    assert not (tmp_path / "output").exists()
