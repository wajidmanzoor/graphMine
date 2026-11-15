"""History paging and search operate across conversations absent from the page."""

from selenium.webdriver.common.by import By
from test_workspace_loading import loading_browser, loading_server, wait_for


def open_history(browser, server):
    server.sessions = [{"id": f"conversation-{index}", "title": f"Conversation {index}", "domain_id": "general"} for index in range(120)]
    server.sessions.append({"id": "archived-old", "title": "Archived discovery", "domain_id": "general", "archived": True})
    server.responses[0].release.set()
    browser.get(server.url)
    wait_for(browser, "window.GraphMineWorkspace?.state.caps && !GraphMineWorkspace.state.busy")


def test_history_loads_more_and_searches_beyond_first_hundred(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    open_history(browser, server)
    assert len(browser.find_elements(By.CSS_SELECTOR, ".recent-session")) == 50
    browser.find_element(By.ID, "load-more-sessions").click()
    wait_for(browser, "document.querySelectorAll('.recent-session').length === 100")
    browser.find_element(By.ID, "load-more-sessions").click()
    wait_for(browser, "document.querySelectorAll('.recent-session').length === 120")
    assert not browser.find_element(By.ID, "load-more-sessions").is_displayed()
    search = browser.find_element(By.ID, "session-search")
    search.send_keys("Conversation 119")
    wait_for(browser, "document.querySelectorAll('.recent-session').length === 1")
    assert browser.find_element(By.CSS_SELECTOR, ".recent-session").get_attribute("href").endswith("#workspace/conversation-119/chat")
    assert server.session_requests[-1]["q"] == ["Conversation 119"]
    assert server.session_requests[-1]["offset"] == ["0"]


def test_archived_history_and_empty_search_keep_filters_usable(loading_browser, loading_server):
    browser = loading_browser
    open_history(browser, loading_server)
    search = browser.find_element(By.ID, "session-search")
    search.send_keys("Archived discovery")
    wait_for(browser, "document.getElementById('recent-sessions').textContent.includes('No conversations match')")
    assert search.is_displayed()
    browser.find_element(By.CSS_SELECTOR, ".history-options > summary").click()
    browser.find_element(By.ID, "show-archived").click()
    wait_for(browser, "document.querySelectorAll('.recent-session').length === 1")
    assert "Archived discovery (archived)" in browser.find_element(By.CSS_SELECTOR, ".recent-session").text


def test_obsolete_search_cannot_replace_newer_results(loading_browser, loading_server):
    browser = loading_browser
    open_history(browser, loading_server)
    browser.execute_script("""
        const original = window.fetch;
        window.fetch = (path, options) => String(path).includes('q=slow') ? new Promise(resolve => {
          window.releaseSearch = () => resolve(new Response(JSON.stringify([{id:'obsolete', title:'Obsolete', domain_id:'general'}]), {headers:{'Content-Type':'application/json'}}));
        }) : original(path, options);
    """)
    search = browser.find_element(By.ID, "session-search")
    search.send_keys("slow")
    wait_for(browser, "typeof window.releaseSearch === 'function'")
    search.clear()
    search.send_keys("Conversation 119")
    wait_for(browser, "document.querySelectorAll('.recent-session').length === 1")
    browser.execute_script("window.releaseSearch()")
    browser.execute_async_script("const done=arguments[arguments.length-1]; setTimeout(done, 100)")
    assert "Conversation 119" in browser.find_element(By.CSS_SELECTOR, ".recent-session").text
