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
    driver.find_element(By.ID, "data-page-link").click()
    wait.until(lambda d: d.find_element(By.ID, "database-workspace").is_displayed())
    wait.until(lambda d: d.find_element(By.ID, 'add-connection').is_enabled())
    driver.find_element(By.ID, "add-connection").click()
    wait.until(lambda d: d.find_element(By.ID, "connection-editor").is_displayed())
    return wait


def test_add_sqlite_map_preview_import_and_remove(collaboration_browser):
    driver, _, sid, _, client, headers, artifacts = collaboration_browser
    wait = open_connections(collaboration_browser)
    Select(driver.find_element(By.ID, 'connection-type')).select_by_value('sqlite')
    driver.find_element(By.ID, 'connection-sqlite-file').send_keys(str(artifacts / 'source.sqlite3'))
    wait.until(lambda d: not d.find_element(By.ID, 'save-connection-settings').get_attribute('disabled'))
    name = driver.find_element(By.ID, 'connection-label'); name.clear(); name.send_keys('My SQLite connection')
    Select(driver.find_element(By.ID, 'connection-table')).select_by_value('connections')
    assert Select(driver.find_element(By.ID, 'connection-source-column')).first_selected_option.get_attribute('value') == 'source'
    driver.find_element(By.ID, 'save-connection-settings').click()
    wait.until(lambda d: not d.find_elements(By.ID, 'connection-editor'))
    identifier = Select(driver.find_element(By.ID, 'database-source')).first_selected_option.get_attribute('value').removeprefix('connector:')
    assert not driver.find_element(By.ID, 'cypher-editor').is_displayed()
    driver.find_element(By.ID, 'preview-cypher').click()
    wait.until(lambda d: not d.find_element(By.ID, 'save-query-snapshot').get_attribute('disabled'))
    assert '2 vertices' in driver.find_element(By.ID, 'database-preview-count').text
    driver.find_element(By.ID, 'save-query-snapshot').click()
    wait.until(lambda d: d.find_element(By.ID, 'save-query-snapshot').text == 'Saved in datasets')
    assert len(client.get("/api/datasets", headers=headers).json()) == 1
    driver.find_element(By.ID, 'run-cypher-chat').click()
    wait.until(lambda d: not d.find_elements(By.ID, 'database-workspace') and d.execute_script('return GraphMineWorkspace.state.view') == 'chat')
    assert driver.execute_script('return GraphMineWorkspace.state.session.id') == sid
    driver.find_element(By.ID, 'data-page-link').click()
    wait.until(lambda d: d.find_element(By.ID, 'edit-connection').is_displayed())
    driver.find_element(By.ID, 'edit-connection').click()
    wait.until(lambda d: d.find_element(By.ID, 'delete-connection').is_displayed())
    driver.find_element(By.ID, 'delete-connection').click(); driver.find_element(By.ID, 'delete-connection').click()
    wait.until(lambda d: not d.find_elements(By.ID, 'connection-editor'))
    assert client.get(f'/api/connectors/{identifier}', headers=headers).status_code == 404
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
    created = client.post("/api/connectors", headers=headers, json={
        "name": f"My {kind} source", "type": kind, "url": origin,
        ("password" if kind == "neo4j" else "bearer_token"): "browser-fixture-secret",
    })
    assert created.status_code == 201, created.text
    identifier = created.json()["id"]
    preview = client.post(f"/api/connectors/{identifier}/preview", headers=headers).json()
    assert preview["metadata"]["vertex_count"] == 2
    saved = client.post(f"/api/connectors/{identifier}/import", headers=headers, json={
        "name": f"My {kind} source", "expected_sha256": preview["sha256"],
    })
    assert saved.status_code == 201, saved.text
    assert len(client.get("/api/datasets", headers=headers).json()) == 1
    assert "browser-fixture-secret" not in client.get(f"/api/connectors/{identifier}", headers=headers).text
    open_connections(browser)
    assert driver.find_element(By.ID, "connection-neo4j-uri").is_displayed()
    assert {option.get_attribute('value') for option in Select(driver.find_element(By.ID, 'connection-type')).options} >= {'neo4j', 'sqlite', 'rest'}
    assert not driver.find_elements(By.ID, "open-connectors")


