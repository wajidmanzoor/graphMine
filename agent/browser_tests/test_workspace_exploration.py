"""Saved display preferences survive reloads without changing analysis evidence."""

import json
import threading
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

from graphmine_agent.exploration import SaveExploration
from test_workspace_conversation_graph import open_saved, saved_network
from test_workspace_loading import CAPABILITIES, loading_browser, loading_server, wait_for  # noqa: F401


@pytest.fixture
def exploration_server(loading_server):
    server = loading_server
    saved_network(server)
    server.preferences = {"revision": 0, "state": None, "warnings": [], "storage_key": "test-owner-saved-session"}
    server.save_requests, server.overlay_requests, server.result_view_requests = [], [], []
    server.fail_reads = server.fail_writes = server.fail_overlays = False
    server.exploration_hook = None
    server.visualization = False
    server.overlay = {"file_id": "enriched", "fetched_at": "2026-10-21T10:00:00Z", "fields": {"vertices": ["risk"], "edges": []},
                      "vertices": [{"id": 1, "attributes": {"risk": 7}}, {"id": "1", "attributes": {"risk": 2}}], "edges": []}
    server.files.append({**server.files[0], "id": "enriched", "original_name": "enriched.json"})
    lock = threading.Lock()

    def route(handler, method):
        path = urlsplit(handler.path).path
        if server.exploration_hook and server.exploration_hook(handler, method):
            return True
        if path.endswith("/exploration"):
            if method == "GET":
                with lock:
                    handler.respond({"error": {"message": "Saved views temporarily unavailable"}} if server.fail_reads else deepcopy(server.preferences), 503 if server.fail_reads else 200)
            elif method == "PUT":
                body = json.loads(handler.rfile.read(int(handler.headers["Content-Length"])))
                with lock:
                    server.save_requests.append(body)
                    if server.fail_writes:
                        handler.respond({"error": {"code": "unavailable", "message": "Cannot save yet"}}, 503)
                    elif body["expected_revision"] != server.preferences["revision"]:
                        handler.respond({"error": {"code": "exploration_conflict", "message": "Another tab saved a view"}}, 409)
                    else:
                        try:
                            value = SaveExploration.model_validate(body)
                        except ValueError as error:
                            handler.respond({"error": {"message": str(error)}}, 422)
                        else:
                            server.preferences.update(revision=server.preferences["revision"] + 1, state=value.state.model_dump(mode="json"))
                            handler.respond(deepcopy(server.preferences))
            return True
        if path.endswith("/exploration/overlay") and method == "POST":
            server.overlay_requests.append(json.loads(handler.rfile.read(int(handler.headers["Content-Length"]))))
            handler.respond({"error": {"message": "Saved attributes temporarily unavailable"}} if server.fail_overlays else server.overlay, 503 if server.fail_overlays else 200)
            return True
        if method == "GET" and path == "/api/analytics/capabilities" and server.visualization:
            capabilities = deepcopy(CAPABILITIES)
            capabilities["operations"].append({"id": "community-detection", "title": "Communities", "input_kind": "graph", "execution": {"cpu": True, "gpu": False}, "parameters": {}, "visualization": {"kind": "subgraph", "title": "Community"}})
            handler.respond(capabilities)
            return True
        if method == "GET" and path.endswith("/view"):
            params = parse_qs(urlsplit(handler.path).query)
            server.result_view_requests.append(params)
            index = int(params["index"][0]) if "index" in params else None
            context = params.get("context", ["false"])[0] == "true"
            ids = [1, 2, 3] if index == 0 else ["1", 4, 5] if index == 1 else []
            graph = deepcopy(server.graph)
            if index is not None and not context:
                graph["vertices"] = [v for v in graph["vertices"] if v["id"] in ids]
                graph["edges"] = [e for e in graph["edges"] if e["source"] in ids and e["target"] in ids]
            graph.update(vertex_count=len(graph["vertices"]), edge_count=len(graph["edges"]), graph_available=True, enrichable=True,
                         index=index, context=context, step="core", port=path.split("/")[-2], item_count=2, selected_vertices=ids, selected_edges=[],
                         profile={"kind": "subgraph", "title": "Community"}, complete=True, note="Recorded community")
            handler.respond(graph)
            return True
        return False

    server.route_handler = route
    return server


