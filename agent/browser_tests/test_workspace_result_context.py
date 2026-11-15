"""Result context keeps source scope, quality and display limits independent."""

import json
from copy import deepcopy
from threading import Event
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select

from graphmine_agent.exploration import SaveExploration
from test_workspace_accessibility import assert_readable
from test_workspace_conversation_graph import open_saved
from test_workspace_exploration import exploration_server, set_control, saved  # noqa: F401
from test_workspace_loading import loading_browser, loading_server, wait_for  # noqa: F401


def provenance(name="Accounts-v2.json", version=2):
    return {"file_id": "network", "sha256": "a" * 64, "dataset_id": "accounts", "version_id": "version-2", "version": version, "source_complete": True,
            "file_snapshot": {"name": name, "kind": "graph", "created_at": "2026-10-20T12:00:00Z", "graph": {"vertex_count": 700, "edge_count": 1500, "directed": False}},
            "source": {"type": "database_query", "database_source": {"id": "accounts-db", "name": "Account database", "revision": 3, "mapping_hash": "mapping-3"},
                       "database_dataset": {"id": "accounts", "name": "Account relationships"}, "fetched_at": "2026-10-20T11:00:00Z", "row_count": 10,
                       "scope": "exact returned graph elements and relationship endpoints", "query": "MATCH (n) WHERE n.userId = $user RETURN n LIMIT 10",
                       "parameters": {"user": 9007199254740993, "code": "001"}, "projection": "elements"}}


@pytest.fixture
def context_server(exploration_server):
    server = exploration_server
    server.visualization = True
    record = server.workflows[0]
    record["input_provenance"] = {"main": provenance(), "unused": provenance("Unused source", 99)}
    server.files.append({**server.files[0], "id": "newer", "original_name": "New graph-v9.json", "provenance": provenance("New graph-v9.json", 9)})
    value = SimpleNamespace(server=server, record=record, output=server.results[record["id"]]["steps"]["core"]["result"],
                            delay=None, failed_view=False, no_graph=False, truncated=True, rows=None, page_error=False, view_revision=1,
                            primary_graph={"vertex_count": 700, "edge_count": 1500, "directed": False}, view_requests=[], preview_reads=0)
    original = server.route_handler

    def route(handler, method):
        parsed = urlsplit(handler.path); path = parsed.path
        if path.endswith("/graph-preview"):
            value.preview_reads += 1
        if path.endswith(("/ports/scores", "/ports/groups")) and value.rows is not None:
            if value.page_error:
                handler.respond({"error": {"code": "revision_conflict", "message": "Analysis revision changed. Reload its results."}}, 409)
                return True
            params = parse_qs(parsed.query); offset = int(params.get("offset", [0])[0]); limit = int(params.get("limit", [30])[0])
            search = params.get("search", [""])[0]
            rows = [(i, row) for i, row in enumerate(value.rows) if search.lower() in json.dumps(row).lower()]
            handler.respond({"items": [row for _, row in rows[offset:offset+limit]], "positions": [i for i, _ in rows[offset:offset+limit]],
                             "offset": offset, "limit": limit, "matched_items": len(rows), "total_items": len(value.rows)})
            return True
        if path.endswith("/view"):
            params = parse_qs(parsed.query); value.view_requests.append(params)
            context = params.get("context", ["false"])[0] == "true"
            index = int(params["index"][0]) if "index" in params else None
            graph = deepcopy(server.graph)
            graph.update(vertex_count=700 if value.truncated else 6, edge_count=1500 if value.truncated else 7, vertices_truncated=value.truncated, edges_truncated=value.truncated,
                         limits={"vertices": 500, "edges": 2000}, input_graph=value.primary_graph, revision=value.view_revision, graph_available=not value.no_graph, enrichable=True, index=index, context=context,
                         step="core", port=path.split("/")[-2], item_count=2, selected_vertices=[1], selected_edges=[], selection_truncated=value.truncated,
                         source_file_ids=["network"], profile={"kind": "subgraph", "title": "Community"}, complete=value.output["ports"].get(path.split("/")[-2], {}).get("complete", False), note="Recorded result")
            if value.no_graph:
                graph["vertices"] = []; graph["edges"] = []
            if value.delay:
                delayed = value.delay; delayed.started.set(); delayed.release.wait(10); delayed.finished.set()
            handler.respond({"error": {"message": "Saved view unavailable"}} if value.failed_view else graph, 503 if value.failed_view else 200)
            return True
        return original(handler, method)

    server.route_handler = route
    yield value
    if value.delay:
        value.delay.release.set()


