"""Recovery, mobile navigation, and result exploration through browser controls."""

from copy import deepcopy

import pytest
import test_workspace_loading as loading_fixtures
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from test_workspace_conversation_graph import open_saved, saved_cliques, saved_network
from test_workspace_loading import wait_for

loading_browser = loading_fixtures.loading_browser
loading_server = loading_fixtures.loading_server


def failed_analysis(server):
    saved_network(server)
    record = server.workflows[0]
    record.update(
        status="failed", complete=False, error={"message": "Memory limit reached"}
    )
    record["validation"]["plan"]["steps"][0].update(
        operation="k-core", parameters={"requested_k": 2}
    )
    record["steps"]["core"] = {"status": "failed"}

    def revise(path, body):
        assert path == "/api/workflows/saved-analysis/revise"
        assert body["expected_revision"] == record["revision"]
        record.update(
            status="awaiting_review",
            mode=body["mode"],
            revision=record["revision"] + 1,
            input_files=body["inputs"],
            error=None,
        )
        record["validation"]["plan"] = body["plan"]
        return deepcopy(record)

    server.post_handler = revise
    return record


def test_adjusting_failed_parameters_saves_for_review(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    failed_analysis(server)
    open_saved(browser, server)
    browser.find_element(By.ID, "adjust-parameters").click()
    value = browser.find_element(By.ID, "edit-core-requested_k")
    value.clear()
    value.send_keys("3")
    browser.find_element(By.CSS_SELECTOR, '[data-edit-step="core"] button').click()
    wait_for(
        browser,
        "GraphMineWorkspace.state.record.revision === 2 && !GraphMineWorkspace.state.busy",
    )
    method, path, body = server.requests[-1]
    assert method == "POST" and path.endswith("/revise")
    assert body["mode"] == "interactive"
    assert body["plan"]["steps"][0]["parameters"]["requested_k"] == 3
    assert body["inputs"]["main"]["file_id"] == "network"
    assert browser.find_element(By.ID, "approve-plan").is_displayed()
    assert not any(path.endswith("/run") for _, path, _ in server.requests)


def test_narrowing_replaces_only_chosen_input_and_waits_for_review(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    record = failed_analysis(server)
    record["input_files"]["reference"] = {"file_id": "network", "kind": "graph"}
    original = deepcopy(record["validation"]["plan"])
    for name, count in [("smaller", 3), ("larger", 50)]:
        server.files.append(
            {
                "id": name,
                "original_name": f"{name}.json",
                "role": "graph",
                "metadata": {"vertex_count": count, "edge_count": count},
            }
        )
    open_saved(browser, server)
    browser.find_element(By.ID, "narrow-input").click()
    choices = Select(browser.find_element(By.ID, "narrow-file"))
    assert [option.get_attribute("value") for option in choices.options] == [
        "",
        "smaller",
    ]
    choices.select_by_value("smaller")
    browser.find_element(By.ID, "save-narrow-input").click()
    wait_for(
        browser,
        "GraphMineWorkspace.state.record.revision === 2 && !GraphMineWorkspace.state.busy",
    )
    body = server.requests[-1][2]
    assert body["mode"] == "interactive" and body["plan"] == original
    assert body["inputs"] == {
        "main": {"file_id": "smaller", "kind": "graph"},
        "reference": {"file_id": "network", "kind": "graph"},
    }
    assert not browser.find_element(By.ID, "narrow-dialog").is_displayed()


def test_mobile_conversation_has_explicit_data_navigation(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_network(server)
    browser.set_window_size(390, 844)
    open_saved(browser, server)
    assert not browser.find_element(By.ID, "data-sidebar").is_displayed()
    button = browser.find_element(By.ID, "toggle-data")
    assert button.is_displayed() and button.get_attribute("aria-expanded") == "false"
    button.click()
    assert browser.find_element(By.ID, "data-sidebar").is_displayed()
    assert button.get_attribute("aria-expanded") == "true"
    assert browser.find_element(By.ID, "active-input").is_displayed()
    assert browser.execute_script(
        "return document.documentElement.scrollWidth <= innerWidth"
    )
    browser.set_window_size(1440, 1000)
    assert browser.find_element(By.ID, "data-sidebar").is_displayed()


def test_home_keeps_saved_conversations_in_the_sidebar(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    server.responses[0].release.set()
    browser.get(server.url)
    wait_for(browser, "document.querySelector('#recent-sessions a') !== null")
    assert browser.execute_script("""
        const history = document.getElementById('recent-section').getBoundingClientRect();
        const home = document.getElementById('domain-view').getBoundingClientRect();
        return history.right <= home.left && history.top >= 0 && history.bottom <= innerHeight;
    """)
    browser.find_element(By.CSS_SELECTOR, "#recent-sessions a").click()
    wait_for(browser, "GraphMineWorkspace.state.session?.id === 'saved-session'")


def test_clique_size_and_typed_member_filters_and_overlap(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_cliques(server)
    open_saved(browser, server, "results/saved-analysis")
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 6")
    assert (
        "4 cliques · 6 distinct members · sizes 2–3 · 3 shared members"
        in browser.find_element(By.ID, "group-summary").text
    )
    browser.find_element(By.ID, "group-min-size").send_keys("3")
    assert browser.find_element(By.ID, "table-count").text == "2 of 4 retained rows"
    member = browser.find_element(By.ID, "group-member")
    member.send_keys('"1"')
    assert browser.find_element(By.ID, "table-count").text == "1 of 4 retained rows"
    assert "Clique 2" in browser.find_element(By.ID, "result-table").text
    member.clear()
    member.send_keys("1")
    assert "Clique 1" in browser.find_element(By.ID, "result-table").text
    browser.find_element(By.ID, "group-max-size").send_keys("2")
    assert "Minimum size" in browser.find_element(By.ID, "group-filter-status").text
    assert "No matching output" in browser.find_element(By.ID, "result-table").text
    browser.find_element(By.ID, "clear-group-filters").click()
    assert browser.find_element(By.ID, "table-count").text == "4 of 4 retained rows"
    browser.find_element(By.ID, "highlight-overlap").click()
    assert browser.execute_script(
        "return GraphMineWorkspace.state.cy.nodes('.shared-member').map(n => n.data('entity'))"
    ) == [2, 3, 4]
    Select(browser.find_element(By.ID, "graph-group")).select_by_index(1)
    assert browser.execute_script(
        "return GraphMineWorkspace.state.cy.nodes('.shared-member').map(n => n.data('entity'))"
    ) == [2, 3]


@pytest.mark.parametrize("fails", [False, True])
def test_overlap_uses_unloaded_groups_and_reports_lookup_failure(
    loading_browser, loading_server, fails
):
    browser, server = loading_browser, loading_server
    result = saved_cliques(server)
    groups = result["ports"]["groups"]
    retained = deepcopy(groups["value"])
    groups.update(
        value=retained[:1],
        value_truncated=True,
        total_items=len(retained),
        group_summary={
            "groups": 4,
            "unique_members": 6,
            "shared_members": 3,
            "smallest": 2,
            "largest": 3,
        },
    )
    server.port_page = {
        "items": retained[:1],
        "positions": [0],
        "offset": 0,
        "matched_items": 4,
        "total_items": 4,
    }

    def memberships(path, body):
        assert path.endswith("/core/ports/groups/memberships")
        if fails:
            return {}  # An unreadable response must not appear as zero overlap.
        return {
            "memberships": [
                {
                    "vertex": vertex,
                    "groups": sum(
                        any(
                            type(member) is type(vertex) and member == vertex
                            for member in group["vertices"]
                        )
                        for group in retained
                    ),
                }
                for vertex in body["vertices"]
            ]
        }

    server.post_handler = memberships
    open_saved(browser, server, "results/saved-analysis")
    wait_for(browser, "GraphMineWorkspace.state.cy?.nodes().length === 6")
    assert browser.find_element(By.ID, "overlap-control").is_displayed()
    browser.find_element(By.ID, "highlight-overlap").click()
    if fails:
        wait_for(
            browser,
            "document.getElementById('notice').textContent.includes('Could not check shared members')",
        )
        assert not browser.find_element(By.ID, "highlight-overlap").is_selected()
        assert (
            browser.execute_script(
                "return GraphMineWorkspace.state.cy.nodes('.shared-member').length"
            )
            == 0
        )
    else:
        wait_for(
            browser, "GraphMineWorkspace.state.cy.nodes('.shared-member').length === 3"
        )
        assert browser.execute_script(
            "return GraphMineWorkspace.state.cy.nodes('.shared-member').map(n => n.data('entity'))"
        ) == [2, 3, 4]
        Select(browser.find_element(By.ID, "graph-group")).select_by_index(1)
        assert browser.execute_script(
            "return GraphMineWorkspace.state.cy.nodes('.shared-member').map(n => n.data('entity'))"
        ) == [2, 3]
        # The already-checked visible IDs are cached when the graph is filtered.
        assert len(server.requests) == 1
        assert (
            "full retained output" in browser.find_element(By.ID, "group-summary").text
        )


def test_filtered_remote_group_keeps_its_original_position(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    result = saved_cliques(server)
    result["ports"]["groups"].update(value_truncated=True, total_items=1000)
    server.port_page = {
        "items": [{"group": 900, "vertices": [4, 5]}],
        "positions": [900],
        "offset": 0,
        "matched_items": 1,
        "total_items": 1000,
    }
    open_saved(browser, server, "results/saved-analysis")
    browser.find_element(By.ID, "group-min-size").send_keys("2")
    browser.find_element(By.ID, "group-member").send_keys("5")
    wait_for(
        browser,
        "document.getElementById('table-count').textContent === '1 of 1,000 rows'",
    )
    wait_for(browser, "!GraphMineWorkspace.state.busy")
    browser.find_element(By.CSS_SELECTOR, "#result-table tbody button").click()
    assert "Clique 901" in browser.find_element(By.ID, "preview-scope").text
    assert any(
        "min_size=2" in path and "member=5" in path for path in server.port_requests
    )
    assert browser.execute_script(
        "return GraphMineWorkspace.state.cy.nodes().map(n => n.data('entity'))"
    ) == [4, 5]
    browser.find_element(By.ID, "chat-page-link").click()
    wait_for(browser, "GraphMineWorkspace.state.view === 'chat'")
    assert "Clique 901" in browser.find_element(By.ID, "selection-label").text


def test_flow_arrows_use_assignment_direction_on_undirected_graph(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_network(server)
    result = server.results["saved-analysis"]["steps"]["core"]["result"]
    result.update(
        operation="max-flow-min-cut",
        result={
            "flows": [
                {"edge": 0, "source": 2, "target": 1, "flow": 3, "capacity": 4},
                {"edge": 0, "source": 1, "target": 2, "flow": 0, "capacity": 4},
            ]
        },
    )
    result["ports"] = {"value": {"type": "scalar", "value": 3, "complete": True}}
    open_saved(browser, server, "results/saved-analysis")
    wait_for(browser, "GraphMineWorkspace.state.cy?.edges().length === 1")
    assert browser.execute_script("""
        const edge = GraphMineWorkspace.state.cy.edges()[0];
        return [edge.source().data('entity'), edge.target().data('entity'), edge.style('target-arrow-shape')];
    """) == [2, 1, "triangle"]
    assert "positive computed flow" in browser.find_element(By.ID, "preview-scope").text
    browser.find_element(By.ID, "flow-direction").click()
    assert (
        browser.execute_script("return GraphMineWorkspace.state.cy.edges().length") == 7
    )
    assert (
        browser.execute_script(
            "return GraphMineWorkspace.state.cy.edges()[0].style('target-arrow-shape')"
        )
        == "none"
    )