def saved(browser, predicate=None):
    wait_for(browser, "document.getElementById('exploration-status').textContent === 'Exploration saved.'")
    if predicate:
        WebDriverWait(browser, 5, poll_frequency=.05).until(lambda _: predicate())


def set_control(browser, identifier, value, event="input"):
    browser.execute_script("const el = document.getElementById(arguments[0]); el.value = arguments[1]; el.dispatchEvent(new Event(arguments[2], {bubbles: true}));", identifier, value, event)


def graph_state(browser):
    return browser.execute_script("""
        const s = GraphMineWorkspace.state, w = GraphMineWorkspace.wire;
        return {zoom: s.cy.zoom(), pan: s.cy.pan(), positions: s.cy.nodes().map(n => ({id: w.idKey(n.data('entity')), ...n.position()})), selected: [...s.selected]};
    """)


def test_active_version_viewport_filters_and_typed_selection_survive_reload(loading_browser, exploration_server):
    browser, server = loading_browser, exploration_server
    server.files.append({**server.files[0], "id": "network-new", "original_name": "new-version.json"})
    for index, edge in enumerate(server.graph["edges"][:-1]):
        edge["timestamp"] = 100 + index
    original = deepcopy(server.results)
    open_saved(browser, server, "results")
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 6")
    set_control(browser, "active-input", "network-new", "change")
    set_control(browser, "graph-layout", "circle", "change")
    set_control(browser, "table-search", "1")
    set_control(browser, "group-min-size", "2")
    set_control(browser, "time-start", "2")
    browser.execute_script("""
        const s = GraphMineWorkspace.state;
        document.getElementById('include-untimed').click();
        s.cy.nodes().forEach((n, i) => n.position({x: 17 + i * 70, y: 19 + i * 45}));
        s.cy.nodes().filter(n => n.data('entity') === 1).emit('tap');
        s.cy.zoom(1.3); s.cy.pan({x: 93, y: 55}); s.cy.nodes().emit('dragfree');
    """)
    saved(browser, lambda: server.preferences["state"]["active_file_id"] == "network-new")
    before = graph_state(browser)
    assert server.preferences["state"]["views"][-1]["selected_vertices"] == [1]
    browser.refresh()
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 6 && !GraphMineWorkspace.state.busy")
    assert graph_state(browser) == before
    assert browser.execute_script("return GraphMineWorkspace.state.active") == "network-new"
    assert browser.execute_script("return GraphMineWorkspace.state.record.input_files.main.file_id") == "network"
    assert browser.find_element(By.ID, "graph-layout").get_attribute("value") == "circle"
    assert browser.find_element(By.ID, "table-search").get_attribute("value") == "1"
    assert browser.find_element(By.ID, "group-min-size").get_attribute("value") == "2"
    assert browser.find_element(By.ID, "time-start").get_attribute("value") == "2"
    assert not browser.find_element(By.ID, "include-untimed").is_selected()
    assert browser.execute_script("return GraphMineWorkspace.state.cy.edges().filter(e => e.style('display') !== 'none').length") == 4
    browser.set_window_size(900, 750)
    wait_for(browser, "document.getElementById('network').clientWidth < 900")
    assert graph_state(browser) == before
    assert server.results == original


