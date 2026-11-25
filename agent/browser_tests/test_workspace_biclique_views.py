"""Saved native biclique rows render through the real result-view endpoint logic."""

from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from graphmine_agent.result_views import PROFILES, result_view
from test_workspace_conversation_graph import open_saved
from test_workspace_exploration import exploration_server, loading_browser
from test_workspace_loading import loading_server, wait_for


def test_biclique_columns_and_unloaded_item_keep_typed_members(
    loading_browser, exploration_server, monkeypatch
):
    browser, server = loading_browser, exploration_server
    pairs = [(1, 2), (1, 3), ("1", 4), ("1", 5)]
    server.graph["edges"] = [
        {"id": i, "source": a, "target": b} for i, (a, b) in enumerate(pairs)
    ]
    server.graph["edge_count"] = 4
    record = server.workflows[0]
    record["validation"]["plan"]["steps"][0]["problem"] = "maximal-bicliques"
    output = server.results["saved-analysis"]["steps"]["core"]["result"]
    rows = [
        {"left_vertices": [1], "right_vertices": [2, 3]},
        {"left_vertices": ["1"], "right_vertices": [4, 5]},
    ]
    output.update(problem="maximal-bicliques", quality="exact", ports={
        "bicliques": {"type": "bipartite_groups", "value": rows, "complete": True}
    })
    saved = deepcopy(output)
    output["ports"]["bicliques"].update(value=rows[:1], value_truncated=True, total_items=2)
    server.port_page = {"items": rows[:1], "positions": [0], "offset": 0, "limit": 1,
                        "matched_items": 2, "total_items": 2}
    service = SimpleNamespace(get=lambda _: record, _saved=lambda *args, **kwargs: {"result": saved})
    monkeypatch.setattr("graphmine_agent.result_views.input_graph", lambda *args: server.graph)
    original = server.route_handler

    def route(handler, method):
        parsed = urlsplit(handler.path)
        if parsed.path == "/api/analytics/capabilities":
            handler.respond({"problems": [{
                "id": "maximal-bicliques", "title": "Maximal bicliques", "input_kind": "graph",
                "parameters": {}, "execution": {"cpu": True, "gpu": False},
                "visualization": PROFILES["maximal-bicliques"],
            }]})
            return True
        if parsed.path.endswith("/view"):
            params = parse_qs(parsed.query)
            handler.respond(result_view(service, "saved-analysis", "core", "bicliques",
                index=int(params["index"][0]) if "index" in params else None,
                context=params.get("context", ["false"])[0] == "true"))
            return True
        return original(handler, method)

    server.route_handler = route
    open_saved(browser, server, "results/saved-analysis")
    wait_for(browser, "GraphMineWorkspace.state.resultView?.index === 0 && !GraphMineWorkspace.state.resultViewPending && GraphMineWorkspace.state.cy?.nodes().length === 3")

    def plotted():
        return browser.execute_script("""
            const cy = GraphMineWorkspace.state.cy;
            return {nodes: cy.nodes().map(n => [n.data('entity'), n.position('x')]), edges: cy.edges().length};
        """)

    assert plotted() == {"nodes": [[1, 0], [2, 280], [3, 280]], "edges": 2}
    wait_for(browser, "!GraphMineWorkspace.state.remoteLoading && document.querySelector('#result-table tbody button')")
    browser.find_element(By.CSS_SELECTOR, "#result-table tbody button").click()
    assert browser.find_element(By.ID, "selection-detail").text.startswith("3 selected:")
    item = browser.find_element(By.ID, "result-item-index")
    item.clear()
    item.send_keys("2")
    browser.find_element(By.ID, "show-result-item").click()
    wait_for(browser, "GraphMineWorkspace.state.resultView?.index === 1 && !GraphMineWorkspace.state.resultViewPending && GraphMineWorkspace.state.cy?.nodes()[0]?.data('entity') === '1'")
    assert plotted() == {"nodes": [["1", 0], [4, 280], [5, 280]], "edges": 2}
    Select(browser.find_element(By.ID, "result-view-mode")).select_by_value("context")
    wait_for(browser, "GraphMineWorkspace.state.resultView?.context && !GraphMineWorkspace.state.resultViewPending && GraphMineWorkspace.state.cy?.nodes().length === 6")
    assert len(plotted()["nodes"]) == 6 and plotted()["edges"] == 4
    assert browser.execute_script("return GraphMineWorkspace.state.resultView.selected_vertices") == ["1", 4, 5]
    assert browser.execute_script("return GraphMineWorkspace.state.resultViewError") is None
