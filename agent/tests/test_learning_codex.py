from __future__ import annotations

import copy
import json
import sys

import pytest
from graphmine_agent.learning import codex, corpus, inference, meaning, review
from graphmine_agent.learning.inference import (
    LearningModel,
    ModelProfile,
    RequestBudget,
)
from graphmine_agent.learning.teacher import ParaphraseBatch

PROFILE = ModelProfile("codex", "gpt-6-astra")


def stream(text, **usage):
    return "\n".join(
        json.dumps(row)
        for row in [
            {"type": "thread.started", "thread_id": "isolated-thread"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {"id": "answer", "type": "agent_message", "text": text},
            },
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 300, "output_tokens": 100, **usage},
            },
        ]
    )


def fake_cli(
    monkeypatch, *, response=None, login="Logged in using ChatGPT\n", exit_code=0
):
    calls = []
    monkeypatch.setattr(codex.shutil, "which", lambda _: sys.executable)

    async def run(argv, *, cwd, stdin="", timeout=20):
        calls.append({"argv": argv, "cwd": cwd, "stdin": stdin})
        assert cwd.is_dir()
        if "login" in argv:
            return 0, "", login
        if "--version" in argv:
            return 0, "codex-cli 0.160.0\n", ""
        assert sorted(path.name for path in cwd.iterdir()) == ["output.schema.json"]
        assert "--ignore-user-config" in argv and "--ephemeral" in argv
        assert argv[argv.index("--sandbox") + 1] == "read-only"
        assert 'forced_login_method="chatgpt"' in argv
        assert "features.shell_tool=false" in argv
        assert "features.apps=false" in argv
        assert "features.plugins=false" in argv
        assert "features.hooks=false" in argv
        assert "features.multi_agent=false" in argv
        assert not any(value.startswith("model_providers.") for value in argv)
        assert "project_doc_max_bytes=0" in argv
        value = response or stream('{"queries":["An application question?"]}')
        return exit_code, value, ""

    monkeypatch.setattr(codex, "run_process", run)
    monkeypatch.setattr(
        inference.httpx,
        "AsyncClient",
        lambda **_: pytest.fail("Codex must not create an API client"),
    )
    return calls


def test_codex_environment_keeps_auth_location_but_strips_credentials(monkeypatch):
    for name in (
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "CODEX_ACCESS_TOKEN",
        "GRAPHMINE_LLM_API_KEY",
        "OPENAI_BASE_URL",
        "HTTP_PROXY",
        "BASH_ENV",
        "NODE_OPTIONS",
        "CODEX_THREAD_ID",
    ):
        monkeypatch.setenv(name, "test-secret-value")
    import os

    actual = codex.child_environment()
    assert actual["HOME"] == os.environ["HOME"]
    assert not any("KEY" in name or "TOKEN" in name for name in actual)
    assert "OPENAI_BASE_URL" not in actual and "BASH_ENV" not in actual
    assert "NODE_OPTIONS" not in actual and "CODEX_THREAD_ID" not in actual
    assert "test-secret-value" not in codex.redact(
        "test-secret-value sk-fake-other-secret"
    )


def test_codex_profile_and_explicit_consent(settings, monkeypatch):
    calls = fake_cli(monkeypatch)
    assert PROFILE.public()["base_url"] == "codex://chatgpt"
    assert (
        PROFILE.public()["execution_policy"]["config"]["forced_login_method"]
        == "chatgpt"
    )
    with pytest.raises(ValueError, match="allow-codex"):
        LearningModel(settings, PROFILE, RequestBudget(), allow_external=True)
    with pytest.raises(ValueError, match="plan allowance"):
        LearningModel(settings, PROFILE, RequestBudget(5), allow_codex=True)
    with pytest.raises(ValueError):
        ModelProfile("codex", "gpt-6-astra", "https://example.com")
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "login",
    [
        "Logged in using an API key",
        "Not logged in",
        "",
        "Logged in using ChatGPT\nUnexpected gateway",
    ],
)
async def test_codex_preflight_refuses_non_chatgpt(settings, monkeypatch, login):
    calls = fake_cli(monkeypatch, login=login)
    with pytest.raises(ValueError, match="signed in with ChatGPT"):
        async with LearningModel(settings, PROFILE, RequestBudget(), allow_codex=True):
            pytest.fail("No inference may start")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_codex_generation_records_evidence_and_honors_call_limit(
    settings, tmp_path, monkeypatch
):
    calls = fake_cli(monkeypatch)
    budget = RequestBudget(max_calls=1)
    artifact = tmp_path / "call.json"
    async with LearningModel(settings, PROFILE, budget, allow_codex=True) as model:
        result = await model.generate(
            system="Return application wording",
            payload={"question": "Who works together?"},
            schema=ParaphraseBatch,
            artifact=artifact,
        )
        assert result.queries == ["An application question?"]
        with pytest.raises(ValueError, match="budget"):
            await model.generate(
                system="No second request",
                payload={},
                schema=ParaphraseBatch,
                artifact=tmp_path / "unused.json",
            )
    saved = json.loads(artifact.read_text())
    assert saved["codex_cli"]["auth"] == "chatgpt" and saved["status"] == "completed"
    assert saved["usage"]["output_tokens"] == 100
    assert saved["request"]["input"] == {"question": "Who works together?"}
    assert saved["reservation"]["output_token_limit"] is None
    assert saved["reservation"]["reserved_usd"] == 0
    assert budget.calls == 1 and len(calls) == 3
    assert not calls[-1]["cwd"].exists()
    assert artifact.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "mutation",
    [
        "tool",
        "failed",
        "incomplete",
        "duplicate",
        "no_usage",
        "over_limit",
        "bad_json",
        "many_answers",
    ],
)
def test_codex_stream_rejects_invalid_or_unblinded_output(mutation):
    raw = stream("{}")
    events = [json.loads(line) for line in raw.splitlines()]
    if mutation == "tool":
        events[2]["item"]["type"] = "command_execution"
    elif mutation == "failed":
        events[-1]["type"] = "turn.failed"
    elif mutation == "incomplete":
        events.pop()
    elif mutation == "duplicate":
        events.insert(1, copy.deepcopy(events[0]))
    elif mutation == "no_usage":
        events[-1]["usage"] = {}
    elif mutation == "over_limit":
        events[-1]["usage"]["output_tokens"] = 9000
    elif mutation == "many_answers":
        events.insert(3, copy.deepcopy(events[2]))
    raw = (
        "invalid"
        if mutation == "bad_json"
        else "\n".join(json.dumps(row) for row in events)
    )
    with pytest.raises(ValueError):
        codex.parse_stream(raw, 4096)