@pytest.mark.parametrize("resolution", ["keep", "reload"])
def test_conflict_requires_explicit_choice(loading_browser, exploration_server, resolution):
    browser, server = loading_browser, exploration_server
    open_saved(browser, server, "results")
    saved(browser)
    server.preferences["revision"] += 1
    server.preferences["state"]["views"][-1]["filters"]["search"] = "remote choice"
    set_control(browser, "table-search", "my choice")
    wait_for(browser, "!document.getElementById('keep-exploration').hidden")
    assert server.preferences["state"]["views"][-1]["filters"]["search"] == "remote choice"
    browser.find_element(By.ID, "keep-exploration" if resolution == "keep" else "reload-exploration").click()
    expected = "my choice" if resolution == "keep" else "remote choice"
    wait_for(browser, f"document.getElementById('table-search').value === '{expected}' && document.getElementById('keep-exploration').hidden")
    WebDriverWait(browser, 5).until(lambda _: server.preferences["state"]["views"][-1]["filters"]["search"] == expected)


def test_failed_save_recovers_from_browser_journal_on_reload(loading_browser, exploration_server):
    browser, server = loading_browser, exploration_server
    open_saved(browser, server, "results")
    saved(browser)
    server.fail_writes = True
    set_control(browser, "table-search", "keep offline work")
    wait_for(browser, "document.getElementById('exploration-status').textContent.includes('Cannot save yet')")
    assert browser.execute_script("return Object.keys(localStorage).some(k => k.startsWith('graphmine.exploration.'))")
    browser.refresh()
    wait_for(browser, "GraphMineWorkspace.state.cy && !GraphMineWorkspace.state.busy")
    assert browser.find_element(By.ID, "table-search").get_attribute("value") == "keep offline work"
    server.fail_writes = False
    browser.find_element(By.ID, "retry-exploration-save").click()
    saved(browser)
    assert server.preferences["state"]["views"][-1]["filters"]["search"] == "keep offline work"
    assert not browser.execute_script("return Object.keys(localStorage).some(k => k.startsWith('graphmine.exploration.'))")


def test_corrupt_recovery_data_does_not_block_saved_results(loading_browser, exploration_server):
    browser, server = loading_browser, exploration_server
    open_saved(browser, server, "results")
    saved(browser)
    browser.execute_script("""
        window.addEventListener('pagehide', () => {
          localStorage.setItem('graphmine.exploration.v1.' + location.origin + '/.test-owner-saved-session', JSON.stringify({revision: 1, document: {active_file_id: 'network', view: null, views: [{scope: null, viewport: {positions: null}}]}}));
        });
    """)
    browser.refresh()
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 6 && !GraphMineWorkspace.state.busy")
    assert not browser.find_element(By.ID, "keep-exploration").is_displayed()
    set_control(browser, "table-search", "recovered")
    saved(browser, lambda: server.preferences["state"]["views"][-1]["filters"]["search"] == "recovered")


def test_unavailable_preferences_can_reconnect_without_losing_tab_changes(loading_browser, exploration_server):
    browser, server = loading_browser, exploration_server
    server.fail_reads = True
    open_saved(browser, server, "results")
    set_control(browser, "table-search", "work during outage")
    wait_for(browser, "document.getElementById('exploration-status').textContent.includes('kept in this tab')")
    server.fail_reads = False
    browser.find_element(By.ID, "retry-exploration-save").click()
    saved(browser)
    assert server.preferences["state"]["views"][-1]["filters"]["search"] == "work during outage"


