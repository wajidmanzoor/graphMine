"""Delayed workspace reads must never overwrite newer navigation."""

from copy import deepcopy

import pytest
from selenium.webdriver.common.by import By
from test_workspace_loading import (
    WORKFLOW,
    loading_browser,
    loading_server,
    wait_for,
)


def workspace(identifier):
    return {
        "session": {"id": identifier, "title": identifier, "domain_id": "general"},
        "files": [],
        "messages": [],
        "events": [],
        "feedback_count": 0,
    }


def workflow(identifier, *, completed=False):
    record = deepcopy(WORKFLOW)
    record.update(id=identifier, session_id="review-b")
    if completed:
        record.update(status="completed", complete=True)
        record["steps"] = {"core": {"status": "completed"}}
    return record


def result(value):
    return {
        "complete": True,
        "steps": {
            "core": {
                "result": {
                    "problem": "k-core",
                    "complete": True,
                    "quality": "exact",
                    "backend": {"device": "cpu"},
                    "ports": {
                        "count": {"type": "scalar", "complete": True, "value": value}
                    },
                }
            }
        },
    }


def open_fixture(browser, server, responses=None, held=()):
    server.responses[0].release.set()
    browser.get(server.url)
    wait_for(browser, "window.GraphMineWorkspace?.state.caps && !GraphMineWorkspace.state.busy")
    values = {
        "/api/sessions/review-a/workspace": workspace("review-a"),
        "/api/sessions/review-b/workspace": workspace("review-b"),
        "/api/sessions/review-a/workflows": [],
        "/api/sessions/review-b/workflows": [],
        **(responses or {}),
    }
    browser.execute_script(
        """
        const original = window.fetch, values = arguments[0], held = new Set(arguments[1]);
        window.navigationReads = {};
        window.releaseNavigation = (path, status = 200) => {
          const read = navigationReads[path];
          read.release(new Response(JSON.stringify(status === 200 ? values[path] : {
            error: {message: 'An obsolete workspace failed to load'}
          }), {status, headers: {'Content-Type': 'application/json'}}));
        };
        window.fetch = (input, options = {}) => {
          const path = String(input).replace(/[?]history_limit=[0-9]+$/, '').replace('/workflows?summary=true', '/workflows');
          if (!(path in values)) return original(input, options);
          const read = {aborted: options.signal?.aborted || false};
          options.signal?.addEventListener('abort', () => { read.aborted = true; });
          navigationReads[path] = read;
          // Deliberately finish aborted requests too: both cancellation and the
          // application's stale-response guards must work independently.
          if (held.has(path)) return new Promise(resolve => { read.release = resolve; });
          return Promise.resolve(new Response(JSON.stringify(values[path]), {
            headers: {'Content-Type': 'application/json'}
          }));
        };
        """,
        values,
        list(held),
    )


def navigate(browser, identifier, page="chat", analysis=""):
    browser.execute_script(
        "location.hash = arguments[0]",
        f"#workspace/{identifier}/{page}" + (f"/{analysis}" if analysis else ""),
    )


def finish_obsolete_read(browser, path, status=200):
    browser.execute_script("releaseNavigation(arguments[0], arguments[1])", path, status)
    # Drain fetch/body/render continuations without depending on network timing.
    browser.execute_async_script(
        "const done=arguments[arguments.length-1]; setTimeout(done, 100);"
    )
    assert browser.execute_script("return navigationReads[arguments[0]].aborted", path)
    assert "obsolete workspace" not in browser.find_element(By.ID, "notice").text


@pytest.mark.parametrize("status", [200, 503])
def test_newer_conversation_wins_over_delayed_workspace(
    loading_browser, loading_server, status
):
    browser = loading_browser
    path = "/api/sessions/review-a/workspace"
    open_fixture(browser, loading_server, held=[path])
    navigate(browser, "review-a")
    wait_for(browser, f"Boolean(navigationReads['{path}']?.release)")
    navigate(browser, "review-b")
    wait_for(browser, "GraphMineWorkspace.state.session?.id === 'review-b'")
    finish_obsolete_read(browser, path, status)
    assert browser.execute_script("return GraphMineWorkspace.state.session.id") == "review-b"
    assert browser.find_element(By.ID, "workspace-title").text == "review-b"
    assert browser.execute_script("return location.hash") == "#workspace/review-b/chat"


def test_home_cancels_a_conversation_that_has_not_loaded(
    loading_browser, loading_server
):
    browser = loading_browser
    path = "/api/sessions/review-a/workspace"
    open_fixture(browser, loading_server, held=[path])
    navigate(browser, "review-a")
    wait_for(browser, f"Boolean(navigationReads['{path}']?.release)")
    browser.execute_script("location.hash = ''")
    wait_for(browser, "document.getElementById('domain-view').hidden === false")
    finish_obsolete_read(browser, path)
    assert browser.execute_script("return GraphMineWorkspace.state.session") is None
    assert browser.find_element(By.ID, "domain-view").is_displayed()
    assert not browser.find_element(By.ID, "workspace-view").is_displayed()


def test_delayed_analysis_list_stays_with_its_conversation(
    loading_browser, loading_server
):
    browser = loading_browser
    path = "/api/sessions/review-a/workflows"
    open_fixture(browser, loading_server, {path: [workflow("obsolete")]}, [path])
    navigate(browser, "review-a")
    wait_for(browser, f"Boolean(navigationReads['{path}']?.release)")
    navigate(browser, "review-b")
    wait_for(browser, "GraphMineWorkspace.state.session?.id === 'review-b'")
    finish_obsolete_read(browser, path)
    assert browser.execute_script("return GraphMineWorkspace.state.workflows") == []
    assert browser.execute_script("return GraphMineWorkspace.state.record") is None
    assert not browser.find_elements(By.CSS_SELECTOR, '[data-workflow="obsolete"]')


@pytest.mark.parametrize("held_stage", ["workflow", "result"])
def test_newer_analysis_wins_over_delayed_analysis_reads(
    loading_browser, loading_server, held_stage
):
    browser = loading_browser
    records = [workflow("old-analysis", completed=True), workflow("new-analysis", completed=True)]
    query = f"summary=true&expected_revision={records[0]['revision']}"
    path = "/api/workflows/old-analysis" + (f"/result?{query}" if held_stage == "result" else "")
    responses = {
        "/api/sessions/review-b/workflows": records,
        **{f"/api/workflows/{record['id']}": record for record in records},
        f"/api/workflows/old-analysis/result?{query}": result(11),
        f"/api/workflows/new-analysis/result?{query}": result(22),
    }
    open_fixture(browser, loading_server, responses, [path])
    navigate(browser, "review-b", "results", "old-analysis")
    wait_for(browser, f"Boolean(navigationReads['{path}']?.release)")
    navigate(browser, "review-b", "results", "new-analysis")
    wait_for(browser, "GraphMineWorkspace.state.record?.id === 'new-analysis' && GraphMineWorkspace.state.result?.steps.core.result.ports.count.value === 22")
    finish_obsolete_read(browser, path)
    assert browser.execute_script("return GraphMineWorkspace.state.record.id") == "new-analysis"
    assert browser.execute_script("return GraphMineWorkspace.state.result.steps.core.result.ports.count.value") == 22
    assert browser.execute_script("return location.hash") == "#workspace/review-b/results/new-analysis"
