"""A routed data workspace keeps editing context through responsive navigation."""

import json
from threading import Event
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from test_workspace_loading import SESSION, loading_browser, loading_server, wait_for  # noqa: F401
from test_workspace_conversation_graph import saved_network, open_saved


@pytest.fixture
def data_page(loading_server):
    server = loading_server
    graph = {"graph": {"directed": True}, "vertices": [{"id": 1, "label": "Ada"}, {"id": "1", "label": "Ben"}], "edges": [{"id": "e1", "source": 1, "target": "1"}]}
    file = {"id": "input", "original_name": "accounts.json", "role": "graph", "metadata": {"vertex_count": 2, "edge_count": 1}}
    server.files, server.graph = [file], {**graph, "vertex_count": 2, "edge_count": 1}
    value = SimpleNamespace(queries=[], source_reads=0, dataset_error=False, delay_upload=None, delay_query=None, delay_source=None, uploads=0)
    source = {"id": "workspace-db", "name": "Research accounts", "managed": True, "entities": [], "relationships": []}

    def route(handler, method):
        path = urlsplit(handler.path).path
        def reply(data, status=200):
            handler.respond(data, status)
            return True
        if method == "GET" and path == "/api/database-sources":
            value.source_reads += 1
            if value.delay_source:
                value.delay_source.started.set()
                value.delay_source.release.wait(10)
            return reply([source])
        if path.endswith("/workspace-db/status"):
            return reply({"connected": True, "sql": {"connected": True}, "neo4j": {"connected": True}})
        if method == "GET" and path.endswith("/workspace-db/datasets"):
            if value.dataset_error:
                return reply({"error": {"message": "Dataset lookup is unavailable"}}, 503)
            return reply([{"id": "default", "name": "Account network", "status": "ready", "schemas": [],
                           "tables": [{"name": "accounts", "labels": ["Account"], "key": "id", "rows": 200,
                                       "columns": [{"name": "id", "type": "integer"}, {"name": "risk", "type": "integer"}]}],
                           "default_query": "MATCH (n) RETURN n LIMIT 10"}])
        if path in {"/api/database-jobs", "/api/query-library"}:
            return reply({"items": [], "has_more": False})
        if method == "POST" and path.endswith("/workspace-db/queries"):
            body = json.loads(handler.rfile.read(int(handler.headers["Content-Length"])))
            value.queries.append(body)
            if value.delay_query:
                value.delay_query.started.set()
                value.delay_query.release.wait(10)
            if "INVALID" in body["statement"]:
                return reply({"error": {"code": "cypher_error", "message": "Invalid query syntax", "details": {"offset": 0}}}, 422)
            return reply({"dataset": {"id": "preview", "temporary": True}, "row_count": 2, "rows": [], "vertex_count": 2, "edge_count": 1, "graph": graph})
        if method == "POST" and path == "/api/database-query-snapshots/preview/chat":
            return reply({"session": SESSION, "file": file, "kind": "graph"}, 201)
        if method == "POST" and path.endswith("/datasets/preview/import"):
            return reply({"file": {**file, "id": "query-input"}, "kind": "graph"}, 201)
        if method == "POST" and path.endswith("/files"):
            handler.rfile.read(int(handler.headers["Content-Length"]))
            if value.delay_upload:
                value.delay_upload.started.set()
                value.delay_upload.release.wait(10)
            value.uploads += 1
            uploaded = {**file, "id": "uploaded", "original_name": "uploaded.json"}
            server.files.append(uploaded)
            return reply(uploaded, 201)
        return False

    server.route_handler = route
    server.responses[0].release.set()
    yield value
    if value.delay_upload:
        value.delay_upload.release.set()
    if value.delay_query:
        value.delay_query.release.set()
    if value.delay_source:
        value.delay_source.release.set()


def open_page(browser, server, width=1440, path="/#data"):
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 900})
    browser.get(server.url + path)
    wait_for(browser, "document.getElementById('preview-cypher')?.disabled === false && !GraphMineWorkspace.state.busy")


def click(browser, identifier):
    element = browser.find_element(By.ID, identifier)
    browser.execute_script("arguments[0].scrollIntoView({block:'nearest'})", element)
    element.click()


