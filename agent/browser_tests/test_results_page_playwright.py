"""Playwright acceptance against isolated replays of the four saved Yelp runs.

Set GRAPHMINE_RESULTS_CASES and GRAPHMINE_RESULTS_URL to the replay manifest
and server. Never run against a live account: the fixture resets exploration.
"""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import time
import zipfile

import pytest

pw = pytest.importorskip('playwright.sync_api')
BASE = os.environ.get('GRAPHMINE_RESULTS_URL', 'http://127.0.0.1:18743')
MANIFEST = os.environ.get('GRAPHMINE_RESULTS_CASES')
pytestmark = pytest.mark.skipif(not MANIFEST, reason='Requires isolated saved-result replay server')
ARTIFACTS = Path(os.environ.get('GRAPHMINE_RESULTS_ARTIFACTS', '/tmp/graphmine-results-acceptance'))


def until(page, expression, arg=None, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = page.evaluate(expression, arg)
        if value:
            return value
        page.wait_for_timeout(100)
    raise AssertionError(f'Timed out: {expression}\n{page.locator("body").inner_text()[-2500:]}')


def settled(page):
    page.wait_for_timeout(300)
    previous, same = None, 0
    for _ in range(100):
        value = page.evaluate('''() => {const c=GraphMineWorkspace.state.cy; return c ? JSON.stringify([c.zoom(), c.pan(), c.nodes().map(n=>n.position())]) : "count"}''')
        same = same + 1 if previous == value else 0
        if same >= 4:
            return
        previous = value
        page.wait_for_timeout(100)
    raise AssertionError('Layout did not settle')


def open_case(page, cases, name):
    case = cases[name]
    page.goto(f"{BASE}/#workspace/{case['session']}/results/{case['workflow']}")
    until(page, 'id => GraphMineWorkspace?.state.resultView?.workflow_id === id && !GraphMineWorkspace.state.resultViewPending', case['workflow'], 90)
    settled(page)
    return case


def more(page):
    if not page.locator('#view-more').get_attribute('open') == '':
        page.locator('#view-more > summary').click()


def click_entity(page, name):
    point = page.evaluate('''name => {const c=GraphMineWorkspace.state.cy, n=c.nodes().filter(n=>n.data("fullLabel")===name)[0];if(!n)throw Error(name);const b=c.container().getBoundingClientRect(), p=n.renderedPosition();return {x:b.left+p.x,y:b.top+p.y}}''', name)
    page.mouse.click(point['x'], point['y'])
    page.mouse.move(5, 5)


@pytest.fixture(scope='module')
def browser():
    with pw.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    assert BASE.startswith('http://127.0.0.1:'), 'Use an isolated localhost replay only'
    context = browser.new_context(viewport={'width': 1440, 'height': 1100}, accept_downloads=True, reduced_motion='reduce', extra_http_headers={'Authorization': 'Bearer results-acceptance-test'})
    context.add_init_script("localStorage.setItem('graphmine.apiToken','results-acceptance-test')")
    cases = json.loads(Path(MANIFEST).read_text())
    session = cases['bicliques']['session']
    latest = context.request.get(f'{BASE}/api/sessions/{session}/exploration').json()
    response = context.request.put(f'{BASE}/api/sessions/{session}/exploration', data={'expected_revision': latest['revision'], 'state': {'active_file_id': None, 'view': None, 'views': [], 'named_views': []}})
    assert response.ok, response.text()
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    yield page, cases
    assert not errors, errors
    context.close()


@pytest.mark.parametrize('name', ['bicliques', 'communities', 'density', 'count'])
def test_01_answer_default_scope_names_and_canvas(page, name):
    page, cases = page
    case = open_case(page, cases, name)
    assert page.locator('#results-question').inner_text() == case['question']
    assert page.locator('#result-answer-sentence').inner_text()
    assert page.locator('#answer-metrics .metric').count() >= (1 if name == 'count' else 3)
    assert 'neo4j:' not in page.locator('body').inner_text()
    assert not page.locator('#view-surrounding-input').is_checked()
    assert page.evaluate('() => GraphMineWorkspace.state.selected.size') == 0
    if name == 'count':
        assert not page.locator('#network').is_visible()
        assert page.locator('#answer-metrics strong').inner_text() == '33'
    else:
        assert page.locator('#graph-layout').input_value() == page.evaluate('() => GraphMineWorkspace.state.resultView.view_spec.layout.name')
        assert page.evaluate('() => GraphMineWorkspace.state.cy.nodes().every(n=>n.data("result") && Number(n.style("opacity"))===1)')
        box = page.locator('#network').bounding_box()
        assert 360 <= box['height'] <= 640
        parent = page.locator('.graph-card').bounding_box()
        assert abs(box['width'] - (parent['width'] - 26)) < 3
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    page.locator('#results-view').screenshot(path=str(ARTIFACTS / f'{name}-default.png'))


def test_02_layouts_fit_and_label_collisions(page):
    page, cases = page
    open_case(page, cases, 'bicliques')
    page.locator('#view-surrounding-input').check()
    until(page, '() => GraphMineWorkspace.state.resultView.context && GraphMineWorkspace.state.cy.nodes().length===20')
    options = page.locator('#graph-layout option').evaluate_all('(options)=>options.filter(o=>!o.disabled&&o.value!=="__more").map(o=>({value:o.value,hidden:o.hidden}))')
    for option in options:
        if option['hidden']:
            page.select_option('#graph-layout', '__more')
            page.locator('#choose-layout-' + option['value']).click()
        else:
            page.select_option('#graph-layout', option['value'])
        settled(page)
        metrics = page.evaluate('''() => {const c=GraphMineWorkspace.state.cy;const boxes=c.nodes(":visible").map(n=>n.renderedBoundingBox());return {zoom:c.zoom(),outside:boxes.filter(b=>b.x1<0||b.y1<0||b.x2>c.width()||b.y2>c.height()).length, overlaps:boxes.reduce((sum,a,i)=>sum+boxes.slice(i+1).filter(b=>Math.min(a.x2,b.x2)>Math.max(a.x1,b.x1)&&Math.min(a.y2,b.y2)>Math.max(a.y1,b.y1)).length,0)}}''')
        assert .8 <= metrics['zoom'] <= 1.8, (option, metrics)
        assert metrics['outside'] == 0, (option, metrics)
        assert metrics['overlaps'] <= 5, (option, metrics)


def test_03_legend_and_community_color_consistency(page):
    page, cases = page
    open_case(page, cases, 'bicliques')
    text = page.locator('#view-legend').inner_text()
    assert 'User (1)' in text and 'Business (9)' in text
    assert 'Unspecified' not in text and 'Shape:' not in text
    open_case(page, cases, 'communities')
    assert page.locator('#result-item-count').inner_text() == 'of 4'
    assert page.evaluate('''() => {const s=GraphMineWorkspace.state;return s.groups.every(g=>s.resultView.view_spec.nodes.color.categories.find(c=>GraphMineWorkspace.wire.idKey(c.value)===g.key)?.color===g.color)}''')


def test_04_stepper_table_scatter_share_the_item(page):
    page, cases = page
    open_case(page, cases, 'bicliques')
    page.locator('#result-item-index').fill('17')
    page.locator('#result-item-index').press('Enter')
    until(page, '() => GraphMineWorkspace.state.resultView.index===16 && !GraphMineWorkspace.state.resultViewPending')
    assert page.locator('#result-table tr[data-result-row="16"]').get_attribute('aria-selected') == 'true'
    page.locator('#result-table tr[data-result-row="2"] button').click()
    until(page, '() => GraphMineWorkspace.state.resultView.index===2 && !GraphMineWorkspace.state.resultViewPending')
    dot = page.locator('#view-linked-charts circle[role="button"]').last
    indices = json.loads(dot.get_attribute('data-view-items'))
    dot.click()
    until(page, 'ids=>ids.includes(GraphMineWorkspace.state.resultView.index)&&!GraphMineWorkspace.state.resultViewPending', indices)
    current = page.evaluate('() => GraphMineWorkspace.state.resultView.index')
    assert page.locator(f'#result-table tr[data-result-row="{current}"]').get_attribute('aria-selected') == 'true'
    assert page.locator('#view-linked-charts circle[aria-pressed="true"]').count() == 1
    page.locator('#network').click(position={'x': 10, 'y': 10})
    page.keyboard.press('ArrowLeft')
    until(page, 'i=>GraphMineWorkspace.state.resultView.index===Math.max(0,i-1)', current)


def test_05_empty_filter_has_real_counts_and_clear_action(page):
    page, cases = page
    open_case(page, cases, 'bicliques')
    more(page); page.locator('#view-filter').click()
    dialog = page.locator('dialog[open]')
    dialog.get_by_label('Property', exact=True).select_option('degree')
    assert 'Range:' in dialog.inner_text()
    assert dialog.locator('svg').count()
    dialog.get_by_label('Value', exact=True).fill('99')
    dialog.locator('#add-view-filter').click()
    assert 'No entities match Connections in input ≥ 99' in page.locator('#view-empty').inner_text()
    assert page.locator('#preview-scope').inner_text().startswith('0 vertices · 0 connections')
    assert 'Connections in input ≥ 99' in page.locator('.view-filter-chips').inner_text()
    page.locator('#view-clear-filter').click()
    assert not page.locator('#view-empty').is_visible()
    assert page.locator('#preview-scope').inner_text().startswith('10 vertices')


def test_06_expand_pins_existing_geometry_and_updates_counts(page):
    page, cases = page
    open_case(page, cases, 'bicliques')
    before = page.evaluate('() => Object.fromEntries(GraphMineWorkspace.state.cy.nodes().map(n=>[n.id(),n.position()]))')
    page.locator('#network').scroll_into_view_if_needed(); click_entity(page, 'Mesa Verde')
    more(page); page.locator('#view-expand').click()
    until(page, '() => GraphMineWorkspace.state.cy.nodes().length>10 && !GraphMineWorkspace.state.incrementalLayout')
    settled(page)
    state = page.evaluate('''() => {const s=GraphMineWorkspace.state;return {zoom:s.cy.zoom(),nodes:s.cy.nodes().length,edges:s.cy.edges().length,positions:Object.fromEntries(s.cy.nodes().map(n=>[n.id(),n.position()])),pins:s.cy.nodes().filter(n=>n.locked()).length}}''')
    assert .8 <= state['zoom'] <= 1.8
    assert state['pins'] == 0
    for key, point in before.items():
        assert state['positions'][key] == pytest.approx(point)
    assert page.locator('#preview-scope').inner_text() == f"{state['nodes']} vertices · {state['edges']} connections ({state['nodes']-10} added by expanding)"


def test_07_entities_actions_and_switch_clear_selection(page):
    page, cases = page
    open_case(page, cases, 'bicliques')
    page.locator('#network').scroll_into_view_if_needed()
    click_entity(page, 'Tracy'); click_entity(page, 'Mesa Verde')
    assert '2 selected · Tracy, Mesa Verde' in page.locator('#view-selection-chip').inner_text()
    more(page); page.locator('#view-connection').click()
    until(page, '() => GraphMineWorkspace.state.selectedEdges.size>0')
    assert page.evaluate('() => GraphMineWorkspace.state.selected.size') == 2
    more(page); page.locator('#view-ask').click()
    until(page, '() => GraphMineWorkspace.state.view==="chat"')
    assert 'Tracy, Mesa Verde' in page.locator('#selection-label').inner_text()
    assert 'biclique' not in page.locator('#selection-label').inner_text().lower()
    open_case(page, cases, 'communities')
    assert page.evaluate('() => GraphMineWorkspace.state.selected.size') == 0
    assert not page.locator('#view-selection-chip').is_visible()


def test_08_small_saved_delta_and_reload(page):
    page, cases = page
    case = open_case(page, cases, 'bicliques')
    page.select_option('#graph-layout', 'grid'); settled(page)
    page.locator('#network').scroll_into_view_if_needed(); click_entity(page, 'Tracy')
    until(page, '() => document.querySelector("#exploration-status").textContent==="Saved"')
    page.wait_for_timeout(600)
    response = page.request.get(f"{BASE}/api/sessions/{case['session']}/exploration")
    saved = response.json()['state']
    assert len(json.dumps(saved).encode()) < 20000
    assert all('view_spec' not in view and 'display' not in view for view in saved['views'])
    assert all(not view.get('viewport', {}).get('positions') for view in saved['views'] if view.get('viewport'))
    page.reload(); until(page, 'id=>GraphMineWorkspace?.state.resultView?.workflow_id===id&&!GraphMineWorkspace.state.resultViewPending',case['workflow']); settled(page)
    assert page.locator('#graph-layout').input_value() == 'grid'
    assert '1 selected · Tracy' in page.locator('#view-selection-chip').inner_text()


def test_09_default_reset_is_pixel_identical(page):
    page, cases = page
    open_case(page, cases, 'bicliques')
    page.mouse.move(0, 0); before = page.locator('#network').screenshot()
    page.select_option('#graph-layout', 'grid'); settled(page)
    page.locator('#next-result-item').click()
    until(page, '() => GraphMineWorkspace.state.resultView.index===1&&!GraphMineWorkspace.state.resultViewPending')
    more(page); page.locator('#reset-result-focus').click(); settled(page)
    until(page, '() => GraphMineWorkspace.state.resultView.index===0&&!GraphMineWorkspace.state.resultViewPending')
    settled(page); page.mouse.move(0, 0)
    assert page.locator('#graph-layout').input_value() == 'bipartite'
    assert page.locator('#network').screenshot() == before


def test_10_downloads_have_unique_named_content_and_report(page):
    page, cases = page
    case = open_case(page, cases, 'bicliques')
    downloaded = {}
    for selector in ('view-export-png', 'view-export-svg', 'export-csv', 'view-export-visible', 'export-report', 'download-result'):
        if page.locator('#result-download-menu').get_attribute('open') is None:
            page.locator('#result-download-menu > summary').click()
        with page.expect_download(timeout=60000) as event:
            page.locator('#' + selector).click()
        downloaded[selector] = Path(event.value.path()).read_bytes()
    assert len({hashlib.sha256(v).hexdigest() for v in downloaded.values()}) == 6
    box = page.locator('#network').bounding_box()
    w, h = struct.unpack('>II', downloaded['view-export-png'][16:24])
    assert abs(w-2*box['width']) <= 2 and abs(h-2*box['height']) <= 2
    svg = downloaded['view-export-svg'].decode()
    assert 'export-legend' in svg and 'Tracy' in svg and f'width="{box["width"]}' in svg
    table = list(csv.DictReader(io.StringIO(downloaded['export-csv'].decode('utf-8-sig'))))
    assert len(table) == 33
    assert set(table[0]) == {'index','left_names','right_names','left_size','right_size','left_ids','right_ids'}
    assert 'Tracy' in table[0]['left_names'] and ';' in table[0]['right_names']
    assert not table[0]['left_ids'].startswith('[')
    visible = list(csv.DictReader(io.StringIO(downloaded['view-export-visible'].decode('utf-8-sig'))))
    assert all(any(row[field] for row in visible) for field in visible[0])
    archive = zipfile.ZipFile(io.BytesIO(downloaded['export-report']))
    report = archive.read('report.html').decode()
    assert case['question'] in report and 'Found 33 maximal bicliques' in report and 'Tracy' in report and '<img' in report and 'Reproduce' in report
    assert archive.read('default-view.png')[:8] == b'\x89PNG\r\n\x1a\n'
    request = json.loads(archive.read('request.json'))
    assert 'inputs' not in request and hashlib.sha256(archive.read(request['inputs_file'])).hexdigest() == request['inputs_sha256']
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    archive.extractall(ARTIFACTS / 'report')
    page.goto((ARTIFACTS / 'report/report.html').resolve().as_uri())
    page.screenshot(path=str(ARTIFACTS / 'report-first-screen.png'))


def test_11_toolbar_matrix_gallery_and_debug_controls(page):
    page, cases = page
    open_case(page, cases, 'bicliques')
    tops = page.locator('#view-toolbar > *:visible').evaluate_all('(els)=>els.map(e=>e.getBoundingClientRect()).filter(r=>r.height).map(r=>Math.round(r.top))')
    assert max(tops)-min(tops) < 16
    for selector in ('view-story','view-export-spec','view-upgrade','view-vertex-limit'):
        assert not page.locator('#'+selector).is_visible()
    for mode in ('matrix','small_multiples'):
        page.select_option('#view-as',mode); page.wait_for_timeout(700)
        assert not page.locator('#graph-layout').is_visible() and not page.locator('#fit-graph').is_visible()
        more(page); assert not page.locator('#view-lasso').is_visible(); page.locator('#view-more > summary').click()
        if mode == 'matrix':
            assert page.locator('#view-primary tbody tr').count() == 10
            assert page.locator('#view-primary thead th').count() == 11
            assert page.locator('.matrix-current').count() == 9
        else:
            assert page.locator('.view-thumbnail').count() == 12
            assert 'user' in page.locator('.view-thumbnail').first.inner_text().lower()
            page.locator('#gallery-next').click(); page.locator('#gallery-next').click()
            assert page.locator('.view-thumbnail').count() == 9
        page.locator('#results-view').screenshot(path=str(ARTIFACTS / f'bicliques-{mode}.png'))
    page.select_option('#view-as','graph'); page.locator('#result-download-menu > summary').click()
    page.locator('#results-view').screenshot(path=str(ARTIFACTS / 'download-menu.png'))


def test_12_run_selection_uses_input_requirements(page):
    page, cases = page
    open_case(page, cases, 'bicliques'); page.locator('#network').scroll_into_view_if_needed(); click_entity(page,'Tracy'); click_entity(page,'Mesa Verde')
    more(page); page.locator('#view-run').click()
    page.locator('#problem-dialog').wait_for(state='visible')
    values = page.locator('#problem-select option').evaluate_all('(els)=>els.map(e=>e.value).filter(Boolean)')
    assert values and len(values) < page.evaluate('() => GraphMineWorkspace.state.caps.problems.length')
    assert 'temporal-motifs' not in values and 'subgraph-isomorphism' not in values
    assert page.evaluate('ids=>ids.every(id=>GraphMineWorkspace.state.caps.problems.find(c=>c.id===id).input_kind==="graph")', values)
