from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning import corpus, inference, meaning, oracles, review
from graphmine_agent.learning.inference import (
    LearningModel,
    ModelProfile,
    RequestBudget,
    request_body,
)
from graphmine_agent.learning.review_export import export_reviewed

LOCAL = ModelProfile("local", "independent-reader", "http://127.0.0.1:9009/v1")
EXTERNAL = ModelProfile("openai", "gpt-6.1-sol")


@pytest.fixture
def synthetic(tmp_path):
    root = tmp_path / "corpus"
    manifest = corpus.generate_corpus(root, graphs_per_family=1)
    _, graphs = corpus.load_corpus(root)
    return root, manifest, graphs


def extraction(expected, query):
    model = meaning.QuestionMeaning.model_validate(expected)
    fields = model.model_dump(mode="json")
    return meaning.MeaningExtraction(
        meaning=model,
        evidence=[
            meaning.EvidenceSpan(field=field, quote=query)
            for field, value in fields.items()
            if value is not None
            and value != []
            and value is not False
            and value != "unspecified"
        ],
    )


def local_response(value, **changes):
    result = {
        "model": LOCAL.model,
        "choices": [
            {"finish_reason": "stop", "message": {"content": value.model_dump_json()}}
        ],
    }
    result.update(changes)
    return result


def external_response(value, **changes):
    result = {
        "model": EXTERNAL.model,
        "status": "completed",
        "usage": {"input_tokens": 500, "output_tokens": 400},
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": value.model_dump_json()}],
            }
        ],
    }
    result.update(changes)
    return result


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        inference.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


def proposal_file(root, manifest, tmp_path):
    example = next(
        row
        for row in manifest["examples"]
        if row["split"] == "train" and row["task"]["operation_id"] == "maximal-cliques"
    )
    query = "Please help me with this: " + example["task"]["query"]
    row = {
        "id": "proposal-" + corpus.digest([example["id"], query])[:16],
        "example_id": example["id"],
        "example_sha256": corpus.digest(example),
        "query": query,
        "teacher_model": "wording-generator",
        "training_eligible": False,
    }
    report = {
        "finished_at": "completed",
        "teacher_model": row["teacher_model"],
        "teacher_endpoint": "http://127.0.0.1:8001/v1",
        "corpus_sha256": HistoryStore.digest(root / "manifest.json"),
        "candidates": [row],
    }
    target = tmp_path / "proposals.json"
    HistoryStore.write(target, report)
    return target, report, example


def test_semantic_controls_and_strict_filter_types(synthetic):
    _, manifest, _ = synthetic
    for example in manifest["examples"]:
        meaning.expected_meaning(example["task"])
    controls = meaning.calibration_controls(manifest)
    assert len(controls) == 16
    test_ids = {
        row["graph_id"] for row in manifest["examples"] if row["split"] == "test"
    }
    assert not test_ids.intersection(row["graph_id"] for row in controls)
    changed = {row["id"]: row["expected"] for row in controls}
    assert changed["control-raised-group-minimum"]["minimum_group_size"] == 4
    assert changed["control-all-largest-ties"]["goal"] == "all_largest_pairwise_groups"
    assert changed["control-millisecond-window"]["time_unit"] == "milliseconds"
    first = meaning.expected_meaning(manifest["examples"][0]["task"])
    a = first.model_copy(
        update={
            "filters": [
                meaning.SemanticFilter(
                    target="edges", field="attributes.flag", operator="eq", value=1
                )
            ]
        }
    )
    b = first.model_copy(
        update={
            "filters": [
                meaning.SemanticFilter(
                    target="edges", field="attributes.flag", operator="eq", value=True
                )
            ]
        }
    )
    assert meaning.meaning_differences(a, b)
    assert meaning.wording_issues("Find the largest possible maximal groups.", first)
    good = extraction(first, "The question itself")
    assert not meaning.evidence_issues("The question itself", good)
    assert meaning.evidence_issues("An unrelated question", good)
    with pytest.raises(ValueError):
        meaning.QuestionMeaning.model_validate(
            {**first.model_dump(), "requires_weights": "false"}
        )


def test_blind_payload_has_no_reference_labels(synthetic):
    _, manifest, graphs = synthetic
    example = manifest["examples"][0]
    payload = review.blind_payload(graphs[example["graph_id"]], "A new question")
    assert set(payload) == {"question", "graph_context"}
    assert example["task"]["query"] not in json.dumps(payload)
    assert "oracle" not in payload and "expected" not in payload
    assert len(payload["graph_context"]["vertex_examples"]) == 1


