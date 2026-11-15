"""Users can explicitly keep or discard temporary query results."""

import pytest
from selenium.webdriver.common.by import By
from test_workspace_loading import loading_browser, loading_server, wait_for


def open_source_fixture(browser, server, *, multiple=False):
    server.responses[0].release.set()
    browser.get(server.url)
    wait_for(browser, "window.GraphMineWorkspace?.state.caps && !GraphMineWorkspace.state.busy")
    browser.execute_script(r"""
      const original = window.fetch, multiple = arguments[0];
      const reply = data => Promise.resolve(new Response(JSON.stringify(data), {headers:{'Content-Type':'application/json'}}));
      window.previewActions = []; window.previewCounter = 0;
      window.fetch = (path, options={}) => {
        if (path === '/api/database-sources') return reply((multiple ? ['preview-db','other-db'] : ['preview-db']).map(id => ({id, name:id, entities:[], relationships:[]})));
        if (/\/(preview-db|other-db)\/status$/.test(path)) return reply({connected:true,sql:{connected:true},neo4j:{connected:true}});
        if (/\/(preview-db|other-db)\/datasets$/.test(path)) return reply((multiple ? ['default','second'] : ['default']).map(id => ({id, name:id, status:'ready', schemas:[], tables:[], default_query:'MATCH (n) RETURN n LIMIT 10'})));
        if (path.endsWith('/preview-db/queries')) {
          previewActions.push('query');
          return reply({dataset:{id:'preview-'+(++window.previewCounter),temporary:true},
            row_count:1, rows:[], vertex_count:1, edge_count:0,
            graph:{graph:{directed:true},vertices:[{id:'a',label:'Ada'}],edges:[]}});
        }
        if (path.startsWith('/api/database-query-snapshots/')) {
          previewActions.push(options.method === 'DELETE' ? 'discard' : 'save');
          return options.method === 'DELETE' ? Promise.resolve(new Response(null, {status:204})) : reply({id:path.split('/')[3]});
        }
        return original(path, options);
      };
    """, multiple)
    browser.find_element(By.ID, "open-database-workspace").click()
    wait_for(browser, "document.getElementById('preview-cypher')?.disabled === false")
    if browser.find_element(By.ID, "data-step-query").is_displayed():
        browser.find_element(By.ID, "data-step-query").click()


@pytest.mark.parametrize("width", [1440, 390, 320])
def test_preview_is_saved_only_when_requested_and_can_be_discarded(loading_browser, loading_server, width):
    browser = loading_browser
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 1000})
    open_source_fixture(browser, loading_server)
    browser.find_element(By.ID, "preview-cypher").click()
    wait_for(browser, "document.getElementById('save-query-snapshot').disabled === false")
    assert browser.execute_script("return previewActions") == ["query"]
    assert "expires in 24 hours" in browser.find_element(By.ID, "database-query-status").text
    save = browser.find_element(By.ID, "save-query-snapshot")
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", save)
    save.click()
    wait_for(browser, "document.getElementById('save-query-snapshot').textContent === 'Saved in datasets'")
    assert browser.execute_script("return previewActions") == ["query", "save"]
    assert not browser.find_element(By.ID, "discard-query-preview").is_displayed()
    browser.find_element(By.ID, "preview-cypher").click()
    wait_for(browser, "document.getElementById('save-query-snapshot').disabled === false")
    discard = browser.find_element(By.ID, "discard-query-preview")
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", discard)
    discard.click()
    wait_for(browser, "document.getElementById('database-query-status').textContent.includes('Preview discarded')")
    assert browser.execute_script("return previewActions") == ["query", "save", "query", "discard"]
    assert not browser.find_element(By.ID, "source-continue").is_displayed()
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("value") == "MATCH (n) RETURN n LIMIT 10"
    assert browser.execute_script("return document.getElementById('database-workspace').scrollWidth <= document.getElementById('database-workspace').clientWidth")
