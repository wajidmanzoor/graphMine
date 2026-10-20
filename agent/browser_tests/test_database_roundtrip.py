"""Actual database/native/browser round trip; authored planner transport fixture.

The English prompt traverses the real planning and workflow APIs, but model
decisions are replayed. This is UI/integration evidence, not LLM accuracy evidence.
Run with the disposable local demo and GRAPHMINE_TEST_DATABASE_INTEGRATION=1.
"""

import os
import socket
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import test_workspace_loading as fixtures
import uvicorn
from graphmine_agent.analytics_planning import AnalyticsPlanner
from graphmine_agent.api import create_app
from graphmine_agent.config import Settings
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

loading_browser = fixtures.loading_browser
pytestmark = pytest.mark.skipif(
    os.getenv("GRAPHMINE_TEST_DATABASE_INTEGRATION") != "1",
    reason="requires the disposable database demo",
)


@pytest.fixture
def database_server(tmp_path, monkeypatch):
    root = Path(
        os.getenv("GRAPHMINE_TEST_RUNTIME_ROOT", Path(__file__).resolve().parents[2])
    )
    settings = replace(
        Settings.from_env(root),
        accounts_enabled=False,
        api_token="test-secret",
        llm_enabled=True,
        data_root=tmp_path / "browser-agent",
        analytics_python=Path(sys.executable),
        native_runtime_library=root / "library/build/runtime/libgraphmine_runtime.so",
        graph_gpu_uuid=None,
        llm_gpu_uuid=None,
        analytics_gpu_uuids=(),
        job_timeout_seconds=60,
    )
    calls = []

    async def generated(self, stage, payload, schema, catalog=None):
        calls.append((stage, payload))
        if stage == "route":
            return {
                "intent": "calculate",
                "operations": ["densest-subgraph"],
                "message": "Find the densest group.",
            }
        return {
            "status": "ready",
            "message": "Find the densest group.",
            "plan": {
                "version": 1,
                "device": payload["device_policy"],
                "steps": [
                    {
                        "id": "dense",
                        "operation": "densest-subgraph",
                        "input": {"input": "main"},
                        "parameters": {},
                        "bindings": {},
                    }
                ],
            },
        }

    async def answer(settings, question, facts):
        return {
            "lead": "The densest group is ready to inspect.",
            "fact_ids": [f["id"] for f in facts[:4]],
        }

    monkeypatch.setattr(AnalyticsPlanner, "_generate", generated)
    monkeypatch.setattr("graphmine_agent.analytics_answers.compose", answer)
    app = create_app(settings)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    try:
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        ready = httpx.get(
            url + "/api/analytics/capabilities",
            headers={"Authorization": "Bearer test-secret"},
            timeout=90,
        )
        assert ready.status_code == 200, ready.text
        yield SimpleNamespace(url=url, app=app, calls=calls)
    finally:
        server.should_exit = True
        thread.join(15)
        sock.close()


def wait(browser, expression):
    try:
        return WebDriverWait(browser, 60, poll_frequency=0.1).until(
            lambda d: d.execute_script("return " + expression)
        )
    except TimeoutException:
        pytest.fail(
            str(
                browser.execute_script(
                    "return {notice: document.getElementById('notice')?.textContent, query: document.getElementById('database-query-status')?.textContent, record: GraphMineWorkspace?.state.record, errors: window.browserErrors}"
                )
            )
        )


def click(browser, id):
    button = browser.find_element(By.ID, id)
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", button)
    button.click()


def screenshot(browser, name):
    if os.getenv("GRAPHMINE_TEST_SCREENSHOTS"):
        directory = Path(os.environ["GRAPHMINE_TEST_SCREENSHOTS"])
        directory.mkdir(parents=True, exist_ok=True)
        browser.save_screenshot(str(directory / name))