@pytest.mark.parametrize(
    "model,endpoint,independent",
    [
        ("wording-generator", "http://localhost:9009/v1", False),
        ("WORDING-GENERATOR-2026", "http://localhost:9009/v1", False),
        ("student", "http://localhost:9009/v1", False),
        ("other-alias", "http://localhost:8001/another-api", False),
        ("other-alias", "http://[::1]:8002/v1", False),
        ("different-reader", "http://localhost:9009/v1", True),
    ],
)
def test_independence_rejects_models_and_same_server_aliases(
    model, endpoint, independent
):
    proposals = {
        "teacher_model": "wording-generator",
        "teacher_endpoint": "http://127.0.0.1:8001/v1",
    }
    assert (
        review.distinct_reviewer(
            proposals,
            ModelProfile("local", model, endpoint),
            "student",
            "http://127.0.0.1:8002/v1",
        )
        is independent
    )


def test_provider_schema_and_budget_fail_closed(settings, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="allow-external"):
        LearningModel(settings, EXTERNAL, RequestBudget(5))
    with pytest.raises(ValueError, match="budget-usd"):
        LearningModel(settings, EXTERNAL, RequestBudget(), allow_external=True)
    with pytest.raises(ValueError, match="not configured"):
        LearningModel(settings, EXTERNAL, RequestBudget(5), allow_external=True)
    for profile in [
        ("openai", "unpriced-model", None),
        ("openai", EXTERNAL.model, "https://attacker.example"),
        ("local", "model", "http://example.com/v1"),
        ("local", "model", "http://user:secret@127.0.0.1/v1"),
    ]:
        with pytest.raises(ValueError):
            ModelProfile(*profile)
    body = request_body(
        EXTERNAL,
        meaning.EXTRACTION_SYSTEM,
        {"question": "q"},
        meaning.MeaningExtraction,
    )
    assert body["store"] is False and body["reasoning"] == {"effort": "low"}
    assert "temperature" not in body and "tools" not in body
    schema = body["text"]["format"]["schema"]
    for specification in [schema, *schema["$defs"].values()]:
        if specification.get("type") == "object":
            assert specification["additionalProperties"] is False
            assert set(specification["required"]) == set(specification["properties"])
    with pytest.raises(ValueError, match="exceed"):
        RequestBudget(0.001).reserve(EXTERNAL, body)
    budget = RequestBudget(5, max_calls=1)
    assert budget.reserve(EXTERNAL, body)["reserved_usd"] > 0
    with pytest.raises(ValueError, match="exhausted"):
        budget.reserve(EXTERNAL, body)


