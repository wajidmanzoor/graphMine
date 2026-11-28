"""One query, real native model HTTP, graph attributes and responsive workspace."""
import json
import re
from dataclasses import replace

import pytest
from neo4j import Record
from neo4j.graph import Graph, Node

from agent.tests.conftest import fake_binary, settings as base_settings  # noqa: F401
from agent.tests.test_admin_browser import browser_app, sign_in, screenshot, pw  # noqa: F401
from agent.tests.test_semantic_native import native_engine  # noqa: F401
from agent.tests.semantic_provider_fixture import provider
from agent.tests.test_database_query_projection import read_transaction
from graphmine_agent.database_sources import DatabaseSource

QUERY = "MATCH (r:Review)-[e:REVIEWS]->(b:Business)\nSET r.summary=llm('qwen','Summarize {{r.text}} {answer STRING}')\nRETURN r,e,b LIMIT 10"

@pytest.fixture
def model_server():
    with provider() as value:
        yield value

@pytest.fixture
def settings(base_settings, tmp_path, model_server):
    path = tmp_path / 'sources.json'
    source = DatabaseSource(id='demo', name='Yelp', users=['*'], neo4j_uri='bolt://127.0.0.1:17687', neo4j_password_env='BROWSER_TEST_PASSWORD')
    path.write_text(json.dumps([source.model_dump()])); path.chmod(0o600)
    return replace(base_settings, database_sources_file=path, semantic_mode='live', llm_base_url=model_server[0], llm_model='fixture-model')

@pytest.fixture
def query_page(browser_app, monkeypatch, model_server, native_engine):
    browser, base, _, _ = browser_app
    g = Graph(); r = Node(g,'r',1,{'Review'},{'text':'Great food'}); b=Node(g,'b',2,{'Business'},{'name':'Cafe'})
    e=g.relationship_type('REVIEWS')(g,'e',3,{}); e._start_node=r; e._end_node=b
    read_transaction(monkeypatch, [Record({'r':r,'e':e,'b':b,'__gm_input_0_0':'Great food'})])
    page = browser.new_page(viewport={'width':1440,'height':1050}, reduced_motion='reduce')
    errors=[]; page.on('pageerror', lambda error: errors.append(str(error)))
    sign_in(page,base,'review-admin')
    source={'id':'demo','name':'Yelp','entities':[],'relationships':[],'capabilities':{'sync':False},'connection':{'neo4j':{}}}
    page.route('**/api/data-sources', lambda route: route.fulfill(json={'items':[{'provider':'database','connection':source}], 'warnings':[], 'active_backend':'local','dataset_picker_only':True}))
    for endpoint in ('status','open'):
        page.route('**/api/database-sources/demo/'+endpoint, lambda route: route.fulfill(json={'neo4j':{'connected':True}}))
    page.route('**/api/database-sources/demo/schema?*', lambda route: route.fulfill(json={
        'entities':[{'id':'review','label':'Review','properties':[{'name':'text','type':'STRING'}]}, {'id':'business','label':'Business','properties':[{'name':'name','type':'STRING'}]}],
        'relationships':[{'id':'edge','label':'REVIEWS','source_entity':'review','target_entity':'business','properties':[]}], 'message':'Property sample.'}))
    page.goto(base+'/'); page.wait_for_function('() => window.GraphMineWorkspace?.state.domains.length && !GraphMineWorkspace.state.busy')
    page.locator('#open-database-workspace').click(); pw.expect(page.locator('#preview-cypher')).to_be_enabled()
    page.locator('#cypher-editor').fill(QUERY)
    yield page,base,model_server[1],errors
    assert errors == []
    page.close()

def run(page):
    with page.expect_response(re.compile(r'/api/database-jobs/[^/]+/result$'), timeout=30000) as response:
        page.locator('#preview-cypher').click()
    value=response.value
    assert value.ok, value.text()
    pw.expect(page.locator('#preview-cypher')).to_be_enabled()
    return value.json()


def test_single_query_node_attributes_layouts_save_and_fresh_rerun(query_page):
    page,base,calls,_=query_page
    pw.expect(page.get_by_role('button',name='Refine with model')).to_have_count(0)
    left=page.locator('#data-query-pane').bounding_box(); right=page.locator('#data-preview-pane').bounding_box()
    assert left['x']+left['width'] <= right['x']+2
    result=run(page)
    assert result['graph']['vertices'][0]['attributes']['summary']=='negative'
    assert result['usage']['http_requests']==1 and len(calls)==1
    pw.expect(page.locator('#database-query-status')).to_contain_text('1 HTTP requests')
    page.wait_for_function("() => document.querySelector('#database-query-graph')._cyreg?.cy?.nodes().length === 2")
    for layout in ['circle','bipartite','grid','concentric','breadthfirst','cose']:
        page.get_by_label('Graph layout',exact=True).select_option(layout)
    page.evaluate("() => document.querySelector('#database-query-graph')._cyreg.cy.nodes()[0].emit('tap')")
    pw.expect(page.locator('#query-element-details')).to_contain_text('negative')
    page.locator('#query-node-label').select_option('summary')
    page.locator('#save-query-snapshot').click(); pw.expect(page.locator('#save-query-snapshot')).to_be_disabled()
    screenshot(page,'query-workspace-desktop')
    second=run(page); assert second['dataset']['id']!=result['dataset']['id'] and len(calls)==2
    with page.expect_response(re.compile(r'/api/database-query-snapshots/[^/]+/chat$')) as response:
        page.locator('#run-cypher-chat').click()
    assert response.value.ok, response.value.text()


