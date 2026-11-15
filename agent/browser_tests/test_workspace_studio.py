"""Review-and-download keeps revision guards and retries only the failed read."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from selenium.webdriver.common.by import By

from test_workspace_loading import SESSION, loading_browser, loading_server, wait_for  # noqa: F401
from test_workspace_conversation_graph import saved_network


@pytest.mark.parametrize("retry", [False, True])
def test_reviewed_workflow_download_keeps_approval_and_revision(loading_server, loading_browser, retry):
    server, browser = loading_server, loading_browser
    saved_network(server)
    reviewed, downloads = [], []
    def route(handler, method):
        parsed = urlsplit(handler.path)
        if parsed.path.endswith("/example-review"):
            if method == "GET":
                handler.respond({"workflow_id": "saved-analysis", "expected_revision": 1, "workflow_hash": "a" * 64, "result_sha256": "b" * 64})
            else:
                reviewed.append(json.loads(handler.rfile.read(int(handler.headers["Content-Length"]))))
                handler.respond({"id": "reviewed-example"}, 201)
            return True
        if parsed.path.endswith("/studio-export"):
            downloads.append(parse_qs(parsed.query))
            if retry and len(downloads) == 1:
                handler.respond({"error": {"message": "Temporary export failure", "code": "unavailable"}}, 503)
            else:
                handler.respond({"schema_version": "graphmine-analytics-studio-v1"})
            return True
        return False
    server.route_handler = route
    server.responses[0].release.set()
    browser.get(server.url + "/analytics.html#workspace/" + SESSION["id"] + "/chat/saved-analysis")
    # Actions are ignored while the workspace is still loading the analysis.
    wait_for(browser, "!document.getElementById('review-example').hidden && !GraphMineWorkspace.state.busy")
    browser.execute_script("document.getElementById('review-example').click()")
    wait_for(browser, "document.getElementById('example-dialog').open")
    question = browser.find_element(By.ID, "example-question"); question.clear(); question.send_keys("Review this network")
    browser.find_element(By.ID, "example-approved").click()
    browser.find_element(By.ID, "example-studio").click()
    browser.execute_script("window.__studioDownloads=[]; HTMLAnchorElement.prototype.click=function(){window.__studioDownloads.push(this.download)}")
    submit = browser.find_element(By.CSS_SELECTOR, '#example-form button[type="submit"]')
    submit.click()
    if retry:
        wait_for(browser, "document.getElementById('example-feedback').textContent.includes('Example saved. Studio download failed')")
        submit.click()
    wait_for(browser, "!document.getElementById('example-dialog').open")
    assert len(reviewed) == 1 and reviewed[0]["expected_revision"] == 1
    assert downloads == [{"example_id": ["reviewed-example"], "expected_revision": ["1"]}] * (2 if retry else 1)
    assert browser.execute_script("return window.__studioDownloads") == ["graphmine-studio-reviewed-example.json"]