@pytest.mark.asyncio
async def test_dry_run_never_calls_network(settings, synthetic, tmp_path, monkeypatch):
    root, _, _ = synthetic
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    transport(monkeypatch, lambda _: pytest.fail("A dry run must not send a request"))
    report = await review.compare_teachers(
        settings,
        corpus=root,
        destination=tmp_path / "plan",
        profiles=[EXTERNAL],
        budget_usd=5,
    )
    assert not report["executed"] and report["budget"]["calls"] == 0
    assert report["estimated_total_reservation_usd"] > 0
    assert not report["models"][0]["qualified_for_screening"]
    with pytest.raises(ValueError, match="exceeds"):
        await review.compare_teachers(
            settings,
            corpus=root,
            destination=tmp_path / "overbudget",
            profiles=[EXTERNAL],
            execute=True,
            allow_external=True,
            budget_usd=0.001,
        )
    assert not (tmp_path / "overbudget").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ["incomplete", "refusal", "missing_usage", "over_limit", "redirect", "bad_json"],
)
async def test_external_failures_are_recorded_without_retry(
    settings, synthetic, tmp_path, monkeypatch, failure
):
    _, manifest, _ = synthetic
    item = manifest["examples"][0]
    value = extraction(meaning.expected_meaning(item["task"]), item["task"]["query"])
    payload = external_response(value)
    if failure == "incomplete":
        payload["status"] = "incomplete"
    elif failure == "refusal":
        payload["output"][0]["content"] = [{"type": "refusal", "refusal": "no"}]
    elif failure == "missing_usage":
        payload.pop("usage")
    elif failure == "over_limit":
        payload["usage"]["output_tokens"] = 100_000
    elif failure == "bad_json":
        payload["output"][0]["content"][0]["text"] = '{"invalid":true}'
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        return httpx.Response(
            302 if failure == "redirect" else 200,
            json=payload,
            headers={"Location": "https://other.example"},
        )

    transport(monkeypatch, handler)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    budget = RequestBudget(5)
    artifact = tmp_path / "call.json"
    async with LearningModel(settings, EXTERNAL, budget, allow_external=True) as model:
        with pytest.raises(ValueError):
            await model.generate(
                system=meaning.EXTRACTION_SYSTEM,
                payload={"question": item["task"]["query"]},
                schema=meaning.MeaningExtraction,
                artifact=artifact,
            )
    assert len(calls) == 1
    saved = json.loads(artifact.read_text())
    assert saved["status"] == "failed" and saved["budget"]["calls"] == 1
    assert "fake-test-key" not in artifact.read_text()
    assert budget.stopped is (failure in {"missing_usage", "over_limit"})
    assert artifact.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_external_success_and_raw_evidence(
    settings, synthetic, tmp_path, monkeypatch
):
    _, manifest, graphs = synthetic
    item = manifest["examples"][0]
    query, graph = item["task"]["query"], graphs[item["graph_id"]]
    value = extraction(meaning.expected_meaning(item["task"]), query)
    transport(monkeypatch, lambda _: httpx.Response(200, json=external_response(value)))
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    target = tmp_path / "call.json"
    async with LearningModel(
        settings, EXTERNAL, RequestBudget(5), allow_external=True
    ) as model:
        result = await model.generate(
            system=meaning.EXTRACTION_SYSTEM,
            payload=review.blind_payload(graph, query),
            schema=meaning.MeaningExtraction,
            artifact=target,
        )
    saved = json.loads(target.read_text())
    assert result == value and saved["undiscounted_usage_cost_usd"] > 0
    review.verify_extraction_call(
        saved, EXTERNAL, graph, query, value.model_dump(mode="json")
    )
    saved["request"]["input"][1]["content"] = '{"question":"wrong question"}'
    with pytest.raises(ValueError, match="blinded"):
        review.verify_extraction_call(
            saved, EXTERNAL, graph, query, value.model_dump(mode="json")
        )


@pytest.mark.asyncio
async def test_echoed_credential_is_redacted_from_errors(
    settings, synthetic, tmp_path, monkeypatch
):
    _, manifest, _ = synthetic
    item = manifest["examples"][0]
    secret = "synthetic-secret-token"
    settings = replace(settings, llm_api_key=secret)
    # Invalid schema error includes the supplied text; both the thrown error and
    # the preserved raw response must be redacted.
    transport(
        monkeypatch,
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"meaning": secret})},
                    }
                ]
            },
        ),
    )
    artifact = tmp_path / "call.json"
    async with LearningModel(settings, LOCAL, RequestBudget()) as model:
        with pytest.raises(ValueError) as caught:
            await model.generate(
                system="read",
                payload={"question": item["task"]["query"]},
                schema=meaning.MeaningExtraction,
                artifact=artifact,
            )
    assert secret not in str(caught.value)
    assert secret not in artifact.read_text() and "[REDACTED]" in artifact.read_text()


