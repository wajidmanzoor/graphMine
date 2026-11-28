"""The curated picker presents every named IU database and scopes previews."""

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from test_workspace_loading import loading_browser, loading_server, wait_for


@pytest.mark.parametrize("width", [1440, 390])
def test_iu_database_choices_and_query_scope(loading_browser, loading_server, width):
    browser = loading_browser
    browser.set_window_size(width, 1000)
    loading_server.responses[0].release.set()
    browser.get(loading_server.url)
    wait_for(browser, "window.GraphMineWorkspace?.state.caps && !GraphMineWorkspace.state.busy")
    browser.execute_script(r"""
      const original=window.fetch;
      const names={amazon:'Amazon',fars:'FARS','fars20-22':'FARS 20–22',ml32m:'MovieLens 32M',
        mlgenome:'MovieLens Genome',remote:'Neo4j',ontime:'OnTime',snb100:'LDBC SNB (snb100)',stackof:'Stack Overflow',yelp:'Yelp'};
      const sources=Object.entries(names).map(([id,name])=>({id:'iu-'+id,name,backend_id:'iu-remote',entities:[],relationships:[],capabilities:{cypher:true,sync:false}}));
      const reply=data=>Promise.resolve(new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}}));
      window.iuQueries=[];
      window.fetch=(path,options={})=>{
        if(path==='/api/data-sources')return reply({active_backend:'iu-remote',dataset_picker_only:true,warnings:[],items:sources.map(s=>({provider:'database',connection:s}))});
        const match=path.match(/^\/api\/database-sources\/(iu-[^/]+)\/(\w+)/);
        if(match){
          const source=sources.find(s=>s.id===match[1]);
          if(['status','open'].includes(match[2]))return reply({neo4j:{connected:true},connected:true});
          if(match[2]==='datasets')return reply([{id:'default',name:source.name,status:'ready',schemas:[],tables:[],default_query:'MATCH (n) RETURN n LIMIT 1'}]);
          if(match[2]==='schema')return reply({entities:[],relationships:[],mapping_hash:source.id});
          if(match[2]==='jobs')return reply([]);
          if(match[2]==='queries'){
            window.iuQueries.push({source_id:source.id,...JSON.parse(options.body)});
            return reply({dataset:{id:'preview-'+iuQueries.length,temporary:true},row_count:1,rows:[],vertex_count:1,edge_count:0,graph:{graph:{directed:true},vertices:[{id:1,label:source.name}],edges:[]}});
          }
        }
        return original(path,options);
      };
    """)
    browser.find_element(By.ID, "open-database-workspace").click()
    wait_for(browser, "document.getElementById('database-source')?.options.length===10 && !document.getElementById('preview-cypher').disabled")
    picker = browser.find_element(By.ID, "database-source")
    assert picker.get_attribute("aria-label") == "Dataset"
    labels = [o.text for o in Select(picker).options]
    assert "Yelp" in labels and "Amazon" in labels and "system" not in labels
    assert not browser.find_element(By.ID, "database-dataset").is_displayed()
    for database in ["yelp", "amazon"]:
        Select(picker).select_by_value("iu-" + database)
        wait_for(browser, "document.getElementById('database-query-scope').textContent === 'Queries run only on " + database.title() + ".' && !document.getElementById('preview-cypher').disabled")
        if browser.find_element(By.ID, "data-step-query").is_displayed():
            browser.find_element(By.ID, "data-step-query").click()
        preview = browser.find_element(By.ID, "preview-cypher")
        browser.execute_script("arguments[0].scrollIntoView({block:'center'})", preview)
        preview.click()
        wait_for(browser, "document.getElementById('save-query-snapshot').disabled === false")
        assert browser.execute_script("return iuQueries.at(-1).source_id") == "iu-" + database
        assert browser.execute_script("return iuQueries.at(-1).dataset_id") == "default"
