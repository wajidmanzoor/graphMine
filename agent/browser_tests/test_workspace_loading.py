"""Real browser loading regressions with controlled API response timing."""

from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

STATIC = Path(__file__).resolve().parents[1] / "graphmine_agent/static"
SESSION = {"id": "saved-session", "domain_id": "general", "title": "Saved conversation"}
CAPABILITIES = {
    "operations": [
        {
            "id": "k-core",
            "title": "K-core",
            "input_kind": "graph",
            "execution": {"cpu": True, "gpu": False},
            "parameters": {"requested_k": {"kind": "integer"}},
        }
    ],
    "device_configuration": {"gpu_configured": False},
    "question_planner_enabled": True,
}
WORKFLOW = {
    "id": "saved-analysis",
    "status": "awaiting_review",
    "mode": "interactive",
    "revision": 1,
    "input_files": {},
    "steps": {},
    "approved_hash": None,
    "validation": {
        "plan": {
            "device": "cpu",
            "steps": [
                {
                    "id": "core",
                    "operation": "k-core",
                    "input": {"input": "main"},
                    "parameters": {"requested_k": 2},
                    "bindings": {},
                }
            ],
        },
        "order": ["core"],
        "inputs": {},
        "workflow_hash": "authored-browser-fixture",
    },
}


def capability_response(status=200):
    return SimpleNamespace(
        started=threading.Event(),
        release=threading.Event(),
        finished=threading.Event(),
        status=status,
    )


