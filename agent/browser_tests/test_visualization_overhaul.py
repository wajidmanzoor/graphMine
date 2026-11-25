"""Browser evidence for semantic fixtures and actual workspace persistence."""
import functools
from copy import deepcopy
import json
import os
import shutil
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from urllib.parse import urlsplit

from test_analytics_workspace import ROOT, authored_model_transport, browser, browser_evidence, server, upload, manual, done, capture

sys.path.insert(0, str(ROOT / "agent/tests"))
from test_view_overhaul import CASES, GOLDENS, Service
from graphmine_agent.result_views import result_view


@pytest.fixture(scope="module")
def gallery(tmp_path_factory):
    root = tmp_path_factory.mktemp("view-gallery")
    package = Path(os.environ.get("GRAPHMINE_BROWSER_APP_PATH", ROOT / "agent")) / "graphmine_agent"
    shutil.copytree(package / "static", root, dirs_exist_ok=True)
    records = []
    cut = deepcopy(next(c for c in CASES if c["kind"] == "flow"))
    cut["result"]["result"].update(source_side=[0, "0"], sink_side=[2])
    walk = deepcopy(next(c for c in CASES if c["kind"] == "path"))
    walk["result"] = {"problem": "random-walks", "parameters": {}, "ports": {"out": {"type": "walk_sample", "value": [[0, "0", 2, "0", 0]], "complete": True}}}
    temporal = deepcopy(next(c for c in CASES if c["kind"] == "path"))
    temporal["result"]["problem"] = "temporal-paths"
    temporal["result"]["ports"]["out"]["value"][0].update(departure=10, arrival=14)
    cases = [(c["kind"], c) for c in CASES] + [(p.stem, json.loads(p.read_text())) for p in GOLDENS] + [("recorded-cut", cut), ("recorded-walk", walk), ("recorded-time", temporal)]
    for i, (name, item) in enumerate(cases):
        service = Service(root / f"snapshot-{i}", item["result"])
        service.g = item["input"]
        port = next(iter(item["result"]["ports"]))
        view = result_view(service, "w", "analysis", port, expected_revision=1)
        context = result_view(service, "w", "analysis", port, context=True, expected_revision=1)
        records.append({"name": name, "view": view, "context": context})
    (root / "cases.json").write_text(json.dumps(records))
    (root / "gallery.html").write_text('''<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/analytics-visualization.css">
<script src="/analytics-wire.js"></script><script src="/vendor/cytoscape.min.js"></script><script src="/vendor/graph-layouts.min.js"></script><script src="/analytics-view-style.js"></script><script src="/analytics-view-geometry.js"></script><script src="/analytics-view-charts.js"></script><script src="/analytics-view-alternates.js"></script><script src="/project-viewer.js"></script>
<style>body{margin:20px}#canvas{height:440px;width:100%;position:relative;background:var(--graph-paper)}#primary,#linked{width:100%;min-width:0}#name{font-size:18px}</style></head><body><h1 id="name"></h1><div id="canvas"></div><div id="primary"></div><div id="linked"></div><script src="/gallery.js"></script></body></html>''')
    (root / "gallery.js").write_text('''"use strict";
const W=window.AnalyticsWire,S=window.GraphMineViewStyle,G=window.GraphMineViewGeometry;
const node=(tag,attrs={},text)=>{const e=document.createElement(tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e};
window.errors=[];window.addEventListener('error',e=>errors.push(e.message));window.addEventListener('unhandledrejection',e=>errors.push(String(e.reason)));
let cy,alt,view;window.selected=[];let records;
const select=item=>{window.selected=item.ids||[];const keys=new Set(selected.map(W.idKey));cy?.nodes().forEach(n=>n.toggleClass('chosen',keys.has(n.id())));charts.selectionChanged(keys)};
const charts=window.GraphMineViewCharts({W,node,label:id=>view?.vertices.find(v=>W.idKey(v.id)===W.idKey(id))?.label||W.idLabel(id),select});
window.loadCase=async(index,choice)=>{records??=W.parse(await (await fetch('/cases.json')).text());cy?.destroy();alt?.clear();view=records[index].view;document.getElementById('name').textContent=records[index].name;const canvas=document.getElementById('canvas'),primary=document.getElementById('primary'),linked=document.getElementById('linked');primary.replaceChildren();canvas.replaceChildren();choice??=view.view_spec.view;canvas.hidden=choice!=='graph';
if(choice==='graph'&&view.vertices.length){const data=S.renderData(W,view,view.view_spec);cy=window.cytoscape({container:canvas,elements:data.elements,style:S.stylesheet(view.graph?.directed),layout:{name:'circle'},minZoom:1e-6,maxZoom:20});S.fit(cy);cy.on('zoom',()=>S.screenSizes(cy));G.overlay(cy,ids=>select({ids:ids.map(key=>cy.getElementById(key).data('entity'))}));}
else{alt=window.GraphMineViewAlternates({W,node,charts,label:W.idLabel,context:async()=>records[index].context,select:ids=>select({ids}),overrides:()=>({}),changed:()=>{}});if(alt.supported.has(choice))await alt.render(primary,view,choice);else charts.renderPrimary(primary,view,choice);}
charts.renderLinked(linked,view);await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));window.testCy=cy;window.testView=view;return {name:records[index].name,errors,body:primary.textContent+linked.textContent,fonts:[...document.querySelectorAll(".view-chart text")].map(t=>{const m=t.getScreenCTM();return parseFloat(getComputedStyle(t).fontSize)*Math.hypot(m.a,m.b)}),graph:cy&&!canvas.hidden?{nodes:cy.nodes().length,font:parseFloat(cy.nodes()[0].style('font-size'))*cy.zoom(),box:cy.nodes().renderedBoundingBox(),width:cy.width(),height:cy.height()}:null};};
window.sharedCoordinates=()=>{cy?.destroy();alt?.clear();const host=document.getElementById('primary');host.replaceChildren();const graph=records[0].view;const saved=W.parse(W.stringify({viewport:{zoom:1.3,pan:{x:93,y:55},positions:graph.vertices.map((v,i)=>({id:v.id,x:30+i*50,y:40+i*25}))},view_spec:graph.view_spec,overrides:{},selected_vertices:[graph.vertices[0].id],pinned:[]}));const viewer=GraphMineProjectViewer.show(host,{name:'Saved view',kind:'workflow',created_at:new Date().toISOString(),snapshot:{kind:'workflow',view_data:graph,view:saved}});const graphCy=document.getElementById('project-graph')._cyreg.cy;return {pan:graphCy.pan(),zoom:graphCy.zoom(),positions:viewer.capture().positions};};
window.exportGraph=async()=>{const source=G.svg(cy),blob=await G.png(source);return {svg:source,pngBytes:blob.size}};
window.workerTest=()=>new Promise(resolve=>{const worker=new Worker('/vendor/layout-worker.min.js');worker.onmessage=e=>{worker.terminate();resolve(e.data)};worker.postMessage({layout:'force',nodes:Array.from({length:501},(_,i)=>({id:'n'+i,x:(i%25)*100,y:Math.floor(i/25)*100,pinned:i===0})),edges:Array.from({length:500},(_,i)=>({source:'n'+i,target:'n'+(i+1)}))});});
''')
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    http = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(root)))
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{http.server_port}", records
    http.shutdown()
    thread.join(timeout=3)


