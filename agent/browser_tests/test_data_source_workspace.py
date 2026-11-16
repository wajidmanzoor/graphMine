"""Live SQL/Neo4j checks for the unified source picker and query editing."""

import json
import os
from urllib.parse import urlsplit, unquote

import pytest
import httpx
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
import test_database_roundtrip as fixtures

loading_browser = fixtures.loading_browser
database_server = fixtures.database_server
click, wait, screenshot = fixtures.click, fixtures.wait, fixtures.screenshot
pytestmark = fixtures.pytestmark


def open_source(browser, server):
    browser.get(server.url)
    browser.execute_script("localStorage.setItem('graphmine.apiToken', 'test-secret')")
    browser.refresh()
    wait(browser, "GraphMineWorkspace.state.caps && !GraphMineWorkspace.state.busy")
    click(browser, "nav-database")
    wait(browser, "document.querySelectorAll('#database-health [data-state=connected]').length===2")


def open_benchmark(browser, server, identifier):
    if os.environ.get("GRAPHMINE_TEST_BENCHMARK_INTEGRATION") != "1":
        pytest.skip("requires verified local benchmark instances")
    browser.get(server.url)
    browser.execute_script("localStorage.setItem('graphmine.apiToken', 'test-secret')")
    browser.refresh()
    wait(browser, "GraphMineWorkspace.state.caps && !GraphMineWorkspace.state.busy")
    click(browser, "nav-database")
    wait(browser, f"document.querySelector('#database-source option[value=benchmark-{identifier}]') !== null && !document.getElementById('database-source').disabled")
    Select(browser.find_element(By.ID, "database-source")).select_by_value("benchmark-" + identifier)
    wait(browser, f"document.getElementById('database-dataset').value === {json.dumps(identifier)} && !document.getElementById('preview-cypher').disabled")


@pytest.mark.parametrize("width,height", [(1440, 1050), (390, 844)])
def test_source_layout_connection_checks_and_upload(loading_browser, database_server, width, height):
    browser = loading_browser
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": height})
    # On mobile the home card provides the same source picker.
    browser.get(database_server.url)
    browser.execute_script("localStorage.setItem('graphmine.apiToken', 'test-secret')")
    browser.refresh()
    wait(browser, "GraphMineWorkspace.state.caps && !GraphMineWorkspace.state.busy")
    click(browser, "open-database-workspace")
    wait(browser, "document.querySelectorAll('#database-health [data-state=connected]').length===2")
    assert Select(browser.find_element(By.ID, "database-source")).first_selected_option.get_attribute("value") == "local-transfers"
    assert not browser.find_elements(By.ID, "open-connectors")
    assert browser.execute_script("""
      const d=document.getElementById('database-workspace'), r=d.getBoundingClientRect();
      return r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight
        && d.scrollWidth<=d.clientWidth;
    """)
    screenshot(browser, f"data-source-{width}.png")
    click(browser, "source-files-tab")
    assert browser.find_element(By.CSS_SELECTOR, ".source-upload-zone").is_displayed()
    assert not browser.find_element(By.ID, "source-database-panel").is_displayed()
    click(browser, "source-database-tab")
    if width <= 600:
        browser.find_element(By.CSS_SELECTOR, ".source-connection-details summary").click()
    click(browser, "add-connection")
    assert browser.find_element(By.ID, "connection-neo4j-uri").is_displayed()
    assert not browser.find_elements(By.ID, "connection-type")
    screenshot(browser, f"paired-connection-{width}.png")
    assert browser.execute_script("return document.getElementById('database-workspace').scrollWidth <= document.getElementById('database-workspace').clientWidth")


