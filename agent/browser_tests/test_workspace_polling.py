"""A disconnect must not strand a running analysis or revive an old workspace."""

import pytest
from selenium.webdriver.common.by import By
from test_workspace_loading import loading_browser, loading_server, wait_for
from test_workspace_navigation import navigate, open_fixture, result, workflow


def open_running(browser, server, failures=()):
    record = workflow("running-analysis")
    record.update(status="running", started_at="2026-10-21T00:00:00Z")
    completed = workflow("running-analysis", completed=True)
    responses = {
        "/api/sessions/review-b/workflows": [record],
        "/api/workflows/running-analysis": record,
        "/api/workflows/running-analysis/result?summary=true&expected_revision=1": result(42),
    }
    open_fixture(browser, server, responses)
    browser.execute_script(
        """
        const original = window.fetch, completed = arguments[0];
        window.pollFailures = arguments[1]; window.pollAttempts = [];
        window.finishAnalysis = false;
        window.fetch = (path, options = {}) => {
          if (path !== '/api/workflows/running-analysis') return original(path, options);
          pollAttempts.push(performance.now());
          if (pollAttempts.length > 1 && pollFailures.length) {
            const status = pollFailures.shift();
            if (status === 'network') return Promise.reject(new TypeError('Network connection lost'));
            return Promise.resolve(new Response(JSON.stringify({error: {message: 'Unavailable'}}), {
              status, headers: {'Content-Type': 'application/json', ...(status === 429 ? {'Retry-After': '2'} : {})}
            }));
          }
          return window.finishAnalysis ? Promise.resolve(new Response(JSON.stringify(completed), {
            headers: {'Content-Type': 'application/json'}
          })) : original(path, options);
        };
        """,
        completed,
        list(failures),
    )
    navigate(browser, "review-b")
    wait_for(browser, "GraphMineWorkspace.state.record?.status === 'running'")


@pytest.mark.parametrize("failure", ["network", 503, 429])
def test_polling_recovers_and_loads_completed_results(loading_browser, loading_server, failure):
    browser = loading_browser
    open_running(browser, loading_server, [failure])
    wait_for(browser, "!document.getElementById('workflow-sync').hidden")
    assert "Retrying" in browser.find_element(By.ID, "workflow-sync-message").text
    browser.execute_script("window.finishAnalysis = true")
    wait_for(browser, "GraphMineWorkspace.state.result?.steps.core.result.ports.count.value === 42")
    assert not browser.find_element(By.ID, "workflow-sync").is_displayed()
    attempts = browser.execute_script("return pollAttempts")
    assert len(attempts) == 3
    assert attempts[2] - attempts[1] >= (1900 if failure == 429 else 900)


def test_polling_backs_off_and_manual_retry_reconciles(loading_browser, loading_server):
    browser = loading_browser
    open_running(browser, loading_server, [503, 503])
    wait_for(browser, "pollAttempts.length === 3")
    wait_for(browser, "document.getElementById('workflow-sync-message').textContent.includes('2 seconds')")
    browser.execute_script("window.finishAnalysis = true")
    browser.find_element(By.ID, "workflow-sync-retry").click()
    wait_for(browser, "GraphMineWorkspace.state.result?.steps.core.result.ports.count.value === 42")
    attempts = browser.execute_script("return pollAttempts")
    assert attempts[2] - attempts[1] >= 900
    assert attempts[3] - attempts[2] < 1900


@pytest.mark.parametrize("signal", ["visibilitychange", "online"])
def test_returning_to_tab_or_network_reconciles_immediately(loading_browser, loading_server, signal):
    browser = loading_browser
    open_running(browser, loading_server, [503])
    wait_for(browser, "!document.getElementById('workflow-sync').hidden")
    browser.execute_script(
        "window.finishAnalysis = true; (arguments[0] === 'online' ? window : document).dispatchEvent(new Event(arguments[0]))",
        signal,
    )
    wait_for(browser, "GraphMineWorkspace.state.result?.steps.core.result.ports.count.value === 42")
    assert not browser.find_element(By.ID, "workflow-sync").is_displayed()


@pytest.mark.parametrize("status", [401, 403, 404])
def test_polling_stops_when_access_is_lost(loading_browser, loading_server, status):
    browser = loading_browser
    open_running(browser, loading_server, [status])
    wait_for(browser, "!document.getElementById('workflow-sync').hidden")
    browser.execute_script("document.dispatchEvent(new Event('visibilitychange'))")
    browser.execute_async_script("const done = arguments[arguments.length - 1]; setTimeout(done, 1100)")
    assert browser.execute_script("return pollAttempts.length") == 2
    assert not browser.find_element(By.ID, "workflow-sync-retry").is_displayed()


def test_navigation_clears_retry_status_and_stops_old_polling(loading_browser, loading_server):
    browser = loading_browser
    open_running(browser, loading_server, [503])
    wait_for(browser, "!document.getElementById('workflow-sync').hidden")
    navigate(browser, "review-a")
    wait_for(browser, "GraphMineWorkspace.state.session?.id === 'review-a'")
    browser.execute_async_script("const done = arguments[arguments.length - 1]; setTimeout(done, 1100)")
    assert browser.execute_script("return pollAttempts.length") == 2
    assert not browser.find_element(By.ID, "workflow-sync").is_displayed()


@pytest.mark.parametrize("width", [1440, 320])
def test_recovery_banner_keeps_composer_and_retry_visible(loading_browser, loading_server, width):
    browser = loading_browser
    browser.set_window_size(width, 640)
    open_running(browser, loading_server, [503] * 5)
    wait_for(browser, "!document.getElementById('workflow-sync').hidden")
    geometry = browser.execute_script("""
      const rect = id => document.getElementById(id).getBoundingClientRect().toJSON();
      return {banner: rect('workflow-sync'), question: rect('question'),
        sidebar: document.querySelector('.app-sidebar').getBoundingClientRect().toJSON(),
        height: innerHeight, width: innerWidth, scrollWidth: document.documentElement.scrollWidth};
    """)
    assert geometry["question"]["bottom"] <= geometry["height"]
    assert geometry["banner"]["bottom"] < geometry["question"]["top"]
    assert geometry["banner"]["right"] <= geometry["width"]
    assert geometry["scrollWidth"] <= geometry["width"]
    if width > 900:
        assert geometry["banner"]["left"] >= geometry["sidebar"]["right"]
    browser.execute_script("window.pollFailures = []; window.finishAnalysis = true")
    browser.find_element(By.ID, "workflow-sync-retry").click()
    wait_for(browser, "GraphMineWorkspace.state.result?.steps.core.result.ports.count.value === 42")