def test_desktop_has_three_independent_panes_and_real_page_navigation(loading_browser, loading_server, data_page):
    browser = loading_browser
    open_page(browser, loading_server)
    assert browser.execute_script("return GraphMineWorkspace.state.view") == "data"
    assert browser.execute_script("return document.querySelectorAll('dialog[open]').length") == 0
    dimensions = browser.execute_script("return ['data-connection-pane','data-query-pane','data-preview-pane'].map(id => { const e = document.getElementById(id), r = e.getBoundingClientRect(); return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,overflow:getComputedStyle(e).overflowY}; })")
    assert dimensions[0]["right"] <= dimensions[1]["left"] + .5
    assert dimensions[1]["right"] <= dimensions[2]["left"] + .5
    assert all(value["top"] == dimensions[0]["top"] and value["overflow"] == "auto" for value in dimensions)
    assert browser.find_element(By.ID, "app-sidebar").is_displayed()
    assert browser.find_element(By.ID, "nav-database").get_attribute("aria-current") == "page"
    search = browser.find_element(By.ID, "database-schema-search")
    search.send_keys("risk")
    assert browser.find_element(By.CSS_SELECTOR, ".dataset-schema-table").get_attribute("open")
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("value") == "MATCH (n) RETURN n LIMIT 10"
    click(browser, "preview-cypher")
    wait_for(browser, "document.getElementById('database-preview-count').textContent.includes('2 nodes')")
    browser.save_screenshot("/tmp/graphmine-data-workspace-desktop.png")
    click(browser, "close-data-source")
    wait_for(browser, "GraphMineWorkspace.state.view === 'domains' && !document.getElementById('database-workspace')")
    browser.back()
    wait_for(browser, "GraphMineWorkspace.state.view === 'data' && document.getElementById('preview-cypher')?.disabled === false")
    assert len(data_page.queries) == 1


def test_resize_keeps_focused_editor_and_url_on_the_same_step(loading_browser, loading_server, data_page):
    browser = loading_browser
    open_page(browser, loading_server)
    editor = browser.find_element(By.ID, "cypher-editor")
    editor.click(); editor.send_keys(" // draft")
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": 768, "height": 900})
    wait_for(browser, "document.getElementById('database-workspace').dataset.step === 'query' && location.hash === '#data/query'")
    assert browser.switch_to.active_element == editor
    assert editor.is_displayed() and editor.get_attribute("value").endswith("// draft")
    assert not data_page.queries


def test_back_from_data_returns_to_the_original_saved_result(loading_browser, loading_server, data_page):
    browser = loading_browser
    saved_network(loading_server)
    open_saved(browser, loading_server, "results")
    wait_for(browser, "Boolean(GraphMineWorkspace.state.cy)")
    click(browser, "data-page-link")
    wait_for(browser, "document.getElementById('preview-cypher')?.disabled === false")
    assert browser.find_element(By.ID, "close-data-source").text == "Back to results"
    click(browser, "close-data-source")
    wait_for(browser, "GraphMineWorkspace.state.view === 'results' && Boolean(GraphMineWorkspace.state.cy)")
    assert browser.execute_script("return GraphMineWorkspace.state.record.id") == "saved-analysis"
    assert browser.execute_script("return location.hash") == "#workspace/saved-session/results/saved-analysis"


def test_slow_initial_discovery_does_not_hold_home_navigation(loading_browser, loading_server, data_page):
    browser = loading_browser
    data_page.delay_source = SimpleNamespace(started=Event(), release=Event())
    browser.get(loading_server.url + "/#data")
    assert data_page.delay_source.started.wait(3)
    wait_for(browser, "GraphMineWorkspace.state.view === 'data' && !GraphMineWorkspace.state.busy")
    assert not browser.find_element(By.ID, "cypher-editor").is_enabled()
    click(browser, "nav-new-chat")
    wait_for(browser, "GraphMineWorkspace.state.view === 'domains' && !GraphMineWorkspace.state.busy")
    assert browser.find_element(By.CSS_SELECTOR, ".domain-card").is_enabled()
    data_page.delay_source.release.set()
    browser.execute_async_script("setTimeout(arguments[0], 100)")
    assert not browser.find_elements(By.ID, "database-workspace")


def test_file_upload_does_not_wait_for_database_discovery(loading_browser, loading_server, data_page, tmp_path):
    browser = loading_browser
    data_page.delay_source = SimpleNamespace(started=Event(), release=Event())
    browser.get(loading_server.url + "/#data/files")
    assert data_page.delay_source.started.wait(3)
    wait_for(browser, "!GraphMineWorkspace.state.busy")
    path = tmp_path / "uploaded.json"; path.write_text(json.dumps(loading_server.graph))
    browser.find_element(By.ID, "source-file-upload").send_keys(str(path))
    wait_for(browser, "GraphMineWorkspace.state.view === 'chat' && GraphMineWorkspace.state.active === 'uploaded' && !document.getElementById('database-workspace')")
    assert data_page.uploads == 1
    data_page.delay_source.release.set()