def test_query_reopens_in_current_chat_and_preserves_draft(loading_browser, database_server):
    browser = loading_browser
    open_source(browser, database_server)
    click(browser, "preview-cypher")
    wait(browser, "document.getElementById('database-preview-count').textContent.includes('8 nodes')")
    assert browser.find_element(By.ID, "query-domain").is_displayed()
    domain = Select(browser.find_element(By.ID, "query-domain"))
    domain.select_by_index(1)
    selected_domain = domain.first_selected_option.get_attribute("value")
    click(browser, "run-cypher-chat")
    wait(browser, "GraphMineWorkspace.state.session && GraphMineWorkspace.state.active && !document.getElementById('database-workspace')")
    session = browser.execute_script("return GraphMineWorkspace.state.session.id")
    original = browser.execute_script("return GraphMineWorkspace.state.active")
    assert browser.execute_script("return GraphMineWorkspace.state.session.domain_id") == selected_domain
    click(browser, "toggle-data")
    wait(browser, "document.getElementById('cypher-editor').value.includes('Account')")

    editor = browser.find_element(By.ID, "cypher-editor")
    editor.clear(); editor.send_keys("MATCH p=(a:Account)-[:TRANSFER]->(b:Account)\nRETURN p LIMIT 2")
    click(browser, "close-data-source")
    click(browser, "toggle-data")
    wait(browser, "document.getElementById('cypher-editor').value.includes('LIMIT 2')")
    click(browser, "preview-cypher")
    wait(browser, "document.getElementById('database-preview-count').textContent.includes('2 relationships')")
    params = browser.find_element(By.ID, "cypher-parameters")
    browser.find_element(By.CSS_SELECTOR, ".query-parameters summary").click()
    params.clear(); params.send_keys('{"limit": 2}')
    assert browser.find_element(By.ID, "database-preview-count").text == "No query run yet"
    assert not browser.find_element(By.ID, "source-continue").is_displayed()
    click(browser, "preview-cypher")
    wait(browser, "document.getElementById('database-preview-count').textContent.includes('2 relationships')")
    click(browser, "run-cypher-chat")
    wait(browser, "document.getElementById('database-workspace')===null")
    assert browser.execute_script("return GraphMineWorkspace.state.session.id") == session
    assert browser.execute_script("return GraphMineWorkspace.state.active") != original


def test_connect_and_save_local_database_pair(loading_browser, database_server):
    browser = loading_browser
    open_source(browser, database_server)
    click(browser, "add-connection")
    click(browser, "connection-use-sql")
    sql = urlsplit(os.environ["GRAPHMINE_DEMO_SQL_DSN"])
    values = {
        "connection-label": "Another local database",
        "connection-host": sql.hostname, "connection-port": str(sql.port),
        "connection-database": sql.path.lstrip("/"), "connection-username": unquote(sql.username),
        "connection-password": unquote(sql.password),
        "connection-neo4j-uri": "bolt://127.0.0.1:17687",
        "connection-neo4j-password": os.environ["GRAPHMINE_DEMO_NEO4J_PASSWORD"],
    }
    for identifier, value in values.items():
        field = browser.find_element(By.ID, identifier)
        field.clear(); field.send_keys(value)
    click(browser, "save-connection-settings")
    wait(browser, "document.getElementById('connection-editor')===null")
    assert Select(browser.find_element(By.ID, "database-source")).first_selected_option.text == "Another local database"
    wait(browser, "document.querySelectorAll('#database-health [data-state=connected]').length===2")
    click(browser, "edit-connection")
    wait(browser, "document.getElementById('connection-editor')!==null")
    assert browser.find_element(By.ID, "connection-password").get_attribute("value") == ""
    assert browser.find_element(By.ID, "connection-neo4j-password").get_attribute("value") == ""
    click(browser, "cancel-connection-settings")
    Select(browser.find_element(By.ID, "database-source")).select_by_value("local-transfers")
    wait(browser, "document.getElementById('cypher-editor').value.includes('Account')")


def test_source_loads_domains_when_home_is_still_initializing(loading_browser, database_server):
    browser = loading_browser
    browser.get(database_server.url)
    browser.execute_script("localStorage.setItem('graphmine.apiToken', 'test-secret')")
    browser.refresh()
    wait(browser, "GraphMineWorkspace.state.caps && !GraphMineWorkspace.state.busy")
    browser.execute_script("GraphMineWorkspace.state.domains=[]")
    click(browser, "open-database-workspace")
    wait(browser, "document.querySelector('#query-domain option[value=general]') !== null")
    assert Select(browser.find_element(By.ID, "query-domain")).first_selected_option.get_attribute("value") == "general"
    click(browser, "source-files-tab")
    assert Select(browser.find_element(By.ID, "file-domain")).first_selected_option.get_attribute("value") == "general"