@pytest.mark.asyncio
async def test_codex_process_failure_stops_further_calls(
    settings, tmp_path, monkeypatch
):
    calls = fake_cli(monkeypatch, exit_code=1)
    budget = RequestBudget(max_calls=10)
    async with LearningModel(settings, PROFILE, budget, allow_codex=True) as model:
        with pytest.raises(ValueError, match="No fallback"):
            await model.generate(
                system="task",
                payload={},
                schema=ParaphraseBatch,
                artifact=tmp_path / "failed.json",
            )
        assert budget.stopped
        with pytest.raises(ValueError, match="stopped"):
            await model.generate(
                system="task",
                payload={},
                schema=ParaphraseBatch,
                artifact=tmp_path / "not-run.json",
            )
    assert len(calls) == 3
    assert json.loads((tmp_path / "failed.json").read_text())["status"] == "failed"


@pytest.mark.asyncio
async def test_codex_dry_run_does_not_read_auth_or_run_cli(
    settings, tmp_path, monkeypatch
):
    calls = fake_cli(monkeypatch)
    root = tmp_path / "corpus"
    corpus.generate_corpus(root, graphs_per_family=1)
    report = await review.compare_teachers(
        settings, corpus=root, destination=tmp_path / "plan", profiles=[PROFILE]
    )
    assert not calls and not report["executed"] and report["budget"]["calls"] == 0
    assert not report["models"][0]["qualified_for_screening"]


@pytest.mark.asyncio
async def test_codex_extraction_is_reverified_from_raw_stream(
    settings, tmp_path, monkeypatch
):
    root = tmp_path / "corpus"
    manifest = corpus.generate_corpus(root, graphs_per_family=1)
    _, graphs = corpus.load_corpus(root)
    example = manifest["examples"][0]
    query = example["task"]["query"]
    value = meaning.MeaningExtraction(
        meaning=meaning.expected_meaning(example["task"]),
        evidence=[meaning.EvidenceSpan(field="goal", quote=query)],
    )
    fake_cli(monkeypatch, response=stream(value.model_dump_json()))
    artifact = tmp_path / "call.json"
    graph = graphs[example["graph_id"]]
    async with LearningModel(
        settings, PROFILE, RequestBudget(), allow_codex=True
    ) as model:
        await model.generate(
            system=meaning.EXTRACTION_SYSTEM,
            payload=review.blind_payload(graph, query),
            schema=meaning.MeaningExtraction,
            artifact=artifact,
        )
    saved = json.loads(artifact.read_text())
    review.verify_extraction_call(
        saved, PROFILE, graph, query, value.model_dump(mode="json")
    )
    saved["codex_cli"]["auth"] = "api"
    with pytest.raises(ValueError, match="ChatGPT"):
        review.verify_extraction_call(
            saved, PROFILE, graph, query, value.model_dump(mode="json")
        )


@pytest.mark.asyncio
async def test_real_process_wrapper_bounds_output_and_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-for-child")
    code, stdout, _ = await codex.run_process(
        [sys.executable, "-c", "import os; print('OPENAI_API_KEY' in os.environ)"],
        cwd=tmp_path,
    )
    assert code == 0 and stdout.strip() == "False"
    with pytest.raises(TimeoutError):
        await codex.run_process(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            cwd=tmp_path,
            timeout=0.05,
        )
    monkeypatch.setattr(codex, "OUTPUT_BYTES", 100)
    with pytest.raises(ValueError, match="byte limit"):
        await codex.run_process(
            [sys.executable, "-c", "print('x' * 1000)"], cwd=tmp_path
        )