@pytest.mark.parametrize("width", [320, 768])
def test_mobile_steps_preserve_draft_and_preview_without_reexecuting(loading_browser, loading_server, data_page, width):
    browser = loading_browser
    open_page(browser, loading_server, width)
    assert browser.find_element(By.ID, "data-connection-pane").is_displayed()
    assert not browser.find_element(By.ID, "data-query-pane").is_displayed()
    click(browser, "data-step-next")
    editor = browser.find_element(By.ID, "cypher-editor")
    editor.clear(); editor.send_keys("MATCH (n) WHERE n.name = $name RETURN n")
    browser.execute_script("const p = document.getElementById('cypher-parameters'); p.value = '{\"name\":\"Ada\"}'; p.dispatchEvent(new Event('input',{bubbles:true})); window.originalEditor = document.getElementById('cypher-editor');")
    click(browser, "data-step-connection")
    click(browser, "data-step-query")
    assert browser.execute_script("return window.originalEditor === document.getElementById('cypher-editor')")
    assert "$name" in editor.get_attribute("value")
    click(browser, "preview-cypher")
    wait_for(browser, "document.getElementById('database-workspace').dataset.step === 'preview' && document.getElementById('save-query-snapshot').disabled === false")
    assert data_page.queries[0]["parameters"] == {"name": "Ada"}
    assert browser.find_element(By.ID, "data-preview-pane").is_displayed()
    assert not browser.find_element(By.ID, "data-query-pane").is_displayed()
    click(browser, "data-step-query")
    assert editor.get_attribute("value").endswith("RETURN n")
    click(browser, "data-step-preview")
    assert len(data_page.queries) == 1
    assert browser.execute_script("return document.documentElement.scrollWidth <= innerWidth && document.getElementById('database-workspace').scrollWidth <= document.getElementById('database-workspace').clientWidth")
    browser.save_screenshot(f"/tmp/graphmine-data-workspace-{width}.png")


def test_short_mobile_view_keeps_preview_and_primary_action_reachable(loading_browser, loading_server, data_page):
    browser = loading_browser
    open_page(browser, loading_server, 320)
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": 320, "height": 640})
    click(browser, "data-step-query"); click(browser, "preview-cypher")
    wait_for(browser, "document.getElementById('save-query-snapshot').disabled === false")
    assert browser.execute_script("""
        const p=document.getElementById('data-preview-pane').getBoundingClientRect(), action=document.getElementById('run-cypher-chat').getBoundingClientRect();
        return p.height >= 180 && action.bottom <= innerHeight && action.top >= p.bottom && document.documentElement.scrollWidth <= innerWidth;
    """)
    click(browser, "run-cypher-chat")
    wait_for(browser, "GraphMineWorkspace.state.view === 'chat' && GraphMineWorkspace.state.active === 'input'")


def test_query_completion_keeps_the_users_upload_tab_selected(loading_browser, loading_server, data_page):
    browser = loading_browser
    open_page(browser, loading_server, 320)
    data_page.delay_query = SimpleNamespace(started=Event(), release=Event())
    click(browser, "data-step-query"); click(browser, "preview-cypher")
    assert data_page.delay_query.started.wait(3)
    click(browser, "source-files-tab")
    data_page.delay_query.release.set()
    wait_for(browser, "document.getElementById('preview-cypher').disabled === false")
    assert browser.execute_script("return location.hash") == "#data/files"
    assert browser.find_element(By.ID, "source-files-panel").is_displayed()
    click(browser, "source-database-tab"); click(browser, "data-step-preview")
    assert "2 nodes" in browser.find_element(By.ID, "database-preview-count").text
    assert len(data_page.queries) == 1


def test_upload_finishing_after_navigation_stays_with_its_original_conversation(loading_browser, loading_server, data_page, tmp_path):
    browser = loading_browser
    open_page(browser, loading_server, path="/#workspace/saved-session/data/files")
    data_page.delay_upload = SimpleNamespace(started=Event(), release=Event())
    path = tmp_path / "uploaded.json"; path.write_text(json.dumps(loading_server.graph))
    browser.find_element(By.ID, "source-file-upload").send_keys(str(path))
    assert data_page.delay_upload.started.wait(3)
    click(browser, "nav-new-chat")
    wait_for(browser, "GraphMineWorkspace.state.view === 'domains' && GraphMineWorkspace.state.session === null")
    data_page.delay_upload.release.set()
    WebDriverWait(browser, 5).until(lambda _: data_page.uploads == 1)
    browser.execute_async_script("setTimeout(arguments[0], 100)")
    assert browser.execute_script("return GraphMineWorkspace.state.session === null && GraphMineWorkspace.state.active === ''")


