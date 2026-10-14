"""Browser regressions for conversation races, partitions and overlapping cliques."""

import threading
from copy import deepcopy

import pytest
import test_workspace_loading as loading_fixtures
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from test_workspace_loading import WORKFLOW, wait_for

loading_browser = loading_fixtures.loading_browser
loading_server = loading_fixtures.loading_server


def event(server, kind, turn, **payload):
    server.events.append(
        {
            "sequence": len(server.events) + 1,
            "type": f"workflow.{kind}",
            "payload": {"turn_id": turn, **payload},
        }
    )


def saved_network(server):
    # Numeric 1 and string "1" belong to different communities.
    ids = [1, "1", 2, 3, 4, 5]
    pairs = [(1, 2), (2, 3), (3, 1), ("1", 4), (4, 5), (5, "1"), (3, 4)]
    server.graph = {
        "graph": {"directed": False},
        "vertices": [{"id": value, "label": f"Vertex {value}"} for value in ids],
        "edges": [
            {"id": i, "source": a, "target": b} for i, (a, b) in enumerate(pairs)
        ],
        "vertex_count": 6,
        "edge_count": 7,
    }
    server.files = [
        {
            "id": "network",
            "original_name": "network.json",
            "role": "graph",
            "metadata": {"vertex_count": 6, "edge_count": 7},
        }
    ]
    workflow = deepcopy(WORKFLOW)
    workflow.update(
        status="completed", mode="normal", complete=True, planning_turn_id="first"
    )
    workflow["input_files"] = {"main": {"kind": "graph", "file_id": "network"}}
    workflow["validation"]["plan"]["steps"][0].update(
        operation="community-detection", parameters={}
    )
    workflow["steps"] = {"core": {"status": "completed"}}
    server.workflows = [workflow]
    groups = [
        {"group": 0, "vertices": [1, 2, 3]},
        {"group": 1, "vertices": ["1", 4, 5]},
    ]
    server.results[workflow["id"]] = {
        "complete": True,
        "steps": {
            "core": {
                "result": {
                    "operation": "community-detection",
                    "complete": True,
                    "quality": "heuristic",
                    "backend": {"device": "cpu"},
                    "diagnostics": {"solver": "native_positive_gain_vertex_moves"},
                    "ports": {
                        "partition": {
                            "type": "vertex_partition",
                            "complete": True,
                            "value": [
                                {"vertex": vertex, "part": group["group"]}
                                for group in groups
                                for vertex in group["vertices"]
                            ],
                        },
                        "groups": {
                            "type": "vertex_groups",
                            "complete": True,
                            "value": groups,
                        },
                    },
                }
            }
        },
    }


def saved_turn(server, turn, question, *, retry=False):
    event(server, "chat", turn, role="user", message=question, mode="normal")
    for stage in ["family", "operation", "plan"] + (["plan"] if retry else []):
        event(server, "planning", turn, stage=stage, status="running")
        event(
            server,
            "reasoning",
            turn,
            stage=stage,
            model="Authored test model",
            text=f"Reasoning for {turn}: {stage}",
        )
        event(
            server,
            "planning",
            turn,
            stage=stage,
            status="ready",
            message=f"Decision for {turn}: {stage}",
            **(
                {"plan": server.workflows[0]["validation"]["plan"]}
                if stage == "plan"
                else {}
            ),
        )
        if stage == "plan":
            event(server, "planning", turn, stage="validation", status="running")
            event(
                server,
                "planning",
                turn,
                stage="validation",
                status="failed" if retry else "passed",
                message="Input needs clarification"
                if retry
                else "Plan passed validation",
            )
    event(
        server,
        "chat",
        turn,
        role="assistant",
        status="needs_information" if retry else "ready",
        message="Which input should be used?" if retry else "The analysis is ready.",
    )


def open_saved(browser, server, page="chat"):
    server.responses[0].release.set()
    browser.get(f"{server.url}/#workspace/saved-session/{page}")
    wait_for(
        browser,
        "GraphMineWorkspace.state.result && GraphMineWorkspace.state.caps && !GraphMineWorkspace.state.busy",
    )


def assert_latest_user_visible(browser):
    assert browser.execute_script("""
        const scroll = document.getElementById('conversation-scroll').getBoundingClientRect();
        const message = [...document.querySelectorAll('#messages .user')].at(-1).getBoundingClientRect();
        return message.top >= scroll.top && message.bottom <= scroll.bottom;
    """)


