"""Studio handoffs use authenticated, revision-bound saved execution evidence."""
from copy import deepcopy

import jsonschema
import pytest

from graphmine_agent.analytics_studio import schema_for, validate_bundle, validate_target
from test_workflow_templates import recipes  # noqa: F401


@pytest.fixture
def exchange(recipes, monkeypatch):
    client, runtime, alice, bob, sid, file, record, result = recipes
    record["validation"]["implementation_sha256"] = "b" * 64
    runtime.analytics._save(record)
    result.update(complete=True, workflow_hash="a" * 64)
    result["steps"]["core"]["result"]["ports"]["count"]["value"] = 9007199254740993
    runtime.analytics._write(runtime.analytics._directory(record) / "result.json", result)
    caps = {"implementation_sha256": "b" * 64, "operations": [{"id": "k-core", "parameters": {"requested_k": {"kind": "integer"}}, "output_ports": {"count": {"type": "scalar"}}}]}
    async def capabilities():
        return deepcopy(caps)
    monkeypatch.setattr(runtime.analytics, "capabilities", capabilities)
    candidate = client.get("/api/workflows/original/example-review", headers=alice)
    assert candidate.status_code == 200, candidate.text
    body = {k: candidate.json()[k] for k in ("expected_revision", "workflow_hash", "result_sha256")}
    reviewed = client.post("/api/workflows/original/example-review", headers=alice, json={**body, "question": "Find the core of this network", "approved": True})
    assert reviewed.status_code == 201, reviewed.text
    example = reviewed.json()
    url = f"/api/workflows/original/studio-export?example_id={example['id']}&expected_revision=1"
    return client, runtime, alice, bob, record, result, caps, example, url


def test_exchange_retains_attribution_schema_and_exact_execution_evidence(exchange):
    client, _, alice, bob, _, result, _, example, url = exchange
    response = client.get(url, headers=alice)
    assert response.status_code == 200, response.text
    row = validate_bundle(response.json())
    assert row["schema"] == "AnalyticsPlanNormalized" and row["adapter"] == "workflow"
    assert row["evidence"]["result"] == result
    assert row["source_review"] == example
    assert row["authorship"]["reviewer"]["name"] == "alice"
    assert row["context_origin"] == "derived_from_reviewed_workflow"
    assert client.get(url, headers=bob).status_code == 404
    assert client.get(url.replace("expected_revision=1", "expected_revision=2"), headers=alice).status_code == 409
    assert client.get(url.replace("expected_revision=1", "expected_revision=0"), headers=alice).status_code == 422


@pytest.mark.parametrize("change", ["result", "revision", "implementation", "revoked", "evaluation"])
def test_changed_or_unreviewed_execution_cannot_be_exported(exchange, change):
    client, runtime, alice, _, record, result, caps, example, url = exchange
    if change == "result":
        result["changed"] = True
        runtime.analytics._write(runtime.analytics._directory(record) / "result.json", result)
    elif change == "revision":
        record["revision"] = 2
        runtime.analytics._save(record)
    elif change == "implementation":
        caps["implementation_sha256"] = "c" * 64
    elif change == "evaluation":
        record["evaluation_id"] = "holdout"
        runtime.analytics._save(record)
    else:
        assert client.delete(f"/api/sessions/{record['session_id']}/analytics/examples/{example['id']}", headers=alice).status_code == 200
    response = client.get(url, headers=alice)
    assert response.status_code == (422 if change == "evaluation" else 409), response.text


def test_current_stage_contracts_use_available_operations_facts_and_wire_format(exchange):
    _, _, _, _, _, _, caps, _, _ = exchange
    context = {"cards": caps["operations"], "aliases": ["main"], "device": "cpu", "facts": [{"id": "f1"}]}
    for name in ("AnalyticsRoute", "AnalyticsPlan", "AnalyticsPlanNormalized", "AnalyticsAnswer"):
        jsonschema.Draft202012Validator.check_schema(schema_for(name, context))
    validate_target("AnalyticsRoute", {"intent": "calculate", "operations": ["k-core"], "message": "Find the core"}, context)
    with pytest.raises(jsonschema.ValidationError):
        validate_target("AnalyticsRoute", {"intent": "calculate", "operations": ["invented"], "message": "x"}, context)
    validate_target("AnalyticsAnswer", {"lead": "Here is the result", "fact_ids": ["f1"]}, context)
    with pytest.raises(ValueError):
        validate_target("AnalyticsAnswer", {"lead": "There are 42", "fact_ids": ["f1"]}, context)
    with pytest.raises(jsonschema.ValidationError):
        validate_target("AnalyticsAnswer", {"lead": "Result", "fact_ids": ["invented"]}, context)


def test_exchange_rejects_modified_payloads_and_excessive_evidence(exchange):
    client, _, alice, _, _, _, _, _, url = exchange
    bundle = client.get(url, headers=alice).json()
    bundle["example"]["question"] = "A different question"
    with pytest.raises(ValueError, match="hash"):
        validate_bundle(bundle)
    bundle["padding"] = "x" * (4 * 1024 * 1024)
    with pytest.raises(ValueError, match="4 MiB"):
        validate_bundle(bundle)


def test_review_revoked_while_capabilities_load_is_rechecked(exchange, monkeypatch):
    client, runtime, alice, _, record, _, caps, example, url = exchange
    async def revoke_during_load():
        runtime.analytics.examples.revoke(record["session_id"], example["id"])
        return caps
    monkeypatch.setattr(runtime.analytics, "capabilities", revoke_during_load)
    response = client.get(url, headers=alice)
    assert response.status_code == 409 and response.json()["error"]["code"] == "revision_conflict"


def test_large_saved_result_is_rejected_before_parsing(exchange, monkeypatch):
    client, runtime, alice, _, record, _, _, _, url = exchange
    path = runtime.analytics._result_path(record["id"])
    path.write_bytes(b" " * (4 * 1024 * 1024 + 1))
    monkeypatch.setattr(runtime.analytics, "result", lambda *_args, **_kwargs: pytest.fail("Oversized result was parsed"))
    response = client.get(url, headers=alice)
    assert response.status_code == 413
