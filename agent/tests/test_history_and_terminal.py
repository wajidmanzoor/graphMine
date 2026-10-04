from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from graphmine_agent.api import create_app
from graphmine_agent.config import Settings
from graphmine_agent.history import HistoryStore
from graphmine_agent.llm import LLMError, OpenAICompatibleModel
from graphmine_agent.models import LLMMode, RouteDecision
from graphmine_agent.terminal import ClientError, Terminal, agent_client

AUTH = {"Authorization": "Bearer test-secret"}


def events(root: Path) -> list[dict]:
    return [
        json.loads(path.read_text())
        for path in sorted((root / "events").glob("*.json"))
    ]


def test_cli_upload_run_feedback_followup_resume_and_export(
    settings: Settings, triangle_graph: bytes, tmp_path: Path
):
    source = tmp_path / "graph.json"
    source.write_bytes(triangle_graph)

    async def scenario():
        async with agent_client(settings, data_dir=settings.data_root) as (
            client,
            history_root,
        ):
            terminal = Terminal(
                client, history_root=history_root, output=lambda _: None
            )
            await terminal.start(domain_id="fraud_detection")
            await terminal.dispatch(f'/load "{source}"')
            await terminal.dispatch("Find every maximal clique in these accounts.")
            original_result = terminal.result_id
            original_turn = terminal.turn_id
            assert original_result
            await terminal.dispatch(
                "/feedback The groups need names | Show the account names alongside every group"
            )
            record = (
                await terminal.request(
                    "GET", f"/api/sessions/{terminal.session_id}/feedback"
                )
            )[0]
            assert record["result_id"] == original_result
            assert record["turn_id"] == original_turn
            assert record["source"] == "user"
            await terminal.dispatch(
                "/explain What does this mean for the investigation?"
            )
            assert terminal.result_id == original_result
            await terminal.dispatch("/plan Compute every maximal clique again")
            assert terminal.job_id is None
            jobs = await terminal.request(
                "GET", "/api/jobs", params={"session_id": terminal.session_id}
            )
            assert len(jobs) == 1
            root = history_root / terminal.session_id
            recorded = events(root)
            assert (
                len([item for item in recorded if item["type"] == "result.saved"]) == 5
            )
            assert any(item["type"] == "model.input" for item in recorded)
            artifacts = root / "jobs" / jobs[0]["id"]
            for name in (
                "inputs.json",
                "command.json",
                "result.json",
                "stdout.log",
                "stderr.log",
                "process.json",
            ):
                assert (artifacts / name).is_file(), name
            archived_graph = root / "files" / terminal.graph_id
            assert (archived_graph / "original").read_bytes() == triangle_graph
            assert json.loads((archived_graph / "canonical.json").read_text())[
                "vertices"
            ]
            destination = tmp_path / "session.zip"
            await terminal.export(destination)
            with zipfile.ZipFile(destination) as bundle:
                assert any(
                    name.endswith("visualizations.json") for name in bundle.namelist()
                )
                assert any("/feedback/" in name for name in bundle.namelist())
                assert all(
                    name.startswith(terminal.session_id + "/")
                    for name in bundle.namelist()
                )
            with pytest.raises(ClientError, match="already exists"):
                await terminal.export(destination)
            return terminal.session_id

    session_id = asyncio.run(scenario())

    async def resume():
        async with agent_client(settings, data_dir=settings.data_root) as (
            client,
            root,
        ):
            terminal = Terminal(client, history_root=root, output=lambda _: None)
            await terminal.start(session_id=session_id)
            assert terminal.graph_id
            # The last turn was a plan preview; feedback should target it.
            assert terminal.result_id is None
            assert terminal.turn_id
            feedback = await terminal.request(
                "GET", f"/api/sessions/{session_id}/feedback"
            )
            assert len(feedback) == 1

    asyncio.run(resume())