def open_context(browser, fixture, width=1440):
    browser.browsing_context.set_viewport(context=browser.current_window_handle, viewport={"width": width, "height": 900})
    open_saved(browser, fixture.server, "results/saved-analysis")
    wait_for(browser, "!document.getElementById('result-context').hidden && !GraphMineWorkspace.state.resultViewPending && document.getElementById('result-context-display').textContent.includes('Table:')")
    button = browser.find_element(By.ID, "toggle-result-context")
    assert button.get_attribute("aria-expanded") == "false"
    assert browser.find_element(By.ID, "result-context-summary").is_displayed()
    assert not browser.find_element(By.ID, "result-context-grid").is_displayed()
    button.click()


def content(browser, key):
    return browser.find_element(By.ID, f"result-context-{key}").text


@pytest.mark.parametrize("width", [1440, 320])
def test_result_context_is_readable_and_keeps_quality_scope_and_bounds_separate(loading_browser, context_server, width):
    browser = loading_browser; fixture = context_server
    fixture.output["quality"] = "exact"
    open_context(browser, fixture, width)
    assert "Accounts-v2.json · version 2" in content(browser, "inputs")
    assert "Unused source" not in browser.find_element(By.ID, "result-context").text
    assert "Complete within the saved source selection" in content(browser, "scope")
    assert "entire database or population" in content(browser, "scope")
    assert "Exact" in content(browser, "calculation") and "output collection is complete" in content(browser, "calculation")
    assert "6 of 700 vertices" in content(browser, "display") and "Graph display is truncated" in content(browser, "display")
    assert_readable(browser)
    assert browser.execute_script("return document.documentElement.scrollWidth <= innerWidth + 1")
    browser.find_element(By.CSS_SELECTOR, '#result-context-scope details summary').click()
    assert "LIMIT 10" in content(browser, "scope") and "9007199254740993" in content(browser, "scope")
    browser.save_screenshot(f"/tmp/graphmine-result-context-{width}.png")
    button = browser.find_element(By.ID, "toggle-result-context")
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", button); button.click()
    assert button.get_attribute("aria-expanded") == "false"
    button.send_keys(Keys.SPACE)
    assert button.get_attribute("aria-expanded") == "true"


def test_older_analysis_keeps_saved_input_when_active_input_changes(loading_browser, context_server):
    browser = loading_browser; open_context(browser, context_server)
    set_control(browser, "active-input", "newer", "change")
    saved(browser, lambda: context_server.server.preferences["state"]["active_file_id"] == "newer")
    browser.refresh()
    wait_for(browser, "GraphMineWorkspace.state.active === 'newer' && !GraphMineWorkspace.state.busy && document.getElementById('result-context-inputs').textContent.includes('Accounts-v2.json')")
    browser.find_element(By.ID, "toggle-result-context").click()
    assert "New graph-v9.json" not in content(browser, "inputs")
    assert "version 2" in content(browser, "inputs")


def test_removed_original_file_does_not_prevent_saved_result_context_or_graph(loading_browser, context_server):
    context_server.server.files = []
    open_context(loading_browser, context_server)
    assert "Accounts-v2.json" in content(loading_browser, "inputs")
    assert loading_browser.execute_script("return GraphMineWorkspace.state.cy.nodes().length") == 6
    assert context_server.preview_reads == 0


def test_incomplete_source_is_independent_of_complete_heuristic_output(loading_browser, context_server):
    context_server.record["input_provenance"]["main"]["source_complete"] = False
    open_context(loading_browser, context_server)
    assert "Includes incomplete source output" in content(loading_browser, "scope")
    assert "Heuristic" in content(loading_browser, "calculation") and "output collection is complete" in content(loading_browser, "calculation")


def test_one_complete_source_does_not_claim_completeness_of_unknown_bound_input(loading_browser, context_server):
    context_server.record["input_provenance"]["other"] = {"file_id": "other", "sha256": "unknown"}
    context_server.record["validation"]["plan"]["steps"][0]["bindings"] = {"other_graph": {"input": "other"}}
    open_context(loading_browser, context_server)
    assert "completeness of other inputs was not recorded" in content(loading_browser, "scope")
    assert "Complete within the saved source selection" not in content(loading_browser, "scope")


