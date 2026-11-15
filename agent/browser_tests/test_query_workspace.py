"""Private query library, typed parameters and accessible editor assistance."""

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from test_database_graph_builder import click, choose
from test_query_previews import open_source_fixture
from test_workspace_loading import loading_browser, loading_server, wait_for


def fixture(browser, server, *, multiple=False):
    open_source_fixture(browser, server, multiple=multiple)
    browser.execute_script(r"""
      const previous = window.fetch;
      const reply = (data,status=200) => Promise.resolve(new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}}));
      window.libraryEntries = []; window.libraryActions = []; window.editorQueries = []; window.queryError = null;
      window.delayLibrary = false;
      window.fetch = (path, options={}) => {
        const url = new URL(path, location.href);
        if (url.pathname === '/api/query-library') {
          if (options.method === 'POST') {
            const body = JSON.parse(options.body); libraryActions.push(['save',body]);
            const entry = {...body,id:'saved-'+libraryEntries.length,kind:'saved',revision:1,dataset_id:body.query.dataset_id,updated_at:new Date().toISOString()};
            libraryEntries.unshift(entry); return reply(entry);
          }
          const data = {items:libraryEntries.filter(e => e.kind === url.searchParams.get('kind') && e.dataset_id === url.searchParams.get('dataset_id')),has_more:false};
          return window.delayLibrary ? new Promise(resolve => {window.releaseLibrary = () => resolve(reply(data));}) : reply(data);
        }
        if (url.pathname.startsWith('/api/query-library/')) {
          const id = url.pathname.split('/').pop(), entry = libraryEntries.find(e=>e.id===id);
          if (options.method === 'DELETE') { libraryActions.push(['delete',id]); window.libraryEntries=libraryEntries.filter(e=>e.id!==id); return Promise.resolve(new Response(null,{status:204})); }
          if (options.method === 'PUT') { const body=JSON.parse(options.body); libraryActions.push(['update',body]); Object.assign(entry,body,{revision:entry.revision+1}); }
          return reply(entry);
        }
        if (url.pathname.endsWith('/graph-builder')) return reply({entities:[{id:'accounts',label:'Account',properties:[{name:'name'},{name:'risk'}]}],relationships:[],max_rows:5000});
        if (url.pathname.endsWith('/queries')) {
          editorQueries.push(options.body);
          if (window.queryError) return reply({error:window.queryError},422);
        }
        return previous(path,options);
      };
    """)


def edit(browser, statement, parameters="{}"):
    browser.execute_script("""
      const editor=document.getElementById('cypher-editor'), params=document.getElementById('cypher-parameters');
      editor.value=arguments[0]; params.value=arguments[1];
      editor.dispatchEvent(new Event('input',{bubbles:true}));
      params.dispatchEvent(new Event('input',{bubbles:true}));
    """, statement, parameters)


@pytest.mark.parametrize("width", [1440, 320])
def test_saved_queries_load_update_and_delete_without_running(loading_browser, loading_server, width):
    browser = loading_browser
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 900})
    fixture(browser, loading_server)
    statement = "MATCH (n) WHERE n.name=$name RETURN n"
    edit(browser, statement, '{"name":"Ada"}')
    click(browser, "#query-library > summary")
    wait_for(browser, "document.getElementById('query-library-status').textContent.includes('No saved queries')")
    field = click(browser, "#saved-query-name"); field.send_keys("Account lookup")
    click(browser, "#save-library-query")
    wait_for(browser, "document.getElementById('query-library-status').textContent.includes('Saved “')")
    edit(browser, "RETURN 1")
    click(browser, "#load-library-query")
    wait_for(browser, "document.getElementById('cypher-editor').value.includes('WHERE n.name')")
    assert browser.find_element(By.ID, "cypher-parameters").get_attribute("value").find('"Ada"') >= 0
    edit(browser, statement + " LIMIT 5", '{"name":"Ben"}')
    click(browser, "#update-library-query")
    wait_for(browser, "libraryActions.length === 2 && !document.getElementById('delete-library-query').disabled")
    assert browser.execute_script("return libraryActions[1][1].expected_revision") == 1
    click(browser, "#delete-library-query")
    wait_for(browser, "libraryEntries.length === 0 && document.getElementById('query-library-status').textContent.includes('deleted')")
    assert browser.execute_script("return editorQueries.length") == 0
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("value").endswith("LIMIT 5")
    assert browser.execute_script("return document.getElementById('database-workspace').scrollWidth <= document.getElementById('database-workspace').clientWidth")


def test_parameter_form_keeps_large_integers_and_rejects_invalid_edits(loading_browser, loading_server):
    browser = loading_browser
    fixture(browser, loading_server)
    edit(browser, "MATCH (n) RETURN n LIMIT $limit", '{"limit":10,"extra":"kept"}')
    click(browser, ".query-parameters > summary")
    wait_for(browser, "Boolean(document.querySelector('[data-query-parameter=limit]'))")
    field = click(browser, "[data-query-parameter=limit]")
    field.clear(); field.send_keys("9007199254740993")
    assert "9007199254740993" in browser.find_element(By.ID, "cypher-parameters").get_attribute("value")
    assert '"extra": "kept"' in browser.find_element(By.ID, "cypher-parameters").get_attribute("value")
    field.clear(); field.send_keys("invalid-number")
    click(browser, "#preview-cypher")
    wait_for(browser, "!document.getElementById('query-inline-error').hidden")
    assert browser.execute_script("return editorQueries.length") == 0
    assert browser.find_element(By.CSS_SELECTOR, "[data-query-parameter=limit]").get_attribute("value") == "invalid-number"
    field = click(browser, "[data-query-parameter=limit]"); field.clear(); field.send_keys("15")
    click(browser, "#preview-cypher")
    wait_for(browser, "editorQueries.length === 1")
    assert browser.execute_script("return JSON.parse(editorQueries[0]).parameters.limit") == 15


