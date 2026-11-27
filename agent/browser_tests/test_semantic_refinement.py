"""Snapshot refinement acceptance with real APIs/native mocks and a disposable app."""
import json
import re
from dataclasses import replace

import pytest

from agent.tests.conftest import fake_binary, settings as base_settings  # noqa: F401
from agent.tests.test_admin_browser import browser_app, sign_in, screenshot, pw  # noqa: F401
from agent.tests.test_semantic_native import native_engine  # noqa: F401
from graphmine_agent.database_sources import DatabaseSource
from test_workspace_accessibility import TEXT_AUDIT


@pytest.fixture
def settings(base_settings, tmp_path):
    path = tmp_path / "semantic-sources.json"
    source = DatabaseSource(id="demo", name="Saved reviews", users=["*"], neo4j_uri="bolt://127.0.0.1:17687", neo4j_password_env="SEMANTIC_BROWSER_TEST_PASSWORD")
    path.write_text(json.dumps([source.model_dump()]))
    path.chmod(0o600)
    return replace(base_settings, database_sources_file=path)


@pytest.fixture
def semantic_page(browser_app, monkeypatch):
    browser, base, _, accounts = browser_app
    graph = {"graph": {"id": "reviews", "directed": True, "allows_self_loops": False, "allows_parallel_edges": True},
             "vertices": [{"id": 1, "type": "Review", "attributes": {"text": "alpha", "neo4j_labels": ["Review", "Item"]}},
                          {"id": "1", "type": "Review", "attributes": {"text": "beta", "neo4j_labels": ["Review"]}}],
             "edges": [{"id": "r", "source": 1, "target": "1", "type": "LINK", "attributes": {"weight": 2}}]}
    calls = []
    def execute(*args, **kwargs):
        calls.append(1)
        return graph, {"vertices": {}, "edges": {}}, [], 2, None
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute)
    page = browser.new_page(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    sign_in(page, base, "review-admin")
    created = page.request.post(base + "/api/database-sources/demo/queries", data={"statement": "MATCH p=()-[]->() RETURN p"}, headers={"X-GraphMine-Request": "1"})
    assert created.status == 201, created.text()
    snapshot = created.json()
    page.goto(base + "/")
    page.wait_for_function("() => window.GraphMineWorkspace?.state.domains.length && !GraphMineWorkspace.state.busy")
    yield page, base, snapshot, calls, errors
    assert errors == []
    page.close()


def open_refinement(page, snapshot, recorded=None):
    page.evaluate("d => document.dispatchEvent(new CustomEvent('graphmine:refine-snapshot', {detail:d}))", {"baseId": snapshot["dataset"]["id"], "recorded": recorded})
    pw.expect(page.locator("#semantic-run")).to_be_enabled()


def run_result(page):
    with page.expect_response(re.compile(r"/api/database-jobs/[^/]+/result$"), timeout=30000) as response:
        page.locator("#semantic-run").click()
    value = response.value
    assert value.ok, value.text()
    pw.expect(page.locator("#semantic-use")).to_be_visible()
    pw.expect(page.locator("#semantic-run")).to_be_enabled()
    return value.json()


def test_preview_refine_save_attach_and_immutable_parent(semantic_page, native_engine):
    page, base, snapshot, calls, _ = semantic_page
    source = {"id": "demo", "name": "Saved reviews", "entities": [], "relationships": [], "capabilities": {"sync": False}, "connection": {"neo4j": {}}}
    page.route("**/api/data-sources", lambda route: route.fulfill(json={"items": [{"provider": "database", "connection": source}], "warnings": [], "active_backend": "local"}))
    page.route("**/api/database-sources/demo/datasets", lambda route: route.fulfill(json=[{"id": "default", "name": "Reviews", "status": "ready", "default_query": "MATCH (n) RETURN n", "schemas": [], "tables": []}]))
    page.route("**/api/database-sources/demo/status", lambda route: route.fulfill(json={"connected": True, "neo4j": {"connected": True}}))
    page.route("**/api/database-sources/demo/schema?*", lambda route: route.fulfill(json={"entities": [], "relationships": []}))
    page.route("**/api/database-sources/demo/queries", lambda route: route.fulfill(json=snapshot))
    page.locator("#open-database-workspace").click()
    pw.expect(page.locator("#preview-cypher")).to_be_enabled()
    page.locator("#preview-cypher").click()
    page.locator("#refine-query-snapshot").click()
    pw.expect(page.locator("#semantic-run")).to_be_enabled()
    pw.expect(page.locator("#semantic-schema")).to_contain_text("Item, Review")
    page.locator("#semantic-template").select_option("extract")
    page.locator("#semantic-insert-template").click()
    page.locator("#semantic-direction").select_option("undirected")
    page.locator("#semantic-check").click()
    pw.expect(page.locator("#semantic-steps")).to_contain_text("answer STRING")
    result = run_result(page)
    assert result["dataset"]["id"] != snapshot["dataset"]["id"]
    assert result["dataset"]["source"]["base_sha256"] == snapshot["dataset"]["sha256"]
    assert result["graph"]["graph"]["directed"] is False
    assert result["dataset"]["source"]["simulation"] is True
    assert len(calls) == 1  # No implicit source refresh during semantic work.
    pw.expect(page.locator("#semantic-output")).to_contain_text("simulated model judgments")
    page.locator("#semantic-save").click()
    pw.expect(page.locator("#semantic-save")).to_be_disabled()
    screenshot(page, "refinement-desktop")
    page.get_by_role("button", name="Run again without saved answers", exact=True).click()
    pw.expect(page.locator("#semantic-direction")).to_have_value("undirected")
    pw.expect(page.locator("#semantic-reuse")).not_to_be_checked()
    rerun = run_result(page)
    assert rerun["dataset"]["id"] != result["dataset"]["id"]
    with page.expect_response(re.compile(r"/api/database-query-snapshots/[^/]+/chat$")) as attached:
        page.locator("#semantic-use").click()
    attachment = attached.value.json()
    pw.expect(page.locator("#semantic-refinement")).to_have_count(0)
    page.wait_for_function("id => GraphMineWorkspace.state.session?.id === id", arg=attachment["session"]["id"])
    assert attachment["file"]["provenance"]["source"]["base_version_id"] == snapshot["dataset"]["id"]
    before = page.request.get(base + f"/api/database-query-snapshots/{snapshot['dataset']['id']}/semantic-schema").json()
    assert before["sha256"] == snapshot["dataset"]["sha256"]


def test_drafts_invalidation_table_and_mobile_keyboard(semantic_page, native_engine):
    page, _, snapshot, _, _ = semantic_page
    page.set_viewport_size({"width": 390, "height": 844})
    open_refinement(page, snapshot)
    page.locator("#semantic-editor").fill("MATCH (n:Vertex) WHERE n.text=$text RETURN n")
    page.locator("#semantic-parameters").evaluate("el => {el.value = '{\"text\":\"alpha\"}'; el.dispatchEvent(new Event('input'));}")
    page.keyboard.press("Escape")
    pw.expect(page.locator("#semantic-refinement")).to_have_count(0)
    open_refinement(page, snapshot)
    pw.expect(page.locator("#semantic-editor")).to_have_value("MATCH (n:Vertex) WHERE n.text=$text RETURN n")
    page.locator("#semantic-editor").press("Control+Enter")
    pw.expect(page.locator("#semantic-use")).to_be_visible(timeout=30000)
    screenshot(page, "refinement-mobile")
    assert page.locator("#semantic-refinement").evaluate("el => el.scrollWidth <= el.clientWidth + 1")
    issues = page.evaluate("() => {" + TEXT_AUDIT.replace("body *", "#semantic-refinement *") + "}")
    assert all(issue["contrast"] >= 4.5 for issue in issues), issues
    page.locator("#close-semantic").focus()
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("() => Boolean(document.activeElement.closest('#semantic-refinement'))")
    page.locator("#semantic-parameters").evaluate("el => {el.closest('details').open = true;}")
    page.get_by_label("Type for $text", exact=True).select_option("number")
    pw.expect(page.locator("#semantic-use")).to_have_count(0)
    page.get_by_label("Type for $text", exact=True).select_option("text")
    page.locator("#semantic-editor").fill("MATCH (n:Vertex) RETURN graph_id(n) AS id, n.text AS text")
    pw.expect(page.locator("#semantic-use")).to_have_count(0)
    result = run_result(page)
    assert result["table"]["table"]["row_count"] == 2
    pw.expect(page.get_by_role("region", name="Complete query table")).to_contain_text("alpha")
    page.locator("#semantic-discard").click()
    pw.expect(page.locator("#semantic-output")).to_be_hidden()


@pytest.mark.parametrize("code", ["semantic_call_limit", "semantic_timeout", "semantic_syntax", "semantic_worker_failed", "semantic_model_server", "database_cancelled"])
def test_failure_usage_and_syntax_navigation(semantic_page, code):
    page, _, snapshot, _, _ = semantic_page
    open_refinement(page, snapshot)
    page.route("**/api/semantic-queries", lambda route: route.fulfill(status=202, json={"job": {"id": "failure", "kind": "semantic", "status": "queued", "cancellable": True}}))
    page.route("**/api/database-jobs/failure", lambda route: route.fulfill(json={"id": "failure", "kind": "semantic", "status": "cancelled" if code == "database_cancelled" else "failed", "cancellable": False,
        "error": {"code": code, "message": "Controlled failure", "details": {"line": 2, "column": 2, "usage": {"calls": 3, "llm_rows": 7}}}}))
    page.locator("#semantic-run").click()
    pw.expect(page.locator("#semantic-status")).to_contain_text("Controlled failure")
    pw.expect(page.locator(".semantic-progress")).to_contain_text("Engine calls observed: 3")
    pw.expect(page.locator(".semantic-progress")).to_contain_text("No new graph was published")
    pw.expect(page.locator("#semantic-use")).to_have_count(0)
    if code == "semantic_syntax":
        page.locator("#semantic-goto-query-error").click()
        assert page.locator("#semantic-editor").evaluate("el => el.selectionStart") == len("MATCH (n:Vertex)\n") + 1


def test_cancel_and_ignore_late_result_after_close(semantic_page):
    page, _, snapshot, _, _ = semantic_page
    open_refinement(page, snapshot)
    cancelled = []
    page.route("**/api/semantic-queries", lambda route: route.fulfill(status=202, json={"job": {"id": "waiting", "kind": "semantic", "status": "running", "cancellable": True}}))
    def job(route):
        if route.request.method == "DELETE": cancelled.append(True)
        route.fulfill(json={"id": "waiting", "kind": "semantic", "status": "cancelled" if cancelled else "running", "cancellable": not cancelled, "progress": {"stage": "asking_model", "usage": {"calls": 2}}})
    page.route("**/api/database-jobs/waiting", job)
    page.locator("#semantic-run").click()
    pw.expect(page.locator(".semantic-progress")).to_contain_text("Running simulated model steps")
    page.locator("#semantic-cancel-database-job").click()
    pw.expect(page.locator("#semantic-run")).to_be_enabled()
    assert cancelled
    cancelled.clear()
    page.locator("#semantic-run").click()
    pw.expect(page.locator("#semantic-cancel-database-job")).to_be_visible()
    page.locator("#close-semantic").click()
    open_refinement(page, snapshot)
    pw.expect(page.locator("#semantic-output")).to_be_hidden()
    pw.expect(page.locator("#semantic-run")).to_be_enabled()


def test_late_submission_cannot_replace_reopened_snapshot(semantic_page):
    page, _, snapshot, _, _ = semantic_page
    open_refinement(page, snapshot)
    page.evaluate("""() => {
      const original = window.fetch;
      window.fetch = (path, options) => String(path).endsWith('/api/semantic-queries')
        ? new Promise(resolve => { window.finishLateRefinement = value => resolve(new Response(JSON.stringify(value), {headers: {'Content-Type': 'application/json'}})); })
        : original(path, options);
    }""")
    page.locator("#semantic-run").click()
    page.wait_for_function("() => Boolean(window.finishLateRefinement)")
    page.locator("#close-semantic").click()
    open_refinement(page, snapshot)
    page.locator("#semantic-editor").fill("MATCH (n:Vertex) RETURN n LIMIT 1")
    page.evaluate("value => window.finishLateRefinement(value)", snapshot)
    # Synchronize through the browser's request/microtask boundary.
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(resolve))")
    pw.expect(page.locator("#semantic-editor")).to_have_value("MATCH (n:Vertex) RETURN n LIMIT 1")
    pw.expect(page.locator("#semantic-output")).to_be_hidden()
    pw.expect(page.locator("#semantic-run")).to_be_enabled()


