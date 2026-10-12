from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from graphmine_agent import adapter_server
from graphmine_agent.config import Settings
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning.adapter_eval import routing_schema
from graphmine_agent.learning.adapter_workflows import route_messages
from graphmine_agent.llm import EXPANDED_ROUTING_SYSTEM_PROMPT, ROUTING_SYSTEM_PROMPT
from graphmine_agent.models import RouteDecision

AUTH = {"Authorization": "Bearer internal-test-key"}


@pytest.fixture
def adapter_bundle(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "adapter").mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({"base_model": "test-base"}))
    weights = run / "adapter/adapter_model.safetensors"
    weights.write_bytes(b"test-only adapter artifact")
    suite = tmp_path / "suite"
    suite.mkdir()
    plan = {
        "run": str(run),
        "run_sha256": HistoryStore.digest(run / "run.json"),
        "adapter_sha256": HistoryStore.digest(weights),
        "system_prompt": ROUTING_SYSTEM_PROMPT,
        "response_schema": routing_schema(),
    }
    (suite / "plan.json").write_text(json.dumps(plan))
    monkeypatch.setenv("GRAPHMINE_ROUTER_SUITE", str(suite))
    monkeypatch.setenv("GRAPHMINE_ROUTER_ADAPTER_SHA256", plan["adapter_sha256"])
    monkeypatch.setenv("GRAPHMINE_ROUTER_MODEL", "test-adapter")
    monkeypatch.setenv("GRAPHMINE_ROUTER_BASE_URL", "http://router.test")
    monkeypatch.setenv("GRAPHMINE_ROUTER_ALLOW_EXPANDED_CATALOG", "false")
    monkeypatch.setenv("GRAPHMINE_LLM_API_KEY", "internal-test-key")
    calls = []

    class Router:
        def __init__(self, *args):
            pass

        def route(self, payload, conversation, arm, *, system_prompt):
            calls.append((payload, conversation, arm, system_prompt))
            return {
                "raw": RouteDecision(
                    supported=False,
                    confidence=1,
                    explanation="Please specify the goal.",
                ).model_dump_json(),
                "finish_reason": "stop",
                "input_tokens": 10,
                "output_tokens": 10,
                "seconds": 0.01,
            }

    monkeypatch.setattr(adapter_server, "ConversationRouter", Router)
    return suite, weights, calls


@pytest.mark.parametrize("allow_expanded", [False, True])
def test_adapter_contract_opt_in_preserves_legacy_and_rejects_unknown_catalogs(
    adapter_bundle, monkeypatch, settings, allow_expanded
):
    _, _, calls = adapter_bundle
    monkeypatch.setenv("GRAPHMINE_ROUTER_ALLOW_EXPANDED_CATALOG", str(allow_expanded))
    contract = settings.routing_contract_version
    with TestClient(adapter_server.create_router_app()) as client:
        assert client.get("/health").status_code == 401
        health = client.get("/health", headers=AUTH).json()
        assert health["evaluated_contract_version"] == "legacy-20"
        assert health["routing_experimental"] is allow_expanded
        assert (contract in health["supported_routing_contracts"]) is allow_expanded

        legacy = client.post(
            "/route", headers=AUTH, json={"payload": {"message": "Find groups"}}
        )
        assert legacy.status_code == 200
        assert calls[-1][2:] == ("adapter_nf4", ROUTING_SYSTEM_PROMPT)
        assert legacy.json()["identity"]["routing_experimental"] is False

        payload = {
            "message": "Find a minimum-cost tree meeting these groups",
            "routing_context": {"contract_version": contract},
        }
        response = client.post("/route", headers=AUTH, json={"payload": payload})
        assert response.status_code == (200 if allow_expanded else 422)
        if allow_expanded:
            identity = response.json()["identity"]
            assert identity["routing_contract_version"] == contract
            assert identity["routing_experimental"] is True
            assert (
                identity["system_prompt_sha256"]
                == hashlib.sha256(EXPANDED_ROUTING_SYSTEM_PROMPT.encode()).hexdigest()
            )
            assert calls[-1][3] == EXPANDED_ROUTING_SYSTEM_PROMPT
            messages = route_messages(payload, [], system_prompt=calls[-1][3])
            assert messages[0]["content"] == EXPANDED_ROUTING_SYSTEM_PROMPT
            assert (
                "group-steiner-tree with nonnegative integer edge costs"
                in messages[0]["content"]
            )
            assert (
                "influence-maximization with explicit activation probabilities"
                in messages[0]["content"]
            )
        count = len(calls)
        payload["routing_context"]["contract_version"] = "unrecognized-future-catalog"
        assert (
            client.post("/route", headers=AUTH, json={"payload": payload}).status_code
            == 422
        )
        assert len(calls) == count


@pytest.mark.parametrize("changed", ["weights", "prompt"])
def test_expanded_opt_in_does_not_bypass_saved_adapter_binding(
    adapter_bundle, monkeypatch, changed
):
    suite, weights, _ = adapter_bundle
    monkeypatch.setenv("GRAPHMINE_ROUTER_ALLOW_EXPANDED_CATALOG", "true")
    if changed == "weights":
        weights.write_bytes(b"different adapter artifact")
        message = "deployment binding"
    else:
        path = suite / "plan.json"
        plan = json.loads(path.read_text())
        plan["system_prompt"] = EXPANDED_ROUTING_SYSTEM_PROMPT
        path.write_text(json.dumps(plan))
        message = "prompt/schema"
    with (
        pytest.raises(ValueError, match=message),
        TestClient(adapter_server.create_router_app()),
    ):
        pytest.fail("Mismatched saved artifacts must prevent startup")


def test_expanded_adapter_setting_requires_a_router_endpoint(monkeypatch):
    monkeypatch.setenv("GRAPHMINE_ROUTER_ALLOW_EXPANDED_CATALOG", "true")
    monkeypatch.delenv("GRAPHMINE_ROUTER_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="GRAPHMINE_ROUTER_BASE_URL"):
        Settings.from_env()


def test_expanded_adapter_settings_and_status_are_explicit(
    adapter_bundle, settings, monkeypatch
):
    from dataclasses import replace

    from graphmine_agent.api import create_app

    monkeypatch.setenv("GRAPHMINE_ROUTER_ALLOW_EXPANDED_CATALOG", "true")
    configured = Settings.from_env(settings.repository_root)
    assert configured.routing_adapter_active and configured.routing_adapter_experimental
    assert configured.active_routing_model == "test-adapter"
    configured = replace(
        settings,
        llm_route_base_url=configured.llm_route_base_url,
        llm_route_model=configured.llm_route_model,
        llm_route_allow_expanded_catalog=True,
    )
    auth = {"Authorization": "Bearer test-secret"}
    with TestClient(create_app(configured)) as client:
        session = client.post("/api/sessions", headers=auth, json={}).json()["id"]
        workspace = client.get(
            f"/api/sessions/{session}/workspace", headers=auth
        ).json()
        assert workspace["deployment"]["routing_model"] == "test-adapter"
        assert workspace["deployment"]["routing_experimental"] is True
        assert (
            workspace["deployment"]["adapter_evaluated_contract_version"] == "legacy-20"
        )
        response = client.post(
            f"/api/sessions/{session}/chat", headers=auth, json={"message": "/status"}
        )
        assert (
            "test-adapter (experimental for the current catalog)"
            in response.json()["message"]
        )