@pytest.fixture
def loading_server():
    state = SimpleNamespace(
        responses=[capability_response()],
        calls=0,
        saved_analysis=False,
        files=[],
        events=[],
        workflows=[],
        results={},
        graph=None,
        plan_handler=None,
    )

    class Handler(BaseHTTPRequestHandler):
        def respond(self, value, status=200):
            self.send(json.dumps(value).encode(), "application/json", status)

        def send(self, raw, content_type, status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/analytics/capabilities":
                response = state.responses[state.calls]
                state.calls += 1
                response.started.set()
                response.release.wait(20)
                self.respond(
                    CAPABILITIES
                    if response.status == 200
                    else {"error": {"message": "The native runtime is unavailable"}},
                    response.status,
                )
                response.finished.set()
            elif path == "/api/domains":
                self.respond(
                    [
                        {
                            "id": "general",
                            "name": "General",
                            "description": "Explore a network",
                        }
                    ]
                )
            elif path == "/api/sessions":
                self.respond([SESSION])
            elif path.endswith("/workspace"):
                self.respond(
                    {
                        "session": SESSION,
                        "files": state.files,
                        "messages": [],
                        "events": state.events,
                    }
                )
            elif path.endswith("/workflows"):
                self.respond([WORKFLOW] if state.saved_analysis else state.workflows)
            elif path.startswith("/api/workflows/") and path.endswith("/result"):
                self.respond(state.results[path.split("/")[-2]])
            elif path.startswith("/api/workflows/") and state.workflows:
                self.respond(
                    next(
                        row
                        for row in state.workflows
                        if row["id"] == path.split("/")[-1]
                    )
                )
            elif path == "/api/workflows/saved-analysis":
                self.respond(WORKFLOW)
            elif path.endswith("/events"):
                after = int(parse_qs(urlsplit(self.path).query).get("after", [0])[0])
                self.respond(
                    [event for event in state.events if event["sequence"] > after]
                )
            elif path.endswith("/graph-preview"):
                self.respond(state.graph)
            else:
                file = STATIC / ("analytics.html" if path == "/" else path.lstrip("/"))
                if file.is_file() and file.resolve().is_relative_to(STATIC):
                    self.send(
                        file.read_bytes(),
                        mimetypes.guess_type(file)[0] or "application/octet-stream",
                    )
                else:
                    self.respond({}, 404)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path.endswith("/analytics/plan") and state.plan_handler:
                self.respond(state.plan_handler(json.loads(body)))
            else:
                self.respond(SESSION, 201)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield state
    finally:
        for response in state.responses:
            response.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.fixture
def loading_browser():
    root = Path("/snap/firefox/current/usr/lib/firefox")
    if not (root / "firefox").is_file() or not (root / "geckodriver").is_file():
        pytest.skip("Firefox and geckodriver are required for the browser gate")
    options = Options()
    options.add_argument("-headless")
    options.binary_location = str(root / "firefox")
    driver = webdriver.Firefox(
        options=options, service=Service(executable_path=str(root / "geckodriver"))
    )
    driver.set_window_size(1440, 1000)
    try:
        yield driver
    finally:
        driver.quit()


def wait_for(browser, expression):
    try:
        return WebDriverWait(browser, 5, poll_frequency=0.05).until(
            lambda driver: driver.execute_script(f"return {expression}")
        )
    except TimeoutException:
        pytest.fail(
            str(
                browser.execute_script(
                    "return {status: document.getElementById('connection-state').textContent, notice: document.getElementById('notice').textContent, errors: window.testErrors}"
                )
            )
        )


def open_domains(browser, server):
    browser.get(server.url)
    wait_for(
        browser,
        "document.querySelectorAll('.domain-card').length === 1 && !GraphMineWorkspace.state.busy",
    )
    assert server.responses[0].started.wait(1)
    assert not server.responses[0].release.is_set()


def reconnect(browser):
    browser.find_element(By.ID, "connection-button").click()
    browser.find_element(By.CSS_SELECTOR, "#connection-form [type=submit]").click()


def test_domains_and_new_conversation_do_not_wait_for_capabilities(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    open_domains(browser, server)
    browser.find_element(By.CSS_SELECTOR, ".domain-card").click()
    wait_for(
        browser,
        "GraphMineWorkspace.state.session?.id === 'saved-session' && !GraphMineWorkspace.state.busy",
    )
    assert browser.find_element(By.ID, "workspace-view").is_displayed()
    assert browser.find_element(By.ID, "data-upload").is_enabled()
    assert not browser.find_element(By.ID, "plan-question").is_enabled()
    assert not browser.find_element(By.ID, "use-operation").is_enabled()
    assert (
        browser.find_element(By.ID, "connection-state").text == "Checking calculations…"
    )
    server.responses[0].release.set()
    wait_for(
        browser,
        "document.getElementById('connection-state').textContent === 'Library ready'",
    )
    assert browser.find_element(By.ID, "plan-question").is_enabled()
    assert browser.find_element(By.ID, "use-operation").is_enabled()


def test_capability_failure_preserves_navigation_and_can_reconnect(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    server.responses[0].status = 503
    open_domains(browser, server)
    server.responses[0].release.set()
    wait_for(
        browser,
        "document.getElementById('connection-state').textContent === 'Analysis unavailable'",
    )
    assert browser.find_element(By.CSS_SELECTOR, ".domain-card").is_displayed()
    browser.find_element(By.CSS_SELECTOR, ".recent-session").click()
    wait_for(browser, "GraphMineWorkspace.state.session?.id === 'saved-session'")
    assert not browser.find_element(By.ID, "plan-question").is_enabled()
    server.responses.append(capability_response())
    server.responses[1].release.set()
    reconnect(browser)
    wait_for(
        browser,
        "document.getElementById('connection-state').textContent === 'Library ready' && !GraphMineWorkspace.state.busy",
    )
    assert browser.find_element(By.ID, "plan-question").is_enabled()


def test_saved_analysis_opens_before_capabilities_and_gains_edit_controls(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    server.saved_analysis = True
    browser.get(server.url + "/#workspace/saved-session/chat")
    wait_for(
        browser,
        "GraphMineWorkspace.state.record?.id === 'saved-analysis' && !GraphMineWorkspace.state.busy",
    )
    assert browser.find_element(By.ID, "workflow-panel").is_displayed()
    assert browser.find_element(By.ID, "notice").get_attribute("hidden")
    assert not browser.find_element(By.ID, "approve-plan").is_enabled()
    assert not browser.find_elements(By.CSS_SELECTOR, "[data-edit-step]")
    browser.execute_script(
        "window.testErrors = []; console.error = (...args) => testErrors.push(args.map(String));"
    )
    server.responses[0].release.set()
    wait_for(browser, "document.querySelector('[data-edit-step]') !== null")
    assert browser.find_element(By.ID, "approve-plan").is_enabled()


def test_old_capability_failure_cannot_overwrite_reconnected_state(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    server.responses[0].status = 503
    open_domains(browser, server)
    server.responses.append(capability_response())
    server.responses[1].release.set()
    reconnect(browser)
    wait_for(
        browser,
        "document.getElementById('connection-state').textContent === 'Library ready'",
    )
    server.responses[0].release.set()
    assert server.responses[0].finished.wait(1)
    assert browser.find_element(By.ID, "connection-state").text == "Library ready"
    assert browser.find_element(By.ID, "notice").get_attribute("hidden")