def test_completed_step_of_failed_workflow_and_scalar_without_graph_remain_explained(loading_browser, context_server):
    context_server.record.update(status="failed", complete=False, error={"message": "Later step failed"})
    context_server.no_graph = True
    context_server.output["ports"] = {"count": {"type": "scalar", "value": 7, "complete": True}}
    open_context(loading_browser, context_server)
    assert "Workflow: Failed" in content(loading_browser, "calculation")
    assert "output collection is complete" in content(loading_browser, "calculation")
    assert "no graph representation" in content(loading_browser, "display")
    assert "Account database" in content(loading_browser, "scope")


def test_expanded_graph_scope_does_not_claim_to_be_only_the_initial_query(loading_browser, context_server):
    source = context_server.record["input_provenance"]["main"]["source"]
    source.update(type="database_expansion", expansion={"mapping": "links", "fetched_at": "2026-10-21T10:00:00Z"})
    open_context(loading_browser, context_server)
    assert "query below describes the original selection" in content(loading_browser, "scope")
    assert "Relationships were added" in content(loading_browser, "scope")


def test_incomplete_collection_and_complete_count_are_described_per_output(loading_browser, context_server):
    output = context_server.output
    output["complete"] = False; output["quality"] = "exact"; output["parameters"] = {"mode": "count", "result_limit": 10}
    output["ports"]["groups"]["complete"] = False
    output["ports"]["count"] = {"type": "scalar", "value": 123, "complete": True}
    open_context(loading_browser, context_server)
    Select(loading_browser.find_element(By.ID, "result-port")).select_by_value("groups")
    wait_for(loading_browser, "document.getElementById('result-completeness').textContent.includes('count-only')")
    Select(loading_browser.find_element(By.ID, "result-port")).select_by_value("count")
    wait_for(loading_browser, "document.getElementById('result-completeness').textContent.includes('output collection is complete')")
    assert "Some outputs from this step are incomplete" in content(loading_browser, "calculation")
    assert "Exact" in content(loading_browser, "calculation")


def test_derived_steps_include_bound_input_lineage_without_unrelated_inputs(loading_browser, context_server):
    record = context_server.record
    record["input_provenance"]["reference"] = provenance("Reference-v4.json", 4)
    record["validation"]["plan"]["steps"].insert(0, {"id": "prepare", "operation": "induced-subgraph", "input": {"input": "main"}, "parameters": {}})
    record["validation"]["plan"]["steps"][1].update(input={"step": "prepare", "port": "graph"}, bindings={"other_graph": {"input": "reference"}})
    context_server.primary_graph = {"vertex_count": 18, "edge_count": 30, "directed": False}
    open_context(loading_browser, context_server)
    assert "Reference-v4.json" in content(loading_browser, "inputs") and "Accounts-v2.json" in content(loading_browser, "inputs")
    assert "Uses earlier workflow output" in content(loading_browser, "inputs")
    assert "Primary step input: 18 vertices · 30 connections" in content(loading_browser, "inputs")
    assert "Unused source" not in content(loading_browser, "inputs")


@pytest.mark.parametrize("source_type", ["tables", "result", "resaved"])
def test_reused_sources_retain_original_query_scope(loading_browser, context_server, source_type):
    original = provenance(); original["source_complete"] = False
    graph = {"file_id": "network", "sha256": "b" * 64, "file_snapshot": {"name": "Derived graph.json"}}
    if source_type == "tables":
        graph.update(projection={"filters": [{"field": "risk", "operator": "gt", "value": 7}]}, tables={"accounts": {"file_id": "query-table", "sha256": "table-hash", "source": original}})
    elif source_type == "result":
        graph["source"] = {"type": "result", "workflow_id": "previous", "revision": 7, "step": "sub", "port": "graph", "group_index": 0,
                           "plan": {"steps": [{"id": "sub", "input": {"input": "before"}}]}, "input_provenance": {"before": original}}
    else:
        graph["source"] = {"type": "upload", "parent": original}
    context_server.record["input_provenance"]["main"] = graph
    open_context(loading_browser, context_server)
    assert "Account database" in content(loading_browser, "scope")
    assert "Includes incomplete source output" in content(loading_browser, "scope")
    if source_type == "tables":
        assert "Graph constructed from saved tables" in content(loading_browser, "scope")
    if source_type == "result":
        assert "previous · revision 7 · sub/graph · group 1" in content(loading_browser, "scope")