def test_source_overlay_labels_and_colors_restore_from_saved_attributes(loading_browser, exploration_server):
    browser, server = loading_browser, exploration_server
    open_saved(browser, server, "results")
    saved(browser)
    view = server.preferences["state"]["views"][-1]
    view.update(overlay_file_id="enriched", label_attribute="risk", color_attribute="risk")
    view["filters"]["attribute_search"] = "7"
    server.preferences["revision"] += 1
    browser.refresh()
    wait_for(browser, "document.getElementById('attribute-label').value === 'risk' && GraphMineWorkspace.state.cy?.nodes().length === 6")
    assert len(server.overlay_requests) == 1
    assert browser.find_element(By.ID, "attribute-color").get_attribute("value") == "risk"
    assert browser.find_element(By.ID, "source-attribute-search").get_attribute("value") == "7"
    labels = browser.execute_script("return GraphMineWorkspace.state.cy.nodes().filter(n => [1, '1'].includes(n.data('entity'))).map(n => n.data('label'))")
    assert labels == ["7", "2"]
    assert browser.execute_script("return GraphMineWorkspace.state.cy.nodes().filter(n => [1, '1'].includes(n.data('entity'))).map(n => n.style('background-color'))")[0] != browser.execute_script("return GraphMineWorkspace.state.cy.nodes().filter(n => n.data('entity') === '1')[0].style('background-color')")
    assert "saved graph version" in browser.find_element(By.ID, "enrichment-note").text
    assert "risk" not in json.dumps(server.results)


def test_saved_overlay_failure_has_retry_and_preserves_style_choice(loading_browser, exploration_server):
    browser, server = loading_browser, exploration_server
    open_saved(browser, server, "results")
    saved(browser)
    server.preferences["state"]["views"][-1].update(overlay_file_id="enriched", label_attribute="risk", color_attribute="risk")
    server.preferences["revision"] += 1
    server.fail_overlays = True
    browser.refresh()
    wait_for(browser, "!document.getElementById('retry-enrichment-restore').hidden && Boolean(GraphMineWorkspace.state.cy)")
    server.fail_overlays = False
    browser.find_element(By.ID, "retry-enrichment-restore").click()
    wait_for(browser, "document.getElementById('attribute-label').value === 'risk' && document.getElementById('retry-enrichment-restore').hidden")
    assert browser.find_element(By.ID, "attribute-color").get_attribute("value") == "risk"


def test_result_item_and_context_restore_on_small_screen(loading_browser, exploration_server):
    browser, server = loading_browser, exploration_server
    browser.set_window_size(320, 700)
    server.visualization = True
    open_saved(browser, server, "results")
    wait_for(browser, "Boolean(GraphMineWorkspace.state.resultView && GraphMineWorkspace.state.cy)")
    set_control(browser, "result-item-index", "2")
    browser.find_element(By.ID, "show-result-item").click()
    wait_for(browser, "GraphMineWorkspace.state.resultView?.index === 1")
    Select(browser.find_element(By.ID, "result-view-mode")).select_by_value("context")
    wait_for(browser, "GraphMineWorkspace.state.resultView?.context && GraphMineWorkspace.state.cy.nodes().length === 6")
    saved(browser, lambda: server.preferences["state"]["view"]["result"]["index"] == 1)
    browser.refresh()
    wait_for(browser, "GraphMineWorkspace.state.resultView?.index === 1 && GraphMineWorkspace.state.resultView?.context && GraphMineWorkspace.state.cy?.nodes().length === 6")
    assert server.result_view_requests[-1]["index"] == ["1"]
    assert server.result_view_requests[-1]["context"] == ["true"]


def test_delayed_overlay_cannot_repaint_another_result_port(loading_browser, exploration_server):
    browser, server = loading_browser, exploration_server
    open_saved(browser, server, "results")
    saved(browser)
    server.preferences["state"]["views"][-1].update(overlay_file_id="enriched", label_attribute="risk", color_attribute="risk")
    server.preferences["revision"] += 1
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def delay(handler, method):
        if method != "POST" or not handler.path.endswith("/exploration/overlay"):
            return False
        handler.rfile.read(int(handler.headers["Content-Length"]))
        started.set()
        release.wait(10)
        handler.respond(server.overlay)
        finished.set()
        return True

    server.exploration_hook = delay
    try:
        browser.refresh()
        assert started.wait(3)
        wait_for(browser, "Boolean(GraphMineWorkspace.state.cy) && !GraphMineWorkspace.state.busy")
        Select(browser.find_element(By.ID, "result-port")).select_by_value("partition")
        wait_for(browser, "GraphMineWorkspace.state.port?.type === 'vertex_partition' && Boolean(GraphMineWorkspace.state.cy)")
        release.set()
        assert finished.wait(3)
        browser.execute_async_script("setTimeout(arguments[0], 150)")
        assert browser.find_element(By.ID, "source-attribute-table").get_attribute("hidden")
        assert browser.execute_script("return GraphMineWorkspace.state.cy.nodes().every(n => n.data('original').attributes?.risk === undefined)")
    finally:
        release.set()


