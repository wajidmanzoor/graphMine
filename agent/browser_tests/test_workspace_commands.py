"""Keyboard and touch commands work even when planning and data are unavailable."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import test_workspace_loading as fixtures
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from test_workspace_loading import wait_for
from test_workspace_shell import open_chat

loading_browser = fixtures.loading_browser
loading_server = fixtures.loading_server


@pytest.mark.parametrize("width,height", [(320, 640), (390, 844), (1440, 1000)])
def test_slash_menu_keyboard_filter_and_pointer(
    loading_browser, loading_server, width, height
):
    browser, server = loading_browser, loading_server
    browser.browsing_context.set_viewport(
        context=browser.current_window_handle,
        viewport={"width": width, "height": height},
    )
    open_chat(browser, server)
    question = browser.find_element(By.ID, "question")
    question.send_keys("/")
    assert question.get_attribute("aria-expanded") == "true"
    assert (
        len(browser.find_elements(By.CSS_SELECTOR, "#command-options [role=option]"))
        == 7
    )
    question.send_keys(Keys.ARROW_DOWN, Keys.ENTER)
    assert question.get_attribute("value") == "/feedback "
    assert question.get_attribute("aria-expanded") == "false"
    assert not server.requests
    question.clear()
    question.send_keys("/ra", Keys.TAB)
    assert question.get_attribute("value") == "/rate "
    assert browser.switch_to.active_element == question
    question.clear()
    question.send_keys("/", Keys.ARROW_UP)
    assert question.get_attribute("aria-activedescendant") == "command-option-status"
    question.send_keys(Keys.ESCAPE)
    assert question.get_attribute("value") == "/"
    assert question.get_attribute("aria-expanded") == "false"
    question.clear()
    question.send_keys("\\no")
    browser.find_element(By.ID, "command-option-note").click()
    assert question.get_attribute("value") == "\\note "
    question.clear()
    question.send_keys("/")
    assert browser.execute_script("""
      const menu = document.getElementById('command-menu').getBoundingClientRect();
      const send = document.getElementById('plan-question').getBoundingClientRect();
      const tools = document.querySelector('.composer-tools').getBoundingClientRect();
      return menu.left >= 0 && menu.right <= innerWidth && menu.top >= 0
        && document.documentElement.scrollWidth <= innerWidth && tools.right <= send.left;
    """)
    output = Path("/tmp/graphmine-command-previews")
    output.mkdir(exist_ok=True)
    browser.save_screenshot(str(output / f"commands-{width}.png"))


def test_commands_without_data_or_planner_survive_reload(
    loading_browser, loading_server
):
    browser, server = loading_browser, loading_server
    server.responses[0].status = 503
    server.responses[0].release.set()
    server.events = [
        {
            "sequence": 1,
            "type": "workflow.chat",
            "created_at": "2026-01-01T00:00:00+00:00",
            "payload": {
                "role": "assistant",
                "turn_id": "analysis-1",
                "message": "An earlier answer",
            },
        }
    ]
    server.messages = [
        {
            "kind": "workflow.chat",
            "role": "assistant",
            "turn_id": "analysis-1",
            "created_at": "2026-01-01T00:00:00+00:00",
            "message": "An earlier answer",
        }
    ]

    def respond(path, body):
        assert path.endswith("/chat")
        command = body["message"].strip().split()[0][1:]
        response = {
            "message": "Saved locally <script>unsafe()</script>",
            "turn_id": "command-1",
            "command": command,
        }
        for role, data in [("user", body), ("assistant", response)]:
            server.messages.append(
                {
                    **data,
                    "role": role,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "kind": "feedback_command.request"
                    if role == "user"
                    else "feedback_command.response",
                }
            )
        return response

    server.post_handler = respond
    browser.get(server.url + "/#workspace/saved-session/chat")
    wait_for(
        browser, "GraphMineWorkspace.state.session && !GraphMineWorkspace.state.busy"
    )
    question = browser.find_element(By.ID, "question")
    question.send_keys("/help ", Keys.ENTER)
    wait_for(
        browser, "document.querySelectorAll('#messages .local-command').length === 2"
    )
    assert server.requests == [
        ("POST", "/api/sessions/saved-session/chat", {"message": "/help"})
    ]
    assert len(browser.find_elements(By.CSS_SELECTOR, "#messages .chat-message")) == 3
    assert not browser.find_elements(By.CSS_SELECTOR, "#messages script")
    assert "<script>unsafe()</script>" in browser.find_element(By.ID, "messages").text
    browser.refresh()
    wait_for(
        browser, "GraphMineWorkspace.state.session && !GraphMineWorkspace.state.busy"
    )
    assert len(browser.find_elements(By.CSS_SELECTOR, "#messages .chat-message")) == 3
    assert (
        browser.find_elements(By.CSS_SELECTOR, "#messages .chat-message")[-1]
        .get_attribute("class")
        .endswith("local-command")
    )
    browser.find_element(By.ID, "question").send_keys("/export ", Keys.ENTER)
    wait_for(browser, "document.querySelector('.command-download') !== null")
    browser.find_element(By.CSS_SELECTOR, ".command-download").click()
    wait_for(browser, "!GraphMineWorkspace.state.busy")
    assert (
        "GET",
        "/api/sessions/saved-session/history/archive",
        None,
    ) in server.requests
    assert not any(path.endswith("/analytics/plan") for _, path, _ in server.requests)


def test_answer_feedback_dialog_and_restored_controls(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    server.events = [
        {
            "sequence": 1,
            "type": "workflow.chat",
            "payload": {
                "role": "assistant",
                "turn_id": "answer-1",
                "message": "The result is three.",
            },
        }
    ]
    server.post_handler = lambda path, body: {"id": "saved-feedback", **body}
    open_chat(browser, server)
    browser.find_element(By.CSS_SELECTOR, ".answer-feedback").click()
    browser.find_element(By.ID, "conversation-feedback-kind").send_keys("Rating")
    browser.find_element(By.ID, "conversation-feedback-rating").send_keys("5")
    browser.find_element(By.ID, "save-conversation-feedback").click()
    wait_for(
        browser,
        "!document.getElementById('conversation-feedback-dialog').open && !GraphMineWorkspace.state.busy",
    )
    method, path, body = server.requests[-1]
    assert (method, path) == ("POST", "/api/sessions/saved-session/feedback")
    assert (
        body["turn_id"] == "answer-1"
        and body["rating"] == 5
        and body["category"] == "rating"
    )
    browser.find_element(By.ID, "toggle-data").click()
    browser.find_element(
        By.CSS_SELECTOR, "details:has(#conversation-help) summary"
    ).click()
    assert (
        browser.find_element(By.ID, "conversation-feedback-count").text
        == "1 saved annotation"
    )
    browser.find_element(By.ID, "conversation-export-feedback").click()
    wait_for(browser, "!GraphMineWorkspace.state.busy")
    assert (
        "GET",
        "/api/sessions/saved-session/feedback/export",
        None,
    ) in server.requests
    browser.find_element(By.ID, "conversation-feedback").click()
    assert not browser.find_element(By.ID, "data-sidebar").is_displayed()
    assert browser.find_element(By.ID, "conversation-feedback-dialog").is_displayed()
    browser.find_element(By.ID, "close-conversation-feedback").click()
