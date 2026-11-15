"""Independent source choices remain usable without SQL and on narrow screens."""

import json
from threading import Event
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from test_workspace_loading import loading_browser, loading_server, wait_for  # noqa: F401


@pytest.fixture
def independent_sources(loading_server):
    server = loading_server; server.responses[0].release.set()
    native = {'id': 'graph', 'name': 'Independent graph', 'managed': True, 'sql_type': None, 'entities': [], 'relationships': [],
              'connection': {'sql': None, 'neo4j': {'uri': 'bolt://graph.example.com', 'database': 'neo4j', 'username': 'reader'}},
              'capabilities': {'cypher': True, 'sql': False, 'enrichment': False, 'expansion': False, 'sync': False}}
    state = SimpleNamespace(native=native, created=[], previews=[], unavailable_sql=False, include_connector=True, warnings=[], discovery=None)
    def route(handler, method):
        path = urlsplit(handler.path).path
        if method == 'GET' and path == '/api/data-sources':
            if state.discovery:
                state.discovery.started.set(); state.discovery.release.wait(10)
            entries = [{'provider': 'database', 'connection': native}]
            if state.include_connector:
                entries.append({'id': 'connector:api', 'source_id': 'api', 'provider': 'connector', 'name': 'REST source', 'type': 'rest', 'managed': True,
                                'capabilities': {'cypher': False, 'preview': True, 'import': True}})
            handler.respond({'items': entries, 'warnings': state.warnings, 'can_manage_imports': True}); return True
        if method == 'GET' and path.endswith('/datasets') and '/database-sources/' in path:
            handler.respond([{'id': 'default', 'name': 'Neo4j graph', 'status': 'ready', 'tables': [], 'schemas': [], 'default_query': 'MATCH (n) RETURN n LIMIT 10',
                              **({'discovery_warning': 'SQL dataset discovery is unavailable. You can still query Neo4j.'} if state.unavailable_sql else {})}]); return True
        if path.endswith('/status') and '/database-sources/' in path:
            handler.respond({'connected': not state.unavailable_sql, 'neo4j': {'connected': True}, 'sql': {'configured': bool(native['sql_type']), 'connected': False if state.unavailable_sql else None}}); return True
        if method == 'GET' and path.endswith('/settings'):
            handler.respond(native); return True
        if method in {'POST', 'PUT'} and (path == '/api/database-sources' or path == '/api/database-sources/graph'):
            body = json.loads(handler.rfile.read(int(handler.headers.get('Content-Length', 0)))); state.created.append(body)
            native.update(name=body['name'], sql_type='postgres' if body['sql_enabled'] else None)
            native['capabilities']['sql'] = body['sql_enabled']
            handler.respond({**native, 'status': {'connected': True, 'neo4j': {'connected': True}, 'sql': {'connected': body['sql_enabled']}}}, 201); return True
        if path == '/api/connectors/api/preview':
            state.previews.append(path)
            handler.respond({'name': 'REST source', 'sha256': 'a'*64, 'source_complete': False, 'source_scope': 'one API response',
                             'metadata': {'vertex_count': 3, 'edge_count': 2, 'directed': True},
                             'vertices': [{'id': 9007199254740993}, {'id': '001'}], 'edges': [{'id': 'edge', 'source': 9007199254740993, 'target': '001'}]}); return True
        return False
    server.route_handler = route
    return state


def open_sources(browser, server, width=1440):
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={'width': width, 'height': 950})
    browser.get(server.url + '/#data')
    wait_for(browser, "document.getElementById('preview-cypher')?.disabled === false")


def click(browser, identifier):
    element = browser.find_element(By.ID, identifier)
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", element); element.click()


@pytest.mark.parametrize('width,with_sql', [(1440, False), (320, False), (1440, True)])
def test_neo4j_form_only_requires_configured_services(loading_browser, loading_server, independent_sources, width, with_sql):
    browser = loading_browser; open_sources(browser, loading_server, width)
    click(browser, 'add-connection')
    assert not browser.find_element(By.ID, 'connection-use-sql').is_selected()
    assert not browser.find_element(By.ID, 'connection-host').is_displayed()
    browser.find_element(By.ID, 'connection-label').send_keys('My direct graph')
    browser.find_element(By.ID, 'connection-neo4j-uri').send_keys('bolt://graph.example.com')
    browser.find_element(By.ID, 'connection-neo4j-password').send_keys('private-graph')
    if with_sql:
        click(browser, 'connection-use-sql')
        for identifier, text in [('connection-host', 'sql.example.com'), ('connection-database', 'records'), ('connection-username', 'reader'), ('connection-password', 'private-sql')]:
            browser.find_element(By.ID, identifier).send_keys(text)
    assert browser.execute_script('return document.documentElement.scrollWidth <= innerWidth + 1')
    toggle = browser.find_element(By.ID, 'connection-use-sql')
    browser.execute_script("arguments[0].closest('label').scrollIntoView({block:'center'})", toggle)
    assert browser.execute_script("const label=arguments[0].closest('label'); return label.scrollWidth <= label.clientWidth + 1", toggle)
    browser.save_screenshot(f'/tmp/graphmine-independent-form-{width}-{with_sql}.png')
    click(browser, 'save-connection-settings')
    wait_for(browser, "!document.getElementById('connection-editor')")
    body = independent_sources.created[-1]
    assert body['sql_enabled'] is with_sql and body['neo4j_password'] == 'private-graph'
    assert ('host' in body) is with_sql and ('password' in body) is with_sql