@pytest.mark.parametrize('destination,width', [('current', 1440), ('new', 320)])
def test_create_rest_connection_preview_and_use_graph_in_browser(network_browser, destination, width):
    browser, origin = network_browser
    driver, base, sid, _, client, headers, _ = browser
    driver.browsing_context.set_viewport(context=driver.current_window_handle, viewport={'width': width, 'height': 950})
    wait = open_connections(browser)
    if destination == 'new':
        driver.get(base + '/#data')
        wait.until(lambda d: d.find_element(By.ID, 'add-connection').is_enabled())
        driver.find_element(By.ID, 'add-connection').click()
        wait.until(lambda d: d.find_element(By.ID, 'connection-editor').is_displayed())
    Select(driver.find_element(By.ID, 'connection-type')).select_by_value('rest')
    driver.find_element(By.ID, 'connection-label').send_keys('REST browser graph')
    driver.find_element(By.ID, 'connection-url').send_keys(origin)
    driver.find_element(By.ID, 'connection-token').send_keys('browser-fixture-secret')
    checkbox = driver.find_element(By.ID, 'connection-complete')
    assert driver.execute_script("const label=arguments[0].closest('label'); return label.scrollWidth <= label.clientWidth + 1", checkbox)
    driver.find_element(By.ID, 'save-connection-settings').click()
    wait.until(lambda d: not d.find_elements(By.ID, 'connection-editor'))
    assert not driver.find_element(By.ID, 'cypher-editor').is_displayed()
    identifier = Select(driver.find_element(By.ID, 'database-source')).first_selected_option.get_attribute('value').removeprefix('connector:')
    assert 'browser-fixture-secret' not in client.get('/api/data-sources', headers=headers).text
    if width == 320: driver.find_element(By.ID, 'data-step-query').click()
    driver.find_element(By.ID, 'preview-cypher').click()
    wait.until(lambda d: d.find_element(By.ID, 'run-cypher-chat').is_enabled())
    assert 'upstream may contain more' in driver.find_element(By.ID, 'database-query-status').text
    driver.find_element(By.ID, 'run-cypher-chat').click()
    wait.until(lambda d: not d.find_elements(By.ID, 'database-workspace'))
    active = driver.execute_script('return GraphMineWorkspace.state.session.id')
    assert (active == sid) is (destination == 'current')
    assert client.get(f'/api/sessions/{active}/files', headers=headers).json()
    saved = client.get('/api/datasets', headers=headers).json()
    assert len(saved) == 1 and saved[0]['source']['connector_id'] == identifier
    assert saved[0]['source_complete'] is False


def test_upload_file_from_data_source_keeps_current_conversation(collaboration_browser):
    driver, _, sid, _, client, headers, artifacts = collaboration_browser
    wait = open_connections(collaboration_browser)
    driver.find_element(By.ID, "cancel-connection-settings").click()
    driver.find_element(By.ID, "source-files-tab").click()
    graph = artifacts / "new-network.json"
    graph.write_text(json.dumps({
        "graph": {"id": "uploaded", "directed": False, "allows_self_loops": False, "allows_parallel_edges": False},
        "vertices": [{"id": 1}, {"id": 2}],
        "edges": [{"id": 0, "source": 1, "target": 2}],
    }))
    driver.find_element(By.ID, "source-file-upload").send_keys(str(graph))
    wait.until(lambda d: not d.find_elements(By.ID, "database-workspace"))
    assert driver.execute_script("return GraphMineWorkspace.state.session.id") == sid
    assert "new-network.json" in driver.find_element(By.ID, "data-summary").get_attribute("textContent")
    assert client.get("/api/auth/me", headers=headers).json()["quota"]["jobs_used"] == 0


def test_cancel_csv_preview_keeps_source_picker_and_input(collaboration_browser):
    driver, _, _, _, _, _, artifacts = collaboration_browser
    wait = open_connections(collaboration_browser)
    original = driver.execute_script("return GraphMineWorkspace.state.active")
    driver.find_element(By.ID, "cancel-connection-settings").click()
    driver.find_element(By.ID, "source-files-tab").click()
    path = artifacts / "connections.csv"
    path.write_text("source,target\n1,2\n")
    driver.find_element(By.ID, "source-file-upload").send_keys(str(path))
    wait.until(lambda d: d.find_element(By.ID, "import-dialog").is_displayed())
    driver.find_element(By.CSS_SELECTOR, "#import-dialog .quiet").click()
    wait.until(lambda d: not d.find_elements(By.ID, "import-dialog"))
    assert driver.find_element(By.ID, "database-workspace").is_displayed()
    assert driver.execute_script("return GraphMineWorkspace.state.active") == original