def test_formatter_and_parameter_discovery_preserve_literals_and_comments(loading_browser, loading_server):
    browser = loading_browser
    fixture(browser, loading_server)
    original = "match (n:`Return`) where n.name = 'return // $fake' /* $ignored */ return n // $also_ignored\n limit $limit"
    edit(browser, original)
    click(browser, "#format-cypher")
    formatted = browser.find_element(By.ID, "cypher-editor").get_attribute("value")
    assert "\nWHERE " in formatted and "\nRETURN " in formatted and "\nLIMIT $limit" in formatted
    assert "'return // $fake'" in formatted and "/* $ignored */" in formatted and "// $also_ignored\n" in formatted
    assert "`Return`" in formatted
    assert browser.execute_script("return GraphMineCypherTools.parameters(arguments[0])", formatted) == ["limit"]
    assert browser.execute_script("return GraphMineCypherTools.parameters(arguments[0])", "RETURN $`odd name`, $limit, '$ignored'") == ["odd name", "limit"]


def test_schema_suggestions_insert_quoted_properties_with_keyboard(loading_browser, loading_server):
    browser = loading_browser
    fixture(browser, loading_server)
    edit(browser, "MATCH (n) RETURN n.na")
    browser.execute_script("const e=document.getElementById('cypher-editor'); e.focus(); e.setSelectionRange(e.value.length,e.value.length)")
    click(browser, "#suggest-cypher")
    wait_for(browser, "document.getElementById('cypher-suggestions').options.length === 1")
    browser.find_element(By.ID, "cypher-suggestions").send_keys(Keys.ENTER)
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("value") == "MATCH (n) RETURN n.`name`"
    assert not browser.find_element(By.ID, "cypher-suggestions").is_displayed()


def test_inline_syntax_error_focuses_correct_unicode_position(loading_browser, loading_server):
    browser = loading_browser
    fixture(browser, loading_server)
    statement = "  MATCH (n) WHERE n.name='😀' RETURN bad(n)"
    edit(browser, statement)
    browser.execute_script("window.queryError={code:'cypher_syntax',message:'Invalid function at line 1',details:{line:1,column:arguments[0]+1,offset:arguments[0]}}", statement.index("bad"))
    click(browser, "#preview-cypher")
    wait_for(browser, "!document.getElementById('query-inline-error').hidden")
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("aria-invalid") == "true"
    click(browser, "#goto-query-error")
    assert browser.execute_script("const e=document.getElementById('cypher-editor'); return e.selectionStart===e.value.indexOf('bad') && document.activeElement===e")
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("value") == statement


def test_late_library_response_does_not_populate_another_dataset(loading_browser, loading_server):
    browser = loading_browser
    fixture(browser, loading_server, multiple=True)
    browser.execute_script("window.libraryEntries=[{id:'old',name:'Old dataset query',kind:'saved',dataset_id:'default',revision:1,updated_at:new Date().toISOString()}]; window.delayLibrary=true")
    click(browser, "#query-library > summary")
    wait_for(browser, "Boolean(window.releaseLibrary)")
    browser.execute_script("window.delayLibrary=false")
    choose(browser, "database-dataset", "second")
    wait_for(browser, "document.getElementById('query-library-status').textContent.includes('No saved queries')")
    browser.execute_script("window.releaseLibrary()")
    browser.execute_async_script("setTimeout(arguments[arguments.length-1],100)")
    assert browser.find_elements(By.CSS_SELECTOR, "#query-library-choices option") == []


def test_failed_history_can_be_loaded_and_saved_without_execution(loading_browser, loading_server):
    browser = loading_browser
    fixture(browser, loading_server)
    browser.execute_script("""
      window.libraryEntries=[{id:'run',name:'Previous lookup',kind:'history',status:'failed',
        error:{message:'Missing parameter'},elapsed_ms:20,dataset_id:'default',revision:1,
        updated_at:new Date().toISOString(),query:{statement:'MATCH (n) RETURN n LIMIT $limit',
        parameters:{limit:7},dataset_id:'default',projection:'elements',directed:true}}];
    """)
    click(browser, "#query-library > summary")
    choose(browser, "query-library-kind", "history")
    wait_for(browser, "document.getElementById('query-library-choices').options.length === 1")
    click(browser, "#load-library-query")
    wait_for(browser, "document.getElementById('query-library-status').textContent.includes('Previous error: Missing parameter')")
    assert browser.find_element(By.ID, "update-library-query").get_attribute("disabled")
    assert '"limit": 7' in browser.find_element(By.ID, "cypher-parameters").get_attribute("value")
    click(browser, "#save-library-query")
    wait_for(browser, "libraryEntries.some(e => e.kind === 'saved')")
    assert browser.execute_script("return editorQueries.length") == 0