def test_switching_focus_while_attributes_load_still_restores_current_view(loading_browser, exploration_server):
    browser, server = loading_browser, exploration_server
    server.visualization = True
    open_saved(browser, server, "results")
    saved(browser)
    view = server.preferences["state"]["views"][-1]
    view.update(overlay_file_id="enriched", label_attribute="risk", color_attribute="risk")
    other = deepcopy(view)
    other["scope"]["result"]["context"] = True
    server.preferences["state"]["views"].append(other)
    server.preferences["revision"] += 1
    started, release = threading.Event(), threading.Event()

    def delay(handler, method):
        if method != "POST" or not handler.path.endswith("/exploration/overlay"):
            return False
        body = json.loads(handler.rfile.read(int(handler.headers["Content-Length"])))
        if not body["scope"]["result"]["context"]:
            started.set()
            release.wait(10)
        handler.respond(server.overlay)
        return True

    server.exploration_hook = delay
    try:
        browser.refresh()
        assert started.wait(3)
        wait_for(browser, "Boolean(GraphMineWorkspace.state.resultView && GraphMineWorkspace.state.cy) && !GraphMineWorkspace.state.busy")
        Select(browser.find_element(By.ID, "result-view-mode")).select_by_value("context")
        wait_for(browser, "GraphMineWorkspace.state.resultView?.context && document.getElementById('attribute-label').value === 'risk'")
        release.set()
        assert browser.execute_script("return GraphMineWorkspace.state.cy.nodes().find(n => n.data('entity') === 1).data('label')") == "7"
    finally:
        release.set()


def test_lost_save_acknowledgement_reconciles_without_false_conflict(loading_browser, exploration_server):
    browser, server = loading_browser, exploration_server
    open_saved(browser, server, "results")
    saved(browser)

    def lose_reply(handler, method):
        if method != "PUT" or not handler.path.endswith("/exploration"):
            return False
        body = json.loads(handler.rfile.read(int(handler.headers["Content-Length"])))
        server.preferences.update(revision=server.preferences["revision"] + 1, state=SaveExploration.model_validate(body).state.model_dump(mode="json"))
        server.exploration_hook = None
        handler.respond({"error": {"message": "Reply lost after saving"}}, 503)
        return True

    server.exploration_hook = lose_reply
    set_control(browser, "table-search", "saved but reply lost")
    wait_for(browser, "document.getElementById('exploration-status').textContent.includes('Reply lost')")
    revision = server.preferences["revision"]
    browser.find_element(By.ID, "retry-exploration-save").click()
    saved(browser)
    assert server.preferences["revision"] == revision
    assert browser.find_element(By.ID, "keep-exploration").get_attribute("hidden")


def test_server_saves_work_without_browser_storage(loading_browser, exploration_server):
    browser, server = loading_browser, exploration_server
    open_saved(browser, server, "results")
    saved(browser)
    browser.execute_script("Storage.prototype.setItem = Storage.prototype.getItem = Storage.prototype.removeItem = () => { throw new Error('Storage unavailable'); };")
    set_control(browser, "table-search", "server saved work")
    saved(browser, lambda: server.preferences["state"]["views"][-1]["filters"]["search"] == "server saved work")
    browser.refresh()
    wait_for(browser, "document.getElementById('table-search').value === 'server saved work' && !GraphMineWorkspace.state.busy")