def test_all_questions_reasoning_retries_and_validation_survive_reload(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_network(server)
    saved_turn(server, "first", "Find the communities")
    saved_turn(server, "second", "Explain the groups", retry=True)
    open_saved(browser, server)
    for reload in [False, True]:
        if reload:
            browser.refresh()
            wait_for(
                browser,
                "GraphMineWorkspace.state.result && !GraphMineWorkspace.state.busy",
            )
        assert browser.find_element(By.ID, "reasoning-count").text == "7"
        assert (
            len(
                browser.find_elements(
                    By.CSS_SELECTOR, "#model-reasoning .reasoning-turn"
                )
            )
            == 2
        )
        assert (
            len(
                browser.find_elements(
                    By.CSS_SELECTOR,
                    '#activity-list [data-turn="second"] [data-stage="plan"]',
                )
            )
            == 2
        )
        assert (
            len(
                browser.find_elements(
                    By.CSS_SELECTOR,
                    '#activity-list [data-turn="second"] [data-stage="validation"].failed',
                )
            )
            == 2
        )
        assert (
            browser.find_element(By.ID, "chat-status").text == "Waiting for your reply"
        )
        assert browser.execute_script(
            "return document.getElementById('model-reasoning-panel').compareDocumentPosition(document.getElementById('activity-list')) & Node.DOCUMENT_POSITION_FOLLOWING"
        )
        assert_latest_user_visible(browser)
    browser.find_element(
        By.CSS_SELECTOR, '#model-reasoning [data-turn="first"] details summary'
    ).click()
    assert "Reasoning for first" in browser.find_element(By.ID, "model-reasoning").text
    assert "attempt 2" in browser.find_element(By.ID, "model-reasoning").text


def test_delayed_old_events_cannot_hide_new_followup(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    saved_turn(server, "first", "Find the communities")
    started, release = threading.Event(), threading.Event()
    request = {}

    def plan(body):
        request.update(body)
        event(
            server,
            "chat",
            "earlier",
            role="user",
            message="An earlier question arrived late",
            mode="normal",
        )
        event(
            server,
            "chat",
            "earlier",
            role="assistant",
            message="Earlier response",
            status="needs_information",
        )
        started.set()
        release.wait(15)
        response = {
            "turn_id": body["request_id"],
            "role": "assistant",
            "status": "needs_information",
            "message": "Which group should I explain?",
            "plan": None,
        }
        event(
            server,
            "chat",
            body["request_id"],
            **{key: value for key, value in response.items() if key != "turn_id"},
        )
        return response

    server.plan_handler = plan
    open_saved(browser, server)
    browser.execute_script(
        "document.getElementById('workflow-panel').style.minHeight = '1600px'"
    )
    browser.find_element(By.ID, "question").send_keys(
        "Now explain my follow-up question"
    )
    browser.find_element(By.ID, "plan-question").click()
    try:
        assert started.wait(2)
        wait_for(
            browser,
            "document.getElementById('messages').textContent.includes('An earlier question arrived late')",
        )
        assert (
            browser.execute_script(
                "return GraphMineWorkspace.state.pendingQuestion?.id"
            )
            == request["request_id"]
        )
        assert_latest_user_visible(browser)
        event(
            server,
            "chat",
            request["request_id"],
            role="user",
            message=request["message"],
            mode="normal",
        )
        wait_for(browser, "!GraphMineWorkspace.state.pendingQuestion")
        assert_latest_user_visible(browser)
    finally:
        release.set()
    wait_for(
        browser,
        "!GraphMineWorkspace.state.busy && document.getElementById('chat-status').textContent === 'Waiting for your reply'",
    )
    assert (
        len(
            browser.find_elements(
                By.CSS_SELECTOR, f'#messages .user[data-turn="{request["request_id"]}"]'
            )
        )
        == 1
    )
    assert_latest_user_visible(browser)


def test_community_overview_filter_and_reset_preserve_typed_ids(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_network(server)
    saved_turn(server, "first", "Find the communities")
    open_saved(browser, server, "results/saved-analysis")
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 6")
    snapshot = browser.execute_script("""
        const cy = GraphMineWorkspace.state.cy;
        return {edges: cy.edges().length, colors: cy.nodes().map(n => [n.id(), n.data('color')]),
                positions: cy.nodes().map(n => n.position())};
    """)
    assert snapshot["edges"] == 7
    colors = dict(snapshot["colors"])
    assert len(set(colors.values())) == 2
    assert len({(p["x"], p["y"]) for p in snapshot["positions"]}) == 6
    assert (
        "Local vertex moves" in browser.find_element(By.ID, "result-completeness").text
    )
    assert (
        "6 of 6 vertices; 7 of 7 connections"
        in browser.find_element(By.ID, "preview-scope").text
    )
    select = Select(browser.find_element(By.ID, "graph-group"))
    select.select_by_index(2)
    wait_for(browser, "GraphMineWorkspace.state.cy.nodes().length === 3")
    filtered = browser.execute_script(
        "return {ids: GraphMineWorkspace.state.cy.nodes().map(n => n.data('entity')), edges: GraphMineWorkspace.state.cy.edges().length, colors: GraphMineWorkspace.state.cy.nodes().map(n => [n.id(), n.data('color')])}"
    )
    assert filtered["ids"] == ["1", 4, 5]
    assert filtered["edges"] == 3
    assert all(colors[key] == color for key, color in filtered["colors"])
    browser.find_element(By.ID, "clear-selection").click()
    assert (
        browser.execute_script("return GraphMineWorkspace.state.cy.nodes().length") == 6
    )
    browser.find_element(By.CSS_SELECTOR, '#chart [data-result-row="0"]').click()
    assert browser.execute_script(
        "return GraphMineWorkspace.state.cy.nodes().map(n => n.data('entity'))"
    ) == [1, 2, 3]
    assert (
        browser.execute_script("return GraphMineWorkspace.state.cy.edges().length") == 3
    )
    browser.find_element(By.CSS_SELECTOR, "#group-legend button").click()
    assert (
        browser.execute_script("return GraphMineWorkspace.state.cy.nodes().length") == 6
    )
    browser.refresh()
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 6")
    assert (
        browser.execute_script("return GraphMineWorkspace.state.cy.edges().length") == 7
    )


def saved_cliques(server, *, complete=True):
    saved_network(server)
    workflow = server.workflows[0]
    workflow["validation"]["plan"]["steps"][0]["operation"] = "maximal-cliques"
    result = server.results[workflow["id"]]["steps"]["core"]["result"]
    result.update(operation="maximal-cliques", quality="exact", complete=complete)
    groups = [
        {"group": 0, "vertices": [1, 2, 3], "size": 3},
        {"group": 1, "vertices": ["1", 2, 3], "size": 3},
        {"group": 2, "vertices": [3, 4], "size": 2},
        {"group": 3, "vertices": [4, 5], "size": 2},
    ]
    result["ports"] = {
        "groups": {"type": "vertex_groups", "complete": complete, "value": groups}
    }
    result["diagnostics"] = {}
    pairs = [(1, 2), (2, 3), (3, 1), ("1", 2), ("1", 3), (3, 4), (4, 5)]
    server.graph["edges"] = [
        {"id": i, "source": a, "target": b} for i, (a, b) in enumerate(pairs)
    ]
    saved_turn(server, "first", "Find the maximal cliques")
    return result


def test_overlapping_cliques_filter_dropdown_chart_and_table(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_cliques(server)
    open_saved(browser, server, "results/saved-analysis")
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 6")
    assert browser.find_element(By.ID, "graph-group-caption").text == "Show clique"
    select = Select(browser.find_element(By.ID, "graph-group"))
    assert [option.text for option in select.options] == [
        "Full network",
        "Clique 1 · 3 vertices",
        "Clique 2 · 3 vertices",
        "Clique 3 · 2 vertices",
        "Clique 4 · 2 vertices",
    ]
    assert "4 returned cliques" in browser.find_element(By.ID, "graph-group-hint").text
    assert "share vertices" in browser.find_element(By.ID, "graph-group-hint").text
    assert not browser.find_element(By.ID, "group-legend").is_displayed()
    # An overlapping collection must not look like a disjoint partition.
    assert browser.execute_script("""
        return new Set(GraphMineWorkspace.state.cy.nodes().map(n => n.data('color'))).size === 1
            && document.querySelector('#graph-layout [value="groups"]').disabled;
    """)

    def assert_clique(ids, edges, row):
        assert (
            browser.execute_script(
                "return GraphMineWorkspace.state.cy.nodes().map(n => n.data('entity'))"
            )
            == ids
        )
        assert (
            browser.execute_script("return GraphMineWorkspace.state.cy.edges().length")
            == edges
        )
        assert browser.execute_script("""
            return [...document.querySelectorAll('#result-table [aria-selected="true"]')]
                .map(row => Number(row.dataset.resultRow));
        """) == [row]
        assert Select(
            browser.find_element(By.ID, "graph-group")
        ).first_selected_option.text.startswith(f"Clique {row + 1} ·")

    select.select_by_index(2)
    assert_clique(["1", 2, 3], 3, 1)
    assert (
        "Clique 2: 3 of 3 vertices; 3 connections within this clique"
        in browser.find_element(By.ID, "preview-scope").text
    )
    browser.find_element(By.CSS_SELECTOR, '#chart [data-result-row="0"]').click()
    assert_clique([1, 2, 3], 3, 0)
    browser.find_element(
        By.CSS_SELECTOR, '#result-table [data-result-row="2"] button'
    ).click()
    assert_clique([3, 4], 1, 2)
    assert "Clique 3" in browser.find_element(By.ID, "result-table").text
    browser.find_element(By.ID, "clear-selection").click()
    assert (
        browser.execute_script("return GraphMineWorkspace.state.cy.nodes().length") == 6
    )
    select.select_by_index(4)
    assert_clique([4, 5], 1, 3)
    select.select_by_value("")
    assert (
        browser.execute_script("return GraphMineWorkspace.state.cy.edges().length") == 7
    )
    assert not browser.find_elements(
        By.CSS_SELECTOR, '#result-table [aria-selected="true"]'
    )
    browser.find_element(By.ID, "table-search").send_keys("Clique 4")
    assert browser.find_element(By.ID, "table-count").text == "1 of 4 retained rows"
    browser.find_element(By.CSS_SELECTOR, "#result-table tbody button").click()
    assert_clique([4, 5], 1, 3)


def test_partial_clique_collection_and_graph_preview_remain_explicit(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_cliques(server, complete=False)
    # The retained cliques are still filterable, but vertex 5 is outside the preview.
    server.graph["vertices"] = server.graph["vertices"][:-1]
    server.graph["edges"] = server.graph["edges"][:-1]
    server.graph.update(vertices_truncated=True, edges_truncated=True)
    open_saved(browser, server, "results/saved-analysis")
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 5")
    Select(browser.find_element(By.ID, "graph-group")).select_by_index(4)
    assert browser.execute_script(
        "return GraphMineWorkspace.state.cy.nodes().map(n => n.data('entity'))"
    ) == [4]
    assert (
        browser.execute_script("return GraphMineWorkspace.state.cy.edges().length") == 0
    )
    scope = browser.find_element(By.ID, "preview-scope").text
    assert "Clique 4: 1 of 2 vertices" in scope
    assert "preview is truncated" in scope
    assert (
        "output is incomplete"
        in browser.find_element(By.ID, "result-completeness").text
    )


def test_count_only_cliques_do_not_invent_filters(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    result = saved_cliques(server, complete=False)
    result["ports"]["groups"]["value"] = []
    open_saved(browser, server, "results/saved-analysis")
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 6")
    assert not browser.find_element(By.ID, "graph-group-label").is_displayed()
    assert not browser.find_element(By.ID, "graph-group-hint").is_displayed()
    assert "count-only" in browser.find_element(By.ID, "result-completeness").text


def test_saved_cliques_open_when_latest_analysis_returns_a_graph(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_cliques(server)
    latest = deepcopy(server.workflows[0])
    latest["id"] = "newest-graph"
    latest["validation"]["plan"]["steps"][0]["operation"] = "induced-subgraph"
    server.workflows.append(latest)
    server.results[latest["id"]] = {
        "complete": True,
        "steps": {
            "core": {
                "result": {
                    "operation": "induced-subgraph",
                    "complete": True,
                    "quality": "exact",
                    "backend": {"device": "cpu"},
                    "ports": {
                        "graph": {
                            "type": "graph",
                            "complete": True,
                            "value": {
                                key: deepcopy(server.graph[key])
                                for key in ["graph", "vertices", "edges"]
                            },
                        }
                    },
                }
            }
        },
    }
    # Restoring a conversation first loads its newest analysis, then the route.
    open_saved(browser, server, "results/saved-analysis")
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 6")
    assert browser.find_element(By.ID, "graph-group-caption").text == "Show clique"
    Select(browser.find_element(By.ID, "result-select")).select_by_value("newest-graph")
    wait_for(browser, "GraphMineWorkspace.state.port?.type === 'graph'")
    assert not browser.find_element(By.ID, "graph-group-label").is_displayed()
    browser.find_element(By.CSS_SELECTOR, "#result-table tbody button").click()
    assert (
        browser.execute_script(
            "return GraphMineWorkspace.state.cy.nodes('.chosen').length"
        )
        == 6
    )
    Select(browser.find_element(By.ID, "result-select")).select_by_value(
        "saved-analysis"
    )
    wait_for(browser, "GraphMineWorkspace.state.port?.type === 'vertex_groups'")
    Select(browser.find_element(By.ID, "graph-group")).select_by_index(2)
    assert browser.execute_script(
        "return GraphMineWorkspace.state.cy.nodes().map(n => n.data('entity'))"
    ) == ["1", 2, 3]


@pytest.mark.parametrize("error_code", ["concurrency_limit", "quota_exceeded"])
def test_clique_preview_retries_busy_requests_only(
    loading_browser, loading_server, error_code
):
    browser, server = loading_browser, loading_server
    saved_cliques(server)
    server.preview_failures = [error_code]
    open_saved(browser, server, "results/saved-analysis")
    if error_code == "concurrency_limit":
        wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 6")
        assert server.preview_calls == 2
        assert browser.find_element(By.ID, "graph-group-caption").text == "Show clique"
    else:
        assert server.preview_calls == 1
        assert browser.find_element(By.ID, "notice").text == "quota_exceeded"
