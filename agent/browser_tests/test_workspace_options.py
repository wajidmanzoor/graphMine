"""The saved choice contract reaches the UI and returns only after a click."""

from copy import deepcopy

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from test_analytics_workspace import capture
from test_workspace_conversation_graph import event, open_saved, saved_network, saved_turn
from test_workspace_loading import loading_browser, loading_server, wait_for


def option_cards(server):
    saved_network(server)
    fields = [
        {"operation": "k-core", "name": "requested_k", "label": "requested k", "kind": "integer",
         "schema": {"type": "integer", "minimum": 0}, "has_value": True, "value": 3},
        {"operation": "k-core", "name": "direction_mode", "label": "direction", "kind": "string",
         "schema": {"enum": ["undirected", "in", "out"]}, "has_value": True, "value": "undirected"},
        {"operation": "k-core", "name": "vertices", "label": "vertices", "kind": "array",
         "schema": {"type": "array"}, "has_value": True, "value": [9007199254740993, "001"]},
    ]
    first = {"id": "option_1", "title": "K-core", "operations": ["k-core"], "parameters": {"requested_k": 3},
             "parameter_fields": fields, "quality": "exact", "match": "High", "preselected": True,
             "interpretation": "Find groups with at least three connections per person.",
             "cost_hint": "Processes six vertices and seven connections.",
             "difference": "Requires a minimum degree; the alternative requires a complete group.",
             "description": "Find the core subgraph."}
    second = {**deepcopy(first), "id": "option_2", "title": "Maximal cliques", "operations": ["maximal-cliques"],
              "parameter_fields": [], "parameters": {}, "match": "Low", "preselected": False,
              "interpretation": "Find complete groups.", "description": "Every person connects to every other person."}
    event(server, "chat", "proposal", role="user", message="Find connected groups", mode="normal")
    event(server, "chat", "proposal", role="assistant", status="options", message="Choose a calculation.",
          question="Find connected groups", options=[first, second], inputs={"main": {"file_id": "network", "kind": "graph"}}, device="cpu")


@pytest.mark.parametrize("width", [1440, 390])
def test_preselection_waits_and_edits_keep_typed_values_after_reload(loading_browser, loading_server, width):
    browser, server = loading_browser, loading_server
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 1000})
    option_cards(server)
    submissions = []
    def choose(body):
        submissions.append(body)
        return {"turn_id": body["request_id"], "status": "needs_information", "message": "Which result next?", "choices": []}
    server.plan_handler = choose
    open_saved(browser, server)
    browser.refresh()
    wait_for(browser, "document.querySelectorAll('.calculation-option').length === 2 && !GraphMineWorkspace.state.busy")
    assert submissions == []
    first = browser.find_element(By.CSS_SELECTOR, '[data-option="option_1"]')
    assert "High match" in first.text and "awaiting your choice" in first.text
    assert "Low match" in browser.find_element(By.CSS_SELECTOR, '[data-option="option_2"]').text
    first.find_element(By.CSS_SELECTOR, '.option-parameters > summary').click()
    k = first.find_element(By.CSS_SELECTOR, '[data-parameter="requested_k"]')
    assert k.get_attribute("value") == "3"
    k.clear(); k.send_keys("2")
    Select(first.find_element(By.CSS_SELECTOR, '[data-parameter="direction_mode"]')).select_by_value('"out"')
    assert "Parameters edited" in first.text and "High match" not in first.text
    assert submissions == []
    assert browser.execute_script("return document.documentElement.scrollWidth <= innerWidth")
    capture(browser, f"options-{width}.png")
    first.find_element(By.CSS_SELECTOR, '[data-pick-option]').click()
    wait_for(browser, "!GraphMineWorkspace.state.busy")
    assert len(submissions) == 1
    sent = submissions[0]
    assert sent["intent"] == "calculate" and sent["operations"] == ["k-core"]
    assert sent["parameters"] == {"requested_k": 2, "direction_mode": "out", "vertices": [9007199254740993, "001"]}
    assert sent["option_id"] == "option_1" and sent["option_turn_id"] == "proposal"


def test_invalid_parameter_json_stays_local(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    option_cards(server)
    server.plan_handler = lambda body: pytest.fail("Invalid JSON must not be sent")
    open_saved(browser, server)
    first = browser.find_element(By.CSS_SELECTOR, '[data-option="option_1"]')
    first.find_element(By.CSS_SELECTOR, '.option-parameters > summary').click()
    values = first.find_element(By.CSS_SELECTOR, '[data-parameter="vertices"]')
    values.clear(); values.send_keys("[invalid")
    first.find_element(By.CSS_SELECTOR, '[data-pick-option]').click()
    assert "Enter valid JSON for vertices." in first.find_element(By.CSS_SELECTOR, '[role="alert"]').text
    assert not browser.execute_script("return GraphMineWorkspace.state.busy")


def test_member_in_expert_mode_cannot_see_working_notes(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    saved_turn(server, "first", "Find groups")
    open_saved(browser, server)
    browser.execute_script("window.GraphMineAccount.user={role:'user'}; document.querySelector('[data-mode=expert]').click()")
    browser.find_element(By.ID, "toggle-activity").click()
    assert not browser.find_elements(By.CSS_SELECTOR, ".reasoning-turn, .reasoning-record")
    assert "Decision for" in browser.find_element(By.ID, "activity-list").text


def test_equal_plan_message_is_not_repeated_in_the_answer(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    text = "A core uses the minimum degree."
    event(server, "chat", "reply", role="user", message="What is a core?", mode="normal")
    event(server, "chat", "reply", role="assistant", status="answered", message=text,
          answer={"text": text, "citations": []}, lane="reply")
    open_saved(browser, server)
    assert browser.find_element(By.ID, "messages").text.count(text) == 1