def test_no_graph_failed_calls_and_feedback_are_recorded(
    settings: Settings, triangle_graph: bytes
):
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/sessions", headers=AUTH, json={}).json()["id"]
        response = client.post(
            f"/api/sessions/{session}/chat",
            headers=AUTH,
            json={"message": "Help me find suspicious activity."},
        ).json()
        assert "Upload" in response["message"]
        turn_id = response["turn_id"]
        root = settings.history_root / session
        assert json.loads((root / "turns" / f"{turn_id}.json").read_text())["request"][
            "message"
        ]
        graph = client.post(
            f"/api/sessions/{session}/files",
            headers=AUTH,
            files={"file": ("graph.json", triangle_graph, "application/json")},
        ).json()

        async def broken(**kwargs):
            raise LLMError("deliberate model failure")

        client.app.state.runtime.agent.model.generate = broken
        failed = client.post(
            f"/api/sessions/{session}/chat",
            headers=AUTH,
            json={
                "message": "Find suspicious rings.",
                "graph_id": graph["id"],
            },
        )
        assert failed.status_code == 503
        failed_turn = failed.json()["turn_id"]
        assert failed_turn and failed_turn != turn_id
        feedback = client.post(
            f"/api/sessions/{session}/feedback",
            headers=AUTH,
            json={
                "what_went_wrong": "It failed",
                "expected_behavior": "Explain my data",
                "turn_id": failed_turn,
            },
        )
        assert feedback.status_code == 201
        assert feedback.json()["result_id"] is None
        assert any(
            item["type"] == "chat.error" and item["turn_id"] == failed_turn
            for item in events(root)
        )
        archive = client.get(f"/api/sessions/{session}/history/archive", headers=AUTH)
        assert archive.status_code == 200
        assert zipfile.is_zipfile(io.BytesIO(archive.content))
        assert client.get(f"/api/sessions/{session}/history").status_code == 401


def test_feedback_validation_and_slash_command_skip_llm(settings: Settings):
    with TestClient(create_app(settings)) as client:
        one = client.post("/api/sessions", headers=AUTH, json={}).json()["id"]
        two = client.post("/api/sessions", headers=AUTH, json={}).json()["id"]
        turn = client.post(
            f"/api/sessions/{one}/chat", headers=AUTH, json={"message": "Help"}
        ).json()["turn_id"]
        for values in (
            {"turn_id": turn},
            {"turn_id": "../../escape"},
            {"what_went_wrong": "   "},
        ):
            response = client.post(
                f"/api/sessions/{two}/feedback",
                headers=AUTH,
                json={
                    "what_went_wrong": "No explanation",
                    "expected_behavior": "An explanation",
                    **values,
                },
            )
            assert response.status_code == 422

        async def forbidden(**kwargs):
            raise AssertionError("feedback must never call the model")

        client.app.state.runtime.agent.model.generate = forbidden
        response = client.post(
            f"/api/sessions/{one}/chat",
            headers=AUTH,
            json={
                "message": "/feedback I could not upload a spreadsheet | Help me map the columns",
            },
        )
        assert response.status_code == 200
        assert response.json()["feedback_id"]
        assert not response.json()["job_id"]


def test_raw_model_request_and_invalid_response_survive_validation(settings: Settings):
    history = HistoryStore(settings.history_root)

    async def scenario():
        model = OpenAICompatibleModel(settings, history)
        await model._client.aclose()
        model._client = httpx.AsyncClient(
            base_url="http://model.test",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"choices": [{"message": {"content": "invalid JSON"}}]}
                )
            ),
        )
        with (
            history.scope("session_test", "chat", {"message": "Find bridge accounts"}),
            pytest.raises(LLMError),
        ):
            await model.generate(
                mode=LLMMode.planner,
                schema=RouteDecision,
                user_payload={"message": "Find bridge accounts"},
            )
        await model.close()

    asyncio.run(scenario())
    recorded = events(settings.history_root / "session_test")
    request = next(item for item in recorded if item["type"] == "llm.request")
    response = next(item for item in recorded if item["type"] == "llm.response")
    assert request["data"]["call_id"] == response["data"]["call_id"]
    assert request["data"]["request"]["messages"][0]["role"] == "system"
    assert "invalid JSON" in response["data"]["body"]
    assert settings.llm_api_key not in json.dumps(recorded)


def test_two_local_clients_cannot_start_workers_on_same_store(settings: Settings):
    async def scenario():
        async with agent_client(settings, data_dir=settings.data_root):
            with pytest.raises(ClientError, match="Another local CLI"):
                async with agent_client(settings, data_dir=settings.data_root):
                    pass

    asyncio.run(scenario())


