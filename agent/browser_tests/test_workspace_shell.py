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
    assert browser.find_element(By.ID, "data-sidebar").get_attribute("aria-modal") == ("true" if width <= 900 else None)
    assert browser.find_element(By.ID, "panel-backdrop").is_displayed() == (width <= 900)
    browser.switch_to.active_element.send_keys(Keys.ESCAPE)
    assert browser.switch_to.active_element.get_attribute("id") == "toggle-data"
    assert not browser.find_element(By.ID, "data-sidebar").is_displayed()


def test_drawers_trap_focus_and_restore_the_trigger(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": 390, "height": 844})
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


@pytest.mark.parametrize("width", [901, 1024, 1440, 1920])
def test_desktop_panels_leave_messages_and_composer_visible(loading_browser, loading_server, width):
    browser, server = loading_browser, loading_server
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 900})
    for role, message in [("user", "Show the connections between the busiest nodes in my network."), ("assistant", "Add your graph to explore its connections.")]:
        row = {"kind": "workflow.chat", "role": role, "turn_id": "panel-preview", "created_at": "2026-10-19T13:00:00+00:00", "message": message}
        server.messages.append(row)
        server.events.append({"sequence": len(server.events) + 1, "type": "workflow.chat", "created_at": row["created_at"], "payload": row})
    open_chat(browser, server)
    original_edge = browser.execute_script("return document.querySelector('.chat-message.user .chat-bubble').getBoundingClientRect().right")
    for name in ("data", "activity"):
        browser.find_element(By.ID, f"toggle-{name}").click()
        panel = browser.find_element(By.ID, f"{name}-sidebar")
        assert panel.is_displayed()
        assert panel.get_attribute("aria-modal") is None
        assert not browser.find_element(By.ID, "panel-backdrop").is_displayed()
        assert browser.execute_script("""
            const panel = arguments[0].getBoundingClientRect();
            const chat = document.getElementById('chat-content').getBoundingClientRect();
            const composer = document.getElementById('question-form').getBoundingClientRect();
            const bubble = document.querySelector('.chat-message.user .chat-bubble').getBoundingClientRect();
            const scroll = document.querySelector('.conversation-scroll');
            return Math.abs(arguments[1] - bubble.right - panel.width) < 1
              && chat.right <= panel.left + 1 && bubble.left >= chat.left
              && composer.right <= panel.left && composer.left >= chat.left
              && composer.top >= 0 && composer.bottom <= innerHeight
              && scroll.scrollWidth <= scroll.clientWidth
              && document.documentElement.scrollWidth <= innerWidth
              && document.documentElement.scrollHeight <= innerHeight + 1
              && [...document.querySelectorAll('.chat-heading button, .composer-actions button')].every(button => {
                  const box = button.getBoundingClientRect();
                  return box.left >= chat.left && box.right <= panel.left;
              });
        """, panel, original_edge)
        question = browser.find_element(By.ID, "question")
        question.click()
        question.send_keys("Keep this draft visible. ")
        question.send_keys(Keys.TAB)
        assert browser.switch_to.active_element.get_attribute("id") == "composer-data"
        assert panel.is_displayed()
    assert not browser.find_element(By.ID, "data-sidebar").is_displayed()
    browser.find_element(By.ID, "toggle-activity").click()
    assert not browser.find_element(By.ID, "activity-sidebar").is_displayed()
    assert browser.execute_script("return document.querySelector('.chat-message.user .chat-bubble').getBoundingClientRect().right") == original_edge
    assert question.get_attribute("value") == "Keep this draft visible. " * 2


def test_open_panel_adapts_when_resizing_between_desktop_and_mobile(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    open_chat(browser, server)
    browser.find_element(By.ID, "toggle-data").click()
    question = browser.find_element(By.ID, "question")
    question.send_keys("Keep my draft when resizing.")
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": 900, "height": 900})
    wait_for(browser, "document.getElementById('data-sidebar').getAttribute('aria-modal') === 'true'")
    assert browser.find_element(By.ID, "panel-backdrop").is_displayed()
    assert browser.execute_script("return document.getElementById('data-sidebar').contains(document.activeElement)")
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": 901, "height": 900})
    wait_for(browser, "!document.getElementById('data-sidebar').hasAttribute('aria-modal')")
    assert not browser.find_element(By.ID, "panel-backdrop").is_displayed()
    assert browser.execute_script("return document.getElementById('question-form').getBoundingClientRect().right <= document.getElementById('data-sidebar').getBoundingClientRect().left")
    question.click()
    assert question.get_attribute("value") == "Keep my draft when resizing."
    question.send_keys(Keys.ESCAPE)
    assert not browser.find_element(By.ID, "data-sidebar").is_displayed()
    assert browser.switch_to.active_element.get_attribute("id") == "toggle-data"


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