def test_sql_outage_leaves_default_graph_and_cypher_available(loading_browser, loading_server, independent_sources):
    fixture = independent_sources; fixture.unavailable_sql = True
    fixture.native['sql_type'] = 'postgres'; fixture.native['capabilities']['sql'] = True
    open_sources(loading_browser, loading_server)
    assert loading_browser.find_element(By.ID, 'cypher-editor').is_enabled()
    assert loading_browser.find_element(By.ID, 'preview-cypher').is_enabled()
    assert 'SQL dataset discovery is unavailable' in loading_browser.find_element(By.ID, 'database-dataset-status').text
    wait_for(loading_browser, "document.querySelector('.source-connection-details summary').textContent.includes('Neo4j ready')")


@pytest.mark.parametrize('width', [1440, 320])
def test_rest_discovery_and_preview_have_import_controls_and_honest_scope(loading_browser, loading_server, independent_sources, width):
    browser = loading_browser; open_sources(browser, loading_server, width)
    Select(browser.find_element(By.ID, 'database-source')).select_by_value('connector:api')
    wait_for(browser, "document.getElementById('preview-cypher').textContent === 'Preview source'")
    assert not browser.find_element(By.ID, 'cypher-editor').is_displayed()
    assert not browser.find_element(By.CSS_SELECTOR, '.query-editor-tools').is_displayed()
    assert not browser.find_element(By.ID, 'sync-database').is_displayed()
    if width == 320: click(browser, 'data-step-query')
    # Load the deferred renderer before wrapping it for geometry assertions.
    assert browser.execute_async_script("const done = arguments[arguments.length - 1]; GraphMineGraphLibrary().then(() => done(null), error => done(error.message));") is None
    browser.execute_script("""
        const create = window.cytoscape;
        window.cytoscape = options => {
          const bounds = options.container.getBoundingClientRect();
          window.importPreviewSize = {width: bounds.width, height: bounds.height};
          return window.importPreviewGraph = create(options);
        };
    """)
    click(browser, 'preview-cypher')
    wait_for(browser, "document.getElementById('database-preview-count').textContent.includes('3 vertices')")
    assert len(independent_sources.previews) == 1
    assert 'upstream may contain more' in browser.find_element(By.ID, 'database-query-status').text
    assert '2 vertices and 1 connections' in browser.find_element(By.ID, 'database-query-status').text
    assert browser.execute_script("return importPreviewSize.width > 200 && importPreviewSize.height > 100")
    assert browser.execute_script("""
        const cy=window.importPreviewGraph, bounds=cy.elements().renderedBoundingBox();
        return bounds.x1 >= -1 && bounds.y1 >= -1 && bounds.x2 <= cy.width()+1 && bounds.y2 <= cy.height()+1;
    """)
    browser.find_element(By.CSS_SELECTOR, '.query-rows summary').click()
    assert '9007199254740993' in browser.find_element(By.ID, 'database-query-rows').text
    assert browser.execute_script('return document.documentElement.scrollWidth <= innerWidth + 1')
    browser.save_screenshot(f'/tmp/graphmine-independent-preview-{width}.png')


def test_refresh_does_not_replace_a_removed_source_with_another_connection(loading_browser, loading_server, independent_sources):
    browser = loading_browser; open_sources(browser, loading_server)
    Select(browser.find_element(By.ID, 'database-source')).select_by_value('connector:api')
    wait_for(browser, "document.getElementById('preview-cypher').textContent === 'Preview source'")
    click(browser, 'preview-cypher')
    wait_for(browser, "!document.getElementById('run-cypher-chat').disabled")
    independent_sources.include_connector = False
    delay = independent_sources.discovery = SimpleNamespace(started=Event(), release=Event())
    try:
        click(browser, 'refresh-database-datasets')
        assert delay.started.wait(3)
        assert not browser.find_element(By.ID, 'database-source').is_enabled()
        assert not browser.find_element(By.ID, 'preview-cypher').is_enabled()
    finally:
        delay.release.set()
    wait_for(browser, "document.getElementById('database-source').value === ''")
    assert not browser.find_element(By.ID, 'preview-cypher').is_enabled()
    assert not browser.find_element(By.ID, 'run-cypher-chat').is_enabled()
    assert browser.find_element(By.ID, 'database-preview-count').text == 'No query run yet'


def test_partial_discovery_warns_without_blocking_available_graphs(loading_browser, loading_server, independent_sources):
    independent_sources.warnings = [{'provider': 'connector', 'message': 'Import connections could not be listed.'}]
    independent_sources.include_connector = False
    open_sources(loading_browser, loading_server)
    assert 'Import connections could not be listed.' in loading_browser.find_element(By.ID, 'source-discovery-warning').text
    assert loading_browser.find_element(By.ID, 'preview-cypher').is_enabled()


def test_connection_creation_waits_for_discovery_permissions(loading_browser, loading_server, independent_sources):
    browser = loading_browser
    delay = independent_sources.discovery = SimpleNamespace(started=Event(), release=Event())
    try:
        browser.get(loading_server.url + '/#data')
        assert delay.started.wait(3)
        assert not browser.find_element(By.ID, 'add-connection').is_enabled()
        delay.release.set()
        wait_for(browser, "document.getElementById('add-connection').disabled === false")
        click(browser, 'add-connection')
        Select(browser.find_element(By.ID, 'connection-type')).select_by_value('rest')
        assert browser.find_element(By.ID, 'connection-url').is_displayed()
    finally:
        delay.release.set()
