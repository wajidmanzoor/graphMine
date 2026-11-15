"""Query drafts survive reloads without crossing identity or source boundaries."""

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from test_query_previews import open_source_fixture
from test_workspace_loading import loading_browser, loading_server, wait_for


def edit(browser, statement, parameters='{"name":"Ada"}'):
    browser.execute_script("""
      const editor=document.getElementById('cypher-editor'); editor.value=arguments[0];
      document.getElementById('cypher-parameters').value=arguments[1];
      document.getElementById('query-graph-direction').value='undirected';
      document.getElementById('query-graph-projection').value='rows';
      editor.dispatchEvent(new Event('input', {bubbles:true}));
    """, statement, parameters)


def choose(browser, identifier, value):
    field = browser.find_element(By.ID, identifier)
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", field)
    Select(field).select_by_value(value)
    wait_for(browser, "document.getElementById('preview-cypher').disabled === false")


def test_draft_restores_after_reload_and_explicit_discard(loading_browser, loading_server):
    browser = loading_browser
    open_source_fixture(browser, loading_server)
    statement = "MATCH (a), (b) WHERE a.name=$name RETURN a AS source,b AS target"
    edit(browser, statement)
    assert browser.find_element(By.ID, "query-draft-status").text == "Draft saved in this browser."
    # A real document reload destroys the in-memory draft cache.
    open_source_fixture(browser, loading_server)
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("value") == statement
    assert browser.find_element(By.ID, "cypher-parameters").get_attribute("value") == '{"name":"Ada"}'
    assert Select(browser.find_element(By.ID, "query-graph-direction")).first_selected_option.get_attribute("value") == "undirected"
    assert Select(browser.find_element(By.ID, "query-graph-projection")).first_selected_option.get_attribute("value") == "rows"
    assert browser.find_element(By.ID, "query-draft-status").text == "Draft restored from this browser."
    discard = browser.find_element(By.ID, "discard-query-draft")
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", discard)
    discard.click()
    open_source_fixture(browser, loading_server)
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("value") == "MATCH (n) RETURN n LIMIT 10"
    assert not browser.find_element(By.ID, "discard-query-draft").is_enabled()


def test_switching_connections_and_datasets_restores_each_draft(loading_browser, loading_server):
    browser = loading_browser
    open_source_fixture(browser, loading_server, multiple=True)
    edit(browser, "RETURN 'first connection, first dataset'")
    choose(browser, "database-dataset", "second")
    edit(browser, "RETURN 'first connection, second dataset'")
    choose(browser, "database-source", "other-db")
    edit(browser, "RETURN 'other connection'")
    choose(browser, "database-source", "preview-db")
    assert Select(browser.find_element(By.ID, "database-dataset")).first_selected_option.get_attribute("value") == "second"
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("value") == "RETURN 'first connection, second dataset'"
    choose(browser, "database-dataset", "default")
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("value") == "RETURN 'first connection, first dataset'"


def test_draft_keys_isolate_identity_conversation_and_api(loading_browser, loading_server):
    browser = loading_browser
    open_source_fixture(browser, loading_server)
    result = browser.execute_async_script("""
      const done=arguments[arguments.length-1];
      (async () => {
        const context={userId:'alice',conversationId:'chat-a',inputId:'input-a'};
        const draft={query:'RETURN 42',parameters:'{}',direction:'directed',projection:'elements'};
        const alice=await GraphMineQueryDrafts(context); alice.put('db-a','dataset-a',draft);
        const contexts=[{...context,userId:'bob'}, {...context,conversationId:'chat-b'}, {...context,inputId:'input-b'}, {...context,base:'https://other.example'}];
        const isolated=await Promise.all(contexts.map(async context => (await GraphMineQueryDrafts(context)).get('db-a','dataset-a')));
        const token=await GraphMineQueryDrafts({token:'private-token-value'}); token.put('db-a','dataset-a',draft);
        const rotated=await GraphMineQueryDrafts({token:'different-token-value'});
        done({own:alice.get('db-a','dataset-a').query, isolated, source:alice.get('db-b','dataset-a'), dataset:alice.get('db-a','dataset-b'), token:rotated.get('db-a','dataset-a'), keys:Object.keys(localStorage).filter(key => key.startsWith('graphmine.queryDraft.'))});
      })().catch(error => done({error:String(error)}));
    """)
    assert result["own"] == "RETURN 42"
    assert result["isolated"] == [None] * 4
    assert result["source"] is result["dataset"] is result["token"] is None
    assert all("private-token-value" not in key for key in result["keys"])


def test_unavailable_storage_keeps_current_draft_and_reports_limit(loading_browser, loading_server):
    browser = loading_browser
    open_source_fixture(browser, loading_server)
    edit(browser, "RETURN 'saved'")
    browser.execute_script("Storage.prototype.setItem = () => { throw new DOMException('Full','QuotaExceededError'); }")
    edit(browser, "RETURN 'latest edit'")
    assert "this tab only" in browser.find_element(By.ID, "query-draft-status").text
    close = browser.find_element(By.ID, "close-data-source")
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", close)
    close.click()
    browser.find_element(By.ID, "open-database-workspace").click()
    wait_for(browser, "document.getElementById('preview-cypher')?.disabled === false")
    assert browser.find_element(By.ID, "cypher-editor").get_attribute("value") == "RETURN 'latest edit'"
    assert "this tab only" in browser.find_element(By.ID, "query-draft-status").text