def test_conversation_data_route_and_draft_survive_reload_and_back(loading_browser, loading_server, data_page):
    browser = loading_browser
    open_page(browser, loading_server, path="/#workspace/saved-session/data/query")
    assert browser.execute_script("return GraphMineWorkspace.state.session.id") == "saved-session"
    editor = browser.find_element(By.ID, "cypher-editor")
    editor.clear(); editor.send_keys("MATCH (n) RETURN n LIMIT 42")
    browser.refresh()
    wait_for(browser, "document.getElementById('cypher-editor')?.value.endsWith('42') && !GraphMineWorkspace.state.busy")
    assert browser.execute_script("return location.hash") == "#workspace/saved-session/data/query"
    click(browser, "close-data-source")
    wait_for(browser, "GraphMineWorkspace.state.view === 'chat'")
    assert browser.execute_script("return location.hash") == "#workspace/saved-session/chat"
    assert not data_page.queries


def test_mobile_steps_have_keyboard_navigation_and_readable_errors(loading_browser, loading_server, data_page):
    browser = loading_browser
    open_page(browser, loading_server, 320)
    step = browser.find_element(By.ID, "data-step-connection")
    step.click(); step.send_keys(Keys.ARROW_RIGHT)
    assert browser.switch_to.active_element.get_attribute("id") == "data-step-query"
    editor = browser.find_element(By.ID, "cypher-editor")
    editor.clear(); editor.send_keys("INVALID")
    click(browser, "preview-cypher")
    wait_for(browser, "document.getElementById('database-query-status').textContent.includes('Invalid query syntax')")
    assert browser.find_element(By.ID, "data-query-pane").is_displayed()
    assert browser.find_element(By.ID, "database-query-status").is_displayed()
    browser.find_element(By.ID, "data-step-query").send_keys(Keys.END)
    assert browser.switch_to.active_element.get_attribute("id") == "data-step-preview"
    assert not browser.find_element(By.ID, "source-continue").is_displayed()


def test_mobile_missing_dataset_keeps_connection_step_actionable(loading_browser, loading_server, data_page):
    browser = loading_browser
    data_page.dataset_error = True
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": 320, "height": 800})
    browser.get(loading_server.url + "/#data")
    wait_for(browser, "document.getElementById('database-dataset-status')?.textContent.includes('unavailable')")
    assert not browser.find_element(By.ID, "data-step-next").is_enabled()
    assert browser.find_element(By.ID, "add-connection").is_enabled()
    data_page.dataset_error = False
    click(browser, "refresh-database-datasets")
    wait_for(browser, "document.getElementById('data-step-next').disabled === false")
    click(browser, "data-step-next")
    assert browser.find_element(By.ID, "cypher-editor").is_displayed()


def test_upload_route_returns_to_chat_with_the_imported_input(loading_browser, loading_server, data_page, tmp_path):
    browser = loading_browser
    open_page(browser, loading_server, path="/#workspace/saved-session/data/files")
    file = tmp_path / "uploaded.json"
    file.write_text(json.dumps(loading_server.graph))
    browser.find_element(By.ID, "source-file-upload").send_keys(str(file))
    wait_for(browser, "GraphMineWorkspace.state.view === 'chat' && GraphMineWorkspace.state.active === 'uploaded' && !document.getElementById('database-workspace')")
    assert browser.execute_script("return location.hash") == "#workspace/saved-session/chat"
    assert data_page.uploads == 1


def test_leaving_while_page_initializes_does_not_mount_a_stale_workspace(loading_browser, loading_server, data_page):
    browser = loading_browser
    browser.get(loading_server.url)
    wait_for(browser, "!GraphMineWorkspace.state.busy && Boolean(GraphMineWorkspace.state.caps)")
    browser.execute_script("""
        const original = window.GraphMineQueryDrafts;
        window.GraphMineQueryDrafts = args => new Promise(resolve => { window.releaseDataDrafts = () => resolve(original(args)); });
    """)
    click(browser, "open-database-workspace")
    wait_for(browser, "Boolean(window.releaseDataDrafts)")
    browser.back()
    wait_for(browser, "GraphMineWorkspace.state.view === 'domains'")
    browser.execute_script("window.releaseDataDrafts()")
    browser.execute_async_script("setTimeout(arguments[0], 100)")
    assert not browser.find_elements(By.ID, "database-workspace")
    assert data_page.source_reads == 0
