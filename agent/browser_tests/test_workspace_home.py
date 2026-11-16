"""Returning-user shortcuts preserve drafts, approvals and navigation context."""

import json
from copy import deepcopy
from threading import Event
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from test_workspace_loading import SESSION, WORKFLOW, loading_browser, loading_server, wait_for  # noqa: F401
from test_workspace_data_layout import data_page, click  # noqa: F401
from test_workspace_conversation_graph import saved_network
from test_workspace_accessibility import assert_readable


@pytest.fixture
def home(loading_server, data_page):
    server = loading_server
    saved_network(server)
    review = deepcopy(WORKFLOW); review["id"] = "review-analysis"
    server.workflows.append(review)
    updated = "2026-10-20T12:00:00+00:00"
    value = SimpleNamespace(
        creation_error=0, workspace_error=0,
        requests=[], created=[], delay_recent=None, failed_section=None,
        sections={
            "datasets": [{"id": f"version-{i}", "dataset_id": f"dataset-{i}", "name": "Saved network " + str(i), "kind": "graph", "version": 2,
                          "source_complete": i != 0, "updated_at": updated} for i in range(7)],
            "analyses": [{"id": row["id"], "session_id": SESSION["id"], "conversation": SESSION["title"],
                          "status": row["status"], "revision": 1, "updated_at": updated, "operations": ["k-core"]} for row in server.workflows],
        },
    )
    original = server.route_handler

    def route(handler, method):
        parsed = urlsplit(handler.path); path = parsed.path
        def reply(data, status=200):
            handler.respond(data, status)
            return True
        if path.startswith("/api/workspace/recent/"):
            section = path.rsplit("/", 1)[1]
            offset = int(parse_qs(parsed.query).get("offset", [0])[0])
            value.requests.append((section, offset))
            items = deepcopy(value.sections[section][offset:offset+4])
            if value.delay_recent:
                delayed = value.delay_recent
                delayed.started.set(); delayed.release.wait(10); delayed.finished.set()
            if section == value.failed_section:
                return reply({"error": {"message": "Temporarily offline"}}, 503)
            return reply({"items": items, "has_more": offset + 4 < len(value.sections[section]), "offset": offset, "limit": 4})
        if path == "/api/sessions/saved-session/workspace" and value.workspace_error:
            return reply({"error": {"message": "Conversation is temporarily unavailable"}}, value.workspace_error)
        if path == "/api/sessions/saved-session/tables/saved-table/schema":
            return reply({"columns": [{"name": "source", "type": "integer"}, {"name": "target", "type": "string"}], "row_count": 3, "sample": []})
        if method == "POST" and path == "/api/datasets/version-0/conversation":
            body = json.loads(handler.rfile.read(int(handler.headers["Content-Length"])))
            value.created.append(body)
            if value.creation_error:
                return reply({"error": {"message": "This saved version was removed. Choose another dataset."}}, value.creation_error)
            server.workflows = []; server.events = []
            return reply({"session": SESSION, "file": server.files[0], "kind": server.files[0].get("provenance", {}).get("kind", "graph")}, 201)
        return original(handler, method)

    server.route_handler = route
    yield value
    if value.delay_recent:
        value.delay_recent.release.set()


def open_home(browser, server, width=1440):
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 900 if width > 600 else 640})
    browser.get(server.url + "/")
    wait_for(browser, "!GraphMineWorkspace.state.busy && document.querySelector('#home-datasets [data-recent-id]') && !document.querySelector('#home-recents [aria-busy=true]')")