def test_all_profiles_and_saved_golden_views_in_real_browser(browser, gallery):
    browser.get(gallery[0] + "/gallery.html")
    for i, record in enumerate(gallery[1]):
        value = browser.execute_async_script("const done=arguments[2];loadCase(arguments[0],arguments[1]).then(done).catch(e=>done({error:String(e)}));", i, None)
        assert not value.get("error") and not value["errors"], (record["name"], value)
        assert all(size == pytest.approx(12, abs=.1) for size in value["fonts"]), (record["name"], value["fonts"])
        if value["graph"]:
            graph = value["graph"]
            assert graph["font"] == pytest.approx(12)
            assert graph["box"]["x1"] >= 0 and graph["box"]["x2"] <= graph["width"]
            assert graph["box"]["y1"] >= 0 and graph["box"]["y2"] <= graph["height"]
        capture(browser, f"profile-{i:02}-{record['name']}.png")
    for name, choice in [("spectrum", "eigenvector"), ("intervals", "filtration"), ("graph", "input_comparison"), ("instances", "occurrence_overlay"), ("mapping", "merged_mapping"), ("recorded-cut", "cut"), ("recorded-walk", "walk"), ("recorded-walk", "visit_heat"), ("recorded-time", "timeline")]:
        i = next(i for i, r in enumerate(gallery[1]) if r["name"] == name)
        value = browser.execute_async_script("const done=arguments[2];loadCase(arguments[0],arguments[1]).then(done).catch(e=>done({error:String(e)}));", i, choice)
        assert not value.get("error") and not value["errors"], value
        capture(browser, "alternate-" + choice + ".png")
    browser.execute_async_script("loadCase(8,'graph').then(arguments[0])")
    exported = browser.execute_async_script("exportGraph().then(arguments[0])")
    assert exported["pngBytes"] > 1000
    assert "polygon" in exported["svg"] and "path" in exported["svg"]
    worker = browser.execute_async_script("workerTest().then(arguments[0])")
    assert "error" not in worker and len(worker["positions"]) == 501
    assert worker["positions"][0]["x"] == 0 and worker["positions"][0]["y"] == 0
    browser.set_window_size(500, 844)
    browser.execute_async_script("loadCase(21,null).then(arguments[0])")
    assert browser.execute_script("return document.documentElement.scrollWidth <= innerWidth")
    capture(browser, "barcode-narrow.png")
    shared = browser.execute_script("return sharedCoordinates()")
    assert shared["pan"] == {"x": 93, "y": 55} and shared["zoom"] == 1.3
    assert shared["positions"][0]["x"] == 30 and shared["positions"][0]["y"] == 40



