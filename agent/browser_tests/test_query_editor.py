"""Direct query execution, typed parameters and accessible editor assistance."""

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from workspace_browser_helpers import click
from test_query_previews import open_source_fixture
from test_workspace_loading import loading_browser, loading_server, wait_for


def fixture(browser, server, *, multiple=False):
    open_source_fixture(browser, server, multiple=multiple)
    browser.execute_script(r"""
      const previous = window.fetch;
      const reply = (data,status=200) => Promise.resolve(new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}}));
      window.editorQueries = []; window.queryError = null;
      window.fetch = (path, options={}) => {
        const url = new URL(path, location.href);
        if (url.pathname.endsWith('/schema')) return reply({entities:[{id:'accounts',label:'Account',properties:[{name:'name'},{name:'risk'}]}],relationships:[],max_rows:5000});
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


@pytest.mark.parametrize("width", [1440, 320])
def test_direct_query_preview_without_library_or_builder(loading_browser, loading_server, width):
    browser = loading_browser
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 900})
    fixture(browser, loading_server)
    assert browser.find_elements(By.CSS_SELECTOR, "#query-library, #graph-builder, #home-queries") == []
    assert browser.execute_script("return typeof GraphMineQueryWorkspace + ',' + typeof GraphMineGraphBuilder") == "undefined,undefined"
    edit(browser, "MATCH (n) RETURN n LIMIT $limit", '{"limit":5}')
    click(browser, "#preview-cypher")
    wait_for(browser, "document.getElementById('save-query-snapshot').disabled === false")
    assert browser.execute_script("return JSON.parse(editorQueries[0])")['parameters'] == {"limit": 5}
    assert browser.execute_script("return JSON.parse(editorQueries[0]).dataset_id") == "default"
    assert browser.execute_script("return document.getElementById('database-workspace').scrollWidth <= document.getElementById('database-workspace').clientWidth")
