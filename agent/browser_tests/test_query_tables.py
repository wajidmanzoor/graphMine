"""Full query table paging, downloads, lifecycle and graph-mapping handoff."""

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from workspace_browser_helpers import click
from test_query_previews import open_source_fixture
from test_workspace_loading import loading_browser, loading_server, wait_for
from test_workspace_navigation import navigate


def table_fixture(browser, server):
    open_source_fixture(browser, server)
    browser.execute_script(r"""
      const previous = window.fetch;
      const reply = (data,status=200) => Promise.resolve(new Response(AnalyticsWire.stringify(data),{status,headers:{'Content-Type':'application/json'}}));
      const columns = [{name:'source',type:'integer',nullable:false},{name:'target',type:'string',nullable:false},{name:'amount',type:'number',nullable:false},{name:'label',type:'string',nullable:false}];
      window.queryTableCalls=0; window.tableCount=125; window.tableReads=[]; window.tableSaved=false; window.slowTable=false; window.tableDownloads=[];
      const meta = (id='table-'+window.queryTableCalls) => ({id,name:'Query table',kind:'table',version:1,temporary:!window.tableSaved,source_complete:true,sha256:'table-hash',size_bytes:1234,source:{query:'RETURN source, target, amount'},table:{columns,row_count:window.tableCount}});
      const tableRows = id => Array.from({length:window.tableCount},(_,index)=>({source:9007199254740993n+BigInt(index),target:String(index).padStart(3,'0'),amount:index+.5,label:id+' row '+index}));
      const file = id => ({id,session_id:'saved-session',role:'attachment',original_name:'query-table-v1.json',size_bytes:1234,provenance:{kind:'table',version_id:'table-'+window.queryTableCalls},metadata:null});
      const nativeClick = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function() { if(this.download) tableDownloads.push(this.download); else nativeClick.call(this); };
      window.fetch = (path,options={}) => {
        const url = new URL(path,location.href);
        if (url.pathname.endsWith('/preview-db/queries')) {
          window.queryTableCalls++; const rows=tableRows('table-'+window.queryTableCalls);
          return reply({dataset:null,table:meta(),row_count:window.tableCount,rows:rows.slice(0,50),rows_truncated:window.tableCount>50,
            vertex_count:0,edge_count:0,elapsed_ms:2,message:'Complete table ready.',graph:{graph:{directed:true},vertices:[],edges:[]}});
        }
        if (url.pathname === '/api/datasets') return reply(window.tableSaved ? [meta()] : []);
        if (url.pathname === '/api/datasets/page') return reply({items:window.tableSaved ? [meta()] : [],offset:0,limit:20,has_more:false});
        if (url.pathname.startsWith('/api/database-query-snapshots/')) {
          const id=url.pathname.split('/')[3]; tableReads.push(url.pathname+url.search);
          if (url.pathname.endsWith('/save')) { window.tableSaved=true; const saved=meta(id); delete saved.temporary; return reply(saved); }
          if (url.pathname.endsWith('/chat')) { window.tableSaved=true; return reply({session:{id:'saved-session',domain_id:'general',title:'Table analysis'},file:file('table-file'),kind:'table'}); }
          if (options.method==='DELETE') return Promise.resolve(new Response(null,{status:204}));
          if (/\/table\/(csv|json)$/.test(url.pathname)) return Promise.resolve(new Response('source,target\n9007199254740993,000\n',{headers:{'Content-Type':'text/csv'}}));
          if (url.pathname.endsWith('/table')) {
            const offset=Number(url.searchParams.get('offset')||0), rows=tableRows(id);
            if (url.searchParams.get('direction')==='desc') rows.reverse();
            const data={columns,rows:rows.slice(offset,offset+50),row_count:window.tableCount,offset,limit:50,has_more:offset+50<window.tableCount,complete:true,sha256:'table-hash'};
            return window.slowTable && offset===50 ? new Promise(resolve=>{window.releaseTable=()=>resolve(reply(data));}) : reply(data);
          }
        }
        if (/\/sessions\/saved-session\/datasets\/.+\/import$/.test(url.pathname)) { window.tableSaved=true; return reply({file:file('added-table'),kind:'table'}); }
        if (/\/tables\/(table-file|added-table)\/schema$/.test(url.pathname)) return reply({columns,row_count:window.tableCount,sample:tableRows('table-'+window.queryTableCalls).slice(0,8)});
        if (url.pathname==='/api/sessions/saved-session/workspace' && window.tableSaved) {
          return previous(path,options).then(response=>response.json()).then(workspace=>reply({...workspace,files:[file('table-file')]}));
        }
        return previous(path,options);
      };
    """)


