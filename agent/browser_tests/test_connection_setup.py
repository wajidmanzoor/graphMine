import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from test_projects_and_connectors import (
    collaboration_browser as collaboration_browser,  # noqa: PLC0414
)
from test_projects_and_connectors import login


def open_connections(browser):
    driver, base, sid, *_ = browser
    wait = login(driver, base, f"/#workspace/{sid}/chat")
    wait.until(
        lambda d: d.execute_script(
            "return GraphMineWorkspace.state.session && !GraphMineWorkspace.state.busy"
        )
    )
    driver.find_element(By.ID, "open-connectors").click()
    wait.until(lambda d: d.find_element(By.ID, "connector-dialog").is_displayed())
    driver.find_element(By.ID, "add-connection").click()
    wait.until(lambda d: d.find_element(By.ID, "connection-editor").is_displayed())
    return wait


def test_add_sqlite_map_preview_import_and_remove(collaboration_browser):
    driver, _, _, _, client, headers, artifacts = collaboration_browser
    wait = open_connections(collaboration_browser)
    driver.find_element(By.ID, "connection-label").send_keys("My SQLite connection")
    driver.find_element(By.ID, "connection-file").send_keys(
        str(artifacts / "source.sqlite3")
    )
    driver.find_element(By.ID, "upload-connection").click()
    wait.until(lambda d: d.find_element(By.ID, "save-connection-settings").is_enabled())
    assert (
        Select(
            driver.find_element(By.ID, "connection-table")
        ).first_selected_option.text
        == "connections"
    )
    driver.set_window_size(500, 844)
    assert driver.execute_script(
        "return document.documentElement.scrollWidth <= innerWidth"
    )
    driver.save_screenshot(str(artifacts / "sqlite-setup-mobile.png"))
    driver.find_element(By.ID, "save-connection-settings").click()
    wait.until(lambda d: not d.find_element(By.ID, "connection-editor").is_displayed())
    driver.find_element(By.ID, "preview-connector").click()
    wait.until(lambda d: d.find_element(By.ID, "save-connector").is_enabled())
    assert "2 vertices" in driver.find_element(By.ID, "connector-scope").text
    driver.find_element(By.ID, "save-connector").click()
    wait.until(lambda d: "Saved" in d.find_element(By.ID, "connector-scope").text)
    assert len(client.get("/api/datasets", headers=headers).json()) == 1
    driver.find_element(By.ID, "delete-connection").click()
    wait.until(lambda d: d.switch_to.alert)
    driver.switch_to.alert.accept()
    wait.until(
        lambda d: len(Select(d.find_element(By.ID, "connector-choice")).options) == 1
    )
    assert len(client.get("/api/datasets", headers=headers).json()) == 1


@pytest.fixture
def network_browser(monkeypatch, request):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'[{"source":"001","target":"002"}]')

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(202)
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "data": {
                            "fields": [
                                "source",
                                "target",
                                "relationship",
                                "relationship_id",
                            ],
                            "values": [["001", "002", "KNOWS", "edge-1"]],
                        },
                        "queryType": "r",
                    }
                ).encode()
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("GRAPHMINE_CONNECTOR_ALLOWED_ORIGINS", origin)
    try:
        yield request.getfixturevalue("collaboration_browser"), origin
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize("kind", ["rest", "neo4j"])
def test_add_api_or_neo4j_connection_in_browser(network_browser, kind):
    browser, origin = network_browser
    driver, _, _, _, client, headers, artifacts = browser
    wait = open_connections(browser)
    Select(driver.find_element(By.ID, "connection-type")).select_by_value(kind)
    driver.find_element(By.ID, "connection-label").send_keys(f"My {kind} source")
    driver.find_element(By.ID, "connection-url").send_keys(origin)
    driver.find_element(
        By.ID, "connection-password" if kind == "neo4j" else "connection-token"
    ).send_keys("browser-fixture-secret")
    driver.find_element(By.ID, "save-connection-settings").click()
    wait.until(lambda d: not d.find_element(By.ID, "connection-editor").is_displayed())
    driver.find_element(By.ID, "preview-connector").click()
    wait.until(lambda d: d.find_element(By.ID, "save-connector").is_enabled())
    assert "2 vertices" in driver.find_element(By.ID, "connector-scope").text
    driver.find_element(By.ID, "save-connector").click()
    wait.until(lambda d: "Saved" in d.find_element(By.ID, "connector-scope").text)
    driver.save_screenshot(str(artifacts / f"{kind}-connection.png"))
    assert len(client.get("/api/datasets", headers=headers).json()) == 1
    driver.find_element(By.ID, "edit-connection").click()
    wait.until(lambda d: d.find_element(By.ID, "connection-editor").is_displayed())
    assert (
        driver.find_element(
            By.ID, "connection-password" if kind == "neo4j" else "connection-token"
        ).get_attribute("value")
        == ""
    )
