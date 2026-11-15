"""Query actions execute explicitly and retain user-entered drafts."""

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from test_workspace_loading import loading_browser, loading_server  # noqa: F401


def test_repeated_preview_and_refresh_preserve_query_parameters(loading_browser, loading_server):
    browser, server = loading_browser, loading_server
    server.responses[0].release.set()
    browser.get(server.url)
    wait = WebDriverWait(browser, 15)
    wait.until(lambda d: d.execute_script("return window.GraphMineWorkspace?.state.domains.length && !GraphMineWorkspace.state.busy"))
    browser.execute_script("""
      window.queryCalls = 0;
      const original = window.fetch;
      const reply = data => Promise.resolve(new Response(JSON.stringify(data), {
        headers: {'Content-Type': 'application/json'}, status: 200
      }));
      window.fetch = (input, options) => {
        const path = String(input);
        if (path.endsWith('/api/database-sources')) return reply([{
          id:'review', name:'Review connection', sql_type:'postgres',
          entities:[], relationships:[], managed:true,
          connection:{sql:{host:'localhost',port:5432,database:'review'},
                      neo4j:{uri:'bolt://localhost:7687',database:'neo4j'}}
        }]);
        if (path.endsWith('/database-sources/review/status')) return reply({
          connected:true,sql:{connected:true},neo4j:{connected:true}
        });
        if (path.endsWith('/database-sources/review/datasets')) return reply([{
          id:'default',name:'Review graph',status:'ready',schemas:[],tables:[],
          default_query:'MATCH (n) RETURN n LIMIT 10'
        }]);
        if (path.endsWith('/database-sources/review/queries')) {
          window.queryCalls++;
          return reply({
            dataset:{id:'saved-'+window.queryCalls}, row_count:1, rows:[],
            vertex_count:1,edge_count:0,elapsed_ms:123,
            graph:{graph:{directed:true},vertices:[{id:1,label:'Ada'}],edges:[]}
          });
        }
        return original(input, options);
      };
    """)
    browser.find_element(By.ID, "open-database-workspace").click()
    wait.until(lambda d: d.execute_script("return document.getElementById('preview-cypher')?.disabled === false"))
    for expected in (1, 2):
        browser.find_element(By.ID, "preview-cypher").click()
        wait.until(lambda d: d.execute_script(
            "return document.getElementById('preview-cypher').disabled === false && window.queryCalls === arguments[0]", expected
        ))
    browser.execute_script("""
      const editor = document.getElementById('cypher-editor'), params = document.getElementById('cypher-parameters');
      editor.value = 'MATCH (n) WHERE n.name=$name RETURN n LIMIT 20';
      params.value = '{"name":"Ada"}';
      editor.dispatchEvent(new Event('input', {bubbles:true}));
    """)
    refresh = browser.find_element(By.ID, "refresh-database-datasets")
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", refresh)
    refresh.click()
    wait.until(lambda d: d.execute_script("return document.getElementById('preview-cypher').disabled === false"))
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("value") == "MATCH (n) WHERE n.name=$name RETURN n LIMIT 20"
    assert browser.find_element(By.ID, "cypher-parameters").get_attribute("value") == '{"name":"Ada"}'
    assert not browser.find_element(By.ID, "source-continue").is_displayed()