@pytest.fixture
async def reviewed_case(settings, synthetic, tmp_path, monkeypatch):
    root, manifest, graphs = synthetic
    candidates, proposals, example = proposal_file(root, manifest, tmp_path)
    proposal = proposals["candidates"][0]
    controls = meaning.calibration_controls(manifest)
    answers = {
        row["query"]: extraction(row["expected"], row["query"]) for row in controls
    }
    answers[proposal["query"]] = extraction(
        meaning.expected_meaning(example["task"]), proposal["query"]
    )

    def handler(request):
        payload = json.loads(request.content)
        question = json.loads(payload["messages"][1]["content"])["question"]
        return httpx.Response(200, json=local_response(answers[question]))

    transport(monkeypatch, handler)
    calibration = tmp_path / "calibration" / "comparison.json"
    await review.compare_teachers(
        settings,
        corpus=root,
        destination=calibration.parent,
        profiles=[LOCAL],
        execute=True,
    )
    assert review.calibrated_profile(root, manifest, calibration, LOCAL)
    graph, task = graphs[example["graph_id"]], example["task"]
    output = {
        "cliques": task["oracle"]["groups"],
        "returned_count": task["oracle"]["count"],
        "complete": True,
    }
    outcome = {
        "job": {
            "status": "completed",
            "plan": {
                "parameters": task["parameters"],
                "application_intent": {"filters": task["filters"]},
            },
        },
        "result": {
            "operation_id": task["operation_id"],
            "payload": {"output": output},
            "answer": {
                "rows": [],
                "facts": ["test fixture"],
                "provenance": {"input_edges": len(graph["edges"])},
            },
            "interpretation": {"visualizations": [{"kind": "test fixture"}]},
        },
    }

    @asynccontextmanager
    async def client(*args, **kwargs):
        yield object(), tmp_path / "history"

    class Terminal:
        session_id, turn_id = "test-session", "test-turn"

        def __init__(self, *args, **kwargs):
            pass

        async def start(self, **kwargs):
            pass

        async def load(self, path):
            pass

        async def ask(self, query):
            assert query == proposal["query"]
            return outcome

        async def feedback(self, *args, **kwargs):
            pytest.fail("Passing mock replay should not need feedback")

    monkeypatch.setattr(review, "agent_client", client)
    monkeypatch.setattr(review, "Terminal", Terminal)
    settings = replace(settings, llm_enabled=True)
    review_path = tmp_path / "review" / "review.json"
    report = await review.review_candidates(
        settings,
        corpus=root,
        candidates=candidates,
        destination=review_path.parent,
        profile=LOCAL,
        calibration=calibration,
        data_dir=tmp_path / "isolated",
    )
    assert report["accepted"] == 1
    audit = tmp_path / "audit.json"
    HistoryStore.write(
        audit,
        {
            "mode": "native_oracle",
            "finished_at": "completed",
            "corpus_sha256": HistoryStore.digest(root / "manifest.json"),
            "checker_sha256": HistoryStore.digest(Path(oracles.__file__)),
            "examples": [
                {
                    "id": example["id"],
                    "example_sha256": corpus.digest(example),
                    "passed": True,
                    "payload": {"ok": True, "output": output},
                }
            ],
        },
    )
    return settings, {
        "corpus": root,
        "candidates": candidates,
        "review": review_path,
        "calibration": calibration,
        "audit": audit,
        "destination": tmp_path / "export",
    }


@pytest.mark.asyncio
async def test_reviewed_export_positive_path(reviewed_case):
    settings, args = reviewed_case
    result = export_reviewed(settings, **args)
    assert len(result["rows"]) == 1 and not result["quarantine"]
    assert result["training_started"] is False
    line = json.loads((args["destination"] / "train.jsonl").read_text())
    user = json.loads(line["messages"][1]["content"])
    label = json.loads(line["messages"][2]["content"])
    assert label["intent"]["objective"] == user["message"]
    assert "expected" not in user and "oracle" not in user
    assert not (args["destination"] / "validation.jsonl").exists()
    assert (args["destination"] / "train.jsonl").stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "stale_code",
        "same_model",
        "calibration_lie",
        "changed_replay_query",
        "bad_native_output",
        "bad_replay_output",
        "changed_raw_call",
        "no_replay",
        "changed_request",
    ],
)
async def test_reviewed_export_rechecks_every_gate(reviewed_case, mutation):
    settings, args = reviewed_case
    report = json.loads(args["review"].read_text())
    row = report["candidates"][0]
    if mutation == "stale_code":
        report["reviewer_contract_sha256"] = "stale"
    elif mutation == "same_model":
        settings = replace(settings, llm_model=LOCAL.model)
        report["student_model"] = LOCAL.model
    elif mutation == "calibration_lie":
        calibration = json.loads(args["calibration"].read_text())
        calibration["models"][0]["checks"][0]["extracted"]["meaning"][
            "minimum_group_size"
        ] = 99
        HistoryStore.write(args["calibration"], calibration)
        report["calibration_sha256"] = HistoryStore.digest(args["calibration"])
    elif mutation == "bad_native_output":
        native = json.loads(args["audit"].read_text())
        native["examples"][0]["payload"]["output"]["cliques"] = []
        HistoryStore.write(args["audit"], native)
    elif mutation == "no_replay":
        row.pop("replay")
    elif mutation in {"changed_replay_query", "bad_replay_output"}:
        path = args["review"].parent / row["replay"]
        replay = json.loads(path.read_text())
        if mutation == "changed_replay_query":
            replay["query"] = "Another question"
        else:
            replay["outcome"]["result"]["payload"]["output"]["cliques"] = []
        HistoryStore.write(path, replay)
        row["replay_sha256"] = HistoryStore.digest(path)
    else:
        path = args["review"].parent / row["call"]
        call = json.loads(path.read_text())
        if mutation == "changed_raw_call":
            raw = json.loads(call["raw_response"])
            raw["choices"][0]["message"]["content"] = "{}"
            call["raw_response"] = json.dumps(raw)
        else:
            call["request"]["messages"][1]["content"] = (
                '{"question":"another question"}'
            )
        HistoryStore.write(path, call)
        row["call_sha256"] = HistoryStore.digest(path)
    HistoryStore.write(args["review"], report)
    if mutation == "stale_code":
        with pytest.raises(ValueError, match="stale"):
            export_reviewed(settings, **args)
    else:
        result = export_reviewed(settings, **args)
        assert not result["rows"] and len(result["quarantine"]) == 1


