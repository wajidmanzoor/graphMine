"""Real Firefox rendering of checked answers; transport evidence is authored."""
import pytest
from selenium.webdriver.common.by import By

from test_analytics_workspace import browser_evidence, capture  # noqa: F401
from test_workspace_conversation_graph import (
    event, loading_browser, loading_server, open_saved, saved_network,
)


def citation(identifier='f1', kind='fact', ref='workflow:saved-analysis:revision:1:step:core:f1'):
    return {'id': identifier, 'kind': kind, 'ref': ref}


@pytest.mark.parametrize('width', [320, 390, 1200])
def test_completed_answer_has_one_footer_and_details_in_activity(loading_browser, loading_server, width):
    browser, server = loading_browser, loading_server
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={'width': width, 'height': 1000})
    saved_network(server)
    text = 'Found 2 groups.\nThe largest has 3 members: Ann, Bob and Zoë.'
    source = {**citation(), 'text': text, 'title': 'Result fact'}
    event(server, 'chat', 'first', role='user', message='Find the communities', mode='normal')
    event(server, 'chat', 'first', role='assistant', status='ready', message=text)
    event(server, 'answer', 'first', workflow_id='saved-analysis', revision=1, pending=False,
          text=text, citations=[citation()], sources=[source], source='model', lead='', fact_ids=['f1'],
          facts=[{'id': 'f1', 'statement': 'Community detection: ' + text}])
    open_saved(browser, server)
    for reload in [False, True]:
        if reload:
            browser.refresh()
        from test_workspace_loading import wait_for
        wait_for(browser, "document.querySelector('#messages .grounded-answer')")
        bubble = browser.find_element(By.CSS_SELECTOR, '#messages .assistant .chat-bubble')
        assert bubble.text.count('Found 2 groups.') == 1
        assert not bubble.find_elements(By.CSS_SELECTOR, '.answer-facts, .answer-lead')
        assert 'Validated ✓' in bubble.text
        assert not bubble.find_elements(By.CSS_SELECTOR, '.answer-sources, .answer-explanation, .chat-trace')
        bubble.find_element(By.CSS_SELECTOR, '.answer-details').click()
        sources = browser.find_element(By.CSS_SELECTOR, '.activity-step[data-stage="sources"]')
        assert not sources.get_attribute('open')
        sources.find_element(By.TAG_NAME, 'summary').click()
        assert citation()['ref'] not in sources.text and 'Ann, Bob and Zoë' in sources.text
        assert sources.find_element(By.CSS_SELECTOR, '.copy-id').is_displayed()
        assert browser.execute_script("return [...document.querySelectorAll('.activity-step summary, .activity-source small')].filter(el=>el.getClientRects().length).every(e => parseFloat(getComputedStyle(e).fontSize) >= 14)")
        browser.execute_script("GraphMineShell.setPanel('activity', false)")
        assert bubble.text.count('Found 2 groups.') == 1
        assert browser.execute_script('return document.documentElement.scrollWidth <= innerWidth + 2')
        if not reload:
            capture(browser, f'grounded-answer-{width}.png')


def test_inline_answer_does_not_repeat_facts_and_keeps_saved_result_link(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    saved_network(server)
    text = 'Ann belongs to the largest group.\nThat group has 3 members.'
    event(server, 'chat', 'explain', role='user', message='Why is Ann there?')
    event(server, 'chat', 'explain', role='assistant', status='answered', message=text,
          answer={'text': text, 'citations': [citation()], 'sources': [{**citation(), 'text': text}],
                  'workflow_id': 'saved-analysis', 'facts': [{'id': 'f1', 'statement': text}]})
    open_saved(browser, server)
    bubble = browser.find_element(By.CSS_SELECTOR, '.assistant[data-turn="explain"]')
    assert bubble.text.count('That group has 3 members.') == 1
    assert not bubble.find_elements(By.CSS_SELECTOR, '.answer-sources')
    assert len(bubble.find_elements(By.CSS_SELECTOR, '.result-link')) == 1
    assert not bubble.find_elements(By.CSS_SELECTOR, '.answer-facts')
    assert bubble.find_element(By.CSS_SELECTOR, ".grounded-answer p").is_displayed()


@pytest.mark.parametrize('status', ['ok', 'blocked', 'disabled'])
def test_google_sources_or_failure_link_are_explicit_and_safe(loading_browser, loading_server, status):
    browser, server = loading_browser, loading_server
    saved_network(server)
    text = {'ok': 'A core has a specified minimum degree.',
            'blocked': "Google blocked this server's search.",
            'disabled': 'Web search is currently disabled.'}[status]
    cited = citation('web.1', 'web', 'https://example.org/core') if status == 'ok' else citation('google.status', 'fact', 'tool:google_search')
    source = {**cited, 'text': text, 'title': '<img src=x onerror=alert(1)>',
              'provenance': 'Google result excerpt; destination page not fetched'}
    event(server, 'chat', 'web', role='user', message='Google k-core definition')
    event(server, 'chat', 'web', role='assistant', status='answered', message=text,
          answer={'text': text, 'citations': [cited], 'sources': [source],
                  'web_search': {'status': status, 'search_url': None if status == 'disabled' else 'https://www.google.com/search?q=k-core'}})
    open_saved(browser, server)
    bubble = browser.find_element(By.CSS_SELECTOR, '.assistant[data-turn="web"]')
    assert bubble.text.count(text) == 1
    assert not bubble.find_elements(By.TAG_NAME, 'img')
    assert not bubble.find_elements(By.CSS_SELECTOR, '.answer-sources')
    if status == 'ok':
        bubble.find_element(By.CSS_SELECTOR, '.inline-citation').click()
    else:
        bubble.find_element(By.CSS_SELECTOR, '.answer-details').click()
        browser.find_element(By.CSS_SELECTOR, '.activity-step[data-stage="sources"] > summary').click()
    sources = browser.find_element(By.CSS_SELECTOR, '.activity-step[data-stage="sources"]')
    assert not sources.find_elements(By.TAG_NAME, 'img')
    if status == 'disabled':
        assert not sources.find_elements(By.LINK_TEXT, 'Open this search in Google')
    elif status == 'blocked':
        link = sources.find_element(By.LINK_TEXT, 'Open this search in Google')
        assert link.get_attribute('href') == 'https://www.google.com/search?q=k-core'
    else:
        link = sources.find_element(By.TAG_NAME, 'a')
        assert link.get_attribute('href') == 'https://example.org/core'
        assert 'noopener' in link.get_attribute('rel')
        assert sources.find_element(By.CSS_SELECTOR, '.markdown-body').text == text
        assert 'destination page not fetched' in sources.text
