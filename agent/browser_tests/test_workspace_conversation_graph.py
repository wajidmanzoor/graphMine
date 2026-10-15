"""Browser regressions for conversation races, partitions and overlapping cliques."""

import threading
import time
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
                browser.find_elements(By.CSS_SELECTOR, "#activity-list .reasoning-turn")
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
        # Each question's reasoning sits inside that question's own timeline.
        assert browser.execute_script(
            "return document.querySelectorAll('#activity-list .activity-turn > .turn-reasoning').length === 2"
        )
        assert_latest_user_visible(browser)
    for turn in ("first", "second"):
        browser.find_element(
            By.CSS_SELECTOR,
            f'.activity-turn[data-turn="{turn}"] .turn-reasoning > summary',
        ).click()
    browser.find_element(
        By.CSS_SELECTOR,
        '[data-turn="first"] .turn-reasoning .reasoning-record > summary',
    ).click()
    activity = browser.find_element(By.ID, "activity-list").text
    assert "Reasoning for first" in activity
    assert "attempt 2" in activity


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


def test_interrupted_question_retries_with_its_original_inputs(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_network(server)
    inputs = {"main": {"file_id": "network", "kind": "graph"}}
    event(
        server,
        "chat",
        "lost",
        role="user",
        message="Find the communities",
        mode="interactive",
        inputs=inputs,
        device="cpu",
        previous_workflow_id=None,
    )
    event(server, "planning", "lost", stage="family", status="running")
    event(
        server,
        "chat",
        "lost",
        role="assistant",
        status="failed",
        code="interrupted",
        retryable=True,
        message="Planning was interrupted by a server restart. Please try again.",
    )
    request = {}

    def plan(body):
        request.update(body)
        event(
            server,
            "chat",
            body["request_id"],
            role="user",
            **{key: body[key] for key in ("message", "mode")},
        )
        event(
            server,
            "chat",
            body["request_id"],
            role="assistant",
            status="needs_information",
            message="Which groups should I compare?",
        )
        return {
            "turn_id": body["request_id"],
            "status": "needs_information",
            "message": "Which groups should I compare?",
            "plan": None,
        }

    server.plan_handler = plan
    open_saved(browser, server)
    browser.find_element(By.CSS_SELECTOR, '[data-retry="lost"]').click()
    wait_for(
        browser,
        "!document.querySelector('[data-retry]') && !GraphMineWorkspace.state.busy",
    )
    assert request["message"] == "Find the communities"
    assert request["inputs"] == inputs
    assert (request["mode"], request["device"]) == ("interactive", "cpu")
    assert request["request_id"] != "lost"


def test_conversation_polling_slows_when_idle_and_stops_when_signed_out(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_network(server)
    open_saved(browser, server)
    start = len(server.event_times)
    deadline = time.monotonic() + 15
    while len(server.event_times) < start + 4 and time.monotonic() < deadline:
        time.sleep(0.2)
    times = server.event_times[start : start + 4]
    gaps = [later - earlier for earlier, later in zip(times, times[1:])]
    # Fixed polling would repeat every 1.4 seconds.
    assert len(gaps) == 3 and gaps[-1] > 2.5, gaps
    server.events_status = 401
    deadline = time.monotonic() + 15
    while server.event_times[-1] < times[-1] + 0.1 and time.monotonic() < deadline:
        time.sleep(0.2)
    stopped = len(server.event_times)
    time.sleep(12)  # Longer than the slowest polling interval.
    assert len(server.event_times) == stopped


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


def test_finished_analysis_answers_in_chat_with_computed_facts(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_network(server)
    saved_turn(server, "first", "Find the communities")
    statements = {
        "f1": "Community detection found 2 groups.",
        "f2": "The largest has 3 members: Vertex 1, Vertex 2, Vertex 3.",
    }
    event(
        server,
        "answer",
        "first",
        workflow_id="saved-analysis",
        revision=1,
        lead="Two communities split the network.",
        fact_ids=["f2", "f1"],
        facts=[{"id": key, "statement": text} for key, text in statements.items()],
        source="model",
    )
    open_saved(browser, server)
    bubble = '.chat-message.assistant[data-turn="first"]'
    lead = browser.find_element(By.CSS_SELECTOR, f"{bubble} .answer-lead")
    assert lead.text == "Two communities split the network."
    facts = browser.find_elements(By.CSS_SELECTOR, f"{bubble} .answer-facts li")
    assert [fact.text for fact in facts] == [statements["f2"], statements["f1"]]


def test_question_about_a_selected_clique_sends_its_position(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_cliques(server)
    request = {}

    def plan(body):
        request.update(body)
        for role, message in (
            ("user", body["message"]),
            ("assistant", "Which measure?"),
        ):
            event(
                server,
                "chat",
                body["request_id"],
                role=role,
                message=message,
                mode="normal",
                status="needs_information",
            )
        return {
            "turn_id": body["request_id"],
            "status": "needs_information",
            "message": "Which measure?",
            "plan": None,
        }

    server.plan_handler = plan
    open_saved(browser, server, "results/saved-analysis")
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 6")
    Select(browser.find_element(By.ID, "graph-group")).select_by_index(2)
    browser.find_element(By.ID, "back-to-chat").click()
    chip = browser.find_element(By.ID, "selection-chip")
    assert chip.is_displayed() and "Asking about Clique 2" in chip.text
    browser.find_element(By.ID, "question").send_keys("Who is central here?")
    browser.find_element(By.ID, "plan-question").click()
    wait_for(browser, "!GraphMineWorkspace.state.busy")
    assert request["selection"] == {
        "workflow_id": "saved-analysis",
        "step": "core",
        "port": "groups",
        "index": 1,
        "label": "Clique 2",
    }
    browser.find_element(By.ID, "clear-question-selection").click()
    assert not chip.is_displayed()


def test_reasoning_streams_while_a_stage_runs(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    event(server, "chat", "live", role="user", message="Find hubs", mode="normal")
    event(server, "planning", "live", stage="family", status="running")
    event(server, "reasoning.delta", "live", stage="family", text="Hubs suggest ")
    event(server, "reasoning.delta", "live", stage="family", text="centrality.")
    open_saved(browser, server)
    live = '#activity-list [data-live="family"] pre'
    wait_for(
        browser,
        f"document.querySelector('{live}')?.textContent === 'Hubs suggest centrality.'",
    )
    event(
        server,
        "reasoning",
        "live",
        stage="family",
        model="Authored test model",
        text="Hubs suggest centrality. Done.",
    )
    wait_for(browser, "!document.querySelector('[data-live]')")


def test_clarification_choices_are_sent_as_replies(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    event(server, "chat", "ask", role="user", message="Find groups", mode="normal")
    event(
        server,
        "chat",
        "ask",
        role="assistant",
        status="needs_information",
        message="Which kind of group?",
        choices=["The single largest clique", "Every maximal clique"],
    )
    request = {}

    def plan(body):
        request.update(body)
        return {
            "turn_id": body["request_id"],
            "status": "unsupported",
            "message": "Recorded",
            "plan": None,
        }

    server.plan_handler = plan
    open_saved(browser, server)
    browser.find_element(
        By.CSS_SELECTOR, '[data-choice="Every maximal clique"]'
    ).click()
    wait_for(browser, "!GraphMineWorkspace.state.busy")
    assert request["message"] == "Every maximal clique"


def test_conversation_can_be_renamed_and_deleted(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    open_saved(browser, server)
    browser.execute_script(
        "window.prompt = () => 'Renamed study'; window.confirm = () => true;"
    )
    browser.find_element(By.ID, "rename-session").click()
    wait_for(browser, "!GraphMineWorkspace.state.busy")
    assert ("PATCH", "/api/sessions/saved-session", {"title": "Renamed study"}) in (
        server.requests
    )
    browser.find_element(By.ID, "delete-session").click()
    wait_for(browser, "!GraphMineWorkspace.state.busy")
    assert ("DELETE", "/api/sessions/saved-session", None) in server.requests


def test_selected_group_is_loaded_from_the_full_graph(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_cliques(server)
    full = deepcopy(server.graph)
    # The bounded preview misses vertex 5, a member of Clique 4.
    server.graph["vertices"] = [v for v in full["vertices"] if v["id"] != 5]
    server.graph["edges"] = [
        e for e in full["edges"] if 5 not in (e["source"], e["target"])
    ]
    server.group_graph = {
        "graph": full["graph"],
        "vertex_count": 2,
        "edge_count": 1,
        "vertices": [v for v in full["vertices"] if v["id"] in (4, 5)],
        "edges": [e for e in full["edges"] if {e["source"], e["target"]} == {4, 5}],
    }
    open_saved(browser, server, "results/saved-analysis")
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 5")
    Select(browser.find_element(By.ID, "graph-group")).select_by_index(4)
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 2")
    assert server.group_requests[-1].endswith("/groups/3/graph")
    assert (
        browser.execute_script("return GraphMineWorkspace.state.cy.edges().length") == 1
    )


def test_scores_size_nodes_and_paths_highlight_their_connections(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_network(server)
    result = server.results["saved-analysis"]["steps"]["core"]["result"]
    result["operation"] = "pagerank"
    result["ports"] = {
        "scores": {
            "type": "vertex_scores",
            "complete": True,
            "value": [
                {"vertex": 1, "score": 0.1},
                {"vertex": 2, "score": 0.5},
                {"vertex": 3, "score": 0.9},
            ],
        },
        "paths": {
            "type": "path_set",
            "complete": True,
            "value": [{"vertices": [1, 2, 3], "edges": [0, 1]}],
        },
    }
    open_saved(browser, server, "results/saved-analysis")
    Select(browser.find_element(By.ID, "result-port")).select_by_value("scores")
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 6")
    sizes = dict(
        browser.execute_script(
            "return GraphMineWorkspace.state.cy.nodes().map(n => [String(n.data('entity')) + typeof n.data('entity'), n.data('size')])"
        )
    )
    assert sizes["3number"] > sizes["2number"] > sizes["1number"]
    assert sizes["4number"] == 25  # Unscored vertices keep the default size.
    assert "Node size shows score" in browser.find_element(By.ID, "preview-scope").text
    Select(browser.find_element(By.ID, "result-port")).select_by_value("paths")
    wait_for(browser, "GraphMineWorkspace.state.port?.type === 'path_set'")
    browser.find_element(
        By.CSS_SELECTOR, '#result-table [data-result-row="0"] button'
    ).click()
    chosen = browser.execute_script(
        "return GraphMineWorkspace.state.cy.edges('.chosen').map(e => e.data('original').id)"
    )
    assert sorted(chosen) == [0, 1]


def test_long_outputs_page_and_search_on_the_server(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    result = server.results["saved-analysis"]["steps"]["core"]["result"]
    rows = [{"vertex": i, "score": i / 10} for i in (1, 2, 3)]
    result["ports"] = {
        "scores": {
            "type": "vertex_scores",
            "complete": True,
            "value": rows,
            "value_truncated": True,
            "total_items": 5000,
        }
    }
    server.port_page = {"items": [rows[1]], "matched_items": 12, "total_items": 5000}
    open_saved(browser, server, "results/saved-analysis")
    Select(browser.find_element(By.ID, "result-port")).select_by_value("scores")
    wait_for(
        browser,
        "document.getElementById('table-count').textContent === '12 of 5,000 rows'",
    )
    browser.find_element(By.ID, "table-search").send_keys("vertex:2")
    deadline = time.monotonic() + 5
    while not any("search=vertex%3A2" in path for path in server.port_requests):
        assert time.monotonic() < deadline, server.port_requests
        time.sleep(0.1)
    assert "offset=0" in server.port_requests[-1]
    assert "searches all 5,000" in browser.find_element(By.ID, "table-scope").text