def test_schema_model_config_and_mobile_query_preservation(query_page):
    page,_,calls,_=query_page
    page.locator('#open-dataset-schema').click()
    dialog=page.get_by_role('dialog',name='Dataset schema')
    pw.expect(dialog.get_by_text(re.compile('2 labels'))).to_be_visible()
    page.wait_for_function("() => document.querySelector('.workspace-schema-canvas')._cyreg?.cy?.edges().length === 1")
    page.wait_for_function("() => {const ns=document.querySelector('.workspace-schema-canvas')._cyreg.cy.nodes(); return Math.hypot(ns[0].position('x')-ns[1].position('x'),ns[0].position('y')-ns[1].position('y')) > 100;}")
    screenshot(page,'query-workspace-schema')
    page.keyboard.press('Escape'); pw.expect(dialog).to_have_count(0)
    page.locator('#open-query-models').click(); dialog=page.get_by_role('dialog',name='Model configuration')
    pw.expect(dialog).to_contain_text('fixture-model')
    pw.expect(dialog).not_to_contain_text('mock')
    dialog.get_by_label('Maximum HTTP requests per query',exact=True).fill('3')
    dialog.get_by_label('Inputs per model batch',exact=True).fill('1')
    dialog.get_by_role('button',name='Apply query settings').click()
    with page.expect_request(re.compile(r'/api/database-sources/demo/queries$')) as request:
        result=run(page)
    assert request.value.post_data_json['call_limit']==3 and request.value.post_data_json['batch_size']==1
    page.set_viewport_size({'width':390,'height':844})
    page.locator('#data-step-query').click()
    pw.expect(page.locator('#cypher-editor')).to_have_value(QUERY)
    page.locator('#data-step-query').focus(); page.keyboard.press('ArrowRight')
    pw.expect(page.locator('#data-step-preview')).to_be_focused()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    screenshot(page,'query-workspace-mobile')
    page.locator('#data-step-query').click()
    page.locator('#cypher-editor').fill(QUERY.replace('LIMIT 10','LIMIT 5'))
    pw.expect(page.locator('#source-continue')).to_be_hidden()
    assert len(calls)==1


@pytest.mark.parametrize('code',['semantic_call_limit','semantic_timeout','semantic_structured_output','semantic_model_server','database_cancelled'])
def test_failed_model_query_never_offers_partial_graph(query_page,code):
    page,_,calls,_=query_page
    page.route('**/api/database-sources/demo/queries',lambda route:route.fulfill(status=202,json={'job':{'id':'failure','kind':'query','status':'queued','cancellable':True}}))
    page.route('**/api/database-jobs/failure',lambda route:route.fulfill(json={'id':'failure','kind':'query','status':'failed','cancellable':False,'error':{'code':code,'message':'Controlled model failure','details':{'usage':{'http_requests':2}}}}))
    page.locator('#preview-cypher').click()
    pw.expect(page.locator('#database-query-status')).to_contain_text('Controlled model failure')
    pw.expect(page.locator('#source-continue')).to_be_hidden()
    pw.expect(page.locator('#preview-cypher')).to_be_enabled()
    assert calls==[]


def test_member_model_access_remains_enforced(query_page):
    page,base,calls,_=query_page
    sign_in(page,base,'review-member')
    response=page.request.post(base+'/api/database-sources/demo/queries',data={'statement':QUERY},headers={'X-GraphMine-Request':'1'})
    assert response.status==403 and calls==[]
    assert page.request.get(base+'/api/query-models').json()['available'] is False


def test_non_bipartite_graph_keeps_a_usable_layout_without_model_calls(query_page):
    page,_,calls,_=query_page
    run(page)
    page.wait_for_function("() => document.querySelector('#database-query-graph')._cyreg?.cy?.nodes().length === 2")
    page.evaluate("""() => {
      const cy=document.querySelector('#database-query-graph')._cyreg.cy, nodes=cy.nodes();
      cy.add([{data:{id:'triangle-node',label:'Third node',color:'#35775c'}},
        {data:{id:'triangle-a',source:nodes[0].id(),target:'triangle-node'}},
        {data:{id:'triangle-b',source:'triangle-node',target:nodes[1].id()}}]);
    }""")
    page.get_by_label('Graph layout',exact=True).select_option('bipartite')
    pw.expect(page.get_by_label('Graph layout',exact=True)).to_have_value('cose')
    pw.expect(page.get_by_text('This graph has an odd cycle; showing Spread instead of Bipartite.')).to_be_visible()
    assert len(calls)==1