def test_proposals_reject_test_split_and_modified_identity(synthetic, tmp_path):
    root, manifest, _ = synthetic
    path, report, _ = proposal_file(root, manifest, tmp_path)
    review.load_proposals(root, path)
    report["candidates"][0]["query"] += " Changed question"
    HistoryStore.write(path, report)
    with pytest.raises(ValueError, match="identity"):
        review.load_proposals(root, path)
    example = next(row for row in manifest["examples"] if row["split"] == "test")
    report["candidates"][0]["example_id"] = example["id"]
    HistoryStore.write(path, report)
    with pytest.raises(ValueError, match="training-family"):
        review.load_proposals(root, path)


@pytest.mark.asyncio
async def test_replay_preconditions_do_not_spend_model_calls(
    settings, synthetic, tmp_path, monkeypatch
):
    root, manifest, _ = synthetic
    path, _, _ = proposal_file(root, manifest, tmp_path)
    transport(
        monkeypatch,
        lambda _: pytest.fail("Invalid replay must fail before model inference"),
    )
    with pytest.raises(ValueError, match="student model"):
        await review.review_candidates(
            settings,
            corpus=root,
            candidates=path,
            destination=tmp_path / "review",
            profile=LOCAL,
            data_dir=tmp_path / "runtime",
        )


@pytest.mark.asyncio
async def test_generic_proposals_dry_run_and_quarantine(
    settings, synthetic, tmp_path, monkeypatch
):
    from graphmine_agent.learning.proposals import propose_candidates

    root, manifest, _ = synthetic
    calls = []

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        question = json.loads(body["messages"][1]["content"])["question"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"queries": ["Please help me: " + question]}
                            )
                        },
                    }
                ],
            },
        )

    transport(monkeypatch, handler)
    plan = await propose_candidates(
        settings,
        corpus=root,
        destination=tmp_path / "plan",
        profile=EXTERNAL,
        count=2,
    )
    assert not calls and plan["budget"]["calls"] == 0 and not plan["candidates"]
    result = await propose_candidates(
        settings,
        corpus=root,
        destination=tmp_path / "generated",
        profile=LOCAL,
        count=2,
        execute=True,
    )
    assert len(calls) == 2 and len(result["candidates"]) == 2
    assert all(row["training_eligible"] is False for row in result["candidates"])
    assert all(row["status"].startswith("quarantined") for row in result["candidates"])
    _, _, saved = review.load_proposals(
        root, tmp_path / "generated" / "candidates.json"
    )
    assert saved == result
    ids = {row["id"] for row in manifest["examples"] if row["split"] == "train"}
    assert all(row["example_id"] in ids for row in result["candidates"])


@pytest.mark.asyncio
async def test_review_without_calibration_or_replay_cannot_approve(
    settings, synthetic, tmp_path, monkeypatch
):
    root, manifest, _ = synthetic
    candidates, proposals, example = proposal_file(root, manifest, tmp_path)
    value = extraction(
        meaning.expected_meaning(example["task"]), proposals["candidates"][0]["query"]
    )
    transport(monkeypatch, lambda _: httpx.Response(200, json=local_response(value)))
    report = await review.review_candidates(
        settings,
        corpus=root,
        candidates=candidates,
        destination=tmp_path / "review",
        profile=LOCAL,
    )
    assert (
        report["screened"] == 1 and report["replayed"] == 0 and report["accepted"] == 0
    )
    assert not report["candidates"][0]["training_eligible"]
    assert "No passing live replay" in report["candidates"][0]["blockers"]


def test_saved_evidence_cannot_escape_directory(tmp_path):
    outside = tmp_path / "outside.json"
    HistoryStore.write(outside, {})
    inner = tmp_path / "inner"
    inner.mkdir()
    with pytest.raises(ValueError, match="escaped"):
        review.verified_artifact(inner, "../outside.json", HistoryStore.digest(outside))
