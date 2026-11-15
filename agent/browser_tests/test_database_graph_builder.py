"""Review generated queries before replacing a draft; discard stale generation."""

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from test_query_previews import open_source_fixture
from test_workspace_loading import loading_browser, loading_server, wait_for


def click(browser, selector):
    element = browser.find_element(By.CSS_SELECTOR, selector)
    step = browser.execute_script("const pane=arguments[0].closest('.data-pane'); return pane?.hidden ? pane.getAttribute('aria-labelledby') : null;", element)
    if step:
        browser.find_element(By.ID, step).click()
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", element)
    element.click()
    return element


def choose(browser, identifier, value):
    element = browser.find_element(By.ID, identifier)
    step = browser.execute_script("const pane=arguments[0].closest('.data-pane'); return pane?.hidden ? pane.getAttribute('aria-labelledby') : null;", element)
    if step:
        browser.find_element(By.ID, step).click()
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", element)
    Select(element).select_by_value(value)


def builder_fixture(browser, server, *, multiple=False):
    open_source_fixture(browser, server, multiple=multiple)
    browser.execute_script(r"""
      const previous = window.fetch;
      const reply = data => Promise.resolve(new Response(JSON.stringify(data), {headers:{'Content-Type':'application/json'}}));
      window.buildRequests = []; window.executedQueries = []; window.delayBuild = false;
      window.fetch = (path, options={}) => {
        if (path.includes('/graph-builder')) {
          if (options.method === 'POST') {
            const body = JSON.parse(options.body); window.buildRequests.push(body);
            const data = {statement:'MATCH p = (a:`Account`)-[r:`TRANSFER`]->(b:`Account`)\nWHERE r.`amount` >= $filter_0\nRETURN p\nLIMIT $row_limit',
              parameters:{filter_0:body.filters[0]?.value ?? 0, row_limit:body.limit},
              directed:body.directed, projection:'elements', weight_property:body.weight_property,
              dataset_id:body.dataset_id, description:'Up to '+body.limit+' relationships and their endpoints.'};
            return window.delayBuild ? new Promise(resolve => {window.releaseBuild = () => resolve(reply(data));}) : reply(data);
          }
          return reply({entities:[{id:'accounts', label:'Account', properties:[{name:'name'}]}],
            relationships:[{id:'transfers',label:'TRANSFER',source_entity:'accounts',target_entity:'accounts',properties:[{name:'amount',type:'number'}]}],max_rows:5000});
        }
        if (path.endsWith('/queries')) window.executedQueries.push(JSON.parse(options.body));
        return previous(path, options);
      };
    """)
    click(browser, "#graph-builder > summary")
    wait_for(browser, "document.getElementById('builder-entity').options.length === 1")


@pytest.mark.parametrize("width", [1440, 320])
def test_generated_query_is_reviewed_then_applied_with_weights(loading_browser, loading_server, width):
    browser = loading_browser
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 900})
    builder_fixture(browser, loading_server)
    original = browser.find_element(By.ID, "cypher-editor").get_attribute("value")
    choose(browser, "builder-relationship", "transfers")
    choose(browser, "builder-weight", "amount")
    choose(browser, "builder-analysis-direction", "undirected")
    click(browser, "#builder-add-filter")
    fields = browser.find_elements(By.CSS_SELECTOR, ".builder-filter select")
    Select(fields[0]).select_by_value("relationship")
    Select(fields[2]).select_by_value("gte")
    Select(fields[3]).select_by_value("number")
    value = browser.find_element(By.CSS_SELECTOR, ".builder-filter input")
    value.send_keys("25")
    click(browser, "#builder-generate")
    wait_for(browser, "document.getElementById('builder-cypher').textContent.includes('RETURN p')")
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("value") == original
    assert browser.execute_script("return executedQueries.length") == 0
    assert browser.execute_script("return buildRequests[0].filters[0]") == {"scope": "relationship", "property": "amount", "operator": "gte", "value": 25}
    click(browser, "#builder-apply")
    assert "RETURN p" in browser.find_element(By.ID, "cypher-editor").get_attribute("value")
    assert browser.find_element(By.ID, "query-weight-property").get_attribute("value") == "amount"
    click(browser, "#preview-cypher")
    wait_for(browser, "executedQueries.length === 1")
    executed = browser.execute_script("return executedQueries[0]")
    assert executed["parameters"]["filter_0"] == 25
    assert executed["weight_property"] == "amount" and not executed["directed"]
    assert executed["projection"] == "elements"
    assert browser.execute_script("return document.getElementById('database-workspace').scrollWidth <= document.getElementById('database-workspace').clientWidth")
    click(browser, "#close-data-source")
    click(browser, "#open-database-workspace")
    wait_for(browser, "document.getElementById('query-weight-property')?.value === 'amount'")
    assert "Draft restored" in browser.find_element(By.ID, "query-draft-status").get_attribute("textContent")


def test_generation_from_previous_dataset_cannot_replace_current_editor(loading_browser, loading_server):
    browser = loading_browser
    builder_fixture(browser, loading_server, multiple=True)
    choose(browser, "builder-relationship", "transfers")
    browser.execute_script("window.delayBuild = true")
    click(browser, "#builder-generate")
    wait_for(browser, "Boolean(window.releaseBuild)")
    choose(browser, "database-dataset", "second")
    wait_for(browser, "!document.getElementById('builder-generate').disabled")
    browser.execute_script("window.releaseBuild()")
    browser.execute_async_script("setTimeout(arguments[arguments.length-1], 100)")
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("value") == "MATCH (n) RETURN n LIMIT 10"
    assert not browser.find_element(By.ID, "builder-apply").is_displayed()
    assert browser.execute_script("return executedQueries.length") == 0