def test_missing_recorded_metadata_is_not_filled_from_catalog_or_current_file(loading_browser, context_server):
    context_server.record.pop("input_provenance")
    context_server.output.pop("quality"); context_server.output.pop("backend")
    context_server.output["ports"]["groups"].pop("complete")
    open_context(loading_browser, context_server)
    assert "Quality: Not recorded" in content(loading_browser, "calculation")
    assert "Output completeness was not recorded" in content(loading_browser, "calculation")
    assert "Source completeness: Not recorded" in content(loading_browser, "scope")
    assert "version 9" not in content(loading_browser, "inputs")


def test_neo4j_only_results_explain_optional_sql_and_disable_unavailable_enrichment(loading_browser, context_server):
    file = context_server.server.files[0]
    file['provenance'] = {'version': 2, 'source': deepcopy(context_server.record['input_provenance']['main']['source'])}
    file['provenance']['source']['database_source']['capabilities'] = {'sql': False, 'enrichment': False, 'expansion': False}
    open_context(loading_browser, context_server)
    assert not loading_browser.find_element(By.ID, 'enrich-attributes').is_enabled()
    assert not loading_browser.find_element(By.ID, 'enrich-relationships').is_enabled()
    assert 'optional' in loading_browser.find_element(By.ID, 'enrichment-note').get_attribute('textContent')


def test_graph_time_filter_and_table_page_counts_change_only_display(loading_browser, context_server):
    for index, edge in enumerate(context_server.server.graph["edges"][:-1]):
        edge["timestamp"] = 100 + index
    context_server.rows = [{"vertex": index, "score": index} for index in range(125)]
    context_server.output["ports"] = {"scores": {"type": "vertex_scores", "complete": True, "value": context_server.rows[:50], "total_items": 125, "value_truncated": True}}
    open_context(loading_browser, context_server)
    wait_for(loading_browser, "document.getElementById('result-context-display').textContent.includes('30 rows on this page')")
    assert "50 loaded rows of 125" in content(loading_browser, "display")
    original = content(loading_browser, "scope")
    set_control(loading_browser, "time-start", "2")
    wait_for(loading_browser, "document.getElementById('result-context-display').textContent.includes('5 connections visible')")
    set_control(loading_browser, "table-search", "124")
    wait_for(loading_browser, "document.getElementById('result-context-display').textContent.includes('1 rows on this page · 1 matching · 125 retained')")
    assert content(loading_browser, "scope") == original


def test_display_overlay_does_not_replace_the_recorded_input_version(loading_browser, context_server):
    server = context_server.server
    server.files[1]["provenance"] = {"version": 8, "source": {"fetched_at": "2026-10-21T10:00:00Z"}}
    scope = {"result": {"workflow_id": "saved-analysis", "revision": 1, "step": "core", "port": "groups", "index": None, "context": False}}
    server.preferences.update(revision=1, state=SaveExploration(expected_revision=0, state={"active_file_id": "network", "view": scope, "views": [{"scope": scope, "overlay_file_id": "enriched"}]}).state.model_dump(mode="json"))
    open_context(loading_browser, context_server)
    wait_for(loading_browser, "document.getElementById('result-context-display').textContent.includes('Version 8')")
    assert "version 2" in content(loading_browser, "inputs")
    assert "calculation retains its original input snapshot" in content(loading_browser, "display")


def test_context_distinguishes_result_focus_from_saved_input_context(loading_browser, context_server):
    browser = loading_browser; open_context(browser, context_server)
    Select(browser.find_element(By.ID, "result-view-mode")).select_by_value("context")
    wait_for(browser, "document.getElementById('result-context-display').textContent.includes('Saved step input with the result highlighted')")
    assert "Accounts-v2.json" in content(browser, "inputs")
    context_server.failed_view = True
    Select(browser.find_element(By.ID, "result-view-mode")).select_by_value("focus")
    wait_for(browser, "document.getElementById('result-context-display').textContent.includes('coverage cannot be verified')")
    assert "output collection is complete" in content(browser, "calculation")


def test_late_result_view_cannot_restore_context_after_navigation_home(loading_browser, context_server):
    browser = loading_browser; open_context(browser, context_server)
    context_server.delay = SimpleNamespace(started=Event(), release=Event(), finished=Event())
    Select(browser.find_element(By.ID, "result-view-mode")).select_by_value("context")
    assert context_server.delay.started.wait(3)
    browser.execute_script("location.hash = '#'")
    wait_for(browser, "GraphMineWorkspace.state.view === 'domains' && document.getElementById('result-context').hidden")
    context_server.delay.release.set(); assert context_server.delay.finished.wait(3)
    assert browser.find_element(By.ID, "result-context").get_attribute("hidden")