def preview(browser):
    click(browser, "#preview-cypher")
    wait_for(browser, "document.querySelector('#database-query-table tbody tr') !== null || window.tableCount===0 && document.querySelector('#database-query-table caption')?.textContent.includes('0 rows')")


@pytest.mark.parametrize("width", [1440, 320])
def test_complete_table_pages_sorts_exports_and_saves_without_rerunning(loading_browser, loading_server, width):
    browser = loading_browser
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width":width,"height":900})
    table_fixture(browser, loading_server); preview(browser)
    first = browser.find_element(By.CSS_SELECTOR, "#database-query-table tbody td").text
    assert first == "9007199254740993"
    assert not browser.find_element(By.ID, "database-query-graph").is_displayed()
    click(browser, "#database-query-table [data-table-action=next]")
    wait_for(browser, "document.querySelector('#database-query-table .query-table-pages').textContent.includes('51–100')")
    click(browser, "#database-query-table [data-table-action=next]")
    wait_for(browser, "document.querySelector('#database-query-table .query-table-pages').textContent.includes('101–125')")
    assert len(browser.find_elements(By.CSS_SELECTOR, "#database-query-table tbody tr")) == 25
    sort = click(browser, '#database-query-table select[aria-label="Sort complete query table by"]')
    Select(sort).select_by_value("amount")
    wait_for(browser, "!document.querySelector('#database-query-table [data-table-action=next]').disabled")
    order = click(browser, '#database-query-table select[aria-label="Table sort direction"]')
    Select(order).select_by_value("desc")
    wait_for(browser, "document.querySelector('#database-query-table tbody td').textContent==='9007199254741117'")
    click(browser, "#database-query-table [data-table-action=csv]")
    wait_for(browser, "tableDownloads.length===1")
    assert browser.execute_script("return tableReads.some(path=>path.includes('/table/csv?sort=amount&direction=desc'))")
    click(browser, "#save-query-snapshot")
    wait_for(browser, "document.getElementById('save-query-snapshot').textContent==='Saved in datasets'")
    assert browser.execute_script("return queryTableCalls") == 1
    assert not browser.find_element(By.ID, "discard-query-preview").is_displayed()
    assert browser.execute_script("return document.getElementById('database-workspace').scrollWidth <= document.getElementById('database-workspace').clientWidth")


def test_table_handoff_opens_mapping_and_saved_library_view(loading_browser, loading_server):
    browser = loading_browser
    table_fixture(browser, loading_server); preview(browser)
    click(browser, "#run-cypher-chat")
    wait_for(browser, "document.getElementById('projection-dialog').open && document.getElementById('projection-source').options.length===5")
    assert browser.execute_script("return GraphMineWorkspace.state.active") == ""
    assert browser.execute_script("return GraphMineWorkspace.state.kinds['table-file']") == "table"
    Select(browser.find_element(By.ID, "projection-source")).select_by_value("source")
    Select(browser.find_element(By.ID, "projection-target")).select_by_value("target")
    assert browser.find_element(By.ID, "projection-source-type").get_attribute("value") == "integer"
    assert browser.find_element(By.ID, "projection-target-type").get_attribute("value") == "string"
    click(browser, '#projection-dialog [data-close="projection-dialog"]')
    assert browser.find_element(By.ID, "welcome-heading").text == "Your table is ready."
    click(browser, "#welcome-data")
    wait_for(browser, "document.getElementById('projection-dialog').open")
    click(browser, '#projection-dialog [data-close="projection-dialog"]')
    # Open the library through its existing data controls.
    click(browser, "#composer-data")
    wait_for(browser, "document.getElementById('database-workspace')?.isConnected")
    click(browser, "#source-files-tab")
    click(browser, "#open-datasets")
    wait_for(browser, "document.querySelector('[data-view-table]') !== null")
    click(browser, "[data-view-table]")
    wait_for(browser, "document.querySelector('dialog[aria-label=\"Saved query table\"] tbody tr') !== null")
    assert len(browser.find_elements(By.CSS_SELECTOR, 'dialog[aria-label="Saved query table"] tbody tr')) == 50
    assert browser.execute_script("return queryTableCalls") == 1
    browser.execute_script("document.getElementById('dataset-dialog').close()")
    wait_for(browser, "document.querySelector('dialog[aria-label=\"Saved query table\"]')===null")


