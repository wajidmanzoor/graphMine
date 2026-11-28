"""Real browser queries must follow the single published dataset selector."""

import json
import os

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from graphmine_agent.neo4j_registry import ready_datasets
import test_database_roundtrip as fixtures

loading_browser = fixtures.loading_browser
database_server = fixtures.database_server
click, wait, screenshot = fixtures.click, fixtures.wait, fixtures.screenshot
pytestmark = [fixtures.pytestmark, pytest.mark.skipif(
    not os.getenv('GRAPHMINE_DATABASE_DATASET_ALLOWLIST') or os.getenv('GRAPHMINE_TEST_BENCHMARK_INTEGRATION') != '1',
    reason='requires the five published isolated datasets and curated configuration')]


@pytest.mark.parametrize('width,height', [(1440, 1050), (390, 844)])
def test_one_picker_routes_arbitrary_queries_and_keeps_drafts_separate(loading_browser, database_server, width, height):
    browser = loading_browser
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={'width': width, 'height': height})
    browser.get(database_server.url)
    browser.execute_script("localStorage.setItem('graphmine.apiToken', 'test-secret')")
    browser.refresh()
    wait(browser, 'GraphMineWorkspace.state.caps && !GraphMineWorkspace.state.busy')
    click(browser, 'open-database-workspace')
    wait(browser, "document.getElementById('database-source')?.options.length === 5 && !document.getElementById('preview-cypher').disabled")
    picker = browser.find_element(By.ID, 'database-source')
    assert picker.get_attribute('aria-label') == 'Dataset'
    assert [option.text for option in Select(picker).options] == [
        'Transfers demo', 'Yelp', 'MovieLens 32M', 'MovieLens Tag Genome', 'LDBC SNB SF100 BI']
    for identifier in ('database-dataset', 'add-connection', 'edit-connection', 'sync-database'):
        assert not browser.find_element(By.ID, identifier).is_displayed()
    assert not browser.find_element(By.CSS_SELECTOR, '.source-connection-details').is_displayed()
    assert browser.execute_script("return document.getElementById('database-workspace').scrollWidth <= document.getElementById('database-workspace').clientWidth")
    screenshot(browser, f'curated-datasets-{width}.png')
    expected = {'local-transfers': ('default', 8)}
    expected.update({'benchmark-' + row['id']: (row['id'], row['node_count'])
                     for row in ready_datasets(database_server.app.state.runtime.settings)})
    assert len(expected) == 5
    for source_id, (dataset_id, count) in expected.items():
        Select(picker).select_by_value(source_id)
        wait(browser, f"document.getElementById('database-dataset').value === {json.dumps(dataset_id)} && !document.getElementById('preview-cypher').disabled")
        assert browser.find_element(By.ID, 'database-preview-count').get_attribute('textContent') == 'No query run yet'
        if width <= 800:
            click(browser, 'data-step-query')
        selected_name = Select(picker).first_selected_option.get_attribute('textContent')
        assert browser.find_element(By.ID, 'database-query-scope').text == f'Queries run only on {selected_name}.'
        # Identical unqualified Cypher across every selection must count only
        # that instance. In particular the demo must not see the legacy store.
        browser.execute_script("const e=document.getElementById('cypher-editor'); e.value=arguments[0]; e.dispatchEvent(new Event('input',{bubbles:true}));",
                               'MATCH (n) RETURN count(n) AS nodes')
        click(browser, 'preview-cypher')
        wait(browser, "document.getElementById('database-preview-count').textContent.includes('1 rows') && !document.getElementById('preview-cypher').disabled")
        rows = json.loads(browser.find_element(By.ID, 'database-query-rows').get_attribute('textContent'))
        assert rows == [{'nodes': count}]
    Select(picker).select_by_value('benchmark-yelp')
    wait(browser, "document.getElementById('database-dataset').value === 'yelp' && !document.getElementById('preview-cypher').disabled")
    assert browser.find_element(By.ID, 'cypher-editor').get_attribute('value') == 'MATCH (n) RETURN count(n) AS nodes'
    assert browser.find_element(By.ID, 'database-preview-count').get_attribute('textContent') == 'No query run yet'
