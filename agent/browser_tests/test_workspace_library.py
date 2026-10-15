"""Save and reuse datasets through the visible workspace controls."""

import pytest
import test_workspace_loading as loading_fixtures
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from test_workspace_conversation_graph import open_saved, saved_cliques, saved_network
from test_workspace_loading import wait_for

loading_browser = loading_fixtures.loading_browser
loading_server = loading_fixtures.loading_server


@pytest.mark.parametrize("result", [False, True])
def test_dataset_snapshot_and_import(loading_browser, loading_server, result):
    browser, server = loading_browser, loading_server
    (saved_cliques if result else saved_network)(server)

    def post(path, body):
        if path == "/api/datasets":
            if result:
                assert body["workflow_id"] == "saved-analysis"
                assert body["group_index"] == 1
                assert body["expected_revision"] == 1
            else:
                assert body["file_id"] == "network" and body["kind"] == "graph"
            server.datasets.append(
                {
                    "id": "version-1",
                    "dataset_id": "dataset-1",
                    "version": 1,
                    "name": body["name"],
                    "kind": "graph",
                    "size_bytes": 200,
                    "source_complete": not result,
                    "sha256": "abc",
                    "source": body,
                }
            )
            return server.datasets[-1]
        assert path == "/api/sessions/saved-session/datasets/version-1/import"
        return {
            "file": {
                "id": "imported",
                "original_name": "Reusable network-v1.json",
                "role": "graph",
                "metadata": {"vertex_count": 3, "edge_count": 2},
                "provenance": {"version_id": "version-1", "kind": "graph"},
            },
            "kind": "graph",
        }

    server.post_handler = post
    open_saved(browser, server, "results/saved-analysis" if result else "chat")
    if result:
        browser.find_element(By.CSS_SELECTOR, "#result-actions-panel summary").click()
        Select(browser.find_element(By.ID, "graph-group")).select_by_index(2)
        browser.find_element(By.ID, "save-dataset-result").click()
    else:
        browser.find_element(By.ID, "toggle-data").click()
        browser.find_element(By.ID, "save-dataset-input").click()
    wait_for(browser, "document.querySelector('#dataset-dialog').open")
    name = browser.find_element(By.ID, "dataset-name")
    name.clear()
    name.send_keys("Reusable network")
    browser.find_element(By.CSS_SELECTOR, "#dataset-form button[type=submit]").click()
    wait_for(browser, "document.querySelector('[data-import-dataset]') !== null")
    assert (
        "Source result is incomplete" if result else "Complete source"
    ) in browser.find_element(By.ID, "dataset-list").text
    browser.find_element(By.CSS_SELECTOR, "[data-import-dataset]").click()
    wait_for(
        browser,
        "GraphMineWorkspace.state.active === 'imported' && !GraphMineWorkspace.state.busy",
    )
    assert not browser.find_element(By.ID, "dataset-dialog").is_displayed()
    assert (
        browser.execute_script("return GraphMineWorkspace.state.kinds.imported")
        == "graph"
    )
    assert not any(
        path.endswith(("/run", "/analytics/plan")) for _, path, _ in server.requests
    )
