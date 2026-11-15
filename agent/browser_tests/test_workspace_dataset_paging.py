"""Visible paged library, lazy provenance, and stale-read recovery."""

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from test_database_graph_builder import click
from test_workspace_conversation_graph import open_saved, saved_network
from test_workspace_loading import loading_browser, loading_server, wait_for


def dataset(index):
    return {"id": f"version-{index}", "dataset_id": f"collection-{index}", "name": f"Network {index}",
            "version": 1, "kind": "graph", "size_bytes": 100, "sha256": f"hash-{index}", "source_complete": True,
            "source": {"query": f"private query {index}", "typed_id": 9007199254740993}}


def open_library(browser, server, *, save=False):
    saved_network(server); server.datasets = [dataset(i) for i in range(45)]
    open_saved(browser, server)
    click(browser, "#toggle-data"); click(browser, "#source-files-tab")
    click(browser, "#save-dataset-input" if save else "#open-datasets")
    wait_for(browser, "document.getElementById('dataset-dialog').open && document.querySelectorAll('#dataset-list article').length===20")


@pytest.mark.parametrize("width", [1440, 320])
def test_paged_library_searches_all_versions_and_loads_provenance_on_demand(loading_browser, loading_server, width):
    browser, server = loading_browser, loading_server
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 900})
    open_library(browser, server)
    assert not any(path.endswith("/provenance") for _, path, _ in server.requests)
    click(browser, "#datasets-next")
    wait_for(browser, "document.querySelector('#dataset-list h3')?.textContent==='Network 24 · version 1'")
    click(browser, "#datasets-next")
    wait_for(browser, "document.querySelectorAll('#dataset-list article').length===5")
    assert browser.find_element(By.ID, "datasets-next").get_property("disabled")
    click(browser, "#datasets-previous")
    wait_for(browser, "document.querySelector('#dataset-list h3')?.textContent==='Network 24 · version 1'")
    search = browser.find_element(By.CSS_SELECTOR, '#dataset-dialog input[aria-label="Search saved datasets"]')
    search.send_keys("Network 0")
    wait_for(browser, "document.querySelectorAll('#dataset-list article').length===1 && document.querySelector('#dataset-list h3').textContent==='Network 0 · version 1'")
    assert not any(path.endswith("/provenance") for _, path, _ in server.requests)
    click(browser, "#dataset-list summary")
    wait_for(browser, "document.querySelector('#dataset-list pre')?.textContent.includes('private query 0')")
    assert "9007199254740993" in browser.find_element(By.CSS_SELECTOR, "#dataset-list pre").text
    assert len([path for _, path, _ in server.requests if path.endswith("/provenance")]) == 1
    click(browser, "#dataset-list summary"); click(browser, "#dataset-list summary")
    assert len([path for _, path, _ in server.requests if path.endswith("/provenance")]) == 1
    assert browser.execute_script("return document.getElementById('dataset-dialog').scrollWidth <= document.getElementById('dataset-dialog').clientWidth")


@pytest.mark.parametrize("width", [1440, 320])
def test_new_version_picker_can_find_collections_beyond_first_page(loading_browser, loading_server, width):
    browser, server = loading_browser, loading_server
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 900})
    open_library(browser, server, save=True)
    wait_for(browser, "document.getElementById('dataset-version').options.length===21")
    browser.find_element(By.CSS_SELECTOR, '#dataset-form input[aria-label="Find an existing dataset"]').send_keys("Network 0")
    wait_for(browser, "document.getElementById('dataset-version').options.length===2")
    Select(browser.find_element(By.ID, "dataset-version")).select_by_value("collection-0")
    assert browser.find_element(By.CSS_SELECTOR, "#dataset-form .dataset-choice").text == "New version of Network 0"
    assert browser.execute_script("return document.getElementById('dataset-dialog').scrollWidth <= document.getElementById('dataset-dialog').clientWidth")
    browser.save_screenshot(f"/tmp/graphmine-dataset-picker-{width}.png")
    posted = []
    def post(path, body):
        assert path == "/api/datasets"
        posted.append(body)
        item = {**dataset(0), "id": "new-version", "version": 2, "name": body["name"]}
        server.datasets.append(item)
        return item
    server.post_handler = post
    click(browser, '#dataset-form button[type="submit"]')
    wait_for(browser, "document.querySelector('#dataset-list h3')?.textContent.includes('version 2')")
    assert posted[0]["dataset_id"] == "collection-0"
    assert not any(path == "/api/datasets" and method == "GET" for method, path, _ in server.requests)