def test_refinement_drafts_are_scoped_to_snapshot(semantic_page):
    page, base, first, _, _ = semantic_page
    created = page.request.post(base + "/api/database-sources/demo/queries", data={"statement": "MATCH (n) RETURN n"}, headers={"X-GraphMine-Request": "1"})
    assert created.status == 201
    second = created.json()
    open_refinement(page, first)
    page.locator("#semantic-editor").fill("MATCH (n:Vertex) RETURN n LIMIT 1")
    open_refinement(page, second)
    pw.expect(page.locator("#semantic-editor")).to_have_value("MATCH (n:Vertex)\nRETURN n")
    open_refinement(page, first)
    pw.expect(page.locator("#semantic-editor")).to_have_value("MATCH (n:Vertex) RETURN n LIMIT 1")


def test_member_capabilities_and_plain_read_access(semantic_page, native_engine):
    page, base, _, _, _ = semantic_page
    sign_in(page, base, "review-member")
    created = page.request.post(base + "/api/database-sources/demo/queries", data={"statement": "MATCH (n) RETURN n"}, headers={"X-GraphMine-Request": "1"})
    assert created.status == 201, created.text()
    snapshot = created.json()
    page.reload()
    page.wait_for_function("() => window.GraphMineWorkspace?.state.domains.length && !GraphMineWorkspace.state.busy")
    open_refinement(page, snapshot)
    assert page.locator('#semantic-model option[value="mock"]').is_disabled()
    assert page.locator("#semantic-template option").count() == 1
    page.locator("#semantic-editor").fill("MATCH (n:Vertex) RETURN n, llm('mock', 'Describe {answer STRING}') AS answer")
    page.locator("#semantic-check").click()
    pw.expect(page.locator("#semantic-status")).to_contain_text("cannot run semantic model steps")
    page.locator("#semantic-editor").fill("MATCH (n:Vertex) RETURN n")
    assert run_result(page)["vertex_count"] == 2