def test_metadata_remains_available_without_upload_or_native_discovery(loading_browser, context_server):
    server = context_server.server
    server.files = []; server.visualization = False
    loading_browser.get(server.url + "/#workspace/saved-session/results/saved-analysis")
    wait_for(loading_browser, "document.getElementById('result-context-inputs').textContent.includes('Accounts-v2.json') && !GraphMineWorkspace.state.busy")
    assert server.responses[0].started.wait(3) and not server.responses[0].finished.is_set()
    loading_browser.find_element(By.ID, "toggle-result-context").click()
    assert "Heuristic" in content(loading_browser, "calculation")
    assert context_server.preview_reads == 0


def test_changed_view_revision_is_not_displayed_under_the_old_snapshot(loading_browser, context_server):
    browser = loading_browser; open_context(browser, context_server)
    assert context_server.view_requests[0]["expected_revision"] == ["1"]
    context_server.view_revision = 2
    Select(browser.find_element(By.ID, "result-view-mode")).select_by_value("context")
    wait_for(browser, "document.getElementById('notice').textContent.includes('revision changed')")
    assert "coverage cannot be verified" in content(browser, "display")
    assert browser.execute_script("return GraphMineWorkspace.state.resultView") is None


def test_changed_table_revision_does_not_report_a_loaded_page(loading_browser, context_server):
    context_server.rows = [{"vertex": index, "score": index} for index in range(125)]
    context_server.output["ports"] = {"scores": {"type": "vertex_scores", "complete": True, "value": context_server.rows[:50], "total_items": 125, "value_truncated": True}}
    browser = loading_browser; open_context(browser, context_server)
    wait_for(browser, "document.getElementById('result-context-display').textContent.includes('30 rows on this page')")
    context_server.page_error = True
    set_control(browser, "table-search", "124")
    wait_for(browser, "document.getElementById('result-context-display').textContent.includes('Table page unavailable')")
    assert "revision changed" in content(browser, "display")
    assert "Accounts-v2.json" in content(browser, "inputs")


def test_invalid_group_filters_clear_pending_table_coverage(loading_browser, context_server):
    context_server.rows = [{"group": index, "vertices": [index]} for index in range(125)]
    context_server.output["ports"] = {"groups": {"type": "vertex_groups", "complete": True, "value": context_server.rows[:50], "total_items": 125, "value_truncated": True}}
    browser = loading_browser; open_context(browser, context_server)
    wait_for(browser, "document.getElementById('result-context-display').textContent.includes('30 rows on this page')")
    set_control(browser, "group-min-size", "5")
    set_control(browser, "group-max-size", "1")
    wait_for(browser, "document.getElementById('result-context-display').textContent.includes('Minimum size must not exceed maximum size')")
    assert "Loading retained rows" not in content(browser, "display")
    assert "30 rows on this page" not in content(browser, "display")
    set_control(browser, "group-max-size", "10")
    wait_for(browser, "document.getElementById('result-context-display').textContent.includes('30 rows on this page')")


def test_selected_group_is_not_mislabeled_as_a_truncated_input(loading_browser, context_server):
    context_server.server.visualization = False
    browser = loading_browser; open_context(browser, context_server)
    Select(browser.find_element(By.ID, "graph-group")).select_by_index(1)
    wait_for(browser, "document.getElementById('result-context-display').textContent.includes('3 of 3 vertices')")
    assert "3 of 3 connections" in content(browser, "display")
    assert "selected members and their internal connections" in content(browser, "display")
    assert "Graph display is truncated" not in content(browser, "display")


def test_partial_group_reports_unknown_connection_coverage(loading_browser, context_server):
    server = context_server.server; server.visualization = False
    server.graph["edges"] = server.graph["edges"][:2]
    server.graph["edges_truncated"] = True
    browser = loading_browser; open_context(browser, context_server)
    Select(browser.find_element(By.ID, "graph-group")).select_by_index(1)
    wait_for(browser, "document.getElementById('result-context-display').textContent.includes('3 of 3 vertices')")
    assert "selected connection total unavailable" in content(browser, "display")
    assert "Graph display is truncated" in content(browser, "display")