def test_database_cypher_chat_dense_result_and_enrichment(
    loading_browser, database_server
):
    browser, server = loading_browser, database_server
    browser.get(server.url)
    browser.execute_script("localStorage.setItem('graphmine.apiToken', 'test-secret')")
    browser.refresh()
    wait(browser, "GraphMineWorkspace.state.caps && !GraphMineWorkspace.state.busy")
    browser.execute_script(
        "window.browserErrors=[]; window.addEventListener('error', e => browserErrors.push(e.message))"
    )
    click(browser, "open-database-workspace")
    wait(browser, "document.getElementById('database-workspace')?.open")
    Select(browser.find_element(By.ID, "database-source")).select_by_value(
        "local-transfers"
    )
    Select(browser.find_element(By.ID, "query-graph-direction")).select_by_value(
        "undirected"
    )
    click(browser, "preview-cypher")
    wait(
        browser,
        "document.getElementById('database-query-status').textContent.includes('8 vertices') && !GraphMineWorkspace.state.busy",
    )
    assert (
        "10 relationships" in browser.find_element(By.ID, "database-query-status").text
    )
    screenshot(browser, "database-query.png")
    click(browser, "run-cypher-chat")
    wait(
        browser,
        "GraphMineWorkspace.state.session && GraphMineWorkspace.state.active && !GraphMineWorkspace.state.busy && GraphMineWorkspace.state.view==='chat'",
    )
    original = browser.execute_script("return GraphMineWorkspace.state.active")
    assert browser.find_element(By.ID, "database-context").is_displayed()
    browser.find_element(By.ID, "question").send_keys(
        "Find the densest subgraph and show just that group."
    )
    click(browser, "plan-question")
    wait(
        browser,
        "GraphMineWorkspace.state.record?.status==='completed' && GraphMineWorkspace.state.resultView?.graph_available && GraphMineWorkspace.state.cy?.nodes().length===4",
    )
    assert browser.execute_script("return GraphMineWorkspace.state.view") == "results"
    assert (
        browser.execute_script("return GraphMineWorkspace.state.cy.edges().length") == 6
    )
    screenshot(browser, "densest-result.png")
    assert server.calls
    Select(browser.find_element(By.ID, "result-view-mode")).select_by_value("context")
    wait(
        browser,
        "GraphMineWorkspace.state.resultView?.context && GraphMineWorkspace.state.cy?.nodes().length===8",
    )
    assert (
        browser.execute_script(
            "return GraphMineWorkspace.state.cy.nodes('.chosen').length"
        )
        == 4
    )
    Select(browser.find_element(By.ID, "result-view-mode")).select_by_value("focus")
    wait(
        browser,
        "!GraphMineWorkspace.state.resultView.context && GraphMineWorkspace.state.cy.nodes().length===4",
    )
    click(browser, "enrich-attributes")
    wait(browser, "document.getElementById('enrichment-dialog')?.open")
    click(browser, "apply-enrichment")
    wait(
        browser,
        "document.getElementById('use-enriched-graph') && !GraphMineWorkspace.state.busy",
    )
    assert "4 entities enriched" in browser.find_element(
        By.ID, "enrichment-note"
    ).get_attribute("textContent")
    browser.find_element(By.CSS_SELECTOR, "#enrichment-dialog .quiet").click()
    Select(browser.find_element(By.ID, "attribute-color")).select_by_value("country")
    assert (
        browser.execute_script(
            "return new Set(GraphMineWorkspace.state.cy.nodes().map(n=>n.style('background-color'))).size"
        )
        == 4
    )
    Select(browser.find_element(By.ID, "attribute-color")).select_by_value("risk_score")
    assert (
        browser.execute_script(
            "return new Set(GraphMineWorkspace.state.cy.nodes().map(n=>n.style('background-color'))).size"
        )
        == 4
    )
    Select(browser.find_element(By.ID, "attribute-color")).select_by_value("country")
    Select(browser.find_element(By.ID, "attribute-label")).select_by_value("risk_score")
    assert sorted(
        browser.execute_script(
            "return GraphMineWorkspace.state.cy.nodes().map(n=>n.data('label'))"
        )
    ) == ["60", "73", "85", "91"]
    screenshot(browser, "enriched-result.png")
    # Changing view retains fetched attribute overlays, including the larger input context.
    Select(browser.find_element(By.ID, "result-view-mode")).select_by_value("context")
    wait(browser, "GraphMineWorkspace.state.cy.nodes().length===8")
    assert (
        browser.execute_script(
            "return GraphMineWorkspace.state.cy.nodes().filter(n=>n.data('original').attributes?.risk_score!==undefined).length"
        )
        == 4
    )
    Select(browser.find_element(By.ID, "result-view-mode")).select_by_value("focus")
    wait(browser, "GraphMineWorkspace.state.cy.nodes().length===4")
    click(browser, "enrich-relationships")
    wait(browser, "document.getElementById('enrichment-dialog')?.open")
    click(browser, "apply-enrichment")
    wait(
        browser,
        "document.getElementById('use-enriched-graph') && !GraphMineWorkspace.state.busy",
    )
    assert "1 vertices and 1 relationships" in browser.find_element(
        By.ID, "enrichment-note"
    ).get_attribute("textContent")
    click(browser, "use-enriched-graph")
    wait(
        browser,
        "GraphMineWorkspace.state.view==='chat' && !GraphMineWorkspace.state.busy",
    )
    assert browser.execute_script("return GraphMineWorkspace.state.active") != original
    assert not browser.execute_script("return window.browserErrors")


