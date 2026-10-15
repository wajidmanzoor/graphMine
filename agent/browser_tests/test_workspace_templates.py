from copy import deepcopy

import test_workspace_loading as loading_fixtures
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from test_workspace_conversation_graph import open_saved, saved_network
from test_workspace_loading import wait_for

loading_browser = loading_fixtures.loading_browser
loading_server = loading_fixtures.loading_server


def test_template_parameter_edit_and_review(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    plan = deepcopy(server.workflows[0]["validation"]["plan"])
    plan["steps"][0]["operation"] = "k-core"
    plan["steps"][0]["parameters"] = {"requested_k": 2}
    server.templates = [
        {
            "id": "recipe",
            "name": "Reusable core",
            "plan": plan,
            "input_kinds": {"main": "graph"},
        }
    ]

    def post(path, body):
        assert path == "/api/sessions/saved-session/workflow-templates/recipe/use"
        assert body["inputs"] == {"main": {"file_id": "network", "kind": "graph"}}
        assert body["parameters"]["core"]["requested_k"] == 3
        record = deepcopy(server.workflows[0])
        record.update(
            id="from-template",
            status="awaiting_review",
            mode="interactive",
            result=None,
        )
        record["validation"]["plan"] = deepcopy(plan)
        record["validation"]["plan"]["steps"][0]["parameters"]["requested_k"] = 3
        record["steps"] = {}
        server.workflows.append(record)
        return record

    server.post_handler = post
    open_saved(browser, server)
    browser.find_element(By.ID, "open-templates").click()
    wait_for(browser, "document.querySelector('#templates-dialog')?.open")
    Select(browser.find_element(By.ID, "template-choice")).select_by_value("recipe")
    value = browser.find_element(By.ID, "template-core-requested_k")
    value.clear()
    value.send_keys("3")
    browser.find_element(
        By.CSS_SELECTOR, "#use-template-form button[type=submit]"
    ).click()
    wait_for(
        browser,
        "GraphMineWorkspace.state.record?.id === 'from-template' && !GraphMineWorkspace.state.busy",
    )
    assert browser.find_element(By.ID, "approve-plan").is_displayed()
    assert not any(path.endswith("/run") for _, path, _ in server.requests)


def test_csv_preview_requires_explicit_import(
    loading_browser, loading_server, tmp_path
):
    browser, server = loading_browser, loading_server
    saved_network(server)
    path = tmp_path / "network.csv"
    content = "employee,manager\n001,b\n"
    path.write_text(content)

    def post(route, body):
        assert body["file"] == content
        if route.endswith("/preview"):
            return {
                "columns": ["employee", "manager"],
                "sample": [{"employee": "001", "manager": "b"}],
                "row_count": 1,
                "metadata": {"vertex_count": 2, "edge_count": 1},
                "provenance": {"source_column": "employee", "target_column": "manager"},
            }
        assert route.endswith("/files")
        assert (
            body["source_column"] == "employee" and body["target_column"] == "manager"
        )
        return {
            "id": "csv",
            "original_name": "network.csv",
            "role": "graph",
            "metadata": {"vertex_count": 2, "edge_count": 1},
        }

    server.post_handler = post
    open_saved(browser, server)
    browser.find_element(By.ID, "data-upload").send_keys(str(path))
    wait_for(browser, "document.querySelector('#confirm-import')?.disabled === false")
    assert not any(route.endswith("/files") for _, route, _ in server.requests)
    assert "001" in browser.find_element(By.ID, "import-sample").text
    browser.find_element(By.ID, "confirm-import").click()
    wait_for(
        browser,
        "GraphMineWorkspace.state.active === 'csv' && !GraphMineWorkspace.state.busy",
    )
    assert sum(route.endswith("/files") for _, route, _ in server.requests) == 1