def test_movielens_shared_movies_projection_opens_in_chat(loading_browser, database_server):
    """Run the actual sample against MovieLens, save it and reopen its settings."""
    if os.environ.get("GRAPHMINE_TEST_BENCHMARK_INTEGRATION") != "1":
        pytest.skip("requires the completed local benchmark graph import")
    browser = loading_browser
    open_benchmark(browser, database_server, "movielens-32m")
    wait(browser, "document.getElementById('preview-cypher').disabled === false")
    click(browser, "query-shared-movies")
    click(browser, "preview-cypher")
    wait(browser, "document.getElementById('source-continue').hidden === false")
    count = browser.find_element(By.ID, "database-preview-count").text
    assert "4,437 rows" in count and "100 nodes" in count and "4,437 relationships" in count
    screenshot(browser, "movielens-shared-movies-projection.png")
    click(browser, "run-cypher-chat")
    wait(browser, "GraphMineWorkspace.state.active && !document.getElementById('database-workspace')")
    file_id = browser.execute_script("return GraphMineWorkspace.state.active")
    runtime = database_server.app.state.runtime
    file = runtime.database.get_file(file_id)
    graph = json.loads(runtime.graph_store.execution_path(file.id, file.session_id).read_text())
    assert len(graph["vertices"]) == 100 and len(graph["edges"]) == 4437
    assert graph["graph"]["directed"] is False
    assert all(edge["weight"] >= 1 and edge["type"] == "SHARED_MOVIE" for edge in graph["edges"])
    provenance = file.provenance["source"]
    assert provenance["projection"] == "rows"
    assert provenance["lineage"] == {"vertices": {}, "edges": {}}
    assert provenance["database_dataset"]["registry"] is True
    click(browser, "toggle-data")
    wait(browser, "document.getElementById('query-graph-projection')?.value === 'rows'")
    assert Select(browser.find_element(By.ID, "query-graph-direction")).first_selected_option.get_attribute("value") == "undirected"
    assert "AS source" in browser.find_element(By.ID, "cypher-editor").get_attribute("value")


@pytest.mark.parametrize("dataset", [
    "yelp", "movielens-32m", "movielens-genome", "ontime", "ldbc-snb",
])
def test_imported_dataset_preview_and_chat(loading_browser, database_server, dataset):
    """Opt in after the large benchmark import has completed."""
    if os.environ.get("GRAPHMINE_TEST_BENCHMARK_INTEGRATION") != "1":
        pytest.skip("requires the completed local benchmark graph import")
    browser = loading_browser
    open_benchmark(browser, database_server, dataset)
    wait(browser, "document.getElementById('preview-cypher').disabled === false")
    wait(browser, "document.getElementById('benchmark-schema-image')?.naturalWidth > 0")
    assert browser.find_element(By.CSS_SELECTOR, "a.benchmark-attribution[href*='/workloads/']").is_displayed()
    editor = browser.find_element(By.ID, "cypher-editor")
    query = editor.get_attribute("value").replace("LIMIT 1000", "LIMIT 10")
    editor.clear()
    editor.send_keys(query)
    click(browser, "preview-cypher")
    wait(browser, "document.getElementById('source-continue').hidden === false")
    assert "10 relationships" in browser.find_element(By.ID, "database-preview-count").text
    screenshot(browser, f"dataset-preview-{dataset}.png")
    click(browser, "run-cypher-chat")
    wait(browser, "GraphMineWorkspace.state.active && !document.getElementById('database-workspace')")
    assert browser.execute_script(
        "return GraphMineWorkspace.state.files.find(f=>f.id===GraphMineWorkspace.state.active)"
        ".provenance.source.database_dataset.id"
    ) == dataset
    assert browser.execute_script("return GraphMineWorkspace.state.session.domain_id") == "general"
    file = browser.execute_script("return GraphMineWorkspace.state.files.find(f=>f.id===GraphMineWorkspace.state.active)")
    provenance = file["provenance"]["source"]
    assert provenance["lineage"] == {"vertices": {}, "edges": {}}
    assert provenance["database_dataset"]["script_hashes"]
    assert provenance["database_source"]["capabilities"]["enrichment"] is False
    with httpx.Client(base_url=database_server.url, headers={"Authorization": "Bearer test-secret"}, timeout=60) as client:
        response = client.get(f"/api/files/{file['id']}/source-schema")
        assert response.status_code == 200, response.text
        assert response.json()["entities"] == []
        response = client.post(f"/api/files/{file['id']}/enrichments", json={
            "mapping": "unavailable", "kind": "vertices", "fields": ["name"],
        })
        assert response.status_code == 409 and response.json()["error"]["code"] == "sql_unavailable"