@pytest.mark.parametrize("failure", [False, True])
def test_delayed_search_cannot_replace_current_page_or_report_stale_error(loading_browser, loading_server, failure):
    browser, server = loading_browser, loading_server
    open_library(browser, server)
    browser.execute_script("""
      const prior = window.fetch;
      window.fetch = (path, options) => {
        const url = new URL(path, location.href);
        if (url.pathname === '/api/datasets/page' && url.searchParams.get('q') === 'held') {
          return new Promise(resolve => {window.releaseLibrary = () => resolve(new Response(JSON.stringify(arguments[0] ? {error:{message:'Old search failed'}} : {items:[],offset:0,limit:20,has_more:false}), {status:arguments[0] ? 503 : 200, headers:{'Content-Type':'application/json'}}));});
        }
        return prior(path, options);
      };
    """, failure)
    search = browser.find_element(By.CSS_SELECTOR, '#dataset-dialog input[aria-label="Search saved datasets"]')
    search.send_keys("held"); wait_for(browser, "typeof window.releaseLibrary==='function'")
    search.clear(); search.send_keys("Network 0")
    wait_for(browser, "document.querySelector('#dataset-list h3')?.textContent==='Network 0 · version 1'")
    browser.execute_script("releaseLibrary()")
    wait_for(browser, "document.getElementById('dataset-list').getAttribute('aria-busy')==='false'")
    assert "Old search failed" not in browser.find_element(By.ID, "dataset-dialog").text
    assert browser.find_element(By.CSS_SELECTOR, "#dataset-list h3").text == "Network 0 · version 1"


def test_provenance_error_can_be_retried(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    open_library(browser, server)
    attempts = []
    def route(handler, method):
        if handler.path.endswith("/provenance"):
            attempts.append(handler.path)
            if len(attempts) == 1:
                handler.respond({"error": {"message": "Try provenance again"}}, status=503)
                return True
        return False
    server.route_handler = route
    click(browser, "#dataset-list summary")
    wait_for(browser, "document.querySelector('#dataset-list details button')?.textContent==='Retry provenance'")
    click(browser, "#dataset-list details button")
    wait_for(browser, "document.querySelector('#dataset-list pre')?.textContent.includes('private query 44')")
    assert len(attempts) == 2


def test_close_and_reopen_ignores_delayed_provenance(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    open_library(browser, server)
    browser.execute_script("""
      const prior=window.fetch;
      window.fetch = (path, options) => String(path).endsWith('/provenance') ? new Promise(resolve => {
        window.releaseProvenance = () => resolve(new Response(JSON.stringify({error:{message:'Stale provenance error'}}), {status:503,headers:{'Content-Type':'application/json'}}));
      }) : prior(path, options);
    """)
    click(browser, "#dataset-list summary"); wait_for(browser, "typeof releaseProvenance==='function'")
    click(browser, "#dataset-dialog .section-heading button")
    click(browser, "#open-datasets")
    wait_for(browser, "document.getElementById('dataset-dialog').open && document.querySelectorAll('#dataset-list article').length===20")
    browser.execute_script("releaseProvenance()")
    assert not browser.find_elements(By.CSS_SELECTOR, "#dataset-list details[open]")
    assert "Stale provenance error" not in browser.find_element(By.ID, "dataset-dialog").text