@pytest.mark.parametrize("width", [1440, 320])
def test_returning_home_has_recent_work_first_and_reflows(loading_browser, loading_server, home, width):
    browser = loading_browser; open_home(browser, loading_server, width)
    assert browser.find_element(By.ID, "domain-heading").text == "Pick up where you left off."
    assert len(browser.find_elements(By.CSS_SELECTOR, "#home-datasets li")) == 4
    assert browser.find_elements(By.ID, "home-queries") == []
    assert all(section != "queries" for section, _ in home.requests)
    assert browser.execute_script("return document.getElementById('home-recents').compareDocumentPosition(document.querySelector('.database-start')) & Node.DOCUMENT_POSITION_FOLLOWING")
    assert browser.execute_script("return document.documentElement.scrollWidth <= innerWidth")
    assert_readable(browser)
    assert "incomplete source" in browser.find_element(By.CSS_SELECTOR, '#home-datasets [data-recent-id="version-0"]').text
    browser.save_screenshot(f"/tmp/graphmine-home-{width}.png")
    home.sections["datasets"][0]["name"] = '<img src=x onerror="window.injected=1">'
    click(browser, "refresh-home-recents")
    wait_for(browser, "document.getElementById('home-datasets').textContent.includes('<img')")
    assert browser.execute_script("return window.injected || document.querySelector('#home-datasets img')") is None


def test_home_paginates_without_duplicates_and_retries_one_section(loading_browser, loading_server, home):
    browser = loading_browser; home.failed_section = "analyses"; open_home(browser, loading_server)
    assert "Could not load analyses" in browser.find_element(By.ID, "home-recents").text
    browser.find_element(By.CSS_SELECTOR, '[data-more-recent="datasets"]').click()
    wait_for(browser, "document.querySelectorAll('#home-datasets li').length === 7")
    assert ("datasets", 4) in home.requests
    assert not browser.find_element(By.CSS_SELECTOR, '[data-more-recent="datasets"]').is_displayed()
    home.failed_section = None
    browser.find_element(By.CSS_SELECTOR, '[data-more-recent="analyses"]').click()
    wait_for(browser, "document.querySelector('#home-analyses [data-recent-id]')")
    assert len(browser.find_elements(By.CSS_SELECTOR, "#home-datasets li")) == 7


def test_empty_home_keeps_the_new_user_start(loading_browser, loading_server, home):
    browser = loading_browser
    home.sections = {section: [] for section in home.sections}
    browser.get(loading_server.url + "/")
    wait_for(browser, "!GraphMineWorkspace.state.busy && document.getElementById('domain-grid').querySelector('button') && !document.querySelector('#home-recents [aria-busy=true]')")
    assert not browser.find_element(By.ID, "home-recents").is_displayed()
    assert browser.find_element(By.ID, "domain-heading").text == "What will you discover?"
    assert browser.find_element(By.ID, "open-database-workspace").is_displayed()


def test_dataset_shortcut_asks_domain_and_creates_only_on_submit(loading_browser, loading_server, home):
    browser = loading_browser; open_home(browser, loading_server, 320)
    entry = browser.find_element(By.CSS_SELECTOR, '[data-recent-id="version-0"]')
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", entry)
    entry.click()
    assert browser.find_element(By.ID, "home-dataset-dialog").is_displayed()
    assert "incomplete" in browser.find_element(By.ID, "home-dataset-dialog").text
    assert home.created == []
    browser.switch_to.active_element.send_keys(Keys.ESCAPE)
    assert not browser.find_element(By.ID, "home-dataset-dialog").is_displayed()
    entry.click(); click(browser, "start-dataset-conversation")
    wait_for(browser, "GraphMineWorkspace.state.session?.id === 'saved-session' && !GraphMineWorkspace.state.busy && GraphMineWorkspace.state.view === 'chat'")
    assert home.created == [{"domain_id": "general"}]
    assert browser.execute_script("return GraphMineWorkspace.state.active") == "network"
    assert browser.current_url.endswith("#workspace/saved-session/chat")


def test_dataset_creation_failure_is_inline_and_retryable(loading_browser, loading_server, home):
    browser = loading_browser; open_home(browser, loading_server)
    home.creation_error = 404
    browser.find_element(By.CSS_SELECTOR, '[data-recent-id="version-0"]').click()
    click(browser, "start-dataset-conversation")
    wait_for(browser, "document.getElementById('home-dataset-status').textContent.includes('removed') && !GraphMineWorkspace.state.busy")
    assert browser.find_element(By.ID, "home-dataset-dialog").is_displayed()
    assert browser.execute_script("return GraphMineWorkspace.state.session") is None
    home.creation_error = 0; click(browser, "start-dataset-conversation")
    wait_for(browser, "GraphMineWorkspace.state.view === 'chat' && !GraphMineWorkspace.state.busy")


