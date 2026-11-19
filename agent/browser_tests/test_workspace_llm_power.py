from selenium.webdriver.common.by import By

from test_analytics_workspace import capture
from test_workspace_conversation_graph import event
from test_workspace_loading import loading_browser, loading_server, wait_for


def test_waking_status_and_timeout_retry_keep_the_question(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    event(server, 'chat', 'wake-question', role='user', message='What is a dense subgraph?', mode='normal', inputs={}, device='cpu')
    event(server, 'planning', 'wake-question', stage='route', status='waking', message='Waking the model…')
    server.responses[0].release.set()
    submissions = []
    def plan(body):
        submissions.append(body)
        return {'turn_id': body['request_id'], 'status': 'answered', 'message': 'The model is ready.', 'plan': None}
    server.plan_handler = plan
    browser.get(server.url + '/#workspace/saved-session/chat')
    wait_for(browser, "document.getElementById('chat-status').textContent === 'Waking the model…' && document.querySelector('.planning-progress')?.textContent.includes('Waking the model…')")
    assert 'Waking the model…' in browser.find_element(By.CSS_SELECTOR, '.planning-progress').text
    assert submissions == []
    capture(browser, 'model-waking.png')
    event(server, 'chat', 'wake-question', role='assistant', status='failed', code='llm_unavailable',
          retryable=True, message='The model is waking up and did not respond in time')
    wait_for(browser, "document.querySelector('[data-retry=\"wake-question\"]') !== null")
    assert 'The model is waking up and did not respond in time' in browser.find_element(By.ID, 'messages').text
    assert browser.find_element(By.ID, 'chat-status').text != 'Waking the model…'
    capture(browser, 'model-wake-retry.png')
    browser.find_element(By.CSS_SELECTOR, '[data-retry="wake-question"]').click()
    wait_for(browser, '!GraphMineWorkspace.state.busy')
    assert len(submissions) == 1 and submissions[0]['message'] == 'What is a dense subgraph?'
