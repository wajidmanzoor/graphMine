"""Real account, sharing and connector browser workflows in a temporary store."""

import json
import socket
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
import uvicorn
from graphmine_agent.analytics import AnalyticsService
from graphmine_agent.api import create_app
from graphmine_agent.config import Settings
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import Select, WebDriverWait

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "browser-test-password-42"


@pytest.fixture
def collaboration_browser(tmp_path, monkeypatch):
    async def capabilities(_self, refresh=False):
        return {
            "operations": [],
            "question_planner_enabled": False,
            "device_configuration": {"gpu_configured": False},
        }

    monkeypatch.setattr(AnalyticsService, "capabilities", capabilities)
    database = tmp_path / "source.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE connections(source TEXT,target TEXT)")
        db.execute("INSERT INTO connections VALUES ('001','002')")
    configuration = tmp_path / "connectors.json"
    configuration.write_text(
        json.dumps(
            [
                {
                    "id": "example",
                    "name": "Company connections",
                    "type": "sqlite",
                    "path": str(database),
                    "table": "connections",
                    "users": ["alice"],
                }
            ]
        )
    )
    configuration.chmod(0o600)
    settings = replace(
        Settings.from_env(ROOT),
        data_root=tmp_path / "data",
        accounts_enabled=True,
        account_cookie_secure=False,
        llm_enabled=False,
        graph_gpu_uuid="",
        llm_gpu_uuid="",
        graphmine_binary=tmp_path / "no-binary",
        connectors_file=configuration,
    )
    app = create_app(settings)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    driver = None
    try:
        deadline = time.monotonic() + 15
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        for name in ("alice", "bob"):
            app.state.runtime.accounts.create_user(name, PASSWORD)
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        with httpx.Client(base_url=base, timeout=10) as client:
            response = client.post(
                "/api/auth/login",
                json={"username": "alice", "password": PASSWORD, "issue_token": True},
                headers={"X-GraphMine-Request": "1"},
            )
            client.cookies.clear()
            headers = {"Authorization": "Bearer " + response.json()["access_token"]}
            sid = client.post(
                "/api/sessions", headers=headers, json={"title": "Private source"}
            ).json()["id"]
            graph = {
                "graph": {
                    "id": "sample",
                    "directed": False,
                    "allows_self_loops": False,
                    "allows_parallel_edges": False,
                },
                "vertices": [{"id": "1"}, {"id": 1}],
                "edges": [{"id": 0, "source": "1", "target": 1}],
            }
            uploaded = client.post(
                f"/api/sessions/{sid}/files",
                headers=headers,
                files={"file": ("sample.json", json.dumps(graph))},
            ).json()
            options = Options()
            options.add_argument("-headless")
            options.binary_location = "/snap/firefox/current/usr/lib/firefox/firefox"
            driver = webdriver.Firefox(
                options=options,
                service=Service(
                    executable_path="/snap/firefox/current/usr/lib/firefox/geckodriver"
                ),
            )
            driver.set_window_size(1400, 1050)
            yield driver, base, sid, uploaded, client, headers, tmp_path
    finally:
        if driver:
            driver.quit()
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()


def login(driver, base, path="/projects.html", name="alice"):
    driver.get(base + path)
    wait = WebDriverWait(driver, 20)
    wait.until(lambda d: d.find_element(By.ID, "account-username").is_displayed())
    driver.find_element(By.ID, "account-username").send_keys(name)
    driver.find_element(By.ID, "account-password").send_keys(PASSWORD)
    driver.find_element(By.ID, "account-sign-in").click()
    wait.until(
        lambda d: not d.find_element(By.CSS_SELECTOR, ".account-dialog").is_displayed()
    )
    return wait


