from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.api import create_app
from graphmine_agent.graph_store import UploadError
from graphmine_agent.models import FileRole, RouteDecision
from graphmine_agent.planning import normalize_route
from graphmine_agent.terminal import ClientError, Terminal, agent_client


def test_csv_mapping_preserves_names_types_edge_and_vertex_attributes(
    graph_store, session
):
    content = b"employee,partner,source_label,target_label,source_type,target_type,source.department,target.department,year,reference,amount\n001,002,Ava,Ben,employee,employee,Design,Support,2026,0007,9007199254740993\n"
    record = graph_store.ingest(
        session_id=session.id,
        role=FileRole.graph,
        filename="projects.csv",
        content=content,
        source_column="employee",
        target_column="partner",
    )
    graph = graph_store.read_graph(record.id, session.id)
    assert graph["vertices"][0] == {
        "id": "001",
        "label": "Ava",
        "type": "employee",
        "attributes": {"department": "Design"},
    }
    assert graph["vertices"][1]["attributes"]["department"] == "Support"
    assert graph["edges"][0]["attributes"] == {
        "year": 2026,
        "reference": "0007",
        "amount": 9007199254740993,
    }
    assert record.metadata.semantic_context["entity_types"] == {"employee": 2}


def test_csv_unknown_headers_require_mapping_instead_of_becoming_fake_entities(
    graph_store, session
):
    with pytest.raises(UploadError, match="From and To"):
        graph_store.ingest(
            session_id=session.id,
            role=FileRole.graph,
            filename="people.csv",
            content=b"employee,partner\nAva,Ben\n",
        )


def test_upload_api_exposes_column_mapping_and_timestamp_unit(settings):
    with TestClient(create_app(settings)) as client:
        auth = {"Authorization": "Bearer test-secret"}
        session = client.post("/api/sessions", headers=auth, json={}).json()["id"]
        response = client.post(
            f"/api/sessions/{session}/files",
            headers=auth,
            files={
                "file": (
                    "events.csv",
                    b"sender,recipient,timestamp,protocol\na,b,1000,HTTPS\n",
                    "text/csv",
                )
            },
            data={
                "source_column": "sender",
                "target_column": "recipient",
                "timestamp_unit": "milliseconds",
                "directed": "true",
            },
        )
        assert response.status_code == 201, response.text
        assert (
            response.json()["metadata"]["semantic_context"]["timestamp_unit"]
            == "milliseconds"
        )
        assert (
            "attributes.protocol"
            in response.json()["metadata"]["semantic_context"]["edge_attributes"]
        )


def test_unknown_unsupported_problem_remains_a_clear_refusal(catalog):
    result = normalize_route(
        catalog,
        RouteDecision(
            problem_id="shortest_path",
            supported=False,
            confidence=0.9,
            explanation="I cannot find a fastest delivery route with the available tools.",
        ),
    )
    assert not result.supported and result.operation_id is None
    assert result.explanation.startswith("I cannot find")


def test_cli_exports_safe_offline_report_without_overwriting(
    settings, triangle_graph, tmp_path
):
    data = json.loads(triangle_graph)
    data["vertices"][0]["label"] = "</script><script>window.injected=true</script>"
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(data), encoding="utf-8")

    async def scenario():
        async with agent_client(settings, data_dir=settings.data_root) as (
            client,
            history_root,
        ):
            terminal = Terminal(
                client, history_root=history_root, output=lambda _: None
            )
            await terminal.start()
            await terminal.dispatch("/direction two-way")
            assert terminal.allow_directed_projection
            await terminal.load(graph_path)
            assert not terminal.allow_directed_projection
            await terminal.ask("Find every maximal clique")
            target = tmp_path / "answer.html"
            await terminal.dispatch(f'/view "{target}"')
            html = target.read_text(encoding="utf-8")
            assert "<script>window.injected=true</script>" not in html
            assert "\\u003c/script>" in html
            assert 'src="/app.js"' not in html and 'src="/vendor/' not in html
            assert 'id="graphmine-report"' in html
            assert target.stat().st_mode & 0o777 == 0o600
            saved = (
                history_root
                / terminal.session_id
                / "results"
                / terminal.result_id
                / "answer.html"
            )
            assert saved.is_file() and saved.stat().st_mode & 0o777 == 0o600
            with pytest.raises(ClientError, match="already exists"):
                await terminal.dispatch(f'/view "{target}"')

    asyncio.run(scenario())