@pytest.mark.parametrize("width", [1440, 390])
def test_projection_example_and_table_result_feedback(loading_browser, loading_server, width):
    browser, server = loading_browser, loading_server
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 1000})
    server.responses[0].release.set()
    browser.get(server.url)
    wait = WebDriverWait(browser, 15)
    wait.until(lambda d: d.execute_script("return window.GraphMineWorkspace?.state.domains.length && !GraphMineWorkspace.state.busy"))
    browser.execute_script("""
      window.queryBodies = [];
      const original = window.fetch;
      const reply = data => Promise.resolve(new Response(JSON.stringify(data), {
        headers: {'Content-Type': 'application/json'}, status: 200
      }));
      window.fetch = (input, options) => {
        const path = String(input);
        if (path.endsWith('/api/database-sources')) return reply([{
          id:'review', name:'Review connection', sql_type:'postgres', entities:[], relationships:[]
        }]);
        if (path.endsWith('/database-sources/review/status')) return reply({
          connected:true,sql:{connected:true},neo4j:{connected:true}
        });
        if (path.endsWith('/database-sources/review/datasets')) return reply([{
          id:'movielens-32m',name:'MovieLens 32M',status:'ready',schemas:[],tables:[],
          default_query:'MATCH (n) RETURN n LIMIT 10'
        }]);
        if (path.endsWith('/database-sources/review/queries')) {
          const body = JSON.parse(options.body); window.queryBodies.push(body);
          const projected = body.projection === 'rows';
          return reply({
            dataset:projected ? {id:'projected-graph'} : null,
            row_count:2, rows:[{weight:3},{weight:4}], rows_truncated:false,
            vertex_count:projected ? 3 : 0, edge_count:projected ? 2 : 0, elapsed_ms:123,
            message:'2 rows returned as table values.',
            graph:{graph:{directed:false},
              vertices:projected ? [{id:1,label:'User 1'},{id:2,label:'User 2'},{id:3,label:'User 3'}] : [],
              edges:projected ? [{source:1,target:2},{source:1,target:3}] : []}
          });
        }
        return original(input, options);
      };
    """)
    browser.find_element(By.ID, "open-database-workspace").click()
    wait.until(lambda d: d.execute_script("return document.getElementById('preview-cypher')?.disabled === false"))
    example = browser.find_element(By.ID, "query-shared-movies")
    if browser.find_element(By.ID, "data-step-query").is_displayed():
        browser.find_element(By.ID, "data-step-query").click()
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", example)
    example.click()
    assert Select(browser.find_element(By.ID, "query-graph-projection")).first_selected_option.get_attribute("value") == "rows"
    assert Select(browser.find_element(By.ID, "query-graph-direction")).first_selected_option.get_attribute("value") == "undirected"
    assert "AS source" in browser.find_element(By.ID, "cypher-editor").get_attribute("value")
    assert browser.find_element(By.ID, "cypher-parameters").get_attribute("value") == '{"userLimit": 100}'
    assert browser.execute_script("return document.getElementById('database-workspace').scrollWidth <= document.getElementById('database-workspace').clientWidth")
    preview = browser.find_element(By.ID, "preview-cypher")
    preview.click()
    wait.until(lambda d: d.execute_script("return !document.getElementById('source-continue').hidden"))
    assert "2 rows" in browser.find_element(By.ID, "database-preview-count").text
    assert browser.execute_script("return queryBodies[0].projection === 'rows' && queryBodies[0].directed === false")
    close = browser.find_element(By.ID, "close-data-source")
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", close)
    close.click()
    browser.find_element(By.ID, "open-database-workspace").click()
    wait.until(lambda d: d.execute_script("return document.getElementById('preview-cypher')?.disabled === false"))
    selector = browser.find_element(By.ID, "query-graph-projection")
    if browser.find_element(By.ID, "data-step-query").is_displayed():
        browser.find_element(By.ID, "data-step-query").click()
    assert Select(selector).first_selected_option.get_attribute("value") == "rows"
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", selector)
    Select(selector).select_by_value("elements")
    browser.find_element(By.ID, "preview-cypher").click()
    wait.until(lambda d: d.execute_script("return !document.getElementById('preview-cypher').disabled && queryBodies.length === 2"))
    assert "2 rows" in browser.find_element(By.ID, "database-preview-count").text
    assert "0 nodes" in browser.find_element(By.ID, "database-preview-count").text
    assert browser.find_element(By.CSS_SELECTOR, ".query-rows").get_attribute("open")
    assert browser.find_element(By.ID, "database-query-rows").text
    assert browser.find_element(By.ID, "database-query-status").text == "2 rows returned as table values."
    assert not browser.find_element(By.ID, "source-continue").is_displayed()