def test_project_publish_annotations_views_and_link_revocation(collaboration_browser):
    driver, base, sid, _, client, headers, artifacts = collaboration_browser
    wait = login(driver, base)
    driver.find_element(By.ID, "project-name").send_keys("Team review")
    driver.find_element(By.CSS_SELECTOR, "#create-project button").click()
    wait.until(lambda d: d.find_element(By.ID, "project-title").text == "Team review")
    project = driver.find_element(By.ID, "project-choice").get_attribute("value")
    driver.find_element(By.CSS_SELECTOR, "#project-detail details summary").click()
    driver.find_element(By.ID, "member-name").send_keys("bob")
    driver.find_element(By.CSS_SELECTOR, "#member-form button").click()
    wait.until(lambda d: "bob" in d.find_element(By.ID, "project-members").text)
    driver.get(f"{base}/#workspace/{sid}/chat")
    wait.until(
        lambda d: d.execute_script(
            "return GraphMineWorkspace.state.active && !GraphMineWorkspace.state.busy"
        )
    )
    driver.find_element(By.ID, "share-project-input").click()
    wait.until(lambda d: d.find_element(By.ID, "publish-project").is_displayed())
    driver.find_element(By.CSS_SELECTOR, "#publish-project .primary").click()
    wait.until(lambda d: "Snapshot shared" in d.find_element(By.ID, "notice").text)
    driver.get(base + "/projects.html")
    wait.until(
        lambda d: len(Select(d.find_element(By.ID, "project-choice")).options) == 2
    )
    Select(driver.find_element(By.ID, "project-choice")).select_by_value(project)
    wait.until(
        lambda d: len(Select(d.find_element(By.ID, "project-item")).options) == 2
    )
    Select(driver.find_element(By.ID, "project-item")).select_by_index(1)
    wait.until(lambda d: d.find_element(By.ID, "annotation-text").is_displayed())
    driver.find_element(By.ID, "annotation-text").send_keys(
        "Check the original connection."
    )
    driver.find_element(By.CSS_SELECTOR, "#annotation-form button").click()
    wait.until(
        lambda d: "Check the original" in d.find_element(By.ID, "project-notes").text
    )
    Select(driver.find_element(By.ID, "project-layout")).select_by_value("circle")
    driver.find_element(By.ID, "view-name").send_keys("Circular review")
    driver.find_element(By.CSS_SELECTOR, "#view-form button").click()
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, "[data-view-id]"))
    driver.find_element(By.CSS_SELECTOR, "[data-view-id]").click()
    assert (
        driver.find_element(By.ID, "project-layout").get_attribute("value") == "circle"
    )
    driver.find_element(By.CSS_SELECTOR, "#link-form button").click()
    wait.until(lambda d: d.find_element(By.ID, "created-link").is_displayed())
    url = driver.find_element(By.ID, "created-link").get_attribute("value")
    driver.set_window_size(500, 844)
    driver.execute_async_script(
        "const done=arguments[0];requestAnimationFrame(()=>requestAnimationFrame(done))"
    )
    driver.save_screenshot(str(artifacts / "project-mobile.png"))
    assert driver.execute_script(
        "return document.documentElement.scrollWidth <= innerWidth"
    ), driver.execute_script(
        "return [...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>[e.tagName,e.id,e.getBoundingClientRect().width]).slice(0,12)"
    )
    owner = driver.current_window_handle
    driver.switch_to.new_window("tab")
    shared = driver.current_window_handle
    driver.get(url)
    wait.until(
        lambda d: "Read-only snapshot" in d.find_element(By.ID, "share-status").text
    )
    assert "sample.json" in driver.find_element(By.ID, "shared-viewer").text
    assert not driver.find_elements(By.ID, "annotation-form")
    driver.switch_to.window(owner)
    driver.find_element(By.CSS_SELECTOR, "[data-revoke-link]").click()
    wait.until(lambda d: not d.find_elements(By.CSS_SELECTOR, "[data-revoke-link]"))
    driver.switch_to.window(shared)
    driver.refresh()
    wait.until(lambda d: "revoked" in d.find_element(By.ID, "share-status").text)
    assert client.get("/api/auth/me", headers=headers).json()["quota"]["jobs_used"] == 0


def test_connector_preview_save_and_use_flow(collaboration_browser):
    driver, base, sid, _, client, headers, artifacts = collaboration_browser
    wait = login(driver, base, f"/#workspace/{sid}/chat")
    wait.until(
        lambda d: d.execute_script(
            "return GraphMineWorkspace.state.session && !GraphMineWorkspace.state.busy"
        )
    )
    driver.find_element(By.ID, "open-connectors").click()
    wait.until(lambda d: d.find_element(By.ID, "connector-dialog").is_displayed())
    driver.find_element(By.ID, "preview-connector").click()
    wait.until(lambda d: d.find_element(By.ID, "save-connector").is_enabled())
    assert "2 vertices" in driver.find_element(By.ID, "connector-scope").text
    assert client.get("/api/datasets", headers=headers).json() == []
    driver.save_screenshot(str(artifacts / "connector-preview.png"))
    driver.find_element(By.ID, "save-connector").click()
    wait.until(lambda d: d.find_element(By.ID, "use-connector").is_displayed())
    driver.find_element(By.ID, "use-connector").click()
    wait.until(lambda d: not d.find_elements(By.ID, "connector-dialog"))
    assert "Company connections" in driver.find_element(By.ID, "data-summary").text
    assert len(client.get("/api/datasets", headers=headers).json()) == 1
    assert client.get("/api/auth/me", headers=headers).json()["quota"]["jobs_used"] == 0