def test_created_conversation_can_reload_after_its_first_read_fails(loading_browser, loading_server, home):
    browser = loading_browser; open_home(browser, loading_server)
    home.workspace_error = 503
    browser.find_element(By.CSS_SELECTOR, '[data-recent-id="version-0"]').click()
    click(browser, "start-dataset-conversation")
    wait_for(browser, "document.getElementById('notice').textContent.includes('temporarily unavailable') && !GraphMineWorkspace.state.busy")
    assert browser.current_url.endswith("#workspace/saved-session/chat")
    assert len(home.created) == 1
    home.workspace_error = 0; browser.refresh()
    wait_for(browser, "GraphMineWorkspace.state.view === 'chat' && GraphMineWorkspace.state.active === 'network' && !GraphMineWorkspace.state.busy")
    assert len(home.created) == 1


def test_saved_table_opens_column_selection_without_running_analysis(loading_browser, loading_server, home):
    browser = loading_browser
    home.sections["datasets"][0]["kind"] = "table"
    loading_server.files = [{"id": "saved-table", "role": "attachment", "original_name": "Accounts-v2.json", "metadata": None, "provenance": {"kind": "table"}}]
    open_home(browser, loading_server, 320)
    entry = browser.find_element(By.CSS_SELECTOR, '[data-recent-id="version-0"]')
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", entry); entry.click()
    click(browser, "start-dataset-conversation")
    wait_for(browser, "document.getElementById('projection-dialog').open && document.getElementById('projection-source').options.length === 3 && !GraphMineWorkspace.state.busy")
    assert browser.execute_script("return GraphMineWorkspace.state.kinds['saved-table']") == "table"
    assert browser.execute_script("return GraphMineWorkspace.state.active") == ""
    assert len(home.created) == 1
    assert not [request for request in loading_server.requests if request[0] == "POST"]


@pytest.mark.parametrize("identifier,page", [("review-analysis", "chat"), ("saved-analysis", "results")])
def test_analysis_shortcut_opens_exact_workflow_without_approval(loading_browser, loading_server, home, identifier, page):
    browser = loading_browser; open_home(browser, loading_server)
    browser.find_element(By.CSS_SELECTOR, f'[data-recent-id="{identifier}"]').click()
    wait_for(browser, f"GraphMineWorkspace.state.record?.id === '{identifier}' && GraphMineWorkspace.state.view === '{page}' && !GraphMineWorkspace.state.busy")
    if identifier == "review-analysis":
        assert browser.execute_script("return GraphMineWorkspace.state.record.status") == "awaiting_review"
        assert browser.find_element(By.ID, "approve-plan").is_displayed()
    assert not [request for request in loading_server.requests if request[0] == "POST"]


def test_home_saved_work_does_not_wait_for_native_capabilities(loading_browser, loading_server, home):
    loading_server.responses[0].release.clear()
    open_home(loading_browser, loading_server)
    assert loading_server.responses[0].started.wait(3)
    assert not loading_server.responses[0].finished.is_set()
    assert loading_browser.find_element(By.CSS_SELECTOR, '#home-analyses a').is_enabled()


def test_home_reloads_after_return_and_ignores_delayed_previous_load(loading_browser, loading_server, home):
    browser = loading_browser
    home.delay_recent = SimpleNamespace(started=Event(), release=Event(), finished=Event())
    browser.get(loading_server.url + "/")
    assert home.delay_recent.started.wait(3)
    browser.execute_script("location.hash = '#data'")
    wait_for(browser, "GraphMineWorkspace.state.view === 'data'")
    delayed = home.delay_recent; home.delay_recent = None
    home.sections["datasets"][0]["name"] = "Newly saved graph"
    browser.execute_script("location.hash = '#'")
    wait_for(browser, "document.getElementById('home-datasets').textContent.includes('Newly saved graph')")
    delayed.release.set(); assert delayed.finished.wait(3)
    assert "Newly saved graph" in browser.find_element(By.ID, "home-datasets").text