def test_failed_execution_keeps_raw_artifacts_and_feedback_target(
    settings: Settings, triangle_graph: bytes, tmp_path: Path
):
    binary = settings.graphmine_binary
    binary.write_text(
        binary.read_text().replace(
            'output.write_text(json.dumps(payload), encoding="utf-8")',
            'output.write_text("not json", encoding="utf-8")',
        )
    )
    source = tmp_path / "input.json"
    source.write_bytes(triangle_graph)

    async def scenario():
        async with agent_client(settings, data_dir=settings.data_root) as (
            client,
            history_root,
        ):
            terminal = Terminal(
                client, history_root=history_root, output=lambda _: None
            )
            await terminal.start()
            await terminal.load(source)
            with pytest.raises(ClientError, match="invalid result JSON"):
                await terminal.ask("Find every maximal clique")
            feedback = await terminal.feedback(
                "The computation failed", "Explain the groups"
            )
            assert feedback["job_id"] == terminal.job_id
            assert feedback["turn_id"] == terminal.turn_id
            root = history_root / terminal.session_id / "jobs" / terminal.job_id
            assert (root / "result.json").read_text() == "not json"
            assert json.loads((root / "command.json").read_text())[1] == "run"
            assert (root / "stderr.log").is_file()

    asyncio.run(scenario())


def test_real_cli_entrypoint_batch_and_interactive_feedback(
    settings: Settings, triangle_graph: bytes, tmp_path: Path
):
    source = tmp_path / "graph with spaces.json"
    source.write_bytes(triangle_graph)
    environment = dict(
        os.environ,
        GRAPHMINE_LLM_ENABLED="false",
        GRAPHMINE_BINARY=str(settings.graphmine_binary),
        GRAPHMINE_HISTORY_ROOT="",
    )
    command = [
        sys.executable,
        "-m",
        "graphmine_agent",
        "chat",
        "--data-dir",
        str(settings.data_root),
        "--graph",
        str(source),
        "--message",
        "Find every maximal clique",
        "--message",
        "/feedback Too technical | Explain the account groups",
        "--message",
        "/history",
    ]
    completed = subprocess.run(
        command,
        env=environment,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert "Feedback saved" in completed.stdout
    assert "Analysis completed" in completed.stdout
    interactive = subprocess.run(
        command[:8],
        env=environment,
        input="/feedback\nNo explanation\nExplain the groups\n/quit\n",
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert interactive.returncode == 0, interactive.stderr
    assert "Feedback saved" in interactive.stdout


def test_history_context_isolated_between_concurrent_sessions(settings: Settings):
    history = HistoryStore(settings.history_root)

    async def scenario(session_id):
        with history.scope(session_id, "chat", {"message": session_id}):
            await asyncio.sleep(0.01)
            history.current("llm.request", {"owner": session_id})

    async def run():
        await asyncio.gather(scenario("session_one"), scenario("session_two"))

    asyncio.run(run())
    for session_id in ("session_one", "session_two"):
        event = next(
            item
            for item in events(settings.history_root / session_id)
            if item["type"] == "llm.request"
        )
        assert event["session_id"] == event["data"]["owner"] == session_id


def test_analyst_failure_keeps_computed_answer_and_reports_source(
    settings: Settings, triangle_graph: bytes, tmp_path: Path
):
    from graphmine_agent.models import GroundedNarrative

    app = create_app(settings)
    source = tmp_path / "graph.json"
    source.write_bytes(triangle_graph)

    async def scenario():
        async with app.router.lifespan_context(app):
            original = app.state.runtime.agent.model.generate

            async def failing_analyst(**kwargs):
                if kwargs["schema"] is GroundedNarrative:
                    raise LLMError("Completion budget exhausted")
                return await original(**kwargs)

            app.state.runtime.agent.model.generate = failing_analyst
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers=AUTH,
            ) as client:
                lines = []
                terminal = Terminal(client, output=lines.append)
                await terminal.start()
                await terminal.load(source)
                outcome = await terminal.ask("Find every maximal clique")
                assert outcome["result"]["interpretation_source"] == "fallback"
                limitations = outcome["result"]["interpretation"]["limitations"]
                assert all("disabled" not in text for text in limitations)
                assert any(
                    "Computed output preview" in line and "cliques" in line
                    for line in lines
                )
                followup = await terminal.ask("Explain these groups")
                assert followup["response"]["interpretation_source"] == "fallback"
                feedback = await terminal.feedback(
                    "I wanted an explanation", "Explain the named groups"
                )
                assert feedback["result_id"] == terminal.result_id

    asyncio.run(scenario())