def test_recovered_local_journal_prunes_deleted_files_and_changed_revisions(loading_browser, exploration_server):
    browser, server = loading_browser, exploration_server
    open_saved(browser, server, "results")
    set_control(browser, "active-input", "enriched", "change")
    saved(browser, lambda: server.preferences["state"]["active_file_id"] == "enriched")
    server.fail_writes = True
    set_control(browser, "table-search", "old revision draft")
    wait_for(browser, "document.getElementById('exploration-status').textContent.includes('Cannot save yet')")
    server.files = [file for file in server.files if file["id"] != "enriched"]
    server.workflows[0]["revision"] += 1
    browser.refresh()
    wait_for(browser, "GraphMineWorkspace.state.record?.revision === 2 && Boolean(GraphMineWorkspace.state.cy) && !GraphMineWorkspace.state.busy")
    server.fail_writes = False
    browser.find_element(By.ID, "retry-exploration-save").click()
    saved(browser)
    assert server.preferences["state"]["active_file_id"] == "network"
    assert server.preferences["state"]["views"]
    assert all(view["scope"]["result"]["revision"] == 2 for view in server.preferences["state"]["views"])


def test_active_input_without_results_does_not_reopen_an_older_analysis(loading_browser, exploration_server):
    browser, server = loading_browser, exploration_server
    server.preferences.update(revision=1, state=SaveExploration(expected_revision=0, state={"active_file_id": "enriched", "view": {"file_id": "enriched"}}).state.model_dump(mode="json"))
    server.responses[0].release.set()
    browser.get(server.url + "/#workspace/saved-session/results")
    wait_for(browser, "GraphMineWorkspace.state.active === 'enriched' && Boolean(GraphMineWorkspace.state.cy) && !GraphMineWorkspace.state.busy")
    assert browser.execute_script("return GraphMineWorkspace.state.record === null && GraphMineWorkspace.state.result === null")
    set_control(browser, "graph-layout", "circle", "change")
    saved(browser)
    browser.refresh()
    wait_for(browser, "GraphMineWorkspace.state.active === 'enriched' && Boolean(GraphMineWorkspace.state.cy) && !GraphMineWorkspace.state.busy")
    assert browser.execute_script("return GraphMineWorkspace.state.record === null && document.getElementById('graph-layout').value === 'circle'")


@pytest.mark.parametrize("initial_route", [True, False])
def test_leaving_conversation_ignores_delayed_saved_exploration(loading_browser, exploration_server, initial_route):
    browser, server = loading_browser, exploration_server
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def delay(handler, method):
        if method != "GET" or not handler.path.endswith("/exploration"):
            return False
        started.set()
        release.wait(10)
        handler.respond(server.preferences)
        finished.set()
        return True

    server.exploration_hook = delay
    server.responses[0].release.set()
    try:
        browser.get(server.url + ("/#workspace/saved-session/results" if initial_route else "/"))
        if not initial_route:
            wait_for(browser, "Boolean(GraphMineWorkspace.state.caps) && !GraphMineWorkspace.state.busy")
            browser.execute_script("location.hash = '#workspace/saved-session/results'")
        assert started.wait(3)
        browser.execute_script("location.hash = ''")
        wait_for(browser, "GraphMineWorkspace.state.view === 'domains' && GraphMineWorkspace.state.session === null")
        # Navigation releases the pending read without waiting for its response.
        wait_for(browser, "!GraphMineWorkspace.state.busy")
        release.set()
        assert finished.wait(3)
        wait_for(browser, "!GraphMineWorkspace.state.busy")
        assert browser.execute_script("return GraphMineWorkspace.state.record === null && GraphMineWorkspace.state.cy === null && GraphMineWorkspace.state.view === 'domains'")
        assert not server.save_requests
    finally:
        release.set()
