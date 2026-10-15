"""Browser coverage for navigation, accessible drawers, and the chat composer."""

import pytest
import test_workspace_loading as fixtures
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from test_workspace_loading import wait_for

loading_browser = fixtures.loading_browser
loading_server = fixtures.loading_server


def open_chat(browser, server):
    server.responses[0].release.set()
    browser.get(server.url + "/#workspace/saved-session/chat")
    wait_for(browser, "GraphMineWorkspace.state.session && GraphMineWorkspace.state.caps && !GraphMineWorkspace.state.busy")


@pytest.mark.parametrize("width,height", [(320, 640), (390, 844), (820, 1180), (1440, 1000)])
def test_conversation_and_composer_fit_the_viewport(loading_browser, loading_server, width, height):
    browser, server = loading_browser, loading_server
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": height})
    open_chat(browser, server)
    assert browser.execute_script("return innerWidth") == width
    assert browser.find_element(By.ID, "chat-welcome").is_displayed()
    assert not browser.find_element(By.ID, "data-sidebar").is_displayed()
    assert not browser.find_element(By.ID, "activity-sidebar").is_displayed()
    assert browser.execute_script("""
        const composer = document.getElementById('question-form').getBoundingClientRect();
        return document.documentElement.scrollWidth <= innerWidth
          && document.documentElement.scrollHeight <= innerHeight + 1
          && composer.top >= 0 && composer.bottom <= innerHeight
          && composer.left >= 0 && composer.right <= innerWidth;
    """)
    browser.find_element(By.ID, "toggle-data").click()
    assert browser.find_element(By.CSS_SELECTOR, ".upload-zone").is_displayed()
    assert browser.find_element(By.ID, "data-sidebar").get_attribute("aria-modal") == "true"
    browser.switch_to.active_element.send_keys(Keys.ESCAPE)
    assert browser.switch_to.active_element.get_attribute("id") == "toggle-data"
    assert not browser.find_element(By.ID, "data-sidebar").is_displayed()


def test_drawers_trap_focus_and_restore_the_trigger(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    open_chat(browser, server)
    browser.find_element(By.ID, "composer-data").click()
    close = browser.find_element(By.CSS_SELECTOR, "#data-sidebar [data-close-panel]")
    assert browser.switch_to.active_element == close
    close.send_keys(Keys.SHIFT, Keys.TAB)
    assert browser.execute_script("return document.getElementById('data-sidebar').contains(document.activeElement)")
    browser.switch_to.active_element.send_keys(Keys.TAB)
    assert browser.switch_to.active_element == close
    close.click()
    assert browser.switch_to.active_element.get_attribute("id") == "composer-data"
    browser.find_element(By.ID, "toggle-activity").click()
    assert browser.find_element(By.ID, "activity-status").is_displayed()
    browser.switch_to.active_element.send_keys(Keys.ESCAPE)
    assert browser.switch_to.active_element.get_attribute("id") == "toggle-activity"
    assert not browser.find_element(By.ID, "panel-backdrop").is_displayed()


def test_mobile_history_search_and_navigation(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    browser.set_window_size(390, 844)
    server.responses[0].release.set()
    browser.get(server.url)
    wait_for(browser, "GraphMineWorkspace.state.caps && !GraphMineWorkspace.state.busy")
    assert not browser.find_element(By.ID, "app-sidebar").is_displayed()
    browser.find_element(By.ID, "toggle-sidebar").click()
    search = browser.find_element(By.ID, "session-search")
    search.send_keys("does not exist")
    assert "No conversations match" in browser.find_element(By.ID, "recent-sessions").text
    search.clear()
    search.send_keys("Saved")
    browser.find_element(By.CSS_SELECTOR, ".recent-session").click()
    wait_for(browser, "GraphMineWorkspace.state.session && !GraphMineWorkspace.state.busy")
    assert not browser.find_element(By.ID, "app-sidebar").is_displayed()
    assert not browser.find_element(By.ID, "panel-backdrop").is_displayed()
    assert browser.find_element(By.ID, "chat-content").is_displayed()
    browser.find_element(By.ID, "toggle-sidebar").click()
    browser.find_element(By.ID, "nav-new-chat").click()
    wait_for(browser, "GraphMineWorkspace.state.view === 'domains'")
    assert browser.find_element(By.ID, "domain-grid").is_displayed()
    assert not browser.find_element(By.ID, "app-sidebar").is_displayed()


def test_sidebar_preference_persists_and_prompt_is_editable(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    open_chat(browser, server)
    browser.find_element(By.ID, "collapse-sidebar").click()
    browser.refresh()
    wait_for(browser, "GraphMineWorkspace.state.session && !GraphMineWorkspace.state.busy")
    assert not browser.find_element(By.ID, "app-sidebar").is_displayed()
    browser.find_element(By.ID, "toggle-sidebar").click()
    assert browser.find_element(By.ID, "app-sidebar").is_displayed()
    assert browser.find_element(By.CSS_SELECTOR, '.recent-session[aria-current="page"]').is_displayed()
    suggestion = browser.find_element(By.CSS_SELECTOR, "[data-prompt]")
    text = suggestion.get_attribute("data-prompt")
    suggestion.click()
    question = browser.find_element(By.ID, "question")
    assert question.get_attribute("value") == text
    assert browser.switch_to.active_element == question
    question.send_keys(Keys.SHIFT, Keys.ENTER)
    question.send_keys("Focus on my team.")
    assert "\nFocus on my team." in question.get_attribute("value")
    assert not server.requests
    browser.find_element(By.CSS_SELECTOR, '[data-mode="interactive"]').click()
    assert "approve" in browser.find_element(By.ID, "mode-description").text
    browser.execute_script("document.querySelector('.skip-link').focus()")
    browser.find_element(By.CSS_SELECTOR, ".skip-link").click()
    assert browser.switch_to.active_element.get_attribute("id") == "chat-content"
    assert "saved-session/chat" in browser.current_url