def test_view_styles_selection_exports_and_named_restore(browser, tmp_path):
    upload(browser, tmp_path)
    manual(browser)
    Select(browser.find_element(By.ID, "problem-select")).select_by_value("degree-centrality")
    browser.find_element(By.ID, "use-problem").click()
    done(browser)
    wait = WebDriverWait(browser, 15)
    wait.until(lambda d: d.execute_script("return !!GraphMineWorkspace.state.resultView?.view_spec && !GraphMineWorkspace.state.resultViewPending"))
    browser.execute_script("const s=GraphMineWorkspace.state;const n=s.cy.nodes()[0];n.position('x',40);n.position('y',60);n.lock();s.selected=new Set([n.id()]);GraphMineWorkspace.visualization.selectionChanged();GraphMineWorkspace.exploration.changed();")
    browser.execute_async_script("GraphMineWorkspace.exploration.saveNamed('Pinned score view').then(arguments[0])")
    view = json.loads(browser.execute_script("return AnalyticsWire.stringify(GraphMineWorkspace.visualization.exportDocument())"))
    assert view["view"]["pinned"] == [0] and view["view"]["selected_vertices"] == [0]
    assert "view_spec" not in view["view"] and "display" not in view["view"]
    assert view["rules_version"]
    old_document = browser.find_element(By.TAG_NAME, 'html')
    browser.get(urlsplit(browser.current_url)._replace(query='debug=1').geturl())
    wait.until(EC.staleness_of(old_document))
    wait.until(lambda d: d.execute_script("return !!GraphMineWorkspace?.state.resultView?.view_spec && !GraphMineWorkspace.state.resultViewPending && !!document.querySelector('#view-more > summary')"))
    browser.find_element(By.CSS_SELECTOR, '#view-more > summary').click()
    browser.find_element(By.ID, "view-export-spec").click()
    wait.until(lambda d: d.find_element(By.CSS_SELECTOR, 'dialog[open] pre'))
    assert json.loads(browser.find_element(By.CSS_SELECTOR, 'dialog[open] pre').text)["view"]["pinned"] == [0]
    browser.find_element(By.XPATH, "//dialog[@open]//button[text()='Close']").click()
    browser.find_element(By.CSS_SELECTOR, '#view-more > summary').click()
    browser.find_element(By.ID, "view-filter").click()
    form = browser.find_element(By.CSS_SELECTOR, "dialog[open] form")
    selects = form.find_elements(By.TAG_NAME, "select")
    Select(selects[1]).select_by_value("score")
    Select(selects[2]).select_by_value("gte")
    form.find_element(By.TAG_NAME, "input").send_keys("0.5")
    browser.find_element(By.ID, "add-view-filter").click()
    wait.until(lambda d: d.execute_script("return GraphMineWorkspace.state.cy.nodes(':visible').length===3"))
    browser.execute_script("document.querySelector('#view-named').closest('details').open=true")
    browser.find_element(By.ID, "view-named").click()
    browser.find_element(By.XPATH, "//dialog[@open]//button[text()='Pinned score view']").click()
    wait.until(lambda d: d.execute_script("return !!GraphMineWorkspace.state.resultView?.view_spec && !GraphMineWorkspace.state.resultViewPending && GraphMineWorkspace.state.cy?.nodes(':visible').length===5 && GraphMineWorkspace.state.cy.nodes()[0].locked()"))
    wait.until(lambda d: d.execute_script("return !GraphMineWorkspace.state.restoreEntitySelection"))
    assert browser.execute_script("return GraphMineWorkspace.state.cy.nodes()[0].position()") == pytest.approx({"x": 40, "y": 60})
    capture(browser, "named-view-restored.png")
    browser.find_element(By.CSS_SELECTOR, '#result-table tr[data-result-row="0"] button').click()
    wait.until(lambda d: d.execute_script("return GraphMineWorkspace.state.resultView?.index===0 && !GraphMineWorkspace.state.resultViewPending && GraphMineWorkspace.state.cy.nodes().length===1"))
    browser.execute_script("document.querySelector('#view-more > summary').scrollIntoView({block:'center'});document.querySelector('#view-expand').closest('details').open=true")
    browser.find_element(By.ID, "view-expand").click()
    wait.until(lambda d: d.execute_script("return GraphMineWorkspace.state.cy.nodes().length===3"))
    browser.execute_async_script("GraphMineWorkspace.exploration.saveNamed('Expanded context').then(arguments[0])")
    expanded = json.loads(browser.execute_script("return AnalyticsWire.stringify(GraphMineWorkspace.visualization.exportDocument())"))
    assert len(expanded["view"]["context_vertices"]) == 2
    browser.refresh()
    wait.until(lambda d: d.execute_script("return GraphMineWorkspace?.state.cy?.nodes().length===3 && !GraphMineWorkspace.state.resultViewPending"))
    assert browser.execute_script("return GraphMineWorkspace.state.viewContext.vertices.length") == 2
    capture(browser, "expanded-context-restored.png")