def test_successive_attribute_fetches_save_the_union_in_one_version(loading_browser, database_server):
    browser = loading_browser
    open_source(browser, database_server)
    Select(browser.find_element(By.ID, "query-graph-direction")).select_by_value("undirected")
    click(browser, "preview-cypher")
    wait(browser, "document.getElementById('source-continue').hidden === false")
    click(browser, "run-cypher-chat")
    wait(browser, "GraphMineWorkspace.state.active && !document.getElementById('database-workspace')")
    browser.execute_script("document.getElementById('device').value='cpu'; document.getElementById('device').dispatchEvent(new Event('change', {bubbles:true}))")
    browser.find_element(By.ID, "question").send_keys("Find the densest subgraph.")
    click(browser, "plan-question")
    wait(browser, "GraphMineWorkspace.state.record?.status==='completed' && GraphMineWorkspace.state.resultView?.graph_available && GraphMineWorkspace.state.cy?.nodes().length")
    click(browser, "enrich-attributes")
    wait(browser, "document.getElementById('enrichment-dialog')?.open")
    for attribute in ["risk_score", "country"]:
        before = browser.execute_script("return GraphMineWorkspace.state.files.length")
        browser.execute_script("""
          for (const input of document.querySelectorAll('#enrichment-fields input'))
            input.checked = input.value === arguments[0];
        """, attribute)
        click(browser, "apply-enrichment")
        wait(browser, f"GraphMineWorkspace.state.files.length > {before} && !GraphMineWorkspace.state.busy")
        assert len(browser.find_elements(By.ID, "use-enriched-graph")) == 1
    file = browser.execute_script("return GraphMineWorkspace.state.files.at(-1)")
    graph = json.loads(database_server.app.state.runtime.graph_store.execution_path(file["id"], file["session_id"]).read_text())
    assert all({"risk_score", "country"}.issubset(v.get("attributes", {})) for v in graph["vertices"])
    click(browser, "use-enriched-graph")
    wait(browser, f"GraphMineWorkspace.state.active === {json.dumps(file['id'])} && !document.getElementById('enrichment-dialog')")


def test_benchmark_expansion_is_unavailable_and_query_identity_is_stable(database_server):
    if os.environ.get("GRAPHMINE_TEST_BENCHMARK_INTEGRATION") != "1":
        pytest.skip("requires verified local benchmark instances")
    with httpx.Client(base_url=database_server.url, headers={"Authorization": "Bearer test-secret"}, timeout=60) as client:
        endpoint = "/api/database-sources/benchmark-movielens-genome/queries"
        query = client.post(endpoint, json={"dataset_id": "movielens-genome",
            "statement": "MATCH (n:Director)-[:DIRECTED]->(:Movie) RETURN n LIMIT 1"})
        assert query.status_code == 201, query.text
        node = query.json()["graph"]["vertices"][0]
        opened = client.post(f"/api/database-query-snapshots/{query.json()['dataset']['id']}/chat", json={})
        assert opened.status_code == 201, opened.text
        response = client.post(f"/api/files/{opened.json()['file']['id']}/expansions", json={"mapping": "directed"})
        assert response.status_code == 409 and response.json()["error"]["code"] == "sql_unavailable"
        queried = client.post(endpoint, json={"dataset_id": "movielens-genome", "parameters": {"name": node["attributes"]["name"]},
            "statement": "MATCH p=(n:Director {name:$name})-[:DIRECTED]->(:Movie) RETURN p LIMIT 3"})
        assert queried.status_code == 201, queried.text
        assert node["id"] in {v["id"] for v in queried.json()["graph"]["vertices"]}


def test_published_schemas_change_with_dataset_and_platform(loading_browser, database_server):
    browser = loading_browser
    open_benchmark(browser, database_server, "yelp")
    assert not browser.find_elements(By.ID, "source-datasets-tab")
    for identifier, title in [("yelp", "Yelp"), ("movielens-32m", "MovieLens 32M"), ("ldbc-snb", "LDBC SNB")]:
        Select(browser.find_element(By.ID, "database-source")).select_by_value("benchmark-" + identifier)
        wait(browser, f"document.getElementById('benchmark-schema-image').alt.startsWith({json.dumps(title)}) && document.getElementById('benchmark-schema-image').naturalWidth>0")
        assert browser.find_element(By.ID, "download-benchmark-schema").is_enabled()
        screenshot(browser, f"schema-{identifier}.png")
    Select(browser.find_element(By.ID, "benchmark-schema-platform")).select_by_visible_text("TigerGraph")
    wait(browser, "document.getElementById('benchmark-schema-image').alt.includes('TigerGraph') && document.getElementById('benchmark-schema-image').naturalWidth>0")
    click(browser, "zoom-benchmark-schema")
    assert browser.find_element(By.ID, "zoom-benchmark-schema").get_attribute("aria-pressed") == "true"
