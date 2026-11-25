"""Home keeps data and domain starting points without saved-work cards."""

from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from selenium.webdriver.common.by import By

from test_workspace_loading import SESSION, loading_browser, loading_server, wait_for  # noqa: F401
from test_workspace_data_layout import data_page  # noqa: F401
from test_workspace_conversation_graph import saved_network
from test_workspace_accessibility import assert_readable


@pytest.fixture
def home(loading_server, data_page):
    server = loading_server
    saved_network(server)
    updated = "2026-10-20T12:00:00+00:00"
    value = SimpleNamespace(
        requests=[],
        sections={
            "datasets": [{"id": "version-0", "dataset_id": "dataset-0", "name": "Saved network", "kind": "graph", "version": 2,
                          "source_complete": True, "updated_at": updated}],
            "analyses": [{"id": row["id"], "session_id": SESSION["id"], "conversation": SESSION["title"],
                          "status": row["status"], "revision": 1, "updated_at": updated, "problems": ["k-core"]} for row in server.workflows],
        },
    )
    original = server.route_handler

    def route(handler, method):
        path = urlsplit(handler.path).path
        if path.startswith("/api/workspace/recent/"):
            section = path.rsplit("/", 1)[1]
            value.requests.append(section)
            handler.respond({"items": value.sections[section], "has_more": False, "offset": 0, "limit": 4})
            return True
        return original(handler, method)

    server.route_handler = route
    return value


def open_home(browser, server, width=1440):
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 900 if width > 600 else 640})
    browser.get(server.url + "/")
    wait_for(browser, "!GraphMineWorkspace.state.busy && document.querySelector('#domain-grid button')")


@pytest.mark.parametrize("width", [1440, 320])
def test_returning_home_keeps_starting_points_and_reflows(loading_browser, loading_server, home, width):
    browser = loading_browser
    open_home(browser, loading_server, width)
    assert browser.find_element(By.ID, "domain-heading").text == "What will you discover?"
    assert browser.find_elements(By.ID, "home-recents") == []
    assert browser.find_elements(By.ID, "home-dataset-dialog") == []
    assert browser.find_element(By.ID, "open-database-workspace").is_displayed()
    assert home.requests == []
    assert browser.execute_script("return document.documentElement.scrollWidth <= innerWidth")
    assert_readable(browser)
    browser.save_screenshot(f"/tmp/graphmine-home-{width}.png")


def test_empty_home_keeps_the_new_user_start(loading_browser, loading_server, home):
    home.sections = {section: [] for section in home.sections}
    open_home(loading_browser, loading_server)
    assert loading_browser.find_elements(By.ID, "home-recents") == []
    assert loading_browser.find_element(By.ID, "domain-heading").text == "What will you discover?"
    assert loading_browser.find_element(By.ID, "open-database-workspace").is_displayed()
    assert home.requests == []