def test_positive_flow_filter_is_not_mislabeled_as_missing_connections(loading_browser, context_server):
    context_server.server.visualization = False
    context_server.output.update(operation="max-flow-min-cut", ports={"flow": {"type": "scalar", "complete": True, "value": 4}},
                                 result={"flows": [{"source": 1, "target": 2, "flow": 4}, {"source": 2, "target": 3, "flow": 0}]})
    browser = loading_browser; open_context(browser, context_server)
    browser.execute_script("const control=document.getElementById('flow-direction'); control.checked=true; control.dispatchEvent(new Event('change', {bubbles:true}));")
    wait_for(browser, "document.getElementById('result-context-display').textContent.includes('1 positive-flow connections loaded')")
    assert "intentionally excluded" in content(browser, "display")
    assert "Graph display is truncated" not in content(browser, "display")


@pytest.mark.parametrize("button,suffix,filename", [
    ("export-csv", "/steps/core/ports/groups/csv", "-table.csv"),
    ("export-report", "/report", ".zip"),
    ("download-result", "/result", ".json"),
])
@pytest.mark.parametrize("status", [200, 409])
def test_downloads_pin_the_displayed_revision_and_report_conflicts(loading_browser, context_server, button, suffix, filename, status):
    browser = loading_browser; open_context(browser, context_server)
    browser.execute_script("""
        const original = window.fetch, suffix = arguments[0];
        window.contextDownloads = []; window.contextExportPath = null;
        HTMLAnchorElement.prototype.click = function () { window.contextDownloads.push(this.download); };
        window.fetch = (input, options) => {
          const url = new URL(input, location.href);
          if (!url.pathname.endsWith(suffix)) return original(input, options);
          window.contextExportPath = url.pathname + url.search;
          return new Promise(resolve => {
            window.finishContextExport = status => resolve(new Response(status === 200 ? '{}' : JSON.stringify({error: {code: 'revision_conflict', message: 'Analysis revision changed.'}}),
              {status, headers: {'Content-Type': 'application/json'}}));
          });
        };
        document.getElementById('result-actions-panel').open = true;
    """, suffix)
    browser.find_element(By.ID, button).click()
    wait_for(browser, "Boolean(window.finishContextExport)")
    assert browser.execute_script("return window.contextExportPath") == f"/api/workflows/saved-analysis{suffix}?expected_revision=1"
    # A later workspace read must not rename the already requested download.
    browser.execute_script("GraphMineWorkspace.state.record = {...GraphMineWorkspace.state.record, id:'another-analysis', revision:2}; window.finishContextExport(arguments[0]);", status)
    wait_for(browser, "!GraphMineWorkspace.state.busy")
    if status == 200:
        assert browser.execute_script("return window.contextDownloads") == [f"graphmine-saved-analysis-revision-1{filename}"]
    else:
        assert browser.execute_script("return window.contextDownloads") == []
        assert "revision changed" in browser.find_element(By.ID, "notice").text


@pytest.mark.parametrize('partial', [False, True])
def test_json_download_keeps_source_bytes_without_browser_reserialization(loading_browser, context_server, partial):
    browser = loading_browser; open_context(browser, context_server)
    raw = '{ "vertex": 9007199254740993, "code": "001", "nested": [null, true], "label": "🐱" }\n'
    browser.execute_script("""
        const original = window.fetch, raw = arguments[0], partial = arguments[1];
        window.contextDownloads = []; window.exportedText = null;
        GraphMineWorkspace.state.result.partial_workflow = partial;
        HTMLAnchorElement.prototype.click = function () { window.contextDownloads.push(this.download); };
        URL.createObjectURL = blob => { blob.text().then(text => window.exportedText = text); return 'blob:recorded'; };
        window.fetch = (input, options) => {
          const url = new URL(input, location.href);
          if (url.pathname !== '/api/workflows/saved-analysis/result') return original(input, options);
          window.contextExportPath = url.pathname + url.search;
          return Promise.resolve(new Response(raw, {headers: {'Content-Type': 'application/json'}}));
        };
        document.getElementById('result-actions-panel').open = true;
    """, raw, partial)
    browser.find_element(By.ID, 'download-result').click()
    wait_for(browser, "window.exportedText !== null && !GraphMineWorkspace.state.busy")
    assert browser.execute_script('return window.exportedText') == raw
    assert browser.execute_script('return window.contextExportPath') == '/api/workflows/saved-analysis/result?expected_revision=1' + ('&partial=true' if partial else '')
    assert browser.execute_script('return window.contextDownloads') == ['graphmine-saved-analysis-revision-1.json']