def test_table_import_preserves_existing_graph_and_analysis(loading_browser, loading_server):
    browser = loading_browser
    loading_server.files = [{"id":"existing-graph","role":"graph","original_name":"existing.json","metadata":{"vertex_count":1,"edge_count":0},"provenance":{}}]
    table_fixture(browser, loading_server)
    click(browser, "#close-data-source")
    navigate(browser, "saved-session")
    wait_for(browser, "GraphMineWorkspace.state.active==='existing-graph'")
    browser.execute_script("GraphMineWorkspace.state.record={id:'keep-analysis'}")
    click(browser, "#composer-data")
    wait_for(browser, "document.getElementById('preview-cypher')?.disabled===false")
    preview(browser); click(browser, "#run-cypher-chat")
    wait_for(browser, "document.getElementById('projection-dialog').open")
    assert browser.execute_script("return GraphMineWorkspace.state.active") == "existing-graph"
    assert browser.execute_script("return GraphMineWorkspace.state.record.id") == "keep-analysis"
    assert browser.find_element(By.ID, "input-aliases").get_attribute("textContent") == "main: graph"


def test_old_table_page_cannot_replace_new_query(loading_browser, loading_server):
    browser = loading_browser
    table_fixture(browser, loading_server); preview(browser)
    browser.execute_script("window.slowTable=true")
    click(browser, "#database-query-table [data-table-action=next]")
    wait_for(browser, "Boolean(window.releaseTable)")
    browser.execute_script("window.slowTable=false; const e=document.getElementById('cypher-editor'); e.value='RETURN 2'; e.dispatchEvent(new Event('input',{bubbles:true}))")
    preview(browser)
    browser.execute_script("window.releaseTable()")
    browser.execute_async_script("setTimeout(arguments[arguments.length-1],100)")
    assert "table-2 row 0" in browser.find_element(By.CSS_SELECTOR, "#database-query-table tbody tr").text
    assert "table-1 row 50" not in browser.find_element(By.CSS_SELECTOR, "#database-query-table tbody").text


def test_empty_table_has_headers_and_discard_removes_it(loading_browser, loading_server):
    browser = loading_browser
    table_fixture(browser, loading_server)
    browser.execute_script("window.tableCount=0")
    preview(browser)
    assert len(browser.find_elements(By.CSS_SELECTOR, "#database-query-table th")) == 4
    assert browser.find_element(By.ID, "run-cypher-chat").get_attribute("disabled")
    assert not browser.find_element(By.CSS_SELECTOR, "#database-query-table [data-table-action=csv]").get_attribute("disabled")
    click(browser, "#discard-query-preview")
    wait_for(browser, "document.getElementById('database-query-status').textContent.includes('Preview discarded')")
    assert not browser.find_element(By.CSS_SELECTOR, "#database-query-table .query-table-view").is_displayed()


def test_projection_uses_latest_table_when_previous_schema_is_delayed(loading_browser, loading_server):
    browser = loading_browser
    loading_server.files = [{"id":identifier,"role":"attachment","original_name":identifier+".json","metadata":None,"provenance":{"kind":"table"}} for identifier in ("table-file", "added-table")]
    table_fixture(browser, loading_server)
    click(browser, "#close-data-source")
    navigate(browser, "saved-session")
    wait_for(browser, "document.getElementById('welcome-data').dataset.action==='projection'")
    browser.execute_script("""
      const previous=window.fetch;
      const reply=columns=>Promise.resolve(new Response(JSON.stringify({columns:columns.map(name=>({name,type:'integer'})),row_count:1}),{headers:{'Content-Type':'application/json'}}));
      window.fetch=(path,options)=>{
        if(path.endsWith('/table-file/schema')) return new Promise(resolve=>{window.releaseSchema=()=>resolve(reply(['old-source','old-target']));});
        if(path.endsWith('/added-table/schema')) return reply(['new-source','new-target']);
        return previous(path,options);
      };
    """)
    click(browser, "#welcome-data")
    wait_for(browser, "Boolean(window.releaseSchema)")
    Select(browser.find_element(By.ID, "projection-table")).select_by_value("table_2")
    wait_for(browser, "document.getElementById('projection-source').textContent.includes('new-source')")
    browser.execute_script("window.releaseSchema()")
    browser.execute_async_script("setTimeout(arguments[arguments.length-1],100)")
    assert "old-source" not in browser.find_element(By.ID, "projection-source").text
