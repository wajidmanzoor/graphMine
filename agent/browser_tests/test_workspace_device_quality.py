"""Device and quality presentation with controlled capability/plan fixtures."""

from copy import deepcopy

import test_workspace_loading as workspace
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from test_workspace_loading import wait_for

loading_browser = workspace.loading_browser
loading_server = workspace.loading_server


def test_gpu_first_picker_and_quality_are_independent(
    loading_browser, loading_server, monkeypatch
):
    browser, server = loading_browser, loading_server
    caps = deepcopy(workspace.CAPABILITIES)
    caps["device_configuration"] = {"gpu_available": True, "gpu_configured": False}
    caps["operations"] = [
        {
            "id": "gpu-count",
            "title": "Count on GPU",
            "input_kind": "graph",
            "quality": "exact",
            "parameters": {},
            "execution": {"cpu": False, "gpu": True},
        },
        {
            "id": "community",
            "title": "Find communities",
            "input_kind": "graph",
            "quality": "parameter_dependent",
            "execution": {"cpu": True, "gpu": False},
            "parameters": {
                "solution_quality": {
                    "kind": "string",
                    "default": "heuristic",
                    "choices": ["exact", "heuristic"],
                }
            },
        },
        {
            "id": "numerical",
            "title": "Numerical similarity",
            "input_kind": "graph",
            "quality": "numerical",
            "execution": {"cpu": True, "gpu": False},
            "parameters": {
                "solution_quality": {
                    "kind": "string",
                    "default": "exact",
                    "choices": ["exact", "approximate"],
                }
            },
        },
    ]
    monkeypatch.setattr(workspace, "CAPABILITIES", caps)
    server.responses[0].release.set()
    browser.get(server.url + "/#workspace/saved-session/chat")
    wait_for(browser, "GraphMineWorkspace.state.caps && !GraphMineWorkspace.state.busy")
    browser.find_element(By.CSS_SELECTOR, '[data-mode="expert"]').click()
    browser.execute_script(
        "document.getElementById('operation-form').closest('details').open = true"
    )
    operation = Select(browser.find_element(By.ID, "operation-select"))
    assert "gpu-count" in [
        option.get_attribute("value") for option in operation.options
    ]
    operation.select_by_value("community")
    quality = Select(
        browser.find_element(By.CSS_SELECTOR, '[data-parameter="solution_quality"]')
    )
    assert (
        quality._el.is_displayed()
    )  # A material choice is visible without expanding optional settings.
    assert "Heuristic" in browser.find_element(By.ID, "operation-quality").text
    quality.select_by_value('"exact"')
    assert (
        "Exact — establishes" in browser.find_element(By.ID, "operation-quality").text
    )
    operation.select_by_value("numerical")
    assert "Numerical —" in browser.find_element(By.ID, "operation-quality").text
    assert (
        "Exact — establishes"
        not in browser.find_element(By.ID, "operation-quality").text
    )
    browser.execute_script("document.querySelector('.advanced-data').open = true")
    device = Select(browser.find_element(By.ID, "device"))
    assert device.first_selected_option.text == "Automatic (GPU first)"
    assert "prefers a verified GPU" in browser.find_element(By.ID, "device-note").text
    device.select_by_value("cpu")
    assert "gpu-count" not in [
        option.get_attribute("value") for option in operation.options
    ]
    device.select_by_value("gpu")
    assert [option.get_attribute("value") for option in operation.options] == [
        "",
        "gpu-count",
    ]


def test_review_and_chat_label_default_heuristic_and_explicit_exact(
    loading_browser, loading_server, monkeypatch
):
    browser, server = loading_browser, loading_server
    caps = deepcopy(workspace.CAPABILITIES)
    caps["operations"][0].update(
        quality="parameter_dependent",
        parameters={
            "solution_quality": {
                "kind": "string",
                "default": "heuristic",
                "choices": ["exact", "heuristic"],
            }
        },
    )
    record = deepcopy(workspace.WORKFLOW)
    record["validation"]["plan"]["device"] = "auto"
    step = record["validation"]["plan"]["steps"][0]
    step["parameters"] = {}
    exact = deepcopy(step)
    exact.update(id="exact", parameters={"solution_quality": "exact"})
    record["validation"]["plan"]["steps"].append(exact)
    record["validation"]["order"].append("exact")
    monkeypatch.setattr(workspace, "CAPABILITIES", caps)
    monkeypatch.setattr(workspace, "WORKFLOW", record)
    server.saved_analysis = True
    server.responses[0].release.set()
    browser.get(server.url + "/#workspace/saved-session/chat")
    wait_for(
        browser,
        "GraphMineWorkspace.state.caps && GraphMineWorkspace.state.record && !GraphMineWorkspace.state.busy",
    )
    assert (
        "GPU preferred, CPU fallback"
        in browser.find_element(By.ID, "workflow-summary").text
    )
    assert (
        "Heuristic — no guarantee"
        in browser.find_element(
            By.CSS_SELECTOR, '[data-step="core"] .step-quality'
        ).text
    )
    assert (
        "Exact — establishes"
        in browser.find_element(
            By.CSS_SELECTOR, '[data-step="exact"] .step-quality'
        ).text
    )
    summaries = browser.find_elements(By.CSS_SELECTOR, "#messages .step-quality")
    assert any("Heuristic — no guarantee" in row.text for row in summaries)
    assert any("Exact — establishes" in row.text for row in summaries)