def test_shortest_path_destination_shows_only_its_witness(
    loading_browser, database_server
):
    browser, server = loading_browser, database_server
    with httpx.Client(
        base_url=server.url, headers={"Authorization": "Bearer test-secret"}, timeout=60
    ) as client:
        response = client.post(
            "/api/database-sources/local-transfers/queries",
            json={"statement": "MATCH p=(a:Account)-[:TRANSFER]->(b:Account) RETURN p"},
        )
        assert response.status_code == 201, response.text
        snapshot = response.json()
        names = {v["label"]: v["id"] for v in snapshot["graph"]["vertices"]}
        opened = client.post(
            f"/api/database-query-snapshots/{snapshot['dataset']['id']}/chat", json={}
        ).json()
        response = client.post(
            f"/api/sessions/{opened['session']['id']}/workflows",
            json={
                "mode": "normal",
                "inputs": {"main": {"file_id": opened["file"]["id"], "kind": "graph"}},
                "plan": {
                    "version": 1,
                    "device": "cpu",
                    "steps": [
                        {
                            "id": "shortest",
                            "operation": "single-source-shortest-paths",
                            "input": {"input": "main"},
                            "parameters": {"source": names["Ada"]},
                        }
                    ],
                },
            },
        )
        assert response.status_code == 201, response.text
        record = response.json()
        deadline = time.monotonic() + 60
        while record["status"] in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.05)
            record = client.get(f"/api/workflows/{record['id']}").json()
        assert record["status"] == "completed", record
        output = client.get(f"/api/workflows/{record['id']}/result").json()["steps"][
            "shortest"
        ]["result"]
        index = next(
            i
            for i, r in enumerate(output["ports"]["distances"]["value"])
            if r["vertex"] == names["Chen"]
        )
    browser.get(server.url)
    browser.execute_script("localStorage.setItem('graphmine.apiToken', 'test-secret')")
    browser.get(
        f"{server.url}/#workspace/{opened['session']['id']}/results/{record['id']}"
    )
    browser.refresh()
    wait(
        browser,
        "Boolean(GraphMineWorkspace.state.resultView && GraphMineWorkspace.state.cy)",
    )
    Select(browser.find_element(By.ID, "result-destination")).select_by_value(
        str(index)
    )
    wait(
        browser,
        "GraphMineWorkspace.state.cy.nodes().length===3 && GraphMineWorkspace.state.cy.edges().length===2",
    )
    assert set(
        browser.execute_script(
            "return GraphMineWorkspace.state.cy.nodes().map(n=>n.data('original').label)"
        )
    ) == {"Ada", "Ben", "Chen"}
    assert "distance: 20" in browser.find_element(By.ID, "result-building-block").text
    assert "Hana" in browser.find_element(By.ID, "result-destination").text
    browser.execute_script(
        "document.getElementById('network').scrollIntoView({block:'center'})"
    )
    screenshot(browser, "shortest-path.png")
    browser.execute_script(
        "document.getElementById('result-view-mode').scrollIntoView({block:'center'})"
    )
    Select(browser.find_element(By.ID, "result-view-mode")).select_by_value("context")
    wait(
        browser,
        "GraphMineWorkspace.state.cy.nodes().length===8 && GraphMineWorkspace.state.cy.edges().length===10",
    )
    assert (
        browser.execute_script(
            "return GraphMineWorkspace.state.cy.edges('.chosen').length"
        )
        == 2
    )
    assert (
        browser.execute_script(
            "return GraphMineWorkspace.state.cy.edges('.faded').length"
        )
        == 8
    )
    click(browser, "clear-selection")
    assert (
        browser.execute_script(
            "return GraphMineWorkspace.state.cy.elements('.chosen').length"
        )
        == 0
    )


@pytest.mark.parametrize("width,height", [(390, 844), (1440, 1000)])
def test_database_query_dialog_fits_viewport(
    loading_browser, database_server, width, height
):
    browser = loading_browser
    browser.browsing_context.set_viewport(
        context=browser.current_window_handle,
        viewport={"width": width, "height": height},
    )
    browser.get(database_server.url)
    browser.execute_script("localStorage.setItem('graphmine.apiToken', 'test-secret')")
    browser.refresh()
    wait(browser, "GraphMineWorkspace.state.caps && !GraphMineWorkspace.state.busy")
    click(browser, "open-database-workspace")
    wait(browser, "document.getElementById('database-workspace')?.open")
    assert browser.execute_script(
        "const d=document.getElementById('database-workspace'); const r=d.getBoundingClientRect(); return r.left>=0 && r.right<=innerWidth && d.scrollWidth<=d.clientWidth+1"
    )
