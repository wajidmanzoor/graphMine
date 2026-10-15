import test_workspace_loading as loading_fixtures
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from test_workspace_conversation_graph import open_saved, saved_network
from test_workspace_loading import wait_for
from test_workspace_recovery_views import failed_analysis

loading_browser = loading_fixtures.loading_browser
loading_server = loading_fixtures.loading_server


def test_visual_editor_revalidates_and_requires_review(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    failed_analysis(server)
    open_saved(browser, server)
    browser.find_element(By.CSS_SELECTOR, '[data-mode="expert"]').click()
    browser.find_element(By.ID, "open-visual-editor").click()
    wait_for(browser, "document.querySelector('#visual-editor')?.open")
    field = browser.find_element(By.ID, "visual-core-requested_k")
    field.clear()
    field.send_keys("3")
    browser.find_element(By.ID, "visual-save").click()
    wait_for(
        browser,
        "GraphMineWorkspace.state.record?.revision === 2 && !GraphMineWorkspace.state.busy",
    )
    body = server.requests[-1][2]
    assert body["plan"]["steps"][0]["parameters"]["requested_k"] == 3
    assert body["mode"] == "interactive"
    assert browser.find_element(By.ID, "approve-plan").is_displayed()
    assert not any(path.endswith("/run") for _, path, _ in server.requests)


def test_time_sliders_filter_only_the_visible_graph(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    for index, edge in enumerate(server.graph["edges"][:-1]):
        edge["timestamp"] = 9007199254740993 + index
    open_saved(browser, server, "results/saved-analysis")
    browser.find_element(By.CSS_SELECTOR, "#time-controls summary").click()
    browser.execute_script(
        "const s=document.querySelector('#time-end'); s.value='0'; s.dispatchEvent(new Event('input'))"
    )
    assert (
        browser.execute_script(
            "return GraphMineWorkspace.state.cy.edges().filter(e => e.style('display') !== 'none').length"
        )
        == 2
    )
    browser.find_element(By.ID, "include-untimed").click()
    assert (
        browser.execute_script(
            "return GraphMineWorkspace.state.cy.edges().filter(e => e.style('display') !== 'none').length"
        )
        == 1
    )
    assert "9007199254740993" in browser.find_element(By.ID, "time-scope").text
    assert not server.requests


def test_embedding_dimensions_preserve_identity_and_png_export(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    saved_network(server)
    result = server.results["saved-analysis"]["steps"]["core"]["result"]
    result["ports"] = {
        "embeddings": {
            "type": "vertex_embeddings",
            "complete": True,
            "value": [
                {"vertex": "1", "values": [1, 2, 3]},
                {"vertex": 1, "values": [-1, 0, 4]},
            ],
        }
    }
    open_saved(browser, server, "results/saved-analysis")
    wait_for(
        browser, "document.querySelectorAll('#embedding-plot circle').length === 2"
    )
    Select(browser.find_element(By.ID, "embedding-x")).select_by_value("2")
    browser.find_element(By.CSS_SELECTOR, "#embedding-plot circle").click()
    assert browser.execute_script("return [...GraphMineWorkspace.state.selected]") == [
        "s:1"
    ]
    browser.execute_script(
        "const original=URL.createObjectURL; URL.createObjectURL=blob=>{window.exportedBlob=blob; return original(blob)}; HTMLAnchorElement.prototype.click=function(){window.exportedName=this.download}"
    )
    browser.find_element(By.CSS_SELECTOR, "#result-actions-panel summary").click()
    browser.find_element(By.ID, "export-image").click()
    wait_for(browser, "window.exportedBlob?.type === 'image/png'")
    assert browser.execute_script("return window.exportedBlob.size") > 1000
    assert browser.execute_script("return window.exportedName").endswith(
        "visible-graph.png"
    )
